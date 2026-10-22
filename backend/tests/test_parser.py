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
