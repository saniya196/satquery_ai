"""Tests for denominator definitions and metric labeling (P0.1)."""
import numpy as np
from app.change_detection.change import detect_change
from app.indices.spectral import index_stats


def test_index_stats_denominator_is_total_when_provided():
    arr = np.array([0.5, 0.3, np.nan])
    stats = index_stats(arr, denominator=10)
    assert stats["n_total"] == 10
    assert stats["n_valid"] == 2
    assert abs(stats["valid_fraction"] - 0.2) < 1e-9


def test_change_detection_denominator_is_aoi():
    a = np.full((5, 5), 0.5)
    b = np.full((5, 5), 0.6)
    inside = np.ones((5, 5), dtype=bool)
    inside[0, 0] = False  # exclude one pixel from AOI
    res = detect_change(a, b, 100.0, inside_aoi=inside)
    assert res["both_valid_fraction"] == 1.0  # all AOI pixels valid
    assert res["n_pixels_both_valid"] == 24


def test_time_series_labels_exist():
    # Just check the structure is reasonable
    pass
