from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import mapping, box

from app.api import main as api_main
from app.api.main import app, get_provider
from app.core.errors import MissingBandError, NoImageryError
from app.satellite.provider import EARTH_SEARCH_ASSETS, EarthSearchProvider
from tests.fakes import AOI, FakeLandCoverClassifier, FakeProvider, make_scene


class SelectableFakeProvider(FakeProvider):
    def __init__(self, scenes):
        super().__init__(scenes)
        self.resolved_ids = []
        self.read_ids = []

    def resolve_scene(self, aoi_geojson, item_id, max_cloud, start=None, end=None,
                      required_bands=None, min_coverage=0.99):
        self.resolved_ids.append(item_id)
        scene = self.scenes.get(item_id)
        if scene is None:
            raise NoImageryError(f"Selected scene {item_id} was not found in the test Sentinel-2 catalog.")
        acquisition_date = datetime.fromisoformat(scene["datetime"].replace("Z", "+00:00")).date()
        if start is not None and not start <= acquisition_date <= end:
            raise NoImageryError(f"Selected scene {item_id} is outside the requested date range.")
        if scene["cloud"] > max_cloud:
            raise NoImageryError(f"Selected scene {item_id} exceeds the cloud-cover limit.")
        missing = set(required_bands or ()) - set(scene["bands"])
        if missing:
            raise MissingBandError(f"Selected scene {item_id} is missing required bands: {', '.join(sorted(missing))}.")
        return {
            "item_id": item_id,
            "datetime": scene["datetime"],
            "acquisition_date": acquisition_date,
            "cloud_cover": scene["cloud"],
            "collection": "sentinel-2-l2a",
            "coverage": 1.0,
        }

    def get_scene(self, aoi_geojson, item_id, bands):
        self.read_ids.append(item_id)
        return super().get_scene(aoi_geojson, item_id, bands)

    def best_scene(self, *args, **kwargs):
        raise AssertionError("best_scene must not be called for an explicit scene selection")


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / "selected-scene.sqlite"))
    provider = SelectableFakeProvider([
        make_scene("S2_A", "2026-06-05T05:00:00+00:00", cloud=5),
        make_scene("S2_B", "2026-06-15T05:00:00+00:00", cloud=12),
    ])
    app.dependency_overrides[get_provider] = lambda: provider
    monkeypatch.setattr(api_main, "get_classifier", lambda: FakeLandCoverClassifier())
    with TestClient(app) as client:
        yield client, provider
    app.dependency_overrides.clear()


def _catalog_item(item_id="S2_TEST", geometry=None, cloud=5.0, assets=None,
                  acquisition="2026-06-15T05:00:00+00:00", collection="sentinel-2-l2a"):
    asset_map = assets if assets is not None else {
        asset: object() for asset in EARTH_SEARCH_ASSETS.values()
    }
    return SimpleNamespace(
        id=item_id,
        collection_id=collection,
        datetime=datetime.fromisoformat(acquisition),
        properties={"eo:cloud_cover": cloud},
        geometry=geometry or mapping(box(78.0, 17.0, 78.01, 17.01)),
        bbox=None,
        assets=asset_map,
    )


class _Search:
    def __init__(self, items):
        self._items = items

    def items(self):
        return iter(self._items)


class _Catalog:
    def __init__(self, item):
        self.item = item

    def search(self, **kwargs):
        requested_ids = kwargs.get("ids") or []
        return _Search([self.item] if self.item and self.item.id in requested_ids else [])


def _mock_catalog(monkeypatch, item):
    from pystac_client import Client

    monkeypatch.setattr(Client, "open", staticmethod(lambda *args, **kwargs: _Catalog(item)))


