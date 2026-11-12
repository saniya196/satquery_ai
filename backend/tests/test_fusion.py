from datetime import date
from pathlib import Path

import numpy as np
import pytest
from affine import Affine
from fastapi.testclient import TestClient

from app.api.main import app, get_provider, get_sar_provider
from app.core.errors import NoImageryError
from app.satellite.provider import SceneData, Sentinel1RTCData
from app.services.fusion import ensure_pair_compatible, fuse
from app.storage import history as history_storage
from tests.fakes import AOI


TF = Affine(10, 0, 500000, 0, -10, 1000)


def optical() -> SceneData:
    return SceneData("s2", "2026-06-15T10:00:00Z", 5.0,
                     {"red": np.full((2, 2), .2), "nir": np.full((2, 2), .6)},
                     np.full((2, 2), 4, dtype=np.uint8), TF, "EPSG:32644", np.ones((2, 2), dtype=bool),
                     provider="Element84", collection="sentinel-2-l2a", platform="sentinel-2a", coverage_fraction=1.0)


def sar() -> Sentinel1RTCData:
    return Sentinel1RTCData("s1", "2026-06-16T10:00:00Z", "sentinel-1a", "ascending", 42, "1", ["VV", "VH"],
                            {"VV": np.full((2, 2), .2, dtype=np.float32), "VH": np.full((2, 2), .1, dtype=np.float32)},
                            np.ones((2, 2), dtype=bool), TF, "EPSG:32644", 10, 1.0)


def test_fusion_writes_georeferenced_stack_and_linear_rvi(tmp_path: Path):
    result, arrays, _ = fuse(optical(), sar(), tmp_path / "fusion.tif")
    assert result["valid_overlapping_pixel_count"] == 4
    np.testing.assert_allclose(arrays["rvi"], 4 / 3)
    import rasterio
    with rasterio.open(tmp_path / "fusion.tif") as src:
        assert src.count == 4
        assert src.crs.to_string() == "EPSG:32644"
        assert src.transform == TF
        assert src.descriptions == ("ndvi", "vv_db", "vh_db", "rvi")


def test_fusion_propagates_nodata_and_rejects_incompatible_dates(tmp_path: Path):
    source = sar()
    source.bands["VH"][0, 0] = np.nan
    _, arrays, _ = fuse(optical(), source, tmp_path / "fusion.tif")
    assert arrays["overlap_mask"][0, 0] == 0
    assert np.isnan(arrays["rvi"][0, 0])
    with pytest.raises(NoImageryError, match="at most"):
        ensure_pair_compatible("2026-06-01T00:00:00Z", "2026-06-05T00:01:00Z")


def test_fusion_scene_discovery_and_completed_result_persist(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("SATQUERY_ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    class OpticalProvider:
        def list_scenes(self, *_):
            return [{"item_id": "s2", "datetime": "2026-06-15T10:00:00Z", "cloud_cover": 5, "coverage": 1.0}]
        def get_selected_scene(self, *_args): return optical()
    class SarProvider:
        def list_scenes(self, *_):
            return [{"item_id": "s1", "datetime": "2026-06-16T10:00:00Z", "coverage_fraction": 1.0,
                     "required_polarizations_available": True, "analysis_supported": True, "polarizations": ["VV", "VH"]}]
        def read_scene(self, *_args): return sar()
    app.dependency_overrides[get_provider] = OpticalProvider
    app.dependency_overrides[get_sar_provider] = SarProvider
    try:
        client = TestClient(app)
        scenes = client.post("/fusion/scenes", json={"aoi": AOI, "start": "2026-06-01", "end": "2026-06-30", "max_cloud": 40})
        assert scenes.status_code == 200 and len(scenes.json()["pairs"]) == 1
        response = client.post("/fusion/analyze", json={"aoi": AOI, "start": "2026-06-01", "end": "2026-06-30", "max_cloud": 40, "optical_scene_id": "s2", "sar_scene_id": "s1"})
        assert response.status_code == 200, response.text
        body = response.json()
        record = client.get(f"/history/{body['job_id']}").json()
        assert record["status"] == "completed"
        assert len(record["result"]["evidence"]["scenes"]) == 2
        assert Path(record["result"]["evidence"]["metrics"]["artifact_path"]).is_file()
    finally:
        app.dependency_overrides.clear()
