"""
ml/src/preprocessing.py
Core preprocessing functions for SatQuery AI.

Band order for EuroSAT all-bands GeoTIFFs:
B01, B02, B03, B04, B05, B06, B07, B08, B08A, B09, B10, B11, B12
index: 0    1    2    3    4    5    6    7    8     9    10   11   12
"""

import numpy as np
import rasterio

BAND_INDEX = {
    "B01": 0, "B02": 1, "B03": 2, "B04": 3, "B05": 4,
    "B06": 5, "B07": 6, "B08": 7, "B08A": 8, "B09": 9,
    "B10": 10, "B11": 11, "B12": 12,
}


def load_bands(tif_path: str) -> np.ndarray:
    """Load a 13-band EuroSAT GeoTIFF. Returns array shape (13, H, W), dtype float32."""
    with rasterio.open(tif_path) as src:
        img = src.read().astype(np.float32)
    return img


def compute_ndvi(bands: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - Red) / (NIR + Red). Uses B08 (NIR) and B04 (Red)."""
    red = bands[BAND_INDEX["B04"]]
    nir = bands[BAND_INDEX["B08"]]
    return (nir - red) / (nir + red + 1e-8)


def compute_ndwi(bands: np.ndarray) -> np.ndarray:
    """NDWI (McFeeters) = (Green - NIR) / (Green + NIR). Uses B03 (Green) and B08 (NIR)."""
    green = bands[BAND_INDEX["B03"]]
    nir = bands[BAND_INDEX["B08"]]
    return (green - nir) / (green + nir + 1e-8)


def get_rgb_preview(bands: np.ndarray) -> np.ndarray:
    """Rough RGB preview from B04(R), B03(G), B02(B), normalized 0-1 for display."""
    rgb = bands[[BAND_INDEX["B04"], BAND_INDEX["B03"], BAND_INDEX["B02"]]]
    rgb = np.transpose(rgb, (1, 2, 0))
    rgb = rgb / (rgb.max() + 1e-8)
    return np.clip(rgb, 0, 1)


def summarize_index(index_map: np.ndarray) -> dict:
    """Summary stats for an index map (NDVI/NDWI) — this is what the answer layer will consume."""
    return {
        "mean": float(np.mean(index_map)),
        "min": float(np.min(index_map)),
        "max": float(np.max(index_map)),
    }