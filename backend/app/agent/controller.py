from __future__ import annotations

from typing import Any, Optional

from app.agent.compat import check_bundle
from app.agent.registry import TASKS, ToolSpec
from app.agent.trace import ExecutionTrace, TraceStep
from app.query_engine.llm_parser import parse_query_smart


def _simple_classify(query: str) -> str:
    q = (query or '').lower()
    hindi = q
    # basic rules
    if 'water' in q:
        return 'index_stats'
    if 'changed' in q or 'change' in q:
        return 'change_detection'
    if 'land cover' in q or 'class' in q:
        return 'land_cover'
    if 'trend' in q or 'time' in q:
        return 'time_series'
    if 'sar' in q and 'optical' in q:
        return 'optical_sar_analysis'
    if 'describe' in q or 'caption' in q:
        return 'caption'
    if 'highlight' in q or 'where' in q and 'water' in q:
        return 'grounding'
    if 'what' in q or '?' in q:
        return 'vqa'
    return 'vqa'


def plan(query: str, bundle, registry: dict[str, ToolSpec] | None = None, llm_client=None) -> Any:
    task = _simple_classify(query)
    compat = check_bundle(bundle, task)
    trace = ExecutionTrace(query=query, bundle_summary=_bundle_summary(bundle), task=task, compat=compat.__dict__ if hasattr(compat, '__dict__') else compat)
    class Plan:
        def __init__(self, task, compat, trace, bundle, registry):
            self.task = task
            self.compat = compat
            self.trace = trace
            self.bundle = bundle
            self.registry = registry or {}
    return Plan(task, compat, trace, bundle, registry or {})


def _bundle_summary(bundle) -> dict:
    if not bundle:
        return {}
    imgs = bundle.images
    return {'kind': getattr(bundle, 'kind', 'single'), 'n': len(imgs) if imgs else 0}


def execute(plan) -> Any:
    trace = plan.trace
    step = TraceStep(step=1, tool='controller', params={'task': plan.task}, status='ok', outputs_summary={'planned': True})
    trace.steps.append(step)
    class Result:
        def __init__(self, trace):
            self.trace = trace
    return Result(trace)
