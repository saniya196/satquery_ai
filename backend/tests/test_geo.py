import pytest
from affine import Affine
from app.rendering.geo import bounds_wgs84, parse_utm_epsg, utm_to_lonlat

# Reference values computed independently with pyproj (EPSG:32644 / 32744 / 32630 -> EPSG:4326).
CASES = [
    # easting, northing, zone, north, expected lon, expected lat
    (500000, 1900000, 44, True, 81.0, 17.18481157493771),
    (399000.0, 1920000.0, 44, True, 80.04932261123054, 17.363337140007484),
    (300000.0, 6000000.0, 30, True, -6.059593683355516, 54.10920644763894),
    (650000.0, 8000000.0, 44, False, 82.41748190150173, -18.08350246621487),
]


@pytest.mark.parametrize("e,n,zone,north,lon,lat", CASES)
def test_utm_matches_pyproj_reference(e, n, zone, north, lon, lat):
    got_lon, got_lat = utm_to_lonlat(e, n, zone, north)
    assert got_lon == pytest.approx(lon, abs=1e-7)   # ~1 cm
    assert got_lat == pytest.approx(lat, abs=1e-7)


def test_parse_epsg():
    assert parse_utm_epsg("EPSG:32644") == (44, True)
    assert parse_utm_epsg("epsg:32744") == (44, False)
    with pytest.raises(ValueError):
        parse_utm_epsg("EPSG:4326")


def test_bounds_order_and_plausible_size():
    tf = Affine(10, 0, 500000, 0, -10, 1900000)   # 60x60 px of 10 m
    (s, w), (n, e) = bounds_wgs84(tf, (60, 60), "EPSG:32644")
    assert s < n and w < e
    assert (n - s) * 111_000 == pytest.approx(600, rel=0.02)   # ~600 m tall
