"""Deterministic, dependency-free RGBA and PNG rendering for analysis rasters."""
import struct
import zlib

import numpy as np

_INDEX_RANGE = (-1.0, 1.0)
_DIFF_RANGE = (-2.0, 2.0)

_INDEX_STOPS = ((0.0, (140, 81, 10)), (1.0, (26, 152, 80)))
_DIFF_STOPS = ((0.0, (215, 48, 39)), (0.5, (255, 255, 255)), (1.0, (26, 152, 80)))
_CLASS_COLORS = {
    -2: ("significant decrease", (178, 24, 43)),
    -1: ("moderate decrease", (239, 138, 98)),
    0: ("stable", (247, 247, 247)),
    1: ("moderate increase", (103, 169, 207)),
    2: ("significant increase", (26, 152, 80)),
}
_LANDCOVER_COLORS = {
    0: ("vegetation", (46, 139, 87)),
    1: ("agricultural_land", (230, 171, 2)),
    2: ("built_up", (217, 95, 2)),
    3: ("water", (31, 120, 180)),
}
_HOTSPOT_COLOR = (255, 0, 0)


def _interpolate(values: np.ndarray, value_range: tuple[float, float],
                 stops: tuple[tuple[float, tuple[int, int, int]], ...]) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    low, high = value_range
    values = np.where(np.isfinite(values), values, low)
    position = np.clip((values - low) / (high - low), 0.0, 1.0)
    rgb = np.empty(values.shape + (3,), dtype=np.uint8)
    for channel in range(3):
        rgb[..., channel] = np.rint(np.interp(
            position,
            [stop[0] for stop in stops],
            [stop[1][channel] for stop in stops],
        )).astype(np.uint8)
    return rgb


def colorize_index(values: np.ndarray) -> np.ndarray:
    """Map [-1, 1] linearly from brown (#8c510a) to green (#1a9850)."""
    values = np.asarray(values)
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    valid = np.isfinite(values)
    rgba[..., :3] = np.where(valid[..., np.newaxis], _interpolate(values, _INDEX_RANGE, _INDEX_STOPS), 0)
    rgba[..., 3] = valid.astype(np.uint8) * 255
    return rgba


def colorize_diff(values: np.ndarray) -> np.ndarray:
    """Map [-2, 0, 2] from red (#d73027), through white, to green (#1a9850)."""
    values = np.asarray(values)
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    valid = np.isfinite(values)
    rgba[..., :3] = np.where(valid[..., np.newaxis], _interpolate(values, _DIFF_RANGE, _DIFF_STOPS), 0)
    rgba[..., 3] = valid.astype(np.uint8) * 255
    return rgba


def colorize_classes(values: np.ndarray) -> np.ndarray:
    """Map change codes -2..2 to class colours; all other codes are transparent."""
    values = np.asarray(values)
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    for code, (_, color) in _CLASS_COLORS.items():
        matched = values == code
        rgba[matched, :3] = color
        rgba[matched, 3] = 255
    return rgba


def colorize_hotspots(values: np.ndarray) -> np.ndarray:
    """Render selected hotspot pixels solid red and every other pixel transparent."""
    values = np.asarray(values)
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    valid = np.isfinite(values)
    mask = valid & (values != 0)
    rgba[mask, :3] = _HOTSPOT_COLOR
    rgba[mask, 3] = 255
    return rgba


def colorize_landcover(values: np.ndarray) -> np.ndarray:
    """Map product codes to vegetation, agriculture, built-up, and water colours."""
    values = np.asarray(values)
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    for code, (_, color) in _LANDCOVER_COLORS.items():
        matched = values == code
        rgba[matched, :3] = color
        rgba[matched, 3] = 255
    return rgba


def encode_png(rgba: np.ndarray) -> bytes:
    """Encode an HxWx4 uint8 array as a PNG without image-library dependencies."""
    image = np.asarray(rgba)
    if image.ndim != 3 or image.shape[2] != 4 or image.dtype != np.uint8:
        raise ValueError("PNG input must be an HxWx4 uint8 array.")

    height, width, _ = image.shape
    scanlines = b"".join(b"\x00" + row.tobytes() for row in image)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b"")


def legend_for(layer: str) -> dict:
    """Return the exact ranges and colour stops used by each renderer."""
    if layer == "index":
        return {
            "value_range": list(_INDEX_RANGE),
            "colors": [
                {"value": -1.0, "hex": "#8c510a"},
                {"value": 1.0, "hex": "#1a9850"},
            ],
        }
    if layer == "diff":
        return {
            "value_range": list(_DIFF_RANGE),
            "colors": [
                {"value": -2.0, "hex": "#d73027"},
                {"value": 0.0, "hex": "#ffffff"},
                {"value": 2.0, "hex": "#1a9850"},
            ],
        }
    if layer == "classes":
        return {
            "value_range": [-2, 2],
            "colors": [
                {"value": code, "label": label, "hex": "#{:02x}{:02x}{:02x}".format(*color)}
                for code, (label, color) in _CLASS_COLORS.items()
            ],
        }
    if layer == "hotspots":
        return {
            "value_range": [0, 1],
            "colors": [{"value": 1, "label": "Detected hotspot", "hex": "#ff0000"}],
        }
    if layer == "landcover":
        return {
            "value_range": [0, 3],
            "colors": [
                {"value": code, "label": label,
                 "hex": "#{:02x}{:02x}{:02x}".format(*color)}
                for code, (label, color) in _LANDCOVER_COLORS.items()
            ],
        }
    raise KeyError(layer)
