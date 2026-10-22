"""Deterministic data-quality score. Same inputs -> same score. Weights live in core/config.py."""
from typing import Optional
from app.core.config import CONFIDENCE_WEIGHTS


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_confidence(*, valid_fraction: float, cloud_cover_pct: Optional[float] = None,
                       temporal_gap_days: Optional[float] = None, n_dates_used: Optional[int] = None,
                       n_dates_requested: Optional[int] = None, model_confidence: Optional[float] = None,
                       trend_significant: Optional[bool] = None, trend_n: Optional[int] = None) -> dict:
    factors = []

    def add(name, value, score01, why):
        factors.append({"factor": name, "value": value, "score": round(score01 * 100, 1),
                        "weight": CONFIDENCE_WEIGHTS[name], "explanation": why})

    # 0.30 valid -> 0 points, >= 0.90 valid -> 100 points, linear in between.
    add("valid_pixels", round(valid_fraction, 4), _clip01((valid_fraction - 0.30) / 0.60),
        f"{valid_fraction:.1%} of AOI pixels were usable (100 at >=90%, 0 at <=30%).")
    if cloud_cover_pct is not None:
        add("cloud_cover", round(cloud_cover_pct, 2), _clip01(1 - cloud_cover_pct / 50.0),
            f"Scene cloud cover {cloud_cover_pct:.1f}% (100 at 0%, 0 at >=50%).")
    if temporal_gap_days is not None:
        g = temporal_gap_days
        if g < 14:
            s = _clip01(g / 14.0)
            why = f"Dates only {g:.0f} days apart; change may be within noise."
        elif g > 365:
            s = _clip01(1 - (g - 365) / 365.0)
            why = f"Dates {g:.0f} days apart; seasonal effects may confound comparison."
        else:
            s, why = 1.0, f"Dates {g:.0f} days apart (14-365 day window)."
        add("temporal_separation", round(g, 1), s, why)
    if n_dates_used is not None and n_dates_requested:
        add("data_availability", f"{n_dates_used}/{n_dates_requested}",
            _clip01(n_dates_used / n_dates_requested),
            f"{n_dates_used} of {n_dates_requested} requested dates had usable imagery.")
    if model_confidence is not None:
        add("model_confidence", round(model_confidence, 4), _clip01(model_confidence),
            "Mean classifier confidence (a model score, not scientific certainty).")
    if trend_n is not None:
        from app.core.config import settings
        enough = _clip01(trend_n / (2 * settings.min_dates_for_trend))
        add("statistical_support", f"n={trend_n}, significant={trend_significant}", enough,
            f"{trend_n} dates available for trend testing (full support at {2 * settings.min_dates_for_trend}).")

    total_w = sum(f["weight"] for f in factors)
    score = sum(f["score"] * f["weight"] for f in factors) / total_w if total_w else 0.0
    for f in factors:
        f["normalised_weight"] = round(f["weight"] / total_w, 4)
    return {"score": round(score, 1), "breakdown": factors,
            "method": "Weighted mean of per-factor 0-100 scores; weights renormalised over applicable factors."}