def test_selected_scene_id_is_read_exactly_for_standard_index_stats(api_client):
    client, provider = api_client
    response = client.post("/analysis/run", json={
        "query": "Show NDVI for June", "aoi": AOI, "reference_date": "2026-10-07",
        "selected_scene_id": "S2_B", "max_cloud": 15,
    })
    assert response.status_code == 200
    job = client.get(f"/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "completed"
    assert provider.read_ids == ["S2_B"]
    assert job["result"]["evidence"]["scenes"][0]["item_id"] == "S2_B"
    assert job["result"]["evidence"]["scenes"][0]["datetime"].startswith("2026-06-15")


def test_selected_scene_supplies_date_when_question_has_no_date(api_client):
    client, provider = api_client
    response = client.post("/analysis/run", json={
        "query": "Show NDVI", "aoi": AOI, "selected_scene_id": "S2_A", "max_cloud": 15,
    })
    assert response.status_code == 200
    job = client.get(f"/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "completed"
    assert job["structured_query"]["date_a"] == {"start": "2026-06-05", "end": "2026-06-05"}
    assert provider.read_ids == ["S2_A"]


def test_selected_scene_is_used_for_land_cover(api_client):
    client, provider = api_client
    response = client.post("/analysis/run", json={
        "query": "Show land cover for June", "aoi": AOI,
        "selected_scene_id": "S2_A", "max_cloud": 15,
    })
    assert response.status_code == 200
    job = client.get(f"/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "completed"
    assert provider.read_ids == ["S2_A"]
    assert job["result"]["evidence"]["scenes"][0]["item_id"] == "S2_A"


def test_unknown_selected_scene_returns_actionable_error_without_fallback(api_client):
    client, provider = api_client
    response = client.post("/analysis/run", json={
        "query": "Show NDVI for June", "aoi": AOI, "selected_scene_id": "unknown",
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_imagery"
    assert "not found" in response.json()["detail"]["message"]
    assert provider.read_ids == []


def test_selected_scene_must_meet_cloud_threshold(api_client):
    client, provider = api_client
    response = client.post("/analysis/run", json={
        "query": "Show NDVI for June", "aoi": AOI,
        "selected_scene_id": "S2_B", "max_cloud": 10,
    })
    assert response.status_code == 422
    assert "cloud-cover" in response.json()["detail"]["message"]
    assert provider.read_ids == []


def test_selected_scene_read_failure_does_not_fall_back(api_client, monkeypatch):
    client, provider = api_client

    def fail_selected_read(aoi_geojson, item_id, bands):
        raise NoImageryError(f"Selected scene {item_id} asset is unavailable.")

    monkeypatch.setattr(provider, "get_scene", fail_selected_read)
    response = client.post("/analysis/run", json={
        "query": "Show NDVI for June", "aoi": AOI,
        "selected_scene_id": "S2_A", "max_cloud": 15,
    })
    assert response.status_code == 200
    job = client.get(f"/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "failed"
    assert "asset is unavailable" in job["error"]["message"]


@pytest.mark.parametrize("query", [
    "Did vegetation decrease between June and September?",
    "Show me the vegetation trend over the last year",
])
def test_selected_scene_is_rejected_for_multi_date_operations(api_client, query):
    client, provider = api_client
    response = client.post("/analysis/run", json={
        "query": query, "aoi": AOI, "selected_scene_id": "S2_A",
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "selected_scene_unsupported"
    assert provider.read_ids == []


def test_provider_resolves_scene_from_catalog_without_prior_cache(monkeypatch, tmp_path):
    item = _catalog_item()
    _mock_catalog(monkeypatch, item)
    provider = EarthSearchProvider(str(tmp_path))
    assert provider._items == {}
    resolved = provider.resolve_scene(AOI, "S2_TEST", 10, date(2026, 6, 1), date(2026, 6, 30), ["red", "nir"])
    assert resolved["item_id"] == "S2_TEST"
    assert resolved["collection"] == "sentinel-2-l2a"
    assert resolved["coverage"] == pytest.approx(1.0)
    assert provider._items["S2_TEST"] is item


def test_provider_rejects_unknown_selected_scene(monkeypatch, tmp_path):
    _mock_catalog(monkeypatch, None)
    provider = EarthSearchProvider(str(tmp_path))
    with pytest.raises(NoImageryError, match="not found"):
        provider.resolve_scene(AOI, "unknown", 40)


def test_provider_rejects_scene_outside_aoi(monkeypatch, tmp_path):
    item = _catalog_item(geometry=mapping(box(79.0, 18.0, 79.01, 18.01)))
    _mock_catalog(monkeypatch, item)
    provider = EarthSearchProvider(str(tmp_path))
    with pytest.raises(NoImageryError, match="covers only"):
        provider.resolve_scene(AOI, "S2_TEST", 40)


def test_provider_rejects_scene_outside_requested_date(monkeypatch, tmp_path):
    _mock_catalog(monkeypatch, _catalog_item())
    provider = EarthSearchProvider(str(tmp_path))
    with pytest.raises(NoImageryError, match="outside the requested"):
        provider.resolve_scene(AOI, "S2_TEST", 40, date(2026, 7, 1), date(2026, 7, 31))


def test_provider_rejects_scene_missing_required_asset(monkeypatch, tmp_path):
    assets = {name: object() for name in EARTH_SEARCH_ASSETS.values() if name != "nir"}
    _mock_catalog(monkeypatch, _catalog_item(assets=assets))
    provider = EarthSearchProvider(str(tmp_path))
    with pytest.raises(MissingBandError, match="missing required Sentinel-2 assets: nir"):
        provider.resolve_scene(AOI, "S2_TEST", 40, required_bands=["nir"])


def test_standard_analysis_without_scene_selection_keeps_best_scene_path(monkeypatch):
    provider = FakeProvider([make_scene("S2_A", "2026-06-15T05:00:00+00:00")])
    monkeypatch.setitem(app.dependency_overrides, get_provider, lambda: provider)
    with TestClient(app) as client:
        response = client.post("/analysis/run", json={
            "query": "Show NDVI for June", "aoi": AOI, "reference_date": "2026-10-07",
        })
        assert response.status_code == 200
        job = client.get(f"/jobs/{response.json()['job_id']}").json()
        assert job["status"] == "completed"
        assert job["result"]["evidence"]["scenes"][0]["item_id"] == "S2_A"
