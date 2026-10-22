from typing import Any, Optional
from pydantic import BaseModel


class SceneRef(BaseModel):
    item_id: str
    datetime: str
    cloud_cover: Optional[float] = None
    resolution_m: float = 10.0
    crs: Optional[str] = None
    processing_level: str = "L2A"
    source: str = "Sentinel-2"


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
