"""American odds <-> probability, vig removal, and the normal points model.

Vig removal methods (all return probabilities that sum to 1):
- multiplicative: p_i = q_i / sum(q)
- power:          p_i = q_i ** k, with k chosen so sum(p) = 1 (default)
- shin:           Shin (1993) insider-trading model, z chosen so sum(p) = 1
"""
from __future__ import annotations

import math
from typing import Sequence

from .config import MODEL, ModelParams


def parse_american(odds) -> float:
    """'+150', '-110', '150', 'EVEN', 150, -110.0 -> float. Raises on nonsense."""
    if isinstance(odds, str):
        s = odds.strip().upper()
        if s in ("EVEN", "EV", "PK"):
            return 100.0
        odds = float(s.replace("+", ""))
    value = float(odds)
    if math.isnan(value) or abs(value) < 100:
        raise ValueError(f"Not a valid American price: {odds!r}")
    return value


def american_to_prob(odds) -> float:
    o = parse_american(odds)
    return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def prob_to_american(p: float) -> float:
    if not 0.0 < p < 1.0:
        raise ValueError(f"Probability must be in (0, 1): {p}")
    return -100.0 * p / (1.0 - p) if p >= 0.5 else 100.0 * (1.0 - p) / p


def american_to_decimal(odds) -> float:
    o = parse_american(odds)
    return 1.0 + (o / 100.0 if o > 0 else 100.0 / -o)


def overround(probs: Sequence[float]) -> float:
    return float(sum(probs))


def devig_multiplicative(probs: Sequence[float]) -> list[float]:
    total = sum(probs)
    return [p / total for p in probs]


def devig_power(probs: Sequence[float], tol: float = 1e-12) -> list[float]:
    """Find k with sum(q_i ** k) == 1. sum(q ** k) falls as k rises, so bisect."""
    if any(not 0.0 < q < 1.0 for q in probs):
        raise ValueError(f"Implied probabilities must be in (0, 1): {probs}")
    lo, hi = 1e-3, 1e3
    for _ in range(200):
        k = (lo + hi) / 2
        total = sum(q ** k for q in probs)
        if abs(total - 1.0) < tol:
            break
        if total > 1.0:
            lo = k
        else:
            hi = k
    return [q ** k for q in probs]


def devig_shin(probs: Sequence[float], tol: float = 1e-12) -> list[float]:
    """Shin's method. Falls back to multiplicative when there is no margin."""
    big_q = sum(probs)
    if big_q <= 1.0:
        return devig_multiplicative(probs)

    def shin_p(z: float) -> list[float]:
        return [(math.sqrt(z * z + 4 * (1 - z) * q * q / big_q) - z) / (2 * (1 - z)) for q in probs]

    lo, hi = 0.0, 0.999
    for _ in range(200):
        z = (lo + hi) / 2
        total = sum(shin_p(z))
        if abs(total - 1.0) < tol:
            break
        if total > 1.0:
            lo = z
        else:
            hi = z
    p = shin_p(z)
    s = sum(p)
    return [x / s for x in p]


VIG_METHODS = {
    "multiplicative": devig_multiplicative,
    "power": devig_power,
    "shin": devig_shin,
}


def devig(probs: Sequence[float], method: str = "power") -> list[float]:
    try:
        return VIG_METHODS[method](probs)
    except KeyError:
        raise ValueError(f"Unknown vig method {method!r}; choose from {sorted(VIG_METHODS)}") from None


def no_vig_two_way(odds_a, odds_b, method: str = "power") -> tuple[float, float]:
    pa, pb = devig([american_to_prob(odds_a), american_to_prob(odds_b)], method)
    return pa, pb


# --- Normal points distribution -------------------------------------------------
def norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def points_sd(mean: float, params: ModelParams = MODEL) -> float:
    return max(params.sd_floor, params.sd_fraction * mean)


def p_over_normal(mean: float, line: float, sd: float | None = None,
                  params: ModelParams = MODEL) -> float:
    """P(points > line) for N(mean, sd). SD defaults to max(floor, fraction * mean)."""
    sd = points_sd(mean, params) if sd is None else sd
    return 1.0 - norm_cdf((line - mean) / sd)


def implied_mean(line: float, p_over: float, params: ModelParams = MODEL,
                 lo: float = 0.0, hi: float = 150.0) -> float:
    """Mean m such that P(X > line) == p_over when X ~ N(m, points_sd(m)).

    P(over) rises monotonically with m for line > 0 (the SD grows slower than
    the distance to the line shrinks), so bisection is safe. The answer is
    clamped to [lo, hi] when p_over is beyond what that range can produce.
    """
    if not 0.0 < p_over < 1.0:
        raise ValueError(f"p_over must be in (0, 1): {p_over}")
    for _ in range(200):
        mid = (lo + hi) / 2
        if p_over_normal(mid, line, params=params) < p_over:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return (lo + hi) / 2
