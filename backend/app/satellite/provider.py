"""Data-provider abstraction. Nothing outside this package knows about STAC or COG URLs."""
import hashlib
import json
import logging
import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
from affine import Affine

from app.core.config import settings
from app.core.errors import MissingBandError, NoImageryError, SatQueryError

logger = logging.getLogger(__name__)


def sensor_identity_from_metadata(collection: Optional[str], platform: Optional[str]) -> tuple[str, Optional[str]]:
    """Return verified sensor identity only when catalog identity metadata supports it."""
    collection_value = str(collection or "").strip()
    platform_value = str(platform or "").strip()
    collection_tokens = collection_value.lower().replace("_", "-")
    platform_tokens = platform_value.lower().replace("_", "-")

    def family(value: str) -> Optional[str]:
        if "sentinel-2" in value or "sentinel 2" in value:
            return "sentinel-2"
        if "sentinel-1" in value or "sentinel 1" in value:
            return "other"
        return None

    collection_family = family(collection_tokens)
    platform_family = family(platform_tokens)
    if collection_family and platform_value and platform_family != collection_family:
        return "unknown", None
    if platform_family and collection_value and collection_family != platform_family:
        return "unknown", None
    if collection_family == "sentinel-2" or platform_family == "sentinel-2":
        return "sentinel-2", platform_value or collection_value
    if platform_value:
        return "other", platform_value
    if collection_family == "other":
        return "other", collection_value
    return "unknown", None


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


def reproject_array_to_grid(
    src_arr: np.ndarray,
    src_transform: Affine,
    src_crs: str,
    dst_transform: Affine,
    dst_crs: str,
    dst_shape: tuple[int, int],
    *,
    categorical: bool = False,
    area_average: bool = False,
) -> np.ndarray:
    """Warp an array onto an explicit destination grid.

    Rasterio is kept inside this provider module to preserve the project's
    geospatial dependency boundary. Continuous arrays use NaN nodata and
    bilinear resampling unless area averaging is requested; categorical
    arrays use zero nodata and nearest resampling.
    """
    src = np.asarray(src_arr)
    if src.ndim != 2 or len(dst_shape) != 2 or any(int(size) <= 0 for size in dst_shape):
        raise ValueError("Raster alignment requires 2D arrays and a positive destination shape.")
    if categorical:
        source = src.astype(np.uint8, copy=False)
        destination = np.zeros(tuple(dst_shape), dtype=np.uint8)
        src_nodata = dst_nodata = 0
    else:
        source = src.astype(np.float32, copy=False)
        destination = np.full(tuple(dst_shape), np.nan, dtype=np.float32)
        src_nodata = dst_nodata = np.nan

    try:
        import rasterio
        from rasterio.warp import Resampling, reproject

        reproject(
            source=source,
            destination=destination,
            src_transform=src_transform,
            src_crs=src_crs,
            src_nodata=src_nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=dst_nodata,
            resampling=(
                Resampling.nearest if categorical else
                Resampling.average if area_average else
                Resampling.bilinear
            ),
            init_dest_nodata=True,
        )
        if not categorical:
            # A nearest-neighbour validity warp prevents a target cell whose
            # nearest source sample is invalid (including boundless fill) from
            # becoming valid merely because bilinear interpolation found
            # surrounding valid samples.
            validity = np.zeros(tuple(dst_shape), dtype=np.uint8)
            reproject(
                source=np.isfinite(source).astype(np.uint8),
                destination=validity,
                src_transform=src_transform,
                src_crs=src_crs,
                src_nodata=0,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                dst_nodata=0,
                resampling=Resampling.nearest,
                init_dest_nodata=True,
            )
            destination[validity == 0] = np.nan
    except Exception as exc:
        raise ValueError(
            "Geospatial reprojection failed. Check rasterio/GDAL availability and "
            "that both CRS definitions and affine transforms are valid."
        ) from exc

    return destination


