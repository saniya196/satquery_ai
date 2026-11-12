"""Orchestrator: structured query -> data -> deterministic compute -> evidence -> grounded answer."""
from datetime import date, datetime, timezone
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
                    resolution_m=sc.resolution_m, crs=sc.crs,
                    provider=getattr(sc, "provider", None), collection=getattr(sc, "collection", None),
                    platform=getattr(sc, "platform", None),
                    processing_level=getattr(sc, "processing_level", None),
                    coverage_fraction=getattr(sc, "coverage_fraction", None),
                    source=getattr(sc, "source", None), sensor=getattr(sc, "sensor", None),
                    sensor_identity=getattr(sc, "sensor_identity", "unknown"))


def _days_between(a: str, b: str) -> float:
    pa, pb = datetime.fromisoformat(a.replace("Z", "+00:00")), datetime.fromisoformat(b.replace("Z", "+00:00"))
    return abs((pb - pa).total_seconds()) / 86400.0


def _bands_for(index: str) -> list:
    return list(INDEX_REGISTRY[index].bands)


def run_index_stats(provider: SatelliteProvider, aoi: dict, rng: DateRange, index: str = "NDVI",
                    max_cloud: float = settings.max_scene_cloud_cover, llm_fn: Optional[Callable] = None,
                    selected_scene_id: Optional[str] = None,
                    compare_utc_date: bool = False) -> dict:
    index = index.upper()
    if selected_scene_id:
        sc = provider.get_selected_scene(aoi, selected_scene_id, _bands_for(index), rng.start, rng.end,
                                         max_cloud, use_utc_calendar_date=compare_utc_date)
        meta = {"coverage": sc.coverage_fraction, "coverage_fraction": sc.coverage_fraction, "coverage_status": "full"}
    else:
        meta = provider.best_scene(aoi, rng.start, rng.end, max_cloud)
        sc = provider.get_scene(aoi, meta["item_id"], _bands_for(index))
    arr, valid, n_aoi = _prepare(sc, index)
    stats = index_stats(arr, vegetation_threshold=VEG_THRESHOLD if index == "NDVI" else None, denominator=n_aoi)
    if stats["valid_fraction"] < settings.min_valid_fraction:
        raise InsufficientValidPixelsError(
            f"Only {stats['valid_fraction']:.1%} of AOI pixels are valid after masking.")
    # Add explicit denominator labels for transparency (backward compatible)
    stats["valid_fraction_of_aoi"] = stats["valid_fraction"]
    stats["n_aoi_pixels"] = n_aoi
    px = pixel_area_m2(sc.transform)
    conf = compute_confidence(valid_fraction=stats["valid_fraction"], cloud_cover_pct=sc.cloud_cover)
    spec = INDEX_REGISTRY[index]
    cov_info = None
    if meta.get("coverage_fraction") is not None or meta.get("coverage") is not None or meta.get("coverage_status") is not None:
        cov_info = {
            "status": meta.get("coverage_status", "full" if (meta.get("coverage_fraction") or meta.get("coverage") or 0) >= 0.99 else "unknown"),
            "fraction": meta.get("coverage_fraction") if meta.get("coverage_fraction") is not None else meta.get("coverage"),
        }
    ev = Evidence(operation="index_stats", scenes=[_scene_ref(sc)], aoi_area_km2=n_aoi * px / 1e6,
                  index=index, formula=spec.formula, bands=spec.sentinel2_bands, preprocessing=sc.preprocessing,
                  thresholds={"vegetation_ndvi": VEG_THRESHOLD} if index == "NDVI" else {},
                  valid_pixel_fraction=stats["valid_fraction"], metrics=stats, coverage=cov_info)
    ev_dict = ev.model_dump()
    if ev.coverage is None:
        ev_dict.pop("coverage", None)
    if cov_info is not None:
        ev_dict["metrics"]["coverage"] = cov_info
    facts = {"operation": "index_stats", "index": index, "date": sc.datetime[:10], "stats": stats,
             "analysed_area_km2": n_aoi * px / 1e6, "coverage": cov_info,
             "provenance": {"scene_ids": [sc.item_id], "provider": getattr(sc, "provider", None),
                            "collection": getattr(sc, "collection", None), "cloud_cover": sc.cloud_cover},
             "data_quality_score": conf["score"]}
    if index == "NDVI":
        facts["thresholds"] = {"vegetation_ndvi": VEG_THRESHOLD}
        facts["spatial_evidence_available"] = True
    res = {"evidence": ev_dict, "confidence": conf, "facts": facts,
           "answer": grounded_answer(facts, llm_fn), "arrays": {"index": arr, "valid": valid},
           "raster": {"transform": sc.transform, "crs": sc.crs}}
    if cov_info is not None:
        res["coverage"] = cov_info
    return res


