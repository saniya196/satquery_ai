import io
import struct
from app.satellite.geotiff import inspect_geotiff


def create_minimal_tiff(width=512, height=512, bands=1, epsg=32643) -> bytes:
    """Constructs a valid in-memory TIFF byte stream with tags."""
    endian = "<"
    header = b"II" + struct.pack(f"{endian}HI", 42, 8)
    
    # IFD entries:
    # 256: ImageWidth (LONG)
    # 257: ImageLength (LONG)
    # 258: BitsPerSample (SHORT, 16)
    # 277: SamplesPerPixel (SHORT)
    # 33550: ModelPixelScaleTag (DOUBLE, 10.0, 10.0, 0.0)
    entries = [
        (256, 4, 1, width),
        (257, 4, 1, height),
        (258, 3, 1, 16),
        (277, 3, 1, bands),
    ]
    
    num_entries = len(entries)
    ifd_bytes = struct.pack(f"{endian}H", num_entries)
    for tag, val_type, count, val in entries:
        ifd_bytes += struct.pack(f"{endian}HHI I", tag, val_type, count, val)
    ifd_bytes += struct.pack(f"{endian}I", 0)  # Next IFD offset
    
    return header + ifd_bytes


def test_inspect_geotiff_valid():
    raw_data = create_minimal_tiff(width=1024, height=768, bands=4)
    stream = io.BytesIO(raw_data)
    meta = inspect_geotiff(stream, filename="S2A_MSIL2A_B04.tif")
    
    assert meta.is_valid_geotiff is True
    assert meta.width == 1024
    assert meta.height == 768
    assert meta.band_count == 4
    assert "B04 (Red - 10m)" in meta.bands_detected
    assert meta.format == "GeoTIFF"


def test_inspect_geotiff_invalid_magic():
    bad_stream = io.BytesIO(b"NOT_A_TIFF_FILE_HEADER")
    meta = inspect_geotiff(bad_stream, filename="bad.tif")
    assert meta.is_valid_geotiff is False
    assert len(meta.errors) > 0


def test_inspect_geotiff_sar_detection():
    raw_data = create_minimal_tiff(width=512, height=512, bands=1)
    stream = io.BytesIO(raw_data)
    meta = inspect_geotiff(stream, filename="S1A_IW_GRDH_1SDV_VV.tif")
    assert meta.is_valid_geotiff is True
    assert any("VV (SAR" in b for b in meta.bands_detected)
