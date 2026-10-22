import numpy as np
import pytest
from app.statistics.trend import analyse_series, mann_kendall, robust_anomalies, sens_slope


def test_mann_kendall_known_s():
    assert mann_kendall([1, 2, 3, 4, 5])["s"] == 10


def test_significant_increasing_and_decreasing():
    up = mann_kendall(list(np.linspace(0.2, 0.8, 12)))
    down = mann_kendall(list(np.linspace(0.8, 0.2, 12)))
    assert up["significant"] and up["trend"] == "increasing"
    assert down["significant"] and down["trend"] == "decreasing"


def test_noise_is_not_a_trend():
    rng = np.random.default_rng(0)
    r = mann_kendall(list(0.5 + rng.normal(0, 0.05, 20)))
    assert not r["significant"] and r["trend"] == "no trend"


def test_sens_slope_per_year():
    days = np.arange(0, 300, 30)
    assert sens_slope(days, 0.001 * days) == pytest.approx(0.001 * 365.25)


def test_too_few_dates_gives_no_trend_claim():
    out = analyse_series(list(range(0, 70, 10)), [0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2])
    assert out["n"] == 7 and not out["trend_claim_allowed"] and out["trend_test"] is None


def test_enough_dates_allows_trend_claim():
    out = analyse_series(list(range(0, 100, 10)), list(np.linspace(0.8, 0.2, 10)))
    assert out["trend_claim_allowed"] and out["trend_test"]["trend"] == "decreasing"


def test_anomaly_detection():
    assert robust_anomalies([0.5, 0.51, 0.49, 0.5, 0.5, 0.05, 0.5, 0.52]) == [5]
