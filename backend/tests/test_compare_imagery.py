from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import app, get_provider
from app.core.errors import InsufficientDataError, NoImageryError
from app.schemas.query import DateRange, Operation
from app.services.compare import run_compare_operation, select_scene_pairs
from tests.fakes import AOI, FakeProvider, make_scene


AOI_B = {"type": "Polygon", "coordinates": [[[78.02, 17.0], [78.03, 17.0], [78.03, 17.01], [78.02, 17.01], [78.02, 17.0]]]}


def candidate(item_id, acquired="2026-06-15T05:00:00+00:00", cloud=5, coverage=1.0,
              collection="sentinel-2-l2a", processing="L2A"):
    return {"item_id": item_id, "datetime": acquired, "cloud_cover": cloud,
            "coverage": coverage, "collection": collection, "processing_level": processing,
            "provider": "mock catalog", "platform": "Sentinel-2A"}


class CatalogProvider:
    def __init__(self, a_items, b_items):
        self.a_items = a_items
        self.b_items = b_items
        self.calls = []

    def list_scenes(self, aoi, start, end, max_cloud):
        self.calls.append((aoi, max_cloud))
        return self.a_items if aoi == AOI else self.b_items


@pytest.mark.parametrize("a_item,b_item", [
    (candidate("SAME"), candidate("SAME")),
    (candidate("A_TILE"), candidate("B_TILE")),
])
def test_scene_pair_accepts_same_utc_date_and_catalog_compatibility(a_item, b_item):
    pairs = select_scene_pairs(CatalogProvider([a_item], [b_item]), AOI, AOI_B,
                               date(2026, 6, 1), date(2026, 6, 30), 10)
    assert len(pairs) == 1
    assert pairs[0][0]["_utc_date"] == pairs[0][1]["_utc_date"] == date(2026, 6, 15)
    assert pairs[0][0]["item_id"] == a_item["item_id"]
    assert pairs[0][1]["item_id"] == b_item["item_id"]


@pytest.mark.parametrize("a_item,b_item", [
    (candidate("A", "2026-06-15T23:30:00-02:00"), candidate("B", "2026-06-15T01:30:00+00:00")),
    (candidate("A", collection="sentinel-2-l2a"), candidate("B", collection="sentinel-2-l1c")),
    (candidate("A", processing="L2A"), candidate("B", processing="L1C")),
    (candidate("A", coverage=None), candidate("B")),
    (candidate("A", coverage=0.989), candidate("B")),
    (candidate("A", cloud=20), candidate("B", cloud=5)),
])
def test_incompatible_scene_pair_is_rejected(a_item, b_item):
    with pytest.raises(NoImageryError, match="No comparable Sentinel-2 observations"):
        select_scene_pairs(CatalogProvider([a_item], [b_item]), AOI, AOI_B,
                           date(2026, 6, 1), date(2026, 6, 30), 10)


def test_cloud_threshold_is_passed_to_both_aoi_discoveries():
    provider = CatalogProvider([candidate("A")], [candidate("B")])
    select_scene_pairs(provider, AOI, AOI_B, date(2026, 6, 1), date(2026, 6, 30), 7)
    assert [call[1] for call in provider.calls] == [7, 7]


def test_no_compatible_pair_does_not_call_best_scene():
    class NoFallbackProvider(CatalogProvider):
        def best_scene(self, *_args, **_kwargs):
            raise AssertionError("Compare must never fall back to independently selected scenes")

    with pytest.raises(NoImageryError, match="Try a wider date range"):
        select_scene_pairs(NoFallbackProvider([candidate("A")], []), AOI, AOI_B,
                           date(2026, 6, 1), date(2026, 6, 30), 10)


class CompareSceneProvider(FakeProvider):
    def __init__(self, scenes, listed_a=None, listed_b=None):
        super().__init__(scenes)
        self.listed_a = listed_a
        self.listed_b = listed_b
        self.discovery_calls = []

    def list_scenes(self, aoi, start, end, max_cloud):
        self.discovery_calls.append((aoi, max_cloud))
        items = self.listed_a if aoi == AOI and self.listed_a is not None else self.listed_b
        if items is None:
            return super().list_scenes(aoi, start, end, max_cloud)
        return [item for item in items
                if start <= datetime.fromisoformat(item["datetime"].replace("Z", "+00:00")).astimezone(timezone.utc).date() <= end
                and item["cloud_cover"] <= max_cloud]


