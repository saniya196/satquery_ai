"""Before/after change detection on an index (default NDVI). Thresholds are explicit and returned."""
from typing import Optional
import numpy as np
from scipy import ndimage

from app.core.config import DEFAULT_CHANGE_THRESHOLDS, settings
from app.core.errors import InsufficientValidPixelsError
from app.rendering.geo import utm_to_lonlat, parse_utm_epsg

CLASS_CODES = {
    "significant_decrease": -2,
    "moderate_decrease": -1,
    "stable": 0,
    "moderate_increase": 1,
    "significant_increase": 2,
}
INVALID_CODE = 99


def classify_change(diff: np.ndarray, thresholds: Optional[dict] = None) -> np.ndarray:
    t = {**DEFAULT_CHANGE_THRESHOLDS, **(thresholds or {})}
    d = np.asarray(diff, dtype=np.float64)
    out = np.full(d.shape, INVALID_CODE, dtype=np.int16)
    f = np.isfinite(d)
    out[f & (d <= t["significant_decrease"])] = -2
    out[f & (d > t["significant_decrease"]) & (d <= t["moderate_decrease"])] = -1
    out[f & (d > t["moderate_decrease"]) & (d < t["moderate_increase"])] = 0
    out[f & (d >= t["moderate_increase"]) & (d < t["significant_increase"])] = 1
    out[f & (d >= t["significant_increase"])] = 2
    return out


def find_hotspots(class_map: np.ndarray, diff: np.ndarray, pixel_area_m2: float,
                  min_pixels: int = settings.hotspot_min_pixels, top_n: int = 10,
                  transform=None, crs: Optional[str] = None) -> list:
    """Connected components (8-connectivity) of significant-decrease pixels."""
    mask = class_map == CLASS_CODES["significant_decrease"]
    labels, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    spots = []
    for i in range(1, n + 1):
        region = labels == i
        count = int(region.sum())
        if count < min_pixels:
            continue
        rows, cols = np.where(region)
        spot = {
            "id": i,
            "pixels": count,
            "area_km2": count * pixel_area_m2 / 1e6,
            "bbox_rowcol": [int(rows.min()), int(cols.min()), int(rows.max()), int(cols.max())],
            "centroid_rowcol": [float(rows.mean()), float(cols.mean())],
            "mean_diff": float(np.nanmean(diff[region])),
        }
        if transform is not None and crs is not None:
            zone, north = parse_utm_epsg(crs)
            easting, northing = transform * (float(cols.mean()) + 0.5, float(rows.mean()) + 0.5)
            lon, lat = utm_to_lonlat(easting, northing, zone, north)
            spot["centroid_lonlat"] = [lon, lat]
        spots.append(spot)
    spots.sort(key=lambda s: s["area_km2"], reverse=True)
    return spots[:top_n]


def detect_change(index_a: np.ndarray, index_b: np.ndarray, pixel_area_m2: float,
                  thresholds: Optional[dict] = None, inside_aoi: Optional[np.ndarray] = None,
                  transform=None, crs: Optional[str] = None) -> dict:
    """index_a = earlier date, index_b = later date. Only pixels valid on BOTH dates are used."""
    a = np.asarray(index_a, dtype=np.float64)
    b = np.asarray(index_b, dtype=np.float64)
    if a.shape != b.shape:
        raise ValueError("Index rasters must share the same grid.")
    both = np.isfinite(a) & np.isfinite(b)
    if inside_aoi is not None:
        both &= inside_aoi
    denom = int(inside_aoi.sum()) if inside_aoi is not None else a.size
    n_both = int(both.sum())
    if denom == 0 or n_both == 0 or n_both / denom < settings.min_valid_fraction:
        frac = (n_both / denom) if denom else 0.0
        raise InsufficientValidPixelsError(
            f"Only {frac:.1%} of AOI pixels are valid on both dates "
            f"(minimum {settings.min_valid_fraction:.0%}).")
    diff = np.where(both, b - a, np.nan)
    class_map = classify_change(diff, thresholds)
    used = {**DEFAULT_CHANGE_THRESHOLDS, **(thresholds or {})}

    mean_a, mean_b = float(a[both].mean()), float(b[both].mean())
    pct = None if abs(mean_a) < 1e-6 else (mean_b - mean_a) / abs(mean_a) * 100.0

    classes = {}
    for name, code in CLASS_CODES.items():
        c = int((class_map == code).sum())
        classes[name] = {"pixels": c, "fraction_of_valid": c / n_both, "area_km2": c * pixel_area_m2 / 1e6}

    hotspots = find_hotspots(class_map, diff, pixel_area_m2, transform=transform, crs=crs)
    labels, _ = ndimage.label(class_map == CLASS_CODES["significant_decrease"],
                              structure=np.ones((3, 3), dtype=int))
    hotspot_ids = [spot["id"] for spot in hotspots]

    return {
        "n_pixels_both_valid": n_both,
        "both_valid_fraction": n_both / denom,
        "mean_a": mean_a,
        "mean_b": mean_b,
        "mean_change": mean_b - mean_a,
        "percent_change_of_mean": pct,
        "median_change": float(np.median(diff[both])),
        "std_change": float(diff[both].std()),
        "classes": classes,
        "thresholds": used,
        "diff": diff,
        "class_map": class_map,
        "hotspots": hotspots,
        "hotspot_map": np.isin(labels, hotspot_ids),
        "analysed_area_km2": n_both * pixel_area_m2 / 1e6,
    }
