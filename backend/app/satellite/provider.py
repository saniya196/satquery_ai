"""Data-provider abstraction. Nothing outside this package knows about STAC or COG URLs."""
import hashlib
import json
import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
from affine import Affine

from app.core.config import settings
from app.core.errors import MissingBandError, NoImageryError


class UploadedRasterError(Exception):
    """A user-uploaded raster cannot be safely read or analysed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class UploadedRaster:
    """One validated band from an uploaded georeferenced raster."""
    data: np.ndarray
    width: int
    height: int
    band_count: int
    dtype: str
    crs: str
    transform: Affine
    nodata: Optional[float]
    resolution_x: float
    resolution_y: float
    linear_units: Optional[str]
    bounds: tuple[float, float, float, float]


@dataclass
class UploadedRasterCube:
    """Validated multiband reflectance cube from one uploaded GeoTIFF."""
    data: np.ndarray
    width: int
    height: int
    band_count: int
    dtype: str
    crs: str
    transform: Affine
    nodata: Optional[float]
    resolution_x: float
    resolution_y: float
    linear_units: Optional[str]
    bounds: tuple[float, float, float, float]
    band_mapping: dict[str, int]


MAX_UPLOADED_LAND_COVER_PIXELS = 4_000_000


def read_uploaded_raster(path: str, band: int = 1, max_dimension: int = 10000) -> UploadedRaster:
    """Read and validate one band from an uploaded GeoTIFF.

    rasterio is imported lazily here so environments without its compiled extension
    return a clear unsupported response instead of failing application startup.
    """
    try:
        import rasterio
    except Exception as exc:
        raise UploadedRasterError(
            "raster_backend_unavailable",
            "GeoTIFF pixel analysis is unavailable because the raster backend could not be loaded.",
        ) from exc

    return _read_uploaded_raster_window(path, band=band, max_dimension=max_dimension)


def read_uploaded_raster_cube(
    path: str,
    band_mapping: dict[str, int],
    band_order: tuple[str, ...],
    radiometry: str,
    max_dimension: int = 10000,
    max_pixels: int = MAX_UPLOADED_LAND_COVER_PIXELS,
) -> UploadedRasterCube:
    """Read an explicitly mapped, already-reflectance multiband GeoTIFF cube.

    This deliberately does not infer band identities, apply scale/offset, or resample.
    """
    if radiometry != "reflectance":
        raise UploadedRasterError(
            "unsupported_radiometry",
            "Uploaded land-cover classification requires an explicit radiometry declaration of 'reflectance'.",
        )
    if set(band_mapping) != set(band_order):
        raise UploadedRasterError(
            "invalid_band_mapping",
            f"band_mapping must contain exactly: {', '.join(band_order)}.",
        )
    try:
        mapped = {logical: int(band_mapping[logical]) for logical in band_order}
    except (KeyError, TypeError, ValueError) as exc:
        raise UploadedRasterError("invalid_band_mapping", "Band indexes must be positive integers.") from exc
    if any(index < 1 for index in mapped.values()) or len(set(mapped.values())) != len(mapped):
        raise UploadedRasterError("invalid_band_mapping", "Band indexes must be positive and unique.")

    try:
        import rasterio
    except Exception as exc:
        raise UploadedRasterError(
            "raster_backend_unavailable",
            "GeoTIFF pixel analysis is unavailable because the raster backend could not be loaded.",
        ) from exc

    try:
        with rasterio.open(path) as src:
            if src.driver not in {"GTiff", "COG"}:
                raise UploadedRasterError("unsupported_raster_format", "Only GeoTIFF rasters are supported.")
            if src.width <= 0 or src.height <= 0 or src.width > max_dimension or src.height > max_dimension:
                raise UploadedRasterError("raster_dimensions_unsupported", "Raster dimensions are missing or exceed the supported limit.")
            if src.width * src.height > max_pixels:
                raise UploadedRasterError(
                    "raster_pixel_limit_exceeded",
                    f"Uploaded land-cover classification supports at most {max_pixels:,} pixels.",
                )
            if any(index > src.count for index in mapped.values()):
                raise UploadedRasterError("invalid_band_mapping", "A mapped band is not present in the uploaded raster.")
            if src.crs is None:
                raise UploadedRasterError("missing_crs", "The raster has no CRS; pixel results cannot be geolocated safely.")
            transform = src.transform
            if not all(np.isfinite(value) for value in tuple(transform)[:6]) or transform.a == 0 or transform.e == 0:
                raise UploadedRasterError("invalid_transform", "The raster has no valid affine geotransform.")
            if transform.b != 0 or transform.d != 0:
                raise UploadedRasterError("rotated_transform_unsupported", "Uploaded land-cover classification requires a north-up raster transform.")

            arrays = []
            nodata_values = []
            for logical in band_order:
                index = mapped[logical]
                masked = src.read(index, masked=True)
                data = np.asarray(masked.filled(np.nan), dtype=np.float32)
                if data.shape != (src.height, src.width):
                    raise UploadedRasterError("incompatible_band_grid", "Mapped bands do not share the raster dimensions.")
                nodata = src.nodatavals[index - 1]
                if nodata is None:
                    nodata = src.nodata
                if nodata is not None:
                    data[data == float(nodata)] = np.nan
                arrays.append(data)
                nodata_values.append(float(nodata) if nodata is not None else None)

            cube = np.stack(arrays).astype(np.float32)
            if np.isinf(cube).any():
                raise UploadedRasterError("invalid_pixel_values", "The selected bands contain invalid pixel values.")
            if not np.isfinite(cube).all(axis=0).any():
                raise UploadedRasterError("no_valid_pixels", "The selected bands contain no valid pixels.")
            common_nodata = nodata_values[0] if all(value == nodata_values[0] for value in nodata_values) else None
            return UploadedRasterCube(
                data=cube,
                width=src.width,
                height=src.height,
                band_count=src.count,
                dtype=str(src.dtypes[mapped[band_order[0]] - 1]),
                crs=src.crs.to_string(),
                transform=transform,
                nodata=common_nodata,
                resolution_x=abs(float(transform.a)),
                resolution_y=abs(float(transform.e)),
                linear_units=getattr(src.crs, "linear_units", None),
                bounds=(float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top)),
                band_mapping=mapped,
            )
    except UploadedRasterError:
        raise
    except Exception as exc:
        raise UploadedRasterError("invalid_raster", "The uploaded file is not a readable GeoTIFF raster.") from exc


def read_uploaded_raster_region(path: str, band: int, region: dict[str, float], max_dimension: int = 10000) -> UploadedRaster:
    """Read one band from an axis-aligned region expressed in the raster CRS."""
    try:
        import rasterio
        from rasterio.windows import Window
    except Exception as exc:
        raise UploadedRasterError(
            "raster_backend_unavailable",
            "GeoTIFF pixel analysis is unavailable because the raster backend could not be loaded.",
        ) from exc

    try:
        with rasterio.open(path) as src:
            if src.driver not in {"GTiff", "COG"}:
                raise UploadedRasterError("unsupported_raster_format", "Only GeoTIFF rasters are supported.")
            if src.width <= 0 or src.height <= 0 or src.width > max_dimension or src.height > max_dimension:
                raise UploadedRasterError("raster_dimensions_unsupported", "Raster dimensions are missing or exceed the supported limit.")
            if src.count < 1 or band < 1 or band > src.count:
                raise UploadedRasterError("invalid_band", f"Band {band} is not present in this raster.")
            if src.crs is None:
                raise UploadedRasterError("missing_crs", "The raster has no CRS; pixel results cannot be geolocated safely.")
            transform = src.transform
            if not all(np.isfinite(v) for v in tuple(transform)[:6]) or transform.a == 0 or transform.e == 0:
                raise UploadedRasterError("invalid_transform", "The raster has no valid affine geotransform.")
            if transform.b != 0 or transform.d != 0:
                raise UploadedRasterError("rotated_transform_unsupported", "Region statistics require a north-up raster transform.")

            raster_left, raster_bottom, raster_right, raster_top = (
                float(src.bounds.left), float(src.bounds.bottom),
                float(src.bounds.right), float(src.bounds.top),
            )
            start_col, start_row, stop_col, stop_row = region_pixel_window(
                region, transform, (raster_left, raster_bottom, raster_right, raster_top), src.width, src.height,
            )
            window = Window(start_col, start_row, stop_col - start_col, stop_row - start_row)
    except UploadedRasterError:
        raise
    except Exception as exc:
        raise UploadedRasterError("invalid_raster", "The uploaded file is not a readable GeoTIFF raster.") from exc

    return _read_uploaded_raster_window(path, band=band, max_dimension=max_dimension, window=window)


def region_pixel_window(region: dict[str, float], transform: Affine, bounds: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    """Convert a raster-CRS bounding box into an inclusive pixel window."""
    try:
        min_x = float(region["min_x"])
        min_y = float(region["min_y"])
        max_x = float(region["max_x"])
        max_y = float(region["max_y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UploadedRasterError("invalid_region", "Region coordinates must be finite numbers in the raster CRS.") from exc
    if not all(np.isfinite(v) for v in (min_x, min_y, max_x, max_y)):
        raise UploadedRasterError("invalid_region", "Region coordinates must be finite numbers in the raster CRS.")
    if min_x >= max_x or min_y >= max_y:
        raise UploadedRasterError("invalid_region", "Region minimum coordinates must be smaller than maximum coordinates.")
    raster_left, raster_bottom, raster_right, raster_top = bounds
    if min_x < raster_left or min_y < raster_bottom or max_x > raster_right or max_y > raster_top:
        raise UploadedRasterError("region_outside_raster", "The requested region lies outside the raster extent.")
    col0, row0 = (~transform) @ (min_x, max_y)
    col1, row1 = (~transform) @ (max_x, min_y)
    start_col = max(0, math.floor(min(col0, col1)))
    start_row = max(0, math.floor(min(row0, row1)))
    stop_col = min(width, math.ceil(max(col0, col1)))
    stop_row = min(height, math.ceil(max(row0, row1)))
    if stop_col <= start_col or stop_row <= start_row:
        raise UploadedRasterError("region_no_pixels", "The requested region does not intersect any raster pixels.")
    return start_col, start_row, stop_col, stop_row


def _read_uploaded_raster_window(path: str, band: int, max_dimension: int = 10000, window=None) -> UploadedRaster:
    try:
        import rasterio

        with rasterio.open(path) as src:
            if src.driver not in {"GTiff", "COG"}:
                raise UploadedRasterError("unsupported_raster_format", "Only GeoTIFF rasters are supported.")
            if src.width <= 0 or src.height <= 0 or src.width > max_dimension or src.height > max_dimension:
                raise UploadedRasterError("raster_dimensions_unsupported", "Raster dimensions are missing or exceed the supported limit.")
            if src.count < 1 or band < 1 or band > src.count:
                raise UploadedRasterError("invalid_band", f"Band {band} is not present in this raster.")
            if src.crs is None:
                raise UploadedRasterError("missing_crs", "The raster has no CRS; pixel results cannot be geolocated safely.")
            transform = src.window_transform(window) if window is not None else src.transform
            masked = src.read(band, window=window, masked=True)
            data = np.asarray(masked.filled(np.nan), dtype=np.float64)
            if src.nodata is not None:
                data[data == float(src.nodata)] = np.nan
            finite = np.isfinite(data)
            if not finite.any():
                raise UploadedRasterError("no_valid_pixels", "The selected region contains no valid pixels.")
            if not np.isfinite(data[finite]).all():
                raise UploadedRasterError("invalid_pixel_values", "The selected band contains invalid pixel values.")
            if window is None:
                bounds = (float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top))
            else:
                bounds = tuple(float(value) for value in rasterio.windows.bounds(window, src.transform))
            return UploadedRaster(
                data=data,
                width=data.shape[1],
                height=data.shape[0],
                band_count=src.count,
                dtype=str(src.dtypes[band - 1]),
                crs=src.crs.to_string(),
                transform=transform,
                nodata=float(src.nodata) if src.nodata is not None else None,
                resolution_x=abs(float(transform.a)),
                resolution_y=abs(float(transform.e)),
                linear_units=getattr(src.crs, "linear_units", None),
                bounds=bounds,
            )
    except UploadedRasterError:
        raise
    except Exception as exc:
        raise UploadedRasterError("invalid_raster", "The uploaded file is not a readable GeoTIFF raster.") from exc


@dataclass
class SceneData:
    """Reflectance bands already scaled, all on one grid, plus SCL on that grid."""
    item_id: str
    datetime: str
    cloud_cover: Optional[float]
    bands: dict                      # logical name -> float array (reflectance)
    scl: np.ndarray
    transform: Affine
    crs: str
    inside_aoi: np.ndarray           # bool, True inside AOI polygon
    resolution_m: float = 10.0
    preprocessing: list = field(default_factory=list)


class SatelliteProvider(ABC):
    @abstractmethod
    def list_scenes(self, aoi_geojson: dict, start: date, end: date, max_cloud: float) -> list:
        """Return [{'item_id','datetime','cloud_cover'}] sorted by datetime."""

    @abstractmethod
    def get_scene(self, aoi_geojson: dict, item_id: str, bands: list) -> SceneData:
        """Windowed read over the AOI only, reflectance-scaled, aligned to the 10 m grid."""

    def best_scene(self, aoi_geojson: dict, start: date, end: date, max_cloud: float) -> dict:
        scenes = self.list_scenes(aoi_geojson, start, end, max_cloud)
        if not scenes:
            raise NoImageryError(f"No Sentinel-2 scenes found between {start} and {end} "
                                 f"with cloud cover <= {max_cloud:.0f}%.")
        return min(scenes, key=lambda s: (s["cloud_cover"] if s["cloud_cover"] is not None else 100.0))


# Logical band name -> Earth Search v1 asset key
EARTH_SEARCH_ASSETS = {"blue": "blue", "green": "green", "red": "red", "rededge1": "rededge1",
                       "nir": "nir", "swir1": "swir16", "swir2": "swir22", "scl": "scl"}


def aoi_hash(aoi_geojson: dict) -> str:
    return hashlib.sha1(json.dumps(aoi_geojson, sort_keys=True).encode()).hexdigest()[:16]


class EarthSearchProvider(SatelliteProvider):
    """Sentinel-2 L2A COGs via Element84 Earth Search (no API key).

    NOTE: written against the Earth Search v1 STAC layout; verify against a live request in your
    environment (scale/offset are read from each asset's `raster:bands` metadata).
    """
    STAC_URL = "https://earth-search.aws.element84.com/v1"
    COLLECTION = "sentinel-2-l2a"

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or settings.cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self._items = {}

    def list_scenes(self, aoi_geojson, start, end, max_cloud):
        from pystac_client import Client
        from app.preprocessing.masking import validate_aoi_geojson
        geom = validate_aoi_geojson(aoi_geojson)
        client = Client.open(self.STAC_URL)
        search = client.search(collections=[self.COLLECTION], intersects=geom.__geo_interface__,
                               datetime=f"{start.isoformat()}/{end.isoformat()}",
                               query={"eo:cloud_cover": {"lt": max_cloud}}, max_items=200)
        out = []
        for item in search.items():
            self._items[item.id] = item
            out.append({"item_id": item.id, "datetime": item.datetime.isoformat(),
                        "cloud_cover": item.properties.get("eo:cloud_cover")})
        return sorted(out, key=lambda s: s["datetime"])

    def get_scene(self, aoi_geojson, item_id, bands):
        import rasterio
        from rasterio.warp import transform_bounds, transform_geom
        from rasterio.windows import from_bounds
        from shapely.geometry import shape as to_shape
        from app.preprocessing.masking import (aoi_mask, resample_to_shape, to_reflectance,
                                               validate_aoi_geojson)

        geom = validate_aoi_geojson(aoi_geojson)
        item = self._items.get(item_id)
        if item is None:
            raise NoImageryError(f"Unknown scene {item_id}; call list_scenes first.")
        key = f"{item_id}_{'-'.join(sorted(bands))}_{aoi_hash(aoi_geojson)}.npz"
        path = os.path.join(self.cache_dir, key)

        pre = ["Windowed COG read over AOI bounding box", "Reflectance = DN*scale+offset from asset metadata",
               "SCL-based cloud/invalid masking", "Bilinear resample of 20 m bands to 10 m grid"]
        if os.path.exists(path):
            z = np.load(path, allow_pickle=True)
            meta = z["meta"].item()
            return SceneData(item_id, meta["datetime"], meta["cloud_cover"],
                             {b: z[f"band_{b}"] for b in bands}, z["scl"],
                             Affine(*meta["transform"]), meta["crs"], z["inside_aoi"], 10.0, pre + ["cache hit"])

        want = list(bands) + ["scl"]
        arrays, ref_tf, ref_crs, ref_shape = {}, None, None, None
        # read the 10 m band 'nir' (or first 10 m band) first so we know the target grid
        order = sorted(want, key=lambda b: 0 if b in ("red", "green", "blue", "nir") else 1)
        for b in order:
            if b not in EARTH_SEARCH_ASSETS or EARTH_SEARCH_ASSETS[b] not in item.assets:
                raise MissingBandError(f"Band '{b}' not available on scene {item_id}.")
            asset = item.assets[EARTH_SEARCH_ASSETS[b]]
            with rasterio.open(asset.href) as src:
                bounds = transform_bounds("EPSG:4326", src.crs, *geom.bounds)
                if ref_tf is None:
                    win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
                    ref_tf, ref_crs = src.window_transform(win), src.crs
                    data = src.read(1, window=win, boundless=True, fill_value=0)
                    ref_shape = data.shape
                else:
                    win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
                    data = src.read(1, window=win, boundless=True, fill_value=0)
            rb = (asset.extra_fields.get("raster:bands") or [{}])[0]
            if b == "scl":
                arrays[b] = resample_to_shape(data, ref_shape, categorical=True).astype(np.uint8)
            else:
                refl = to_reflectance(data, scale=rb.get("scale", 1e-4), offset=rb.get("offset", 0.0), nodata=rb.get("nodata", 0))
                arrays[b] = resample_to_shape(refl, ref_shape)
        geom_r = to_shape(transform_geom("EPSG:4326", ref_crs, geom.__geo_interface__))
        inside = aoi_mask(ref_shape, ref_tf, geom_r)
        np.savez_compressed(path, scl=arrays["scl"], inside_aoi=inside,
                            meta=np.array({"datetime": item.datetime.isoformat(),
                                           "cloud_cover": item.properties.get("eo:cloud_cover"),
                                           "transform": tuple(ref_tf)[:6], "crs": str(ref_crs)}, dtype=object),
                            **{f"band_{b}": arrays[b] for b in bands})
        return SceneData(item_id, item.datetime.isoformat(), item.properties.get("eo:cloud_cover"),
                         {b: arrays[b] for b in bands}, arrays["scl"], ref_tf, str(ref_crs), inside, 10.0, pre)
