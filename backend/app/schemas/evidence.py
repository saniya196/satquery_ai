from typing import Any, Literal, Optional
from pydantic import BaseModel


class SceneRef(BaseModel):
    item_id: str
    datetime: str
    cloud_cover: Optional[float] = None
    resolution_m: float = 10.0
    crs: Optional[str] = None
    processing_level: Optional[str] = None
    # ``source`` is retained for older consumers but is never sufficient to
    # establish sensor identity. New records populate it from catalog metadata.
    source: Optional[str] = None
    provider: Optional[str] = None
    collection: Optional[str] = None
    platform: Optional[str] = None
    coverage_fraction: Optional[float] = None
    sensor: Optional[str] = None
    sensor_identity: Literal["sentinel-2", "other", "unknown"] = "unknown"


class Evidence(BaseModel):
    """Everything needed to audit one result."""
    operation: str
    scenes: list[SceneRef]
    aoi_area_km2: float
    index: Optional[str] = None
    formula: Optional[str] = None
    bands: Optional[str] = None
    preprocessing: list[str]
    thresholds: dict[str, Any] = {}
    valid_pixel_fraction: float
    metrics: dict[str, Any]
    model: Optional[dict[str, Any]] = None
    # Scene-footprint AOI coverage metadata (additive, optional). Shape preserved:
    # {"status": "full"|"partial"|"unknown", "fraction": <float|None>, "note"?: <str>}
    coverage: Optional[dict[str, Any]] = None
