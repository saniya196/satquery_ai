from datetime import date
from app.query_engine.parser import clarification_message, parse_query
from app.schemas.query import Operation

REF = date(2026, 10, 7)


def test_change_with_two_months():
    q = parse_query("Did vegetation health decrease between June and September?", REF)
    assert q.operation == Operation.CHANGE_DETECTION and q.index == "NDVI" and q.change_direction == "decrease"
    assert q.date_a.start == date(2026, 6, 1) and q.date_b.end == date(2026, 9, 30) and not q.missing


def test_missing_periods_asks_back():
    q = parse_query("Did vegetation decrease?", REF)
    assert q.missing and "comparison periods" in clarification_message(q)


def test_water_percentage_needs_a_date():
    q = parse_query("What percentage of this area is water?", REF)
    assert q.operation == Operation.INDEX_STATS and q.index == "NDWI" and q.missing


def test_trend_last_year():
    q = parse_query("Show me the vegetation trend over the last year", REF)
    assert q.operation == Operation.TIME_SERIES and q.series_range.end == REF and not q.missing


def test_land_cover_and_compare_regions():
    assert parse_query("What is the dominant land cover in this area?", REF).operation == Operation.LAND_COVER
    assert parse_query("Compare vegetation health between Field A and Field B", REF).operation == Operation.COMPARE_REGIONS


def test_unsupported_query_explains_capabilities():
    q = parse_query("Write me a poem about rivers", REF)
    assert q.operation == Operation.UNSUPPORTED and "analyse" in clarification_message(q)


def test_hindi_and_english_map_to_same_intent():
    en = parse_query("Is vegetation health decreasing?", REF)
    hi = parse_query("क्या इस क्षेत्र में वनस्पति की स्थिति कम हुई है?", REF)
    assert hi.language == "hi" and en.language == "en"
    assert (hi.operation, hi.index, hi.change_direction) == (en.operation, en.index, en.change_direction)


def test_iso_dates():
    q = parse_query("Compare NDVI between 2026-01-10 and 2026-09-10", REF)
    assert q.date_a.start == date(2026, 1, 10) and q.date_b.start == date(2026, 9, 10)


def test_hindi_month_and_year_parse_without_llm():
    q = parse_query("जून 2026 में NDVI दिखाएं", REF)
    assert q.language == "hi" and q.operation == Operation.INDEX_STATS
    assert q.date_a.start == date(2026, 6, 1) and q.date_a.end == date(2026, 6, 30)
    assert not q.missing


def test_hindi_last_year_trend_parses_without_llm():
    q = parse_query("पिछले साल का NDVI रुझान दिखाएं", REF)
    assert q.language == "hi" and q.operation == Operation.TIME_SERIES
    assert q.series_range.start == date(2025, 10, 7) and q.series_range.end == REF
    assert not q.missing


def test_hindi_relative_month_range_accepts_devanagari_digits():
    q = parse_query("पिछले १२ महीनों का NDVI रुझान", REF)
    assert q.language == "hi" and q.operation == Operation.TIME_SERIES
    assert q.series_range.start == date(2025, 10, 12) and q.series_range.end == REF
    assert not q.missing


def test_explicit_multi_year_trend_uses_full_calendar_years():
    q = parse_query("Show NDVI trend from 2022 to 2025", REF)
    assert q.operation == Operation.TIME_SERIES
    assert q.series_range.start == date(2022, 1, 1)
    assert q.series_range.end == date(2025, 12, 31)
    assert not q.missing


def test_hindi_explicit_multi_year_trend_uses_calendar_year_bounds():
    q = parse_query("2023 से 2025 तक NDVI का रुझान दिखाएं", REF)
    assert q.language == "hi" and q.operation == Operation.TIME_SERIES
    assert q.series_range.start == date(2023, 1, 1)
    assert q.series_range.end == date(2025, 12, 31)
    assert not q.missing


def test_year_only_index_query_uses_the_explicit_calendar_year():
    q = parse_query("Show NDWI for 2025", REF)
    assert q.operation == Operation.INDEX_STATS and q.index == "NDWI"
    assert q.date_a.start == date(2025, 1, 1) and q.date_a.end == date(2025, 12, 31)
    assert not q.missing
