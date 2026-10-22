import numpy as np
import pytest
from datetime import date
from app.core.errors import InsufficientValidPixelsError, NoImageryError
from app.schemas.query import DateRange
from app.services import analysis
from app.validation.grounding import check_grounding
from tests.fakes import AOI, FakeProvider, make_scene


def test_change_end_to_end():
    p = FakeProvider([make_scene("A", "2026-06-15T05:00:00+00:00", 0.8, 0.8),
                      make_scene("B", "2026-09-10T05:00:00+00:00", 0.5, 0.8, cloud=8.0)])
    r = analysis.run_change(p, AOI, DateRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
                            DateRange(start=date(2026, 9, 1), end=date(2026, 9, 30)))
    ev, f = r["evidence"], r["facts"]
    assert ev["index"] == "NDVI" and ev["bands"] == "B08 / B04" and len(ev["scenes"]) == 2
    assert f["change"]["mean_change"] == pytest.approx(-0.15, abs=1e-6)
    assert f["change"]["percent_change_of_mean"] == pytest.approx(-18.75, abs=1e-4)
    assert ev["aoi_area_km2"] == pytest.approx(0.36) and ev["valid_pixel_fraction"] == pytest.approx(1.0)
    assert len(r["hotspots"]) == 1 and r["confidence"]["score"] > 80
    assert r["answer"]["source"] == "template" and check_grounding(r["answer"]["text"], f)["valid"]


def test_cloud_reduces_valid_fraction_and_score():
    p = FakeProvider([make_scene("A", "2026-06-15T05:00:00+00:00"),
                      make_scene("B", "2026-09-10T05:00:00+00:00", cloudy_fraction=0.3, cloud=30.0)])
    r = analysis.run_change(p, AOI, DateRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
                            DateRange(start=date(2026, 9, 1), end=date(2026, 9, 30)))
    assert r["evidence"]["valid_pixel_fraction"] == pytest.approx(0.7)


def test_too_cloudy_is_refused_not_fabricated():
    p = FakeProvider([make_scene("A", "2026-06-15T05:00:00+00:00", cloudy_fraction=0.9, cloud=35.0)])
    with pytest.raises(InsufficientValidPixelsError):
        analysis.run_index_stats(p, AOI, DateRange(start=date(2026, 6, 1), end=date(2026, 6, 30)))


def test_no_imagery_raises():
    with pytest.raises(NoImageryError):
        analysis.run_index_stats(FakeProvider([]), AOI, DateRange(start=date(2026, 6, 1), end=date(2026, 6, 30)))


def test_index_stats_values():
    p = FakeProvider([make_scene("A", "2026-06-15T05:00:00+00:00", 0.6, 0.6)])
    r = analysis.run_index_stats(p, AOI, DateRange(start=date(2026, 6, 1), end=date(2026, 6, 30)))
    assert r["facts"]["stats"]["mean"] == pytest.approx(0.6) and r["facts"]["stats"]["coverage_fraction"] == 1.0


def _series(n, start=0.8, end=0.3):
    vals = np.linspace(start, end, n)
    return [make_scene(f"S{i}", f"2026-{1 + i:02d}-10T05:00:00+00:00", v, v) for i, v in enumerate(vals)]


def test_time_series_significant_decrease():
    r = analysis.run_time_series(FakeProvider(_series(10)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    assert s["n"] == 10 and s["trend_test"]["trend"] == "decreasing" and s["sens_slope_per_year"] < 0
    assert "decreasing" in r["answer"]["text"]


def test_time_series_few_dates_makes_no_trend_claim():
    r = analysis.run_time_series(FakeProvider(_series(5)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    assert r["facts"]["series"]["trend_test"] is None and "too few dates" in r["answer"]["text"]
