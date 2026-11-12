from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional
import uuid

import numpy as np

from app.core.errors import SatQueryError
from app.investigation.models import EvidenceCheck, InvestigationPlan, InvestigationResult, ToolExecution, TraceEvent
from app.investigation.planner import TOOL_CHANGE, TOOL_INDEX, TOOL_TIME_SERIES, TOOL_WATER_CHANGE, build_plan
from app.investigation.validator import check_causal_claims, validate_tool_result
from app.llm.client import LLMClient
from app.llm.explainer import make_llm_fn
from app.satellite.provider import SatelliteProvider
from app.schemas.query import DateRange, StructuredQuery
from app.services import analysis
from app.validation.grounding import check_grounding, grounded_answer


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evt(label: str, status: str, detail: str | None = None, tool: str | None = None, error: dict | None = None, started: str | None = None) -> TraceEvent:
    finished = _now() if status in ("completed", "failed", "skipped") else None
    return TraceEvent(id=uuid.uuid4().hex[:12], label=label, status=status, detail=detail, tool=tool,
                      started_at=started or _now(), finished_at=finished, error=error)


def _sanitize_result(res: dict[str, Any]) -> dict[str, Any]:
    """Keep actual computed outputs/evidence; drop large arrays/raster payloads."""
    if not isinstance(res, dict):
        return {}
    def sanitize(value: Any) -> Any:
        if isinstance(value, np.ndarray):
            return None
        if isinstance(value, dict):
            return {str(k): sanitized for k, v in value.items()
                    if (sanitized := sanitize(v)) is not None}
        if isinstance(value, (list, tuple)):
            return [sanitized for v in value if (sanitized := sanitize(v)) is not None]
        return value

    keep = {}
    for k in ("evidence", "confidence", "facts", "answer", "hotspots", "coverage", "job_id"):
        if k in res:
            sanitized = sanitize(res[k])
            if sanitized is not None:
                keep[k] = sanitized
    # hotspots may be duplicated in facts/arrays in services; ensure we capture explicit hotspots list
    if "hotspots" not in keep and isinstance(res.get("facts"), dict):
        pass
    return keep


def _deterministic_investigation_text(findings: dict[str, Any], limitations: list[str]) -> str:
    parts = []
    for tool, payload in findings.items():
        facts = (payload or {}).get("facts") or {}
        op = facts.get("operation")
        if op == "change_detection":
            c = facts.get("change") or {}
            ma, mb, mc = c.get("mean_a"), c.get("mean_b"), c.get("mean_change")
            da, db = facts.get("date_a"), facts.get("date_b")
            idx = facts.get("index", "NDVI")
            hotspots = (payload or {}).get("hotspots") or []
            n_hot = len(hotspots) if isinstance(hotspots, list) else 0
            if all(isinstance(x, (int, float)) for x in (ma, mb, mc)):
                direction = "decreased" if mc < 0 else ("increased" if mc > 0 else "showed little net change")
                parts.append(f"For {idx}, the measured mean value {direction} from {ma:.3f} ({da}) to {mb:.3f} ({db}); mean change {mc:.3f}.")
            if n_hot:
                parts.append(f"The change analysis identified {n_hot} significant decrease hotspot cluster(s) in the selected area (as returned by the deterministic hotspot detection).")
            else:
                parts.append("No significant decrease hotspot clusters were returned by the change analysis for the selected thresholds.")
        elif op == "index_stats":
            s = facts.get("stats") or {}
            idx = facts.get("index", "index")
            d = facts.get("date")
            if isinstance(s.get("mean"), (int, float)):
                parts.append(f"{idx} statistics for {d}: mean {s['mean']:.3f}, median {s.get('median')}, valid pixel fraction {s.get('valid_fraction')}.")
        elif op == "time_series":
            series = facts.get("series") or {}
            idx = facts.get("index", "index")
            if series.get("trend_claim_allowed") and (series.get("trend_test") or {}).get("trend"):
                parts.append(f"Time-series analysis for {idx} reported a Mann-Kendall trend result: {(series.get('trend_test') or {}).get('trend')}.")
            else:
                parts.append(f"Time-series analysis for {idx} returned observations, but a reliable trend claim was not supported with the available usable dates.")
        ans = ((payload or {}).get("answer") or {}).get("text")
        if ans and ans not in parts:
            # keep grounded answer available separately; avoid duplication
            pass
    if not parts:
        parts.append("No supported findings could be produced from the available analysis outputs.")
    parts.append("These findings describe measured satellite/index outputs for the selected area and period; they do not establish the cause of any change.")
    if limitations:
        parts.append("Limitations: " + " ".join(limitations[:3]))
    return " ".join(parts)


