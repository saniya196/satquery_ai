"""Deterministic Sentinel-2/Sentinel-1 feature-level fusion.

The output is an aligned feature stack, not a synthetic physical measurement or
a claim that acquisitions are simultaneous.  RVI is only evaluated on linear
RTC gamma0 values before the VV/VH dB display bands are created.
"""
from datetime import datetime
from pathlib import Path
import math
import numpy as np

from app.core.config import settings
from app.core.errors import InsufficientValidPixelsError, NoImageryError
from app.indices.spectral import ndvi
from app.preprocessing.masking import build_valid_mask
from app.satellite.provider import SceneData, Sentinel1RTCData, reproject_array_to_grid, write_fusion_geotiff


def temporal_separation_hours(optical_time: str, sar_time: str) -> float:
    try:
        first = datetime.fromisoformat(optical_time.replace("Z", "+00:00"))
        second = datetime.fromisoformat(sar_time.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise NoImageryError("A selected source has unreadable acquisition-time metadata.") from exc
    return abs((first - second).total_seconds()) / 3600.0


def ensure_pair_compatible(optical_time: str, sar_time: str) -> float:
    hours = temporal_separation_hours(optical_time, sar_time)
    if hours > settings.fusion_max_temporal_separation_days * 24:
        raise NoImageryError(
            f"The selected acquisitions are {hours / 24:.2f} days apart; fusion permits at most "
            f"{settings.fusion_max_temporal_separation_days:g} days. Select a closer pair."
        )
    return hours


def _db(linear: np.ndarray) -> np.ndarray:
    out = np.full(linear.shape, np.nan, dtype=np.float32)
    usable = np.isfinite(linear) & (linear > 0)
    out[usable] = 10 * np.log10(linear[usable])
    return out


def fuse(optical: SceneData, sar: Sentinel1RTCData, output_path: Path) -> tuple[dict, dict, dict]:
    """Align RTC to the native 10 m Sentinel-2 grid and write a real GeoTIFF."""
    separation_hours = ensure_pair_compatible(optical.datetime, sar.datetime)
    if set(("red", "nir")) - set(optical.bands):
        raise NoImageryError("Selected Sentinel-2 scene lacks the B04/B08 inputs required for NDVI fusion.")
    if set(("VV", "VH")) - set(sar.bands):
        raise NoImageryError("Selected Sentinel-1 RTC scene lacks both linear VV and VH assets.")
    s2_valid = build_valid_mask(optical.scl, optical.inside_aoi, [optical.bands["red"], optical.bands["nir"]])
    vv = reproject_array_to_grid(sar.bands["VV"], sar.transform, sar.crs, optical.transform, optical.crs,
                                 optical.inside_aoi.shape)
    vh = reproject_array_to_grid(sar.bands["VH"], sar.transform, sar.crs, optical.transform, optical.crs,
                                 optical.inside_aoi.shape)
    sar_inside = reproject_array_to_grid(sar.inside_aoi.astype(np.uint8), sar.transform, sar.crs,
                                         optical.transform, optical.crs, optical.inside_aoi.shape, categorical=True).astype(bool)
    # RTC gamma0 must be non-negative linear power. Negative values cannot be dB-converted or used in RVI.
    sar_valid = sar_inside & np.isfinite(vv) & np.isfinite(vh) & (vv >= 0) & (vh >= 0)
    denominator = vv + vh
    rvi = np.full(vv.shape, np.nan, dtype=np.float32)
    rvi_valid = sar_valid & np.isfinite(denominator) & (denominator > 0)
    rvi[rvi_valid] = 4.0 * vh[rvi_valid] / denominator[rvi_valid]
    overlap = s2_valid & rvi_valid
    total = int(np.count_nonzero(optical.inside_aoi))
    valid_count = int(np.count_nonzero(overlap))
    if total == 0 or valid_count == 0:
        raise InsufficientValidPixelsError("No valid optical/SAR overlap remains after alignment and nodata masking.")
    fraction = valid_count / total
    if fraction < settings.min_valid_fraction:
        raise InsufficientValidPixelsError(
            f"Only {fraction:.1%} of AOI pixels have valid optical/SAR overlap; the minimum is {settings.min_valid_fraction:.0%}."
        )
    features = {"ndvi": np.where(overlap, ndvi(optical.bands["nir"], optical.bands["red"]), np.nan).astype(np.float32),
                "vv_db": np.where(overlap, _db(vv), np.nan).astype(np.float32),
                "vh_db": np.where(overlap, _db(vh), np.nan).astype(np.float32),
                "rvi": np.where(overlap, rvi, np.nan).astype(np.float32)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_fusion_geotiff(str(output_path), features, optical.transform, optical.crs)
    metrics = {"valid_overlapping_pixel_count": valid_count, "aoi_pixel_count": total,
               "overlap_fraction": fraction, "temporal_separation_hours": separation_hours,
               "common_crs": optical.crs, "resolution_m": optical.resolution_m,
               "artifact_path": str(output_path)}
    facts = {"operation": "optical_sar_fusion", "product": "Aligned Sentinel-2/Sentinel-1 feature stack",
             "valid_overlapping_pixel_count": valid_count, "overlap_fraction": fraction,
             "temporal_separation_hours": separation_hours,
             "mean_ndvi": float(np.nanmean(features["ndvi"])), "mean_rvi": float(np.nanmean(features["rvi"])),
             "common_crs": optical.crs, "resolution_m": optical.resolution_m}
    evidence = {"operation": "optical_sar_fusion", "scenes": [
        {"item_id": optical.item_id, "datetime": optical.datetime, "cloud_cover": optical.cloud_cover,
         "resolution_m": optical.resolution_m, "crs": optical.crs, "provider": optical.provider,
         "collection": optical.collection, "platform": optical.platform, "processing_level": optical.processing_level,
         "sensor": "Sentinel-2", "sensor_identity": "sentinel-2", "coverage_fraction": optical.coverage_fraction},
        {"item_id": sar.item_id, "datetime": sar.datetime, "resolution_m": sar.resolution_m, "crs": sar.crs,
         "provider": "Microsoft Planetary Computer", "collection": "sentinel-1-rtc", "platform": sar.platform,
         "processing_level": sar.processing_level, "sensor": "Sentinel-1", "sensor_identity": "other",
         "coverage_fraction": sar.coverage_fraction, "polarizations": ["VV", "VH"]}],
        "aoi_area_km2": 0.0, "bands": ["Sentinel-2 B08/B04 -> NDVI", "Sentinel-1 RTC VV/VH linear gamma0 -> RVI", "VV/VH dB display bands"],
        "preprocessing": ["Sentinel-2 SCL and AOI validity mask", "Sentinel-2 native projected 10 m grid selected as common grid",
                          "Sentinel-1 RTC VV/VH bilinearly reprojected to that grid", "AOI/finite/nodata overlap mask applied",
                          "RVI = 4*VH/(VV+VH) computed from linear RTC gamma0 before dB conversion"],
        "thresholds": {"max_temporal_separation_days": settings.fusion_max_temporal_separation_days,
                       "min_valid_pixel_fraction": settings.min_valid_fraction},
        "valid_pixel_fraction": fraction, "metrics": metrics,
        "coverage": {"status": "full", "fraction": fraction,
                     "note": "Valid overlap after source masks and reprojection; sources are not simultaneous."}}
    return {**facts, "evidence": evidence}, {**features, "overlap_mask": overlap.astype(np.uint8)}, {"transform": optical.transform, "crs": optical.crs, "shape": features["ndvi"].shape}
