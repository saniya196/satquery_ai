import json
import sqlite3
import uuid
from types import SimpleNamespace
from datetime import date

from fastapi.testclient import TestClient
from affine import Affine
import numpy as np

from app.api.main import app
from app.satellite.provider import EarthSearchProvider, SceneData, sensor_identity_from_metadata
from app.schemas.evidence import SceneRef
from app.schemas.query import DateRange, Operation
from app.services.analysis import _scene_ref, run_index_stats
from app.services.compare import run_compare_operation
from app.storage import history as history_storage
from app.storage.history import get_history, list_history, save_history_job
from tests.fakes import AOI, FakeProvider, make_scene


client = TestClient(app)


def test_catalog_sentinel2_metadata_produces_verified_sentinel2_identity():
    provider = object.__new__(EarthSearchProvider)
    metadata = provider._scene_catalog_metadata(
        SimpleNamespace(
            collection_id="sentinel-2-l2a",
            properties={"platform": "sentinel-2a", "processing:level": "L2A"},
        )
    )

    assert metadata["sensor_identity"] == "sentinel-2"
    assert metadata["sensor"] == "sentinel-2a"
    assert metadata["provider"] == "Element84 Earth Search"
    assert metadata["collection"] == "sentinel-2-l2a"
    assert metadata["processing_level"] == "L2A"
    collection_only_identity = sensor_identity_from_metadata("sentinel-2-l2a", None)
    assert collection_only_identity == ("sentinel-2", "sentinel-2-l2a")


def test_missing_catalog_identity_metadata_is_unknown():
    assert sensor_identity_from_metadata(None, None) == ("unknown", None)
    assert sensor_identity_from_metadata("some-imagery", None) == ("unknown", None)


def test_other_catalog_sensor_is_not_mislabeled_sentinel2():
    identity, sensor = sensor_identity_from_metadata("sentinel-1-grd", "sentinel-1a")
    assert identity == "other"
    assert sensor == "sentinel-1a"
    assert sensor_identity_from_metadata("sentinel-2-l2a", "sentinel-1a") == ("unknown", None)
    assert sensor_identity_from_metadata("sentinel-1-grd", "landsat-8") == ("unknown", None)


def test_schema_source_default_cannot_create_verified_sensor_identity():
    scene = SceneRef(item_id="scene-1", datetime="2026-01-02T03:04:05Z", source="Sentinel-2",
                     processing_level="L2A")
    assert scene.sensor_identity == "unknown"
    assert scene.sensor is None
    assert SceneRef(item_id="scene-2", datetime="2026-01-02T03:04:05Z").source is None


def test_standard_scene_evidence_serialization_keeps_acquisition_metadata():
    data = SceneData(
        item_id="catalog-scene-123",
        datetime="2026-01-02T03:04:05+00:00",
        cloud_cover=4.5,
        bands={}, scl=np.zeros((1, 1), dtype=np.uint8),
        transform=Affine.identity(), crs="EPSG:32644", inside_aoi=np.ones((1, 1), dtype=bool),
        provider="Element84 Earth Search", collection="sentinel-2-l2a",
        platform="sentinel-2a", processing_level="L2A", source="sentinel-2a",
        sensor="sentinel-2a", sensor_identity="sentinel-2",
    )

    evidence_scene = _scene_ref(data).model_dump()
    assert evidence_scene["item_id"] == "catalog-scene-123"
    assert evidence_scene["datetime"] == "2026-01-02T03:04:05+00:00"
    assert evidence_scene["provider"] == "Element84 Earth Search"
    assert evidence_scene["collection"] == "sentinel-2-l2a"
    assert evidence_scene["platform"] == "sentinel-2a"
    assert evidence_scene["sensor_identity"] == "sentinel-2"


class CatalogMetadataFakeProvider(FakeProvider):
    def get_scene(self, aoi_geojson, item_id, bands):
        scene = super().get_scene(aoi_geojson, item_id, bands)
        scene.provider = "Element84 Earth Search"
        scene.collection = "sentinel-2-l2a"
        scene.platform = "sentinel-2a"
        scene.processing_level = "L2A"
        scene.source = "sentinel-2a"
        scene.sensor = "sentinel-2a"
        scene.sensor_identity = "sentinel-2"
        return scene