def _suggestions(plan: InvestigationPlan, findings: dict[str, Any], status: str) -> list[str]:
    s = []
    ops = {((v or {}).get("facts") or {}).get("operation") for v in findings.values()}
    if "change_detection" in ops:
        s.append("Run a time-series trend analysis for the same area to see whether the change is part of a longer pattern (requires a date range with enough usable observations).")
        s.append("Compare vegetation/water indicators (for example NDVI and NDWI) for the same dates if you want to investigate different surface signals.")
    if "index_stats" in ops:
        s.append("Run a before/after change analysis using two dates or months to measure how the indicator changed.")
    if "time_series" in ops:
        s.append("Run a focused before/after change detection for two specific periods to map where significant changes occurred.")
    if status == "needs_input":
        s.append("Provide the missing AOI or date information shown in the investigation plan, then run the investigation again.")
    # keep only supported follow-ups
    out = []
    for item in s:
        if len(out) >= 4: break
        out.append(item)
    if not out:
        out.append("Try a supported question such as vegetation change between two months, water change, or a trend over time for the selected area.")
    return out


def run_investigation(query: str, aoi: Optional[dict], reference_date: Optional[date], max_cloud: float,
                      provider: SatelliteProvider, llm_client: Optional[LLMClient], date_overrides: Optional[dict] = None) -> InvestigationResult:
    trace: list[TraceEvent] = []
    t0 = _now()
    trace.append(_evt("Understanding request", "completed", "Parsed the question and checked required inputs.", started=t0))
    trace.append(_evt("Preparing analysis plan", "running", "Selecting whitelisted existing analysis tools."))
    plan, q = build_plan(query, aoi, reference_date, llm_client, date_overrides=date_overrides)
    trace[-1] = _evt("Preparing analysis plan", "completed", f"Selected {len(plan.selected_tools)} tool(s); can_execute={plan.can_execute}.", started=trace[-1].started_at)

    if not plan.can_execute:
        # missing input or unsupported
        if plan.missing_required_inputs:
            trace.append(_evt("Running selected analysis", "skipped", "Skipped because required inputs are missing.", tool=None))
            trace.append(_evt("Retrieving results", "skipped", "No tools were executed."))
            trace.append(_evt("Validating evidence", "skipped", "No results to validate."))
            trace.append(_evt("Generating explanation", "completed", "Provided guidance for missing inputs."))
            msg = "Missing required information: " + "; ".join(plan.missing_required_inputs) + "."
            return InvestigationResult(
                question_understood=plan.original_question,
                plan=plan, trace=trace, tools_executed=[], actual_findings={},
                supporting_evidence=[], data_quality_and_uncertainty={"limitations": plan.missing_required_inputs},
                unsupported_conclusions=[],
                suggested_next_investigations=_suggestions(plan, {}, "needs_input"),
                explanation={"text": msg + " " + " ".join(plan.notes), "source": "template", "validated": True},
                status="needs_input",
            )
        trace.append(_evt("Running selected analysis", "skipped", "No supported tools selected for this request."))
        trace.append(_evt("Validating evidence", "skipped", "No results to validate."))
        trace.append(_evt("Generating explanation", "completed", "Returned an unsupported-request explanation."))
        return InvestigationResult(
            question_understood=plan.original_question, plan=plan, trace=trace, tools_executed=[],
            actual_findings={}, supporting_evidence=[], data_quality_and_uncertainty={},
            unsupported_conclusions=[], suggested_next_investigations=_suggestions(plan, {}, "failed"),
            explanation={"text": " ".join(plan.notes) or "This request is not supported by the available satellite analysis tools.", "source": "template", "validated": True},
            status="failed",
        )

    assert aoi is not None
    llm_fn = make_llm_fn(llm_client)
    executions: list[ToolExecution] = []
    findings: dict[str, Any] = {}
    evidence_items: list[dict[str, Any]] = []
    all_limitations: list[str] = []
    all_checks: list[EvidenceCheck] = []
    any_success = False

    for tool_spec in plan.selected_tools:
        tool_name = tool_spec.tool
        params = tool_spec.params or {}
        idx = params.get("index") or plan.index or "NDVI"
        run_started = _now()
        trace.append(_evt(f"Running selected analysis: {tool_name}", "running", tool_spec.purpose, tool=tool_name, started=run_started))
        try:
            if params.get("operation") == "change_detection":
                if not (q.date_a and q.date_b):
                    raise ValueError("Missing date_a/date_b for change detection.")
                res = analysis.run_change(provider, aoi, q.date_a, q.date_b, index=idx, max_cloud=max_cloud, llm_fn=llm_fn)
            elif params.get("operation") == "time_series":
                if not q.series_range:
                    raise ValueError("Missing series_range for time series.")
                res = analysis.run_time_series(provider, aoi, q.series_range, index=idx, max_cloud=max_cloud, llm_fn=llm_fn)
            elif params.get("operation") == "index_stats":
                if not q.date_a:
                    raise ValueError("Missing date_a for index stats.")
                res = analysis.run_index_stats(provider, aoi, q.date_a, index=idx, max_cloud=max_cloud, llm_fn=llm_fn)
            else:
                raise ValueError(f"Unsupported whitelisted tool operation: {params.get('operation')}")

            sanitized = _sanitize_result(res)
            checks, lims = validate_tool_result(tool_name, sanitized, params)
            all_checks.extend(checks)
            all_limitations.extend(lims)
            if isinstance(sanitized.get("evidence"), dict):
                evidence_items.append({"tool": tool_name, **{k: sanitized["evidence"].get(k) for k in ("operation", "scenes", "valid_pixel_fraction", "aoi_area_km2", "index", "formula", "bands", "preprocessing", "thresholds", "coverage") if k in sanitized["evidence"]}})
            executions.append(ToolExecution(tool=tool_name, status="completed", purpose=tool_spec.purpose,
                                            summary={"operation": (sanitized.get("facts") or {}).get("operation"), "index": (sanitized.get("facts") or {}).get("index"), "data_quality_score": (sanitized.get("confidence") or {}).get("score")},
                                            actual_result=sanitized))
            findings[tool_name] = sanitized
            any_success = True
            trace[-1] = _evt(f"Running selected analysis: {tool_name}", "completed", "Tool returned actual analysis outputs.", tool=tool_name, started=run_started)
        except Exception as e:
            err = {"code": getattr(e, "code", "tool_error"), "message": getattr(e, "message", str(e)) if not isinstance(e, SatQueryError) else e.message}
            executions.append(ToolExecution(tool=tool_name, status="failed", purpose=tool_spec.purpose, error=err))
            trace[-1] = _evt(f"Running selected analysis: {tool_name}", "failed", "Tool execution failed.", tool=tool_name, error=err, started=run_started)
            # continue to next tool if any (partial failure handling)
            all_limitations.append(f"Tool '{tool_name}' failed: {err.get('message')}")

    trace.append(_evt("Retrieving results", "completed" if any_success else "failed", "Collected actual outputs from executed tools." if any_success else "No tool outputs were retrieved."))
    trace.append(_evt("Validating evidence", "running", "Checking evidence presence, data quality, and claim constraints."))
    unsupported = []
    # validate explanation later; also flag obvious causal language in any tool text? (tool answers are already grounded; still check)
    for ex in executions:
        if ex.actual_result:
            txt = ((ex.actual_result.get("answer") or {}).get("text") or "")
            unsupported.extend(check_causal_claims(txt))
    trace[-1] = _evt("Validating evidence", "completed", f"Completed {len(all_checks)} evidence check(s)." + (f" Found {len(unsupported)} causal-claim warning(s)." if unsupported else ""))

    trace.append(_evt("Generating explanation", "running", "Creating an evidence-grounded explanation from verified findings."))
    det_text = _deterministic_investigation_text(findings, all_limitations)
    combined_facts = {"investigation": {"question": plan.original_question, "tools": list(findings.keys())}, "findings": {k: {"facts": (v or {}).get("facts"), "confidence": (v or {}).get("confidence")} for k, v in findings.items()}}
    explanation = {"text": det_text, "source": "template", "attempts": 0, "validated": True}
    if llm_fn is not None and any_success:
        try:
            # use grounded_answer pattern with custom facts; if it falls back, we keep deterministic text
            ga = grounded_answer(combined_facts, llm_fn, max_retries=1, allowed_literals=tuple(range(0, 101)))
            # grounded_answer may return template_answer for unknown op; detect and prefer our deterministic text if it became generic
            if ga.get("source") == "llm" and ga.get("text"):
                extra_causal = check_causal_claims(ga["text"])
                if not extra_causal:
                    explanation = {**ga, "validated": True}
                else:
                    unsupported.extend(extra_causal)
            elif ga.get("text") and "Analysis complete. See the evidence panel" not in ga.get("text", ""):
                # grounded template used our facts? unlikely; keep our deterministic
                pass
        except Exception:
            pass
    unsupported.extend(check_causal_claims(explanation.get("text", "")))
    # final grounding check against combined facts for the explanation text
    verdict = check_grounding(explanation.get("text", ""), combined_facts, allowed_literals=tuple(list(range(0, 101)) + [0.5, 1.0]))
    if not verdict["valid"] and explanation.get("source") == "llm":
        explanation = {"text": det_text, "source": "template", "attempts": explanation.get("attempts", 0), "validated": True, "grounding_fallback": verdict}
    trace[-1] = _evt("Generating explanation", "completed", f"Explanation source: {explanation.get('source')}.")

    status = "completed" if any_success and all(e.status == "completed" for e in executions) else ("partial" if any_success else "failed")
    dq = {"checks": [c.model_dump() for c in all_checks], "limitations": list(dict.fromkeys(all_limitations))}
    return InvestigationResult(
        question_understood=plan.original_question,
        plan=plan,
        trace=trace,
        tools_executed=executions,
        actual_findings={k: _sanitize_result(v) for k, v in findings.items()},
        supporting_evidence=evidence_items,
        data_quality_and_uncertainty=dq,
        unsupported_conclusions=list(dict.fromkeys(unsupported)),
        suggested_next_investigations=_suggestions(plan, findings, status),
        explanation=explanation,
        status=status,
    )
