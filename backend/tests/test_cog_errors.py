"""Tests for COG/raster read error handling (P0.4)."""
from unittest.mock import MagicMock, patch

import pytest

from app.core.errors import NoImageryError
from app.satellite.provider import EarthSearchProvider


AOI = {"type": "Polygon", "coordinates": [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]]}


def _provider_with_item():
    p = EarthSearchProvider(cache_dir="./.test_cache")
    item = MagicMock()
    item.id = "S2_TEST"
    item.datetime = MagicMock()
    item.datetime.isoformat.return_value = "2026-01-01T00:00:00Z"
    item.properties = {"eo:cloud_cover": 10}
    asset = MagicMock()
    asset.href = "https://example.com/data.tif?token=secret123&sig=abc"
    asset.extra_fields = {"raster:bands": [{"scale": 0.0001, "offset": 0, "nodata": 0}]}
    item.assets = {"nir": asset, "red": asset, "green": asset, "blue": asset, "scl": asset}
    p._items["S2_TEST"] = item
    return p


class TestCogErrorMapping:
    def test_timeout_error_message(self):
        p = _provider_with_item()
        with patch("rasterio.open", side_effect=Exception("CPL_HTTP timeout timed out")):
            with pytest.raises(NoImageryError) as exc:
                p.get_scene(AOI, "S2_TEST", ["nir"])
            msg = str(exc.value.message)
            assert "timeout" in msg.lower()
            assert "not necessarily retryable" in msg.lower()
            assert "token=secret123" not in msg
            assert "sig=abc" not in msg

    def test_connection_error_message(self):
        p = _provider_with_item()
        with patch("rasterio.open", side_effect=Exception("failed to connect to network")):
            with pytest.raises(NoImageryError) as exc:
                p.get_scene(AOI, "S2_TEST", ["nir"])
            msg = str(exc.value.message)
            assert "connection" in msg.lower() or "network" in msg.lower()
            assert "token=secret123" not in msg

    def test_missing_asset_404(self):
        p = _provider_with_item()
        with patch("rasterio.open", side_effect=Exception("HTTP error 404 not found")):
            with pytest.raises(NoImageryError) as exc:
                p.get_scene(AOI, "S2_TEST", ["nir"])
            msg = str(exc.value.message)
            assert "missing" in msg.lower() or "unavailable" in msg.lower()
            assert "token=secret123" not in msg

    def test_rasterio_io_error(self):
        p = _provider_with_item()
        class RasterioIOError(Exception):
            pass
        with patch("rasterio.open", side_effect=RasterioIOError("rasterio.io error")):
            with pytest.raises(NoImageryError) as exc:
                p.get_scene(AOI, "S2_TEST", ["nir"])
            msg = str(exc.value.message)
            assert "unreadable" in msg.lower() or "invalid" in msg.lower()
            assert "token=secret123" not in msg

    def test_unavailable_band(self):
        p = EarthSearchProvider(cache_dir="./.test_cache")
        item = MagicMock()
        item.id = "S2_TEST"
        # Only request the missing band to avoid triggering read of other bands
        item.assets = {"nir": MagicMock()}
        p._items["S2_TEST"] = item
        from app.core.errors import MissingBandError
        with pytest.raises(MissingBandError) as exc:
            p.get_scene(AOI, "S2_TEST", ["red"])
        msg = str(exc.value.message) if hasattr(exc.value, 'message') else str(exc.value)
        assert "not available" in msg.lower() or "band" in msg.lower()

    def test_aoi_not_covered_message(self):
        # This is tested via processing path; easier to check best_scene partial coverage message
        from app.satellite.provider import SatelliteProvider
        class MockProv(SatelliteProvider):
            def list_scenes(self, aoi, start, end, max_cloud):
                return [{"item_id":"s1","datetime":"2026-01-01","cloud_cover":5,"coverage":0.5}]
            def get_scene(self, aoi, item_id, bands):
                raise NotImplementedError()
        with pytest.raises(NoImageryError) as exc:
            MockProv().best_scene(AOI, __import__('datetime').date(2026,1,1), __import__('datetime').date(2026,1,31), 40)
        assert "coverage" in str(exc.value).lower()
