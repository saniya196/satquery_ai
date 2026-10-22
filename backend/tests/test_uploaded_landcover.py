import json
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pytest
from affine import Affine
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.main import app
from app.classification.loader import get_classifier
from app.core.errors import InsufficientValidPixelsError
from app.satellite.geotiff import GeoTIFFMetadata
from app.satellite.provider import UploadedRasterCube, UploadedRasterError, read_uploaded_raster_cube
from app.services.land_cover import run_uploaded_land_cover


client = TestClient(app)
BANDS = ("B02", "B03", "B04", "B08", "B11")
MAPPING = {band: index for index, band in enumerate(BANDS, start=1)}


def cube(data=None, *, crs="EPSG:32643", transform=None, nodata=-9999.0, mapping=None):
    data = np.asarray(data if data is not None else np.ones((5, 64, 64), dtype=np.float32), dtype=np.float32)
    transform = transform or Affine(10, 0, 500000, 0, -10, 2000000)
    return UploadedRasterCube(
        data=data, width=data.shape[2], height=data.shape[1], band_count=5, dtype="float32",
        crs=crs, transform=transform, nodata=nodata, resolution_x=10.0, resolution_y=10.0,
        linear_units="metre", bounds=(500000.0, 1999360.0, 500640.0, 2000000.0),
        band_mapping=mapping or MAPPING,
    )


def metadata(*, crs="EPSG:32643", band_count=5):
    return GeoTIFFMetadata(filename="upload.tif", is_valid_geotiff=True, width=64, height=64,
                           band_count=band_count, bits_per_sample=[32] * band_count,
                           data_type="float32", crs=crs, epsg_code=32643 if crs else None,
                           resolution_m=10.0)


def post_file(mapping=MAPPING, radiometry="reflectance"):
    return client.post(
        "/geotiff/land-cover",
        data={"band_mapping": json.dumps(mapping), "radiometry": radiometry},
        files={"file": ("upload.tif", b"synthetic test bytes", "image/tiff")},
    )


class CaptureClassifier:
    bands_logical = ("blue", "green", "red", "nir", "swir1")
    tile = 64

    def __init__(self, captured):
        self.captured = captured

    def classify_cube(self, cube_value, valid, pixel_area):
        self.captured["cube"] = cube_value.copy()
        self.captured["valid"] = valid.copy()
        self.captured["pixel_area"] = pixel_area
        classes = {name: {"pixels": 0, "fraction": 0.0, "area_km2": 0.0}
                   for name in ("vegetation", "agricultural_land", "built_up", "water")}
        classes["vegetation"] = {"pixels": int(valid.sum()), "fraction": 1.0,
                                  "area_km2": float(valid.sum() * pixel_area / 1e6)}
        return {
            "distribution": {"classes": classes, "classified_pixels": int(valid.sum()),
                             "unclassified_pixels": int(valid.size - valid.sum()),
                             "classified_fraction": float(valid.mean())},
            "distribution_10class": {}, "dominant_class": "vegetation",
            "n_tiles_classified": 1, "n_tiles_skipped": 0, "edge_pixels_unused": 0,
            "mean_confidence": 0.91, "low_confidence_tile_fraction": 0.0,
        }

    def model_info(self):
        return {"architecture": "test classifier", "trained_on": "synthetic test fixture", "limitations": ["test only"]}


class FakeDataset:
    def __init__(self, arrays, *, crs="EPSG:32643", transform=None, nodata=-9999.0):
        self.arrays = arrays
        self.driver = "GTiff"
        self.width = arrays[0].shape[1]
        self.height = arrays[0].shape[0]
        self.count = len(arrays)
        self.crs = types.SimpleNamespace(to_string=lambda: crs, linear_units="metre") if crs else None
        self.transform = transform or Affine(10, 0, 500000, 0, -10, 2000000)
        self.dtypes = ["float32"] * self.count
        self.nodatavals = [nodata] * self.count
        self.nodata = nodata
        self.bounds = types.SimpleNamespace(left=500000.0, bottom=2000000.0 - self.height * 10,
                                            right=500000.0 + self.width * 10, top=2000000.0)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, index, masked=True):
        data = np.asarray(self.arrays[index - 1], dtype=np.float32)
        mask = data == self.nodatavals[index - 1]
        return np.ma.array(data, mask=mask)


def install_fake_rasterio(monkeypatch, dataset):
    fake = types.ModuleType("rasterio")
    fake.open = lambda *_args, **_kwargs: dataset
    monkeypatch.setitem(sys.modules, "rasterio", fake)


def patch_valid_upload(monkeypatch, uploaded=None, classifier=None):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: metadata())
    monkeypatch.setattr(api_main, "read_uploaded_raster_cube", lambda *_args, **_kwargs: uploaded or cube())
    if classifier is not None:
        monkeypatch.setattr(api_main, "get_classifier", lambda: classifier)


