"""Rule-based fallback parser (works with no API key). An LLM parser must emit the same StructuredQuery."""
import calendar
import re
from datetime import date, timedelta
from typing import Optional

from app.schemas.query import DateRange, Operation, StructuredQuery

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_YEAR = re.compile(r"\b(20\d{2})\b")

KW = {
    "ts": ["trend", "time series", "time-series", "over the last", "over time", "रुझान", "समय श्रृंखला"],
    "change": ["decreas", "increas", "chang", "loss", "gain", "before and after", "compare vegetation",
               "declin", "कम", "बढ़", "बदल", "परिवर्तन"],
    "landcover": ["land cover", "land-cover", "landcover", "dominant", "classes", "classification", "भूमि आवरण"],
    "compare_regions": ["field a", "field b", "two fields", "two locations", "between these two", "compare regions"],
}
INDEX_KW = [
    ("NDVI", ["ndvi", "vegetation", "crop", "green", "plant", "वनस्पति", "हरियाली", "फसल"]),
    ("MNDWI", ["mndwi"]),
    ("NDWI", ["ndwi", "water", "जल", "पानी"]),
    ("NDBI", ["ndbi", "built-up", "built up", "urban", "construction", "शहरी"]),
    ("SAVI", ["savi", "soil-adjusted", "sparse vegetation"]),
]


def _month_range(month: int, year: int) -> DateRange:
    return DateRange(start=date(year, month, 1), end=date(year, month, calendar.monthrange(year, month)[1]))


def _extract_dates(text: str, ref: date) -> list:
    t = text.lower()
    found = []
    for m in _ISO.finditer(t):
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        found.append((m.start(), DateRange(start=d, end=d)))
    year_m = _YEAR.search(t)
    year = int(year_m.group(1)) if year_m else ref.year
    for name, num in _MONTHS.items():
        for m in re.finditer(rf"\b{name}\b", t):
            # a month later than the reference month, with no explicit year, means last year
            y = year if year_m or num <= ref.month else year - 1
            found.append((m.start(), _month_range(num, y)))
    found.sort(key=lambda x: x[0])
    seen, out = set(), []
    for _, r in found:
        if (r.start, r.end) not in seen:
            seen.add((r.start, r.end))
            out.append(r)
    return out


def _relative_range(text: str, ref: date) -> Optional[DateRange]:
    t = text.lower()
    if "last year" in t or "past year" in t:
        return DateRange(start=ref - timedelta(days=365), end=ref)
    m = re.search(r"last (\d+) months?", t)
    if m:
        return DateRange(start=ref - timedelta(days=30 * int(m.group(1))), end=ref)
    return None


def _has(text: str, key: str) -> bool:
    return any(k in text for k in KW[key])


def parse_query(text: str, reference_date: Optional[date] = None) -> StructuredQuery:
    ref = reference_date or date.today()
    t = text.lower().strip()
    lang = "hi" if re.search(r"[\u0900-\u097F]", text) else "en"

    index = next((name for name, kws in INDEX_KW if any(k in t for k in kws)), None)
    dates = _extract_dates(text, ref)
    rel = _relative_range(text, ref)
    two_date_compare = bool(index) and len(dates) >= 2 and re.search(r"compare|between|\bvs\b|versus", t)

    if _has(t, "landcover"):
        op = Operation.LAND_COVER
    elif _has(t, "compare_regions"):
        op = Operation.COMPARE_REGIONS
    elif _has(t, "ts"):
        op = Operation.TIME_SERIES
    elif _has(t, "change") or two_date_compare:
        op = Operation.CHANGE_DETECTION
    elif index:
        op = Operation.INDEX_STATS
    else:
        return StructuredQuery(raw_text=text, language=lang, operation=Operation.UNSUPPORTED,
                               unsupported_reason=("I can analyse vegetation/water/built-up indices, "
                                                   "before/after change, time-series trends and land cover."))

    if index is None and op in (Operation.CHANGE_DETECTION, Operation.TIME_SERIES, Operation.INDEX_STATS):
        index = "NDVI" if op != Operation.INDEX_STATS else None

    direction = "decrease" if re.search(r"decreas|declin|loss|कम", t) else (
        "increase" if re.search(r"increas|gain|बढ़", t) else "any")

    q = StructuredQuery(raw_text=text, language=lang, operation=op, index=index, change_direction=direction)

    if op == Operation.CHANGE_DETECTION:
        if len(dates) >= 2:
            q.date_a, q.date_b = dates[0], dates[1]
        q.outputs = ["mean_change", "change_map", "class_statistics", "hotspots"]
    elif op == Operation.TIME_SERIES:
        q.series_range = rel or (DateRange(start=dates[0].start, end=dates[-1].end) if dates else None)
        q.outputs = ["time_series", "trend_test"]
    elif op == Operation.INDEX_STATS:
        if dates:
            q.date_a = dates[0]
        q.outputs = ["statistics", "index_map"]
    elif op == Operation.LAND_COVER:
        if dates:
            q.date_a = dates[0]
        q.outputs = ["class_map", "class_distribution"]
    return validate_query(q)


def validate_query(q: StructuredQuery) -> StructuredQuery:
    """Mark what is missing instead of inventing it. AOI is always taken from the map context."""
    missing = []
    if q.operation == Operation.CHANGE_DETECTION and not (q.date_a and q.date_b):
        missing.append("two comparison periods (e.g. 'June' vs 'September')")
    if q.operation == Operation.TIME_SERIES and not q.series_range:
        missing.append("a time range (e.g. 'last year')")
    if q.operation in (Operation.INDEX_STATS, Operation.LAND_COVER) and not q.date_a:
        missing.append("a date or month")
    if q.operation == Operation.INDEX_STATS and not q.index:
        missing.append("which index (vegetation, water or built-up)")
    q.missing = missing
    return q


def clarification_message(q: StructuredQuery) -> Optional[str]:
    if q.operation == Operation.UNSUPPORTED:
        return q.unsupported_reason
    if q.missing:
        return "Which " + " and ".join(q.missing) + " should I use?"
    return None
