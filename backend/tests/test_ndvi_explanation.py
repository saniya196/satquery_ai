import math

from app.llm.explainer import NDVI_SYSTEM_PROMPT, make_llm_fn
from app.validation.grounding import check_grounding, grounded_answer, template_answer


def _facts(**overrides):
    facts = {
        "operation": "index_stats",
        "index": "NDVI",
        "date": "2026-06-06",
        "stats": {
            "mean": 0.29,
            "median": 0.25,
            "std": 0.12,
            "min": -0.1,
            "max": 0.7,
            "valid_fraction": 0.95,
            "coverage_fraction": 0.42,
        },
        "analysed_area_km2": 2.4,
        "thresholds": {"vegetation_ndvi": 0.3},
        "spatial_evidence_available": True,
        "provenance": {
            "scene_ids": ["S2C_43QHU_20260606_0_L2A"],
            "provider": "Element84 Earth Search",
            "collection": "sentinel-2-l2a",
            "cloud_cover": 4.9,
        },
    }
    facts.update(overrides)
    return facts


def test_ndvi_fallback_explains_all_supplied_stats_and_provenance_groundedly():
    facts = _facts()
    answer = grounded_answer(facts)
    text = answer["text"]
    assert answer["source"] == "template"
    for expected in (
        "mean 0.290", "median 0.250", "standard deviation 0.120", "minimum -0.100",
        "maximum 0.700", "Valid-pixel coverage is 95.0%", "42.0% of valid pixels",
        "threshold of 0.30", "2026-06-06", "2.40 km2", "4.9%", "Element84 Earth Search",
        "S2C_43QHU_20260606_0_L2A", "pixel map contains spatial evidence",
        "cannot show vegetation loss or improvement",
    ):
        assert expected in text
    assert check_grounding(text, facts)["valid"]


def test_ndvi_missing_fields_are_omitted_without_inventing_metrics():
    facts = _facts(date=None, stats={"median": None, "valid_fraction": None}, provenance={})
    text = template_answer(facts)
    assert "NDVI summary statistics are unavailable or invalid" in text
    assert "acquired on" not in text
    assert "mean 0." not in text
    assert "Valid-pixel coverage is unavailable" in text
    assert check_grounding(text, facts)["valid"]


def test_ndvi_zero_measurements_are_kept_as_valid_values():
    facts = _facts(stats={"mean": 0.0, "median": 0.0, "std": 0.0, "min": 0.0, "max": 0.0,
                          "valid_fraction": 0.0, "coverage_fraction": 0.0})
    text = template_answer(facts)
    assert "mean 0.000" in text and "median 0.000" in text
    assert "standard deviation 0.000" in text
    assert "Valid-pixel coverage is 0.0%" in text
    assert "0.0% of valid pixels meet" in text
    assert check_grounding(text, facts)["valid"]


def test_ndvi_invalid_or_nonfinite_statistics_are_not_reported():
    facts = _facts(stats={"mean": 2.0, "median": math.nan, "std": -0.1, "min": 0.8, "max": -0.4,
                          "valid_fraction": 1.2, "coverage_fraction": -0.1})
    text = template_answer(facts)
    assert "NDVI summary statistics are unavailable or invalid" in text
    assert "Valid-pixel coverage is unavailable or invalid" in text
    assert "Measured NDVI:" not in text
    assert check_grounding(text, facts)["valid"]


def test_ndvi_configured_llm_uses_ndvi_specific_grounded_prompt():
    calls = []

    class Client:
        def complete(self, system, user):
            calls.append((system, user))
            return "NDVI mean 0.290 was measured on 2026-06-06."

    llm = make_llm_fn(Client())
    facts = _facts()
    answer = grounded_answer(facts, llm)
    assert answer["source"] == "llm"
    assert calls[0][0] == NDVI_SYSTEM_PROMPT
    assert check_grounding(answer["text"], facts)["valid"]


def test_ndvi_llm_ungrounded_answer_falls_back_to_deterministic_explanation():
    facts = _facts()
    answer = grounded_answer(facts, lambda _facts, _errors: "The mean NDVI was 0.88.", max_retries=0)
    assert answer["source"] == "template"
    assert "mean 0.290" in answer["text"]
    assert check_grounding(answer["text"], facts)["valid"]
