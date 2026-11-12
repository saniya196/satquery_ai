import numpy as np
import pytest
from affine import Affine
from rasterio.warp import transform_bounds

from app.change_detection.align import align_to_grid, grids_compatible
from app.satellite.provider import reproject_array_to_grid
from app.preprocessing.masking import build_valid_mask


CRS_UTM = "EPSG:32644"


def test_grids_compatible_requires_same_crs_transform_and_shape():
    tf = Affine(10, 0, 500000, 0, -10, 4000000)
    shape = (3, 3)
    assert grids_compatible(tf, CRS_UTM, shape, tf, CRS_UTM, shape)
    assert not grids_compatible(tf, CRS_UTM, shape, Affine(10, 0, 500010, 0, -10, 4000000), CRS_UTM, shape)
    assert not grids_compatible(tf, CRS_UTM, shape, tf, "EPSG:32643", shape)
    assert not grids_compatible(tf, CRS_UTM, shape, tf, CRS_UTM, (2, 3))


def test_identical_grid_returns_independent_copy():
    tf = Affine(10, 0, 500000, 0, -10, 4000000)
    arr = np.arange(9, dtype=np.float32).reshape(3, 3)
    out = align_to_grid(arr, tf, CRS_UTM, arr.shape, tf, CRS_UTM, arr.shape)
    np.testing.assert_array_equal(out, arr)
    assert out is not arr


def test_same_shape_shifted_origin_is_geospatially_warped():
    src_tf = Affine(10, 0, 500000, 0, -10, 4000000)
    dst_tf = Affine(10, 0, 500010, 0, -10, 4000000)
    src = np.arange(1, 10, dtype=np.float32).reshape(3, 3)

    out = align_to_grid(src, src_tf, CRS_UTM, src.shape, dst_tf, CRS_UTM, src.shape)

    assert out.shape == src.shape
    np.testing.assert_array_equal(out[:, :2], src[:, 1:])
    assert np.isnan(out[:, 2]).all()
    assert not np.array_equal(out, src, equal_nan=True)


def test_different_resolution_is_warped_to_destination_grid():
    src_tf = Affine(10, 0, 0, 0, -10, 40)
    dst_tf = Affine(20, 0, 0, 0, -20, 40)
    src = np.arange(16, dtype=np.float32).reshape(4, 4)

    out = align_to_grid(src, src_tf, CRS_UTM, src.shape, dst_tf, CRS_UTM, (2, 2))

    assert out.shape == (2, 2)
    np.testing.assert_allclose(out, [[2.5, 4.5], [10.5, 12.5]], atol=1e-5)


def test_different_crs_is_warped_to_destination_grid():
    src_tf = Affine(10, 0, 500000, 0, -10, 4000000)
    bounds = transform_bounds(CRS_UTM, "EPSG:4326", 500000, 3999960, 500040, 4000000)
    west, south, east, north = bounds
    dst_tf = Affine((east - west) / 4, 0, west, 0, -(north - south) / 4, north)
    src = np.arange(16, dtype=np.float32).reshape(4, 4)

    out = align_to_grid(src, src_tf, CRS_UTM, src.shape, dst_tf, "EPSG:4326", (4, 4))

    assert out.shape == (4, 4)
    assert np.isfinite(out).any()
    assert np.nanmin(out) >= src.min() and np.nanmax(out) <= src.max()


def test_reprojection_failure_raises_actionable_error(monkeypatch):
    import rasterio.warp

    def fail_warp(*_args, **_kwargs):
        raise RuntimeError("synthetic warp failure")

    monkeypatch.setattr(rasterio.warp, "reproject", fail_warp)
    tf1 = Affine(10, 0, 500000, 0, -10, 4000000)
    tf2 = Affine(10, 0, 500010, 0, -10, 4000000)
    src = np.ones((2, 2), dtype=np.float32)

    with pytest.raises(ValueError, match="Geospatial reprojection failed"):
        align_to_grid(src, tf1, CRS_UTM, src.shape, tf2, CRS_UTM, src.shape)


