"""Binary "N+ points" contract math shared by the board and the ladders.

For a contract with win probability p and a taker fee of rate * c * (1 - c)
per contract, buying at price c has expected value p - c - fee(c). The max
price is the largest c that still leaves the edge. Venue decisions (with each
venue's exact fee and rounding) live in decision.py; this module only prices
theoretical rungs. Nothing here talks to any venue.
"""
from __future__ import annotations

import math

import pandas as pd

from . import config
from .config import MODEL, ModelParams
from .odds_math import norm_cdf, points_sd


def max_price(p: float, fee_rate: float, min_edge: float = config.EDGE_THRESHOLD) -> float | None:
    """Largest price c (in dollars) with p - c - fee_rate * c * (1 - c) >= min_edge."""
    target = p - min_edge
    if target <= 0:
        return None
    if fee_rate == 0:
        return min(target, 0.99)
    a, b = fee_rate, -(1 + fee_rate)
    root = (-b - math.sqrt(b * b - 4 * a * target)) / (2 * a)
    return max(0.0, min(root, 0.99))


def cents_floor(price: float | None) -> int | None:
    return None if price is None else int(math.floor(100 * price + 1e-9))


def p_at_least(n: int, mean: float, sd: float) -> float:
    """P(points >= n) with a continuity correction."""
    return 1.0 - norm_cdf((n - 0.5 - mean) / sd)


def contract_for(side: str, line: float) -> tuple[int, str]:
    """Book over/under -> 'N+ points' contract. Over 24.5 = 25+ YES; under 24.5 = 25+ NO."""
    if side == "over":
        return int(math.floor(line)) + 1, "YES"
    return int(math.ceil(line)), "NO"


def contract_p(n: int, outcome: str, mean: float, sd: float) -> float:
    p = p_at_least(n, mean, sd)
    return p if outcome == "YES" else 1 - p


def ladder(mean: float, consensus_mean: float | None, line: float,
           half_width: int = config.LADDER_HALF_WIDTH, params: ModelParams = MODEL) -> pd.DataFrame:
    """Fair YES price for 'N+ points' rungs around the line, model vs market."""
    centre = int(math.floor(line)) + 1
    sd = points_sd(mean, params)
    rows = []
    for n in range(centre - half_width, centre + half_width + 1):
        p = p_at_least(n, mean, sd)
        row = {"contract": f"{n}+", "model_yes_c": round(100 * p, 1)}
        if consensus_mean is not None:
            row["market_yes_c"] = round(100 * p_at_least(n, consensus_mean, points_sd(consensus_mean, params)), 1)
        rows.append(row)
    return pd.DataFrame(rows)
