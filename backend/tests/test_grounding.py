from app.validation.grounding import check_grounding, grounded_answer, template_answer

FACTS = {
    "operation": "change_detection", "index": "NDVI", "date_a": "2026-06-15", "date_b": "2026-09-10",
    "change": {"mean_a": 0.71, "mean_b": 0.58, "mean_change": -0.13, "percent_change_of_mean": -18.32,
               "classes": {"significant_decrease": {"area_km2": 0.18, "fraction_of_valid": 0.5, "pixels": 1800}}},
    "data_quality_score": 91.4,
}


def test_correct_answer_passes():
    ans = "NDVI fell from 0.71 on 2026-06-15 to 0.58 on 2026-09-10, an 18.3% decrease. Quality 91/100."
    assert check_grounding(ans, FACTS)["valid"]


def test_changed_number_rejected():
    r = check_grounding("NDVI decreased by 25.0% between the two dates.", FACTS)
    assert not r["valid"] and "25.0" in r["ungrounded_numbers"]


def test_invented_date_rejected():
    r = check_grounding("NDVI fell on 2026-07-01 by 18.3%.", FACTS)
    assert not r["valid"] and r["ungrounded_dates"] == ["2026-07-01"]


def test_fraction_may_be_quoted_as_percent():
    assert check_grounding("About 50% of valid pixels changed significantly.", FACTS)["valid"]


def test_template_answer_is_itself_grounded():
    assert check_grounding(template_answer(FACTS), FACTS)["valid"]


def test_retry_then_accept():
    calls = []

    def llm(facts, errors):
        calls.append(errors)
        return "Dropped 40%." if len(calls) == 1 else "NDVI dropped 18.3% overall."

    out = grounded_answer(FACTS, llm)
    assert out["source"] == "llm" and out["attempts"] == 2 and calls[1] == ["40"]


def test_falls_back_to_template_after_repeated_failures():
    out = grounded_answer(FACTS, lambda f, e: "It fell 99%.", max_retries=2)
    assert out["source"] == "template" and out["attempts"] == 3


def test_llm_exception_falls_back():
    def boom(f, e):
        raise RuntimeError("api down")
    assert grounded_answer(FACTS, boom)["source"] == "template"


def test_index_explanations_are_natural_and_grounded_for_all_supported_indices():
    for index, meaning in {
        "NDVI": "vegetation proxy", "NDWI": "water signal", "MNDWI": "modified spectral water",
        "NDBI": "built-up surface signal", "SAVI": "soil-adjusted vegetation",
    }.items():
        facts = {
            "operation": "index_stats", "index": index, "date": "2026-06-06",
            "stats": {"mean": 0.29, "median": 0.25, "std": 0.12, "min": -0.1, "max": 0.7,
                      "valid_fraction": 0.95},
            "analysed_area_km2": 2.4, "coverage": {"fraction": 0.98},
            "provenance": {"scene_ids": ["S2C_43QHU_20260606_0_L2A"], "provider": "Element84 Earth Search"},
            "data_quality_score": 91.0,
        }
        answer = template_answer(facts)
        assert meaning in answer
        assert "does not establish a cause" in answer
        assert "Element84 Earth Search" in answer and "S2C_43QHU_20260606_0_L2A" in answer
        assert check_grounding(answer, facts)["valid"]


def test_change_and_hotspot_explanation_uses_categories_and_grounded_provenance():
    facts = {
        **FACTS,
        "analysed_area_km2": 0.78,
        "hotspot_summary": {"count": 2},
        "provenance": {"scene_ids": ["SCENE_A", "SCENE_B"], "provider": "Earth Search"},
    }
    answer = template_answer(facts)
    assert "change map shows where" in answer
    assert "2 spatial hotspot cluster(s)" in answer
    assert "do not explain why" in answer
    assert "SCENE_A, SCENE_B" in answer
    assert check_grounding(answer, facts)["valid"]


def test_temporal_trend_explanation_includes_dates_slope_and_caveat():
    facts = {
        "operation": "time_series", "index": "NDVI", "data_quality_score": 88.0,
        "analysed_area_km2": 3.1, "sens_slope_per_year": -0.04,
        "provenance": {"scene_ids": ["SCENE_1", "SCENE_2"], "provider": "Earth Search"},
        "series": {"n": 8, "min": 0.2, "max": 0.6, "dates": ["2025-01-01", "2025-12-01"],
                   "mean_valid_fraction_of_aoi_included": 0.9, "trend_claim_allowed": True,
                   "trend_test": {"trend": "decreasing", "p_value": 0.03, "significant": True}},
    }
    answer = template_answer(facts)
    assert "per-date AOI median NDVI" in answer
    assert "seasonality and autocorrelation" in answer
    assert check_grounding(answer, facts)["valid"]
