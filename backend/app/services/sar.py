"""Statistics for provider-preprocessed Sentinel-1 RTC acquisitions."""
import math

import numpy as np

from app.core.errors import InsufficientValidPixelsError, NoImageryError
from app.core.config import settings
from app.satellite.provider import Sentinel1RTCData


def summarize_rtc_scene(scene: Sentinel1RTCData, aoi_area_km2: float | None = None) -> dict:
    """Compute reproducible VV/VH statistics in the provider's native gamma0 units.

    No reflectance scaling, cross-scene resampling, dB conversion, or inferred
    physical area is applied here. The provider must supply one exact RTC grid.
    """
    inside = np.asarray(scene.inside_aoi, dtype=bool)
    if inside.ndim != 2 or inside.size == 0:
        raise NoImageryError("Sentinel-1 scene has no pixels in the selected AOI.")
    vv = np.asarray(scene.bands.get("VV"), dtype=np.float64)
    vh = np.asarray(scene.bands.get("VH"), dtype=np.float64)
    if vv.shape != inside.shape or vh.shape != inside.shape:
        raise NoImageryError("Sentinel-1 VV/VH pixels are not aligned to one shared AOI grid.")
    source_valid = inside & np.isfinite(vv) & np.isfinite(vh)
    if np.any(source_valid & ((vv < 0) | (vh < 0))):
        raise NoImageryError("RTC gamma0 assets contain negative valid samples; unit interpretation is unsafe.")
    valid = source_valid
    denominator = int(inside.sum())
    count = int(valid.sum())
    if denominator == 0 or count == 0:
        raise InsufficientValidPixelsError("No valid VV/VH pixels remain inside the selected AOI.")
    fraction = count / denominator
    if fraction < settings.min_valid_fraction:
        raise InsufficientValidPixelsError(
            f"Only {fraction:.1%} of AOI pixels have valid VV/VH values; "
            f"the minimum is {settings.min_valid_fraction:.0%}."
        )

    def stats(values: np.ndarray) -> dict[str, float]:
        sample = values[valid]
        return {
            "mean": float(np.mean(sample)),
            "median": float(np.median(sample)),
            "minimum": float(np.min(sample)),
            "maximum": float(np.max(sample)),
            "standard_deviation": float(np.std(sample)),
        }

    evidence = {
        "operation": "sar_backscatter",
        "scenes": [{
            "item_id": scene.item_id,
            "datetime": scene.datetime,
            "provider": "Microsoft Planetary Computer",
            "collection": "sentinel-1-rtc",
            "platform": scene.platform,
            "sensor": "Sentinel-1",
            "sensor_identity": "other",
            "processing_level": scene.processing_level,
            "processing_product": "Radiometrically terrain-corrected gamma0 derived from GRD",
            "orbit_state": scene.orbit_state,
            "relative_orbit": scene.relative_orbit,
            "polarizations": scene.polarizations,
            "coverage_fraction": scene.coverage_fraction,
            "resolution_m": scene.resolution_m,
            "crs": scene.crs,
        }],
        "aoi_area_km2": aoi_area_km2,
        "bands": ["VV", "VH"],
        "preprocessing": [
            "Planetary Computer Sentinel-1 RTC product (calibrated and terrain corrected by provider)",
            "AOI mask applied in the source asset grid",
            "VV and VH jointly masked for nodata and non-finite values",
        ],
        "valid_pixel_fraction": fraction,
        "thresholds": {"min_valid_pixel_fraction": settings.min_valid_fraction},
        "metrics": {"valid_pixel_count": count, "aoi_pixel_count": denominator},
    }
    facts = {
        "operation": "sar_backscatter",
        "measurement": "Sentinel-1 RTC gamma0 asset values in provider-native units",
        "unit": "linear gamma0",
        "valid_pixel_fraction": fraction,
        "valid_pixel_count": count,
        "vv": stats(vv),
        "vh": stats(vh),
    }
    # Guard the JSON contract against accidental NaN/Infinity propagation.
    if not all(math.isfinite(value) for group in (facts["vv"], facts["vh"]) for value in group.values()):
        raise NoImageryError("Sentinel-1 statistics contain invalid numeric values; analysis was stopped.")
    return {"facts": facts, "evidence": evidence}
