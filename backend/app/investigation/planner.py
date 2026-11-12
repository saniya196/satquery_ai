from __future__ import annotations

from datetime import date
from typing import Optional

from app.investigation.models import InvestigationPlan, PlanTool
from app.llm.client import LLMClient
from app.query_engine.llm_parser import parse_query_smart
from app.query_engine.parser import clarification_message
from app.schemas.query import DateRange, Operation, StructuredQuery

# Whitelisted tools that map to existing deterministic backend capabilities.
TOOL_CHANGE = "ndvi_change_hotspots"  # uses existing run_change (NDVI) + hotspot output
TOOL_INDEX = "index_stats"
TOOL_TIME_SERIES = "time_series"
TOOL_WATER_CHANGE = "water_change"  # NDWI change (if requested)

SUPPORTED_TOOL_NAMES = {TOOL_CHANGE, TOOL_INDEX, TOOL_TIME_SERIES, TOOL_WATER_CHANGE}


def _date_range_dict(q: StructuredQuery) -> dict:
    out = {}
    if q.date_a:
        out["date_a"] = {"start": q.date_a.start.isoformat(), "end": q.date_a.end.isoformat()}
    if q.date_b:
        out["date_b"] = {"start": q.date_b.start.isoformat(), "end": q.date_b.end.isoformat()}
    if q.series_range:
        out["series_range"] = {"start": q.series_range.start.isoformat(), "end": q.series_range.end.isoformat()}
    return out


def _apply_date_overrides(q: StructuredQuery, overrides: Optional[dict]) -> None:
    if not overrides:
        return
    def _mk(v):
        if not isinstance(v, dict): return None
        try:
            from datetime import date as _date
            return DateRange(start=_date.fromisoformat(str(v["start"])[:10]), end=_date.fromisoformat(str(v["end"])[:10]))
        except Exception:
            return None
    if _mk(overrides.get("date_a")): q.date_a = _mk(overrides.get("date_a"))
    if _mk(overrides.get("date_b")): q.date_b = _mk(overrides.get("date_b"))
    if _mk(overrides.get("series_range")): q.series_range = _mk(overrides.get("series_range"))
    # Re-evaluate missing based on operation
    missing = list(q.missing or [])
    if q.operation == Operation.CHANGE_DETECTION and q.date_a and q.date_b:
        missing = [m for m in missing if "two comparison periods" not in m]
    if q.operation == Operation.TIME_SERIES and q.series_range:
        missing = [m for m in missing if "time range" not in m]
    if q.operation in (Operation.INDEX_STATS, Operation.LAND_COVER) and q.date_a:
        missing = [m for m in missing if "date or month" not in m]
    q.missing = missing


