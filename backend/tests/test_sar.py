import sys
import sqlite3
import types
import uuid
from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest
from affine import Affine
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import app, get_sar_provider
from app.core.errors import MissingBandError, NoImageryError
from app.satellite.provider import PlanetaryComputerSentinel1Provider, Sentinel1RTCData
from app.services.sar import summarize_rtc_scene
from app.storage import history as history_storage
from tests.fakes import AOI


def _scene() -> Sentinel1RTCData:
    inside = np.array([[True, True, True], [True, False, True]])
    vv = np.array([[0.1, 0.2, np.nan], [0.4, 9.0, 0.6]], dtype=np.float32)
    vh = np.array([[0.01, 0.02, 0.03], [0.04, 9.0, 0.06]], dtype=np.float32)
    return Sentinel1RTCData(
        item_id="actual-s1-item", datetime="2026-06-15T05:00:00Z", platform="sentinel-1a",
        orbit_state="ascending", relative_orbit=42, processing_level="1", polarizations=["VV", "VH"],
        bands={"VV": vv, "VH": vh}, inside_aoi=inside, transform=Affine(10, 0, 0, 0, -10, 20),
        crs="EPSG:32644", resolution_m=10.0, coverage_fraction=1.0,
    )


def test_sar_summary_uses_joint_valid_pixels_and_preserves_scene_provenance():
    result = summarize_rtc_scene(_scene())
    assert result["facts"]["valid_pixel_fraction"] == pytest.approx(4 / 5)
    assert result["facts"]["valid_pixel_count"] == 4
    assert result["facts"]["vv"]["mean"] == pytest.approx(0.325)
    assert result["facts"]["vh"]["median"] == pytest.approx(0.03)
    evidence = result["evidence"]
    assert evidence["aoi_area_km2"] is None
    assert evidence["scenes"][0]["item_id"] == "actual-s1-item"
    assert evidence["scenes"][0]["datetime"] == "2026-06-15T05:00:00Z"
    assert evidence["scenes"][0]["sensor_identity"] == "other"
    assert evidence["scenes"][0]["processing_level"] == "1"
    assert evidence["scenes"][0]["processing_product"].startswith("Radiometrically terrain-corrected")
    assert evidence["scenes"][0]["relative_orbit"] == 42


def test_sar_summary_rejects_misaligned_or_nonphysical_assets():
    scene = _scene()
    scene.bands["VH"] = np.zeros((3, 2), dtype=np.float32)
    with pytest.raises(NoImageryError, match="not aligned"):
        summarize_rtc_scene(scene)

    scene = _scene()
    scene.bands["VV"][0, 0] = -0.1
    with pytest.raises(NoImageryError, match="negative"):
        summarize_rtc_scene(scene)


def test_sar_scene_resolution_keeps_exact_item_and_rejects_missing_polarization(monkeypatch):
    calls = []
    item = SimpleNamespace(
        id="exact-s1-id",
        geometry={"type": "Polygon", "coordinates": AOI["coordinates"]},
        properties={"datetime": "2026-06-15T05:00:00Z", "sar:product_type": "GRD",
                    "sar:instrument_mode": "IW", "s1:processing_level": "1"},
        assets={"vv": SimpleNamespace(href="https://example.test/vv.tif")},
    )

    class FakeSearch:
        def items(self):
            return iter([item])

    class FakeCatalog:
        def search(self, **kwargs):
            calls.append(kwargs)
            return FakeSearch()

    monkeypatch.setitem(sys.modules, "pystac_client", SimpleNamespace(Client=SimpleNamespace(open=lambda *_: FakeCatalog())))
    with pytest.raises(MissingBandError, match="both VV and VH"):
        PlanetaryComputerSentinel1Provider().read_scene(AOI, "exact-s1-id", date(2026, 6, 1), date(2026, 6, 30))
    assert calls[0]["ids"] == ["exact-s1-id"]
    assert calls[0]["collections"] == ["sentinel-1-rtc"]
    with pytest.raises(NoImageryError, match="outside the requested acquisition date range"):
        PlanetaryComputerSentinel1Provider().read_scene(
            AOI, "exact-s1-id", date(2026, 7, 1), date(2026, 7, 31)
        )


