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
