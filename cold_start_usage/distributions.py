"""Per-stat outcome distributions: where a mean becomes a probability.

- points: normal with SD = max(4, 0.30 m) (odds_math), and for robust pricing a
  second, compound-Poisson SD sqrt(2.2 m + (0.15 m)^2). These are the same
  functions the points path always used, so points prices don't move.
- rebounds, assists: counts. Negative binomial with Var = phi * m
  (r = m / (phi - 1), success probability 1 / phi; phi <= 1 is Poisson), with an
  exact discrete CDF from lgamma pmf terms. Robust pricing takes the lower of
  phi and phi_alt (config.COUNT_DISPERSION).

Lines are X.5, so for a count P(X > 7.5) = P(X >= 8). Pure Python (no scipy).
"""
from __future__ import annotations

import math

from . import config
from .config import MODEL, ModelParams
from .odds_math import implied_mean as normal_implied_mean
from .odds_math import p_over_normal, points_sd

COUNT_MEAN_MAX = 60.0            # bisection ceiling for a count mean (no player averages 60 boards)


def check_stat(stat: str) -> str:
    if stat not in config.STATS:
        raise ValueError(f"Unknown stat {stat!r}; choose from {config.STATS}")
    return stat


def dispersion(stat: str) -> tuple[float, float]:
    """(phi, phi_alt) for a count stat: Var = phi * mean."""
    return config.COUNT_DISPERSION[check_stat(stat)]


def sd_compound(mean: float, ab: tuple[float, float] = config.SD_COMPOUND) -> float:
    a, b = ab
    return math.sqrt(max(a * mean + (b * mean) ** 2, 1e-9))


def sd(stat: str, mean: float, params: ModelParams = MODEL) -> float:
    """The centre model's SD: points max(4, 0.30 m); counts sqrt(phi * m)."""
    if check_stat(stat) == "points":
        return points_sd(mean, params)
    phi, _ = dispersion(stat)
    return math.sqrt(max(phi, 1.0) * max(mean, 0.0))


def count_sf(mean: float, line: float, phi: float) -> float:
    """P(X > line) for a count with this mean and Var = phi * mean (phi <= 1: Poisson)."""
    if line < 0:
        return 1.0
    if mean <= 0:
        return 0.0                                   # X = 0 for sure
    n = math.floor(line)                             # P(X > line) = 1 - P(X <= floor(line))
    if phi <= 1.0:
        log_m = math.log(mean)
        cdf = sum(math.exp(k * log_m - mean - math.lgamma(k + 1)) for k in range(n + 1))
    else:
        r, p = mean / (phi - 1.0), 1.0 / phi
        head = r * math.log(p) - math.lgamma(r)
        log_q = math.log1p(-p)
        cdf = sum(math.exp(math.lgamma(k + r) - math.lgamma(k + 1) + head + k * log_q) for k in range(n + 1))
    return min(1.0, max(0.0, 1.0 - cdf))


def p_over(stat: str, mean: float, line: float, params: ModelParams = MODEL, phi: float | None = None) -> float:
    """P(X > line) under the centre model (or a given phi, for counts)."""
    if check_stat(stat) == "points":
        return p_over_normal(mean, line, params=params)
    return count_sf(mean, line, dispersion(stat)[0] if phi is None else phi)


def implied_mean(stat: str, line: float, p: float, params: ModelParams = MODEL) -> float:
    """Mean m with P(X > line) == p under the centre model. P(over) rises with m, so bisect.
    Clamped to [0, COUNT_MEAN_MAX] for counts when p is beyond what that range produces."""
    if check_stat(stat) == "points":
        return normal_implied_mean(line, p, params)
    if not 0.0 < p < 1.0:
        raise ValueError(f"p_over must be in (0, 1): {p}")
    lo, hi = 0.0, COUNT_MEAN_MAX
    for _ in range(200):
        mid = (lo + hi) / 2
        if p_over(stat, mid, line, params) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return (lo + hi) / 2


def normal_side_p(mean: float, line: float, side: str, sd_: float) -> float:
    """P(YES) = P(points > line) for side YES, else 1 - that, for N(mean, sd_). Lines are X.5."""
    p = p_over_normal(mean, line, sd=sd_)
    return p if side == "YES" else 1.0 - p


def side_p(stat: str, mean: float, line: float, side: str, params: ModelParams = MODEL,
           phi: float | None = None) -> float:
    """P(this side wins) under the centre model: YES pays if X > line."""
    if check_stat(stat) == "points":
        return normal_side_p(mean, line, side, points_sd(mean, params))
    p = p_over(stat, mean, line, params, phi)
    return p if side == "YES" else 1.0 - p


def robust_p(stat: str, mean: float, line: float, side: str, params: ModelParams = MODEL) -> tuple[float, float]:
    """(lower of the two models, spread between them). Points: the linear and the
    compound-Poisson SD. Counts: phi and phi_alt."""
    if check_stat(stat) == "points":
        p1 = normal_side_p(mean, line, side, points_sd(mean, params))
        p2 = normal_side_p(mean, line, side, sd_compound(mean))
    else:
        phi, phi_alt = dispersion(stat)
        p1 = side_p(stat, mean, line, side, params, phi)
        p2 = side_p(stat, mean, line, side, params, phi_alt)
    return min(p1, p2), abs(p1 - p2)


def unit(stat: str) -> str:
    """'pts', 'reb', 'ast': for messages such as 'model +1.2 reb from market'."""
    return config.STAT_LABELS[check_stat(stat)].lower()
