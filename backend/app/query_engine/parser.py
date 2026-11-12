"""Rule-based fallback parser (works with no API key). An LLM parser must emit the same StructuredQuery."""
import calendar
import re
from datetime import date, timedelta
from typing import Optional

from app.schemas.query import DateRange, Operation, StructuredQuery

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS.update({
    "जनवरी": 1,
    "फरवरी": 2, "फ़रवरी": 2,
    "मार्च": 3,
    "अप्रैल": 4,
    "मई": 5,
    "जून": 6,
    "जुलाई": 7,
    "अगस्त": 8,
    "सितंबर": 9, "सितम्बर": 9,
    "अक्टूबर": 10,
    "नवंबर": 11, "नवम्बर": 11,
    "दिसंबर": 12, "दिसम्बर": 12,
})
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_HINDI_COUNTS = {"एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5,
                 "छह": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10}
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
    t = text.lower().translate(_DEVANAGARI_DIGITS)
    found = []
    iso_matches = list(_ISO.finditer(t))
    for m in iso_matches:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        found.append((m.start(), DateRange(start=d, end=d)))

    year_matches = list(_YEAR.finditer(t))
    month_matches = []
    for name, num in _MONTHS.items():
        for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", t):
            month_matches.append((match, num))

    for match, num in month_matches:
        nearest_year = min(year_matches, key=lambda year_match: abs(year_match.start() - match.start()), default=None)
        if nearest_year:
            year = int(nearest_year.group(1))
        else:
            # A month later than the reference month, without an explicit year, means last year.
            year = ref.year if num <= ref.month else ref.year - 1
        found.append((match.start(), _month_range(num, year)))

    if not month_matches and not iso_matches:
        for match in year_matches:
            year = int(match.group(1))
            found.append((match.start(), DateRange(start=date(year, 1, 1), end=date(year, 12, 31))))

    found.sort(key=lambda x: x[0])
    seen, out = set(), []
    for _, r in found:
        if (r.start, r.end) not in seen:
            seen.add((r.start, r.end))
            out.append(r)
    return out


def _relative_range(text: str, ref: date) -> Optional[DateRange]:
    t = text.lower().translate(_DEVANAGARI_DIGITS)
    if "last year" in t or "past year" in t or re.search(r"(?:पिछले|पिछला|पिछली)\s+(?:साल|वर्ष)", t):
        return DateRange(start=ref - timedelta(days=365), end=ref)
    m = re.search(r"(?:last|past)\s+(\d+)\s+months?", t)
    if m:
        return DateRange(start=ref - timedelta(days=30 * int(m.group(1))), end=ref)
    m = re.search(r"(?:last|past)\s+(\d+)\s+years?", t)
    if m:
        return DateRange(start=ref - timedelta(days=365 * int(m.group(1))), end=ref)
    m = re.search(r"(?:पिछले|पिछला|पिछली)\s+(\d+|एक|दो|तीन|चार|पांच|पाँच|छह|सात|आठ|नौ|दस)\s+(?:महीने|महीनों|माह)", t)
    if m:
        count = int(m.group(1)) if m.group(1).isdigit() else _HINDI_COUNTS[m.group(1)]
        return DateRange(start=ref - timedelta(days=30 * count), end=ref)
    m = re.search(r"(?:पिछले|पिछला|पिछली)\s+(\d+|एक|दो|तीन|चार|पांच|पाँच|छह|सात|आठ|नौ|दस)\s+(?:साल|सालों|वर्ष|वर्षों)", t)
    if m:
        count = int(m.group(1)) if m.group(1).isdigit() else _HINDI_COUNTS[m.group(1)]
        return DateRange(start=ref - timedelta(days=365 * count), end=ref)
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