def build_plan(query: str, aoi: Optional[dict], reference_date: Optional[date], llm_client: Optional[LLMClient], date_overrides: Optional[dict] = None) -> tuple[InvestigationPlan, StructuredQuery]:
    q = parse_query_smart(query, reference_date, llm_client)
    _apply_date_overrides(q, date_overrides)
    missing = list(q.missing or [])
    if not aoi or not isinstance(aoi, dict) or aoi.get("type") != "Polygon":
        missing.append("an area of interest (AOI) drawn/selected on the map")

    tools: list[PlanTool] = []
    expected: list[str] = []
    intent = q.operation.value if q and q.operation else "unknown"

    text_l = (query or "").lower()
    wants_hotspots = "hotspot" in text_l or "significant decrease" in text_l or "cluster" in text_l
    wants_change = wants_hotspots or q.operation == Operation.CHANGE_DETECTION or "change" in text_l or "decrease" in text_l or "increase" in text_l
    wants_trend = q.operation == Operation.TIME_SERIES or "trend" in text_l or "over time" in text_l or "time series" in text_l
    wants_water = (q.index and q.index.upper() in ("NDWI", "MNDWI")) or "water" in text_l

    # Bounded selection: prefer reliable existing tools; avoid unsupported/fabricated tools.
    if q.operation == Operation.UNSUPPORTED:
        plan = InvestigationPlan(
            original_question=query,
            parsed_intent="unsupported",
            operation=q.operation.value,
            index=q.index,
            aoi_provided=bool(aoi),
            date_range=_date_range_dict(q),
            selected_tools=[],
            missing_required_inputs=[],
            expected_outputs=[],
            can_execute=False,
            notes=[q.unsupported_reason or "The request is not supported by the available satellite analysis tools."],
        )
        return plan, q

    if wants_change and not wants_trend:
        # Change detection via existing implementation includes hotspot detection output.
        idx = "NDWI" if wants_water and not wants_hotspots else (q.index or "NDVI")
        if idx not in ("NDVI", "NDWI", "MNDWI", "NDBI", "SAVI"):
            idx = "NDVI"
        tools.append(PlanTool(
            tool=TOOL_WATER_CHANGE if idx in ("NDWI", "MNDWI") else TOOL_CHANGE,
            purpose=f"Measure {idx} before/after change and identify significant decrease hotspots (existing deterministic pipeline).",
            reason="The question asks to investigate change" + (" and hotspots." if wants_hotspots else ".") + f" {idx} change detection reuses existing analysis and produces hotspot/evidence outputs.",
            params={"index": idx, "operation": "change_detection"},
        ))
        expected += [f"{idx} change statistics", "change classes/areas", "significant decrease hotspots (if detected)", "evidence and data quality"]
    elif wants_trend:
        idx = q.index or ("NDWI" if wants_water else "NDVI")
        if idx not in ("NDVI", "NDWI", "MNDWI", "NDBI", "SAVI"):
            idx = "NDVI"
        tools.append(PlanTool(
            tool=TOOL_TIME_SERIES,
            purpose=f"Analyze {idx} over time using AOI median values (Mann-Kendall / Sen's slope where enough observations exist).",
            reason="The question asks for temporal trends/changes over time; existing time-series analysis computes deterministic statistics.",
            params={"index": idx, "operation": "time_series"},
        ))
        expected += [f"{idx} time series", "trend test (if sufficient observations)", "evidence and data quality"]
    else:
        # Fallback to index stats if dates/intent fit; otherwise ask for clarification via missing inputs.
        idx = q.index or ("NDWI" if wants_water else "NDVI")
        if idx not in ("NDVI", "NDWI", "MNDWI", "NDBI", "SAVI"):
            idx = "NDVI"
        tools.append(PlanTool(
            tool=TOOL_INDEX,
            purpose=f"Compute {idx} statistics for the selected area and date.",
            reason="A bounded index-statistics analysis is the most reliable existing tool for this request.",
            params={"index": idx, "operation": "index_stats"},
        ))
        expected += [f"{idx} statistics", "index map evidence", "data quality"]

    # Ensure required dates are present based on selected tools.
    if any(t.params.get("operation") == "change_detection" for t in tools) and not (q.date_a and q.date_b):
        if "two comparison periods (e.g. 'June' vs 'September')" not in missing:
            missing.append("two comparison periods (e.g. 'June' vs 'September')")
    if any(t.params.get("operation") == "time_series" for t in tools) and not q.series_range:
        if "a time range (e.g. 'last year')" not in missing:
            missing.append("a time range (e.g. 'last year')")
    if any(t.params.get("operation") == "index_stats" for t in tools) and not q.date_a:
        if "a date or month" not in missing:
            missing.append("a date or month")

    can_execute = len(missing) == 0 and len(tools) > 0
    notes = []
    if wants_hotspots and tools and "change_detection" in str(tools[0].params):
        notes.append("Hotspots are produced by the existing change-detection pipeline as significant-decrease clusters; no separate hotspot model is invented.")
    if can_execute:
        notes.append("Tools will run sequentially using existing deterministic analysis functions; LLM is used only to phrase verified results.")

    plan = InvestigationPlan(
        original_question=query,
        parsed_intent=intent,
        operation=q.operation.value,
        index=tools[0].params.get("index") if tools else q.index,
        aoi_provided=bool(aoi and aoi.get("type") == "Polygon"),
        date_range=_date_range_dict(q),
        selected_tools=tools,
        missing_required_inputs=missing,
        expected_outputs=expected,
        can_execute=can_execute,
        notes=notes,
    )
    return plan, q
