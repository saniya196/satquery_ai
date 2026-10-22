# SatQuery AI — Analysis Operation Registry

## 1. Concept

Every analysis capability in SatQuery AI is a **registered operation** — a self-describing plugin that declares its name, required inputs, output type, and validation rules. The orchestrator never hard-codes analysis logic; it looks up the operation in the registry and calls its `run()` method.

This design lets us add new operations (e.g., NDWI, burn-area index) by writing one module and registering it — zero changes to the orchestrator or API.

---

## 2. Registry Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class OperationMeta:
    """Declarative metadata for an operation."""
    name: str                                  # Registry key, e.g. "ndvi"
    display_name: str                          # Human-readable, e.g. "Vegetation Index (NDVI)"
    description: str
    required_inputs: list[str]                 # What must be in params, e.g. ["date_range", "aoi"]
    required_bands: list[str]                  # Sentinel-2 bands needed, e.g. ["B04", "B08"]
    output_type: str                           # "raster" | "raster+stats" | "stats_only" | "classification"
    supports_comparison: bool = False          # Can produce before/after diff
    min_scenes: int = 1                        # Minimum scenes needed
    phase: str = "mvp"                         # "mvp" | "advanced"


class BaseOperation(ABC):
    meta: OperationMeta

    @abstractmethod
    def validate(self, params: dict) -> list[str]:
        """Return list of validation error messages (empty = valid)."""
        ...

    @abstractmethod
    def run(self, tiles: list[np.ndarray], params: dict) -> dict[str, Any]:
        """
        Execute the operation on a list of tiles.
        Returns: { "raster": np.ndarray | None, "stats": dict, "metadata": dict }
        """
        ...


# Global registry
_REGISTRY: dict[str, BaseOperation] = {}

def register(op: BaseOperation):
    _REGISTRY[op.meta.name] = op

def get(name: str) -> BaseOperation:
    return _REGISTRY[name]

def list_operations() -> list[OperationMeta]:
    return [op.meta for op in _REGISTRY.values()]
