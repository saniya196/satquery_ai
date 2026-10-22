"""Grounded response validator.

The LLM may only phrase results. Every number and date in its answer must exist in the
structured result (within rounding tolerance). Otherwise reject -> regenerate -> template fallback.
"""
import re
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
    if op == "change_detection":
        c = facts["change"]
        direction = "decreased" if c["mean_change"] < 0 else "increased"
        pct = c.get("percent_change_of_mean")
        pct_txt = f" ({abs(pct):.1f}% relative change)" if pct is not None else ""
        sig = c["classes"]["significant_decrease"]
        return (f"Mean {facts['index']} {direction} from {c['mean_a']:.2f} on {facts['date_a']} to "
                f"{c['mean_b']:.2f} on {facts['date_b']}{pct_txt}. "
                f"Pixels with a significant decrease cover {sig['area_km2']:.2f} km2 "
                f"({sig['fraction_of_valid'] * 100:.1f}% of valid pixels). "
                f"Data quality score: {facts['data_quality_score']:.0f}/100.")
    if op == "index_stats":
        s = facts["stats"]
        return (f"Mean {facts['index']} on {facts['date']} is {s['mean']:.2f} "
                f"(median {s['median']:.2f}, std {s['std']:.2f}) over {s['valid_fraction'] * 100:.1f}% valid pixels. "
                f"Data quality score: {facts['data_quality_score']:.0f}/100.")
    if op == "time_series":
        t = facts["series"]
        if t["trend_claim_allowed"]:
            tt = t["trend_test"]
            return (f"Across {t['n']} dates, mean {facts['index']} ranged from {t['min']:.2f} to {t['max']:.2f}. "
                    f"Mann-Kendall trend: {tt['trend']} (p = {tt['p_value']:.3f}). "
                    f"Data quality score: {facts['data_quality_score']:.0f}/100.")
        return (f"Across {t['n']} dates, mean {facts['index']} ranged from {t['min']:.2f} to {t['max']:.2f}. "
                f"There are too few dates for a trend test. "
                f"Data quality score: {facts['data_quality_score']:.0f}/100.")
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
