"""Compare-only planning and execution using verified, date-matched scenes."""
from datetime import date, datetime, timezone
import math
from typing import Optional

from app.core.config import settings
from app.core.errors import InsufficientDataError, NoImageryError
from app.satellite.provider import SatelliteProvider
from app.schemas.query import Operation
from app.services import analysis, land_cover

MIN_SCENE_COVERAGE = 0.99


def _utc_date(value) -> date:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Scene acquisition timestamp is missing or invalid.") from exc
    if parsed.tzinfo is None:
        raise ValueError("Scene acquisition timestamp has no UTC offset.")
    return parsed.astimezone(timezone.utc).date()


def _processing_level(value) -> Optional[str]:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip().upper().replace("_", "").replace("-", "")
    if "L2A" in normalized or "MSI2A" in normalized:
        return "L2A"
    if "L1C" in normalized or "MSI1C" in normalized:
        return "L1C"
    return normalized


def _valid_candidates(items: list[dict], start: date, end: date, max_cloud: float) -> list[dict]:
    valid = []
    for item in items:
        try:
            acquired = _utc_date(item.get("datetime"))
            if isinstance(item.get("cloud_cover"), bool):
                continue
            cloud = float(item.get("cloud_cover"))
            coverage_value = item.get("coverage_fraction")
            if coverage_value is None:
                coverage_value = item.get("coverage")
            if isinstance(coverage_value, bool):
                continue
            coverage = float(coverage_value)
            collection = item.get("collection")
        except (TypeError, ValueError, OverflowError):
            continue
        if (item.get("item_id") and start <= acquired <= end and
                math.isfinite(cloud) and cloud <= max_cloud and
                math.isfinite(coverage) and coverage >= MIN_SCENE_COVERAGE and coverage <= 1.01 and
                isinstance(collection, str) and collection.strip()):
            candidate = dict(item)
            candidate["_utc_date"] = acquired
            candidate["_cloud"] = cloud
            candidate["_coverage"] = min(1.0, coverage)
            candidate["_collection"] = collection.strip()
            candidate["_processing"] = _processing_level(item.get("processing_level"))
            valid.append(candidate)
    return valid


def select_scene_pairs(provider: SatelliteProvider, aoi_a: dict, aoi_b: dict,
                       start: date, end: date, max_cloud: float) -> list[tuple[dict, dict]]:
    """Return verified catalog candidates paired by actual UTC date and collection."""
    if end < start:
        raise NoImageryError("The Compare date range is invalid. Set an end date on or after the start date.")
    try:
        scenes_a = provider.list_scenes(aoi_a, start, end, max_cloud)
        scenes_b = provider.list_scenes(aoi_b, start, end, max_cloud)
    except Exception as exc:
        if isinstance(exc, NoImageryError):
            raise
        raise NoImageryError("Could not discover comparable Sentinel-2 scenes for both areas. Retry the comparison.") from exc
    candidates_a = _valid_candidates(scenes_a, start, end, max_cloud)
    candidates_b = _valid_candidates(scenes_b, start, end, max_cloud)

    by_date_a: dict[date, list[dict]] = {}
    by_date_b: dict[date, list[dict]] = {}
    for candidate in candidates_a:
        by_date_a.setdefault(candidate["_utc_date"], []).append(candidate)
    for candidate in candidates_b:
        by_date_b.setdefault(candidate["_utc_date"], []).append(candidate)

    pairs_by_date: dict[date, list[tuple[dict, dict]]] = {}
    for acquired in by_date_a.keys() & by_date_b.keys():
        pairs = []
        for left in by_date_a[acquired]:
            for right in by_date_b[acquired]:
                if left["_collection"] != right["_collection"]:
                    continue
                left_level, right_level = left["_processing"], right["_processing"]
                if left_level and right_level and left_level != right_level:
                    continue
                pairs.append((left, right))
        if pairs:
            # Prefer a single footprint covering both areas, then the clearest pair.
            pairs.sort(key=lambda pair: (
                0 if pair[0]["item_id"] == pair[1]["item_id"] else 1,
                pair[0]["_cloud"] + pair[1]["_cloud"],
                pair[0]["item_id"], pair[1]["item_id"],
            ))
            pairs_by_date[acquired] = pairs

    if not pairs_by_date:
        raise NoImageryError(
            f"No comparable Sentinel-2 observations were found for both areas from {start} to {end}. "
            f"A valid pair must have the same UTC acquisition date and collection, compatible processing levels, "
            f"known coverage of at least 99% for each area, and cloud cover at or below {max_cloud:g}%. "
            "Try a wider date range or a higher cloud threshold."
        )
    return [pairs_by_date[acquired][0] for acquired in sorted(pairs_by_date)]


