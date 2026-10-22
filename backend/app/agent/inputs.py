from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Modality = Literal['optical', 'sar', 'unknown']
ImageFormat = Literal['GeoTIFF', 'TIFF', 'PNG', 'JPEG']
BundleKind = Literal['single', 'cross_modal_pair', 'bitemporal_pair', 'aoi_download']


@dataclass(frozen=True)
class ImageInput:
    id: str
    path: str
    modality: Modality = 'unknown'
    format: ImageFormat = 'GeoTIFF'
    bands: list[str] = field(default_factory=list)
    crs: Optional[str] = None
    bounds: Optional[list[float]] = None  # [minx, miny, maxx, maxy]
    resolution_m: Optional[float] = None
    datetime: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass(frozen=True)
class InputBundle:
    kind: BundleKind
    images: list[ImageInput]
    roles: dict[str, str] = field(default_factory=dict)