def run_change(provider: SatelliteProvider, aoi: dict, range_a: DateRange, range_b: DateRange,
               index: str = "NDVI", thresholds: Optional[dict] = None,
               max_cloud: float = settings.max_scene_cloud_cover, llm_fn: Optional[Callable] = None,
               selected_scene_ids: Optional[tuple[str, str]] = None) -> dict:
    index = index.upper()
    bands = _bands_for(index)
    if selected_scene_ids is None:
        ma = provider.best_scene(aoi, range_a.start, range_a.end, max_cloud)
        mb = provider.best_scene(aoi, range_b.start, range_b.end, max_cloud)
        sa, sb = provider.get_scene(aoi, ma["item_id"], bands), provider.get_scene(aoi, mb["item_id"], bands)
    else:
        sa = provider.get_selected_scene(aoi, selected_scene_ids[0], bands,
                                         range_a.start, range_a.end, max_cloud, use_utc_calendar_date=True)
        sb = provider.get_selected_scene(aoi, selected_scene_ids[1], bands,
                                         range_b.start, range_b.end, max_cloud, use_utc_calendar_date=True)
        ma = {"item_id": sa.item_id, "coverage": sa.coverage_fraction,
              "coverage_fraction": sa.coverage_fraction}
        mb = {"item_id": sb.item_id, "coverage": sb.coverage_fraction,
              "coverage_fraction": sb.coverage_fraction}
    from app.change_detection.align import align_to_grid, grids_compatible
    # Try to align if grids differ
    if not grids_compatible(sa.transform, sa.crs, sa.inside_aoi.shape,
                            sb.transform, sb.crs, sb.inside_aoi.shape):
        # Choose common grid - prefer higher resolution / first scene's grid by default
        target_tf, target_crs, target_shape = sa.transform, sa.crs, sa.inside_aoi.shape
        try:
            # Align scene b to scene a's grid
            sb_scl_aligned = align_to_grid(sb.scl, sb.transform, sb.crs, sb.scl.shape,
                                           target_tf, target_crs, target_shape, categorical=True)
            sb_inside_aligned = align_to_grid(sb.inside_aoi.astype(np.float32), sb.transform, sb.crs, sb.inside_aoi.shape,
                                              target_tf, target_crs, target_shape, categorical=False)
            # Rebuild scene b bands aligned
            sb_bands_aligned = {}
            for bname in bands:
                sb_bands_aligned[bname] = align_to_grid(sb.bands[bname], sb.transform, sb.crs, sb.bands[bname].shape,
                                                        target_tf, target_crs, target_shape, categorical=False)
            # Create aligned scene b
            from app.satellite.provider import SceneData
            sb = SceneData(sb.item_id, sb.datetime, sb.cloud_cover, sb_bands_aligned,
                           sb_scl_aligned.astype(np.uint8), target_tf, target_crs,
                           sb_inside_aligned > 0.5, sb.resolution_m,
                           sb.preprocessing + ["Aligned to common grid for change detection"],
                           sb.coverage_fraction, sb.provider, sb.collection,
                           sb.platform, sb.processing_level, sb.source, sb.sensor, sb.sensor_identity)
        except Exception as e:
            raise NoImageryError(
                "Could not geospatially align the two scenes for change detection. "
                "Check rasterio/GDAL availability and scene CRS/grid metadata, or select "
                "dates whose scenes can be aligned to a common grid."
            ) from e
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
    metrics["both_valid_fraction_of_aoi"] = res["both_valid_fraction"]
    metrics["n_aoi_pixels"] = n_aoi
    # Collect coverage from both scenes
    covs = []
    for m in (ma, mb):
        c = m.get("coverage_fraction") if m.get("coverage_fraction") is not None else m.get("coverage")
        if c is not None:
            covs.append(c)
    cov_info = None
    if covs:
        cov_info = {"status": "full" if min(covs) >= 0.99 else ("partial" if min(covs) > 0 else "unknown"), "fraction": float(min(covs)), "note": "Minimum coverage across the two scenes used."}
    ev = Evidence(operation="change_detection", scenes=[_scene_ref(sa), _scene_ref(sb)],
                  aoi_area_km2=n_aoi * px / 1e6, index=index, formula=spec.formula, bands=spec.sentinel2_bands,
                  preprocessing=sa.preprocessing + ["Pixels used only where valid on BOTH dates"],
                  thresholds=res["thresholds"], valid_pixel_fraction=res["both_valid_fraction"], metrics=metrics,
                  coverage=cov_info)
    ev_dict = ev.model_dump()
    if ev.coverage is None:
        ev_dict.pop("coverage", None)
    if cov_info is not None:
        ev_dict["metrics"]["coverage"] = cov_info
    # Attach additive per-hotspot evidence references (reuse global evidence; no large arrays)
    hotspots = res.get("hotspots") or []
    hotspot_evidence = {
        "baseline_scene_id": ma.get("item_id") if isinstance(ma, dict) else getattr(sa, "item_id", None),
        "comparison_scene_id": mb.get("item_id") if isinstance(mb, dict) else getattr(sb, "item_id", None),
        "baseline_date": sa.datetime[:10] if sa.datetime else None,
        "comparison_date": sb.datetime[:10] if sb.datetime else None,
        "index": index,
        "formula": spec.formula,
        "bands": spec.sentinel2_bands,
        "change_thresholds": res["thresholds"],
        "preprocessing": sa.preprocessing + ["Pixels used only where valid on BOTH dates"],
        "global_valid_pixel_fraction": res["both_valid_fraction"],
        "coverage": cov_info,
    }
    for h in hotspots:
        if isinstance(h, dict):
            h["evidence"] = dict(hotspot_evidence)
    facts = {"operation": "change_detection", "index": index, "date_a": sa.datetime[:10], "date_b": sb.datetime[:10],
             "change": {k: res[k] for k in ("mean_a", "mean_b", "mean_change", "percent_change_of_mean", "classes")},
             "analysed_area_km2": res["analysed_area_km2"], "coverage": cov_info,
             "hotspot_summary": {"count": len(hotspots)},
             "provenance": {"scene_ids": [sa.item_id, sb.item_id],
                            "provider": getattr(sa, "provider", None),
                            "collection": getattr(sa, "collection", None),
                            "providers": [getattr(sa, "provider", None), getattr(sb, "provider", None)]},
             "data_quality_score": conf["score"]}
    res_out = {"evidence": ev_dict, "confidence": conf, "facts": facts,
               "answer": grounded_answer(facts, llm_fn),
               "arrays": {"index_a": arr_a, "index_b": arr_b, "diff": res["diff"],
                          "class_map": res["class_map"], "hotspots": res["hotspot_map"]},
               "hotspots": hotspots, "raster": {"transform": sa.transform, "crs": sa.crs}}
    if cov_info is not None:
        res_out["coverage"] = cov_info
    return res_out