def write_fusion_geotiff(path: str, bands: dict[str, np.ndarray], transform: Affine, crs: str) -> None:
    """Write the auditable fusion feature stack as a georeferenced GeoTIFF.

    Rasterio use remains confined to this provider boundary.  NaN is represented
    by a documented float nodata value; the overlap mask is written separately.
    """
    import rasterio

    names = ("ndvi", "vv_db", "vh_db", "rvi")
    arrays = [np.asarray(bands[name], dtype=np.float32) for name in names]
    if not arrays or any(value.ndim != 2 or value.shape != arrays[0].shape for value in arrays):
        raise ValueError("Fusion GeoTIFF requires same-sized two-dimensional feature bands.")
    nodata = -9999.0
    with rasterio.open(path, "w", driver="GTiff", height=arrays[0].shape[0], width=arrays[0].shape[1],
                       count=len(arrays), dtype="float32", crs=crs, transform=transform,
                       nodata=nodata, compress="lzw") as dst:
        for index, (name, values) in enumerate(zip(names, arrays), start=1):
            dst.write(np.where(np.isfinite(values), values, nodata), index)
            dst.set_band_description(index, name)


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
    coverage_fraction: Optional[float] = None
    provider: Optional[str] = None
    collection: Optional[str] = None
    platform: Optional[str] = None
    processing_level: Optional[str] = None
    source: Optional[str] = None
    sensor: Optional[str] = None
    sensor_identity: str = "unknown"


class SatelliteProvider(ABC):
    @abstractmethod
    def list_scenes(self, aoi_geojson: dict, start: date, end: date, max_cloud: float) -> list:
        """Return [{'item_id','datetime','cloud_cover'}] sorted by datetime."""

    @abstractmethod
    def get_scene(self, aoi_geojson: dict, item_id: str, bands: list) -> SceneData:
        """Windowed read over the AOI only, reflectance-scaled, aligned to the 10 m grid."""

    def resolve_scene(self, aoi_geojson: dict, item_id: str, max_cloud: float,
                      start: Optional[date] = None, end: Optional[date] = None,
                      required_bands: Optional[list[str]] = None,
                      min_coverage: float = 0.99) -> dict:
        """Resolve and validate an explicitly selected scene without relying on cached discovery."""
        raise NoImageryError("The configured satellite provider cannot resolve an explicitly selected scene.")

    def get_selected_scene(self, aoi_geojson: dict, item_id: str, bands: list,
                           start: date, end: date, max_cloud: float,
                           *, use_utc_calendar_date: bool = False) -> SceneData:
        metadata = self.resolve_scene(aoi_geojson, item_id, max_cloud, start, end, bands)
        scene = self.get_scene(aoi_geojson, item_id, bands)
        if scene.item_id != item_id:
            raise NoImageryError(
                f"Provider returned scene {scene.item_id} after scene {item_id} was explicitly selected. "
                "The selected imagery was not used; analysis was stopped."
            )
        try:
            actual_datetime = datetime.fromisoformat(scene.datetime.replace("Z", "+00:00"))
            actual_date = (actual_datetime.astimezone(timezone.utc).date() if use_utc_calendar_date
                           else actual_datetime.date())
        except (TypeError, ValueError) as exc:
            raise NoImageryError(f"Selected scene {item_id} has unreadable acquisition-date metadata.") from exc
        metadata_date = metadata.get("utc_acquisition_date") if use_utc_calendar_date else metadata["acquisition_date"]
        if metadata_date is None:
            metadata_date = metadata["acquisition_date"]
        if actual_date != metadata_date or not start <= actual_date <= end:
            raise NoImageryError(
                f"Selected scene {item_id} returned inconsistent acquisition metadata. "
                "Refresh the scene list and try again."
            )
        if scene.cloud_cover is None or scene.cloud_cover > max_cloud:
            raise NoImageryError(
                f"Selected scene {item_id} does not satisfy the current cloud-cover limit. "
                "Select a scene within the current cloud filter."
            )
        scene.coverage_fraction = metadata.get("coverage")
        scene.provider = metadata.get("provider")
        scene.collection = metadata.get("collection")
        scene.platform = metadata.get("platform")
        scene.processing_level = metadata.get("processing_level")
        scene.source = metadata.get("source")
        scene.sensor_identity, scene.sensor = sensor_identity_from_metadata(
            scene.collection, scene.platform
        )
        return scene

    def best_scene(self, aoi_geojson: dict, start: date, end: date, max_cloud: float,
                    min_coverage: float = 0.99) -> dict:
        scenes = self.list_scenes(aoi_geojson, start, end, max_cloud)
        if not scenes:
            raise NoImageryError(f"No Sentinel-2 scenes found between {start} and {end} "
                                 f"with cloud cover <= {max_cloud:.0f}%.")
        # Prefer scenes with full/near-full AOI coverage
        covered = []
        for s in scenes:
            cov = s.get("coverage")
            if cov is not None and cov >= min_coverage:
                covered.append(s)
        if covered:
            best = min(covered, key=lambda s: (s["cloud_cover"] if s["cloud_cover"] is not None else 100.0))
            best = dict(best)
            best["coverage_status"] = "full"
            if best.get("coverage") is not None:
                best["coverage_fraction"] = best["coverage"]
            return best
        # If none fully cover, check if any have partial coverage
        partial = [s for s in scenes if s.get("coverage") is not None and s.get("coverage", 0) > 0]
        if partial:
            best = min(partial, key=lambda s: (-(s.get("coverage") or 0), s["cloud_cover"] if s["cloud_cover"] is not None else 100.0))
            best = dict(best)
            best["coverage_status"] = "partial"
            best["coverage_fraction"] = best.get("coverage")
            raise NoImageryError(
                f"No single Sentinel-2 scene fully covers the AOI (best coverage {best.get('coverage'):.1%} "
                f"for {best['item_id']}). Multiple tiles may be required.")
        # No coverage info available - fall back to old behavior but warn via exception context
        best = min(scenes, key=lambda s: (s["cloud_cover"] if s["cloud_cover"] is not None else 100.0))
        best = dict(best)
        best["coverage_status"] = "unknown"
        if best.get("coverage") is not None:
            best["coverage_fraction"] = best["coverage"]
        return best


