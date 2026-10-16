"""Prediction-market watchlist: what each paper signal is worth on Novig, Kalshi or
Polymarket, priced as binary "N+ points" contracts that pay $1.

For a contract with win probability p and a taker fee of rate * c * (1 - c)
per contract, buying at price c has expected value p - c - fee(c). The max
price is the largest c that still leaves EDGE_THRESHOLD of expected value.

Read-only research output. Nothing here talks to any venue.
"""
from __future__ import annotations

import math

import pandas as pd

from . import config
from .config import MODEL, ModelParams
from .odds_math import american_to_prob, norm_cdf, points_sd


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


def watchlist_rows(signals: pd.DataFrame, venues: pd.DataFrame | None = None,
                   params: ModelParams = MODEL) -> pd.DataFrame:
    """One row per paper signal: the contract to wait for and the max price per venue."""
    venues = pd.DataFrame() if venues is None else venues
    rows = []
    for s in signals.itertuples():
        if s.decision != "paper":
            continue
        n, outcome = contract_for(s.side, s.line)
        model_sd = points_sd(s.model_mean, params)
        cons_sd = points_sd(s.consensus_mean, params)
        p_model = contract_p(n, outcome, s.model_mean, model_sd)
        p_cons = contract_p(n, outcome, s.consensus_mean, cons_sd)
        row = {
            "event_id": s.event_id, "player": s.player_name, "team": s.team,
            "book_side": f"{s.side} {s.line:g}", "contract": f"{n}+ pts {outcome}",
            "model_mean": s.model_mean, "consensus_mean": s.consensus_mean,
            "model_cents": round(100 * p_model, 1), "market_cents": round(100 * p_cons, 1),
            "edge_pp": round(100 * s.edge, 1),
        }
        for venue in sorted(config.TARGET_VENUES):
            row[f"max_{venue}"] = cents_floor(max_price(p_model, config.VENUE_FEE_RATE.get(venue, 0.07)))
        row["posted"] = posted_summary(venues, s, params)
        rows.append(row)
    return pd.DataFrame(rows)


def posted_summary(venues: pd.DataFrame, s, params: ModelParams = MODEL) -> str:
    """Prices already posted by target venues for this player's chosen side, vs our max."""
    if venues is None or venues.empty:
        return ""
    mine = venues[(venues.event_id == s.event_id) & (venues.player_id == s.player_id)
                  & (venues.side == s.side)]
    parts = []
    for q in mine.itertuples():
        n, outcome = contract_for(q.side, q.line)
        p_model = contract_p(n, outcome, s.model_mean, points_sd(s.model_mean, params))
        cap = cents_floor(max_price(p_model, config.VENUE_FEE_RATE.get(q.book, 0.07)))
        price = round(100 * american_to_prob(q.odds_american))
        verdict = "within max" if cap is not None and price <= cap else "above max"
        parts.append(f"{q.book} {n}+ {outcome} @ {price}c ({verdict} {cap}c)")
    return "; ".join(parts)


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