def test_partial_overlap_and_source_nodata_are_preserved():
    src_tf = Affine(10, 0, 500000, 0, -10, 4000000)
    dst_tf = Affine(10, 0, 500020, 0, -10, 4000000)
    src = np.arange(1, 10, dtype=np.float32).reshape(3, 3)
    src[1, 2] = np.nan

    out = align_to_grid(src, src_tf, CRS_UTM, src.shape, dst_tf, CRS_UTM, src.shape)

    np.testing.assert_array_equal(out[:, 0], src[:, 2])
    assert np.isnan(out[1, 0])
    assert np.isnan(out[:, 1:]).all()


def test_categorical_alignment_uses_nearest_and_zero_for_outside_source():
    src_tf = Affine(10, 0, 500000, 0, -10, 4000000)
    dst_tf = Affine(10, 0, 500010, 0, -10, 4000000)
    src = np.array([[4, 9], [4, 4]], dtype=np.uint8)

    out = align_to_grid(src, src_tf, CRS_UTM, src.shape, dst_tf, CRS_UTM, src.shape, categorical=True)

    np.testing.assert_array_equal(out[:, 0], src[:, 1])
    np.testing.assert_array_equal(out[:, 1], [0, 0])


def test_scene_band_reprojection_uses_explicit_20m_to_10m_grids():
    # Synthetic unit fixture: CRS and affine coordinates, not shape ratios,
    # determine where each 20 m source value lands on the 10 m target grid.
    src_tf = Affine(20, 0, 500000, 0, -20, 400000)
    dst_tf = Affine(10, 0, 500000, 0, -10, 400000)
    source = np.full((2, 2), 0.25, dtype=np.float32)
    out = reproject_array_to_grid(source, src_tf, CRS_UTM, dst_tf, CRS_UTM, (4, 4))

    assert out.shape == (4, 4)
    assert np.isfinite(out).all()
    np.testing.assert_allclose(out, 0.25, atol=1e-6)


def test_scene_band_reprojection_accounts_for_transform_shift_and_partial_overlap():
    src_tf = Affine(10, 0, 500000, 0, -10, 400000)
    dst_tf = Affine(10, 0, 500010, 0, -10, 400000)
    source = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)

    out = reproject_array_to_grid(source, src_tf, CRS_UTM, dst_tf, CRS_UTM, source.shape)

    np.testing.assert_array_equal(out[:, :2], source[:, 1:])
    assert np.isnan(out[:, 2]).all()


def test_scene_band_reprojection_handles_different_crs():
    src_tf = Affine(10, 0, 500000, 0, -10, 4000000)
    bounds = transform_bounds(CRS_UTM, "EPSG:4326", 500000, 3999960, 500040, 4000000)
    west, south, east, north = bounds
    dst_tf = Affine((east - west) / 4, 0, west, 0, -(north - south) / 4, north)
    source = np.full((4, 4), 0.2, dtype=np.float32)

    out = reproject_array_to_grid(source, src_tf, CRS_UTM, dst_tf, "EPSG:4326", (4, 4))

    assert out.shape == (4, 4)
    assert np.isfinite(out).any()
    np.testing.assert_allclose(out[np.isfinite(out)], 0.2, atol=1e-5)


def test_scene_band_reprojection_preserves_nodata_boundaries_and_coverage():
    src_tf = Affine(10, 0, 500000, 0, -10, 400000)
    source = np.full((3, 3), 0.2, dtype=np.float32)
    source[1, 1] = np.nan

    out = reproject_array_to_grid(source, src_tf, CRS_UTM, src_tf, CRS_UTM, source.shape)

    assert np.isnan(out[1, 1])
    assert np.isfinite(out).sum() == 8
    mask = build_valid_mask(np.full((3, 3), 5, dtype=np.uint8), bands=[out])
    assert mask.sum() == 8


def test_scene_scl_reprojection_uses_nearest_neighbour_and_keeps_nodata():
    src_tf = Affine(20, 0, 500000, 0, -20, 400000)
    dst_tf = Affine(10, 0, 500000, 0, -10, 400000)
    source = np.array([[4, 9], [5, 0]], dtype=np.uint8)

    out = reproject_array_to_grid(source, src_tf, CRS_UTM, dst_tf, CRS_UTM, (4, 4), categorical=True)

    assert out.shape == (4, 4)
    assert set(np.unique(out)).issubset({0, 4, 5, 9})
    assert np.any(out == 0)
    assert not np.any((out != 0) & ~np.isin(out, source))
