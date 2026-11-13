import json
from datetime import date

import httpx
import pytest

from app.llm.client import GeminiClient, LLMClient, LLMError, get_llm_client
from app.llm.explainer import make_llm_fn
from app.query_engine.llm_parser import has_date_cue, parse_query_smart, parse_with_llm
from app.schemas.query import DateRange, Operation
from app.validation.grounding import grounded_answer

REF = date(2026, 10, 7)


class FakeLLM(LLMClient):
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def complete(self, system, user, json_mode=False):
        self.calls.append((system, user, json_mode))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


CHANGE_JSON = json.dumps({
    "operation": "change_detection", "index": "ndvi",
    "date_a": {"start": "2026-06-01", "end": "2026-06-30"},
    "date_b": {"start": "2026-09-01", "end": "2026-09-30"},
    "change_direction": "decrease"})


def test_llm_parse_matches_rule_parser_shape():
    q = parse_with_llm("Did crops get worse between June and September?", FakeLLM(CHANGE_JSON), REF)
    assert q.parser == "llm" and q.operation == Operation.CHANGE_DETECTION and q.index == "NDVI"
    assert q.date_a.start == date(2026, 6, 1) and not q.missing


def test_markdown_fenced_json_is_accepted():
    q = parse_with_llm("compare June and September", FakeLLM("```json\n" + CHANGE_JSON + "\n```"), REF)
    assert q.operation == Operation.CHANGE_DETECTION


def test_hallucinated_dates_are_dropped_and_user_is_asked():
    q = parse_with_llm("Did vegetation decrease?", FakeLLM(CHANGE_JSON), REF)
    assert q.date_a is None and q.date_b is None and q.missing


@pytest.mark.parametrize("reply", ["not json at all", '{"operation": "make_coffee"}', "[1, 2]", ""])
def test_bad_llm_output_falls_back_to_rules(reply):
    q = parse_query_smart("Did vegetation health decrease between June and September?", REF, FakeLLM(reply))
    assert q.parser == "rules" and q.operation == Operation.CHANGE_DETECTION and not q.missing


def test_llm_outage_falls_back_to_rules():
    q = parse_query_smart("Did vegetation health decrease between June and September?", REF,
                          FakeLLM(LLMError("down")))
    assert q.parser == "rules" and q.operation == Operation.CHANGE_DETECTION


def test_explicit_iso_dates_override_different_llm_dates():
    reply = json.dumps({
        "operation": "change_detection", "index": "NDVI",
        "date_a": {"start": "2026-10-09", "end": "2026-10-09"},
        "date_b": {"start": "2026-10-04", "end": "2026-10-04"},
    })
    q = parse_with_llm(
        "Investigate vegetation changes between 2026-10-04 and 2026-10-29",
        FakeLLM(reply), REF,
    )
    assert q.date_a.start == date(2026, 10, 4)
    assert q.date_b.start == date(2026, 10, 29)


def test_explicit_iso_dates_override_different_valid_llm_ranges():
    reply = json.dumps({
        "operation": "change_detection", "index": "NDVI",
        "date_a": {"start": "2026-01-01", "end": "2026-01-31"},
        "date_b": {"start": "2026-02-01", "end": "2026-02-28"},
    })
    q = parse_with_llm(
        "Compare NDVI on 2026-10-04 and 2026-10-29",
        FakeLLM(reply), REF,
    )
    assert q.date_a == DateRange(start=date(2026, 10, 4), end=date(2026, 10, 4))
    assert q.date_b == DateRange(start=date(2026, 10, 29), end=date(2026, 10, 29))


def test_without_two_explicit_iso_dates_preserves_llm_dates():
    q = parse_with_llm(
        "Compare NDVI between June and September",
        FakeLLM(CHANGE_JSON), REF,
    )
    assert q.date_a.start == date(2026, 6, 1)
    assert q.date_b.start == date(2026, 9, 1)


def test_no_client_uses_rules():
    assert parse_query_smart("Show me the vegetation trend over the last year", REF, None).parser == "rules"


def test_unsupported_from_llm_carries_a_reason():
    q = parse_with_llm("write a poem", FakeLLM('{"operation": "unsupported"}'), REF)
    assert q.operation == Operation.UNSUPPORTED and q.unsupported_reason


def test_bad_index_is_ignored_and_reversed_range_dropped():
    reply = json.dumps({"operation": "index_stats", "index": "XYZ",
                        "date_a": {"start": "2026-09-30", "end": "2026-09-01"}})
    q = parse_with_llm("water in September", FakeLLM(reply), REF)
    assert q.index is None and q.date_a is None and q.missing


@pytest.mark.parametrize("text,expected", [
    ("between June and September", True), ("over the last year", True), ("in 2025", True),
    ("पिछले साल का रुझान", True), ("Did vegetation decrease?", False),
    ("Which parts may have lost vegetation?", False), ("what about in May", True)])
def test_date_cue_detection(text, expected):
    assert has_date_cue(text) is expected


FACTS = {"operation": "change_detection", "index": "NDVI", "date_a": "2026-06-15", "date_b": "2026-09-10",
         "change": {"mean_a": 0.71, "mean_b": 0.58, "mean_change": -0.13, "percent_change_of_mean": -18.32,
                    "classes": {"significant_decrease": {"area_km2": 0.18, "fraction_of_valid": 0.5, "pixels": 1800}}},
         "data_quality_score": 91.4}


def test_explainer_retries_with_error_feedback_then_accepts():
    llm = FakeLLM("NDVI fell by 40%.", "NDVI fell about 18.3% between 2026-06-15 and 2026-09-10. Quality 91/100.")
    out = grounded_answer(FACTS, make_llm_fn(llm))
    assert out["source"] == "llm" and out["attempts"] == 2
    assert "40" in llm.calls[1][1] and "FACTS" in llm.calls[1][1]   # the rejected value is fed back


def test_explainer_never_lets_a_wrong_number_through():
    out = grounded_answer(FACTS, make_llm_fn(FakeLLM("It fell 99%.", "It fell 98%.", "It fell 97%.")))
    assert out["source"] == "template"


def test_explainer_none_without_client():
    assert make_llm_fn(None) is None


def _gemini(handler):
    return GeminiClient("secret-key", model="m", transport=httpx.MockTransport(handler))


def test_gemini_request_shape_and_parsing():
    seen = {}

    def handler(req):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-goog-api-key"), json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hello"}]}}]})

    assert _gemini(handler).complete("sys", "usr", json_mode=True) == "hello"
    assert seen["url"].endswith("/models/m:generateContent") and seen["key"] == "secret-key"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["generationConfig"]["temperature"] == 0
    assert "secret-key" not in str(seen["url"])


@pytest.mark.parametrize("resp", [httpx.Response(500), httpx.Response(200, json={"candidates": []}),
                                  httpx.Response(200, text="not json")])
def test_gemini_failures_raise_llmerror_without_leaking_key(resp):
    with pytest.raises(LLMError) as e:
        _gemini(lambda req: resp).complete("s", "u")
    assert "secret-key" not in str(e.value)


def test_factory_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert get_llm_client() is None
    monkeypatch.setenv("GEMINI_API_KEY", "replace-me-with-your-gemini-api-key")
    assert get_llm_client() is None
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    assert isinstance(get_llm_client(), GeminiClient)