def test_change_detection_pairs_before_and_after_dates_across_aois():
    specs = [
        ("A_BEFORE", "2026-06-15T05:00:00+00:00", .8),
        ("B_BEFORE", "2026-06-15T05:00:00+00:00", .8),
        ("A_AFTER", "2026-09-10T05:00:00+00:00", .5),
        ("B_AFTER", "2026-09-10T05:00:00+00:00", .5),
    ]
    scenes = [make_scene(item_id, acquired, ndvi_left=value, ndvi_right=value, coverage=1.0)
              for item_id, acquired, value in specs]
    listed_a = [candidate(item_id, acquired) for item_id, acquired, _ in specs if item_id.startswith("A_")]
    listed_b = [candidate(item_id, acquired) for item_id, acquired, _ in specs if item_id.startswith("B_")]
    provider = CompareSceneProvider(scenes, listed_a, listed_b)
    q = SimpleNamespace(operation=Operation.CHANGE_DETECTION, date_a=DateRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
                        date_b=DateRange(start=date(2026, 9, 1), end=date(2026, 9, 30)), index="NDVI", thresholds={})

    result_a, result_b = run_compare_operation(q, AOI, AOI_B, provider, 10, None)

    assert [scene["item_id"] for scene in result_a["evidence"]["scenes"]] == ["A_BEFORE", "A_AFTER"]
    assert [scene["item_id"] for scene in result_b["evidence"]["scenes"]] == ["B_BEFORE", "B_AFTER"]
    assert [scene["datetime"][:10] for scene in result_a["evidence"]["scenes"]] == [
        scene["datetime"][:10] for scene in result_b["evidence"]["scenes"]]
    for scene in result_a["evidence"]["scenes"] + result_b["evidence"]["scenes"]:
        assert scene["collection"] == "sentinel-2-l2a"
        assert scene["provider"] == "synthetic test provider"
        assert scene["platform"] == "Sentinel-2A"
        assert scene["processing_level"] == "L2A"
        assert scene["coverage_fraction"] == pytest.approx(1.0)


def test_time_series_uses_only_matched_dates_and_fails_below_minimum():
    dates = [f"2026-{month:02d}-15T05:00:00+00:00" for month in range(1, 10)]
    scenes = []
    listed_a, listed_b = [], []
    for index, acquired in enumerate(dates):
        for prefix, target in (("A", listed_a), ("B", listed_b)):
            item_id = f"{prefix}_{index}"
            scenes.append(make_scene(item_id, acquired, ndvi_left=.5 + index * .01, ndvi_right=.5 + index * .01,
                                     coverage=1.0))
            # B lacks the first date; the eight remaining calendar dates are paired.
            if prefix == "A" or index > 0:
                target.append(candidate(item_id, acquired))
    provider = CompareSceneProvider(scenes, listed_a, listed_b)
    q = SimpleNamespace(operation=Operation.TIME_SERIES,
                        series_range=DateRange(start=date(2026, 1, 1), end=date(2026, 9, 30)),
                        index="NDVI")
    result_a, result_b = run_compare_operation(q, AOI, AOI_B, provider, 10, None)
    dates_a = result_a["facts"]["series"]["dates"]
    dates_b = result_b["facts"]["series"]["dates"]
    assert dates_a == dates_b == [d[:10] for d in dates[1:]]
    assert [s["item_id"] for s in result_a["evidence"]["scenes"]] == [f"A_{i}" for i in range(1, 9)]
    assert [s["item_id"] for s in result_b["evidence"]["scenes"]] == [f"B_{i}" for i in range(1, 9)]

    provider.listed_a = listed_a[:7]
    provider.listed_b = listed_b[:7]
    with pytest.raises(InsufficientDataError, match="at least 8 are required"):
        run_compare_operation(q, AOI, AOI_B, provider, 10, None)


@pytest.mark.parametrize("oversized", ["a", "b"])
def test_compare_checks_area_limit_for_each_aoi(tmp_path, monkeypatch, oversized):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / f"compare-area-{oversized}.sqlite"))
    monkeypatch.setattr(api_main, "MAX_AOI_AREA_KM2", 200.0)
    original = api_main._aoi_measurements

    def measurements(geometry):
        measured = original(geometry)
        is_area_a = geometry.centroid.x < 78.01
        if (oversized == "a" and is_area_a) or (oversized == "b" and not is_area_a):
            return 201.0, measured[1], measured[2]
        return measured

    monkeypatch.setattr(api_main, "_aoi_measurements", measurements)
    app.dependency_overrides[get_provider] = lambda: CompareSceneProvider([])
    with TestClient(app) as client:
        response = client.post("/analysis/compare", json={
            "query": "Show NDVI for June", "aoi_a": AOI, "aoi_b": AOI_B,
            "max_cloud": 10,
        })
    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "aoi_too_large"


def test_compare_api_applies_the_requested_cloud_threshold_to_both_areas(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / "compare-cloud.sqlite"))
    scene = make_scene("S2_MATCH", "2026-06-15T05:00:00+00:00", coverage=1.0)
    provider = CompareSceneProvider([scene], [candidate("S2_MATCH")], [candidate("S2_MATCH")])
    app.dependency_overrides[get_provider] = lambda: provider
    with TestClient(app) as client:
        response = client.post("/analysis/compare", json={
            "query": "Show NDVI for June", "aoi_a": AOI, "aoi_b": AOI_B,
            "max_cloud": 7,
        })
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert [cloud for _aoi, cloud in provider.discovery_calls] == [7, 7]
