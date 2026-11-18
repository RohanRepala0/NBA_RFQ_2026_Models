"""Small statistics helpers (no scipy needed). Every interval is 95%.

- wilson(k, n): Wilson score interval for a proportion.
- mean_ci(x): mean with a t interval (t quantiles tabulated for small n).
- paired(a, b): mean of a - b with a t interval (for Brier / log-loss gaps on the same contracts).
- boot_ci(...): percentile bootstrap, iid or clustered (resampling whole groups, e.g. slate dates).
- brier / log_loss / calibration table.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

LOW_CONFIDENCE_N = 100
SEED = 20261118
B = 10_000

# two-sided 95% t quantiles by degrees of freedom; 1.96 beyond 30
_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
         11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
         20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048,
         29: 2.045, 30: 2.042}


def t975(df: int) -> float:
    return _T975.get(df, 1.96) if df >= 1 else float("nan")


def conf_flag(n: int) -> str:
    return "LOW-CONFIDENCE (n<100)" if n < LOW_CONFIDENCE_N else ""


def wilson(k: float, n: int) -> dict:
    if n == 0:
        return {"value": None, "lo": None, "hi": None, "n": 0}
    p, z = k / n, 1.96
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {"value": p, "lo": c - h, "hi": c + h, "n": n}


def mean_ci(x) -> dict:
    x = np.asarray(pd.Series(x).dropna(), float)
    n = len(x)
    if n == 0:
        return {"value": None, "se": None, "lo": None, "hi": None, "n": 0}
    m = float(x.mean())
    if n == 1:
        return {"value": m, "se": None, "lo": None, "hi": None, "n": 1}
    se = float(x.std(ddof=1) / math.sqrt(n))
    t = t975(n - 1)
    return {"value": m, "se": se, "lo": m - t * se, "hi": m + t * se, "n": n}


def paired(a, b) -> dict:
    """Mean of a - b on the same rows, with a t interval."""
    d = np.asarray(a, float) - np.asarray(b, float)
    return mean_ci(d[~np.isnan(d)])


def boot_ci(df: pd.DataFrame, stat, cluster: str | None = None, b: int = B, seed: int = SEED) -> dict:
    """Percentile bootstrap of stat(df). With `cluster`, whole groups are resampled together."""
    rng = np.random.default_rng(seed)
    est = float(stat(df))
    vals = []
    if cluster:
        groups = [g for _, g in df.groupby(cluster, sort=True)]
        k = len(groups)
        for _ in range(b):
            idx = rng.integers(0, k, k)
            vals.append(stat(pd.concat([groups[i] for i in idx], ignore_index=True)))
    else:
        n = len(df)
        arr = df.reset_index(drop=True)
        for _ in range(b):
            vals.append(stat(arr.iloc[rng.integers(0, n, n)]))
    vals = np.asarray(vals, float)
    vals = vals[~np.isnan(vals)]
    return {"value": est, "lo": float(np.percentile(vals, 2.5)), "hi": float(np.percentile(vals, 97.5)),
            "se": float(vals.std(ddof=1)), "n": len(df), "clusters": df[cluster].nunique() if cluster else None,
            "method": f"bootstrap, {b} resamples" + (f", by {cluster}" if cluster else ", by row")}


def brier(p, y) -> np.ndarray:
    return (np.asarray(p, float) - np.asarray(y, float)) ** 2


def log_loss(p, y, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def calibration(p, y, bins: int = 10) -> pd.DataFrame:
    """Reliability table: 10 equal-width probability bins, predicted mean vs actual rate (Wilson CI)."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, bins - 1)
    rows = []
    for i in range(bins):
        m = idx == i
        n = int(m.sum())
        w = wilson(float(y[m].sum()), n) if n else {"value": None, "lo": None, "hi": None}
        rows.append({"bin": f"{edges[i]:.1f}-{edges[i + 1]:.1f}", "n": n,
                     "predicted": float(p[m].mean()) if n else None,
                     "actual": w["value"], "actual_lo": w["lo"], "actual_hi": w["hi"],
                     "gap_actual_minus_predicted": (w["value"] - float(p[m].mean())) if n else None})
    return pd.DataFrame(rows)


def max_drawdown(pnl: pd.Series) -> dict:
    """Largest peak-to-trough fall of the cumulative sum (starting from 0)."""
    cum = np.concatenate([[0.0], np.cumsum(np.asarray(pnl, float))])
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    j = int(dd.argmax())
    i = int(cum[: j + 1].argmax())
    return {"max_drawdown": float(dd[j]), "peak_index": i, "trough_index": j, "peak_value": float(cum[i]),
            "trough_value": float(cum[j])}


def longest_run(flags) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best
