"""Bounded, evidence-grounded AOI investigation agent (SIH26167 WOW upgrade).
Orchestrates existing deterministic analysis tools; LLM only phrases verified results.
"""
from .orchestrator import run_investigation
from .planner import build_plan

__all__ = ["run_investigation", "build_plan"]
