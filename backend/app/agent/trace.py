from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional
import json
import uuid


StepStatus = Literal['ok', 'error', 'skipped', 'not_implemented']


@dataclass
class TraceStep:
    step: int
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    started_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    duration_ms: float = 0.0
    status: StepStatus = 'ok'
    outputs_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ExecutionTrace:
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    query: str = ''
    bundle_summary: dict[str, Any] = field(default_factory=dict)
    task: str = ''
    compat: dict[str, Any] = field(default_factory=dict)
    steps: list[TraceStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)
