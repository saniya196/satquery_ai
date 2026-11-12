from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import app, get_provider
from app.investigation.orchestrator import run_investigation
from app.investigation.planner import build_plan
from app.llm.client import LLMClient
from app.validation.grounding import check_grounding
from tests.fakes import AOI, FakeProvider, make_scene


client = TestClient(app)


class NoClient(LLMClient):
    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        raise AssertionError("The investigation tests must not call an LLM.")


@pytest.fixture(autouse=True)
def isolate_investigation(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / "investigation.sqlite"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with api_main._lock:
        api_main._jobs.clear()
        api_main._layer_store.clear()
    yield
    app.dependency_overrides.clear()


def _provider():
    return FakeProvider([
        make_scene("A", "2026-06-15T05:00:00+00:00", 0.8, 0.8),
        make_scene("B", "2026-09-10T05:00:00+00:00", 0.5, 0.8),
    ])


def test_planner_requires_aoi_and_two_periods_for_change():
    plan, query = build_plan("Investigate vegetation changes and hotspots", None, date(2026, 10, 7), None)
    assert query.operation.value == "change_detection"
    assert plan.can_execute is False
    assert "an area of interest (AOI) drawn/selected on the map" in plan.missing_required_inputs
    assert any("two comparison periods" in item for item in plan.missing_required_inputs)
    assert plan.selected_tools[0].params["operation"] == "change_detection"


def test_unsupported_question_does_not_select_or_execute_a_tool():
    plan, query = build_plan("Will it rain tomorrow?", AOI, date(2026, 10, 7), None)
    assert query.operation.value == "unsupported"
    assert plan.selected_tools == []
    assert plan.can_execute is False


def test_investigation_executes_real_change_tool_and_returns_trace_evidence():
    result = run_investigation(
        "Investigate vegetation changes and identify significant decrease hotspots between June and September",
        AOI,
        date(2026, 10, 7),
        40,
        _provider(),
        None,
    )
    assert result.status == "completed"
    assert result.tools_executed[0].status == "completed"
    assert result.tools_executed[0].actual_result["facts"]["change"]["mean_change"] == pytest.approx(-0.15)
    assert result.supporting_evidence[0]["scenes"][0]["item_id"] == "A"
    assert any(event.tool == "ndvi_change_hotspots" and event.status == "completed" for event in result.trace)
    assert result.explanation["validated"] is True
    assert "cause" in result.explanation["text"].lower()


def test_investigation_reports_tool_failure_without_fabricated_findings():
    result = run_investigation(
        "Investigate vegetation changes between June and September",
        AOI,
        date(2026, 10, 7),
        40,
        FakeProvider([]),
        None,
    )
    assert result.status == "failed"
    assert result.actual_findings == {}
    assert result.tools_executed[0].status == "failed"
    assert any(event.status == "failed" for event in result.trace)
    assert "failed" in result.data_quality_and_uncertainty["limitations"][0].lower()


def test_investigation_api_contract_returns_plan_trace_and_evidence():
    app.dependency_overrides[get_provider] = _provider
    response = client.post("/analysis/investigate", json={
        "query": "Investigate vegetation changes between June and September",
        "aoi": AOI,
        "reference_date": "2026-10-07",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["plan"]["selected_tools"][0]["tool"] == "ndvi_change_hotspots"
    assert body["trace"]
    assert body["supporting_evidence"][0]["scenes"]
    assert body["explanation"]["validated"] is True


def test_causal_claims_are_not_presented_as_grounded_measurements():
    result = run_investigation(
        "Investigate vegetation changes between June and September",
        AOI,
        date(2026, 10, 7),
        40,
        _provider(),
        None,
    )
    assert result.unsupported_conclusions == []
    assert check_grounding(result.explanation["text"], {
        "facts": result.actual_findings["ndvi_change_hotspots"]["facts"],
        "confidence": result.actual_findings["ndvi_change_hotspots"]["confidence"],
    }, allowed_literals=tuple(range(0, 101)))["valid"]
