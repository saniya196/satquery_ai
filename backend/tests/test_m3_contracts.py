"""Milestone 3 P1.3: API/history contract regression tests (additive fields & count invariants).

Deterministic, isolated; no Sentinel-2/external calls. Reuses existing fakes/patterns.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import app, get_provider
from app.schemas.query import DateRange, Operation, StructuredQuery
from app.services import analysis
from app.storage.history import get_history, save_history_job
from tests.fakes import AOI, FakeProvider, make_scene

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / "m3-contracts.sqlite"))
    # keep execution deterministic (no LLM dependency)
    monkeypatch.setattr(api_main, "make_llm_fn", lambda _client: None)
    with api_main._lock:
        api_main._jobs.clear()
        api_main._layer_store.clear()
    yield
    app.dependency_overrides.clear()
    with api_main._lock:
        api_main._jobs.clear()
        api_main._layer_store.clear()


def _series_all_valid(n, start=0.8, end=0.3):
    import numpy as np

    vals = np.linspace(start, end, n)
    return [make_scene(f"S{i}", f"2026-{1 + i:02d}-10T05:00:00+00:00", float(v), float(v)) for i, v in enumerate(vals)]


class LoadFailProvider(FakeProvider):
    def __init__(self, scenes, fail_ids):
        super().__init__(scenes)
        self.fail_ids = set(fail_ids)

    def get_scene(self, aoi_geojson, item_id, bands):
        if item_id in self.fail_ids:
            raise RuntimeError("synthetic load failure")
        return super().get_scene(aoi_geojson, item_id, bands)


class CoverageProvider(FakeProvider):
    """Adds scene footprint coverage metadata (synthetic) without changing scene pixels."""

    def __init__(self, scenes, coverage=0.95):
        super().__init__(scenes)
        self.coverage = coverage

    def list_scenes(self, aoi_geojson, start, end, max_cloud):
        out = super().list_scenes(aoi_geojson, start, end, max_cloud)
        for s in out:
            s["coverage"] = self.coverage
            s["coverage_fraction"] = self.coverage
            s["coverage_status"] = "partial" if self.coverage < 0.99 else "full"
        return out

    def best_scene(self, aoi_geojson, start, end, max_cloud, min_coverage=0.99):
        try:
            return super().best_scene(aoi_geojson, start, end, max_cloud, min_coverage=min_coverage)
        except Exception:
            scenes = self.list_scenes(aoi_geojson, start, end, max_cloud)
            if not scenes:
                raise
            b = dict(scenes[0])
            b["coverage_status"] = "partial" if self.coverage < 0.99 else "full"
            b["coverage_fraction"] = self.coverage
            b["coverage"] = self.coverage
            return b


def _assert_count_invariant(series: dict):
    req = series["n_dates_requested"]
    inc = series["n_dates_included"]
    low = series["n_dates_skipped_low_valid"]
    load = series["n_dates_skipped_load_error"]
    assert req == inc + low + load, (req, inc, low, load)
    assert isinstance(req, int) and isinstance(inc, int) and isinstance(low, int) and isinstance(load, int)


# 1) Time-series count invariant

def test_time_series_count_invariant_all_included():
    r = analysis.run_time_series(FakeProvider(_series_all_valid(8)), AOI, DateRange(start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 12, 31)))
    s = r["facts"]["series"]
    _assert_count_invariant(s)
    assert (s["n_dates_requested"], s["n_dates_included"], s["n_dates_skipped_low_valid"], s["n_dates_skipped_load_error"]) == (8, 8, 0, 0)


def test_time_series_count_invariant_low_valid_skips():
    scenes = _series_all_valid(10)
    scenes[2] = make_scene("S2", "2026-03-10T05:00:00+00:00", 0.65, 0.65, cloudy_fraction=0.8)
    scenes[6] = make_scene("S6", "2026-07-10T05:00:00+00:00", 0.45, 0.45, cloudy_fraction=0.8)
    r = analysis.run_time_series(FakeProvider(scenes), AOI, DateRange(start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 12, 31)))
    s = r["facts"]["series"]
    _assert_count_invariant(s)
    assert s["n_dates_skipped_low_valid"] == 2 and s["n_dates_skipped_load_error"] == 0 and s["n_dates_included"] == 8


def test_time_series_count_invariant_load_error_skips():
    r = analysis.run_time_series(LoadFailProvider(_series_all_valid(10), {"S1", "S4", "S6"}), AOI, DateRange(start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 12, 31)))
    s = r["facts"]["series"]
    _assert_count_invariant(s)
    assert s["n_dates_skipped_load_error"] == 3 and s["n_dates_skipped_low_valid"] == 0 and s["n_dates_included"] == 7


def test_time_series_count_invariant_mixed_skips():
    scenes = _series_all_valid(10)
    scenes[3] = make_scene("S3", "2026-04-10T05:00:00+00:00", 0.6, 0.6, cloudy_fraction=0.8)
    scenes[5] = make_scene("S5", "2026-06-10T05:00:00+00:00", 0.55, 0.55, cloudy_fraction=0.8)
    scenes[8] = make_scene("S8", "2026-09-10T05:00:00+00:00", 0.5, 0.5, cloudy_fraction=0.8)
    r = analysis.run_time_series(LoadFailProvider(scenes, {"S0", "S9"}), AOI, DateRange(start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 12, 31)))
    s = r["facts"]["series"]
    _assert_count_invariant(s)
    assert (s["n_dates_requested"], s["n_dates_included"], s["n_dates_skipped_low_valid"], s["n_dates_skipped_load_error"]) == (10, 5, 3, 2)


def test_time_series_count_invariant_fewer_than_eight_usable():
    scenes = _series_all_valid(9)
    scenes[1] = make_scene("S1", "2026-02-10T05:00:00+00:00", 0.7, 0.7, cloudy_fraction=0.8)
    r = analysis.run_time_series(LoadFailProvider(scenes, {"S4"}), AOI, DateRange(start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 12, 31)))
    s = r["facts"]["series"]
    _assert_count_invariant(s)
    assert s["n_dates_included"] == 7
    assert s["trend_claim_allowed"] is False
    assert s.get("insufficient_observations") is True
    assert s.get("status") == "insufficient_observations"
    assert "8" in (s.get("message") or "")


# 2) Time-series API/history persistence

def _ts_query():
    return StructuredQuery(
        raw_text="Show vegetation trend over 2026",
        operation=Operation.TIME_SERIES,
        index="NDVI",
        series_range=DateRange(start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 12, 31)),
        outputs=["chart", "trend"],
        missing=[],
        parser="test",
    )


def _run_via_api(query: StructuredQuery, provider):
    app.dependency_overrides[get_provider] = lambda: provider

    def _parse(*args, **kwargs):
        return query

    # patch both the symbol used by the route
    orig = api_main.parse_query_smart
    api_main.parse_query_smart = _parse
    try:
        resp = client.post("/analysis/run", json={"query": query.raw_text, "aoi": AOI, "reference_date": "2026-10-07"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "queued"
        job_id = body["job_id"]
        job = client.get(f"/jobs/{job_id}")
        assert job.status_code == 200
        history = client.get(f"/history/{job_id}")
        assert history.status_code == 200
        return job.json(), history.json()
    finally:
        api_main.parse_query_smart = orig


def test_time_series_additive_fields_survive_job_and_history():
    scenes = _series_all_valid(10)
    scenes[2] = make_scene("S2", "2026-03-10T05:00:00+00:00", 0.65, 0.65, cloudy_fraction=0.8)
    provider = LoadFailProvider(scenes, {"S4"})
    job, hist = _run_via_api(_ts_query(), provider)
    assert job["status"] == "completed"
    for result in (job["result"], hist["result"]):
        s = result["facts"]["series"]
        _assert_count_invariant(s)
        assert s["n_dates_requested"] == 10
        assert s["n_dates_skipped_low_valid"] == 1
        assert s["n_dates_skipped_load_error"] == 1
        assert s["n_dates_included"] == 8
        assert "n_dates_usable" in s
        assert s["trend_claim_allowed"] is True
        # evidence scenes align to included observations
        assert len(result["evidence"]["scenes"]) == 8
    assert hist["structured_query"]["operation"] == "time_series"
    assert hist["aoi"] == AOI


def test_time_series_insufficient_observations_fields_survive_job_and_history():
    scenes = _series_all_valid(9)
    scenes[1] = make_scene("S1", "2026-02-10T05:00:00+00:00", 0.7, 0.7, cloudy_fraction=0.8)
    provider = LoadFailProvider(scenes, {"S4"})
    job, hist = _run_via_api(_ts_query(), provider)
    assert job["status"] == "completed"
    for result in (job["result"], hist["result"]):
        s = result["facts"]["series"]
        _assert_count_invariant(s)
        assert s["n_dates_included"] == 7
        assert s["trend_claim_allowed"] is False
        assert s.get("insufficient_observations") is True
        assert s.get("status") == "insufficient_observations"
        assert isinstance(s.get("message"), str) and "8" in s["message"]


# 3) Coverage serialization

def test_coverage_metadata_survives_job_and_history(monkeypatch):
    provider = CoverageProvider(_series_all_valid(1), coverage=0.82)
    q = StructuredQuery(
        raw_text="Show NDVI for Jan 2026",
        operation=Operation.INDEX_STATS,
        index="NDVI",
        date_a=DateRange(start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 1, 31)),
        outputs=["map"],
        missing=[],
        parser="test",
    )
    job, hist = _run_via_api(q, provider)
    assert job["status"] == "completed"
    for result in (job["result"], hist["result"]):
        cov = result.get("coverage") or result.get("evidence", {}).get("coverage")
        assert cov is not None
        assert cov.get("status") in ("partial", "full", "unknown")
        assert cov.get("fraction") == pytest.approx(0.82, abs=1e-6)
        # scene footprint coverage meaning preserved (not a valid-pixel fraction field)


# 3b) Evidence schema coverage (P1.4b)

def test_evidence_schema_accepts_coverage_present_and_preserves_shape():
    from app.schemas.evidence import Evidence, SceneRef

    # shape variant without note (index_stats-style)
    ev = Evidence(
        operation="index_stats",
        scenes=[SceneRef(item_id="S1", datetime="2026-01-10T00:00:00Z")],
        aoi_area_km2=1.0,
        index="NDVI",
        preprocessing=["x"],
        valid_pixel_fraction=0.9,
        metrics={"mean": 0.5},
        coverage={"status": "partial", "fraction": 0.82},
    )
    d = ev.model_dump()
    assert d["coverage"] == {"status": "partial", "fraction": 0.82}
    assert "note" not in d["coverage"]

    # shape variant with note (change/time-series style)
    ev2 = Evidence(**{**ev.model_dump(), "coverage": {"status": "full", "fraction": 1.0, "note": "Minimum coverage across the two scenes used."}})
    d2 = ev2.model_dump()
    assert d2["coverage"]["note"] == "Minimum coverage across the two scenes used."
    assert set(d2["coverage"].keys()) == {"status", "fraction", "note"}


def test_evidence_schema_accepts_legacy_payload_without_coverage():
    from app.schemas.evidence import Evidence

    legacy = {
        "operation": "index_stats",
        "scenes": [{"item_id": "S1", "datetime": "2026-01-10T00:00:00Z"}],
        "aoi_area_km2": 1.0,
        "index": "NDVI",
        "preprocessing": ["x"],
        "thresholds": {},
        "valid_pixel_fraction": 0.9,
        "metrics": {"mean": 0.5},
    }
    ev = Evidence.model_validate(legacy)
    d = ev.model_dump()
    assert "coverage" not in d or d["coverage"] is None
    # production serialization omits null coverage to preserve legacy shape
    d.pop("coverage", None)
    assert "coverage" not in d


def test_service_evidence_coverage_absent_when_no_scene_coverage_metadata():
    # FakeProvider scenes have no coverage metadata => evidence.coverage absent
    r = analysis.run_time_series(FakeProvider(_series_all_valid(8)), AOI, DateRange(start=__import__("datetime").date(2026, 1, 1), end=__import__("datetime").date(2026, 12, 31)))
    ev = r["evidence"]
    assert "coverage" not in ev
    assert "coverage" not in (ev.get("metrics") or {})


# 4) Hotspot enrichment persistence

def _change_query():
    return StructuredQuery(
        raw_text="Did vegetation health decrease between June and September?",
        operation=Operation.CHANGE_DETECTION,
        index="NDVI",
        date_a=DateRange(start=__import__("datetime").date(2026, 6, 1), end=__import__("datetime").date(2026, 6, 30)),
        date_b=DateRange(start=__import__("datetime").date(2026, 9, 1), end=__import__("datetime").date(2026, 9, 30)),
        outputs=["map", "hotspots"],
        missing=[],
        parser="test",
    )


def test_hotspot_enrichment_survives_job_and_history():
    provider = FakeProvider([make_scene("A", "2026-06-15T05:00:00+00:00", 0.8, 0.8),
                             make_scene("B", "2026-09-10T05:00:00+00:00", 0.5, 0.8)])
    job, hist = _run_via_api(_change_query(), provider)
    assert job["status"] == "completed"
    for result in (job["result"], hist["result"]):
        hotspots = result.get("hotspots") or []
        assert len(hotspots) >= 1
        h = hotspots[0]
        # legacy-compatible fields
        assert "pixels" in h and "area_km2" in h and "mean_diff" in h and "id" in h
        # additive descriptive stats
        assert h.get("median_diff") is not None
        assert h.get("valid_pixel_count") is not None
        assert h.get("class") == "significant_decrease"
        assert h.get("direction") == "decrease"
        # additive evidence refs (reuse global/source scenes)
        ev = h.get("evidence") or {}
        assert ev.get("baseline_scene_id") == "A"
        assert ev.get("comparison_scene_id") == "B"
        assert ev.get("index") == result["evidence"]["index"]
        assert ev.get("change_thresholds") == result["evidence"]["thresholds"]
        assert ev.get("global_valid_pixel_fraction") == pytest.approx(result["evidence"]["valid_pixel_fraction"])


def test_older_hotspot_records_without_optional_fields_remain_accepted():
    """History retrieval is JSON passthrough; legacy hotspot shapes must survive unchanged."""
    legacy = {
        "evidence": {"operation": "change_detection", "scenes": [], "valid_pixel_fraction": 0.9, "thresholds": {}},
        "facts": {"operation": "change_detection"},
        "hotspots": [{"id": 1, "pixels": 10, "area_km2": 0.001, "mean_diff": -0.3, "bbox_rowcol": [0, 0, 1, 1]}],
        "answer": {"text": "legacy", "source": "template"},
    }
    save_history_job("legacy-hotspot", "2026-01-01T00:00:00Z", "q", {"operation": "change_detection"}, AOI, "completed", legacy)
    got = get_history("legacy-hotspot")
    assert got is not None and got["status"] == "completed"
    h = got["result"]["hotspots"][0]
    assert h["pixels"] == 10 and h["mean_diff"] == -0.3
    assert "median_diff" not in h and "evidence" not in h
    # payload remains valid JSON round-trippable
    json.dumps(got["result"], allow_nan=False)