def _verify_result_pairs(result_a: dict, result_b: dict, planned_pairs: list[tuple[dict, dict]],
                         max_cloud: float) -> None:
    scenes_a = result_a.get("evidence", {}).get("scenes", [])
    scenes_b = result_b.get("evidence", {}).get("scenes", [])
    if len(scenes_a) != len(planned_pairs) or len(scenes_b) != len(planned_pairs):
        raise NoImageryError("The analyzed results do not contain every planned matched observation; comparison stopped.")
    for index, (planned_a, planned_b) in enumerate(planned_pairs):
        actual_a, actual_b = scenes_a[index], scenes_b[index]
        for actual, planned in ((actual_a, planned_a), (actual_b, planned_b)):
            try:
                coverage = actual.get("coverage_fraction")
                cloud = actual.get("cloud_cover")
                if (actual.get("item_id") != planned["item_id"] or
                        _utc_date(actual.get("datetime")) != planned["_utc_date"] or
                        actual.get("collection") != planned["_collection"] or
                        not isinstance(coverage, (int, float)) or isinstance(coverage, bool) or
                        not math.isfinite(coverage) or coverage < MIN_SCENE_COVERAGE or coverage > 1.01 or
                        not isinstance(cloud, (int, float)) or isinstance(cloud, bool) or
                        not math.isfinite(cloud) or cloud > max_cloud):
                    raise ValueError("scene metadata does not match its verified catalog candidate")
            except (TypeError, ValueError) as exc:
                raise NoImageryError(
                    "Catalog metadata changed or could not be verified while reading a planned Compare scene. "
                    "No substitute scene was used; retry the comparison."
                ) from exc
        if _utc_date(actual_a["datetime"]) != _utc_date(actual_b["datetime"]):
            raise NoImageryError("The analyzed AOIs did not use the same acquisition date; comparison stopped.")
        collection_a, collection_b = actual_a.get("collection"), actual_b.get("collection")
        if not collection_a or collection_a != collection_b:
            raise NoImageryError("The analyzed scenes do not share a verified Sentinel-2 collection.")
        level_a, level_b = _processing_level(actual_a.get("processing_level")), _processing_level(actual_b.get("processing_level"))
        if level_a and level_b and level_a != level_b:
            raise NoImageryError("The analyzed scenes have incompatible processing levels.")


def _best_pair(pairs: list[tuple[dict, dict]]) -> tuple[dict, dict]:
    return min(pairs, key=lambda pair: (
        0 if pair[0]["item_id"] == pair[1]["item_id"] else 1,
        pair[0]["_cloud"] + pair[1]["_cloud"],
        pair[0]["_utc_date"],
    ))


