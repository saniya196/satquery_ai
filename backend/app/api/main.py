import csv
import io
import json
import math
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.classification.loader import get_classifier
from app.core.errors import CaptionModelUnavailableError, SatQueryError
from app.core.config import settings
from app.satellite.geotiff import inspect_geotiff
from app.llm.client import get_llm_client
from app.llm.explainer import make_llm_fn
from app.preprocessing.masking import validate_aoi_geojson
from app.query_engine.llm_parser import parse_query_smart
from app.query_engine.parser import clarification_message
from app.rendering.geo import bounds_wgs84
from app.rendering.layers import (
    colorize_classes,
    colorize_diff,
    colorize_hotspots,
    colorize_index,
    colorize_landcover,
    encode_png,
    legend_for,
)
from app.satellite.provider import (EarthSearchProvider, SatelliteProvider, Sentinel1Provider, UploadedRasterError,
                                    PlanetaryComputerSentinel1Provider, read_uploaded_raster,
                                    read_uploaded_raster_cube, read_uploaded_raster_region)
from app.classification.labels import BANDS as LAND_COVER_BANDS, LOGICAL_BANDS as LAND_COVER_LOGICAL_BANDS
from app.schemas.query import DateRange, Operation
from app.services import analysis, land_cover
from app.services.sar import summarize_rtc_scene
from app.services.fusion import temporal_separation_hours, fuse
from app.services.captioning import caption_scene
from app.services.compare import run_compare_operation
from app.storage.history import delete_history, get_history, list_history, save_history_job
from app.storage import jobs as job_store
from app.storage.artifacts import artifacts_dir, load_artifacts, save_artifacts
from app.validation.grounding import check_grounding
from app.investigation import run_investigation

app = FastAPI(title="SatQuery AI", version="0.1.0",
              description="Natural-language satellite analytics. The LLM interprets; the engine computes.")

_default_cors_origins = "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"
_cors_origins = [o.strip() for o in os.getenv("SATQUERY_CORS_ORIGINS", _default_cors_origins).split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

_provider: Optional[SatelliteProvider] = None
_sar_provider: Optional[Sentinel1Provider] = None
_jobs: dict = {}
_layer_store: dict = {}
_MAX_LAYER_JOBS = 20
_lock = threading.Lock()

# Place search is proxied through the API because Nominatim does not send CORS
# headers, so a browser cannot call it directly. The proxy also supplies the
# required User-Agent and enforces Nominatim's one-request-per-second policy.
_PLACE_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_PLACE_SEARCH_USER_AGENT = "SatQueryAI/0.1 (local development)"
_PLACE_SEARCH_CACHE_TTL_SECONDS = 300.0
_PLACE_SEARCH_MIN_INTERVAL_SECONDS = 1.0
_place_search_lock = threading.Lock()
_place_search_cache: dict[tuple[str, int], tuple[float, list[dict[str, str]]]] = {}
_last_place_search_at = 0.0


def _nominatim_place_search(query: str, limit: int) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"format": "jsonv2", "limit": str(limit), "q": query})
    request = urllib.request.Request(
        f"{_PLACE_SEARCH_URL}?{params}",
        headers={"User-Agent": _PLACE_SEARCH_USER_AGENT, "Accept-Language": "en"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "place_search_unavailable",
                "message": "Location search is temporarily unavailable. Try again, or choose the location on the map.",
            },
        ) from exc
    if not isinstance(payload, list):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "place_search_unavailable",
                "message": "Location search returned an unexpected response. Try again, or choose the location on the map.",
            },
        )
    results: list[dict[str, str]] = []
    for item in payload[:limit]:
        if not isinstance(item, dict):
            continue
        display_name = item.get("display_name")
        lat = item.get("lat")
        lon = item.get("lon")
        if isinstance(display_name, str) and display_name.strip() and lat is not None and lon is not None:
            results.append({"display_name": display_name.strip(), "lat": str(lat), "lon": str(lon)})
    return results


@app.on_event("startup")
def _on_startup():
    try:
        job_store.mark_interrupted_on_startup()
    except Exception:
        pass



def get_provider() -> SatelliteProvider:
    global _provider
    if _provider is None:
        _provider = EarthSearchProvider()
    return _provider


def get_sar_provider() -> Sentinel1Provider:
    global _sar_provider
    if _sar_provider is None:
        _sar_provider = PlanetaryComputerSentinel1Provider()
    return _sar_provider


