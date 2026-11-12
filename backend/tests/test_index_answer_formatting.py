from app.validation.grounding import check_grounding, template_answer


def test_multindex_answer_keeps_small_negative_values_visible_and_punctuated():
    facts = {
        "operation": "index_stats",
        "index": "MNDWI",
        "date": "2026-11-08",
        "stats": {
            "mean": -0.23459650485759345,
            "median": -0.23430152143845093,
            "std": 0.06641738521768163,
            "min": -0.4475362318840579,
            "max": -0.00352039759784636,
            "valid_fraction": 1.0,
        },
        "analysed_area_km2": 0.1891,
        "coverage": {"fraction": 1.0},
        "provenance": {
            "scene_ids": ["S2B_43QHV_20261108_0_L2A"],
            "provider": "Element84 Earth Search",
            "collection": "sentinel-2-l2a",
        },
        "data_quality_score": 97.0,
    }
    answer = template_answer(facts)
    assert "AOI on 2026-11-08. The analyzed AOI area is 0.19 km2." in answer
    assert "Values ranged from -0.448 to -0.004" in answer
    assert "to -0.00," not in answer
    assert "sentinel-2-l2a" not in answer
    assert check_grounding(answer, facts)["valid"]
