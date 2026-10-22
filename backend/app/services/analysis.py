"""Orchestrator: structured query -> data -> deterministic compute -> evidence -> grounded answer."""
from datetime import date, datetime
from typing import Callable, Optional

import numpy as np

from app.change_detection.change import detect_change
from app.core.config import DEFAULT_CHANGE_THRESHOLDS, settings
from app.core.errors import InsufficientValidPixelsError, NoImageryError
from app.evidence.confidence import compute_confidence
from app.indices.spectral import INDEX_REGISTRY, compute_index, index_stats
from app.preprocessing.masking import build_valid_mask, pixel_area_m2
from app.satellite.provider import SatelliteProvider, SceneData
from app.schemas.evidence import Evidence, SceneRef
from app.schemas.query import DateRange
from app.statistics.trend import analyse_series
from app.validation.grounding import grounded_answer

VEG_THRESHOLD = 0.3  # NDVI >= 0.3 counted as vegetated (shown in methodology)


def _prepare(scene: SceneData, index: str):
    spec = INDEX_REGISTRY[index]
    used = [scene.bands[b] for b in spec.bands]
    valid = build_valid_mask(scene.scl, scene.inside_aoi, used)
    arr = compute_index(index, scene.bands, valid)
    n_aoi = int(scene.inside_aoi.sum())
    return arr, valid, n_aoi


def _scene_ref(sc: SceneData) -> SceneRef:
    return SceneRef(item_id=sc.item_id, datetime=sc.datetime, cloud_cover=sc.cloud_cover,
                    resolution_m=sc.resolution_m, crs=sc.crs)


def _days_between(a: str, b: str) -> float:
    pa, pb = datetime.fromisoformat(a.replace("Z", "+00:00")), datetime.fromisoformat(b.replace("Z", "+00:00"))
    return abs((pb - pa).total_seconds()) / 86400.0


def _bands_for(index: str) -> list:
    return list(INDEX_REGISTRY[index].bands)


def run_index_stats(provider: SatelliteProvider, aoi: dict, rng: DateRange, index: str = "NDVI",
                    max_cloud: float = settings.max_scene_cloud_cover, llm_fn: Optional[Callable] = None) -> dict:
    index = index.upper()
    meta = provider.best_scene(aoi, rng.start, rng.end, max_cloud)
    sc = provider.get_scene(aoi, meta["item_id"], _bands_for(index))
    arr, valid, n_aoi = _prepare(sc, index)
    stats = index_stats(arr, vegetation_threshold=VEG_THRESHOLD if index == "NDVI" else None, denominator=n_aoi)
    if stats["valid_fraction"] < settings.min_valid_fraction:
        raise InsufficientValidPixelsError(
            f"Only {stats['valid_fraction']:.1%} of AOI pixels are valid after masking.")
    px = pixel_area_m2(sc.transform)
    conf = compute_confidence(valid_fraction=stats["valid_fraction"], cloud_cover_pct=sc.cloud_cover)
    spec = INDEX_REGISTRY[index]
    ev = Evidence(operation="index_stats", scenes=[_scene_ref(sc)], aoi_area_km2=n_aoi * px / 1e6,
                  index=index, formula=spec.formula, bands=spec.sentinel2_bands, preprocessing=sc.preprocessing,
                  thresholds={"vegetation_ndvi": VEG_THRESHOLD} if index == "NDVI" else {},
                  valid_pixel_fraction=stats["valid_fraction"], metrics=stats)
    facts = {"operation": "index_stats", "index": index, "date": sc.datetime[:10], "stats": stats,
             "data_quality_score": conf["score"]}
    return {"evidence": ev.model_dump(), "confidence": conf, "facts": facts,
            "answer": grounded_answer(facts, llm_fn), "arrays": {"index": arr, "valid": valid},
            "raster": {"transform": sc.transform, "crs": sc.crs}}


