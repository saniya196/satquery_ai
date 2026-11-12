"""LLM query parser with guard rails. Output is the SAME StructuredQuery the rule parser produces."""
import json
import re
from datetime import date
from typing import Optional

from pydantic import ValidationError

from app.indices.spectral import INDEX_REGISTRY
from app.llm.client import LLMClient, LLMError
from app.query_engine.parser import parse_query, validate_query
from app.schemas.query import DateRange, Operation, StructuredQuery

SYSTEM_PROMPT = """You convert a question about satellite imagery into JSON. Output JSON only.
You do NOT answer the question and you never compute anything.

Schema:
{"operation": "index_stats|change_detection|time_series|land_cover|compare_regions|unsupported",
 "index": "NDVI|NDWI|MNDWI|NDBI|SAVI|null",
 "date_a": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} | null,
 "date_b": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} | null,
 "series_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} | null,
 "change_direction": "decrease|increase|any|null",
 "unsupported_reason": string | null}

Rules:
- Vegetation/crop health -> NDVI. Water -> NDWI. Built-up/urban -> NDBI. Sparse vegetation on soil -> SAVI.
- A month name means the whole month (use the given reference year logic). "Last year" means the 365 days before the reference date.
- If the user did not give a date or period, use null. NEVER invent or assume dates.
- The area of interest comes from the map, not from the text. Do not output locations.
- Questions you cannot support (poems, weather forecasts, ...) -> operation "unsupported" with a short reason.
- The question may be in English or Hindi. Output the same schema either way."""

_MONTH_WORDS = ("january february march april june july august september october november december "
                "jan feb mar apr jun jul aug sep sept oct nov dec").split()
_HI_CUES = ("जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "सितम्बर",
            "अक्टूबर", "नवंबर", "दिसंबर", "पिछले", "पिछला", "साल", "महीने")
_EXPLICIT_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def has_date_cue(text: str) -> bool:
    """True if the text itself contains something date-like. Used to drop hallucinated dates."""
    t = text.lower()
    if re.search(r"\b20\d{2}\b|\d{4}-\d{2}-\d{2}", t):
        return True
    if re.search(r"last (year|month|week)|past (year|month)|last \d+ (month|week|day)s?|this year|yesterday|recent", t):
        return True
    if any(re.search(rf"\b{m}\b", t) for m in _MONTH_WORDS):
        return True
    if re.search(r"\b(in|of|to|and|from|between|since|until|during)\s+may\b", t):
        return True
    return any(h in text for h in _HI_CUES)


def _range(obj) -> Optional[DateRange]:
    if not obj:
        return None
    try:
        r = DateRange(start=date.fromisoformat(obj["start"]), end=date.fromisoformat(obj["end"]))
    except (KeyError, TypeError, ValueError, ValidationError):
        return None
    return r if r.end >= r.start else None


def _explicit_iso_ranges(text: str) -> list[DateRange]:
    """Return valid ISO dates in their textual order."""
    ranges = []
    for value in _EXPLICIT_ISO.findall(text):
        try:
            day = date.fromisoformat(value)
        except ValueError:
            continue
        ranges.append(DateRange(start=day, end=day))
    return ranges


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def parse_with_llm(text: str, client: LLMClient, reference_date: Optional[date] = None) -> StructuredQuery:
    """Raises LLMError/ValueError on any problem; use parse_query_smart for the safe version."""
    ref = reference_date or date.today()
    raw = client.complete(SYSTEM_PROMPT, f"Reference date: {ref.isoformat()}\nQuestion: {text}", json_mode=True)
    data = _extract_json(raw)
    op = Operation(data.get("operation"))                       # unknown value -> ValueError
    index = (data.get("index") or None)
    index = index.upper() if isinstance(index, str) and index.upper() in INDEX_REGISTRY else None
    cue = has_date_cue(text)
    q = StructuredQuery(
        raw_text=text,
        language="hi" if re.search(r"[\u0900-\u097F]", text) else "en",
        operation=op, index=index,
        date_a=_range(data.get("date_a")) if cue else None,
        date_b=_range(data.get("date_b")) if cue else None,
        series_range=_range(data.get("series_range")) if cue else None,
        change_direction=data.get("change_direction") if data.get("change_direction") in ("decrease", "increase", "any") else None,
        unsupported_reason=data.get("unsupported_reason") if op == Operation.UNSUPPORTED else None,
        parser="llm",
    )
    explicit_dates = _explicit_iso_ranges(text)
    if len(explicit_dates) == 2:
        q.date_a, q.date_b = (
            explicit_dates if explicit_dates[0].start <= explicit_dates[1].start
            else (explicit_dates[1], explicit_dates[0])
        )
    if op == Operation.UNSUPPORTED and not q.unsupported_reason:
        q.unsupported_reason = "That question is outside what I can analyse from satellite imagery."
    if q.index is None and op in (Operation.CHANGE_DETECTION, Operation.TIME_SERIES):
        q.index = "NDVI"
    q.outputs = {"change_detection": ["mean_change", "change_map", "class_statistics", "hotspots"],
                 "time_series": ["time_series", "trend_test"], "index_stats": ["statistics", "index_map"],
                 "land_cover": ["class_map", "class_distribution"]}.get(op.value, [])
    return validate_query(q)


def parse_query_smart(text: str, reference_date: Optional[date] = None,
                      client: Optional[LLMClient] = None) -> StructuredQuery:
    """LLM first (if configured), rule-based parser as the guaranteed fallback."""
    if client is not None:
        try:
            return parse_with_llm(text, client, reference_date)
        except (LLMError, ValueError, ValidationError, KeyError, TypeError):
            pass
    return parse_query(text, reference_date)
