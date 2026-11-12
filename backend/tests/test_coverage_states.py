"""Focused tests for coverage states (P0.2)."""
from shapely.geometry import box
from app.preprocessing.masking import validate_aoi_geojson


def test_coverage_full_state():
    aoi = validate_aoi_geojson({"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]})
    scene = box(-0.05, -0.05, 1.05, 1.05)
    inter = aoi.intersection(scene)
    cov = inter.area / aoi.area if aoi.area > 0 else 0
    assert cov >= 0.99


def test_coverage_partial_state():
    aoi = validate_aoi_geojson({"type": "Polygon", "coordinates": [[[0,0],[3,0],[3,3],[0,3],[0,0]]]})
    scene = box(0, 0, 1, 1)
    inter = aoi.intersection(scene)
    cov = inter.area / aoi.area if aoi.area > 0 else 0
    assert 0 < cov < 0.99


def test_coverage_unavailable_state():
    aoi = validate_aoi_geojson({"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]})
    scene = box(10, 10, 11, 11)
    assert not aoi.intersects(scene)
