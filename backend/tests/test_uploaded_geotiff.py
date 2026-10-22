import io

import numpy as np
import pytest
from affine import Affine

from app.api import main as api_main
from app.api.main import app
from app.satellite.geotiff import GeoTIFFMetadata
from app.satellite.provider import UploadedRaster, UploadedRasterError, region_pixel_window
from fastapi.testclient import TestClient


client = TestClient(app)


def _raster(values=None, units="metre"):
    data = np.asarray(values if values is not None else [[1.0, 2.0], [np.nan, 4.0]], dtype=np.float64)
    return UploadedRaster(data=data, width=2, height=2, band_count=1, dtype="float32",
                          crs="EPSG:32643", transform=Affine(10, 0, 500000, 0, -10, 2000000),
                          nodata=-9999.0, resolution_x=10.0, resolution_y=10.0,
                          linear_units=units, bounds=(500000.0, 1999980.0, 500020.0, 2000000.0))


def _metadata(crs="EPSG:32643", resolution=10.0):
    return GeoTIFFMetadata(filename="upload.tif", is_valid_geotiff=True, width=2, height=2,
                           band_count=1, bits_per_sample=[32], data_type="float32", crs=crs,
                           epsg_code=32643 if crs else None, resolution_m=resolution)


def test_uploaded_result_uses_real_pixels_and_only_reports_supported_area():
    result = api_main._uploaded_result(_metadata(), _raster(), "upload.tif", 1)
    assert result["operation"] == "uploaded_single_band_statistics"
    assert result["stats"]["valid_pixel_count"] == 3
    assert result["stats"]["mean"] == 7 / 3
    assert result["stats"]["analysed_area_km2"] == 0.0003
    assert result["evidence"]["valid_pixel_fraction"] == 0.75


def test_uploaded_result_does_not_invent_area_for_degree_crs():
    result = api_main._uploaded_result(_metadata(crs="EPSG:4326"), _raster(units="degree"), "upload.tif", 1)
    assert result["stats"]["analysed_area_km2"] is None
    assert "not metres" in result["evidence"]["area_note"]


def test_upload_rejects_non_tiff():
    response = client.post("/geotiff/analyze", files={"file": ("image.png", b"not a tiff", "image/png")})
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"


def test_upload_rejects_missing_crs(monkeypatch):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: _metadata(crs=None))
    monkeypatch.setattr(api_main, "read_uploaded_raster",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            UploadedRasterError("missing_crs", "The raster has no CRS.")))
    response = client.post("/geotiff/analyze", files={"file": ("image.tif", b"TIFF", "image/tiff")})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "missing_crs"


def test_upload_returns_clear_error_for_unavailable_pixel_backend(monkeypatch):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: _metadata())
    monkeypatch.setattr(api_main, "read_uploaded_raster",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            UploadedRasterError("raster_backend_unavailable", "backend unavailable")))
    response = client.post("/geotiff/analyze", files={"file": ("image.tif", b"TIFF", "image/tiff")})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "raster_backend_unavailable"


def test_upload_rejects_unsupported_operation(monkeypatch):
    response = client.post("/geotiff/analyze", data={"operation": "ndvi", "band": "1"},
                           files={"file": ("image.tif", io.BytesIO(b"TIFF"), "image/tiff")})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_operation"


def test_region_pixel_window_uses_raster_crs_and_affine_transform():
    window = region_pixel_window(
        {"min_x": 500010, "min_y": 1999990, "max_x": 500020, "max_y": 2000000},
        _raster().transform,
        _raster().bounds,
        2,
        2,
    )
    assert window == (1, 0, 2, 1)


def test_region_pixel_window_rejects_outside_and_invalid_regions():
    bounds = _raster().bounds
    transform = _raster().transform
    with pytest.raises(UploadedRasterError, match="outside"):
        region_pixel_window({"min_x": 499999, "min_y": 1999990, "max_x": 500010, "max_y": 2000000}, transform, bounds, 2, 2)
    with pytest.raises(UploadedRasterError, match="smaller"):
        region_pixel_window({"min_x": 500010, "min_y": 1999990, "max_x": 500000, "max_y": 2000000}, transform, bounds, 2, 2)