def test_explicit_mapping_controls_logical_cube_order(monkeypatch):
    physical = np.stack([np.full((64, 64), value, dtype=np.float32) for value in (5, 4, 3, 2, 1)])
    install_fake_rasterio(monkeypatch, FakeDataset(physical))
    raster = read_uploaded_raster_cube("ignored.tif", {"B02": 5, "B03": 4, "B04": 3, "B08": 2, "B11": 1}, BANDS, "reflectance")
    assert [float(raster.data[i, 0, 0]) for i in range(5)] == [1, 2, 3, 4, 5]
    captured = {}
    patch_valid_upload(monkeypatch, uploaded=raster,
                       classifier=CaptureClassifier(captured))
    response = post_file({"B02": 5, "B03": 4, "B04": 3, "B08": 2, "B11": 1})
    assert response.status_code == 200
    assert [float(captured["cube"][i, 0, 0]) for i in range(5)] == [1, 2, 3, 4, 5]
    assert response.json()["band_mapping"] == {"B02": 5, "B03": 4, "B04": 3, "B08": 2, "B11": 1}


@pytest.mark.parametrize("mapping", [
    {"B02": 1, "B03": 2, "B04": 3, "B08": 4},
    {"B02": 1, "B03": 1, "B04": 3, "B08": 4, "B11": 5},
    {"B02": 0, "B03": 2, "B04": 3, "B08": 4, "B11": 5},
])
def test_mapping_is_required_unique_and_positive(monkeypatch, mapping):
    patch_valid_upload(monkeypatch)
    response = post_file(mapping)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_band_mapping"


def test_malformed_mapping_and_radiometry_are_rejected(monkeypatch):
    patch_valid_upload(monkeypatch)
    malformed = client.post("/geotiff/land-cover", data={"band_mapping": "not-json", "radiometry": "reflectance"},
                            files={"file": ("upload.tif", b"synthetic", "image/tiff")})
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "invalid_band_mapping"
    unsupported = post_file(radiometry="dn")
    assert unsupported.status_code == 422
    assert unsupported.json()["detail"]["code"] == "unsupported_radiometry"
    missing = client.post("/geotiff/land-cover", data={"band_mapping": json.dumps(MAPPING)},
                          files={"file": ("upload.tif", b"synthetic", "image/tiff")})
    assert missing.status_code == 422


def test_single_or_three_band_file_cannot_satisfy_mapping(monkeypatch):
    monkeypatch.setattr(api_main, "inspect_geotiff", lambda *_args, **_kwargs: metadata(band_count=3))
    monkeypatch.setattr(api_main, "read_uploaded_raster_cube",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            UploadedRasterError("invalid_band_mapping", "A mapped band is not present.")))
    response = post_file()
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_band_mapping"


def test_reader_rejects_missing_crs_rotated_grid_and_incompatible_shapes(monkeypatch):
    arrays = [np.ones((64, 64), dtype=np.float32) for _ in range(5)]
    install_fake_rasterio(monkeypatch, FakeDataset(arrays))
    invalid_index = dict(MAPPING, B11=6)
    with pytest.raises(UploadedRasterError, match="not present"):
        read_uploaded_raster_cube("ignored.tif", invalid_index, BANDS, "reflectance")
    install_fake_rasterio(monkeypatch, FakeDataset(arrays, crs=None))
    with pytest.raises(UploadedRasterError, match="no CRS"):
        read_uploaded_raster_cube("ignored.tif", MAPPING, BANDS, "reflectance")
    install_fake_rasterio(monkeypatch, FakeDataset(arrays, transform=Affine(10, 1, 500000, 0, -10, 2000000)))
    with pytest.raises(UploadedRasterError, match="north-up"):
        read_uploaded_raster_cube("ignored.tif", MAPPING, BANDS, "reflectance")
    incompatible = FakeDataset(arrays)
    incompatible.arrays[4] = np.ones((32, 64), dtype=np.float32)
    install_fake_rasterio(monkeypatch, incompatible)
    with pytest.raises(UploadedRasterError, match="dimensions"):
        read_uploaded_raster_cube("ignored.tif", MAPPING, BANDS, "reflectance")


def test_reader_rejects_pixel_limit_before_reading_bands(monkeypatch):
    arrays = [np.ones((64, 64), dtype=np.float32) for _ in range(5)]
    dataset = FakeDataset(arrays)
    dataset.width, dataset.height = 2001, 2000
    dataset.read = lambda *_args, **_kwargs: pytest.fail("band data must not be allocated/read")
    install_fake_rasterio(monkeypatch, dataset)
    with pytest.raises(UploadedRasterError, match="at most"):
        read_uploaded_raster_cube("ignored.tif", MAPPING, BANDS, "reflectance", max_pixels=4_000_000)


@pytest.mark.parametrize("width,height", [(0, 64), (-1, 64), (64, 0), (64, -1)])
def test_reader_rejects_zero_or_negative_dimensions_before_reading(monkeypatch, width, height):
    arrays = [np.ones((64, 64), dtype=np.float32) for _ in range(5)]
    dataset = FakeDataset(arrays)
    dataset.width, dataset.height = width, height
    dataset.read = lambda *_args, **_kwargs: pytest.fail("band data must not be read")
    install_fake_rasterio(monkeypatch, dataset)
    with pytest.raises(UploadedRasterError, match="dimensions"):
        read_uploaded_raster_cube("ignored.tif", MAPPING, BANDS, "reflectance")


