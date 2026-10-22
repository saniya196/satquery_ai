"""Pure-Python UTM -> WGS84 (lon/lat). No pyproj, so it runs where compiled GIS libs are blocked.

Kruger series (Karney 2011), accurate to well under a millimetre inside a UTM zone.
Sentinel-2 L2A tiles are in EPSG:326xx (UTM north) or EPSG:327xx (UTM south).
"""
import math

_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996
_N = _F / (2 - _F)
_AA = _A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64)
_BETA = (
    _N / 2 - 2 * _N**2 / 3 + 37 * _N**3 / 96 - _N**4 / 360,
    _N**2 / 48 + _N**3 / 15 - 437 * _N**4 / 1440,
    17 * _N**3 / 480 - 37 * _N**4 / 840,
    4397 * _N**4 / 161280,
)
_DELTA = (
    2 * _N - 2 * _N**2 / 3 - 2 * _N**3 + 116 * _N**4 / 45,
    7 * _N**2 / 3 - 8 * _N**3 / 5 - 227 * _N**4 / 45,
    56 * _N**3 / 15 - 136 * _N**4 / 35,
    4279 * _N**4 / 630,
)


def parse_utm_epsg(crs: str) -> tuple:
    """'EPSG:32644' -> (44, True)  (zone, is_north). Raises ValueError for non-UTM CRS."""
    code = str(crs).upper().replace("EPSG:", "")
    if code.isdigit() and len(code) == 5 and code[:3] in ("326", "327") and 1 <= int(code[3:]) <= 60:
        return int(code[3:]), code[:3] == "326"
    raise ValueError(f"Unsupported CRS '{crs}': only UTM (EPSG:326xx / EPSG:327xx) is supported.")


def utm_to_lonlat(easting: float, northing: float, zone: int, north: bool = True) -> tuple:
    """Return (lon, lat) in degrees."""
    xi = (northing - (0.0 if north else 10_000_000.0)) / (_K0 * _AA)
    eta = (easting - 500_000.0) / (_K0 * _AA)
    xi_p, eta_p = xi, eta
    for j, b in enumerate(_BETA, start=1):
        xi_p -= b * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        eta_p -= b * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
    chi = math.asin(math.sin(xi_p) / math.cosh(eta_p))
    lat = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(_DELTA, start=1))
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    lon = lon0 + math.atan2(math.sinh(eta_p), math.cos(xi_p))
    return math.degrees(lon), math.degrees(lat)


def bounds_wgs84(transform, shape_hw: tuple, crs: str) -> list:
    """Image bounds as [[south, west], [north, east]] (Leaflet L.imageOverlay order).

    Uses all four raster corners, so it is also right if the grid is slightly rotated.
    """
    zone, north = parse_utm_epsg(crs)
    h, w = shape_hw
    corners = [(0, 0), (w, 0), (0, h), (w, h)]  # (col, row) pixel corners
    pts = []
    for col, row in corners:
        x = transform.a * col + transform.b * row + transform.c
        y = transform.d * col + transform.e * row + transform.f
        pts.append(utm_to_lonlat(x, y, zone, north))
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]