def run_time_series(provider: SatelliteProvider, aoi: dict, rng: DateRange, index: str = "NDVI",
                    max_cloud: float = settings.max_scene_cloud_cover, max_scenes: int = 60,
                    llm_fn: Optional[Callable] = None,
                    selected_scenes: Optional[list[dict]] = None,
                    require_all_selected: bool = False) -> dict:
    index = index.upper()
    listed = (selected_scenes if selected_scenes is not None else
              provider.list_scenes(aoi, rng.start, rng.end, max_cloud)[:max_scenes])
    if not listed:
        raise NoImageryError(f"No scenes between {rng.start} and {rng.end} with cloud cover <= {max_cloud:.0f}%.")
    pts, vfracs, clouds, refs, px, n_aoi = [], [], [], [], None, 0
    n_skipped_low_valid = 0
    n_dates_skipped_load_error = 0
    covs = []
    for m in listed:
        c = m.get("coverage_fraction") if m.get("coverage_fraction") is not None else m.get("coverage")
        if c is not None:
            covs.append(c)
        try:
            if selected_scenes is not None:
                selected_date = (m.get("_utc_date") or
                                 datetime.fromisoformat(str(m["datetime"]).replace("Z", "+00:00")).astimezone(timezone.utc).date())
                sc = provider.get_selected_scene(aoi, m["item_id"], _bands_for(index),
                                                 selected_date, selected_date, max_cloud,
                                                 use_utc_calendar_date=True)
            else:
                sc = provider.get_scene(aoi, m["item_id"], _bands_for(index))
        except Exception as exc:
            if require_all_selected:
                raise NoImageryError(
                    f"A selected matched scene could not be read for acquisition {m.get('datetime')}. "
                    "The Compare time series was stopped without substituting another scene."
                ) from exc
            n_dates_skipped_load_error += 1
            continue  # skip scenes that fail to load (no sensitive details exposed)
        arr, _, n_aoi = _prepare(sc, index)
        st = index_stats(arr, denominator=n_aoi)
        if st["valid_fraction"] < settings.min_valid_fraction:
            if require_all_selected:
                raise InsufficientValidPixelsError(
                    f"Matched acquisition {sc.datetime[:10]} has only {st['valid_fraction']:.1%} "
                    "valid pixels in one comparison area; no dates were substituted."
                )
            n_skipped_low_valid += 1
            continue
        px = pixel_area_m2(sc.transform)
        pts.append((sc.datetime, st["median"]))
        vfracs.append(st["valid_fraction"])
        if sc.cloud_cover is not None:
            clouds.append(sc.cloud_cover)
        refs.append(_scene_ref(sc))
    if not pts:
        raise InsufficientValidPixelsError("No date had enough valid pixels after masking.")

    def _parse_ts(dt: str):
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))

    # Defensive chronological ordering (stable): keeps parallel metadata aligned.
    # No deduplication of identical timestamps or same-calendar-date observations.
    order = sorted(range(len(pts)), key=lambda i: _parse_ts(pts[i][0]))
    pts = [pts[i] for i in order]
    vfracs = [vfracs[i] for i in order]
    refs = [refs[i] for i in order]
    clouds = [r.cloud_cover for r in refs if r.cloud_cover is not None]

    t0 = _parse_ts(pts[0][0])
    days = [(_parse_ts(d) - t0).total_seconds() / 86400 for d, _ in pts]
    vals = [v for _, v in pts]
    series = analyse_series(days, vals)
    series["dates"] = [d[:10] for d, _ in pts]
    series["values"] = vals
    tt = series["trend_test"]
    mean_vf = float(np.mean(vfracs))
    conf = compute_confidence(valid_fraction=mean_vf,
                              cloud_cover_pct=float(np.mean(clouds)) if clouds else None,
                              n_dates_used=len(pts), n_dates_requested=len(listed),
                              trend_significant=tt["significant"] if tt else None, trend_n=len(pts))
    spec = INDEX_REGISTRY[index]
    series["valid_fractions_per_included_date"] = [float(x) for x in vfracs]
    series["mean_valid_fraction_of_aoi_included"] = mean_vf
    series["n_dates_included"] = len(pts)
    series["n_dates_usable"] = len(pts)
    series["n_dates_skipped_low_valid"] = n_skipped_low_valid
    series["n_dates_skipped_load_error"] = n_dates_skipped_load_error
    series["n_dates_requested"] = len(listed)
    # Enforce minimum of 8 usable observations
    min_obs = int(getattr(settings, "min_dates_for_trend", 8))
    if len(pts) < min_obs:
        series["trend_claim_allowed"] = False
        series["trend_test"] = None
        series["sens_slope_per_year"] = None
        series["insufficient_observations"] = True
        series["status"] = "insufficient_observations"
        series["message"] = f"Insufficient observations for trend analysis: need at least {min_obs} usable dates (got {len(pts)})."
    else:
        series["insufficient_observations"] = False
    cov_info = None
    if covs:
        cov_info = {"status": "full" if min(covs) >= 0.99 else ("partial" if min(covs) > 0 else "unknown"), "fraction": float(min(covs)), "note": "Coverage varies by scene; using scenes that pass valid-pixel threshold."}
    ev = Evidence(operation="time_series", scenes=refs, aoi_area_km2=n_aoi * px / 1e6, index=index,
                  formula=spec.formula, bands=spec.sentinel2_bands,
                  preprocessing=[
                      "Per-date AOI median of valid pixels",
                      f"Scenes skipped when valid pixels < {settings.min_valid_fraction:.0%} (counted separately as low valid pixels).",
                      "Scenes skipped when scene loading failed (counted separately as load errors).",
                  ],
                  thresholds={"min_dates_for_trend": settings.min_dates_for_trend},
                  valid_pixel_fraction=mean_vf, metrics=series, coverage=cov_info)
    ev_dict = ev.model_dump()
    if ev.coverage is None:
        ev_dict.pop("coverage", None)
    if cov_info is not None:
        ev_dict["metrics"]["coverage"] = cov_info
    facts = {"operation": "time_series", "index": index, "series": series,
             "analysed_area_km2": n_aoi * px / 1e6, "sens_slope_per_year": series.get("sens_slope_per_year"),
             "provenance": {"scene_ids": [r.item_id for r in refs[:3]],
                            "provider": refs[0].provider if refs and all(r.provider == refs[0].provider for r in refs) else None,
                            "collection": refs[0].collection if refs and all(r.collection == refs[0].collection for r in refs) else None},
             "data_quality_score": conf["score"]}
    res = {"evidence": ev_dict, "confidence": conf, "facts": facts, "answer": grounded_answer(facts, llm_fn)}
    if cov_info is not None:
        res["coverage"] = cov_info
    return res
