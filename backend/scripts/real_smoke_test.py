#!/usr/bin/env python3
"""Reproducible real Sentinel-2 L2A smoke test using the configured provider.

This script is NOT run as part of the default pytest suite. It requires network
access to Element84 Earth Search and will fail clearly if unavailable.
"""
import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import NoImageryError, SatQueryError
from app.satellite.provider import EarthSearchProvider
from app.services import analysis
from app.llm.explainer import make_llm_fn
from app.llm.client import get_llm_client


AOIS = [
    {
        "name": "delhi",
        "aoi": {"type": "Polygon", "coordinates": [[[77.1, 28.5], [77.3, 28.5], [77.3, 28.7], [77.1, 28.7], [77.1, 28.5]]]},
    },
    {
        "name": "mumbai",
        "aoi": {"type": "Polygon", "coordinates": [[[72.8, 19.0], [73.0, 19.0], [73.0, 19.2], [72.8, 19.2], [72.8, 19.0]]]},
    },
    {
        "name": "bengaluru",
        "aoi": {"type": "Polygon", "coordinates": [[[77.5, 12.9], [77.7, 12.9], [77.7, 13.1], [77.5, 13.1], [77.5, 12.9]]]},
    },
]


def run(diagnostic_only=False, max_cloud=30, days_back=90, aoi_filter=None):
    report_dir = Path(__file__).resolve().parents[2] / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"real_smoke_{date.today().isoformat()}.md"

    provider = EarthSearchProvider()
    llm_fn = make_llm_fn(get_llm_client())
    results = []
    errors = []
    stages = []

    end = date.today()
    start = end - timedelta(days=days_back)

    if aoi_filter:
        aois_to_run = [a for a in AOIS if a["name"] == aoi_filter]
        if not aois_to_run:
            print(f"[SMOKE] No AOI named {aoi_filter}")
            return False
    else:
        aois_to_run = AOIS[:1] if diagnostic_only else AOIS
    print(f"[SMOKE] Starting diagnostic_only={diagnostic_only}, aoi_filter={aoi_filter}, aois={[a['name'] for a in aois_to_run]}, max_cloud={max_cloud}, days_back={days_back}")

    for item in aois_to_run:
        name = item["name"]
        aoi = item["aoi"]
        t0 = time.time()
        try:
            print(f"[SMOKE] [{name}] STAC search start...")
            t_s = time.time()
            scenes = provider.list_scenes(aoi, start, end, max_cloud)
            t_s_end = time.time()
            stages.append(f"{name}:stac_search:{t_s_end-t_s:.2f}s")
            print(f"[SMOKE] [{name}] STAC search done in {t_s_end-t_s:.2f}s, scenes={len(scenes)}")
            if not scenes:
                errors.append(f"{name}:cloud_filter:no scenes found (max_cloud={max_cloud}, {start}..{end})")
                continue
            scene = scenes[0]
            print(f"[SMOKE] [{name}] Using scene {scene['item_id']} {scene['datetime']} cloud={scene.get('cloud_cover')}")
            rng = type("R", (), {"start": start, "end": end})()
            print(f"[SMOKE] [{name}] Analysis start (index_stats NDVI)...")
            t_a = time.time()
            res = analysis.run_index_stats(provider, aoi, rng, index="NDVI", max_cloud=max_cloud, llm_fn=llm_fn)
            t_a_end = time.time()
            stages.append(f"{name}:analysis:{t_a_end-t_a:.2f}s")
            print(f"[SMOKE] [{name}] Analysis done in {t_a_end-t_a:.2f}s")
            facts = res.get("facts", {})
            evidence = res.get("evidence", {})
            stats = facts.get("stats") or evidence.get("metrics") or {}
            results.append({
                "aoi": name,
                "scene": scene["item_id"],
                "datetime": scene["datetime"],
                "cloud_cover": scene.get("cloud_cover"),
                "ndvi_stats": stats,
                "valid_pixel_fraction": evidence.get("valid_pixel_fraction"),
                "crs": evidence.get("scenes", [{}])[0].get("crs") if evidence.get("scenes") else None,
                "duration_s": round(time.time() - t0, 2),
            })
        except NoImageryError as e:
            errors.append(f"{name}:network/no_imagery:{e}")
            continue
        except SatQueryError as e:
            errors.append(f"{name}:processing/satquery:{e.code}:{e.message}")
            continue
        except Exception as e:
            errors.append(f"{name}:unknown:{type(e).__name__}:{e}")
            continue

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# SatQuery AI — Real Sentinel-2 Smoke Test Report\n\n")
        f.write(f"Date: {date.today().isoformat()}\n")
        f.write(f"Diagnostic only: {diagnostic_only}\n")
        f.write(f"Max cloud: {max_cloud}, Days back: {days_back}\n\n")
        f.write("## Stage timings\n\n")
        for s in stages:
            f.write(f"- {s}\n")
        f.write("\n## Results\n\n")
        if results:
            for r in results:
                f.write(f"### {r['aoi']}\n")
                f.write(f"- Scene: {r['scene']}\n")
                f.write(f"- Date: {r['datetime']}\n")
                f.write(f"- Cloud: {r['cloud_cover']}\n")
                f.write(f"- Valid pixel fraction: {r['valid_pixel_fraction']}\n")
                f.write(f"- CRS: {r['crs']}\n")
                f.write(f"- Duration: {r['duration_s']}s\n")
                f.write(f"- NDVI stats: {json.dumps(r['ndvi_stats'])}\n\n")
        else:
            f.write("No successful results.\n\n")
        f.write("## Errors / Limitations\n\n")
        if errors:
            for e in errors:
                f.write(f"- {e}\n")
        else:
            f.write("- None\n")

    print(f"[SMOKE] Report written to {report_path}")
    print(f"[SMOKE] Results: {len(results)}, Errors: {len(errors)}")
    return len(results) > 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="Run all three AOIs (default is diagnostic: 1 AOI)")
    ap.add_argument("--max-cloud", type=float, default=30.0)
    ap.add_argument("--days-back", type=int, default=90)
    ap.add_argument("--aoi", type=str, default=None, help="Run only specific AOI (delhi/mumbai/bengaluru)")
    args = ap.parse_args()
    ok = run(diagnostic_only=not args.full and args.aoi is None, max_cloud=args.max_cloud, days_back=args.days_back, aoi_filter=args.aoi)
    sys.exit(0 if ok else 1)



if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