def run_compare_operation(q, aoi_a: dict, aoi_b: dict, provider: SatelliteProvider,
                          max_cloud: float, llm_fn, classifier=None) -> tuple[dict, dict]:
    """Run the same supported operation for two AOIs using only planned scene pairs."""
    if q.operation == Operation.INDEX_STATS:
        if not q.date_a or not q.index:
            raise NoImageryError("Compare needs an index and date range. Add them to the question and retry.")
        pair = _best_pair(select_scene_pairs(provider, aoi_a, aoi_b, q.date_a.start, q.date_a.end, max_cloud))
        left = analysis.run_index_stats(provider, aoi_a, q.date_a, q.index, max_cloud,
                                        llm_fn=llm_fn, selected_scene_id=pair[0]["item_id"],
                                        compare_utc_date=True)
        right = analysis.run_index_stats(provider, aoi_b, q.date_a, q.index, max_cloud,
                                         llm_fn=llm_fn, selected_scene_id=pair[1]["item_id"],
                                         compare_utc_date=True)
        _verify_result_pairs(left, right, [pair], max_cloud)
        return left, right

    if q.operation == Operation.LAND_COVER:
        if not q.date_a:
            raise NoImageryError("Compare needs a date range for land-cover analysis. Add one and retry.")
        pair = _best_pair(select_scene_pairs(provider, aoi_a, aoi_b, q.date_a.start, q.date_a.end, max_cloud))
        if classifier is None:
            raise NoImageryError("The land-cover model is unavailable for Compare. Try another analysis type.")
        left = land_cover.run_land_cover(provider, aoi_a, q.date_a, classifier, max_cloud,
                                         llm_fn=llm_fn, selected_scene_id=pair[0]["item_id"],
                                         compare_utc_date=True)
        right = land_cover.run_land_cover(provider, aoi_b, q.date_a, classifier, max_cloud,
                                          llm_fn=llm_fn, selected_scene_id=pair[1]["item_id"],
                                          compare_utc_date=True)
        _verify_result_pairs(left, right, [pair], max_cloud)
        return left, right

    if q.operation == Operation.CHANGE_DETECTION:
        if not q.date_a or not q.date_b or not q.index:
            raise NoImageryError("Compare change detection needs before and after date ranges. Add both and retry.")
        before = _best_pair(select_scene_pairs(provider, aoi_a, aoi_b, q.date_a.start, q.date_a.end, max_cloud))
        after = _best_pair(select_scene_pairs(provider, aoi_a, aoi_b, q.date_b.start, q.date_b.end, max_cloud))
        left = analysis.run_change(provider, aoi_a, q.date_a, q.date_b, q.index, q.thresholds or None,
                                   max_cloud, llm_fn=llm_fn,
                                   selected_scene_ids=(before[0]["item_id"], after[0]["item_id"]))
        right = analysis.run_change(provider, aoi_b, q.date_a, q.date_b, q.index, q.thresholds or None,
                                    max_cloud, llm_fn=llm_fn,
                                    selected_scene_ids=(before[1]["item_id"], after[1]["item_id"]))
        _verify_result_pairs(left, right, [before, after], max_cloud)
        return left, right

    if q.operation == Operation.TIME_SERIES:
        if not q.series_range or not q.index:
            raise NoImageryError("Compare time series needs an index and date range. Add them and retry.")
        pairs = select_scene_pairs(provider, aoi_a, aoi_b, q.series_range.start,
                                   q.series_range.end, max_cloud)[:60]
        minimum = int(getattr(settings, "min_dates_for_trend", 8))
        if len(pairs) < minimum:
            raise InsufficientDataError(
                f"Only {len(pairs)} matched, verified acquisition dates are available for both areas; "
                f"at least {minimum} are required for a comparable time series. Widen the date range or adjust cloud cover."
            )
        left_scenes = [pair[0] for pair in pairs]
        right_scenes = [pair[1] for pair in pairs]
        left = analysis.run_time_series(provider, aoi_a, q.series_range, q.index, max_cloud,
                                        llm_fn=llm_fn, selected_scenes=left_scenes,
                                        require_all_selected=True)
        right = analysis.run_time_series(provider, aoi_b, q.series_range, q.index, max_cloud,
                                         llm_fn=llm_fn, selected_scenes=right_scenes,
                                         require_all_selected=True)
        dates_a = left["facts"]["series"]["dates"]
        dates_b = right["facts"]["series"]["dates"]
        if dates_a != dates_b:
            raise NoImageryError("Comparable time-series dates could not be verified for both areas. Retry with another date range.")
        if len(dates_a) < minimum:
            raise InsufficientDataError(
                f"Only {len(dates_a)} matched dates had sufficient valid pixels in both areas; "
                f"at least {minimum} are required. Widen the date range or adjust cloud cover."
            )
        _verify_result_pairs(left, right, pairs, max_cloud)
        return left, right

    raise NoImageryError(f"Compare does not support the parsed operation '{q.operation.value}'.")
