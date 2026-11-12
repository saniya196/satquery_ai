"""Grid compatibility and safe raster alignment for change detection."""
from typing import Tuple

import numpy as np
from affine import Affine


def _affine_approx_equal(tf1: Affine, tf2: Affine, atol: float = 1e-9) -> bool:
    return all(
        abs(left - right) < atol
        for left, right in zip(tf1[:6], tf2[:6])
    )


def grids_compatible(sa_transform, sa_crs, sa_shape,
                     sb_transform, sb_crs, sb_shape) -> bool:
    """True only when CRS, complete affine transform, and array shape agree."""
    return (
        sa_crs == sb_crs
        and tuple(sa_shape) == tuple(sb_shape)
        and _affine_approx_equal(sa_transform, sb_transform)
    )


def align_to_grid(src_arr: np.ndarray, src_tf: Affine, src_crs: str, src_shape: Tuple[int, int],
                  dst_tf: Affine, dst_crs: str, dst_shape: Tuple[int, int],
                  categorical: bool = False) -> np.ndarray:
    """Warp ``src_arr`` to the destination grid or fail without guessing.

    An array shape match is not evidence of geospatial alignment. All
    mismatched grids are warped by the provider's rasterio-backed helper,
    which keeps rasterio imports within ``satellite/provider.py``.
    """
    src = np.asarray(src_arr)
    if src.ndim != 2 or tuple(src.shape) != tuple(src_shape):
        raise ValueError("Source shape metadata does not match the 2D source array.")
    if len(dst_shape) != 2 or any(int(size) <= 0 for size in dst_shape):
        raise ValueError("Destination shape must contain two positive dimensions.")
    if grids_compatible(src_tf, src_crs, src_shape, dst_tf, dst_crs, dst_shape):
        return src.copy()

    source_pixel_area = abs(src_tf.a * src_tf.e - src_tf.b * src_tf.d)
    destination_pixel_area = abs(dst_tf.a * dst_tf.e - dst_tf.b * dst_tf.d)
    area_average = (
        not categorical
        and src_crs == dst_crs
        and destination_pixel_area > source_pixel_area * (1.0 + 1e-9)
    )

    from app.satellite.provider import reproject_array_to_grid

    return reproject_array_to_grid(
        src,
        src_tf,
        src_crs,
        dst_tf,
        dst_crs,
        tuple(dst_shape),
        categorical=categorical,
        area_average=area_average,
    )