def test_nodata_and_nonfinite_pixels_are_handled(monkeypatch):
    arrays = [np.ones((64, 64), dtype=np.float32) for _ in range(5)]
    arrays[0][0, 0] = np.inf
    install_fake_rasterio(monkeypatch, FakeDataset(arrays))
    with pytest.raises(UploadedRasterError, match="invalid pixel"):
        read_uploaded_raster_cube("ignored.tif", MAPPING, BANDS, "reflectance")
    arrays = [np.ones((64, 64), dtype=np.float32) for _ in range(5)]
    for array in arrays:
        array[0, 0] = -9999
        array[0, 1] = -9999
    install_fake_rasterio(monkeypatch, FakeDataset(arrays))
    raster = read_uploaded_raster_cube("ignored.tif", MAPPING, BANDS, "reflectance")
    assert np.isfinite(raster.data).all(axis=0).sum() == 64 * 64 - 2


def test_insufficient_valid_tile_is_reported(monkeypatch):
    data = np.ones((5, 64, 64), dtype=np.float32)
    data[:, :32, :] = np.nan
    patch_valid_upload(monkeypatch, uploaded=cube(data))
    response = post_file()
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "insufficient_valid_pixels"


def test_real_model_fixture_produces_classification_response():
    data = np.stack([np.full((64, 64), value, dtype=np.float32) for value in (0.1, 0.12, 0.14, 0.3, 0.2)])
    result = run_uploaded_land_cover(data, cube(data), "synthetic-reflectance.tif", get_classifier(), "reflectance")
    assert result["operation"] == "uploaded_land_cover"
    assert result["metrics"]["n_tiles_classified"] == 1
    assert result["model"]["architecture"].startswith("resnet18")
    assert result["evidence"]["radiometry"].startswith("user-declared reflectance")
    assert "Indian landscapes" in " ".join(result["evidence"]["limitations"])
    assert result["confidence"]["combined_score"] is None


def test_mostly_nodata_uploaded_raster_is_refused_before_classification():
    data = np.full((5, 128, 128), np.nan, dtype=np.float32)
    data[:, :64, :64] = 0.2
    with pytest.raises(InsufficientValidPixelsError, match="valid"):
        run_uploaded_land_cover(data, cube(data), "mostly-nodata.tif", get_classifier(), "reflectance")


def test_uploaded_service_rejects_malformed_cube_and_radiometry():
    valid = np.ones((5, 64, 64), dtype=np.float32)
    with pytest.raises(UploadedRasterError, match="radiometry"):
        run_uploaded_land_cover(valid, cube(valid), "upload.tif", get_classifier(), "dn")
    with pytest.raises(UploadedRasterError, match="5, height, width"):
        run_uploaded_land_cover(valid[:3], cube(valid), "upload.tif", get_classifier(), "reflectance")


def test_uploaded_service_rejects_mapping_index_above_raster_band_count():
    valid = np.ones((5, 64, 64), dtype=np.float32)
    raster = cube(valid, mapping=dict(MAPPING, B11=6))
    with pytest.raises(UploadedRasterError, match="not present"):
        run_uploaded_land_cover(valid, raster, "upload.tif", get_classifier(), "reflectance")


def test_temporary_file_is_removed_on_failure(monkeypatch):
    removed = []
    original_unlink = api_main.os.unlink
    monkeypatch.setattr(api_main.os, "unlink", lambda path: (removed.append(path), original_unlink(path))[1])
    response = client.post("/geotiff/land-cover", data={"band_mapping": json.dumps(MAPPING), "radiometry": "reflectance"},
                           files={"file": ("bad.tif", b"not-a-tiff", "image/tiff")})
    assert response.status_code == 422
    assert removed and all(not Path(path).exists() for path in removed)


def test_real_synthetic_geotiff_endpoint_when_rasterio_is_available():
    try:
        import rasterio
        from rasterio.transform import from_origin
    except Exception as exc:
        pytest.skip(f"rasterio cannot load in this environment: {exc}")
    with tempfile.TemporaryDirectory(prefix="satquery-landcover-test-") as directory:
        path = Path(directory) / "synthetic.tif"
        data = np.stack([np.full((64, 64), value, dtype=np.float32) for value in (0.1, 0.12, 0.14, 0.3, 0.2)])
        with rasterio.open(path, "w", driver="GTiff", width=64, height=64, count=5, dtype="float32",
                           crs="EPSG:32643", transform=from_origin(500000, 2000000, 10, 10), nodata=-9999.0) as dst:
            dst.write(data)
        response = client.post(
            "/geotiff/land-cover",
            data={"band_mapping": json.dumps(MAPPING), "radiometry": "reflectance"},
            files={"file": (path.name, path.read_bytes(), "image/tiff")},
        )
        assert response.status_code == 200
        assert response.json()["metrics"]["n_tiles_classified"] == 1
