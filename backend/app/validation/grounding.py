"""Grounded response validator.

The LLM may only phrase results. Every number and date in its answer must exist in the
structured result (within rounding tolerance). Otherwise reject -> regenerate -> template fallback.
"""
import re
import math
from typing import Any, Callable, Iterable, Optional

_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUM_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def _flatten_numbers(obj: Any, out: list, dates: set) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        for d in _DATE_RE.findall(obj):
            dates.add(d)
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_numbers(v, out, dates)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _flatten_numbers(v, out, dates)


def _candidates(fact: float) -> list:
    c = [fact, abs(fact), fact * 100, abs(fact * 100)]  # fractions may be quoted as percentages
    return c


def _decimals(text: str) -> int:
    return len(text.split(".")[1]) if "." in text else 0


def _finite_value(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _ndvi_stat(stats: dict, key: str) -> Optional[float]:
    value = _finite_value(stats.get(key))
    if value is None:
        return None
    if key == "std":
        return value if 0.0 <= value <= 1.0 else None
    return value if -1.0 <= value <= 1.0 else None


def _ndvi_answer(facts: dict) -> str:
    """Explain one NDVI observation without assigning universal condition classes."""
    stats = facts.get("stats") if isinstance(facts.get("stats"), dict) else {}
    provenance = facts.get("provenance") if isinstance(facts.get("provenance"), dict) else {}
    parts = ["This is a single-date NDVI snapshot of the selected area and a spectral vegetation proxy derived from near-infrared and red reflectance."]

    area = _finite_value(facts.get("analysed_area_km2"))
    if area is not None:
        parts.append(f"The analyzed area of interest (AOI) is {area:.2f} km2.")

    date = facts.get("date")
    if isinstance(date, str) and _DATE_RE.fullmatch(date):
        parts.append(f"The image was acquired on {date}.")

    cloud = _finite_value(provenance.get("cloud_cover"))
    if cloud is not None:
        parts.append(f"Scene cloud cover was {cloud:.1f}%.")

    labels = (("mean", "mean"), ("median", "median"), ("std", "standard deviation"),
              ("min", "minimum"), ("max", "maximum"))
    measured = []
    for key, label in labels:
        value = _ndvi_stat(stats, key)
        if value is not None:
            measured.append((key, label, value))
    vals = {key: value for key, _, value in measured}
    if "min" in vals and "max" in vals and vals["min"] > vals["max"]:
        measured = [(key, label, value) for key, label, value in measured if key not in ("min", "max")]
        vals.pop("min", None)
        vals.pop("max", None)
    if "min" in vals and "mean" in vals and not vals["min"] <= vals["mean"]:
        measured = [(key, label, value) for key, label, value in measured if key != "mean"]
        vals.pop("mean", None)
    if "max" in vals and "mean" in vals and not vals["mean"] <= vals["max"]:
        measured = [(key, label, value) for key, label, value in measured if key != "mean"]
        vals.pop("mean", None)
    if measured:
        parts.append("Measured NDVI: " + "; ".join(f"{label} {value:.3f}" for _, label, value in measured) + ".")
        values = {key: value for key, _, value in measured}
        if "mean" in values or "median" in values:
            center = []
            if "mean" in values:
                center.append(f"mean {values['mean']:.3f}")
            if "median" in values:
                center.append(f"median {values['median']:.3f}")
            parts.append(
                f"The {' and '.join(center)} summarize the AOI-wide vegetation greenness signal. "
                "Higher NDVI generally means a stronger green-vegetation signal in this image, but NDVI alone does not measure plant health."
            )
        if "std" in values:
            parts.append(f"The standard deviation of {values['std']:.3f} describes how spread out pixel values are around the mean.")
        if "min" in values and "max" in values:
            parts.append(f"The observed range runs from {values['min']:.3f} to {values['max']:.3f}; these area-wide statistics do not locate the low or high pixels.")
    else:
        parts.append("NDVI summary statistics are unavailable or invalid, so no vegetation level can be described from them.")

    valid = _finite_value(stats.get("valid_fraction"))
    if valid is not None and 0.0 <= valid <= 1.0:
        parts.append(f"Valid-pixel coverage is {valid * 100:.1f}% of the AOI after masking.")
    else:
        parts.append("Valid-pixel coverage is unavailable or invalid.")

    coverage = _finite_value(stats.get("coverage_fraction"))
    threshold = _finite_value((facts.get("thresholds") or {}).get("vegetation_ndvi"))
    if coverage is not None and 0.0 <= coverage <= 1.0 and threshold is not None:
        parts.append(f"{coverage * 100:.1f}% of valid pixels meet this project's NDVI threshold of {threshold:.2f}; this is a configurable screening rule, not a universal vegetation boundary.")

    parts.append("Low, moderate, and high NDVI labels depend on local conditions and the chosen convention; these statistics are not ground-truth condition classes. One observation does not establish a cause and cannot show vegetation loss or improvement.")

    if facts.get("spatial_evidence_available") is True:
        parts.append("The pixel map contains spatial evidence for where NDVI varies; inspect it for location-specific patterns, since these summary statistics do not describe their positions.")

    scene_ids = provenance.get("scene_ids")
    provider = provenance.get("provider")
    if isinstance(scene_ids, list) and scene_ids:
        source = f"Satellite source: {provider}. " if isinstance(provider, str) and provider else "Satellite source provenance is recorded. "
        source += "Scene ID(s): " + ", ".join(str(item) for item in scene_ids if isinstance(item, str)) + "."
        parts.append(source)

    quality = _finite_value(facts.get("data_quality_score"))
    if quality is not None:
        parts.append(f"Data quality score: {quality:.0f}/100.")
    return " ".join(parts)


def check_grounding(answer: str, facts: dict, allowed_literals: Iterable[float] = ()) -> dict:
    nums, dates = [], set()
    _flatten_numbers(facts, nums, dates)
    for lit in allowed_literals:
        nums.append(float(lit))
    nums.append(100.0)  # scale of the 0-100 quality score ("91/100")

    ungrounded_dates = [d for d in _DATE_RE.findall(answer) if d not in dates]
    stripped = _DATE_RE.sub(" ", answer)

    ungrounded = []
    for m in _NUM_RE.findall(stripped):
        raw = m.replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        d = _decimals(raw)
        tol = 0.5 * 10 ** (-d) + 1e-9
        ok = any(abs(abs(val) - abs(c)) <= tol for f in nums for c in _candidates(f))
        if not ok:
            ungrounded.append(m)
    return {"valid": not ungrounded and not ungrounded_dates,
            "ungrounded_numbers": ungrounded, "ungrounded_dates": ungrounded_dates}


def template_answer(facts: dict) -> str:
    """Deterministic fallback. Built only from fields in `facts`."""
    op = facts.get("operation")
    provenance = facts.get("provenance") or {}
    scene_ids = provenance.get("scene_ids") or []
    provider = provenance.get("provider")
    area = facts.get("analysed_area_km2")
    quality = facts.get("data_quality_score")
    quality_text = f" Data quality score: {quality:.0f}/100." if quality is not None else ""
    source_text = (f" Satellite-data provenance: {provider}, scene ID(s) {', '.join(scene_ids)}." if provider and scene_ids
                   else f" Satellite-data scene ID(s): {', '.join(scene_ids)}." if scene_ids else "")
    area_text = f" The analyzed area is {area:.2f} km2." if area is not None else ""
    if op == "index_stats" and str(facts.get("index", "")).upper() == "NDVI":
        return _ndvi_answer(facts)
    if op == "change_detection":
        c = facts["change"]
        direction = "decreased" if c["mean_change"] < 0 else "increased" if c["mean_change"] > 0 else "was unchanged"
        pct = c.get("percent_change_of_mean")
        pct_txt = f" ({abs(pct):.1f}% relative change)" if pct is not None else ""
        sig = c["classes"]["significant_decrease"]
        classes = c["classes"]
        class_summary = "; ".join(
            f"{name.replace('_', ' ')}: {item['area_km2']:.2f} km2 ({item['fraction_of_valid'] * 100:.1f}% of valid pixels)"
            for name, item in classes.items() if isinstance(item, dict) and item.get("area_km2") is not None
            and item.get("fraction_of_valid") is not None)
        text = (f"This compares {facts['index']} across the analyzed area{area_text} on {facts['date_a']} and "
                f"{facts['date_b']}. The AOI-wide mean {direction} from {c['mean_a']:.2f} to {c['mean_b']:.2f}{pct_txt}; "
                f"this describes the measured index difference and does not identify its cause. "
                f"The significant-decrease category covers {sig['area_km2']:.2f} km2 "
                f"({sig['fraction_of_valid'] * 100:.1f}% of valid pixels).")
        if class_summary:
            text += f" Measured category areas: {class_summary}."
        text += " The change map shows where the classified differences occur; category thresholds affect these areas."
        hotspot_summary = facts.get("hotspot_summary") or {}
        if hotspot_summary.get("count") is not None:
            text += f" The pipeline identified {hotspot_summary['count']} spatial hotspot cluster(s) meeting its configured criteria."
            text += " These clusters locate measured index changes and do not explain why they occurred."
        return text + source_text + quality_text
    if op == "index_stats":
        s = facts["stats"]
        name = facts["index"].upper()
        meanings = {
            "NDVI": "NDVI is a spectral greenness signal commonly used as a vegetation proxy.",
            "NDWI": "This NDWI formulation highlights a spectral water signal; built surfaces can sometimes resemble water in this index.",
            "MNDWI": "MNDWI is a modified spectral water signal designed to better separate water from built-up surfaces.",
            "NDBI": "NDBI highlights a built-up surface signal, but bare soil can also produce similar values.",
            "SAVI": "SAVI is a soil-adjusted vegetation signal, intended to reduce some soil-background effects.",
        }.get(name, f"{name} is the spectral index calculated for this observation.")
        spread = f" Values ranged from {s['min']:.3f} to {s['max']:.3f}, with a standard deviation of {s['std']:.3f}." if s.get("min") is not None and s.get("max") is not None and s.get("std") is not None else ""
        scene_cov = facts.get("coverage") or {}
        scene_cov_text = (f" The imagery footprint covers {scene_cov['fraction'] * 100:.1f}% of the AOI."
                          if scene_cov.get("fraction") is not None else "")
        area_sentence = f" The analyzed AOI area is {area:.2f} km2." if area is not None else ""
        text = (f"This analyzes {name} for the AOI on {facts['date']}.{area_sentence} The mean is {s['mean']:.3f} "
                f"and the median is {s['median']:.3f}; {s['valid_fraction'] * 100:.1f}% of AOI pixels had valid measurements."
                f"{scene_cov_text} "
                f"{meanings}{spread} These area-wide summaries do not show where values occur, so use the map to inspect spatial variation. "
                "A single index observation does not establish a cause or a change over time.")
        return text + source_text + quality_text
    if op == "time_series":
        t = facts["series"]
        dates = t.get("dates") or []
        date_text = f" from {dates[0]} to {dates[-1]}" if dates else ""
        valid = t.get("mean_valid_fraction_of_aoi_included")
        valid_text = f" Mean valid-pixel coverage was {valid * 100:.1f}%." if valid is not None else ""
        if t["trend_claim_allowed"]:
            tt = t["trend_test"]
            slope = facts.get("sens_slope_per_year")
            slope_text = f" Sen's slope is {slope:.3f} index units per year." if slope is not None else ""
            text = (f"This tracks per-date AOI median {facts['index']} across {t['n']} usable dates{date_text}. "
                    f"Values ranged from {t['min']:.2f} to {t['max']:.2f}; the Mann-Kendall result is {tt['trend']} "
                    f"(p = {tt['p_value']:.3f}).{slope_text} This describes the observed series, not its cause. "
                    f"Because seasonality and autocorrelation can affect the trend test, interpret it cautiously.{valid_text}")
        else:
            text = (f"This tracks per-date AOI median {facts['index']} across {t['n']} usable dates{date_text}. "
                    f"Values ranged from {t['min']:.2f} to {t['max']:.2f}, but there are too few dates with usable observations for a trend test. "
                    f"This is a description of the observations, not evidence of a long-term direction.{valid_text}")
        return text + source_text + quality_text
    if op == "land_cover":
        dom = facts["dominant_class"].replace("_", " ")
        return (f"Dominant land cover on {facts['date']} is {dom} "
                f"({facts['dominant_fraction'] * 100:.1f}% of the classified area). "
                f"{facts['classified_fraction'] * 100:.1f}% of the area was classified by a multispectral ResNet18 "
                f"(EuroSAT test accuracy {facts['model_test_accuracy'] * 100:.1f}%); mean model confidence "
                f"{facts['mean_model_confidence'] * 100:.1f}% is a model score, not certainty. "
                f"Data quality score: {facts['data_quality_score']:.0f}/100.")
    return "Analysis complete. See the evidence panel for the measured values."


def grounded_answer(facts: dict, llm_fn: Optional[Callable[[dict, Optional[list]], str]] = None,
                    max_retries: int = 2, allowed_literals: Iterable[float] = (8,)) -> dict:
    """llm_fn(facts, previous_errors) -> text. Falls back to the template when grounding fails."""
    attempts, errors = 0, None
    if llm_fn is not None:
        for _ in range(max_retries + 1):
            attempts += 1
            try:
                text = llm_fn(facts, errors)
            except Exception as exc:  # LLM/API failure must never block a result
                errors = [f"llm_error: {exc}"]
                continue
            verdict = check_grounding(text, facts, allowed_literals)
            if verdict["valid"]:
                return {"text": text, "source": "llm", "attempts": attempts}
            errors = verdict["ungrounded_numbers"] + verdict["ungrounded_dates"]
    return {"text": template_answer(facts), "source": "template", "attempts": attempts}
