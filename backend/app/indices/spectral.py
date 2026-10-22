"""Deterministic spectral indices. Pure numpy; no I/O.

Invalid / divide-by-zero pixels become NaN (never 0).
"""
from dataclasses import dataclass
from typing import Callable, Optional
import numpy as np

from app.core.config import settings
from app.core.errors import MissingBandError

_EPS = 1e-12


def _nd(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    den = a + b
    out = np.full(den.shape, np.nan, dtype=np.float64)
    ok = np.isfinite(den) & (np.abs(den) > _EPS)
    out[ok] = (a[ok] - b[ok]) / den[ok]
    return out


def ndvi(nir, red):
    return _nd(nir, red)


def ndwi(green, nir):  # McFeeters (1996)
    return _nd(green, nir)


def mndwi(green, swir1):  # Xu (2006)
    return _nd(green, swir1)


def ndbi(swir1, nir):
    return _nd(swir1, nir)


def savi(nir, red, L: float = settings.savi_l):
    nir = np.asarray(nir, dtype=np.float64)
    red = np.asarray(red, dtype=np.float64)
    den = nir + red + L
    out = np.full(den.shape, np.nan, dtype=np.float64)
    ok = np.isfinite(den) & (np.abs(den) > _EPS)
    out[ok] = (nir[ok] - red[ok]) / den[ok] * (1.0 + L)
    return out


@dataclass(frozen=True)
class IndexSpec:
    name: str
    formula: str
    bands: tuple          # logical band names, in function-argument order
    sentinel2_bands: str  # human-readable band IDs
    fn: Callable
    note: str = ""


INDEX_REGISTRY = {
    "NDVI": IndexSpec("NDVI", "(NIR - RED) / (NIR + RED)", ("nir", "red"), "B08 / B04", ndvi,
                      "Vegetation greenness/health proxy."),
    "NDWI": IndexSpec("NDWI", "(GREEN - NIR) / (GREEN + NIR)", ("green", "nir"), "B03 / B08", ndwi,
                      "McFeeters formulation, open water. Can confuse built-up land with water."),
    "MNDWI": IndexSpec("MNDWI", "(GREEN - SWIR1) / (GREEN + SWIR1)", ("green", "swir1"), "B03 / B11", mndwi,
                       "Modified NDWI (Xu), separates water from built-up better."),
    "NDBI": IndexSpec("NDBI", "(SWIR1 - NIR) / (SWIR1 + NIR)", ("swir1", "nir"), "B11 / B08", ndbi,
                      "Built-up index. Also responds to bare soil."),
    "SAVI": IndexSpec("SAVI", "((NIR - RED) / (NIR + RED + L)) * (1 + L), L=0.5", ("nir", "red"), "B08 / B04", savi,
                      "Soil-adjusted vegetation index for sparse vegetation."),
}


def compute_index(name: str, bands: dict, valid_mask: Optional[np.ndarray] = None) -> np.ndarray:
    name = name.upper()
    if name not in INDEX_REGISTRY:
        raise KeyError(f"Unsupported index: {name}")
    spec = INDEX_REGISTRY[name]
    missing = [b for b in spec.bands if b not in bands]
    if missing:
        raise MissingBandError(f"{name} needs bands {list(spec.bands)}; missing {missing}.")
    out = spec.fn(*[bands[b] for b in spec.bands])
    if valid_mask is not None:
        out = np.where(valid_mask, out, np.nan)
    return out


def index_stats(arr, *, vegetation_threshold: Optional[float] = None, denominator: Optional[int] = None) -> dict:
    """Stats over finite pixels only. coverage_fraction = share of valid pixels >= threshold."""
    arr = np.asarray(arr, dtype=np.float64)
    finite = np.isfinite(arr)
    n_total = int(denominator) if denominator else int(arr.size)
    n_valid = int(finite.sum())
    if n_valid == 0:
        return {"n_total": n_total, "n_valid": 0, "valid_fraction": 0.0, "mean": None, "median": None,
                "min": None, "max": None, "std": None, "coverage_fraction": None}
    v = arr[finite]
    out = {
        "n_total": n_total,
        "n_valid": n_valid,
        "valid_fraction": n_valid / n_total,
        "mean": float(v.mean()),
        "median": float(np.median(v)),
        "min": float(v.min()),
        "max": float(v.max()),
        "std": float(v.std(ddof=0)),
        "coverage_fraction": None,
    }
    if vegetation_threshold is not None:
        out["coverage_fraction"] = float((v >= vegetation_threshold).mean())
    return out
