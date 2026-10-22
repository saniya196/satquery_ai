from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from app.agent.trace import ExecutionTrace


VerificationStatus = Literal['agree', 'disagree', 'not_verifiable', 'not_applicable']


@dataclass
class VLMAnswer:
    text: str = ''
    boxes: Optional[list] = None
    token_prob: Optional[float] = None
    model_generated: bool = True


@dataclass
class Verification:
    status: VerificationStatus = 'not_applicable'
    details: str = ''


@dataclass
class AnswerBundle:
    task: str = ''
    vlm_answer: Optional[VLMAnswer] = None
    tool_results: list[Any] = field(default_factory=list)
    verification: Optional[Verification] = None
    final_text: str = ''
    confidence: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    trace: Optional[ExecutionTrace] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d
