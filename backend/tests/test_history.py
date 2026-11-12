import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, get_provider
from tests.fakes import AOI, FakeProvider, make_scene

client = TestClient(app)


@pytest.fixture
def fake_history_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / "history.sqlite"))
    provider = FakeProvider([
        make_scene("A", "2026-06-15T05:00:00+00:00", 0.8, 0.8, coverage=1.0),
        make_scene("B", "2026-09-10T05:00:00+00:00", 0.5, 0.8, coverage=1.0),
    ])
    app.dependency_overrides[get_provider] = lambda: provider
    yield
    app.dependency_overrides.clear()


def _run_change():
    return client.post("/analysis/run", json={
        "query": "Did vegetation health decrease between June and September?",
        "aoi": AOI,
        "reference_date": "2026-10-07",
    }).json()


def test_history_list_detail_and_delete_use_sqlite(fake_history_environment):
    run = _run_change()
    job_id = run["job_id"]

    listing = client.get("/history")
    assert listing.status_code == 200
    summary = listing.json()["items"][0]
    assert summary == {
        "id": job_id,
        "created": client.get(f"/jobs/{job_id}").json()["created"],
        "query": "Did vegetation health decrease between June and September?",
        "status": "completed",
        "operation": "change_detection",
        "sensor_identity": "unknown",
        "sensor": None,
        "acquisition_dates": ["2026-06-15", "2026-09-10"],
        "aoi_area_km2": pytest.approx(client.get(f"/history/{job_id}").json()["result"]["evidence"]["aoi_area_km2"]),
    }
    assert "result" not in listing.json()["items"][0]

    detail = client.get(f"/history/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["aoi"] == AOI
    assert detail.json()["structured_query"]["operation"] == "change_detection"
    assert detail.json()["result"]["facts"]["change"]["mean_change"] == pytest.approx(-0.15)

    assert client.delete(f"/history/{job_id}").status_code == 204
    assert client.get(f"/history/{job_id}").status_code == 404
    assert client.delete(f"/history/{job_id}").status_code == 404


def test_stored_result_exports_csv_and_geojson(fake_history_environment):
    run = _run_change()
    job_id = run["job_id"]

    csv_response = client.get(f"/analysis/{job_id}/export.csv")
    assert csv_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert any(row["metric"] == "change.mean_change" and float(row["value"]) == pytest.approx(-0.15)
               for row in rows)

    geo_response = client.get(f"/analysis/{job_id}/export.geojson")
    assert geo_response.status_code == 200
    feature = json.loads(geo_response.text)
    assert feature["type"] == "Feature"
    assert feature["geometry"] == AOI
    assert feature["properties"]["change"]["mean_change"] == pytest.approx(-0.15)


def test_compare_runs_same_operation_for_both_aois(fake_history_environment):
    response = client.post("/analysis/compare", json={
        "query": "Did vegetation health decrease between June and September?",
        "aoi_a": AOI,
        "aoi_b": AOI,
        "reference_date": "2026-10-07",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["aoi_a"]["result"]["facts"]["operation"] == "change_detection"
    assert body["aoi_b"]["result"]["facts"]["operation"] == "change_detection"
    assert body["differences"]["change.mean_change"] == pytest.approx(0.0)
    assert "arrays" not in body["aoi_a"]["result"]


def test_exports_and_compare_return_clear_errors(fake_history_environment):
    assert client.get("/analysis/missing/export.csv").status_code == 404
    bad = client.post("/analysis/compare", json={
        "query": "Show NDVI for June",
        "aoi_a": AOI,
        "aoi_b": {"type": "Point", "coordinates": [0, 0]},
        "reference_date": "2026-10-07",
    })
    assert bad.status_code == 422


def test_failed_jobs_are_saved_and_time_series_csv_has_per_date_rows(fake_history_environment):
    failed = client.post("/analysis/run", json={
        "query": "Did vegetation decrease between January and February?",
        "aoi": AOI,
        "reference_date": "2026-10-07",
    }).json()
    failed_job = client.get(f"/jobs/{failed['job_id']}").json()
    assert failed_job["status"] == "failed"
    failed_record = client.get(f"/history/{failed['job_id']}").json()
    assert failed_record["status"] == "failed"
    assert failed_record["result"]["error"]["code"] == "no_imagery"

    from tests.fakes import make_scene
    provider = FakeProvider([
        make_scene("T1", "2026-01-10T05:00:00+00:00", 0.8, 0.8),
        make_scene("T2", "2026-02-10T05:00:00+00:00", 0.7, 0.7),
        make_scene("T3", "2026-03-10T05:00:00+00:00", 0.6, 0.6),
    ])
    app.dependency_overrides[get_provider] = lambda: provider
    series_run = client.post("/analysis/run", json={
        "query": "Show vegetation trend over the last year",
        "aoi": AOI,
        "reference_date": "2026-10-07",
    }).json()
    series_job = client.get(f"/jobs/{series_run['job_id']}").json()
    assert series_job["status"] == "completed"
    rows = list(csv.DictReader(io.StringIO(client.get(
        f"/analysis/{series_run['job_id']}/export.csv").text)))
    dates = {row["date"] for row in rows if row["metric"] == "series.value"}
    assert dates == {"2026-01-10", "2026-02-10", "2026-03-10"}
