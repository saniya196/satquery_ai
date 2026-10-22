"""One real Sentinel-2 round trip: search -> download -> mask -> indices -> (optional) land cover.

Run from backend/ on a machine where rasterio works (e.g. GitHub Codespaces):
    python scripts/live_check.py
    python scripts/live_check.py --bbox 80.60 16.49 80.64 16.53 --start 2026-01-01 --end 2026-10-01
Prints what it found and PASS/WARN lines. Paste the whole output back for review.
"""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.indices.spectral import compute_index, index_stats  # noqa: E402
from app.preprocessing.masking import build_valid_mask, pixel_area_m2  # noqa: E402
from app.satellite.provider import EarthSearchProvider  # noqa: E402

BANDS = ["blue", "green", "red", "nir", "swir1"]


def bbox_polygon(minlon, minlat, maxlon, maxlat):
    return {"type": "Polygon", "coordinates": [[[minlon, minlat], [maxlon, minlat], [maxlon, maxlat],
                                                [minlon, maxlat], [minlon, minlat]]]}


def run(provider, aoi, start, end, max_cloud, classify=True, out=print):
    notes = []
    t = time.time()
    scenes = provider.list_scenes(aoi, start, end, max_cloud)
    out(f"STAC search: {len(scenes)} scenes with cloud <= {max_cloud:.0f}%  ({time.time() - t:.1f}s)")
    if not scenes:
        out("WARN no scenes found: widen the dates or raise --max-cloud")
        return 1
    for s in scenes[:5]:
        out(f"   {s['datetime'][:10]}  cloud {s['cloud_cover']}  {s['item_id']}")
    best = min(scenes, key=lambda s: s["cloud_cover"] if s["cloud_cover"] is not None else 100)
    out(f"using least cloudy: {best['item_id']} ({best['datetime'][:10]}, cloud {best['cloud_cover']})")

    items = getattr(provider, "_items", {})
    if best["item_id"] in items:
        for key in ("red", "nir", "swir16", "scl"):
            a = items[best["item_id"]].assets.get(key)
            out(f"   asset '{key}' raster:bands = {a.extra_fields.get('raster:bands') if a else 'MISSING'}")

    t = time.time()
    sc = provider.get_scene(aoi, best["item_id"], BANDS)
    t1 = time.time() - t
    t = time.time()
    provider.get_scene(aoi, best["item_id"], BANDS)
    out(f"download+read {t1:.1f}s, second call (cache) {time.time() - t:.1f}s")
    px = pixel_area_m2(sc.transform)
    n_aoi = int(sc.inside_aoi.sum())
    out(f"grid {sc.scl.shape}  crs {sc.crs}  pixel {px ** 0.5:.1f} m  AOI {n_aoi} px = {n_aoi * px / 1e6:.2f} km2")
    vals, cnt = np.unique(sc.scl[sc.inside_aoi], return_counts=True)
    out("SCL classes in AOI: " + ", ".join(f"{int(v)}:{c / n_aoi:.1%}" for v, c in zip(vals, cnt)))

    bands = [sc.bands[b] for b in BANDS]
    valid = build_valid_mask(sc.scl, sc.inside_aoi, bands)
    vf = valid.sum() / n_aoi
    out(f"valid pixels: {vf:.1%}")
    ok = True
    for b in BANDS:
        v = sc.bands[b][valid]
        if v.size == 0:
            continue
        p1, p50, p99 = np.percentile(v, [1, 50, 99])
        out(f"   {b:6s} reflectance p1 {p1:7.4f}  median {p50:7.4f}  p99 {p99:7.4f}")
        if p1 < -0.05 or p99 > 1.2:
            ok = False
            notes.append(f"WARN {b}: reflectance outside plausible range -> check scale/offset handling in provider.py")
    for name in ("NDVI", "NDWI", "NDBI"):
        s = index_stats(compute_index(name, sc.bands, valid), denominator=n_aoi)
        out(f"   {name}: mean {s['mean']:.3f}  median {s['median']:.3f}  min {s['min']:.3f}  max {s['max']:.3f}")
    if vf < 0.3:
        notes.append("WARN valid fraction below 30%: pick a clearer date")
    if ok:
        out("PASS reflectance values look physically plausible")

    if classify:
        try:
            from app.classification.loader import get_classifier
            from app.schemas.query import DateRange
            from app.services.land_cover import run_land_cover
            r = run_land_cover(provider, aoi, DateRange(start=start, end=end), get_classifier(), max_cloud)
            out("land cover (model output, NOT ground truth):")
            for k, v in r["distribution"]["classes"].items():
                out(f"   {k:18s} {v['fraction'] * 100:5.1f}%  {v['area_km2']:.3f} km2")
            out(f"   tiles classified {r['evidence']['metrics']['n_tiles_classified']}, "
                f"mean model confidence {r['facts']['mean_model_confidence']:.1%}")
            out("   answer: " + r["answer"]["text"])
        except Exception as exc:  # report, never hide
            notes.append(f"WARN land cover step failed: {type(exc).__name__}: {exc}")
    for n in notes:
        out(n)
    return 0 if not notes else 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, default=[80.60, 16.49, 80.64, 16.53],
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ap.add_argument("--start", type=date.fromisoformat, default=date(2026, 1, 1))
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    ap.add_argument("--max-cloud", type=float, default=40.0)
    ap.add_argument("--no-classify", action="store_true")
    a = ap.parse_args()
    sys.exit(run(EarthSearchProvider(cache_dir=".cache/live_check"), bbox_polygon(*a.bbox), a.start, a.end,
                 a.max_cloud, classify=not a.no_classify))