def clean(obj: Any) -> Any:
    """Make results JSON-safe: NaN/inf -> None, numpy -> python."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def _store_layer_data(job_id: str, arrays: dict, raster: dict, operation: Operation):
    stored_arrays = dict(arrays)
    if operation == Operation.CHANGE_DETECTION:
        if "index" not in stored_arrays and "index_b" in stored_arrays:
            stored_arrays["index"] = stored_arrays["index_b"]
        if "classes" not in stored_arrays and "class_map" in stored_arrays:
            stored_arrays["classes"] = stored_arrays["class_map"]
    elif operation == Operation.LAND_COVER and "class_map" in stored_arrays:
        stored_arrays["landcover"] = stored_arrays["class_map"]
    _layer_store[job_id] = {**stored_arrays, **raster}
    while len(_layer_store) > _MAX_LAYER_JOBS:
        _layer_store.pop(next(iter(_layer_store)))


def _persist_artifacts(job_id: str, arrays: dict, raster: dict, operation: Operation) -> None:
    """Write array/raster outputs to the filesystem artifact store and record
    the reference in the job row so completed results survive a restart."""
    try:
        ref = save_artifacts(job_id, arrays, raster, operation)
        if ref is not None:
            job_store.update_job(
                job_id,
                artifacts_ref={"job_id": job_id, "meta_path": str(artifacts_dir() / job_id / "meta.json")},
            )
    except Exception:
        pass



class AOIRequest(BaseModel):
    aoi: dict


class ParseRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    reference_date: Optional[date] = None


class GroundingRequest(BaseModel):
    answer: str = Field(max_length=5000)
    facts: dict


class RunRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    aoi: dict
    reference_date: Optional[date] = None
    max_cloud: float = Field(default=40.0, ge=0, le=100)
    selected_scene_id: Optional[str] = Field(default=None, min_length=1, max_length=256)


class CompareRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    aoi_a: dict
    aoi_b: dict
    reference_date: Optional[date] = None
    max_cloud: float = Field(default=40.0, ge=0, le=100)


class DateRangeOverride(BaseModel):
    start: date
    end: date


class InvestigationRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    aoi: Optional[dict] = None
    reference_date: Optional[date] = None
    max_cloud: float = Field(default=40.0, ge=0, le=100)
    date_a: Optional[DateRangeOverride] = None
    date_b: Optional[DateRangeOverride] = None
    series_range: Optional[DateRangeOverride] = None


class ImageryScenesRequest(BaseModel):
    aoi: dict
    start: date
    end: date
    max_cloud: float = Field(default=40.0, ge=0, le=100)


class SarSceneSearchRequest(BaseModel):
    aoi: dict
    start: date
    end: date


class SarAnalysisRequest(BaseModel):
    aoi: dict
    selected_scene_id: str = Field(min_length=1, max_length=256)
    start: date
    end: date


class FusionSceneSearchRequest(BaseModel):
    aoi: dict
    start: date
    end: date
    max_cloud: float = Field(default=40.0, ge=0, le=100)


class FusionAnalysisRequest(FusionSceneSearchRequest):
    optical_scene_id: str = Field(min_length=1, max_length=256)
    sar_scene_id: str = Field(min_length=1, max_length=256)


class CaptionAnalysisRequest(BaseModel):
    aoi: dict
    selected_scene_id: str = Field(min_length=1, max_length=256)
    start: date
    end: date
    max_cloud: float = Field(default=40.0, ge=0, le=100)


MAX_AOI_AREA_KM2 = 200.0
EARTH_RADIUS_KM = 6371.0088
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _aoi_measurements(geometry) -> tuple[float, dict, list]:
    """Approximate AOI area equirectangularly at its centroid; return area, center, bounds."""
    centroid = geometry.centroid
    center_lat, center_lon = float(centroid.y), float(centroid.x)
    lat_scale = math.pi * EARTH_RADIUS_KM / 180.0
    lon_scale = lat_scale * math.cos(math.radians(center_lat))

    def ring_area(coords) -> float:
        points = [(float(lon) * lon_scale, float(lat) * lat_scale) for lon, lat, *_ in coords]
        return abs(sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        ) / 2.0) if len(points) >= 3 else 0.0

    polygons = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    area = 0.0
    for polygon in polygons:
        area += ring_area(polygon.exterior.coords)
        area -= sum(ring_area(interior.coords) for interior in polygon.interiors)
    return max(0.0, area), {"lat": center_lat, "lon": center_lon}, list(geometry.bounds)


def _parse_uploaded_band_mapping(value: str) -> dict[str, int]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, {"code": "invalid_band_mapping", "message": "band_mapping must be valid JSON."}) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(422, {"code": "invalid_band_mapping", "message": "band_mapping must be a JSON object."})
    if set(parsed) != set(LAND_COVER_BANDS):
        raise HTTPException(422, {"code": "invalid_band_mapping", "message": f"band_mapping must contain exactly: {', '.join(LAND_COVER_BANDS)}."})
    if any(isinstance(index, bool) or not isinstance(index, int) for index in parsed.values()):
        raise HTTPException(422, {"code": "invalid_band_mapping", "message": "Band indexes must be positive integers."})
    mapping = {str(logical): int(parsed[logical]) for logical in LAND_COVER_BANDS}
    if any(index < 1 for index in mapping.values()) or len(set(mapping.values())) != len(mapping):
        raise HTTPException(422, {"code": "invalid_band_mapping", "message": "Band indexes must be positive and unique."})
    return mapping


def _validate_aoi_size(aoi: dict):
    try:
        geometry = validate_aoi_geojson(aoi)
    except SatQueryError as e:
        raise HTTPException(422, {"code": e.code, "message": e.message})
    area_km2, center, bounds = _aoi_measurements(geometry)
    if area_km2 > MAX_AOI_AREA_KM2:
        raise HTTPException(422, {
            "code": "aoi_too_large",
            "message": f"AOI is {area_km2:.1f} km²; please select a smaller area (maximum {MAX_AOI_AREA_KM2:.0f} km²).",
        })
    return geometry, area_km2, center, bounds


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/evaluation/land-cover")
def land_cover_evaluation():
    """Expose the checked-in EuroSAT metrics without claiming a local reevaluation."""
    roots = (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[2])
    metrics_path = next((root / "models" / "metrics.json" for root in roots
                         if (root / "models" / "metrics.json").is_file()), None)
    if metrics_path is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "evaluation_report_unavailable",
                "message": "The checked-in land-cover evaluation report is not available in this deployment.",
            },
        )
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "evaluation_report_unavailable",
                "message": "The checked-in land-cover evaluation report could not be read.",
            },
        ) from exc

    try:
        ten_class = metrics["test_10class"]
        four_class = metrics["test_product_4class"]
        test_samples = sum(int(item["support"]) for item in ten_class["per_class"].values())
        results = {
            "accuracy_10_class": float(ten_class["accuracy"]),
            "macro_f1_10_class": float(ten_class["macro_f1"]),
            "accuracy_4_class": float(four_class["accuracy"]),
            "macro_f1_4_class": float(four_class["macro_f1"]),
            "expected_calibration_error": float(metrics["ece"]),
            "accuracy_gaussian_noise_sd_0_01": float(metrics["robustness"]["gaussian noise sd=0.01"]["accuracy"]),
        }
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "evaluation_report_invalid",
                "message": "The checked-in land-cover evaluation report is incomplete or invalid.",
            },
        ) from exc

    return {
        "dataset": "EuroSAT",
        "test_samples": test_samples,
        "source": "models/metrics.json and models/MODEL_CARD.md",
        "reported_artifact_only": True,
        "reproduced_by_this_endpoint": False,
        "results": results,
        "limitations": [
            "The checkpoint report describes a held-out EuroSAT test split; this endpoint does not rerun the evaluation.",
            "The model was trained on Sentinel-2 L1C imagery and is applied to Sentinel-2 L2A, so domain shift is possible.",
            "Accuracy on Indian landscapes is unmeasured; these dataset metrics are not accuracy estimates for an AOI.",
            "The noise result is the reported test accuracy with Gaussian noise standard deviation 0.01 applied to the input bands.",
            "Model softmax confidence is not ground-truth accuracy.",
        ],
    }


@app.get("/places/search")
def places_search(q: str, limit: int = 5):
    global _last_place_search_at
    query = q.strip()
    if len(query) < 2:
        return []
    if len(query) > 200:
        raise HTTPException(422, {"code": "place_query_too_long", "message": "Search text is too long."})
    bounded_limit = max(1, min(limit, 10))
    cache_key = (query.casefold(), bounded_limit)
    now = time.monotonic()
    with _place_search_lock:
        cached = _place_search_cache.get(cache_key)
        if cached and now - cached[0] < _PLACE_SEARCH_CACHE_TTL_SECONDS:
            return cached[1]
        wait = max(0.0, _PLACE_SEARCH_MIN_INTERVAL_SECONDS - (now - _last_place_search_at))
        _last_place_search_at = now + wait
    if wait > 0:
        time.sleep(wait)
    results = _nominatim_place_search(query, bounded_limit)
    with _place_search_lock:
        _place_search_cache[cache_key] = (time.monotonic(), results)
        if len(_place_search_cache) > 256:
            oldest_key = min(_place_search_cache, key=lambda key: _place_search_cache[key][0])
            _place_search_cache.pop(oldest_key, None)
    return results


@app.post("/aoi/validate")
def aoi_validate(req: AOIRequest):
    geom, area_km2, center, bounds = _validate_aoi_size(req.aoi)
    return {"valid": True, "bounds": bounds, "geometry_type": geom.geom_type,
            "area_km2": area_km2, "centre": center}


@app.post("/geotiff/inspect")
async def geotiff_inspect(file: UploadFile = File(...)):
    filename = file.filename or "uploaded.tif"
    if not (filename.lower().endswith(".tif") or filename.lower().endswith(".tiff")):
        return {
            "valid": False,
            "filename": filename,
            "errors": ["Only .tif and .tiff GeoTIFF files are supported."],
        }
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        return {"valid": False, "filename": filename,
                "errors": [f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."]}
    meta = inspect_geotiff(io.BytesIO(content), filename=filename)
    return {
        "valid": meta.is_valid_geotiff,
        "filename": meta.filename,
        "format": meta.format,
        "width": meta.width,
        "height": meta.height,
        "band_count": meta.band_count,
        "bands": meta.bands_detected,
        "crs": meta.crs,
        "resolution_m": meta.resolution_m,
        "data_type": meta.data_type,
        "size_bytes": len(content),
        "nodata": meta.nodata,
        "geospatial_valid": bool(meta.crs and meta.resolution_m),
        "errors": meta.errors,
    }


def _uploaded_result(meta, raster, filename: str, band: int) -> dict:
    finite = np.isfinite(raster.data)
    values = raster.data[finite]
    valid_count = int(values.size)
    total_count = int(raster.data.size)
    area_km2 = None
    area_note = "Area estimate unavailable because the CRS linear units are not metres."
    if raster.linear_units and raster.linear_units.lower() in {"metre", "metres", "meter", "meters"}:
        area_km2 = valid_count * abs(raster.transform.a * raster.transform.e) / 1_000_000.0
        area_note = "Area estimated from valid-pixel count and the uploaded raster affine transform."

    stats = {
        "band": band,
        "valid_pixel_count": valid_count,
        "total_pixel_count": total_count,
        "valid_pixel_fraction": valid_count / total_count,
        "minimum": float(values.min()),
        "maximum": float(values.max()),
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "standard_deviation": float(values.std()),
        "analysed_area_km2": area_km2,
    }
    return {
        "operation": "uploaded_single_band_statistics",
        "source": {
            "filename": filename,
            "format": meta.format,
            "width": raster.width,
            "height": raster.height,
            "band_count": raster.band_count,
            "selected_band": band,
            "data_type": raster.dtype,
            "crs": raster.crs,
            "transform": list(tuple(raster.transform)[:6]),
            "resolution": {"x": raster.resolution_x, "y": raster.resolution_y,
                            "units": raster.linear_units},
            "nodata": raster.nodata,
            "bounds": list(raster.bounds),
        },
        "evidence": {
            "source": "user-uploaded GeoTIFF",
            "item_id": None,
            "dates": [],
            "bands": [f"band_{band}"],
            "formula": None,
            "preprocessing": ["Read selected band from uploaded GeoTIFF",
                               "Excluded nodata and non-finite pixels"],
            "valid_pixel_fraction": stats["valid_pixel_fraction"],
            "metrics": stats,
            "area_note": area_note,
        },
        "stats": stats,
    }


def _uploaded_region_result(meta, raster, filename: str, band: int, region: dict[str, float]) -> dict:
    result = _uploaded_result(meta, raster, filename, band)
    result["operation"] = "uploaded_region_statistics"
    result["region"] = {
        "coordinate_convention": "axis-aligned bounding box in the uploaded raster CRS",
        "crs": raster.crs,
        "requested": region,
        "pixel_window_bounds": list(raster.bounds),
        "pixel_window": {"width": raster.width, "height": raster.height},
    }
    result["evidence"]["formula"] = "Descriptive statistics over finite pixels in the requested raster-CRS region."
    result["evidence"]["region"] = result["region"]
    result["evidence"]["preprocessing"] = [
        "Read only the raster window intersecting the requested region",
        "Excluded nodata and non-finite pixels",
    ]
    result["source"]["region_crs"] = raster.crs
    return result


def _uploaded_source(raster, filename: str, acquisition_date: date, band: int) -> dict:
    return {
        "filename": filename,
        "date": acquisition_date.isoformat(),
        "format": "GeoTIFF",
        "width": raster.width,
        "height": raster.height,
        "band_count": raster.band_count,
        "selected_band": band,
        "data_type": raster.dtype,
        "crs": raster.crs,
        "transform": list(tuple(raster.transform)[:6]),
        "resolution": {"x": raster.resolution_x, "y": raster.resolution_y, "units": raster.linear_units},
        "nodata": raster.nodata,
        "bounds": list(raster.bounds),
    }


def _uploaded_change_description(metrics: dict, before_date: date, after_date: date,
                                 before_band: int, after_band: int) -> dict:
    mean_difference = metrics["difference_mean"]
    if mean_difference > 0:
        direction = "positive"
        direction_text = "increased"
    elif mean_difference < 0:
        direction = "negative"
        direction_text = "decreased"
    else:
        direction = "zero"
        direction_text = "showed no mean change"

    return {
        "text": (
            f"The selected band's mean raw pixel value {direction_text} from "
            f"{before_date.isoformat()} to {after_date.isoformat()}."
        ),
        "direction": direction,
        "mean_difference": mean_difference,
        "absolute_difference_mean": metrics["absolute_difference_mean"],
        "median_difference": metrics["difference_median"],
        "common_valid_pixel_fraction": metrics["common_valid_pixel_fraction"],
        "dates": [before_date.isoformat(), after_date.isoformat()],
        "bands": [f"band_{before_band}", f"band_{after_band}"],
        "source_units": None,
        "semantic_scope": "Raw pixel-value differences only; no semantic land-cover, NDVI, deforestation, or urbanization claim.",
    }


def _uploaded_change_result(before, after, before_filename: str, after_filename: str,
                            before_date: date, after_date: date, before_band: int, after_band: int) -> dict:
    if before.crs != after.crs:
        raise UploadedRasterError("incompatible_crs", "Before and after rasters must use equivalent CRS definitions.")
    if (before.width, before.height) != (after.width, after.height):
        raise UploadedRasterError("incompatible_dimensions", "Before and after rasters must have identical dimensions.")
    if not np.allclose(tuple(before.transform)[:6], tuple(after.transform)[:6], rtol=0.0, atol=1e-9):
        raise UploadedRasterError("incompatible_transform", "Before and after rasters must have equivalent affine transforms.")
    if before.bounds != after.bounds:
        raise UploadedRasterError("no_spatial_overlap", "Before and after rasters do not share the same spatial extent.")

    common = np.isfinite(before.data) & np.isfinite(after.data)
    common_count = int(common.sum())
    total_count = int(common.size)
    if common_count == 0:
        raise UploadedRasterError("no_common_valid_pixels", "The before and after rasters have no pixels valid on both dates.")
    difference = after.data[common] - before.data[common]
    absolute_difference = np.abs(difference)
    metrics = {
        "total_pixel_count": total_count,
        "before_valid_pixel_count": int(np.isfinite(before.data).sum()),
        "after_valid_pixel_count": int(np.isfinite(after.data).sum()),
        "common_valid_pixel_count": common_count,
        "common_valid_pixel_fraction": common_count / total_count,
        "difference_minimum": float(difference.min()),
        "difference_maximum": float(difference.max()),
        "difference_mean": float(difference.mean()),
        "difference_median": float(np.median(difference)),
        "difference_standard_deviation": float(difference.std()),
        "absolute_difference_mean": float(absolute_difference.mean()),
        "absolute_difference_median": float(np.median(absolute_difference)),
        "absolute_difference_maximum": float(absolute_difference.max()),
    }
    alignment = {
        "crs_equivalent": True,
        "dimensions_identical": True,
        "affine_transform_equivalent": True,
        "spatial_overlap": True,
        "resampling": "none",
        "reprojection": "none",
    }
    sources = [
        _uploaded_source(before, before_filename, before_date, before_band),
        _uploaded_source(after, after_filename, after_date, after_band),
    ]
    description = _uploaded_change_description(metrics, before_date, after_date, before_band, after_band)
    return {
        "operation": "uploaded_raw_raster_change",
        "before_date": before_date.isoformat(),
        "after_date": after_date.isoformat(),
        "sources": sources,
        "alignment": alignment,
        "description": description,
        "evidence": {
            "source": "two user-uploaded GeoTIFF rasters",
            "item_ids": [],
            "dates": [before_date.isoformat(), after_date.isoformat()],
            "bands": [f"band_{before_band}", f"band_{after_band}"],
            "formula": "after - before",
            "preprocessing": [
                "Read each uploaded raster with its native nodata mask",
                "Compared only pixels valid on both dates",
                "No reprojection, resampling, cropping, or alignment correction",
            ],
            "valid_pixel_fraction": common_count / total_count,
            "thresholds": {},
            "metrics": metrics,
            "alignment": alignment,
            "description": description,
            "limitations": [
                "Differences are raw pixel-value differences in the source raster units.",
                "Source numeric units were not established by this endpoint.",
                "No Sentinel-2 index, semantic class, or change significance was inferred.",
            ],
        },
        "metrics": metrics,
    }


@app.post("/geotiff/analyze")
async def geotiff_analyze(
    file: UploadFile = File(...),
    band: int = Form(1),
    operation: str = Form("single_band_statistics"),
    region_min_x: str | None = Form(None),
    region_min_y: str | None = Form(None),
    region_max_x: str | None = Form(None),
    region_max_y: str | None = Form(None),
):
    """Analyse real pixels from one uploaded, georeferenced GeoTIFF band.

    This operation intentionally does not infer Sentinel-2 wavelengths or compute spectral indices.
    """
    filename = file.filename or "uploaded.tif"
    if not filename.lower().endswith((".tif", ".tiff")):
        raise HTTPException(415, {"code": "unsupported_file_type", "message": "Only .tif and .tiff GeoTIFF files are supported."})
    if operation not in {"single_band_statistics", "region_statistics"}:
        raise HTTPException(422, {"code": "unsupported_operation", "message": "Supported uploaded-raster operations are single_band_statistics and region_statistics."})
    if band < 1:
        raise HTTPException(422, {"code": "invalid_band", "message": "Band must be a positive integer."})
    region = None
    if operation == "region_statistics":
        values = {"min_x": region_min_x, "min_y": region_min_y, "max_x": region_max_x, "max_y": region_max_y}
        if any(value is None or not value.strip() for value in values.values()):
            raise HTTPException(422, {"code": "region_required", "message": "Region statistics require min_x, min_y, max_x, and max_y in the raster CRS."})
        try:
            region = {key: float(value) for key, value in values.items()}
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, {"code": "invalid_region", "message": "Region coordinates must be finite numbers in the raster CRS."}) from exc

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="satquery-upload-", suffix=".tif", delete=False) as temp:
            temp_path = temp.name
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, {"code": "file_too_large", "message": "Uploaded file exceeds the 100 MB limit."})
                temp.write(chunk)
        meta = inspect_geotiff(temp_path, filename=filename)
        if not meta.is_valid_geotiff:
            raise HTTPException(422, {"code": "invalid_geotiff", "message": "; ".join(meta.errors)})
        try:
            if operation == "region_statistics":
                raster = read_uploaded_raster_region(temp_path, band=band, region=region or {})
            else:
                raster = read_uploaded_raster(temp_path, band=band)
        except UploadedRasterError as exc:
            raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
        if operation == "region_statistics":
            return _uploaded_region_result(meta, raster, filename, band, region or {})
        return _uploaded_result(meta, raster, filename, band)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


@app.post("/geotiff/change")
async def geotiff_change(
    before_file: UploadFile = File(...),
    after_file: UploadFile = File(...),
    before_date: str = Form(...),
    after_date: str = Form(...),
    before_band: str = Form("1"),
    after_band: str = Form("1"),
):
    """Compare raw pixel values from two explicitly dated, uploaded GeoTIFF rasters."""
    uploads = ((before_file, "before"), (after_file, "after"))
    for upload, role in uploads:
        filename = upload.filename or f"{role}.tif"
        if not filename.lower().endswith((".tif", ".tiff")):
            raise HTTPException(415, {"code": "unsupported_file_type", "message": f"The {role} file must be a .tif or .tiff GeoTIFF."})
    try:
        parsed_before = date.fromisoformat(before_date)
        parsed_after = date.fromisoformat(after_date)
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_date", "message": "before_date and after_date must use YYYY-MM-DD format."}) from exc
    if parsed_after <= parsed_before:
        raise HTTPException(422, {"code": "invalid_date_order", "message": "after_date must be later than before_date."})
    try:
        parsed_before_band = int(before_band)
        parsed_after_band = int(after_band)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, {"code": "invalid_band", "message": "before_band and after_band must be positive integers."}) from exc
    if parsed_before_band < 1 or parsed_after_band < 1:
        raise HTTPException(422, {"code": "invalid_band", "message": "before_band and after_band must be positive integers."})

    temp_paths: list[str] = []
    try:
        for upload, role in uploads:
            with tempfile.NamedTemporaryFile(prefix=f"satquery-{role}-", suffix=".tif", delete=False) as temp:
                temp_paths.append(temp.name)
                size = 0
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, {"code": "file_too_large", "message": f"The {role} file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."})
                    temp.write(chunk)

        metadata = []
        for path, upload in zip(temp_paths, uploads):
            meta = inspect_geotiff(path, filename=upload[0].filename or f"{upload[1]}.tif")
            if not meta.is_valid_geotiff:
                raise HTTPException(422, {"code": "invalid_geotiff", "message": f"The {upload[1]} file is not a valid GeoTIFF: {'; '.join(meta.errors)}"})
            metadata.append(meta)
        try:
            before = read_uploaded_raster(temp_paths[0], band=parsed_before_band)
            after = read_uploaded_raster(temp_paths[1], band=parsed_after_band)
        except UploadedRasterError as exc:
            code = "no_common_valid_pixels" if exc.code == "no_valid_pixels" else exc.code
            message = "The before and after rasters have no pixels valid on both dates." if code == "no_common_valid_pixels" else exc.message
            raise HTTPException(422, {"code": code, "message": message}) from exc
        try:
            return _uploaded_change_result(
                before, after, before_file.filename or "before.tif", after_file.filename or "after.tif",
                parsed_before, parsed_after, parsed_before_band, parsed_after_band,
            )
        except UploadedRasterError as exc:
            raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
    finally:
        for path in temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


@app.post("/geotiff/land-cover")
async def geotiff_land_cover(
    file: UploadFile = File(...),
    band_mapping: str = Form(...),
    radiometry: str = Form(...),
):
    """Classify a user-mapped five-band reflectance GeoTIFF with the existing model."""
    filename = file.filename or "uploaded.tif"
    if not filename.lower().endswith((".tif", ".tiff")):
        raise HTTPException(415, {"code": "unsupported_file_type", "message": "Only .tif and .tiff GeoTIFF files are supported."})
    mapping = _parse_uploaded_band_mapping(band_mapping)
    if radiometry != "reflectance":
        raise HTTPException(422, {"code": "unsupported_radiometry", "message": "radiometry must be explicitly declared as 'reflectance'."})

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="satquery-land-cover-", suffix=".tif", delete=False) as temp:
            temp_path = temp.name
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, {"code": "file_too_large", "message": "Uploaded file exceeds the 100 MB limit."})
                temp.write(chunk)

        meta = inspect_geotiff(temp_path, filename=filename)
        if not meta.is_valid_geotiff:
            raise HTTPException(422, {"code": "invalid_geotiff", "message": "; ".join(meta.errors)})
        try:
            raster = read_uploaded_raster_cube(
                temp_path, band_mapping=mapping, band_order=LAND_COVER_BANDS, radiometry=radiometry,
            )
            classifier = get_classifier()
            return land_cover.run_uploaded_land_cover(raster.data, raster, filename, classifier, radiometry)
        except UploadedRasterError as exc:
            raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
        except SatQueryError as exc:
            status = 503 if exc.code == "model_unavailable" else 422
            raise HTTPException(status, {"code": exc.code, "message": exc.message}) from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


@app.post("/imagery/scenes")
def imagery_scenes(req: ImageryScenesRequest, provider: SatelliteProvider = Depends(get_provider)):
    _validate_aoi_size(req.aoi)
    if req.end < req.start:
        raise HTTPException(422, {"code": "invalid_date_range", "message": "End date must be on or after start date."})
    try:
        scenes = provider.list_scenes(req.aoi, req.start, req.end, req.max_cloud)
    except SatQueryError as e:
        raise HTTPException(422, {"code": e.code, "message": e.message})
    except Exception:
        raise HTTPException(502, {"code": "imagery_unavailable", "message": "Could not search satellite imagery right now."})
    items = []
    for scene in sorted(scenes, key=lambda item: item["datetime"])[:100]:
        preview_url = scene.get("preview_url")
        coverage = scene.get("coverage")
        items.append({
            "item_id": scene.get("item_id"),
            "datetime": scene.get("datetime"),
            "cloud_cover": scene.get("cloud_cover"),
            "sensor": "Sentinel-2 L2A",
            "collection": scene.get("collection") or "sentinel-2-l2a",
            "preview_url": preview_url if isinstance(preview_url, str) and preview_url else None,
            "coverage_fraction": float(coverage) if isinstance(coverage, (int, float)) and math.isfinite(float(coverage)) else None,
            "data_available": True,
        })
    return items


@app.post("/sar/scenes")
def sar_scenes(req: SarSceneSearchRequest,
               provider: Sentinel1Provider = Depends(get_sar_provider)):
    _validate_aoi_size(req.aoi)
    if req.end < req.start:
        raise HTTPException(422, {"code": "invalid_date_range", "message": "End date must be on or after start date."})
    try:
        return provider.list_scenes(req.aoi, req.start, req.end)
    except SatQueryError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc


@app.post("/sar/analyze")
def sar_analyze(req: SarAnalysisRequest,
                provider: Sentinel1Provider = Depends(get_sar_provider)):
    _, aoi_area_km2, _, _ = _validate_aoi_size(req.aoi)
    if req.end < req.start:
        raise HTTPException(422, {"code": "invalid_date_range", "message": "End date must be on or after start date."})
    item_id = req.selected_scene_id.strip()
    if not item_id:
        raise HTTPException(422, {"code": "invalid_selected_scene", "message": "Select a Sentinel-1 scene first."})
    job_id = uuid.uuid4().hex
    created = _now()
    query = "Sentinel-1 RTC VV/VH backscatter statistics"
    structured = {"operation": "sar_backscatter", "sensor": "sentinel-1", "selected_scene_id": item_id}
    try:
        scene = provider.read_scene(req.aoi, item_id, req.start, req.end)
        result = clean(summarize_rtc_scene(scene, aoi_area_km2))
        save_history_job(job_id, created, query, structured, req.aoi, "completed", result)
        return {"job_id": job_id, "status": "completed", "result": result}
    except SatQueryError as exc:
        save_history_job(job_id, created, query, structured, req.aoi, "failed",
                         {"error": {"code": exc.code, "message": exc.message}})
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:
        save_history_job(job_id, created, query, structured, req.aoi, "failed",
                         {"error": {"code": "sar_analysis_failed", "message": "Sentinel-1 analysis failed."}})
        raise HTTPException(502, {
            "code": "sar_analysis_failed", "message": "Sentinel-1 analysis failed. No result was produced."
        }) from exc


@app.post("/fusion/scenes")
def fusion_scenes(req: FusionSceneSearchRequest, optical_provider: SatelliteProvider = Depends(get_provider),
                  sar_provider: Sentinel1Provider = Depends(get_sar_provider)):
    """Discover only full-coverage, asset-complete source pairs within the configured time limit."""
    _validate_aoi_size(req.aoi)
    if req.end < req.start:
        raise HTTPException(422, {"code": "invalid_date_range", "message": "End date must be on or after start date."})
    try:
        optical = optical_provider.list_scenes(req.aoi, req.start, req.end, req.max_cloud)
        sar = sar_provider.list_scenes(req.aoi, req.start, req.end)
        pairs = []
        for s2 in optical:
            if float(s2.get("coverage") or 0) < 0.999:
                continue
            for s1 in sar:
                if float(s1.get("coverage_fraction") or 0) < 0.999 or not s1.get("required_polarizations_available") or not s1.get("analysis_supported"):
                    continue
                hours = temporal_separation_hours(s2.get("datetime"), s1.get("datetime"))
                if hours <= settings.fusion_max_temporal_separation_days * 24:
                    pairs.append({"optical": {"item_id": s2["item_id"], "datetime": s2["datetime"], "cloud_cover": s2.get("cloud_cover"), "coverage_fraction": s2.get("coverage")},
                                  "sar": {"item_id": s1["item_id"], "datetime": s1["datetime"], "coverage_fraction": s1.get("coverage_fraction"), "polarizations": s1.get("polarizations", [])},
                                  "temporal_separation_hours": hours,
                                  "max_temporal_separation_days": settings.fusion_max_temporal_separation_days})
        return {"pairs": sorted(pairs, key=lambda p: (p["temporal_separation_hours"], p["optical"]["datetime"])),
                "max_temporal_separation_days": settings.fusion_max_temporal_separation_days,
                "note": "Pairs are close in time, not simultaneous; dynamic conditions can differ between acquisitions."}
    except SatQueryError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc


@app.post("/fusion/analyze")
def fusion_analyze(req: FusionAnalysisRequest, optical_provider: SatelliteProvider = Depends(get_provider),
                   sar_provider: Sentinel1Provider = Depends(get_sar_provider)):
    _validate_aoi_size(req.aoi)
    if req.end < req.start:
        raise HTTPException(422, {"code": "invalid_date_range", "message": "End date must be on or after start date."})
    job_id, created = uuid.uuid4().hex, _now()
    structured = {"operation": "optical_sar_fusion", "sensor": "sentinel-2+sentinel-1",
                  "optical_scene_id": req.optical_scene_id, "sar_scene_id": req.sar_scene_id}
    query = "Sentinel-2 L2A + Sentinel-1 RTC feature-level fusion"
    try:
        optical = optical_provider.get_selected_scene(req.aoi, req.optical_scene_id.strip(), ["red", "nir"], req.start, req.end, req.max_cloud)
        sar = sar_provider.read_scene(req.aoi, req.sar_scene_id.strip(), req.start, req.end)
        output = artifacts_dir() / job_id / "sentinel2_sentinel1_fusion.tif"
        result, arrays, raster = fuse(optical, sar, output)
        result["evidence"]["aoi_area_km2"] = _aoi_measurements(validate_aoi_geojson(req.aoi))[0]
        result["limitations"] = ["The sources are not simultaneous; interpretation assumes conditions did not materially change during the stated separation.",
                                 "This is a feature stack, not a physically fused reflectance/backscatter measurement.",
                                 "SAR speckle and optical cloud masking can reduce overlap."]
        result = clean(result)
        save_history_job(job_id, created, query, structured, req.aoi, "completed", result)
        _persist_artifacts(job_id, arrays, raster, "optical_sar_fusion")
        return {"job_id": job_id, "status": "completed", "result": result}
    except SatQueryError as exc:
        save_history_job(job_id, created, query, structured, req.aoi, "failed", {"error": {"code": exc.code, "message": exc.message}})
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:
        save_history_job(job_id, created, query, structured, req.aoi, "failed", {"error": {"code": "fusion_failed", "message": "Optical/SAR fusion failed; no result was produced."}})
        raise HTTPException(502, {"code": "fusion_failed", "message": "Optical/SAR fusion failed; no result was produced."}) from exc


@app.post("/caption/analyze")
def caption_analyze(req: CaptionAnalysisRequest, provider: SatelliteProvider = Depends(get_provider)):
    """Render the selected Sentinel-2 AOI to true-color RGB and caption it with
    the local RSICD BLIP checkpoint. Real pixels only; the caption is model
    output, never a template, and every run is recorded in history."""
    _validate_aoi_size(req.aoi)
    if req.end < req.start:
        raise HTTPException(422, {"code": "invalid_date_range", "message": "End date must be on or after start date."})
    item_id = req.selected_scene_id.strip()
    if not item_id:
        raise HTTPException(422, {"code": "invalid_selected_scene", "message": "Select a Sentinel-2 scene first."})
    job_id = uuid.uuid4().hex
    created = _now()
    query = "Sentinel-2 scene caption (BLIP image-to-text)"
    structured = {"operation": "image_captioning", "sensor": "sentinel-2", "selected_scene_id": item_id}
    try:
        scene = provider.get_selected_scene(req.aoi, item_id, ["red", "green", "blue"],
                                            req.start, req.end, req.max_cloud)
        output_image = artifacts_dir() / job_id / "caption_scene.png"
        result = clean(caption_scene(scene, output_image_path=output_image))
        result["evidence"]["aoi_area_km2"] = _aoi_measurements(validate_aoi_geojson(req.aoi))[0]
        result["image_url"] = f"/caption/{job_id}/image.png"
        save_history_job(job_id, created, query, structured, req.aoi, "completed", result)
        return {"job_id": job_id, "status": "completed", "result": result, "image_url": result["image_url"]}
    except CaptionModelUnavailableError as exc:
        save_history_job(job_id, created, query, structured, req.aoi, "failed",
                         {"error": {"code": exc.code, "message": exc.message}})
        raise HTTPException(503, {"code": exc.code, "message": exc.message}) from exc
    except SatQueryError as exc:
        save_history_job(job_id, created, query, structured, req.aoi, "failed",
                         {"error": {"code": exc.code, "message": exc.message}})
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:
        save_history_job(job_id, created, query, structured, req.aoi, "failed",
                         {"error": {"code": "caption_failed", "message": "Scene captioning failed; no result was produced."}})
        raise HTTPException(502, {"code": "caption_failed", "message": "Scene captioning failed; no result was produced."}) from exc


@app.get("/caption/{job_id}/image.png")
def caption_image(job_id: str):
    """Serve the deterministic RGB rendering that was captioned for a job."""
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(404, "Caption image is not available for this job.")
    path = artifacts_dir() / job_id / "caption_scene.png"
    if not path.is_file():
        raise HTTPException(404, "Caption image is not available for this job.")
    return FileResponse(path, media_type="image/png")


@app.post("/query/parse")
def query_parse(req: ParseRequest):
    q = parse_query_smart(req.query, req.reference_date, get_llm_client())
    return {"structured_query": q.model_dump(mode="json"), "clarification": clarification_message(q)}


@app.post("/grounding/check")
def grounding_check(req: GroundingRequest):
    return check_grounding(req.answer, req.facts)


def _run_operation(q, aoi: dict, max_cloud: float, provider: SatelliteProvider, llm_fn,
                   selected_scene_id: Optional[str] = None) -> dict:
    if selected_scene_id and q.operation not in (Operation.INDEX_STATS, Operation.LAND_COVER):
        raise SatQueryError(
            "An explicitly selected scene supports only single-date index statistics and land-cover analysis. "
            "Clear the scene selection to run change detection or a time series."
        )
    if q.operation == Operation.CHANGE_DETECTION:
        return analysis.run_change(provider, aoi, q.date_a, q.date_b, q.index or "NDVI", q.thresholds or None,
                                   max_cloud, llm_fn=llm_fn)
    if q.operation == Operation.TIME_SERIES:
        return analysis.run_time_series(provider, aoi, q.series_range, q.index or "NDVI", max_cloud,
                                        llm_fn=llm_fn)
    if q.operation == Operation.INDEX_STATS:
        return analysis.run_index_stats(provider, aoi, q.date_a, q.index, max_cloud, llm_fn=llm_fn,
                                        selected_scene_id=selected_scene_id)
    if q.operation == Operation.LAND_COVER:
        return land_cover.run_land_cover(provider, aoi, q.date_a, get_classifier(), max_cloud,
                                         llm_fn=llm_fn, selected_scene_id=selected_scene_id)
    if q.operation == Operation.COMPARE_REGIONS:
        raise SatQueryError("compare_regions is not supported by /analysis/run. Use /analysis/compare with two AOIs.")
    raise SatQueryError(f"'{q.operation.value}' is not implemented in this build yet.")


# MGRS tile inside a STAC item id. Earth Search uses ids like "S2C_44QMD_20251018_0_L2A"
# while Copernicus-style ids carry an explicit "T" prefix ("..._T41PFT_...").
_MGRS_TILE_RE = re.compile(r"(?:^|_)(T?\d{2}[A-Z]{3})(?=_|$)")

_MAX_METADATA_VALUES = 3


def _format_duration(seconds: float) -> str:
    if seconds < 1:
        return "<1s"
    secs = int(seconds)
    m, s = divmod(secs, 60)
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _distinct_join(values: list[str]) -> str | None:
    """Join distinct values for display, or return None when there are none."""
    if not values:
        return None
    shown = values[:_MAX_METADATA_VALUES]
    label = ", ".join(shown)
    if len(values) > len(shown):
        label += f" +{len(values) - len(shown)} more"
    return label


def _scene_metadata(result: dict) -> tuple[str | None, str | None]:
    """Derive the provider tile and acquisition date from the evidence scenes.

    Returns (None, None) when the evidence does not establish them. Values from
    multi-scene analyses are listed rather than collapsed onto the first scene.
    """
    evidence = result.get("evidence") or {}
    scenes = evidence.get("scenes") or []
    tiles: list[str] = []
    dates: list[str] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        match = _MGRS_TILE_RE.search(str(scene.get("item_id") or ""))
        if match and match.group(1) not in tiles:
            tiles.append(match.group(1))
        raw_dt = scene.get("datetime")
        if raw_dt:
            try:
                label = datetime.fromisoformat(str(raw_dt).replace("Z", "+00:00")).strftime("%d %b %Y")
            except ValueError:
                label = str(raw_dt)[:10]
            if label not in dates:
                dates.append(label)
    return _distinct_join(tiles), _distinct_join(dates)


def _execute(job_id: str, q, aoi: dict, max_cloud: float, provider: SatelliteProvider,
             selected_scene_id: Optional[str] = None):
    start_time = time.time()
    coverage_info = None
    try:
        job_store.update_job(job_id, status="processing", progress={"percent": 10})
    except Exception:
        pass
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "processing"
            _jobs[job_id]["progress"] = {"percent": 10}
            if "stages" in _jobs[job_id] and len(_jobs[job_id]["stages"]) > 0:
                _jobs[job_id]["stages"][0]["status"] = "processing"
    try:
        llm_fn = make_llm_fn(get_llm_client())
        res = _run_operation(q, aoi, max_cloud, provider, llm_fn, selected_scene_id)
        arrays = res.pop("arrays", None)
        raster = res.pop("raster", None)
        result = clean(res)
        with _lock:
            job = _jobs[job_id]
            created = job["created"]
        save_history_job(job_id, created, q.raw_text, q.model_dump(mode="json"), aoi, "completed", result)

        total_dur = time.time() - start_time
        # Only the total runtime is measured. Per-stage timings are not instrumented,
        # so they are omitted rather than estimated from fractions of total_dur.
        elapsed = _format_duration(total_dur)

        # Tile and acquisition date come from the scene evidence actually used.
        tile_str, date_str = _scene_metadata(result)
        # Try to extract coverage from result evidence/metrics if present
        try:
            ev = result.get("evidence") if isinstance(result, dict) else None
            if isinstance(ev, dict):
                if ev.get("coverage") is not None:
                    coverage_info = ev.get("coverage")
                elif isinstance(ev.get("metrics"), dict) and ev["metrics"].get("coverage") is not None:
                    coverage_info = ev["metrics"].get("coverage")
        except Exception:
            pass
        if coverage_info is None and result.get("coverage") is not None:
            coverage_info = result.get("coverage")

        provider_info = {"name": "Sentinel-2", "tile": tile_str, "date": date_str}
        if coverage_info is not None:
            provider_info["coverage"] = coverage_info

        stages_done = [
            {"name": "Data Fetching (Sentinel-2)", "status": "completed"},
            {"name": "Preprocessing", "status": "completed"},
            {"name": "Analysis", "status": "completed"},
            {"name": "Results Ready", "status": "completed", "duration": elapsed},
        ]
        with _lock:
            if arrays is not None and raster is not None:
                _store_layer_data(job_id, arrays, raster, q.operation)
            if job_id in _jobs:
                _jobs[job_id].update(
                    status="completed",
                    result=result,
                    finished=_now(),
                    stages=stages_done,
                    provider_info=provider_info,
                    progress={"percent": 100},
                )
        # Persist raster artifacts so completed results survive a backend restart.
        if arrays is not None and raster is not None:
            _persist_artifacts(job_id, arrays, raster, q.operation)
        try:
            job_store.update_job(job_id, status="completed", stages=stages_done,
                                 provider_info=provider_info,
                                 finished=_now(), progress={"percent": 100})
        except Exception:
            pass

    except SatQueryError as e:
        error = {"code": e.code, "message": e.message}
        # Try to extract partial coverage info from error message
        try:
            msg = str(e.message) if hasattr(e, 'message') else str(e)
            m = re.search(r'best coverage ([0-9]*\.?[0-9]+)%', msg)
            cov = None
            if m:
                try:
                    cov = float(m.group(1)) / 100.0
                except Exception:
                    cov = None
            provider_info_fail = {"name": "Sentinel-2", "tile": None, "date": None}
            if cov is not None or 'partial' in msg.lower() or 'coverage' in msg.lower():
                provider_info_fail["coverage"] = {"status": "partial", "fraction": cov, "note": msg}
            try:
                with _lock:
                    if job_id in _jobs:
                        job = _jobs[job_id]
                        created = job.get("created")
                        if job.get("provider_info") and provider_info_fail.get("coverage") is None:
                            pass  # keep existing if any
                    else:
                        created = _now()
                save_history_job(job_id, created, q.raw_text, q.model_dump(mode="json"), aoi,
                                 "failed", {"error": error, "coverage": provider_info_fail.get("coverage")})
            except Exception:
                pass
            try:
                job_store.update_job(job_id, status="failed", error=error, finished=_now(), progress={"percent": 100}, provider_info=provider_info_fail)
            except Exception:
                pass
            with _lock:
                if job_id in _jobs:
                    _jobs[job_id].update(status="failed", error=error, finished=_now(), progress={"percent": 100}, provider_info=provider_info_fail)
            return
        except Exception:
            pass
        try:
            with _lock:
                if job_id in _jobs:
                    job = _jobs[job_id]
                    created = job.get("created")
                else:
                    created = _now()
            save_history_job(job_id, created, q.raw_text, q.model_dump(mode="json"), aoi,
                             "failed", {"error": error})
        except Exception:
            pass
        try:
            job_store.update_job(job_id, status="failed", error=error, finished=_now(), progress={"percent": 100})
        except Exception:
            pass
        with _lock:
            if job_id in _jobs:
                _jobs[job_id].update(status="failed", error=error, finished=_now(), progress={"percent": 100})
    except Exception as e:  # never leak a stack trace; never fabricate a result
        if isinstance(e, SatQueryError):
            error = {"code": e.code, "message": e.message}
        else:
            error = {"code": "internal_error", "message": "Analysis failed."}
        try:
            with _lock:
                if job_id in _jobs:
                    job = _jobs[job_id]
                    created = job.get("created")
                else:
                    created = _now()
            save_history_job(job_id, created, q.raw_text, q.model_dump(mode="json"), aoi, "failed", {"error": error})
        except Exception:
            pass
        try:
            job_store.update_job(job_id, status="failed", error=error, finished=_now(), progress={"percent": 100})
        except Exception:
            pass
        with _lock:
            if job_id in _jobs:
                _jobs[job_id].update(status="failed", error=error, finished=_now(), progress={"percent": 100})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.post("/analysis/investigate")
def analysis_investigate(req: InvestigationRequest, provider: SatelliteProvider = Depends(get_provider)):
    if req.aoi is not None:
        try:
            _validate_aoi_size(req.aoi)
        except SatQueryError as e:
            raise HTTPException(422, {"code": e.code, "message": e.message})
    overrides = {}
    if req.date_a:
        overrides["date_a"] = {"start": req.date_a.start.isoformat(), "end": req.date_a.end.isoformat()}
    if req.date_b:
        overrides["date_b"] = {"start": req.date_b.start.isoformat(), "end": req.date_b.end.isoformat()}
    if req.series_range:
        overrides["series_range"] = {"start": req.series_range.start.isoformat(), "end": req.series_range.end.isoformat()}
    try:
        result = run_investigation(req.query, req.aoi, req.reference_date, req.max_cloud, provider, get_llm_client(), date_overrides=overrides or None)
        return clean(result.model_dump(mode="json"))
    except SatQueryError as e:
        raise HTTPException(422, {"code": e.code, "message": e.message})
    except Exception:
        raise HTTPException(500, {"code": "internal_error", "message": "Investigation failed."})


@app.post("/analysis/run")
def analysis_run(req: RunRequest, bg: BackgroundTasks, provider: SatelliteProvider = Depends(get_provider)):
    _validate_aoi_size(req.aoi)
    q = parse_query_smart(req.query, req.reference_date, get_llm_client())
    selected_scene_id = req.selected_scene_id.strip() if req.selected_scene_id is not None else None
    if req.selected_scene_id is not None and not selected_scene_id:
        raise HTTPException(422, {
            "code": "invalid_selected_scene",
            "message": "Selected scene ID is empty. Refresh the scene list and select a valid scene.",
        })
    if selected_scene_id:
        if q.operation not in (Operation.INDEX_STATS, Operation.LAND_COVER):
            raise HTTPException(422, {
                "code": "selected_scene_unsupported",
                "message": "Selected-scene mode supports only single-date index statistics and land-cover analysis. Clear the scene selection to run change detection or a time series.",
            })
        required_bands = analysis._bands_for(q.index) if q.operation == Operation.INDEX_STATS and q.index else (
            list(LAND_COVER_LOGICAL_BANDS) if q.operation == Operation.LAND_COVER else [])
        try:
            selected_meta = provider.resolve_scene(
                req.aoi, selected_scene_id, req.max_cloud,
                q.date_a.start if q.date_a else None,
                q.date_a.end if q.date_a else None,
                required_bands,
            )
        except SatQueryError as exc:
            raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
        if q.date_a is None:
            selected_date = selected_meta["acquisition_date"]
            q.date_a = DateRange(start=selected_date, end=selected_date)
            q.missing = [missing for missing in q.missing if "date or month" not in missing]
    msg = clarification_message(q)
    if msg:
        return {"status": "needs_clarification", "message": msg, "structured_query": q.model_dump(mode="json")}
    job_id = uuid.uuid4().hex
    created = _now()
    qd = q.model_dump(mode="json")
    stages = [
        {"name": "Data Fetching (Sentinel-2)", "status": "queued"},
        {"name": "Preprocessing", "status": "queued"},
        {"name": "Analysis", "status": "queued"},
        {"name": "Results Ready", "status": "queued"},
    ]
    provider_info = {"name": "Sentinel-2", "tile": None, "date": None}
    try:
        job_store.create_job(job_id, req.query, qd, req.aoi)
        job_store.update_job(job_id, status="queued", stages=stages, provider_info=provider_info, progress={"percent": 0})
    except Exception:
        pass
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created": created,
            "query": req.query,
            "structured_query": qd,
            "aoi": req.aoi,
            "stages": stages,
            "provider_info": provider_info,
            "progress": {"percent": 0},
        }
    bg.add_task(_execute, job_id, q, req.aoi, req.max_cloud, provider, selected_scene_id)
    return {"status": "queued", "job_id": job_id}


@app.get("/history")
def history_list():
    return {"items": list_history()}


@app.get("/history/{job_id}")
def history_detail(job_id: str):
    record = get_history(job_id)
    if record is None:
        raise HTTPException(404, "Unknown history record.")
    # Old persisted results predate trustworthy sensor identity. Annotate the
    # response copy only; do not rewrite their stored JSON or trust legacy source
    # defaults (or processing level) as proof of a sensor.
    result = record.get("result")
    evidence = result.get("evidence") if isinstance(result, dict) else None
    scenes = evidence.get("scenes") if isinstance(evidence, dict) else None
    if isinstance(scenes, list):
        for scene in scenes:
            if isinstance(scene, dict) and scene.get("sensor_identity") not in ("sentinel-2", "other", "unknown"):
                scene["sensor_identity"] = "unknown"
                scene["sensor"] = None
            elif isinstance(scene, dict) and scene.get("sensor_identity") == "unknown":
                scene["sensor"] = None
    return record


@app.delete("/history/{job_id}", status_code=204)
def history_delete(job_id: str):
    if not delete_history(job_id):
        raise HTTPException(404, "Unknown history record.")
    return Response(status_code=204)


def _flatten_values(value, prefix: str = "") -> dict[str, Any]:
    flattened = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_values(child, path))
    elif isinstance(value, (int, float, str, bool)) or value is None:
        if value is not None:
            flattened[prefix] = value
    return flattened


def _stored_result(job_id: str) -> dict:
    record = get_history(job_id)
    if record is None:
        raise HTTPException(404, "Unknown history record.")
    if record["status"] != "completed" or not isinstance(record["result"], dict):
        raise HTTPException(404, "No completed result is available for export.")
    return record


@app.get("/analysis/{job_id}/export.csv")
def export_analysis_csv(job_id: str):
    record = _stored_result(job_id)
    result = record["result"]
    facts = result.get("facts", {})
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("metric", "value", "date"))
    metric_values = _flatten_values(facts)
    confidence = result.get("confidence", {})
    evidence = result.get("evidence", {})
    if isinstance(confidence, dict):
        metric_values.update(_flatten_values(confidence, "confidence"))
    if isinstance(evidence, dict):
        metric_values.update(_flatten_values(evidence.get("metrics", {}), "evidence.metrics"))
        metric_values["evidence.valid_pixel_fraction"] = evidence.get("valid_pixel_fraction")
    for name, value in metric_values.items():
        if name.startswith("series.") and name.rsplit(".", 1)[-1] in {
            "dates", "values", "rolling_mean_3", "anomaly_indices"
        }:
            continue
        if name != "operation":
            writer.writerow((name, value, ""))
    series = facts.get("series", {}) if isinstance(facts, dict) else {}
    dates, values = series.get("dates", []), series.get("values", [])
    rolling = series.get("rolling_mean_3", [])
    anomalies = set(series.get("anomaly_indices", []))
    if isinstance(dates, list) and isinstance(values, list):
        for index, (observed_date, value) in enumerate(zip(dates, values)):
            writer.writerow(("series.value", value, observed_date))
            if index < len(rolling):
                writer.writerow(("series.rolling_mean_3", rolling[index], observed_date))
            if index in anomalies:
                writer.writerow(("series.anomaly", True, observed_date))
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.csv"'},
    )


@app.get("/analysis/{job_id}/export.geojson")
def export_analysis_geojson(job_id: str):
    record = _stored_result(job_id)
    feature = {
        "type": "Feature",
        "geometry": record["aoi"],
        "properties": record["result"].get("facts", {}),
    }
    return Response(
        content=json.dumps(feature, ensure_ascii=False, allow_nan=False),
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.geojson"'},
    )


def _comparison_metrics(result: dict) -> dict[str, float]:
    facts = result.get("facts", {})
    flattened = _flatten_values(facts)
    metrics = {key: value for key, value in flattened.items()
               if isinstance(value, (int, float)) and not isinstance(value, bool)}
    series = facts.get("series", {}) if isinstance(facts, dict) else {}
    dates, values = series.get("dates", []), series.get("values", [])
    if isinstance(dates, list) and isinstance(values, list):
        metrics.update({f"series.value.{observed_date}": value
                        for observed_date, value in zip(dates, values)
                        if isinstance(value, (int, float)) and not isinstance(value, bool)})
    return metrics


@app.post("/analysis/compare")
def analysis_compare(req: CompareRequest, provider: SatelliteProvider = Depends(get_provider)):
    for label, aoi in (("A", req.aoi_a), ("B", req.aoi_b)):
        try:
            _validate_aoi_size(aoi)
        except HTTPException as exc:
            detail = exc.detail
            if isinstance(detail, dict) and isinstance(detail.get("message"), str):
                detail = {**detail, "message": f"Area {label}: {detail['message']}"}
            raise HTTPException(exc.status_code, detail) from exc
    q = parse_query_smart(req.query, req.reference_date, get_llm_client())
    message = clarification_message(q)
    if message:
        raise HTTPException(422, {"code": "needs_clarification", "message": message})
    llm_fn = make_llm_fn(get_llm_client())
    try:
        result_a, result_b = run_compare_operation(
            q, req.aoi_a, req.aoi_b, provider, req.max_cloud, llm_fn,
            classifier=get_classifier() if q.operation == Operation.LAND_COVER else None,
        )
    except SatQueryError as e:
        raise HTTPException(422, {"code": e.code, "message": e.message})
    for result in (result_a, result_b):
        result.pop("arrays", None)
        result.pop("raster", None)
    clean_a, clean_b = clean(result_a), clean(result_b)
    metrics_a, metrics_b = _comparison_metrics(clean_a), _comparison_metrics(clean_b)
    differences = {key: metrics_b[key] - metrics_a[key]
                   for key in metrics_a.keys() & metrics_b.keys()}
    return {
        "structured_query": q.model_dump(mode="json"),
        "aoi_a": {"result": clean_a},
        "aoi_b": {"result": clean_b},
        "differences": differences,
    }


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    if job:
        # Try to sync from DB for fresher state
        try:
            j = job_store.get_job(job_id)
            if j:
                merged = dict(job)
                merged.update({k: v for k, v in j.items() if k in ("status", "stages", "error", "finished", "updated", "progress", "provider_info")})
                with _lock:
                    _jobs[job_id].update(merged)
                return clean(_jobs[job_id])
        except Exception:
            pass
        return clean(job)
    try:
        j = job_store.get_job(job_id)
        if j:
            return clean(j)
    except Exception:
        pass
    raise HTTPException(404, "Unknown job.")


def _load_layer_artifacts(job_id: str, job: dict) -> Optional[dict]:
    """Load raster arrays and grid metadata persisted to the artifact store.

    Mirrors the alias keys that _store_layer_data writes at analysis time so
    layer endpoints keep working after a restart wipes the in-memory store.
    Returns None when artifacts are missing or corrupt.
    """
    try:
        data = load_artifacts(job_id)
    except Exception:
        return None
    if not isinstance(data, dict) or not data:
        return None
    # Rebuild the display aliases created when the result was first stored.
    if "index" not in data and isinstance(data.get("index_b"), np.ndarray):
        data["index"] = data["index_b"]
    if "classes" not in data and isinstance(data.get("class_map"), np.ndarray):
        data["classes"] = data["class_map"]
    if "landcover" not in data and isinstance(data.get("class_map"), np.ndarray):
        data["landcover"] = data["class_map"]
    # Grid metadata is required for bounds and rendering.
    if "transform" not in data or "crs" not in data:
        return None
    return data


def _completed_layer_data(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        try:
            j = job_store.get_job(job_id)
            if j:
                job = j
        except Exception:
            pass
    # History-only fallback: when both in-memory and SQLite job records are
    # missing, consult persisted history (read-only). This never rewrites
    # history or creates a SQLite jobs row.
    if job is None:
        try:
            record = get_history(job_id)
        except Exception:
            record = None
        if record is None:
            raise HTTPException(404, "Unknown job.")
        if record.get("status") != "completed":
            # Failed/non-completed history records must never be treated as
            # completed and must not trigger raster recovery.
            raise HTTPException(409, "Analysis job is not completed.")
        layer_data = _layer_store.get(job_id)
        if layer_data is None:
            layer_data = _load_layer_artifacts(job_id, record)
            if layer_data is not None:
                with _lock:
                    _layer_store[job_id] = layer_data
        if layer_data is None:
            raise HTTPException(404, "No raster layers are available for this job.")
        return layer_data
    if job["status"] != "completed":
        raise HTTPException(409, "Analysis job is not completed.")
    layer_data = _layer_store.get(job_id)
    if layer_data is None:
        # Restart recovery: the in-memory store was wiped, so reload the
        # persisted artifacts from disk and re-populate the in-memory cache.
        layer_data = _load_layer_artifacts(job_id, job)
        if layer_data is not None:
            with _lock:
                _layer_store[job_id] = layer_data
    if layer_data is None:
        raise HTTPException(404, "No raster layers are available for this job.")
    return layer_data


_LAYER_RENDERERS = {
    "index": colorize_index,
    "diff": colorize_diff,
    "classes": colorize_classes,
    "hotspots": colorize_hotspots,
    "landcover": colorize_landcover,
}


@app.get("/analysis/{job_id}/layers")
def analysis_layers(job_id: str):
    data = _completed_layer_data(job_id)
    available = [name for name in _LAYER_RENDERERS if name in data]
    if not available:
        raise HTTPException(404, "No raster layers are available for this job.")
    shape = data[available[0]].shape
    try:
        bounds = bounds_wgs84(data["transform"], shape, data["crs"])
    except (KeyError, ValueError) as e:
        raise HTTPException(404, "Raster grid metadata is unavailable.") from e
    return {
        "bounds": bounds,
        "layers": {name: legend_for(name) for name in available},
    }


@app.get("/analysis/{job_id}/layer/{name}.png")
def analysis_layer_png(job_id: str, name: str):
    data = _completed_layer_data(job_id)
    renderer = _LAYER_RENDERERS.get(name)
    if renderer is None or name not in data:
        raise HTTPException(404, "Unknown or unavailable raster layer.")
    return Response(content=encode_png(renderer(data[name])), media_type="image/png")