class Sentinel1Provider(ABC):
    """Interface for Sentinel-1 products, kept separate from Sentinel-2 reflectance scenes."""

    @abstractmethod
    def list_scenes(self, aoi_geojson: dict, start: date, end: date) -> list[dict]:
        """Discover Sentinel-1 scenes and return acquisition/provenance metadata."""

    @abstractmethod
    def read_scene(self, aoi_geojson: dict, item_id: str, start: date, end: date) -> "Sentinel1RTCData":
        """Read one exact analysis-ready Sentinel-1 scene, clipped to the AOI."""


@dataclass
class Sentinel1RTCData:
    """One exact Sentinel-1 RTC acquisition clipped to the requested AOI."""
    item_id: str
    datetime: str
    platform: Optional[str]
    orbit_state: Optional[str]
    relative_orbit: Optional[int]
    processing_level: Optional[str]
    polarizations: list[str]
    bands: dict[str, np.ndarray]
    inside_aoi: np.ndarray
    transform: Affine
    crs: str
    resolution_m: float
    coverage_fraction: float


class PlanetaryComputerSentinel1Provider(Sentinel1Provider):
    """Sentinel-1 IW RTC products from Microsoft's Planetary Computer.

    This provider deliberately exposes RTC gamma-naught data, never raw GRD.
    Raster I/O remains in this module to honor the project's rasterio boundary.
    """
    STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
    COLLECTION = "sentinel-1-rtc"
    SAS_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

    def list_scenes(self, aoi_geojson: dict, start: date, end: date) -> list[dict]:
        from pystac_client import Client
        from shapely.geometry import shape

        aoi = shape(aoi_geojson)
        try:
            catalog = Client.open(self.STAC_URL)
            items = catalog.search(
                collections=[self.COLLECTION],
                intersects=aoi_geojson,
                datetime=f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
                max_items=100,
            ).items()
            scenes = []
            for item in items:
                props = item.properties or {}
                acquisition_time = props.get("datetime") or (item.datetime.isoformat() if item.datetime else None)
                if not acquisition_time:
                    continue
                footprint = shape(item.geometry) if item.geometry else None
                coverage = (float(aoi.intersection(footprint).area / aoi.area)
                            if footprint is not None and aoi.area > 0 else 0.0)
                assets = item.assets or {}
                pols = sorted(name.upper() for name in ("vv", "vh", "hh", "hv") if name in assets)
                scenes.append({
                    "item_id": item.id,
                    "datetime": acquisition_time,
                    "provider": "Microsoft Planetary Computer",
                    "collection": self.COLLECTION,
                    "platform": props.get("platform"),
                    "processing_level": props.get("s1:processing_level"),
                    "processing_product": "RTC",
                    "product_type": props.get("sar:product_type"),
                    "instrument_mode": props.get("sar:instrument_mode"),
                    "orbit_state": props.get("sat:orbit_state"),
                    "relative_orbit": props.get("sat:relative_orbit"),
                    "polarizations": pols,
                    "coverage_fraction": max(0.0, min(1.0, coverage)),
                    "required_polarizations_available": "VV" in pols and "VH" in pols,
                    "analysis_supported": (
                        str(props.get("s1:processing_level")) == "1"
                        and props.get("sar:product_type") == "GRD"
                        and props.get("sar:instrument_mode") == "IW"
                        and "VV" in pols and "VH" in pols
                    ),
                })
            return sorted(scenes, key=lambda item: item["datetime"])
        except Exception as exc:
            raise NoImageryError(
                "Sentinel-1 RTC catalog search failed. Check connectivity and retry; no scene was selected."
            ) from exc

    def read_scene(self, aoi_geojson: dict, item_id: str, start: date, end: date) -> Sentinel1RTCData:
        """Read exactly item_id, requiring a full-footprint VV/VH RTC scene."""
        from pystac_client import Client
        from shapely.geometry import shape

        aoi = shape(aoi_geojson)
        try:
            catalog = Client.open(self.STAC_URL)
            matches = list(catalog.search(
                collections=[self.COLLECTION], ids=[item_id], intersects=aoi_geojson, max_items=2
            ).items())
        except Exception as exc:
            raise NoImageryError("Sentinel-1 scene resolution failed. Refresh the scene list and retry.") from exc
        if len(matches) != 1 or matches[0].id != item_id:
            raise NoImageryError(f"Selected Sentinel-1 scene {item_id} could not be resolved exactly.")
        item = matches[0]
        props = item.properties or {}
        acquisition_time = props.get("datetime") or (item.datetime.isoformat() if item.datetime else None)
        try:
            actual_datetime = datetime.fromisoformat(acquisition_time.replace("Z", "+00:00"))
            if actual_datetime.tzinfo is None:
                raise ValueError("Acquisition timestamp has no timezone.")
            acquisition_date = actual_datetime.astimezone(timezone.utc).date()
        except (AttributeError, ValueError) as exc:
            raise NoImageryError("Selected Sentinel-1 scene has unreadable acquisition-time metadata.") from exc
        if not start <= acquisition_date <= end:
            raise NoImageryError(
                f"Selected Sentinel-1 scene {item_id} is outside the requested acquisition date range."
            )
        if (props.get("sar:product_type") != "GRD" or props.get("sar:instrument_mode") != "IW"
                or str(props.get("s1:processing_level")) != "1"):
            raise NoImageryError("Selected scene is not a supported Sentinel-1 IW RTC product.")
        footprint = shape(item.geometry) if item.geometry else None
        coverage = float(aoi.intersection(footprint).area / aoi.area) if footprint is not None and aoi.area > 0 else 0.0
        if coverage < 0.999:
            raise NoImageryError(
                f"Selected Sentinel-1 scene covers only {coverage:.1%} of the AOI. Choose a scene that fully covers it."
            )
        if not all(name in (item.assets or {}) for name in ("vv", "vh")):
            raise MissingBandError("Selected Sentinel-1 scene does not contain both VV and VH assets.")

        try:
            import httpx
            import rasterio
            from rasterio.mask import mask
            from rasterio.features import geometry_mask
            from rasterio.warp import transform_geom

            bands: dict[str, np.ndarray] = {}
            out_transform = None
            out_crs = None
            inside_aoi = None
            resolution = 10.0
            for name in ("vv", "vh"):
                asset_href = item.assets[name].href
                response = httpx.get(self.SAS_SIGN_URL, params={"href": asset_href}, timeout=30.0)
                response.raise_for_status()
                signed_href = response.json().get("href")
                if not isinstance(signed_href, str) or not signed_href.startswith("https://"):
                    raise ValueError("The data provider did not return a signed asset URL.")
                with rasterio.open(signed_href) as source:
                    if not source.crs or not source.crs.is_projected:
                        raise ValueError("Sentinel-1 RTC asset does not use a projected CRS.")
                    try:
                        unit_name, unit_to_metre = source.crs.linear_units_factor
                        if not math.isfinite(float(unit_to_metre)) or float(unit_to_metre) <= 0:
                            raise ValueError("Projected CRS has no usable linear unit conversion.")
                    except Exception as exc:
                        raise ValueError("Could not determine asset CRS units for pixel resolution.") from exc
                    projected_aoi = transform_geom("EPSG:4326", source.crs, aoi_geojson)
                    min_x, min_y, max_x, max_y = shape(projected_aoi).bounds
                    if (min_x < source.bounds.left or min_y < source.bounds.bottom
                            or max_x > source.bounds.right or max_y > source.bounds.top):
                        raise ValueError("Sentinel-1 RTC asset bounds do not fully cover the AOI.")
                    pixels, transform = mask(source, [projected_aoi], crop=True, filled=False)
                    values = np.asarray(pixels[0].filled(np.nan), dtype=np.float32)
                    valid = (~np.ma.getmaskarray(pixels[0]) & np.isfinite(values))
                    if source.nodata is not None:
                        valid &= values != float(source.nodata)
                    values[~valid] = np.nan
                    if out_transform is None:
                        out_transform, out_crs = transform, source.crs.to_string()
                        resolution = float((abs(source.transform.a) * abs(source.transform.e)) ** 0.5 * float(unit_to_metre))
                        inside_aoi = geometry_mask(
                            [projected_aoi], out_shape=values.shape, transform=transform, invert=True
                        )
                    elif values.shape != bands["VV"].shape or transform != out_transform or source.crs.to_string() != out_crs:
                        raise ValueError("VV and VH assets do not share an identical geospatial grid.")
                    bands[name.upper()] = values
            valid_inside = inside_aoi & np.isfinite(bands["VV"]) & np.isfinite(bands["VH"])
            denominator = int(np.count_nonzero(inside_aoi))
            if denominator == 0 or not np.any(valid_inside):
                raise NoImageryError("The selected Sentinel-1 scene has no valid VV/VH pixels inside the AOI.")
            return Sentinel1RTCData(
                item_id=item.id,
                datetime=acquisition_time,
                platform=props.get("platform"),
                orbit_state=props.get("sat:orbit_state"),
                relative_orbit=props.get("sat:relative_orbit"),
                processing_level=str(props.get("s1:processing_level")) if props.get("s1:processing_level") is not None else None,
                polarizations=["VV", "VH"],
                bands=bands,
                inside_aoi=inside_aoi,
                transform=out_transform,
                crs=out_crs,
                resolution_m=resolution,
                coverage_fraction=max(0.0, min(1.0, coverage)),
            )
        except SatQueryError:
            raise
        except Exception as exc:
            raise NoImageryError(
                "Could not read the selected Sentinel-1 RTC assets. Check data access, asset readability, and retry."
            ) from exc


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
    PROVIDER_NAME = "Element84 Earth Search"

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or settings.cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self._items = {}

    def _scene_catalog_metadata(self, item) -> dict:
        collection = getattr(item, "collection_id", None)
        properties = getattr(item, "properties", {}) or {}
        platform = properties.get("platform")
        sensor_identity, sensor = sensor_identity_from_metadata(collection, platform)
        processing_level = properties.get("processing:level") or properties.get("s2:product_type")
        return {
            "source": sensor,
            "provider": self.PROVIDER_NAME,
            "collection": collection,
            "platform": platform,
            "processing_level": processing_level,
            "sensor": sensor,
            "sensor_identity": sensor_identity,
        }

    def list_scenes(self, aoi_geojson, start, end, max_cloud):
        from pystac_client import Client
        from app.preprocessing.masking import validate_aoi_geojson
        from shapely.geometry import shape as to_shape
        from shapely.ops import transform as shp_transform
        geom = validate_aoi_geojson(aoi_geojson)
        # Use equirectangular approximation around AOI centroid for area ratios (no pyproj dependency).
        # This avoids degree-based planar area distortion; ratios are accurate for typical AOI sizes.
        try:
            c = geom.centroid
            lat0 = float(c.y)
            lon0 = float(c.x)
            cos_lat = math.cos(math.radians(lat0))
            def _to_local(x, y, z=None):
                return ((x - lon0) * cos_lat, (y - lat0))
            geom_local = shp_transform(_to_local, geom)
            use_local = geom_local.area > 0
        except Exception:
            geom_local = geom
            use_local = False
            def _to_local(x, y, z=None): return (x, y)
        try:
            client = Client.open(self.STAC_URL, request_modifier=lambda r: r)
        except Exception:
            try:
                client = Client.open(self.STAC_URL)
            except Exception as e:
                raise NoImageryError(f"Failed to open STAC client: {e}") from e
        try:
            search = client.search(collections=[self.COLLECTION], intersects=geom.__geo_interface__,
                                   datetime=f"{start.isoformat()}/{end.isoformat()}",
                                   query={"eo:cloud_cover": {"lte": max_cloud}}, max_items=50)
            out = []
            for item in search.items():
                self._items[item.id] = item
                coverage = None
                try:
                    if item.geometry is not None:
                        scene_geom = to_shape(item.geometry)
                        if geom.intersects(scene_geom):
                            inter = geom.intersection(scene_geom)
                            if use_local:
                                inter_local = shp_transform(_to_local, inter)
                                if geom_local.area > 0:
                                    coverage = float(inter_local.area / geom_local.area)
                            else:
                                if geom.area > 0:
                                    coverage = float(inter.area / geom.area)
                    elif item.bbox is not None:
                        # bbox is [minx,miny,maxx,maxy] in EPSG:4326
                        from shapely.geometry import box
                        scene_geom = box(*item.bbox)
                        if geom.intersects(scene_geom):
                            inter = geom.intersection(scene_geom)
                            if use_local:
                                inter_local = shp_transform(_to_local, inter)
                                if geom_local.area > 0:
                                    coverage = float(inter_local.area / geom_local.area)
                            else:
                                if geom.area > 0:
                                    coverage = float(inter.area / geom.area)
                except Exception:
                    coverage = None
                preview_url = None
                thumbnail = item.assets.get("thumbnail")
                if thumbnail is not None and isinstance(thumbnail.href, str):
                    preview_url = thumbnail.href
                out.append({"item_id": item.id, "datetime": item.datetime.isoformat(),
                            "cloud_cover": item.properties.get("eo:cloud_cover"),
                            "coverage": coverage, "preview_url": preview_url,
                            **self._scene_catalog_metadata(item)})
            return sorted(out, key=lambda s: s["datetime"])
        except Exception as e:
            raise NoImageryError(f"Failed to search satellite imagery: {e}") from e

    def resolve_scene(self, aoi_geojson, item_id, max_cloud, start=None, end=None,
                      required_bands=None, min_coverage=0.99):
        """Fetch an exact scene from the L2A catalog and validate its metadata for this AOI."""
        from pystac_client import Client
        from shapely.geometry import box, shape as to_shape
        from shapely.ops import transform as shp_transform
        from app.preprocessing.masking import validate_aoi_geojson

        if (start is None) != (end is None):
            raise NoImageryError("Selected-scene validation requires both ends of the requested date range.")
        geom = validate_aoi_geojson(aoi_geojson)
        try:
            try:
                client = Client.open(self.STAC_URL, request_modifier=lambda r: r)
            except Exception:
                client = Client.open(self.STAC_URL)
            search = client.search(collections=[self.COLLECTION], ids=[item_id], max_items=2)
            item = next((candidate for candidate in search.items() if candidate.id == item_id), None)
        except Exception as exc:
            raise NoImageryError(
                f"Could not resolve selected Sentinel-2 scene {item_id} from the catalog. "
                "Refresh the scene list and try again."
            ) from exc
        if item is None or item.collection_id != self.COLLECTION:
            raise NoImageryError(
                f"Selected scene {item_id} was not found in the Sentinel-2 L2A collection. "
                "Refresh the scene list and select an available scene."
            )

        raw_datetime = item.datetime or item.properties.get("datetime")
        if not raw_datetime:
            raise NoImageryError(f"Selected scene {item_id} has no acquisition date in the catalog.")
        try:
            acquisition = raw_datetime if isinstance(raw_datetime, datetime) else datetime.fromisoformat(str(raw_datetime).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise NoImageryError(f"Selected scene {item_id} has invalid acquisition-date metadata.") from exc
        acquisition_date = acquisition.date()
        utc_acquisition_date = acquisition.astimezone(timezone.utc).date()
        if start is not None and not start <= acquisition_date <= end:
            raise NoImageryError(
                f"Selected scene {item_id} was acquired on {acquisition_date}, outside the requested "
                f"single-date range {start} to {end}. Select a scene from that date range."
            )

        cloud_cover = item.properties.get("eo:cloud_cover")
        try:
            cloud_cover = float(cloud_cover)
        except (TypeError, ValueError):
            cloud_cover = math.nan
        if not math.isfinite(cloud_cover):
            raise NoImageryError(
                f"Cloud cover is unavailable for selected scene {item_id}; it cannot be checked against "
                f"the {max_cloud:.0f}% limit. Select a scene with known cloud metadata."
            )
        if cloud_cover > max_cloud:
            raise NoImageryError(
                f"Selected scene {item_id} has {cloud_cover:.1f}% cloud cover, above the "
                f"{max_cloud:.0f}% limit. Select a scene within the current cloud filter."
            )

        scene_geometry = to_shape(item.geometry) if item.geometry is not None else (box(*item.bbox) if item.bbox else None)
        coverage = 0.0
        if scene_geometry is not None and geom.intersects(scene_geometry) and geom.area > 0:
            centroid = geom.centroid
            lon0, lat0 = float(centroid.x), float(centroid.y)
            cos_lat = math.cos(math.radians(lat0))
            def to_local(x, y, z=None):
                return ((x - lon0) * cos_lat, y - lat0)
            geom_local = shp_transform(to_local, geom)
            intersection_local = shp_transform(to_local, geom.intersection(scene_geometry))
            if geom_local.area > 0:
                coverage = float(intersection_local.area / geom_local.area)
        if coverage < min_coverage:
            raise NoImageryError(
                f"Selected scene {item_id} covers only {coverage:.1%} of the AOI; at least "
                f"{min_coverage:.0%} coverage is required. Select a scene that covers the full area."
            )

        required_assets = set(required_bands or ()) | {"scl"}
        missing = [band for band in sorted(required_assets)
                   if band not in EARTH_SEARCH_ASSETS or EARTH_SEARCH_ASSETS[band] not in item.assets]
        if missing:
            raise MissingBandError(
                f"Selected scene {item_id} is missing required Sentinel-2 assets: {', '.join(missing)}. "
                "Select another scene that provides the required bands."
            )

        self._items[item_id] = item
        return {
            "item_id": item.id,
            "datetime": acquisition.isoformat(),
            "acquisition_date": acquisition_date,
            "utc_acquisition_date": utc_acquisition_date,
            "cloud_cover": cloud_cover,
            **self._scene_catalog_metadata(item),
            "coverage": coverage,
            "data_available": True,
        }


    def get_scene(self, aoi_geojson, item_id, bands):
        import rasterio
        from rasterio.warp import transform_bounds, transform_geom
        from rasterio.windows import from_bounds
        from shapely.geometry import shape as to_shape
        from app.preprocessing.masking import (aoi_mask, to_reflectance,
                                               validate_aoi_geojson)

        geom = validate_aoi_geojson(aoi_geojson)
        item = self._items.get(item_id)
        if item is None:
            raise NoImageryError(f"Unknown scene {item_id}; call list_scenes first.")
        # Version the cache after replacing shape-based resampling with explicit
        # geospatial reprojection. Existing cache files remain untouched but unused.
        key = f"grid-v2_{item_id}_{'-'.join(sorted(bands))}_{aoi_hash(aoi_geojson)}.npz"
        path = os.path.join(self.cache_dir, key)

        pre = ["Windowed COG read over AOI bounding box", "Reflectance = DN*scale+offset from asset metadata",
               "SCL-based cloud/invalid masking", "Bilinear resample of 20 m bands to 10 m grid"]
        catalog_metadata = self._scene_catalog_metadata(item)
        if os.path.exists(path):
            z = np.load(path, allow_pickle=True)
            meta = z["meta"].item()
            return SceneData(item.id, meta["datetime"], meta["cloud_cover"],
                             {b: z[f"band_{b}"] for b in bands}, z["scl"],
                             Affine(*meta["transform"]), meta["crs"], z["inside_aoi"], 10.0,
                             pre + ["cache hit"], **catalog_metadata)

        # B08 is the explicit reference grid for every Sentinel-2 index, including
        # MNDWI. Keep it as an internal read when it is not an output band.
        want = list(dict.fromkeys(["nir", *bands, "scl"]))
        # Fail before opening any COG if an output band or the required reference
        # grid is absent. This preserves clear missing-band behavior while B08 is
        # loaded first for alignment.
        for b in list(dict.fromkeys([*bands, "nir", "scl"])):
            if b not in EARTH_SEARCH_ASSETS or EARTH_SEARCH_ASSETS[b] not in item.assets:
                raise MissingBandError(f"Band '{b}' not available on scene {item_id}.")
        arrays = {}
        ref_tf, ref_crs, ref_shape = None, None, None
        order = ["nir", *[b for b in want if b != "nir"]]
        try:
            from rasterio.env import Env
        except Exception:
            Env = None
        for b in order:
            if b not in EARTH_SEARCH_ASSETS or EARTH_SEARCH_ASSETS[b] not in item.assets:
                raise MissingBandError(f"Band '{b}' not available on scene {item_id}.")
            asset = item.assets[EARTH_SEARCH_ASSETS[b]]
            try:
                def read_window():
                    nonlocal ref_tf, ref_crs, ref_shape
                    with rasterio.open(asset.href) as src:
                        bounds = transform_bounds("EPSG:4326", src.crs, *geom.bounds)
                        win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
                        data = src.read(1, window=win, boundless=True, fill_value=0)
                        source_transform = src.window_transform(win)
                        source_crs = src.crs
                        if b == "nir":
                            ref_tf, ref_crs, ref_shape = source_transform, source_crs, data.shape
                        return data, source_transform, source_crs

                if Env is not None:
                    with Env(GDAL_HTTP_TIMEOUT='60', GDAL_HTTP_CONNECTTIMEOUT='15', VSI_CACHE='TRUE', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif,.jp2'):
                        data, source_transform, source_crs = read_window()
                else:
                    data, source_transform, source_crs = read_window()
            except Exception as e:
                exc_name = type(e).__name__
                msg = str(e).lower()
                # Sanitize href (never log full URLs with potential tokens)
                href_sanitized = asset.href.split('?')[0] if hasattr(asset, 'href') and asset.href else 'unknown'
                # Log original details for diagnostics (sanitized)
                try:
                    logger.warning("COG read failed: band=%s scene=%s href=%s error=%s: %s",
                                   b, item_id, href_sanitized, exc_name, str(e).split('?')[0])
                except Exception:
                    pass
                if 'timeout' in msg or 'timed out' in msg or 'cpl_http' in msg or 'curl' in msg:
                    raise NoImageryError(
                        f"Remote source timeout while reading band '{b}' from scene {item_id}. "
                        "The data source is slow or temporarily unavailable. "
                        "This failure is not necessarily retryable."
                    ) from e
                if 'connection' in msg or 'network' in msg or 'resolve' in msg or 'refused' in msg or 'failed to connect' in msg:
                    raise NoImageryError(
                        f"Network/connection failure while reading band '{b}' from scene {item_id}. "
                        "Check connectivity to the imagery source. This failure is not necessarily retryable."
                    ) from e
                if '404' in msg or 'not found' in msg or 'http error' in msg and '404' in msg:
                    raise NoImageryError(
                        f"Missing or unavailable asset/band '{b}' for scene {item_id}. "
                        "The selected scene does not provide this band or the asset is unavailable."
                    ) from e
                if 'rasterioioerror' in exc_name.lower() or 'rasterio' in exc_name.lower() or 'invalid' in msg or 'malformed' in msg:
                    raise NoImageryError(
                        f"Invalid or unreadable raster data for band '{b}' from scene {item_id}. "
                        "The asset may be malformed or corrupted. This failure is not retryable."
                    ) from e
                raise NoImageryError(
                    f"Failed to read asset '{b}' for scene {item_id}. "
                    "An error occurred while reading remote COG data. This failure may not be retryable."
                ) from e
            rb = (asset.extra_fields.get("raster:bands") or [{}])[0]
            if b == "scl":
                arrays[b] = reproject_array_to_grid(
                    data, source_transform, source_crs, ref_tf, ref_crs, ref_shape, categorical=True
                ).astype(np.uint8)
            else:
                refl = to_reflectance(data, scale=rb.get("scale", 1e-4), offset=rb.get("offset", 0.0), nodata=rb.get("nodata", 0))
                arrays[b] = reproject_array_to_grid(
                    refl, source_transform, source_crs, ref_tf, ref_crs, ref_shape
                )
        try:
            geom_r = to_shape(transform_geom("EPSG:4326", ref_crs, geom.__geo_interface__))
            inside = aoi_mask(ref_shape, ref_tf, geom_r)
            # Check if AOI is effectively not covered (all outside)
            if inside.size > 0 and not np.any(inside):
                raise NoImageryError(
                    f"AOI is not covered by the selected scene {item_id}. "
                    "The scene footprint does not intersect the area of interest. This failure is not retryable."
                )
            np.savez_compressed(path, scl=arrays["scl"], inside_aoi=inside,
                                meta=np.array({"datetime": item.datetime.isoformat(),
                                               "cloud_cover": item.properties.get("eo:cloud_cover"),
                                               "transform": tuple(ref_tf)[:6], "crs": str(ref_crs)}, dtype=object),
                                **{f"band_{b}": arrays[b] for b in bands})
            return SceneData(item.id, item.datetime.isoformat(), item.properties.get("eo:cloud_cover"),
                             {b: arrays[b] for b in bands}, arrays["scl"], ref_tf, str(ref_crs),
                             inside, 10.0, pre, **catalog_metadata)
        except NoImageryError:
            raise
        except Exception as e:
            try:
                logger.warning("Scene processing failed: scene=%s error=%s: %s", item_id, type(e).__name__, str(e).split('?')[0])
            except Exception:
                pass
            raise NoImageryError(
                f"Failed to process scene {item_id} for the requested AOI. "
                "The raster data could not be processed for this area. This failure may not be retryable."
            ) from e
