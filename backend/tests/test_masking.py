import numpy as np
import pytest
from shapely.geometry import box
from affine import Affine
from app.core.errors import InvalidAOIError
from app.preprocessing.masking import (aoi_mask, build_valid_mask, resample_to_shape, scl_valid_mask,
                                       to_reflectance, validate_aoi_geojson)


def test_cloud_masking_exact_valid_fraction():
    scl = np.full((10, 10), 4)
    scl[:2, :] = 9          # 20 cloud pixels
    assert scl_valid_mask(scl).mean() == pytest.approx(0.8)


@pytest.mark.parametrize("code", [0, 1, 3, 8, 9, 10, 11])
def test_invalid_scl_classes(code):
    assert not scl_valid_mask(np.array([code]))[0]


def test_reflectance_nodata_becomes_nan():
    out = to_reflectance(np.array([0, 5000]), scale=1e-4, offset=0.0, nodata=0)
    assert np.isnan(out[0]) and out[1] == pytest.approx(0.5)


def test_resample_shapes_and_categorical_values():
    assert resample_to_shape(np.random.rand(5, 5), (10, 10)).shape == (10, 10)
    scl = np.array([[4, 9], [4, 9]], dtype=np.uint8)
    assert set(np.unique(resample_to_shape(scl, (4, 4), categorical=True))) == {4, 9}


def test_aoi_clipping_half():
    tf = Affine(10, 0, 0, 0, -10, 100)
    inside = aoi_mask((10, 10), tf, box(0, 0, 50, 100))
    assert inside.sum() == 50


def test_build_valid_mask_combines_everything():
    scl = np.full((2, 2), 4)
    inside = np.array([[True, True], [False, True]])
    band = np.array([[1.0, np.nan], [1.0, 1.0]])
    assert build_valid_mask(scl, inside, [band]).sum() == 2


@pytest.mark.parametrize("bad", [
    {"type": "Point", "coordinates": [78, 17]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]},   # bow-tie
    {"type": "Polygon", "coordinates": [[[300, 0], [301, 0], [301, 1], [300, 1], [300, 0]]]},
    {"type": "Nonsense"},
    {},
])
def test_invalid_aoi_rejected(bad):
    with pytest.raises(InvalidAOIError):
        validate_aoi_geojson(bad)
