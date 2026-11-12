"""Service-level test for per-hotspot evidence references (synthetic data, no network)."""
from datetime import date
from unittest.mock import MagicMock

import numpy as np
from affine import Affine

from app.satellite.provider import SatelliteProvider, SceneData
from app.schemas.query import DateRange
from app.services import analysis


class MockProvider(SatelliteProvider):
    def __init__(self, scenes_by_id):
        self.scenes_by_id = scenes_by_id

    def list_scenes(self, aoi_geojson, start, end, max_cloud):
        return []

    def best_scene(self, aoi_geojson, start, end, max_cloud, min_coverage=0.99):
        # Return metadata matching requested range by simple heuristic
        for sid, sc in self.scenes_by_id.items():
            d = sc.datetime[:10]
            if str(start) <= d <= str(end):
                return {"item_id": sid, "datetime": sc.datetime, "cloud_cover": sc.cloud_cover,
                        "coverage_fraction": 1.0, "coverage_status": "full"}
        sid = next(iter(self.scenes_by_id))
        sc = self.scenes_by_id[sid]
        return {"item_id": sid, "datetime": sc.datetime, "cloud_cover": sc.cloud_cover,
                "coverage_fraction": 1.0, "coverage_status": "full"}

    def get_scene(self, aoi_geojson, item_id, bands):
        return self.scenes_by_id[item_id]


def _scene(item_id, dt, nir, red):
    shape = nir.shape
    return SceneData(
        item_id=item_id,
        datetime=dt,
        cloud_cover=5.0,
        bands={"nir": nir.astype(np.float32), "red": red.astype(np.float32)},
        scl=np.full(shape, 4, dtype=np.uint8),
        transform=Affine(10, 0, 500000, 0, -10, 4000000),
        crs="EPSG:32644",
        inside_aoi=np.ones(shape, dtype=bool),
        resolution_m=10.0,
        preprocessing=["test preprocessing"],
    )


def test_run_change_attaches_hotspot_evidence_references():
    nir_a = np.full((20, 20), 0.8)
    red_a = np.full((20, 20), 0.2)  # NDVI 0.6
    nir_b = nir_a.copy(); red_b = red_a.copy()
    nir_b[:, :10] = 0.4; red_b[:, :10] = 0.2  # NDVI 0.333 -> drop ~0.267 (significant decrease)
    sa = _scene("S2_A", "2024-01-01T00:00:00Z", nir_a, red_a)
    sb = _scene("S2_B", "2024-06-01T00:00:00Z", nir_b, red_b)
    provider = MockProvider({"S2_A": sa, "S2_B": sb})
    # Force specific scene selection by patching best_scene behavior via ranges
    provider.best_scene = lambda aoi, start, end, max_cloud, min_coverage=0.99: (
        {"item_id": "S2_A", "coverage_fraction": 1.0} if start.year == 2024 and start.month == 1
        else {"item_id": "S2_B", "coverage_fraction": 1.0}
    )
    aoi = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    res = analysis.run_change(provider, aoi, DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31)),
                              DateRange(start=date(2024, 6, 1), end=date(2024, 6, 30)), index="NDVI")
    assert res["hotspots"], "expected at least one hotspot"
    h = res["hotspots"][0]
    assert h["class"] == "significant_decrease"
    assert "median_diff" in h and "valid_pixel_count" in h
    ev = h.get("evidence")
    assert ev is not None
    assert ev["baseline_scene_id"] == "S2_A"
    assert ev["comparison_scene_id"] == "S2_B"
    assert ev["baseline_date"] == "2024-01-01"
    assert ev["comparison_date"] == "2024-06-01"
    assert ev["index"] == "NDVI"
    assert ev["formula"] == res["evidence"]["formula"]
    assert ev["bands"] == res["evidence"]["bands"]
    assert ev["change_thresholds"] == res["evidence"]["thresholds"]
    assert isinstance(ev["preprocessing"], list)
    assert ev["global_valid_pixel_fraction"] == res["evidence"]["valid_pixel_fraction"]
    # Additive: global evidence still present
    assert "scenes" in res["evidence"] and len(res["evidence"]["scenes"]) == 2
