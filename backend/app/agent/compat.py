from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GEOSPATIAL_TASKS = {
    'index_stats',
    'change_detection',
    'time_series',
    'land_cover',
    'change_map',
    'optical_sar_analysis',
}


@dataclass
class CompatResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def _fmt_fix(fix: str) -> str:
    return f' Suggested fix: {fix}.'


def check_bundle(bundle, task: str, benchmark_mode: bool = False) -> CompatResult:
    res = CompatResult()
    if bundle is None or getattr(bundle, 'images', None) is None:
        res.ok = False
        res.errors.append('No images were provided.')
        res.suggestions.append('Upload at least one image or draw an area in map mode.')
        return res

    images = list(bundle.images)
    expected = _expected_count(task, getattr(bundle, 'kind', 'single'))
    if expected and len(images) != expected:
        res.ok = False
        res.errors.append(f'Expected {expected} image(s) for this task, but got {len(images)}.')
        res.suggestions.append('Match the number of images to the selected task.')

    for img in images:
        fmt = getattr(img, 'format', 'unknown')
        if fmt in ('GeoTIFF', 'TIFF'):
            pass
        elif fmt in ('PNG', 'JPEG'):
            if not benchmark_mode:
                res.ok = False
                res.errors.append(f'{fmt} is only accepted in benchmark mode.')
                res.suggestions.append('Use GeoTIFF or TIFF for this task, or enable benchmark mode.')
        else:
            res.ok = False
            res.errors.append(f'Unsupported image format: {fmt}.')
            res.suggestions.append('Use GeoTIFF, TIFF, or PNG/JPEG only in benchmark mode.')

        if task in GEOSPATIAL_TASKS:
            if getattr(img, 'crs', None) is None:
                res.ok = False
                res.errors.append('CRS is missing for a geospatial task.')
                res.suggestions.append('Re-save the GeoTIFF with georeferencing (CRS/geotransform).')

    if len(images) >= 2:
        crs0 = getattr(images[0], 'crs', None)
        for img in images[1:]:
            if crs0 != getattr(img, 'crs', None):
                res.ok = False
                res.errors.append('Images must share the same CRS.')
                res.suggestions.append('Reproject both images to the same CRS.')
                break

    if getattr(bundle, 'kind', '') == 'bitemporal_pair' and len(images) >= 2:
        dt0 = getattr(images[0], 'datetime', None)
        dt1 = getattr(images[1], 'datetime', None)
        if dt0 and dt1 and dt0 > dt1:
            res.ok = False
            res.errors.append('Acquisition dates must be in order (t1 before or equal to t2).')
            res.suggestions.append('Swap the before/after images or correct their dates.')

    return res


def _expected_count(task: str, kind: str) -> Optional[int]:
    single_tasks = {'vqa', 'caption', 'grounding', 'index_stats', 'time_series', 'land_cover'}
    if task in single_tasks:
        return 1
    pair_tasks = {'change_description', 'change_vqa', 'change_map', 'change_detection'}
    if task in pair_tasks:
        return 2
    modal_tasks = {'optical_sar_analysis', 'optical_sar_vqa'}
    if task in modal_tasks:
        return 2
    return None
