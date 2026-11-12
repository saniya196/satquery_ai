from __future__ import annotations

from typing import Any
import re

from app.investigation.models import EvidenceCheck
from app.core.config import settings


_CAUSAL_PATTERNS = [
    r"\b(caused by|due to|because of|result of|as a result of)\b",
    r"\b(deforestation caused|drought caused|harvest caused|construction caused|farming caused|rainfall caused)\b",
    r"\b(led to (deforestation|loss of trees|tree loss))\b",
]


def check_causal_claims(text: str) -> list[str]:
    unsupported = []
    t = (text or "").lower()
    for pat in _CAUSAL_PATTERNS:
        if re.search(pat, t):
            unsupported.append(f"Possible unsupported causal claim detected ('{pat}'). Satellite index/change results show measured changes, not proven causes.")
            break
    return unsupported


def validate_tool_result(tool: str, result: dict[str, Any], requested: dict[str, Any]) -> tuple[list[EvidenceCheck], list[str]]:
    checks: list[EvidenceCheck] = []
    limitations: list[str] = []
    facts = result.get("facts") if isinstance(result, dict) else None
    evidence = result.get("evidence") if isinstance(result, dict) else None
    confidence = result.get("confidence") if isinstance(result, dict) else None

    checks.append(EvidenceCheck(check="result_returned", passed=isinstance(result, dict) and bool(result),
                                detail="An actual analysis result object was returned." if result else "No result was returned."))
    checks.append(EvidenceCheck(check="facts_present", passed=isinstance(facts, dict) and bool(facts),
                                detail="Computed facts are present." if isinstance(facts, dict) else "Computed facts are missing."))
    checks.append(EvidenceCheck(check="evidence_present", passed=isinstance(evidence, dict) and bool(evidence),
                                detail="Evidence metadata is present." if isinstance(evidence, dict) else "Evidence metadata is missing."))

    op = (facts or {}).get("operation")
    if op == "change_detection":
        change = (facts or {}).get("change") or {}
        required = ["mean_a", "mean_b", "mean_change", "classes"]
        has_stats = all(k in change for k in required)
        checks.append(EvidenceCheck(check="required_change_stats", passed=has_stats,
                                    detail="Required change statistics are present." if has_stats else f"Missing change statistics: {[k for k in required if k not in change]}"))
        vf = (evidence or {}).get("valid_pixel_fraction")
        if isinstance(vf, (int, float)):
            checks.append(EvidenceCheck(check="valid_pixel_coverage", passed=vf >= settings.min_valid_fraction,
                                        detail=f"Valid pixel fraction on both dates: {vf:.3f} (threshold {settings.min_valid_fraction:.2f})."))
            if vf < 0.7:
                limitations.append(f"Usable imagery coverage was limited ({vf*100:.1f}% valid pixels on both dates); results may be affected by clouds/missing observations.")
        scenes = (evidence or {}).get("scenes") or []
        checks.append(EvidenceCheck(check="scenes_for_period", passed=len(scenes) >= 2,
                                    detail=f"{len(scenes)} scene(s) recorded for the change analysis." + (" Expected baseline and comparison scenes." if len(scenes) < 2 else "")))
    elif op == "index_stats":
        stats = (facts or {}).get("stats") or {}
        has_stats = "mean" in stats or "median" in stats
        checks.append(EvidenceCheck(check="required_index_stats", passed=has_stats,
                                    detail="Index statistics are present." if has_stats else "Index statistics are missing."))
        vf = (evidence or {}).get("valid_pixel_fraction")
        if isinstance(vf, (int, float)):
            checks.append(EvidenceCheck(check="valid_pixel_coverage", passed=vf >= settings.min_valid_fraction,
                                        detail=f"Valid pixel fraction: {vf:.3f}."))
            if vf < 0.7:
                limitations.append(f"Usable imagery coverage was limited ({vf*100:.1f}% valid pixels).")
    elif op == "time_series":
        series = (facts or {}).get("series") or {}
        n = series.get("n_dates_included") or series.get("n_dates_usable") or len(series.get("dates") or [])
        checks.append(EvidenceCheck(check="observations_available", passed=int(n or 0) > 0,
                                    detail=f"{n} usable observation date(s) included."))
        if not series.get("trend_claim_allowed"):
            limitations.append("Insufficient usable observations for a reliable trend claim; any trend interpretation should be avoided.")
        vf = (evidence or {}).get("valid_pixel_fraction")
        if isinstance(vf, (int, float)) and vf < 0.7:
            limitations.append(f"Average valid pixel fraction was limited ({vf*100:.1f}%).")

    # AOI/period consistency (best effort from available evidence)
    if isinstance(evidence, dict):
        if evidence.get("aoi_area_km2") is None:
            limitations.append("AOI area was not reported in evidence.")
    if isinstance(confidence, dict) and confidence.get("score") is None:
        limitations.append("A data quality score was not available.")

    return checks, limitations