def test_sar_scene_discovery_returns_actual_catalog_metadata(monkeypatch):
    item = SimpleNamespace(
        id="catalog-s1", geometry={"type": "Polygon", "coordinates": AOI["coordinates"]},
        properties={"datetime": "2026-06-15T05:00:00Z", "platform": "sentinel-1a",
                    "s1:processing_level": "1", "sar:product_type": "GRD",
                    "sar:instrument_mode": "IW", "sat:orbit_state": "ascending",
                    "sat:relative_orbit": 42},
        assets={"vv": object(), "vh": object()}, datetime=None,
    )

    class FakeSearch:
        def items(self):
            return iter([item])

    class FakeCatalog:
        def search(self, **kwargs):
            assert kwargs["collections"] == ["sentinel-1-rtc"]
            return FakeSearch()

    monkeypatch.setitem(sys.modules, "pystac_client", SimpleNamespace(Client=SimpleNamespace(open=lambda *_: FakeCatalog())))
    scenes = PlanetaryComputerSentinel1Provider().list_scenes(AOI, date(2026, 6, 1), date(2026, 6, 30))
    assert scenes == [{
        "item_id": "catalog-s1", "datetime": "2026-06-15T05:00:00Z",
        "provider": "Microsoft Planetary Computer", "collection": "sentinel-1-rtc",
        "platform": "sentinel-1a", "processing_level": "1", "processing_product": "RTC",
        "product_type": "GRD", "instrument_mode": "IW", "orbit_state": "ascending",
        "relative_orbit": 42, "polarizations": ["VH", "VV"],
        "coverage_fraction": pytest.approx(1.0), "required_polarizations_available": True,
        "analysis_supported": True,
    }]


def test_sar_provider_reads_both_exact_assets_on_the_same_grid(monkeypatch):
    item = SimpleNamespace(
        id="exact-live-shaped-item",
        geometry={"type": "Polygon", "coordinates": AOI["coordinates"]},
        properties={
            "datetime": "2026-06-15T05:00:00Z", "platform": "sentinel-1a",
            "s1:processing_level": "1", "sar:product_type": "GRD",
            "sar:instrument_mode": "IW", "sat:orbit_state": "ascending",
            "sat:relative_orbit": 42,
        },
        assets={"vv": SimpleNamespace(href="vv.tif"), "vh": SimpleNamespace(href="vh.tif")},
        datetime=None,
    )

    class FakeSearch:
        def items(self):
            return iter([item])

    class FakeCatalog:
        def search(self, **kwargs):
            assert kwargs["collections"] == ["sentinel-1-rtc"]
            assert kwargs["ids"] == [item.id]
            return FakeSearch()

    class FakeCRS:
        is_projected = True
        linear_units_factor = ("metre", 1.0)

        def to_string(self):
            return "EPSG:32644"

    class FakeSource:
        crs = FakeCRS()
        transform = Affine(10, 0, 0, 0, -10, 20)
        bounds = SimpleNamespace(left=-1_000_000, bottom=-1_000_000, right=1_000_000, top=1_000_000)
        nodata = -32768

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    rasterio = types.ModuleType("rasterio")
    rasterio.open = lambda _href: FakeSource()
    rasterio_mask = types.ModuleType("rasterio.mask")
    rasterio_mask.mask = lambda _source, _shapes, crop, filled: (
        np.ma.array([[[0.1, 0.2], [0.3, 0.4]]], mask=False), FakeSource.transform
    )
    rasterio_features = types.ModuleType("rasterio.features")
    rasterio_features.geometry_mask = lambda _shapes, out_shape, transform, invert: np.ones(out_shape, dtype=bool)
    rasterio_warp = types.ModuleType("rasterio.warp")
    rasterio_warp.transform_geom = lambda _src, _dst, geometry: geometry
    monkeypatch.setitem(sys.modules, "pystac_client", SimpleNamespace(
        Client=SimpleNamespace(open=lambda *_args: FakeCatalog())
    ))
    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(
        get=lambda url, params, timeout: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"href": f"https://signed.example/{params['href']}"},
        )
    ))
    monkeypatch.setitem(sys.modules, "rasterio", rasterio)
    monkeypatch.setitem(sys.modules, "rasterio.mask", rasterio_mask)
    monkeypatch.setitem(sys.modules, "rasterio.features", rasterio_features)
    monkeypatch.setitem(sys.modules, "rasterio.warp", rasterio_warp)

    scene = PlanetaryComputerSentinel1Provider().read_scene(
        AOI, item.id, date(2026, 6, 1), date(2026, 6, 30)
    )

    assert scene.item_id == item.id
    assert scene.bands["VV"].shape == scene.bands["VH"].shape == (2, 2)
    assert scene.crs == "EPSG:32644"
    assert scene.resolution_m == 10
    assert summarize_rtc_scene(scene)["facts"]["valid_pixel_count"] == 4