def test_region_statistics_returns_real_region_evidence_and_nodata(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: _metadata())

    def fake_read(_path, band, region):
        captured["band"] = band
        captured["region"] = region
        return _raster([[1.0, np.nan], [3.0, 4.0]])

    monkeypatch.setattr(api_main, "read_uploaded_raster_region", fake_read)
    response = client.post(
        "/geotiff/analyze",
        data={"operation": "region_statistics", "band": "1", "region_min_x": "500000",
              "region_min_y": "1999990", "region_max_x": "500020", "region_max_y": "2000000"},
        files={"file": ("image.tif", b"TIFF", "image/tiff")},
    )
    assert response.status_code == 200
    body = response.json()
    assert captured["band"] == 1
    assert captured["region"] == {"min_x": 500000.0, "min_y": 1999990.0, "max_x": 500020.0, "max_y": 2000000.0}
    assert body["operation"] == "uploaded_region_statistics"
    assert body["stats"]["valid_pixel_count"] == 3
    assert body["stats"]["mean"] == pytest.approx(8 / 3)
    assert body["stats"]["total_pixel_count"] == 4
    assert body["evidence"]["region"]["crs"] == "EPSG:32643"
    assert body["evidence"]["valid_pixel_fraction"] == pytest.approx(0.75)
    assert "finite pixels" in body["evidence"]["formula"]


