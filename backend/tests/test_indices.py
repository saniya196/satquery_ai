import numpy as np
import pytest
from app.core.errors import MissingBandError
from app.indices.spectral import compute_index, index_stats, ndbi, ndvi, ndwi, savi


def test_ndvi_hand_value():
    assert ndvi(np.array([0.5]), np.array([0.1]))[0] == pytest.approx(0.4 / 0.6)


def test_ndwi_ndbi_savi_hand_values():
    assert ndwi(np.array([0.3]), np.array([0.1]))[0] == pytest.approx(0.5)
    assert ndbi(np.array([0.4]), np.array([0.2]))[0] == pytest.approx(1 / 3)
    assert savi(np.array([0.5]), np.array([0.1]))[0] == pytest.approx(0.4 / 1.1 * 1.5)


def test_divide_by_zero_is_nan_not_zero():
    out = ndvi(np.array([0.0, 0.5]), np.array([0.0, 0.1]))
    assert np.isnan(out[0]) and np.isfinite(out[1])


def test_missing_band_raises():
    with pytest.raises(MissingBandError):
        compute_index("NDWI", {"nir": np.ones((2, 2))})


def test_valid_mask_applied_and_stats_ignore_nan():
    bands = {"nir": np.full((2, 2), 0.5), "red": np.full((2, 2), 0.1)}
    valid = np.array([[True, True], [True, False]])
    arr = compute_index("NDVI", bands, valid)
    s = index_stats(arr, vegetation_threshold=0.3)
    assert s["n_valid"] == 3 and s["valid_fraction"] == 0.75
    assert s["mean"] == pytest.approx(0.4 / 0.6) and s["coverage_fraction"] == 1.0
