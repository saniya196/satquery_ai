from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import app

client = TestClient(app)


def _reset_place_search(monkeypatch):
    api_main._place_search_cache.clear()
    api_main._last_place_search_at = 0.0
    monkeypatch.setattr(api_main, "_PLACE_SEARCH_MIN_INTERVAL_SECONDS", 0.0)


def test_places_search_returns_normalized_results(monkeypatch):
    _reset_place_search(monkeypatch)
    monkeypatch.setattr(
        api_main,
        "_nominatim_place_search",
        lambda query, limit: [
            {"display_name": "London, England, United Kingdom", "lat": "51.5073", "lon": "-0.1276"}
        ],
    )

    response = client.get("/places/search", params={"q": "London", "limit": 5})

    assert response.status_code == 200
    assert response.json() == [
        {"display_name": "London, England, United Kingdom", "lat": "51.5073", "lon": "-0.1276"}
    ]


def test_places_search_short_query_returns_empty_list(monkeypatch):
    _reset_place_search(monkeypatch)

    response = client.get("/places/search", params={"q": "a"})

    assert response.status_code == 200
    assert response.json() == []


def test_places_search_rejects_overlong_query(monkeypatch):
    _reset_place_search(monkeypatch)

    response = client.get("/places/search", params={"q": "x" * 201})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "place_query_too_long"


def test_places_search_reports_upstream_failure(monkeypatch):
    _reset_place_search(monkeypatch)

    def fail(query, limit):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "place_search_unavailable",
                "message": "Location search is temporarily unavailable. Try again, or choose the location on the map.",
            },
        )

    monkeypatch.setattr(api_main, "_nominatim_place_search", fail)

    response = client.get("/places/search", params={"q": "London"})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "place_search_unavailable"
