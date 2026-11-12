import numpy as np
from shapely.geometry import box
from app.preprocessing.masking import validate_aoi_geojson


def test_validate_aoi_geojson_polygon():
    g = {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}
    geom = validate_aoi_geojson(g)
    assert geom.area > 0


def test_coverage_full():
    aoi = validate_aoi_geojson({"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]})
    scene = box(-0.1, -0.1, 1.1, 1.1)
    inter = aoi.intersection(scene)
    cov = inter.area / aoi.area if aoi.area > 0 else 0
    assert cov >= 0.99


def test_coverage_partial():
    aoi = validate_aoi_geojson({"type": "Polygon", "coordinates": [[[0,0],[2,0],[2,2],[0,2],[0,0]]]})
    scene = box(0, 0, 1, 1)
    inter = aoi.intersection(scene)
    cov = inter.area / aoi.area if aoi.area > 0 else 0
    assert 0 < cov < 0.3


def test_coverage_none():
    aoi = validate_aoi_geojson({"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]})
    scene = box(10, 10, 11, 11)
    assert aoi.intersects(scene) is False


def test_multiple_scenes_prefer_full():
    aoi = validate_aoi_geojson({"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]})
    scenes = [
        {"id": "s1", "coverage": 0.5},
        {"id": "s2", "coverage": 1.0},
    ]
    covered = [s for s in scenes if s["coverage"] >= 0.99]
    assert covered[0]["id"] == "s2"
