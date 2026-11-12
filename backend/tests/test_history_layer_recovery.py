"""Regression tests for Phase 8 history-only layer recovery.

Covers history-only completed/failed/unknown cases and ensures existing SQLite job
behavior remains unchanged. Uses temporary DB/artifact dirs and isolated app state;
no real Sentinel-2 data or network access.
"""

import json
from pathlib import Path

import numpy as np
from affine import Affine
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import app
from app.storage import artifacts
from app.storage.history import save_history_job
from app.storage.jobs import create_job, update_job

client = TestClient(app)

AOI = {
    "type": "Polygon",
    "coordinates": [[[80.2, 32.4], [80.8, 32.4], [80.8, 32.9], [80.2, 32.9], [80.2, 32.4]]],
}


def _clear_state():
    with api_main._lock:
        api_main._jobs.clear()
        api_main._layer_store.clear()


def _iso():
    return "2026-01-01T00:00:00+00:00"


def _save_completed_history(job_id: str, query: str = "test"):
    save_history_job(
        job_id,
        _iso(),
        query,
        {"operation": "index_stats", "index": "NDVI"},
        AOI,
        "completed",
        {"facts": {"operation": "index_stats"}, "evidence": {}, "answer": {"text": "ok"}},
    )


def _save_failed_history(job_id: str):
    save_history_job(
        job_id,
        _iso(),
        "test",
        {"operation": "index_stats", "index": "NDVI"},
        AOI,
        "failed",
        {"error": {"code": "no_imagery", "message": "No scenes."}},
    )


def _valid_arrays():
    return {"index": np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)}


def _valid_raster():
    # UTM zone supported by bounds_wgs84 (EPSG:32644). Shape matches arrays (2,2).
    return {"transform": Affine(10, 0, 500000, 0, -10, 4000000), "crs": "EPSG:32644"}


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / "satquery.db"))
    monkeypatch.setenv("SATQUERY_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(api_main, "make_llm_fn", lambda _client: None)
    _clear_state()
    return tmp_path


def test_history_only_completed_with_valid_artifacts_serves_layers(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job_id = "hist-only-ok"
    _save_completed_history(job_id)
    artifacts.save_artifacts(job_id, _valid_arrays(), _valid_raster(), "index_stats")
    try:
        meta = client.get(f"/analysis/{job_id}/layers")
        assert meta.status_code == 200, meta.text
        body = meta.json()
        assert "bounds" in body and len(body["bounds"]) == 2
        assert "index" in body["layers"]
        assert body["layers"]["index"]["value_range"] == [-1.0, 1.0]

        png = client.get(f"/analysis/{job_id}/layer/index.png")
        assert png.status_code == 200, png.text
        assert png.headers["content-type"] == "image/png"
        assert png.content.startswith(b"\x89PNG")

        # Existing history/artifact files were only read; still present.
        assert Path(tmp_path / "satquery.db").exists()
        assert (Path(tmp_path / "artifacts") / job_id / "meta.json").exists()
    finally:
        _clear_state()


def test_history_only_completed_without_artifacts_returns_missing_layers(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job_id = "hist-only-noart"
    _save_completed_history(job_id)
    try:
        res = client.get(f"/analysis/{job_id}/layers")
        assert res.status_code == 404
        assert res.json()["detail"] == "No raster layers are available for this job."
        png = client.get(f"/analysis/{job_id}/layer/index.png")
        assert png.status_code == 404
        assert png.json()["detail"] == "No raster layers are available for this job."
    finally:
        _clear_state()


def test_history_only_completed_missing_crs_rejected_safely(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job_id = "hist-only-nocrs"
    _save_completed_history(job_id)
    # Save artifacts with transform but missing CRS; loader/recovery must reject.
    artifacts.save_artifacts(
        job_id,
        _valid_arrays(),
        {"transform": Affine(10, 0, 500000, 0, -10, 4000000)},
        "index_stats",
    )
    try:
        res = client.get(f"/analysis/{job_id}/layers")
        assert res.status_code == 404
        assert res.json()["detail"] == "No raster layers are available for this job."
    finally:
        _clear_state()


def test_history_only_failed_record_never_treated_as_completed(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job_id = "hist-only-failed"
    _save_failed_history(job_id)
    # Even if artifacts existed, failed history must not trigger recovery.
    artifacts.save_artifacts(job_id, _valid_arrays(), _valid_raster(), "index_stats")
    try:
        res = client.get(f"/analysis/{job_id}/layers")
        assert res.status_code == 409
        assert res.json()["detail"] == "Analysis job is not completed."
        png = client.get(f"/analysis/{job_id}/layer/index.png")
        assert png.status_code == 409
        assert png.json()["detail"] == "Analysis job is not completed."
    finally:
        _clear_state()


def test_unknown_id_preserves_404_unknown_job(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    try:
        res = client.get("/analysis/definitely-missing-id/layers")
        assert res.status_code == 404
        assert res.json()["detail"] == "Unknown job."
        png = client.get("/analysis/definitely-missing-id/layer/index.png")
        assert png.status_code == 404
        assert png.json()["detail"] == "Unknown job."
    finally:
        _clear_state()


def test_existing_completed_sqlite_job_with_valid_artifacts_unchanged(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job_id = "sqlite-job-ok"
    create_job(job_id, "q", {"operation": "index_stats"}, AOI)
    update_job(job_id, status="processing")
    update_job(job_id, status="completed", finished=_iso())
    artifacts.save_artifacts(job_id, _valid_arrays(), _valid_raster(), "index_stats")
    try:
        # No in-memory _jobs entry: exercises existing SQLite+artifact restart path.
        assert job_id not in api_main._jobs
        meta = client.get(f"/analysis/{job_id}/layers")
        assert meta.status_code == 200
        assert "index" in meta.json()["layers"]
        png = client.get(f"/analysis/{job_id}/layer/index.png")
        assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    finally:
        _clear_state()


def test_existing_failed_sqlite_job_unchanged(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job_id = "sqlite-job-failed"
    create_job(job_id, "q", {"operation": "index_stats"}, AOI)
    update_job(job_id, status="processing")
    update_job(job_id, status="failed", finished=_iso(), error={"code": "x", "message": "y"})
    try:
        res = client.get(f"/analysis/{job_id}/layers")
        assert res.status_code == 409
        assert res.json()["detail"] == "Analysis job is not completed."
        png = client.get(f"/analysis/{job_id}/layer/index.png")
        assert png.status_code == 409
    finally:
        _clear_state()
