from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

TraceStatus = Literal["pending", "running", "completed", "failed", "skipped"]


class PlanTool(BaseModel):
    tool: str
    purpose: str
    reason: str
    params: dict[str, Any] = Field(default_factory=dict)


class InvestigationPlan(BaseModel):
    original_question: str
    parsed_intent: str
    operation: Optional[str] = None
    index: Optional[str] = None
    aoi_provided: bool = False
    date_range: dict[str, Any] = Field(default_factory=dict)
    selected_tools: list[PlanTool] = Field(default_factory=list)
    missing_required_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    can_execute: bool = False
    notes: list[str] = Field(default_factory=list)


class TraceEvent(BaseModel):
    id: str
    label: str
    status: TraceStatus
    detail: Optional[str] = None
    tool: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[dict[str, Any]] = None


class ToolExecution(BaseModel):
    tool: str
    status: TraceStatus
    purpose: str
    summary: dict[str, Any] = Field(default_factory=dict)
    error: Optional[dict[str, Any]] = None
    actual_result: Optional[dict[str, Any]] = None  # sanitized actual output (facts/evidence/confidence/answer subset)


class EvidenceCheck(BaseModel):
    check: str
    passed: bool
    detail: str


class InvestigationResult(BaseModel):
    question_understood: str
    plan: InvestigationPlan
    trace: list[TraceEvent] = Field(default_factory=list)
    tools_executed: list[ToolExecution] = Field(default_factory=list)
    actual_findings: dict[str, Any] = Field(default_factory=dict)
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    data_quality_and_uncertainty: dict[str, Any] = Field(default_factory=dict)
    unsupported_conclusions: list[str] = Field(default_factory=list)
    suggested_next_investigations: list[str] = Field(default_factory=list)
    explanation: dict[str, Any] = Field(default_factory=dict)
    status: Literal["completed", "partial", "needs_input", "failed"] = "completed"
