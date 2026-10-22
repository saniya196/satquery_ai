import numpy as np
import pytest
from app.change_detection.change import classify_change, detect_change
from app.core.errors import InsufficientValidPixelsError


def _pair():
    a = np.full((60, 60), 0.8)
    b = a.copy()
    b[:, :30] = 0.5
    return a, b


def test_known_change_statistics():
    a, b = _pair()
    r = detect_change(a, b, 100.0)
    assert r["mean_change"] == pytest.approx(-0.15)
    assert r["percent_change_of_mean"] == pytest.approx(-18.75)
    c = r["classes"]
    assert c["significant_decrease"]["fraction_of_valid"] == pytest.approx(0.5)
    assert c["stable"]["fraction_of_valid"] == pytest.approx(0.5)
    assert c["significant_decrease"]["area_km2"] == pytest.approx(0.18)
    assert len(r["hotspots"]) == 1 and r["hotspots"][0]["pixels"] == 1800


def test_no_change_is_all_stable():
    a = np.full((20, 20), 0.6)
    r = detect_change(a, a.copy(), 100.0)
    assert r["classes"]["stable"]["fraction_of_valid"] == 1.0 and r["hotspots"] == []


def test_thresholds_are_configurable_and_reported():
    d = np.array([[-0.10]])
    assert classify_change(d)[0, 0] == -1
    assert classify_change(d, {"significant_decrease": -0.08})[0, 0] == -2
    a, b = _pair()
    assert detect_change(a, b, 100.0, {"significant_decrease": -0.5})["thresholds"]["significant_decrease"] == -0.5


def test_insufficient_valid_pixels_refused():
    a, b = _pair()
    b[:50, :] = np.nan
    with pytest.raises(InsufficientValidPixelsError):
        detect_change(a, b, 100.0)


def test_only_pixels_valid_on_both_dates_are_used():
    a, b = _pair()
    a[:6, :] = np.nan
    r = detect_change(a, b, 100.0)
    assert r["n_pixels_both_valid"] == 54 * 60


def test_hotspot_centroid_is_geographic_when_grid_metadata_is_available():
    from affine import Affine

    a, b = _pair()
    result = detect_change(a, b, 100.0, transform=Affine(10, 0, 500000, 0, -10, 4000000), crs="EPSG:32644")
    hotspot = result["hotspots"][0]
    assert len(hotspot["centroid_lonlat"]) == 2
    assert -180 <= hotspot["centroid_lonlat"][0] <= 180
    assert -90 <= hotspot["centroid_lonlat"][1] <= 90