def test_standard_analysis_keeps_explicit_sensor_metadata_in_result():
    provider = CatalogMetadataFakeProvider([
        make_scene("standard-s2", "2026-06-15T05:00:00+00:00", .8, .8)
    ])
    result = run_index_stats(provider, AOI,
                             DateRange(start=date(2026, 6, 1), end=date(2026, 6, 30)))
    scene = result["evidence"]["scenes"][0]
    assert scene["sensor_identity"] == "sentinel-2"
    assert scene["item_id"] == "standard-s2"
    assert scene["datetime"] == "2026-06-15T05:00:00+00:00"


def test_compare_evidence_serialization_keeps_sensor_identity():
    provider = FakeProvider([
        make_scene("compare-s2", "2026-06-15T05:00:00+00:00", .8, .8, coverage=1.0)
    ])
    query = SimpleNamespace(
        operation=Operation.INDEX_STATS,
        date_a=DateRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
        index="NDVI",
    )
    left, right = run_compare_operation(query, AOI, AOI, provider, 10, None)
    for result in (left, right):
        scene = result["evidence"]["scenes"][0]
        assert scene["sensor_identity"] == "sentinel-2"
        assert scene["item_id"] == "compare-s2"


def test_legacy_history_detail_is_unknown_without_rewriting_stored_json(monkeypatch):
    uri = f"file:sensor_identity_{uuid.uuid4().hex}?mode=memory&cache=shared"
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
    legacy_result = {
        "evidence": {
            "scenes": [{
                "item_id": "old-scene",
                "datetime": "2025-01-02T03:04:05Z",
                "source": "Sentinel-2",
                "processing_level": "L2A",
            }]
        },
        "facts": {"operation": "index_stats"},
    }
    save_history_job("legacy", "2025-01-03T00:00:00Z", "old query",
                     {"operation": "index_stats"}, AOI, "completed", legacy_result)

    try:
        response = client.get("/history/legacy")
        assert response.status_code == 200
        scene = response.json()["result"]["evidence"]["scenes"][0]
        assert scene["sensor_identity"] == "unknown"
        assert scene["sensor"] is None
        # Read-time compatibility annotation does not rewrite the persisted row.
        stored = get_history("legacy")
        assert "sensor_identity" not in stored["result"]["evidence"]["scenes"][0]
        assert stored["result"]["evidence"]["scenes"][0]["source"] == "Sentinel-2"
    finally:
        keeper.close()


def test_history_summaries_keep_sentinel_families_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / "sensor-history.sqlite"))
    scenes = [
        {
            "item_id": "s2-history",
            "datetime": "2026-01-02T03:04:05Z",
            "sensor": "sentinel-2a",
            "sensor_identity": "sentinel-2",
        },
        {
            "item_id": "s1-history",
            "datetime": "2026-01-03T03:04:05Z",
            "sensor": "Sentinel-1",
            "sensor_identity": "other",
        },
    ]
    for scene in scenes:
        save_history_job(
            scene["item_id"],
            "2026-01-04T00:00:00Z",
            "sensor history test",
            {"operation": "sar_backscatter"},
            AOI,
            "completed",
            {"evidence": {"scenes": [scene]}},
        )

    summaries = {item["id"]: item for item in list_history()}
    assert summaries["s2-history"]["sensor_identity"] == "sentinel-2"
    assert summaries["s2-history"]["sensor"] == "sentinel-2a"
    assert summaries["s1-history"]["sensor_identity"] == "other"
    assert summaries["s1-history"]["sensor"] == "Sentinel-1"


def test_compare_scene_evidence_serialization_accepts_additive_identity_fields():
    scene = SceneRef(
        item_id="compare-scene",
        datetime="2026-06-15T05:00:00+00:00",
        provider="synthetic test catalog",
        collection="sentinel-2-l2a",
        platform="Sentinel-2A",
        sensor="Sentinel-2A",
        sensor_identity="sentinel-2",
    ).model_dump()
    restored = SceneRef.model_validate(json.loads(json.dumps(scene)))
    assert restored.sensor_identity == "sentinel-2"
    assert restored.item_id == "compare-scene"
