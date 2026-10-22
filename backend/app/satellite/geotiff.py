"""GeoTIFF inspection module for SatQuery AI.
Parses TIFF/GeoTIFF metadata directly using standard library struct to avoid heavy compilation issues.
Handles large files by reading only the header and IFD structures.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Optional


@dataclass
class GeoTIFFMetadata:
    filename: str
    is_valid_geotiff: bool
    format: str = "GeoTIFF"
    width: int = 0
    height: int = 0
    band_count: int = 1
    bits_per_sample: list[int] = field(default_factory=lambda: [16])
    data_type: str = "uint16"
    crs: Optional[str] = None
    epsg_code: Optional[int] = None
    resolution_m: Optional[float] = None
    nodata: Optional[float] = None
    bounds: Optional[list[float]] = None
    bands_detected: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    file_size_bytes: int = 0


def _read_tag_value(f: BinaryIO, endian: str, val_type: int, count: int, offset_or_val: int) -> Any:
    # Type sizes in TIFF:
    # 1: BYTE, 2: ASCII, 3: SHORT (2 bytes), 4: LONG (4 bytes), 5: RATIONAL (8 bytes), 12: DOUBLE (8 bytes)
    type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 12: 8}
    size = type_sizes.get(val_type, 1) * count

    if size <= 4:
        # Value is packed inside offset_or_val
        val_bytes = struct.pack(f"{endian}I", offset_or_val)[:size]
        if val_type == 3:  # SHORT
            vals = struct.unpack(f"{endian}{count}H", val_bytes)
            return vals[0] if count == 1 else list(vals)
        elif val_type == 4:  # LONG
            vals = struct.unpack(f"{endian}{count}I", val_bytes)
            return vals[0] if count == 1 else list(vals)
        elif val_type == 1:  # BYTE
            return val_bytes[0] if count == 1 else list(val_bytes)
        return offset_or_val
    else:
        # Value is at file offset
        saved_pos = f.tell()
        f.seek(offset_or_val)
        raw = f.read(size)
        f.seek(saved_pos)
        if val_type == 2:  # ASCII
            return raw.decode("latin1", errors="replace").rstrip("\x00")
        elif val_type == 3:  # SHORT
            vals = struct.unpack(f"{endian}{count}H", raw)
            return vals[0] if count == 1 else list(vals)
        elif val_type == 4:  # LONG
            vals = struct.unpack(f"{endian}{count}I", raw)
            return vals[0] if count == 1 else list(vals)
        elif val_type == 12:  # DOUBLE
            vals = struct.unpack(f"{endian}{count}d", raw)
            return vals[0] if count == 1 else list(vals)
        elif val_type == 5:  # RATIONAL (num / den)
            vals = struct.unpack(f"{endian}{count * 2}I", raw)
            rationals = [vals[i] / vals[i + 1] if vals[i + 1] != 0 else 0.0 for i in range(0, len(vals), 2)]
            return rationals[0] if count == 1 else rationals
        return raw


def inspect_geotiff(filepath_or_stream: str | BinaryIO, filename: str = "") -> GeoTIFFMetadata:
    """Inspects a GeoTIFF raster file or stream and extracts projection, resolution, dimensions, and bands."""
    if isinstance(filepath_or_stream, str):
        if not os.path.exists(filepath_or_stream):
            return GeoTIFFMetadata(filename=filename or filepath_or_stream, is_valid_geotiff=False, errors=["File not found"])
        size_bytes = os.path.getsize(filepath_or_stream)
        fname = filename or os.path.basename(filepath_or_stream)
        with open(filepath_or_stream, "rb") as f:
            return _parse_tiff_stream(f, fname, size_bytes)
    else:
        saved_pos = filepath_or_stream.tell()
        filepath_or_stream.seek(0, os.SEEK_END)
        size_bytes = filepath_or_stream.tell()
        filepath_or_stream.seek(0)
        res = _parse_tiff_stream(filepath_or_stream, filename or "uploaded.tif", size_bytes)
        filepath_or_stream.seek(saved_pos)
        return res


def _parse_tiff_stream(f: BinaryIO, filename: str, size_bytes: int) -> GeoTIFFMetadata:
    header = f.read(8)
    if len(header) < 8:
        return GeoTIFFMetadata(filename=filename, is_valid_geotiff=False, errors=["File too small to be a valid TIFF"], file_size_bytes=size_bytes)

    if header[:2] == b"II":
        endian = "<"
    elif header[:2] == b"MM":
        endian = ">"
    else:
        return GeoTIFFMetadata(filename=filename, is_valid_geotiff=False, errors=["Not a TIFF file (invalid magic bytes)"], file_size_bytes=size_bytes)

    magic = struct.unpack(f"{endian}H", header[2:4])[0]
    if magic != 42 and magic != 43:  # 42 = Classic TIFF, 43 = BigTIFF
        return GeoTIFFMetadata(filename=filename, is_valid_geotiff=False, errors=["Invalid TIFF version identifier"], file_size_bytes=size_bytes)

    first_ifd_offset = struct.unpack(f"{endian}I", header[4:8])[0]
    if first_ifd_offset >= size_bytes:
        return GeoTIFFMetadata(filename=filename, is_valid_geotiff=False, errors=["Corrupt TIFF header offset"], file_size_bytes=size_bytes)

    f.seek(first_ifd_offset)
    num_entries_raw = f.read(2)
    if len(num_entries_raw) < 2:
        return GeoTIFFMetadata(filename=filename, is_valid_geotiff=False, errors=["Truncated IFD table"], file_size_bytes=size_bytes)

    num_entries = struct.unpack(f"{endian}H", num_entries_raw)[0]
    tags: dict[int, Any] = {}

    for _ in range(num_entries):
        entry_raw = f.read(12)
        if len(entry_raw) < 12:
            break
        tag, val_type, count, offset_val = struct.unpack(f"{endian}HHI I", entry_raw)
        try:
            val = _read_tag_value(f, endian, val_type, count, offset_val)
            tags[tag] = val
        except Exception:
            continue

    width = tags.get(256)  # ImageWidth
    height = tags.get(257)  # ImageLength
    bands = tags.get(277, 1)  # SamplesPerPixel
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return GeoTIFFMetadata(filename=filename, is_valid_geotiff=False,
                                errors=["TIFF is missing valid image dimensions"], file_size_bytes=size_bytes)
    bits = tags.get(258, [16])
    if isinstance(bits, int):
        bits = [bits]

    # Sample format (1=uint, 2=int, 3=float)
    sample_fmt = tags.get(339, 1)
    data_type = "uint16" if 16 in bits else "float32" if sample_fmt == 3 else "uint8"

    # GeoTIFF Pixel Scale Tag (33550: ScaleX, ScaleY, ScaleZ)
    scale = tags.get(33550)
    resolution = None
    if isinstance(scale, (list, tuple)) and len(scale) >= 2:
        resolution = float(scale[0]) if scale[0] > 0 else None

    # GeoKeyDirectoryTag (34735)
    geo_keys = tags.get(34735)
    epsg_code = None
    crs_desc = None

    if isinstance(geo_keys, list) and len(geo_keys) >= 4:
        # GeoKeyDirectory header: [KeyDirectoryVersion, KeyRevision, MinorRevision, NumberOfKeys]
        num_keys = geo_keys[3]
        for i in range(1, num_keys + 1):
            idx = i * 4
            if idx + 3 < len(geo_keys):
                key_id = geo_keys[idx]
                val_offset = geo_keys[idx + 3]
                if key_id == 3072:  # ProjectedCSTypeGeoKey
                    epsg_code = val_offset
                    crs_desc = f"EPSG:{epsg_code} (Projected UTM)"
                elif key_id == 2048:  # GeographicTypeGeoKey
                    if epsg_code is None:
                        epsg_code = val_offset
                        crs_desc = f"EPSG:{epsg_code} (Geographic WGS 84)"

    # Infer bands based on filename and band count
    lower_name = filename.lower()
    detected_bands = []
    if "b02" in lower_name or "blue" in lower_name:
        detected_bands.append("B02 (Blue - 10m)")
    if "b03" in lower_name or "green" in lower_name:
        detected_bands.append("B03 (Green - 10m)")
    if "b04" in lower_name or "red" in lower_name:
        detected_bands.append("B04 (Red - 10m)")
    if "b08" in lower_name or "nir" in lower_name:
        detected_bands.append("B08 (NIR - 10m)")
    if "b11" in lower_name or "swir" in lower_name:
        detected_bands.append("B11 (SWIR1 - 20m)")
    if "vv" in lower_name:
        detected_bands.append("VV (SAR C-Band)")
    if "vh" in lower_name:
        detected_bands.append("VH (SAR C-Band)")

    if not detected_bands:
        if bands == 1:
            detected_bands = ["Band 1 (Single Band / Grayscale)"]
        elif bands == 3:
            detected_bands = ["B04 (Red)", "B03 (Green)", "B02 (Blue)"]
        elif bands >= 4:
            detected_bands = ["B02 (Blue)", "B03 (Green)", "B04 (Red)", "B08 (NIR)"]

    nodata = tags.get(42113)
    if isinstance(nodata, str):
        try:
            nodata = float(nodata.strip())
        except ValueError:
            nodata = None
    elif isinstance(nodata, (int, float)):
        nodata = float(nodata)
    else:
        nodata = None

    return GeoTIFFMetadata(
        filename=filename,
        is_valid_geotiff=True,
        format="GeoTIFF",
        width=int(width),
        height=int(height),
        band_count=int(bands),
        bits_per_sample=list(bits),
        data_type=data_type,
        crs=crs_desc,
        epsg_code=epsg_code,
        resolution_m=resolution,
        nodata=nodata,
        bands_detected=detected_bands,
        file_size_bytes=size_bytes,
    )
