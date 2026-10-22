"""Mann-Kendall trend test + Sen's slope + robust anomaly flags. No pymannkendall dependency."""
from typing import Sequence
import numpy as np
from scipy.stats import norm

from app.core.config import settings


def mann_kendall(values: Sequence[float], alpha: float = 0.05) -> dict:
    x = np.asarray(values, dtype=np.float64)
    n = len(x)
    s = 0
    for k in range(n - 1):
        s += int(np.sign(x[k + 1:] - x[k]).sum())
    _, counts = np.unique(x, return_counts=True)
    tie = sum(t * (t - 1) * (2 * t + 5) for t in counts if t > 1)
    var_s = (n * (n - 1) * (2 * n + 5) - tie) / 18.0
    if var_s <= 0:
        z = 0.0
    elif s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0
    p = float(2 * (1 - norm.cdf(abs(z))))
    significant = p < alpha
    direction = "no trend" if not significant else ("increasing" if z > 0 else "decreasing")
    return {"n": n, "s": int(s), "var_s": float(var_s), "z": float(z), "p_value": p,
            "alpha": alpha, "significant": bool(significant), "trend": direction}


def sens_slope(t_days: Sequence[float], values: Sequence[float]) -> float:
    """Median pairwise slope, returned per YEAR (365.25 days)."""
    t = np.asarray(t_days, dtype=np.float64)
    x = np.asarray(values, dtype=np.float64)
    slopes = []
    for i in range(len(x) - 1):
        dt = t[i + 1:] - t[i]
        ok = dt != 0
        slopes.extend(((x[i + 1:] - x[i])[ok] / dt[ok]).tolist())
    return float(np.median(slopes) * 365.25) if slopes else 0.0


def robust_anomalies(values: Sequence[float], threshold: float = 3.5) -> list:
    """Indices where |modified z-score| (median/MAD) exceeds threshold."""
    x = np.asarray(values, dtype=np.float64)
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    if mad == 0:
        return []
    mz = 0.6745 * (x - med) / mad
    return [int(i) for i in np.where(np.abs(mz) > threshold)[0]]


def rolling_mean(values: Sequence[float], window: int = 3) -> list:
    x = np.asarray(values, dtype=np.float64)
    if len(x) < window:
        return [float(v) for v in x]
    k = np.ones(window) / window
    r = np.convolve(x, k, mode="valid")
    pad = [float("nan")] * (window - 1)
    return pad + [float(v) for v in r]


def analyse_series(dates_days: Sequence[float], values: Sequence[float]) -> dict:
    """Trend claims only when n >= min_dates_for_trend; otherwise descriptive stats only."""
    x = np.asarray(values, dtype=np.float64)
    out = {
        "n": len(x), "min": float(x.min()), "max": float(x.max()), "mean": float(x.mean()),
        "argmin": int(x.argmin()), "argmax": int(x.argmax()),
        "rolling_mean_3": rolling_mean(x, 3),
        "anomaly_indices": robust_anomalies(x),
        "trend_test": None, "sens_slope_per_year": None,
        "trend_claim_allowed": len(x) >= settings.min_dates_for_trend,
        "caveat": ("Mann-Kendall assumes independent observations; vegetation series are seasonal "
                   "and autocorrelated, so significance is indicative only."),
    }
    if out["trend_claim_allowed"]:
        out["trend_test"] = mann_kendall(x)
        out["sens_slope_per_year"] = sens_slope(dates_days, x)
    return out