def run_change(provider: SatelliteProvider, aoi: dict, range_a: DateRange, range_b: DateRange,
               index: str = "NDVI", thresholds: Optional[dict] = None,
               max_cloud: float = settings.max_scene_cloud_cover, llm_fn: Optional[Callable] = None) -> dict:
    index = index.upper()
    ma = provider.best_scene(aoi, range_a.start, range_a.end, max_cloud)
    mb = provider.best_scene(aoi, range_b.start, range_b.end, max_cloud)
    bands = _bands_for(index)
    sa, sb = provider.get_scene(aoi, ma["item_id"], bands), provider.get_scene(aoi, mb["item_id"], bands)
    if sa.transform != sb.transform or sa.crs != sb.crs or sa.inside_aoi.shape != sb.inside_aoi.shape:
        raise NoImageryError("The two scenes are on different pixel grids (different tiles/orbits); "
                             "pick dates from the same tile.")
    arr_a, _, n_aoi = _prepare(sa, index)
    arr_b, _, _ = _prepare(sb, index)
    px = pixel_area_m2(sa.transform)
    res = detect_change(arr_a, arr_b, px, thresholds, inside_aoi=sa.inside_aoi,
                        transform=sa.transform, crs=sa.crs)

    gap = _days_between(sa.datetime, sb.datetime)
    cloud = float(np.mean([c for c in (sa.cloud_cover, sb.cloud_cover) if c is not None])) \
        if any(c is not None for c in (sa.cloud_cover, sb.cloud_cover)) else None
    conf = compute_confidence(valid_fraction=res["both_valid_fraction"], cloud_cover_pct=cloud, temporal_gap_days=gap)
    spec = INDEX_REGISTRY[index]
    metrics = {k: v for k, v in res.items() if k not in ("diff", "class_map")}
    ev = Evidence(operation="change_detection", scenes=[_scene_ref(sa), _scene_ref(sb)],
                  aoi_area_km2=n_aoi * px / 1e6, index=index, formula=spec.formula, bands=spec.sentinel2_bands,
                  preprocessing=sa.preprocessing + ["Pixels used only where valid on BOTH dates"],
                  thresholds=res["thresholds"], valid_pixel_fraction=res["both_valid_fraction"], metrics=metrics)
    facts = {"operation": "change_detection", "index": index, "date_a": sa.datetime[:10], "date_b": sb.datetime[:10],
             "change": {k: res[k] for k in ("mean_a", "mean_b", "mean_change", "percent_change_of_mean", "classes")},
             "analysed_area_km2": res["analysed_area_km2"], "data_quality_score": conf["score"]}
    return {"evidence": ev.model_dump(), "confidence": conf, "facts": facts,
            "answer": grounded_answer(facts, llm_fn),
            "arrays": {"index_a": arr_a, "index_b": arr_b, "diff": res["diff"],
                       "class_map": res["class_map"], "hotspots": res["hotspot_map"]},
            "hotspots": res["hotspots"], "raster": {"transform": sa.transform, "crs": sa.crs}}


def run_time_series(provider: SatelliteProvider, aoi: dict, rng: DateRange, index: str = "NDVI",
                    max_cloud: float = settings.max_scene_cloud_cover, max_scenes: int = 60,
                    llm_fn: Optional[Callable] = None) -> dict:
    index = index.upper()
    listed = provider.list_scenes(aoi, rng.start, rng.end, max_cloud)[:max_scenes]
    if not listed:
        raise NoImageryError(f"No scenes between {rng.start} and {rng.end} with cloud cover <= {max_cloud:.0f}%.")
    pts, vfracs, clouds, refs, px, n_aoi = [], [], [], [], None, 0
    for m in listed:
        sc = provider.get_scene(aoi, m["item_id"], _bands_for(index))
        arr, _, n_aoi = _prepare(sc, index)
        st = index_stats(arr, denominator=n_aoi)
        if st["valid_fraction"] < settings.min_valid_fraction:
            continue
        px = pixel_area_m2(sc.transform)
        pts.append((sc.datetime, st["median"]))
        vfracs.append(st["valid_fraction"])
        if sc.cloud_cover is not None:
            clouds.append(sc.cloud_cover)
        refs.append(_scene_ref(sc))
    if not pts:
        raise InsufficientValidPixelsError("No date had enough valid pixels after masking.")
    t0 = datetime.fromisoformat(pts[0][0].replace("Z", "+00:00"))
    days = [(datetime.fromisoformat(d.replace("Z", "+00:00")) - t0).total_seconds() / 86400 for d, _ in pts]
    vals = [v for _, v in pts]
    series = analyse_series(days, vals)
    series["dates"] = [d[:10] for d, _ in pts]
    series["values"] = vals
    tt = series["trend_test"]
    conf = compute_confidence(valid_fraction=float(np.mean(vfracs)),
                              cloud_cover_pct=float(np.mean(clouds)) if clouds else None,
                              n_dates_used=len(pts), n_dates_requested=len(listed),
                              trend_significant=tt["significant"] if tt else None, trend_n=len(pts))
    spec = INDEX_REGISTRY[index]
    ev = Evidence(operation="time_series", scenes=refs, aoi_area_km2=n_aoi * px / 1e6, index=index,
                  formula=spec.formula, bands=spec.sentinel2_bands,
                  preprocessing=["Per-date AOI median of valid pixels", f"Dates with <{settings.min_valid_fraction:.0%} valid pixels skipped"],
                  thresholds={"min_dates_for_trend": settings.min_dates_for_trend},
                  valid_pixel_fraction=float(np.mean(vfracs)), metrics=series)
    facts = {"operation": "time_series", "index": index, "series": series, "data_quality_score": conf["score"]}
    return {"evidence": ev.model_dump(), "confidence": conf, "facts": facts, "answer": grounded_answer(facts, llm_fn)}
