from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

ToolStatus = Literal['available', 'not_implemented']


@dataclass
class ParamSpec:
    type: str = 'str'
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[list[Any]] = None


@dataclass
class ToolSpec:
    name: str
    task: str
    description: str
    accepted_bundles: list[str] = field(default_factory=list)
    required_modalities: list[str] = field(default_factory=list)
    required_bands: list[str] = field(default_factory=list)
    params: dict[str, ParamSpec] = field(default_factory=dict)
    run: Optional[Callable[..., Any]] = None
    produces: str = 'result'
    status: ToolStatus = 'available'


TASKS = [
    'vqa',
    'caption',
    'grounding',
    'change_description',
    'change_vqa',
    'change_map',
    'optical_sar_analysis',
    'optical_sar_vqa',
    'index_stats',
    'change_detection',
    'time_series',
    'land_cover',
]
