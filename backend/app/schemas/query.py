"""Language-independent structured query. English/Hindi/etc. all map to this one schema."""
from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Operation(str, Enum):
    INDEX_STATS = "index_stats"
    CHANGE_DETECTION = "change_detection"
    TIME_SERIES = "time_series"
    LAND_COVER = "land_cover"
    COMPARE_REGIONS = "compare_regions"
    UNSUPPORTED = "unsupported"


class DateRange(BaseModel):
    start: date
    end: date


class StructuredQuery(BaseModel):
    raw_text: str
    language: str = "en"
    operation: Operation
    index: Optional[str] = None                      # NDVI | NDWI | MNDWI | NDBI | SAVI
    date_a: Optional[DateRange] = None               # baseline / single date
    date_b: Optional[DateRange] = None               # comparison
    series_range: Optional[DateRange] = None         # for time series
    change_direction: Optional[str] = None           # decrease | increase | any
    thresholds: dict[str, float] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)
    aoi_from_context: bool = True                    # AOI is drawn on the map, not parsed from text
    missing: list[str] = Field(default_factory=list)
    unsupported_reason: Optional[str] = None
    parser: str = "rules"                            # rules | llm