def test_region_statistics_requires_all_coordinates():
    response = client.post(
        "/geotiff/analyze",
        data={"operation": "region_statistics", "band": "1"},
        files={"file": ("image.tif", b"TIFF", "image/tiff")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "region_required"


def test_region_statistics_reports_no_valid_pixels(monkeypatch):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: _metadata())
    monkeypatch.setattr(api_main, "read_uploaded_raster_region",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            UploadedRasterError("no_valid_pixels", "The selected region contains no valid pixels.")))
    response = client.post(
        "/geotiff/analyze",
        data={"operation": "region_statistics", "band": "1", "region_min_x": "500000",
              "region_min_y": "1999990", "region_max_x": "500020", "region_max_y": "2000000"},
        files={"file": ("image.tif", b"TIFF", "image/tiff")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_valid_pixels"


def test_uploaded_change_uses_after_minus_before_and_evidence(monkeypatch):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: _metadata())
    rasters = iter([_raster([[1.0, np.nan], [3.0, 4.0]]), _raster([[2.0, 5.0], [1.0, 6.0]])])
    monkeypatch.setattr(api_main, "read_uploaded_raster", lambda *_args, **_kwargs: next(rasters))
    response = client.post(
        "/geotiff/change",
        data={"before_date": "2026-01-01", "after_date": "2026-02-01", "before_band": "1", "after_band": "1"},
        files={
            "before_file": ("before.tif", b"before", "image/tiff"),
            "after_file": ("after.tif", b"after", "image/tiff"),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["common_valid_pixel_count"] == 3
    assert body["metrics"]["difference_mean"] == pytest.approx(1 / 3)
    assert body["metrics"]["absolute_difference_mean"] == pytest.approx(5 / 3)
    assert body["description"]["direction"] == "positive"
    assert body["description"]["mean_difference"] == pytest.approx(1 / 3)
    assert body["description"]["absolute_difference_mean"] == pytest.approx(5 / 3)
    assert body["description"]["median_difference"] == pytest.approx(1)
    assert body["description"]["common_valid_pixel_fraction"] == pytest.approx(0.75)
    assert body["description"]["source_units"] is None
    assert "increased" in body["description"]["text"]
    assert all(term not in body["description"]["text"].lower() for term in ("deforestation", "urbanization", "ndvi", "land-cover"))
    assert body["evidence"]["dates"] == ["2026-01-01", "2026-02-01"]
    assert body["evidence"]["bands"] == ["band_1", "band_1"]
    assert body["evidence"]["formula"] == "after - before"
    assert [source["filename"] for source in body["sources"]] == ["before.tif", "after.tif"]
    assert body["alignment"]["resampling"] == "none"


@pytest.mark.parametrize(
    ("after_values", "direction", "phrase"),
    [([[2.0, 2.0], [2.0, 2.0]], "positive", "increased"),
     ([[0.0, 0.0], [0.0, 0.0]], "negative", "decreased"),
     ([[1.0, 1.0], [1.0, 1.0]], "zero", "showed no mean change")],
)
def test_uploaded_change_description_direction_is_deterministic(monkeypatch, after_values, direction, phrase):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: _metadata())
    rasters = iter([_raster([[1.0, 1.0], [1.0, 1.0]]), _raster(after_values)])
    monkeypatch.setattr(api_main, "read_uploaded_raster", lambda *_args, **_kwargs: next(rasters))
    response = client.post(
        "/geotiff/change",
        data={"before_date": "2026-01-01", "after_date": "2026-02-01"},
        files={"before_file": ("before.tif", b"before", "image/tiff"), "after_file": ("after.tif", b"after", "image/tiff")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"]["direction"] == direction
    assert phrase in body["description"]["text"]
    assert body["description"]["dates"] == ["2026-01-01", "2026-02-01"]
    assert body["description"]["bands"] == ["band_1", "band_1"]
    assert body["evidence"]["description"] == body["description"]


def test_uploaded_change_rejects_invalid_dates_and_bands():
    files = {
        "before_file": ("before.tif", b"before", "image/tiff"),
        "after_file": ("after.tif", b"after", "image/tiff"),
    }
    invalid_date = client.post("/geotiff/change", data={"before_date": "01-01-2026", "after_date": "2026-02-01"}, files=files)
    assert invalid_date.status_code == 422
    assert invalid_date.json()["detail"]["code"] == "invalid_date"
    invalid_order = client.post("/geotiff/change", data={"before_date": "2026-02-02", "after_date": "2026-02-01"}, files=files)
    assert invalid_order.status_code == 422
    assert invalid_order.json()["detail"]["code"] == "invalid_date_order"
    invalid_band = client.post("/geotiff/change", data={"before_date": "2026-01-01", "after_date": "2026-02-01", "before_band": "0"}, files=files)
    assert invalid_band.status_code == 422
    assert invalid_band.json()["detail"]["code"] == "invalid_band"


def test_uploaded_change_rejects_incompatible_grids(monkeypatch):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: _metadata())
    before = _raster()
    after = UploadedRaster(data=before.data.copy(), width=3, height=2, band_count=1, dtype="float32",
                           crs=before.crs, transform=before.transform, nodata=before.nodata,
                           resolution_x=before.resolution_x, resolution_y=before.resolution_y,
                           linear_units=before.linear_units, bounds=before.bounds)
    rasters = iter([before, after])
    monkeypatch.setattr(api_main, "read_uploaded_raster", lambda *_args, **_kwargs: next(rasters))
    response = client.post(
        "/geotiff/change",
        data={"before_date": "2026-01-01", "after_date": "2026-02-01"},
        files={"before_file": ("before.tif", b"before", "image/tiff"), "after_file": ("after.tif", b"after", "image/tiff")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "incompatible_dimensions"


def test_uploaded_change_rejects_crs_and_transform_mismatches(monkeypatch):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: _metadata())
    before = _raster()
    crs_mismatch = _raster()
    crs_mismatch.crs = "EPSG:4326"
    monkeypatch.setattr(api_main, "read_uploaded_raster", lambda *_args, **_kwargs: before)
    response = client.post(
        "/geotiff/change", data={"before_date": "2026-01-01", "after_date": "2026-02-01"},
        files={"before_file": ("before.tif", b"before", "image/tiff"), "after_file": ("after.tif", b"after", "image/tiff")},
    )
    assert response.status_code == 200

    rasters = iter([before, crs_mismatch])
    monkeypatch.setattr(api_main, "read_uploaded_raster", lambda *_args, **_kwargs: next(rasters))
    response = client.post(
        "/geotiff/change", data={"before_date": "2026-01-01", "after_date": "2026-02-01"},
        files={"before_file": ("before.tif", b"before", "image/tiff"), "after_file": ("after.tif", b"after", "image/tiff")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "incompatible_crs"

    transform_mismatch = _raster()
    transform_mismatch.transform = Affine(20, 0, 500000, 0, -10, 2000000)
    rasters = iter([before, transform_mismatch])
    monkeypatch.setattr(api_main, "read_uploaded_raster", lambda *_args, **_kwargs: next(rasters))
    response = client.post(
        "/geotiff/change", data={"before_date": "2026-01-01", "after_date": "2026-02-01"},
        files={"before_file": ("before.tif", b"before", "image/tiff"), "after_file": ("after.tif", b"after", "image/tiff")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "incompatible_transform"


def test_uploaded_change_reports_no_common_valid_pixels(monkeypatch):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: _metadata())
    invalid = _raster([[np.nan, np.nan], [np.nan, np.nan]])
    rasters = iter([invalid, invalid])
    monkeypatch.setattr(api_main, "read_uploaded_raster", lambda *_args, **_kwargs: next(rasters))
    response = client.post(
        "/geotiff/change",
        data={"before_date": "2026-01-01", "after_date": "2026-02-01"},
        files={"before_file": ("before.tif", b"before", "image/tiff"), "after_file": ("after.tif", b"after", "image/tiff")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_common_valid_pixels"


def test_uploaded_change_cleans_temp_files_and_rejects_oversized_upload(monkeypatch):
    monkeypatch.setattr(api_main, "MAX_UPLOAD_BYTES", 3)
    removed = []
    original_unlink = api_main.os.unlink
    monkeypatch.setattr(api_main.os, "unlink", lambda path: (removed.append(path), original_unlink(path))[1])
    response = client.post(
        "/geotiff/change",
        data={"before_date": "2026-01-01", "after_date": "2026-02-01"},
        files={"before_file": ("before.tif", b"1234", "image/tiff"), "after_file": ("after.tif", b"after", "image/tiff")},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"
    assert len(removed) == 1


def test_uploaded_change_rejects_invalid_files():
    response = client.post(
        "/geotiff/change", data={"before_date": "2026-01-01", "after_date": "2026-02-01"},
        files={"before_file": ("before.png", b"not tiff", "image/png"), "after_file": ("after.tif", b"after", "image/tiff")},
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"