```

---

## 3. Registered Operations

### 3.1 NDVI — Normalised Difference Vegetation Index `[MVP]`

| Attribute | Value |
|---|---|
| **Name** | `ndvi` |
| **Display Name** | Vegetation Index (NDVI) |
| **Description** | Measures vegetation health using the normalised difference of NIR and Red bands. Values range from -1 to +1; healthy vegetation > 0.3. |
| **Required Inputs** | `date_range`, `aoi` |
| **Required Bands** | `B04` (Red, 10m), `B08` (NIR, 10m) |
| **Output Type** | `raster+stats` |
| **Supports Comparison** | Yes |
| **Min Scenes** | 1 |
| **Formula** | `(B08 - B04) / (B08 + B04)` |
| **Output Stats** | `mean`, `median`, `min`, `max`, `std`, `area_above_threshold_km2` |

**Validation Rules:**
- Date range must be ≤ 2 years
- AOI must be ≤ 100 km²
- `cloud_cover_max` must be 0–100

**Colormap:** `RdYlGn` (red = barren/water, green = dense vegetation)

---

### 3.2 Change Detection `[MVP]`

| Attribute | Value |
|---|---|
| **Name** | `change_detection` |
| **Display Name** | Before / After Change Detection |
| **Description** | Computes pixel-wise difference between two date ranges for a given index (default: NDVI). Highlights areas of significant increase or decrease. |
| **Required Inputs** | `date_range` (with comparison.date_range_a and date_range_b), `aoi` |
| **Required Bands** | Depends on base index (default: `B04`, `B08` for NDVI) |
| **Output Type** | `raster+stats` |
| **Supports Comparison** | Inherently comparative |
| **Min Scenes** | 2 (one per period) |

**Parameters:**
- `base_index`: Which index to difference (default: `"ndvi"`)
- `threshold`: Minimum absolute change to flag as significant (default: `0.1`)

**Output Stats:**
- `mean_change`, `median_change`
- `area_increased_km2`, `area_decreased_km2`
- `pct_significant_change`
- `change_histogram` (binned into 10 buckets)

**Validation Rules:**
- Two non-overlapping date ranges required
- Each date range must have ≥ 1 low-cloud scene

**Colormap:** Diverging `RdBu` (red = decrease, blue = increase)

---

### 3.3 ML Land-Use Classification `[Advanced]`

| Attribute | Value |
|---|---|
| **Name** | `classify` |
| **Display Name** | Land-Use / Land-Cover Classification |
| **Description** | Classifies each 64×64-pixel patch into a land-use category using a EuroSAT-trained ResNet18. See [ML_STRATEGY.md](file:///c:/Users/Dell/Downloads/satquery_ai/docs/ML_STRATEGY.md) for model details. |
| **Required Inputs** | `date_range`, `aoi` |
| **Required Bands** | `B02` (Blue), `B03` (Green), `B04` (Red), `B08` (NIR) — minimum; full 13-band for best accuracy |
| **Output Type** | `classification` |
| **Supports Comparison** | Yes (compare two dates to detect land-use change) |
| **Min Scenes** | 1 |

**Output:**
- Per-patch class label + confidence score
- Aggregate class distribution (% of AOI per class)
- Confidence heatmap raster

**Validation Rules:**
- Warn if AOI is > 50 km² (processing time)
- Warn if cloud cover > 10% (degrades accuracy)
- Reject if no 4-band scene available

**Classes:** See Section 4 below.

---

### 3.4 Time-Series Statistics `[Advanced]`

| Attribute | Value |
|---|---|
| **Name** | `time_series_stats` |
| **Display Name** | Temporal Trend Analysis |
| **Description** | Computes a chosen index for every available scene in the date range and returns a time-series of statistics with trend line. |
| **Required Inputs** | `date_range`, `aoi`, `time_step` |
| **Required Bands** | Depends on base index |
| **Output Type** | `stats_only` (time-series JSON + chart data) |
| **Supports Comparison** | No |
| **Min Scenes** | 3 |

**Parameters:**
- `base_index`: default `"ndvi"`
- `time_step`: `"per_scene"`, `"weekly"`, `"monthly"`
- `aggregation`: `"mean"`, `"median"`, `"max"`

**Output:**
```json
{
  "time_series": [
    { "date": "2024-01-15", "value": 0.42, "cloud_pct": 5 },
    { "date": "2024-02-01", "value": 0.38, "cloud_pct": 12 }
  ],
  "trend": { "slope": -0.02, "r_squared": 0.85, "direction": "decreasing" },
  "chart_config": { "type": "line", "x": "date", "y": "value" }
}
```

**Validation Rules:**
- Date range must span ≥ 2 months
- Must find ≥ 3 scenes; warn if < 6

---

### 3.5 Custom Band Index `[Advanced]`

| Attribute | Value |
|---|---|
| **Name** | `custom_index` |
| **Display Name** | Custom Spectral Index |
| **Description** | Computes a user-defined band math formula. Supports common indices (NDWI, EVI, SAVI, NBR) as presets. |
| **Required Inputs** | `date_range`, `aoi`, `index_formula` or preset name |
| **Required Bands** | Parsed from the formula |
| **Output Type** | `raster+stats` |
| **Supports Comparison** | Yes |
| **Min Scenes** | 1 |

**Presets:**

| Preset | Formula | Bands | Use Case |
|---|---|---|---|
| NDWI | `(B03 - B08) / (B03 + B08)` | B03, B08 | Water body detection |
| EVI | `2.5 * (B08 - B04) / (B08 + 6*B04 - 7.5*B02 + 1)` | B02, B04, B08 | Enhanced vegetation |
| SAVI | `1.5 * (B08 - B04) / (B08 + B04 + 0.5)` | B04, B08 | Soil-adjusted vegetation |
| NBR | `(B08 - B12) / (B08 + B12)` | B08, B12 | Burn area mapping |

**Validation Rules:**
- Formula must reference only valid Sentinel-2 band names
- Formula must be a safe arithmetic expression (no function calls, imports)
- Division-by-zero protection: denominator clamped to ±ε

---

## 4. Classification Label Mapping

The ML classifier outputs EuroSAT's 10 classes. We map them to product-level categories:

| EuroSAT Class | Product Category | Color |
|---|---|---|
| AnnualCrop | Agriculture | `#E6C229` |
| PermanentCrop | Agriculture | `#D4A017` |
| Pasture | Grassland | `#7CFC00` |
| HerbaceousVegetation | Grassland | `#228B22` |
| Forest | Forest | `#006400` |
| River | Water | `#1E90FF` |
| SeaLake | Water | `#00008B` |
| Industrial | Built-up | `#FF4500` |
| Residential | Built-up | `#FF6347` |
| Highway | Built-up | `#CD853F` |

Product categories: **Agriculture**, **Grassland**, **Forest**, **Water**, **Built-up** (5 classes).

---

## 5. Adding a New Operation (Checklist)

1. Create `backend/operations/my_op.py` implementing `BaseOperation`
2. Define `OperationMeta` with all required fields
3. Call `register()` in the module's `__init__`
4. Add the operation name to `OperationType` enum in the query schema
5. Add band/param defaults in `OperationParams`
6. Write unit tests: `tests/operations/test_my_op.py`
7. Add to this document