def test_sar_api_works_without_sentinel2_history_and_persists_result(monkeypatch):
    uri = f"file:sar_history_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keeper = sqlite3.connect(uri, uri=True)

    def connect_shared_memory():
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id TEXT PRIMARY KEY, created TEXT NOT NULL, query TEXT NOT NULL,
                structured_query TEXT NOT NULL, aoi TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT
            )"""
        )
        return connection

    monkeypatch.setattr(history_storage, "_connect", connect_shared_memory)
    scene = _scene()

    class FakeProvider:
        requested_id = None

        def read_scene(self, aoi, item_id, start, end):
            self.requested_id = item_id
            assert start == date(2026, 6, 1) and end == date(2026, 6, 30)
            return scene

    provider = FakeProvider()
    app.dependency_overrides[get_sar_provider] = lambda: provider
    try:
        client = TestClient(app)
        assert client.get("/history").json()["items"] == []
        response = client.post("/sar/analyze", json={
            "aoi": AOI, "selected_scene_id": "actual-s1-item", "start": "2026-06-01", "end": "2026-06-30",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "completed"
        assert provider.requested_id == "actual-s1-item"
        record = client.get(f"/history/{body['job_id']}").json()
        assert record["status"] == "completed"
        assert record["result"]["evidence"]["scenes"][0]["item_id"] == "actual-s1-item"
        assert record["result"]["evidence"]["scenes"][0]["sensor"] == "Sentinel-1"
        assert record["result"]["evidence"]["scenes"][0]["sensor_identity"] == "other"
        assert record["result"]["facts"]["operation"] == "sar_backscatter"
        assert isinstance(record["result"]["evidence"]["aoi_area_km2"], (int, float))
        assert record["result"]["evidence"]["aoi_area_km2"] > 0
        assert record["result"]["evidence"]["aoi_area_km2"] == pytest.approx(
            api_main._validate_aoi_size(AOI)[1]
        )
        summary = next(item for item in client.get("/history").json()["items"]
                       if item["id"] == body["job_id"])
        assert summary["sensor"] == "Sentinel-1"
        assert summary["sensor_identity"] == "other"

        with api_main._lock:
            previous_jobs = dict(api_main._jobs)
            previous_layers = dict(api_main._layer_store)
            api_main._jobs.clear()
            api_main._layer_store.clear()
        try:
            recovered = client.get(f"/history/{body['job_id']}").json()
            recovered_scene = recovered["result"]["evidence"]["scenes"][0]
            assert recovered["status"] == "completed"
            assert recovered_scene["sensor"] == "Sentinel-1"
            assert recovered_scene["sensor_identity"] == "other"
        finally:
            with api_main._lock:
                api_main._jobs.clear()
                api_main._jobs.update(previous_jobs)
                api_main._layer_store.clear()
                api_main._layer_store.update(previous_layers)
    finally:
        app.dependency_overrides.clear()
        keeper.close()


def test_sar_api_persists_scene_failure_as_failed_not_completed(monkeypatch):
    uri = f"file:sar_failed_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keeper = sqlite3.connect(uri, uri=True)

    def connect_shared_memory():
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id TEXT PRIMARY KEY, created TEXT NOT NULL, query TEXT NOT NULL,
                structured_query TEXT NOT NULL, aoi TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT
            )"""
        )
        return connection

    monkeypatch.setattr(history_storage, "_connect", connect_shared_memory)

    class MissingSceneProvider:
        def read_scene(self, aoi, item_id, start, end):
            raise NoImageryError("Selected Sentinel-1 scene could not be resolved exactly.")

    app.dependency_overrides[get_sar_provider] = MissingSceneProvider
    try:
        client = TestClient(app)
        response = client.post("/sar/analyze", json={
            "aoi": AOI, "selected_scene_id": "missing-scene", "start": "2026-06-01", "end": "2026-06-30",
        })
        assert response.status_code == 422
        assert response.json()["detail"]["message"] == "Selected Sentinel-1 scene could not be resolved exactly."
        rows = client.get("/history").json()["items"]
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"
        assert rows[0]["operation"] == "sar_backscatter"
    finally:
        app.dependency_overrides.clear()
        keeper.close()
