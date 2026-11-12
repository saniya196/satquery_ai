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


def test_hotspot_enriched_stats_and_compatibility():
    a, b = _pair()
    r = detect_change(a, b, 100.0)
    h = r["hotspots"][0]
    # Existing compatibility
    assert h["pixels"] == 1800
    assert h["mean_diff"] == pytest.approx(-0.3)
    assert h["area_km2"] == pytest.approx(0.18)
    assert "bbox_rowcol" in h and "centroid_rowcol" in h
    # Enriched stats from finite diff values in hotspot
    assert h["median_diff"] == pytest.approx(-0.3)
    assert h["std_diff"] == pytest.approx(0.0)
    assert h["min_diff"] == pytest.approx(-0.3)
    assert h["max_diff"] == pytest.approx(-0.3)
    assert h["valid_pixel_count"] == 1800
    assert h["class"] == "significant_decrease"
    assert h["class_code"] == -2
    assert h["direction"] == "decrease"


def test_hotspot_single_pixel():
    from app.change_detection.change import find_hotspots, classify_change

    diff = np.array([[ -0.3, 0.0], [0.0, 0.0]])
    cmap = classify_change(diff)
    spots = find_hotspots(cmap, diff, 100.0, min_pixels=1)
    assert len(spots) == 1
    h = spots[0]
    assert h["pixels"] == 1
    assert h["valid_pixel_count"] == 1
    assert h["mean_diff"] == pytest.approx(-0.3)
    assert h["median_diff"] == pytest.approx(-0.3)
    assert h["min_diff"] == pytest.approx(-0.3)
    assert h["max_diff"] == pytest.approx(-0.3)


def test_hotspot_nan_handling_in_diff():
    # NaNs in the overall grid are excluded by both-valid mask; hotspot stats use finite values.
    a = np.full((10, 10), 0.8)
    b = np.full((10, 10), 0.4)
    a[0, 0] = np.nan  # not valid on both
    r = detect_change(a, b, 100.0)
    assert len(r["hotspots"]) == 1
    h = r["hotspots"][0]
    assert h["valid_pixel_count"] == 99
    assert h["pixels"] == 99
    assert h["mean_diff"] == pytest.approx(-0.4)
    assert h["median_diff"] == pytest.approx(-0.4)


def test_hotspot_top_n_ordering_by_area():
    a = np.full((30, 30), 0.8)
    b = a.copy()
    b[0:10, 0:5] = 0.4   # 50 px
    b[15:25, 15:30] = 0.4  # 150 px (separate component)
    r = detect_change(a, b, 100.0)
    assert len(r["hotspots"]) == 2
    assert r["hotspots"][0]["pixels"] == 150
    assert r["hotspots"][1]["pixels"] == 50
    assert r["hotspots"][0]["area_km2"] >= r["hotspots"][1]["area_km2"]


def test_no_hotspots_when_no_significant_decrease():
    a = np.full((10, 10), 0.5)
    b = np.full((10, 10), 0.55)  # moderate/stable depending on thresholds, no significant decrease
    r = detect_change(a, b, 100.0)
    assert r["hotspots"] == []


def test_hotspot_bbox_lonlat_utm_and_unsupported_crs():
    from affine import Affine
    from app.change_detection.change import find_hotspots

    diff = np.zeros((10, 10))
    cmap = np.zeros((10, 10), dtype=np.int16)
    cmap[2:5, 3:7] = -2
    diff[cmap == -2] = -0.3
    tf = Affine(10, 0, 500000, 0, -10, 4000000)
    spots = find_hotspots(cmap, diff, 100.0, min_pixels=1, transform=tf, crs="EPSG:32644")
    assert len(spots) == 1
    assert "bbox_lonlat" in spots[0] and len(spots[0]["bbox_lonlat"]) == 4
    mnlon, mnlat, mxlon, mxlat = spots[0]["bbox_lonlat"]
    assert mnlon <= mxlon and mnlat <= mxlat
    assert "centroid_lonlat" in spots[0]

    # Unsupported/non-UTM CRS: should not raise, geo fields omitted
    spots2 = find_hotspots(cmap, diff, 100.0, min_pixels=1, transform=tf, crs="EPSG:4326")
    assert len(spots2) == 1
    assert "centroid_lonlat" not in spots2[0]
    assert "bbox_lonlat" not in spots2[0]
