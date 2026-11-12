"""Tests for minimum usable observations in time series (P0.3, P1.2a)."""
from datetime import date

import numpy as np

from app.core.errors import InsufficientValidPixelsError
from app.schemas.query import DateRange
from app.services import analysis
from tests.fakes import AOI, FakeProvider, make_scene


def _series_all_valid(n, start=0.8, end=0.3):
    vals = np.linspace(start, end, n)
    return [make_scene(f"S{i}", f"2026-{1 + i:02d}-10T05:00:00+00:00", v, v) for i, v in enumerate(vals)]


def test_time_series_zero_usable_raises():
    # No scenes or all filtered - should raise
    try:
        r = analysis.run_time_series(FakeProvider([]), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
        assert False, "should have raised"
    except Exception:
        pass


def test_time_series_one_usable_no_trend():
    r = analysis.run_time_series(FakeProvider(_series_all_valid(1)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    assert s["trend_test"] is None
    assert s.get("n_dates_included") == 1 or s.get("n_dates_usable") == 1
    assert s.get("insufficient_observations") is True or s.get("trend_claim_allowed") is False


def test_time_series_seven_usable_no_trend():
    r = analysis.run_time_series(FakeProvider(_series_all_valid(7)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    assert s["trend_test"] is None
    assert s.get("n_dates_included") == 7
    assert s.get("insufficient_observations") is True or s.get("trend_claim_allowed") is False


def test_time_series_eight_usable_has_trend_capability():
    r = analysis.run_time_series(FakeProvider(_series_all_valid(8)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    # With >=8 observations, trend can be calculated (may or may not be significant)
    assert s.get("n_dates_included") == 8
    assert s.get("trend_claim_allowed") is True


def test_time_series_more_than_eight_usable():
    r = analysis.run_time_series(FakeProvider(_series_all_valid(10)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    assert s.get("n_dates_included") == 10
    assert s.get("trend_claim_allowed") is True


def test_time_series_skipped_low_valid_counted():
    # 10 requested scenes: 2 have < min_valid_fraction (0.30) due to cloudy/invalid SCL pixels.
    scenes = _series_all_valid(10)
    # cloudy_fraction=0.8 -> 48/60 rows invalid (SCL=9) => 20% valid < 30%
    scenes[2] = make_scene("S2", "2026-03-10T05:00:00+00:00", 0.65, 0.65, cloudy_fraction=0.8)
    scenes[6] = make_scene("S6", "2026-07-10T05:00:00+00:00", 0.45, 0.45, cloudy_fraction=0.8)
    r = analysis.run_time_series(FakeProvider(scenes), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    assert s["n_dates_requested"] == 10
    assert s["n_dates_skipped_low_valid"] == 2
    assert s["n_dates_included"] == 8
    assert "2026-03-10" not in s["dates"]
    assert "2026-07-10" not in s["dates"]
    assert len(s["dates"]) == 8
    assert len(s["values"]) == 8
    # Skipped scene values (NDVI ~0.65, ~0.45 in our synthetic setup) must not appear
    assert not any(abs(float(v) - 0.65) < 1e-6 for v in s["values"])
    assert not any(abs(float(v) - 0.45) < 1e-6 for v in s["values"])


def test_time_series_scene_load_failure_excluded_not_counted_as_low_valid():
    class FailOneProvider(FakeProvider):
        def get_scene(self, aoi_geojson, item_id, bands):
            if item_id == "S3":
                raise RuntimeError("synthetic load failure")
            return super().get_scene(aoi_geojson, item_id, bands)

    scenes = _series_all_valid(9)  # S0..S8
    r = analysis.run_time_series(FailOneProvider(scenes), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    assert s["n_dates_requested"] == 9
    assert s["n_dates_skipped_low_valid"] == 0  # load failure is NOT a low-valid skip
    assert s["n_dates_skipped_load_error"] == 1
    assert s["n_dates_included"] == 8
    assert "2026-04-10" not in s["dates"]  # S3
    assert len(s["dates"]) == 8
    assert len(s["values"]) == 8


def test_time_series_min_eight_rule_with_skipped_scenes():
    # 10 requested, 3 skipped (2 low-valid + 1 load failure) => 7 usable: no trend claim
    class FailOneProvider(FakeProvider):
        def get_scene(self, aoi_geojson, item_id, bands):
            if item_id == "S4":
                raise RuntimeError("synthetic load failure")
            return super().get_scene(aoi_geojson, item_id, bands)

    scenes = _series_all_valid(10)
    scenes[1] = make_scene("S1", "2026-02-10T05:00:00+00:00", 0.7, 0.7, cloudy_fraction=0.8)
    scenes[7] = make_scene("S7", "2026-08-10T05:00:00+00:00", 0.5, 0.5, cloudy_fraction=0.8)
    r = analysis.run_time_series(FailOneProvider(scenes), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    assert s["n_dates_requested"] == 10
    assert s["n_dates_skipped_low_valid"] == 2
    assert s["n_dates_skipped_load_error"] == 1
    assert s["n_dates_included"] == 7
    assert s["trend_claim_allowed"] is False
    assert s.get("insufficient_observations") is True
    assert s["trend_test"] is None
    assert "2026-02-10" not in s["dates"]
    assert "2026-05-10" not in s["dates"]  # S4 load failure
    assert "2026-08-10" not in s["dates"]

    # 11 requested, 2 skipped (1 low-valid + 1 load failure) => 9 usable: trend claim allowed
    class FailOneB(FakeProvider):
        def get_scene(self, aoi_geojson, item_id, bands):
            if item_id == "S5":
                raise RuntimeError("synthetic load failure")
            return super().get_scene(aoi_geojson, item_id, bands)

    scenes2 = _series_all_valid(11)
    scenes2[3] = make_scene("S3", "2026-04-10T05:00:00+00:00", 0.6, 0.6, cloudy_fraction=0.8)
    r2 = analysis.run_time_series(FailOneB(scenes2), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s2 = r2["facts"]["series"]
    assert s2["n_dates_requested"] == 11
    assert s2["n_dates_skipped_low_valid"] == 1
    assert s2["n_dates_skipped_load_error"] == 1
    assert s2["n_dates_included"] == 9
    assert s2["trend_claim_allowed"] is True
    assert "2026-04-10" not in s2["dates"]
    assert "2026-06-10" not in s2["dates"]


def test_time_series_load_error_counts_zero_one_multiple():
    # 0 load errors
    r0 = analysis.run_time_series(FakeProvider(_series_all_valid(8)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    assert r0["facts"]["series"]["n_dates_skipped_load_error"] == 0
    assert r0["facts"]["series"]["n_dates_skipped_low_valid"] == 0

    # 1 load error
    class FailOne(FakeProvider):
        def get_scene(self, aoi_geojson, item_id, bands):
            if item_id == "S2":
                raise RuntimeError("synthetic load failure")
            return super().get_scene(aoi_geojson, item_id, bands)
    r1 = analysis.run_time_series(FailOne(_series_all_valid(9)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s1 = r1["facts"]["series"]
    assert s1["n_dates_requested"] == 9
    assert s1["n_dates_skipped_load_error"] == 1
    assert s1["n_dates_skipped_low_valid"] == 0
    assert s1["n_dates_included"] == 8
    assert "2026-03-10" not in s1["dates"]

    # multiple load errors
    class FailMany(FakeProvider):
        def get_scene(self, aoi_geojson, item_id, bands):
            if item_id in {"S1", "S4", "S6"}:
                raise RuntimeError("synthetic load failure")
            return super().get_scene(aoi_geojson, item_id, bands)
    r2 = analysis.run_time_series(FailMany(_series_all_valid(10)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s2 = r2["facts"]["series"]
    assert s2["n_dates_requested"] == 10
    assert s2["n_dates_skipped_load_error"] == 3
    assert s2["n_dates_skipped_low_valid"] == 0
    assert s2["n_dates_included"] == 7
    for d in ("2026-02-10", "2026-05-10", "2026-07-10"):
        assert d not in s2["dates"]


def test_time_series_skip_counts_separate_with_fewer_than_eight_usable():
    class FailSome(FakeProvider):
        def get_scene(self, aoi_geojson, item_id, bands):
            if item_id in {"S0", "S9"}:
                raise RuntimeError("synthetic load failure")
            return super().get_scene(aoi_geojson, item_id, bands)
    scenes = _series_all_valid(10)
    scenes[3] = make_scene("S3", "2026-04-10T05:00:00+00:00", 0.6, 0.6, cloudy_fraction=0.8)
    scenes[5] = make_scene("S5", "2026-06-10T05:00:00+00:00", 0.55, 0.55, cloudy_fraction=0.8)
    scenes[8] = make_scene("S8", "2026-09-10T05:00:00+00:00", 0.5, 0.5, cloudy_fraction=0.8)
    r = analysis.run_time_series(FailSome(scenes), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    assert s["n_dates_requested"] == 10
    assert s["n_dates_skipped_load_error"] == 2
    assert s["n_dates_skipped_low_valid"] == 3
    assert s["n_dates_included"] == 5
    assert s["trend_claim_allowed"] is False
    assert s.get("insufficient_observations") is True
    assert s["trend_test"] is None
    assert len(s["dates"]) == 5 and len(s["values"]) == 5


class ReverseOrderProvider(FakeProvider):
    def list_scenes(self, aoi_geojson, start, end, max_cloud):
        return sorted(super().list_scenes(aoi_geojson, start, end, max_cloud), key=lambda x: x["datetime"], reverse=True)


class FixedOrderProvider(FakeProvider):
    def __init__(self, scenes, order_ids):
        super().__init__(scenes)
        self._order_ids = list(order_ids)

    def list_scenes(self, aoi_geojson, start, end, max_cloud):
        out = []
        for item_id in self._order_ids:
            s = self.scenes[item_id]
            d = date.fromisoformat(s["datetime"][:10])
            if start <= d <= end and s["cloud"] <= max_cloud:
                out.append({"item_id": s["item_id"], "datetime": s["datetime"], "cloud_cover": s["cloud"]})
        return out


def test_time_series_sorts_reverse_chronological_provider_order():
    scenes = [
        make_scene("A", "2026-01-10T05:00:00+00:00", 0.80, 0.80, cloud=10),
        make_scene("B", "2026-02-10T05:00:00+00:00", 0.70, 0.70, cloud=12),
        make_scene("C", "2026-03-10T05:00:00+00:00", 0.60, 0.60, cloud=14),
        make_scene("D", "2026-04-10T05:00:00+00:00", 0.50, 0.50, cloud=16),
        make_scene("E", "2026-05-10T05:00:00+00:00", 0.40, 0.40, cloud=18),
        make_scene("F", "2026-06-10T05:00:00+00:00", 0.35, 0.35, cloud=20),
        make_scene("G", "2026-07-10T05:00:00+00:00", 0.30, 0.30, cloud=22),
        make_scene("H", "2026-08-10T05:00:00+00:00", 0.25, 0.25, cloud=24),
    ]
    r = analysis.run_time_series(ReverseOrderProvider(scenes), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    s = r["facts"]["series"]
    ev = r["evidence"]["scenes"]
    assert s["dates"] == ["2026-01-10", "2026-02-10", "2026-03-10", "2026-04-10", "2026-05-10", "2026-06-10", "2026-07-10", "2026-08-10"]
    assert [e["item_id"] for e in ev] == ["A", "B", "C", "D", "E", "F", "G", "H"]
    assert s["values"][0] > s["values"][-1]
    assert s["n_dates_included"] == 8


def test_time_series_mixed_order_keeps_parallel_metadata_aligned():
    scenes = [
        make_scene("JAN", "2026-01-10T05:00:00+00:00", 0.80, 0.80, cloud=11),
        make_scene("FEB", "2026-02-10T05:00:00+00:00", 0.70, 0.70, cloud=22),
        make_scene("MAR", "2026-03-10T05:00:00+00:00", 0.60, 0.60, cloud=33),
        make_scene("APR", "2026-04-10T05:00:00+00:00", 0.50, 0.50, cloud=44),
        make_scene("MAY", "2026-05-10T05:00:00+00:00", 0.45, 0.45, cloud=55),
        make_scene("JUN", "2026-06-10T05:00:00+00:00", 0.40, 0.40, cloud=66),
        make_scene("JUL", "2026-07-10T05:00:00+00:00", 0.35, 0.35, cloud=77),
        make_scene("AUG", "2026-08-10T05:00:00+00:00", 0.30, 0.30, cloud=88),
    ]
    mixed = ["MAR", "JAN", "AUG", "FEB", "JUL", "APR", "JUN", "MAY"]
    r = analysis.run_time_series(FixedOrderProvider(scenes, mixed), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)), max_cloud=100)
    s = r["facts"]["series"]
    ev = r["evidence"]["scenes"]
    expected_dates = ["2026-01-10", "2026-02-10", "2026-03-10", "2026-04-10", "2026-05-10", "2026-06-10", "2026-07-10", "2026-08-10"]
    expected_ids = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG"]
    expected_clouds = [11.0, 22.0, 33.0, 44.0, 55.0, 66.0, 77.0, 88.0]
    assert s["dates"] == expected_dates
    assert [e["item_id"] for e in ev] == expected_ids
    assert [float(e["cloud_cover"]) for e in ev] == expected_clouds
    assert len(s["valid_fractions_per_included_date"]) == 8
    # Values descend with the scene NDVI targets in chronological order
    assert all(s["values"][i] > s["values"][i + 1] for i in range(len(s["values"]) - 1))


def test_time_series_identical_timestamps_retained_stable_order():
    scenes = [
        make_scene("T1A", "2026-01-10T05:00:00+00:00", 0.80, 0.80),
        make_scene("T1B", "2026-01-10T05:00:00+00:00", 0.79, 0.79),
        make_scene("T2", "2026-02-10T05:00:00+00:00", 0.70, 0.70),
        make_scene("T3", "2026-03-10T05:00:00+00:00", 0.60, 0.60),
        make_scene("T4", "2026-04-10T05:00:00+00:00", 0.50, 0.50),
        make_scene("T5", "2026-05-10T05:00:00+00:00", 0.45, 0.45),
        make_scene("T6", "2026-06-10T05:00:00+00:00", 0.40, 0.40),
        make_scene("T7", "2026-07-10T05:00:00+00:00", 0.35, 0.35),
        make_scene("T8", "2026-08-10T05:00:00+00:00", 0.30, 0.30),
    ]
    # mixed order but T1B appears before T1A in provider list; stable sort must keep T1B before T1A
    order = ["T8", "T1B", "T3", "T1A", "T7", "T2", "T6", "T4", "T5"]
    r = analysis.run_time_series(FixedOrderProvider(scenes, order), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    ev = r["evidence"]["scenes"]
    s = r["facts"]["series"]
    assert s["n_dates_included"] == 9
    assert [e["item_id"] for e in ev[:2]] == ["T1B", "T1A"]
    assert s["dates"][0] == "2026-01-10" and s["dates"][1] == "2026-01-10"
    # retained duplicates: two values present for same calendar date
    assert abs(s["values"][0] - 0.79) < 1e-6
    assert abs(s["values"][1] - 0.80) < 1e-6


def test_time_series_same_calendar_date_different_timestamps_retained():
    scenes = [
        make_scene("D1M", "2026-03-10T05:00:00+00:00", 0.70, 0.70),
        make_scene("D1A", "2026-03-10T10:30:00+00:00", 0.69, 0.69),
        make_scene("D2", "2026-04-10T05:00:00+00:00", 0.60, 0.60),
        make_scene("D3", "2026-05-10T05:00:00+00:00", 0.55, 0.55),
        make_scene("D4", "2026-06-10T05:00:00+00:00", 0.50, 0.50),
        make_scene("D5", "2026-07-10T05:00:00+00:00", 0.45, 0.45),
        make_scene("D6", "2026-08-10T05:00:00+00:00", 0.40, 0.40),
        make_scene("D7", "2026-09-10T05:00:00+00:00", 0.35, 0.35),
        make_scene("D8", "2026-10-10T05:00:00+00:00", 0.30, 0.30),
    ]
    order = ["D8", "D1A", "D5", "D1M", "D7", "D3", "D6", "D2", "D4"]
    r = analysis.run_time_series(FixedOrderProvider(scenes, order), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    ev = r["evidence"]["scenes"]
    s = r["facts"]["series"]
    assert s["n_dates_included"] == 9
    assert [e["item_id"] for e in ev[:2]] == ["D1M", "D1A"]
    assert s["dates"][:2] == ["2026-03-10", "2026-03-10"]
    assert ev[0]["datetime"].startswith("2026-03-10T05:00:00")
    assert ev[1]["datetime"].startswith("2026-03-10T10:30:00")


def test_time_series_already_chronological_unique_results_unchanged():
    scenes = _series_all_valid(10)
    r_sorted = analysis.run_time_series(FakeProvider(scenes), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    r_mixed_but_defensively_sorted = analysis.run_time_series(
        FixedOrderProvider(scenes, [f"S{i}" for i in range(10)]), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31))
    )
    s1 = r_sorted["facts"]["series"]
    s2 = r_mixed_but_defensively_sorted["facts"]["series"]
    assert s1["dates"] == s2["dates"]
    assert len(s1["values"]) == len(s2["values"])
    for a, b in zip(s1["values"], s2["values"]):
        assert abs(float(a) - float(b)) < 1e-9
    assert s1["trend_claim_allowed"] == s2["trend_claim_allowed"] is True
    assert s1["n_dates_included"] == s2["n_dates_included"] == 10
    # trend outputs unchanged for unique ordered observations
    assert s1["trend_test"]["trend"] == s2["trend_test"]["trend"]
    assert s1["trend_test"]["significant"] == s2["trend_test"]["significant"]
    assert abs(float(s1["sens_slope_per_year"]) - float(s2["sens_slope_per_year"])) < 1e-12


def test_time_series_min_eight_rule_unchanged_with_defensive_sort():
    scenes = _series_all_valid(8)
    r = analysis.run_time_series(ReverseOrderProvider(scenes), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    assert r["facts"]["series"]["n_dates_included"] == 8
    assert r["facts"]["series"]["trend_claim_allowed"] is True
    scenes7 = _series_all_valid(7)
    r7 = analysis.run_time_series(ReverseOrderProvider(scenes7), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    assert r7["facts"]["series"]["n_dates_included"] == 7
    assert r7["facts"]["series"]["trend_claim_allowed"] is False
    assert r7["facts"]["series"].get("insufficient_observations") is True


def test_time_series_preprocessing_evidence_describes_both_skip_reasons():
    r = analysis.run_time_series(FakeProvider(_series_all_valid(8)), AOI, DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    prep = r["evidence"]["preprocessing"]
    joined = " | ".join(str(p).lower() for p in prep)
    assert any("median" in str(p).lower() for p in prep)
    assert "valid pixel" in joined or "low valid" in joined
    assert "load" in joined and ("fail" in joined or "error" in joined)
    assert "separately" in joined or "counted" in joined
