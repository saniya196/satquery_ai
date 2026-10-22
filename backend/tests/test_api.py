import struct
import zlib

import numpy as np
import pytest
from fastapi.testclient import TestClient
from app.api import main as api_main
from app.api.main import app, get_provider
from tests.fakes import AOI, FakeLandCoverClassifier, FakeProvider, make_scene

client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_DB", str(tmp_path / "api-history.sqlite"))
    p = FakeProvider([make_scene("A", "2026-06-15T05:00:00+00:00", 0.8, 0.8),
                      make_scene("B", "2026-09-10T05:00:00+00:00", 0.5, 0.8)])
    app.dependency_overrides[get_provider] = lambda: p
    yield p
    app.dependency_overrides.clear()


def _decode_rgba_png(content):
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", content[16:24])
    offset, compressed = 8, []
    while offset < len(content):
        length = struct.unpack(">I", content[offset:offset + 4])[0]
        kind = content[offset + 4:offset + 8]
        payload = content[offset + 8:offset + 8 + length]
        if kind == b"IDAT":
            compressed.append(payload)
        offset += 12 + length
        if kind == b"IEND":
            break
    raw = zlib.decompress(b"".join(compressed))
    row_size = width * 4 + 1
    rows = [raw[i * row_size:(i + 1) * row_size] for i in range(height)]
    assert all(row[0] == 0 for row in rows)
    pixels = np.frombuffer(b"".join(row[1:] for row in rows), dtype=np.uint8)
    return width, height, pixels.reshape(height, width, 4)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_bad_aoi_is_422():
    r = client.post("/aoi/validate", json={"aoi": {"type": "Point", "coordinates": [1, 2]}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_aoi"


def test_aoi_validate_returns_equirectangular_area_center_and_bounds():
    response = client.post("/aoi/validate", json={"aoi": AOI})
    assert response.status_code == 200
    data = response.json()
    assert data["area_km2"] == pytest.approx(1.18, rel=0.03)
    assert data["centre"]["lat"] == pytest.approx(17.005)
    assert data["centre"]["lon"] == pytest.approx(78.005)
    assert data["bounds"] == [78.0, 17.0, 78.01, 17.01]


def test_aoi_over_200_square_km_is_rejected_for_validation_and_analysis():
    large_aoi = {"type": "Polygon", "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]]}
    validation = client.post("/aoi/validate", json={"aoi": large_aoi})
    assert validation.status_code == 422
    assert validation.json()["detail"]["code"] == "aoi_too_large"
    assert "smaller area" in validation.json()["detail"]["message"]

    run = client.post("/analysis/run", json={
        "query": "Show NDVI for June", "aoi": large_aoi, "reference_date": "2026-10-07",
    })
    assert run.status_code == 422
    assert run.json()["detail"]["code"] == "aoi_too_large"


def test_imagery_scenes_returns_sorted_fakes_and_validates_aoi():
    response = client.post("/imagery/scenes", json={
        "aoi": AOI, "start": "2026-06-01", "end": "2026-09-30", "max_cloud": 40,
    })
    assert response.status_code == 200
    items = response.json()
    assert [item["item_id"] for item in items] == ["A", "B"]
    assert [item["datetime"] for item in items] == sorted(item["datetime"] for item in items)

    invalid = client.post("/imagery/scenes", json={
        "aoi": {"type": "Point", "coordinates": [0, 0]},
        "start": "2026-06-01", "end": "2026-09-30", "max_cloud": 40,
    })
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_aoi"


def test_imagery_scenes_caps_provider_results_at_100(monkeypatch):
    provider = FakeProvider([])
    provider.list_scenes = lambda aoi, start, end, max_cloud: [
        {"item_id": str(index), "datetime": f"2026-01-{index % 28 + 1:02d}T00:00:00Z", "cloud_cover": 1}
        for index in range(120)
    ]
    app.dependency_overrides[get_provider] = lambda: provider
    response = client.post("/imagery/scenes", json={
        "aoi": AOI, "start": "2026-01-01", "end": "2026-12-31", "max_cloud": 40,
    })
    assert response.status_code == 200
    assert len(response.json()) == 100


def test_parse_endpoint():
    r = client.post("/query/parse", json={"query": "Did vegetation decrease?", "reference_date": "2026-10-07"}).json()
    assert r["clarification"] and r["structured_query"]["operation"] == "change_detection"


def test_query_length_limit():
    assert client.post("/query/parse", json={"query": "x" * 501}).status_code == 422


def test_grounding_endpoint():
    r = client.post("/grounding/check", json={"answer": "It fell 25%.", "facts": {"x": 18.3}}).json()
    assert r["valid"] is False


def test_run_asks_for_missing_info_instead_of_guessing():
    r = client.post("/analysis/run", json={"query": "Did vegetation decrease?", "aoi": AOI}).json()
    assert r["status"] == "needs_clarification"


def test_run_full_job_lifecycle():
    r = client.post("/analysis/run", json={"query": "Did vegetation health decrease between June and September?",
                                           "aoi": AOI, "reference_date": "2026-10-07"}).json()
    assert r["status"] == "queued"
    job = client.get(f"/jobs/{r['job_id']}").json()
    assert job["status"] == "completed"
    assert job["result"]["facts"]["change"]["mean_change"] == pytest.approx(-0.15, abs=1e-6)
    assert "arrays" not in job["result"]


def test_failed_job_reports_error_not_result():
    r = client.post("/analysis/run", json={"query": "Did vegetation decrease between January and February?",
                                           "aoi": AOI, "reference_date": "2026-10-07"}).json()
    job = client.get(f"/jobs/{r['job_id']}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "no_imagery" and "result" not in job


def test_unknown_job_404():
    assert client.get("/jobs/nope").status_code == 404


def test_map_layers_render_png_and_publish_bounds_and_legends():
    p = FakeProvider([make_scene("A", "2026-06-15T05:00:00+00:00"),
                      make_scene("B", "2026-09-10T05:00:00+00:00", 0.5, 0.8,
                                 cloudy_fraction=0.1)])
    app.dependency_overrides[get_provider] = lambda: p
    run = client.post("/analysis/run", json={
        "query": "Did vegetation health decrease between June and September?",
        "aoi": AOI,
        "reference_date": "2026-10-07",
    }).json()
    assert client.get(f"/jobs/{run['job_id']}").json()["status"] == "completed"

    metadata = client.get(f"/analysis/{run['job_id']}/layers")
    assert metadata.status_code == 200
    metadata = metadata.json()
    south_west, north_east = metadata["bounds"]
    assert 30 < south_west[0] < 40 and 30 < north_east[0] < 40
    assert 78 < south_west[1] < 84 and 78 < north_east[1] < 84
    assert set(metadata["layers"]) == {"index", "diff", "classes", "hotspots"}

    index_response = client.get(f"/analysis/{run['job_id']}/layer/index.png")
    assert index_response.status_code == 200 and index_response.headers["content-type"] == "image/png"
    width, height, index_pixels = _decode_rgba_png(index_response.content)
    assert (width, height) == (60, 60)
    assert tuple(index_pixels[0, 0]) == (0, 0, 0, 0)
    assert index_pixels[10, 45, 3] == 255

    index_legend = metadata["layers"]["index"]
    assert index_legend["value_range"] == [-1.0, 1.0]
    low, high = [tuple(int(color["hex"][i:i + 2], 16) for i in (1, 3, 5))
                 for color in index_legend["colors"]]
    fraction = (0.8 - index_legend["value_range"][0]) / (
        index_legend["value_range"][1] - index_legend["value_range"][0])
    expected = tuple(round(low[i] + (high[i] - low[i]) * fraction) for i in range(3))
    assert tuple(index_pixels[10, 45, :3]) == expected

    diff_response = client.get(f"/analysis/{run['job_id']}/layer/diff.png")
    assert diff_response.status_code == 200
    diff_width, diff_height, diff_pixels = _decode_rgba_png(diff_response.content)
    assert (diff_width, diff_height) == (60, 60)
    assert tuple(diff_pixels[0, 0]) == (0, 0, 0, 0)

    classes_response = client.get(f"/analysis/{run['job_id']}/layer/classes.png")
    _, _, class_pixels = _decode_rgba_png(classes_response.content)
    class_legend = metadata["layers"]["classes"]
    decrease_color = next(c["hex"] for c in class_legend["colors"] if c["value"] == -2)
    assert tuple(class_pixels[10, 10, :3]) == tuple(
        int(decrease_color[i:i + 2], 16) for i in (1, 3, 5))
    assert class_pixels[0, 0, 3] == 0

    hotspots_response = client.get(f"/analysis/{run['job_id']}/layer/hotspots.png")
    _, _, hotspot_pixels = _decode_rgba_png(hotspots_response.content)
    assert tuple(hotspot_pixels[10, 10]) == (255, 0, 0, 255)
    assert hotspot_pixels[10, 45, 3] == 0
    assert metadata["layers"]["hotspots"]["colors"][0]["hex"] == "#ff0000"

    assert client.get(f"/analysis/{run['job_id']}/layer/unknown.png").status_code == 404
    assert client.get(f"/analysis/missing/layers").status_code == 404


def test_index_stats_raster_is_retained_for_rendering():
    run = client.post("/analysis/run", json={
        "query": "Show NDVI for June",
        "aoi": AOI,
        "reference_date": "2026-10-07",
    }).json()
    assert client.get(f"/jobs/{run['job_id']}").json()["status"] == "completed"
    image = client.get(f"/analysis/{run['job_id']}/layer/index.png")
    assert image.status_code == 200
    assert _decode_rgba_png(image.content)[:2] == (60, 60)


def test_landcover_job_exposes_product_classes(monkeypatch):
    monkeypatch.setattr(api_main, "get_classifier", FakeLandCoverClassifier)
    run = client.post("/analysis/run", json={
        "query": "Show land cover for June",
        "aoi": AOI,
        "reference_date": "2026-10-07",
    }).json()
    assert client.get(f"/jobs/{run['job_id']}").json()["status"] == "completed"

    metadata = client.get(f"/analysis/{run['job_id']}/layers").json()
    assert set(metadata["layers"]) == {"landcover"}
    legend = metadata["layers"]["landcover"]
    assert [item["label"] for item in legend["colors"]] == [
        "vegetation", "agricultural_land", "built_up", "water"]
    _, _, pixels = _decode_rgba_png(client.get(
        f"/analysis/{run['job_id']}/layer/landcover.png").content)
    for item in legend["colors"]:
        code = item["value"]
        color = tuple(int(item["hex"][i:i + 2], 16) for i in (1, 3, 5))
        assert tuple(pixels[10, code, :3]) == color
        assert pixels[10, code, 3] == 255


def test_layer_store_evicts_oldest_after_twenty_jobs():
    api_main._layer_store.clear()
    operation = api_main.Operation.INDEX_STATS
    try:
        for number in range(21):
            with api_main._lock:
                api_main._store_layer_data(
                    f"layer-job-{number}", {"index": np.zeros((1, 1))},
                    {"transform": "synthetic transform", "crs": "EPSG:32644"}, operation)
        assert len(api_main._layer_store) == 20
        assert "layer-job-0" not in api_main._layer_store
        assert "layer-job-20" in api_main._layer_store
    finally:
        api_main._layer_store.clear()


def test_layer_endpoints_return_409_until_job_is_completed():
    job_id = "pending-layer-job"
    api_main._jobs[job_id] = {"job_id": job_id, "status": "processing"}
    try:
        assert client.get(f"/analysis/{job_id}/layers").status_code == 409
        assert client.get(f"/analysis/{job_id}/layer/index.png").status_code == 409
    finally:
        api_main._jobs.pop(job_id, None)


def test_nan_pixels_are_transparent_and_landcover_colors_match_legend():
    from app.rendering.layers import colorize_diff, colorize_index, colorize_landcover, legend_for

    index = colorize_index(np.array([[np.nan, 1.0]]))
    assert tuple(index[0, 0]) == (0, 0, 0, 0)
    index_high = next(color for color in legend_for("index")["colors"] if color["value"] == 1.0)
    assert tuple(index[0, 1, :3]) == tuple(int(index_high["hex"][i:i + 2], 16) for i in (1, 3, 5))

    diff = colorize_diff(np.array([[np.nan, 0.0]]))
    assert tuple(diff[0, 0]) == (0, 0, 0, 0)
    diff_mid = next(color for color in legend_for("diff")["colors"] if color["value"] == 0.0)
    assert tuple(diff[0, 1, :3]) == tuple(int(diff_mid["hex"][i:i + 2], 16) for i in (1, 3, 5))

    landcover = colorize_landcover(np.array([[-1, np.nan, 0, 1, 2, 3]]))
    assert np.all(landcover[0, :2] == 0)
    for color in legend_for("landcover")["colors"]:
        code = color["value"]
        rgb = tuple(int(color["hex"][i:i + 2], 16) for i in (1, 3, 5))
        assert tuple(landcover[0, code + 2, :3]) == rgb
        assert landcover[0, code + 2, 3] == 255


def test_geotiff_inspect_endpoint():
    from tests.test_geotiff import create_minimal_tiff
    data = create_minimal_tiff(width=640, height=480, bands=4)
    res = client.post(
        "/geotiff/inspect",
        files={"file": ("S2A_MSIL2A_B08.tif", data, "image/tiff")}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["valid"] is True
    assert body["width"] == 640
    assert body["height"] == 480
    assert body["band_count"] == 4
    assert any("B08" in b for b in body["bands"])

