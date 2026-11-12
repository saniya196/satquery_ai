"""Regression tests for scene coverage (P0.5). Uses synthetic geometries only."""
from datetime import date
from unittest.mock import MagicMock, patch

import math
import pytest
from shapely.geometry import box, mapping
from shapely.ops import transform as shp_transform

from app.core.errors import NoImageryError
from app.preprocessing.masking import validate_aoi_geojson
from app.satellite.provider import SatelliteProvider


AOI = {"type": "Polygon", "coordinates": [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]}


def _equirect_area_ratio(geom_wgs, other_wgs):
    """Compute area ratio using equirectangular approximation (matches provider logic)."""
    c = geom_wgs.centroid
    cos_lat = math.cos(math.radians(float(c.y)))
    lon0 = float(c.x)
    lat0 = float(c.y)
    def to_local(x, y, z=None):
        return ((x - lon0) * cos_lat, (y - lat0))
    g = shp_transform(to_local, geom_wgs)
    o = shp_transform(to_local, other_wgs)
    inter = g.intersection(o)
    return float(inter.area / g.area) if g.area > 0 else 0.0


class MockProvider(SatelliteProvider):
    def __init__(self, scenes):
        self._scenes = scenes
    def list_scenes(self, aoi_geojson, start, end, max_cloud):
        return list(self._scenes)
    def get_scene(self, aoi_geojson, item_id, bands):
        raise NotImplementedError()


def test_aoi_completely_inside_scene():
    aoi = validate_aoi_geojson(AOI)
    scene = box(77.4, 12.8, 77.7, 13.1)
    cov = _equirect_area_ratio(aoi, scene)
    assert cov >= 0.999


def test_aoi_exactly_matches_scene():
    aoi = validate_aoi_geojson(AOI)
    scene = box(*aoi.bounds)
    cov = _equirect_area_ratio(aoi, scene)
    assert cov >= 0.999


def test_aoi_partially_intersects_scene():
    aoi = validate_aoi_geojson(AOI)
    # scene covers only western half roughly
    minx, miny, maxx, maxy = aoi.bounds
    scene = box(minx, miny, minx + (maxx-minx)*0.5, maxy)
    cov = _equirect_area_ratio(aoi, scene)
    assert 0.45 < cov < 0.55


def test_aoi_completely_outside_scene():
    aoi = validate_aoi_geojson(AOI)
    scene = box(0, 0, 1, 1)
    assert not aoi.intersects(scene)
    cov = _equirect_area_ratio(aoi, scene)
    assert cov == 0.0


def test_multiple_candidates_different_coverage():
    scenes = [
        {"item_id": "s1", "datetime": "2026-01-01", "cloud_cover": 5, "coverage": 0.5},
        {"item_id": "s2", "datetime": "2026-01-02", "cloud_cover": 10, "coverage": 0.8},
        {"item_id": "s3", "datetime": "2026-01-03", "cloud_cover": 2, "coverage": 0.99},
    ]
    p = MockProvider(scenes)
    best = p.best_scene(AOI, date(2026,1,1), date(2026,1,31), 40)
    assert best["item_id"] == "s3"


def test_fully_covering_preferred_over_lower_coverage():
    scenes = [
        {"item_id": "s1", "datetime": "2026-01-01", "cloud_cover": 1, "coverage": 0.95},
        {"item_id": "s2", "datetime": "2026-01-02", "cloud_cover": 30, "coverage": 1.0},
    ]
    p = MockProvider(scenes)
    best = p.best_scene(AOI, date(2026,1,1), date(2026,1,31), 40)
    assert best["item_id"] == "s2"
    assert best["coverage_status"] == "full"


def test_no_full_coverage_preserves_partial_failure():
    scenes = [
        {"item_id": "s1", "datetime": "2026-01-01", "cloud_cover": 5, "coverage": 0.6},
        {"item_id": "s2", "datetime": "2026-01-02", "cloud_cover": 10, "coverage": 0.7},
    ]
    p = MockProvider(scenes)
    with pytest.raises(NoImageryError) as exc:
        p.best_scene(AOI, date(2026,1,1), date(2026,1,31), 40)
    assert "coverage" in str(exc.value).lower()
    assert "70" in str(exc.value) or "0.7" in str(exc.value) or "partially" in str(exc.value).lower() or "fully covers" in str(exc.value).lower()


def test_numerical_stability_around_threshold():
    # At threshold boundary
    scenes = [{"item_id": "s1", "datetime": "2026-01-01", "cloud_cover": 5, "coverage": 0.99}]
    p = MockProvider(scenes)
    best = p.best_scene(AOI, date(2026,1,1), date(2026,1,31), 40)
    assert best["item_id"] == "s1"
    # Just below
    scenes2 = [{"item_id": "s1", "datetime": "2026-01-01", "cloud_cover": 5, "coverage": 0.989}]
    p2 = MockProvider(scenes2)
    with pytest.raises(NoImageryError):
        p2.best_scene(AOI, date(2026,1,1), date(2026,1,31), 40)


def test_coverage_at_different_latitudes_uses_local_approx():
    # Same degree size AOIs at different latitudes - ratio of a half-covering scene should be ~0.5
    for lat in [0.0, 30.0, 60.0]:
        aoi = box(10.0, lat, 10.2, lat + 0.2)
        scene = box(10.0, lat, 10.1, lat + 0.2)  # half in longitude
        aoi_g = validate_aoi_geojson(mapping(aoi))
        cov = _equirect_area_ratio(aoi_g, scene)
        assert 0.48 < cov < 0.52, f"lat={lat} cov={cov}"


def test_invalid_empty_scene_geometry_handling():
    # list_scenes catches exceptions and sets coverage None; test via best_scene behavior with None coverage
    scenes = [{"item_id": "s1", "datetime": "2026-01-01", "cloud_cover": 5, "coverage": None}]
    p = MockProvider(scenes)
    # When no coverage info, falls back to old behavior (picks lowest cloud)
    best = p.best_scene(AOI, date(2026,1,1), date(2026,1,31), 40)
    assert best["item_id"] == "s1"
    assert best.get("coverage_status") == "unknown"
