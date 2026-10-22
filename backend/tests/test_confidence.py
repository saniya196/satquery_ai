import pytest
from app.evidence.confidence import compute_confidence


def test_deterministic():
    kw = dict(valid_fraction=0.87, cloud_cover_pct=12.0, temporal_gap_days=90)
    assert compute_confidence(**kw) == compute_confidence(**kw)


def test_ideal_inputs_score_high_and_poor_inputs_low():
    good = compute_confidence(valid_fraction=0.95, cloud_cover_pct=1, temporal_gap_days=90)["score"]
    bad = compute_confidence(valid_fraction=0.35, cloud_cover_pct=45, temporal_gap_days=3)["score"]
    assert good >= 95 and bad < 30


def test_breakdown_explains_and_weights_renormalise():
    c = compute_confidence(valid_fraction=0.8, cloud_cover_pct=10)
    assert all(f["explanation"] for f in c["breakdown"])
    assert sum(f["normalised_weight"] for f in c["breakdown"]) == pytest.approx(1.0, abs=1e-3)


def test_short_gap_is_penalised():
    near = compute_confidence(valid_fraction=0.9, temporal_gap_days=2)["score"]
    ok = compute_confidence(valid_fraction=0.9, temporal_gap_days=60)["score"]
    assert near < ok
