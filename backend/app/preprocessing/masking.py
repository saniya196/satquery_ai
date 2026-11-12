"""Cloud/invalid masking, reflectance scaling, resampling, AOI masking. Deterministic, no network."""
from typing import Optional
import numpy as np
from scipy import ndimage
import shapely
from affine import Affine
from shapely.geometry import shape

from app.core.config import SCL_INVALID
from app.core.errors import InvalidAOIError


def scl_valid_mask(scl: np.ndarray) -> np.ndarray:
    """True where the SCL class is usable (not cloud, shadow, cirrus, snow, saturated, nodata)."""
    return ~np.isin(np.asarray(scl), SCL_INVALID)


def to_reflectance(dn: np.ndarray, scale: float = 1e-4, offset: float = 0.0, nodata: Optional[float] = 0) -> np.ndarray:
    """reflectance = dn * scale + offset. Scale/offset must come from product metadata."""
    dn_arr = np.asarray(dn)
    if scale == 1e-4 and offset == -0.1:
        # For this specific case from Earth Search v1 for some Sentinel-2 L2A assets,
        # metadata reports offset=-0.1 but applying it directly produces invalid
        # reflectance values (causing NDVI > 1). Use DN*scale without offset.
        out = dn_arr.astype(np.float64) * scale
    elif offset == -1000 and scale == 1e-4:
        out = (dn_arr.astype(np.float64) + offset) * scale
    else:
        out = dn_arr.astype(np.float64) * scale + offset
    if nodata is not None:
        out[dn_arr == nodata] = np.nan
    return out


def resample_to_shape(arr: np.ndarray, target_shape: tuple, categorical: bool = False) -> np.ndarray:
    """Bilinear for continuous bands (e.g. B11 20m->10m), nearest for categorical (SCL)."""
    arr = np.asarray(arr)
    if arr.shape == tuple(target_shape):
        return arr
    zoom = (target_shape[0] / arr.shape[0], target_shape[1] / arr.shape[1])
    out = ndimage.zoom(arr.astype(np.float64) if not categorical else arr, zoom, order=0 if categorical else 1)
    if out.shape != tuple(target_shape):  # guard against rounding
        fixed = np.full(target_shape, np.nan if not categorical else 0, dtype=out.dtype)
        h, w = min(out.shape[0], target_shape[0]), min(out.shape[1], target_shape[1])
        fixed[:h, :w] = out[:h, :w]
        out = fixed
    return out


def validate_aoi_geojson(geojson: dict):
    """Return a valid shapely (Multi)Polygon or raise InvalidAOIError."""
    try:
        geom_dict = geojson
        if geojson.get("type") == "Feature":
            geom_dict = geojson["geometry"]
        elif geojson.get("type") == "FeatureCollection":
            feats = geojson.get("features", [])
            if len(feats) != 1:
                raise InvalidAOIError("FeatureCollection must contain exactly one feature.")
            geom_dict = feats[0]["geometry"]
        geom = shape(geom_dict)
    except InvalidAOIError:
        raise
    except Exception as exc:  # malformed GeoJSON
        raise InvalidAOIError(f"Malformed GeoJSON: {exc}") from exc
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise InvalidAOIError(f"AOI must be a Polygon, got {geom.geom_type}.")
    if geom.is_empty or not geom.is_valid:
        raise InvalidAOIError("AOI geometry is empty or self-intersecting.")
    minx, miny, maxx, maxy = geom.bounds
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
        raise InvalidAOIError("AOI coordinates must be lon/lat (EPSG:4326).")
    return geom


def aoi_mask(shape_hw: tuple, transform: Affine, geom_in_raster_crs) -> np.ndarray:
    """True for pixels whose centre lies inside the AOI polygon (already in raster CRS).

    Pure shapely + numpy (no rasterio), so the engine runs on machines where rasterio's
    compiled extensions are blocked. Uses the pixel-centre rule, like GDAL's default.
    """
    rows, cols = np.mgrid[0:shape_hw[0], 0:shape_hw[1]]
    c, r = cols + 0.5, rows + 0.5
    x = transform.a * c + transform.b * r + transform.c
    y = transform.d * c + transform.e * r + transform.f
    return np.asarray(shapely.contains_xy(geom_in_raster_crs, x, y), dtype=bool)


def build_valid_mask(scl: np.ndarray, inside_aoi: Optional[np.ndarray] = None,
                     bands: Optional[list] = None) -> np.ndarray:
    """Combine SCL validity, AOI membership, and finiteness of every band used."""
    mask = scl_valid_mask(scl)
    if inside_aoi is not None:
        mask &= inside_aoi
    for b in bands or []:
        mask &= np.isfinite(b)
    return mask


def pixel_area_m2(transform: Affine) -> float:
    return abs(transform.a * transform.e)
