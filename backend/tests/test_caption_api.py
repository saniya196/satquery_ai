"""API-level tests for the Sentinel-2 scene captioning endpoint.

The satellite provider is a synthetic fake and the BLIP inference itself is
stubbed; everything else (RGB rendering, masking, evidence, PNG artifact,
history persistence) runs the real production code on synthetic rasters.
Synthetic data is used here because these are tests, never user-facing output.
"""
import re
import sqlite3
import uuid
from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.main import app, get_provider
from app.core.errors import CaptionModelUnavailableError, NoImageryError
from app.services import captioning as captioning_service
from app.storage import history as history_storage
from tests.fakes import AOI, FakeProvider, make_scene

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _memory_history(monkeypatch):
    uri = f"file:caption_history_{uuid.uuid4().hex}?mode=memory&cache=shared"
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
    return keeper


class _StubProcessor:
    """Deterministic stand-in for the BLIP processor (tests only)."""

    def __call__(self, images, return_tensors):
        return {"pixel_values": None}

    def decode(self, tokens, skip_special_tokens=True):
        return "a synthetic test caption"


class _StubModel:
    def generate(self, **kwargs):
        return [[7, 8, 9]]

    def parameters(self):
        return iter([])


def _stub_bundle():
    return SimpleNamespace(
        processor=_StubProcessor(), model=_StubModel(), model_dir="synthetic-test-bundle",
        device="cpu", parameter_count=0, model_size_bytes=None, model_dtype=None,
    )


def test_caption_api_persists_result_and_serves_rendered_image(monkeypatch, tmp_path):
    keeper = _memory_history(monkeypatch)
    monkeypatch.setenv("SATQUERY_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(captioning_service, "load_caption_model", _stub_bundle)

    scene = make_scene("S2B_XL1C_20260615", "2026-06-15T10:30:00Z")
    provider = FakeProvider([scene])
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        client = TestClient(app)
        assert client.get("/history").json()["items"] == []
        response = client.post("/caption/analyze", json={
            "aoi": AOI,
            "selected_scene_id": "S2B_XL1C_20260615",
            "start": "2026-06-01",
            "end": "2026-06-30",
            "max_cloud": 40.0,
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "completed"
        assert body["image_url"] == f"/caption/{body['job_id']}/image.png"

        result = body["result"]
        assert result["facts"]["operation"] == "image_captioning"
        assert result["facts"]["caption"] == "a synthetic test caption"
        assert result["facts"]["source_scene_id"] == "S2B_XL1C_20260615"
        assert result["evidence"]["scenes"][0]["item_id"] == "S2B_XL1C_20260615"
        assert result["evidence"]["valid_pixel_fraction"] == 1.0
        assert "aoi_area_km2" in result["evidence"]
        assert result["limitations"], "caption results must carry limitations"
        assert result["model"]["task"] == "image-to-text"
        assert re.fullmatch(r"/caption/[0-9a-f]{32}/image.png", result["image_url"])

        image = client.get(result["image_url"])
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content.startswith(PNG_MAGIC)

        record = client.get(f"/history/{body['job_id']}").json()
        assert record["status"] == "completed"
        assert record["structured_query"]["operation"] == "image_captioning"
        assert record["result"]["facts"]["caption"] == "a synthetic test caption"
    finally:
        app.dependency_overrides.clear()
        keeper.close()


def test_caption_api_persists_scene_failure_as_failed_not_completed(monkeypatch, tmp_path):
    keeper = _memory_history(monkeypatch)
    monkeypatch.setenv("SATQUERY_ARTIFACTS_DIR", str(tmp_path))

    class MissingSceneProvider(FakeProvider):
        def get_scene(self, aoi_geojson, item_id, bands):
            raise NoImageryError(f"Selected scene {item_id} could not be resolved exactly.")

    provider = MissingSceneProvider([make_scene("missing-scene", "2026-06-15T10:30:00Z")])
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        client = TestClient(app)
        response = client.post("/caption/analyze", json={
            "aoi": AOI,
            "selected_scene_id": "missing-scene",
            "start": "2026-06-01",
            "end": "2026-06-30",
        })
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "no_imagery"
        rows = client.get("/history").json()["items"]
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"
        assert rows[0]["operation"] == "image_captioning"
    finally:
        app.dependency_overrides.clear()
        keeper.close()


def test_caption_api_reports_unavailable_model_as_503_without_result(monkeypatch, tmp_path):
    keeper = _memory_history(monkeypatch)
    monkeypatch.setenv("SATQUERY_ARTIFACTS_DIR", str(tmp_path))

    def unavailable():
        raise CaptionModelUnavailableError(
            "The local RSICD caption checkpoint is incomplete. No fallback caption was produced."
        )

    monkeypatch.setattr(captioning_service, "load_caption_model", unavailable)
    scene = make_scene("S2B_UNAV_20260615", "2026-06-15T10:30:00Z")
    provider = FakeProvider([scene])
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        client = TestClient(app)
        response = client.post("/caption/analyze", json={
            "aoi": AOI,
            "selected_scene_id": "S2B_UNAV_20260615",
            "start": "2026-06-01",
            "end": "2026-06-30",
        })
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "caption_model_unavailable"
        assert "No fallback caption" in response.json()["detail"]["message"]
        rows = client.get("/history").json()["items"]
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"
    finally:
        app.dependency_overrides.clear()
        keeper.close()


def test_caption_image_rejects_malformed_job_ids(tmp_path):
    client = TestClient(app)
    for bad in ("deadbeef", "Z" * 32, "0" * 31):
        response = client.get(f"/caption/{bad}/image.png")
        assert response.status_code == 404
