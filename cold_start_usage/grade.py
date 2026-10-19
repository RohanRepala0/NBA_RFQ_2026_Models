"""Grading after games are final: CLV, hit rate, Brier, log loss, calibration.

- CLV (prob): close no-vig P(our side at OUR logged line) minus the consensus
  P(our side) when we logged. Positive = the market moved toward us.
- CLV (line): close consensus line minus our line for overs (reversed for
  unders). Positive = the line moved our way.
- Accuracy is scored on model_p and, as the baseline, on consensus_p, both for
  the side we logged. Pushes are excluded.
"""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

from .odds_math import p_over_normal
from .schedule import et_date, et_day_bounds, week_of_season
from .storage import Storage

EPS = 1e-6


def graded_signals(storage: Storage, start: date, end: date) -> pd.DataFrame:
    lo, _ = et_day_bounds(start)
    _, hi = et_day_bounds(end)
    df = storage.query("""
        WITH ev AS (
          SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (PARTITION BY event_id ORDER BY ts DESC) rn FROM events)
          WHERE rn = 1),
        res AS (
          SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (PARTITION BY event_id, player_id ORDER BY ts DESC) rn FROM results)
          WHERE rn = 1)
        SELECT s.*, ev.starts_at, res.actual_points, res.close_consensus_line,
               res.close_consensus_mean, res.close_source
        FROM signals s
        JOIN ev USING (event_id)
        LEFT JOIN res USING (event_id, player_id)
        WHERE ev.starts_at >= ? AND ev.starts_at < ?""", [lo, hi])
    if df.empty:
        return df
    df["game_date"] = df.starts_at.map(et_date)
    df["week"] = df.game_date.map(week_of_season)

    def outcome(r):
        if pd.isna(r.actual_points) or pd.isna(r.line) or pd.isna(r.side):
            return None
        if r.actual_points == r.line:
            return None                                     # push
        won_over = r.actual_points > r.line
        return float(won_over if r.side == "over" else not won_over)

    def clv_p(r):
        if pd.isna(r.close_consensus_mean) or pd.isna(r.line) or pd.isna(r.side) or pd.isna(r.consensus_p):
            return None
        p_over = p_over_normal(r.close_consensus_mean, r.line)
        return (p_over if r.side == "over" else 1 - p_over) - r.consensus_p

    def clv_line(r):
        if pd.isna(r.close_consensus_line) or pd.isna(r.line) or pd.isna(r.side):
            return None
        if r.side == "over":
            return r.close_consensus_line - r.line
        return r.line - r.close_consensus_line

    df["outcome"] = df.apply(outcome, axis=1)
    df["clv_p"] = df.apply(clv_p, axis=1)
    df["clv_line"] = df.apply(clv_line, axis=1)
    return df


def _brier(p: pd.Series, y: pd.Series) -> float:
    return float(((p - y) ** 2).mean())


def _logloss(p: pd.Series, y: pd.Series) -> float:
    p = p.clip(EPS, 1 - EPS)
    return float(-(y * p.map(math.log) + (1 - y) * (1 - p).map(math.log)).mean())


def summarize(df: pd.DataFrame) -> dict:
    out = {"signals": len(df)}
    if df.empty:
        return out
    g = df[df.outcome.notna() & df.model_p.notna() & df.consensus_p.notna()]
    y = g.outcome.astype(float)
    out.update({
        "graded": len(g),
        "pushes_or_missing": int(len(df) - len(g)),
        "hit_rate": float(y.mean()) if len(g) else None,
        "avg_clv_p": float(df.clv_p.dropna().mean()) if df.clv_p.notna().any() else None,
        "avg_clv_line": float(df.clv_line.dropna().mean()) if df.clv_line.notna().any() else None,
        "brier_model": _brier(g.model_p, y) if len(g) else None,
        "brier_market": _brier(g.consensus_p, y) if len(g) else None,
        "logloss_model": _logloss(g.model_p, y) if len(g) else None,
        "logloss_market": _logloss(g.consensus_p, y) if len(g) else None,
    })
    return out


def calibration(df: pd.DataFrame) -> pd.DataFrame:
    g = df[df.outcome.notna() & df.model_p.notna()].copy()
    if g.empty:
        return pd.DataFrame(columns=["bucket", "n", "avg_model_p", "hit_rate"])
    g["bucket"] = (g.model_p * 10).clip(upper=9.999).map(math.floor) / 10
    t = g.groupby("bucket").agg(n=("outcome", "size"), avg_model_p=("model_p", "mean"),
                                hit_rate=("outcome", "mean")).reset_index()
    t["bucket"] = t.bucket.map(lambda b: f"{b:.0%}-{b + 0.1:.0%}")
    return t


def by_segment(df: pd.DataFrame, col: str) -> pd.DataFrame:
    rows = []
    for key, grp in df.groupby(col, dropna=False):
        s = summarize(grp)
        rows.append({col: "unknown" if pd.isna(key) else key, **{k: s.get(k) for k in ("signals", "graded", "hit_rate", "avg_clv_p",
                                                        "brier_model", "brier_market")}})
    return pd.DataFrame(rows)


# --- Venue grading: what Kalshi and Polymarket US actually pay ---------------------------
# A contract pays its settlement value: 1 or 0, or, for a player who never takes
# the court, a fair price the venue sets (Kalshi "scalar", Polymarket US LFMP).
# NO pays 1 - value. Paper P&L takes the first actionable decision per contract
# side at its logged all-in cost; fills use what Rohan actually paid.

def fetch_venue_settlements(storage: Storage, start: date, end: date, now,
                            kalshi_market=None, pm_us_settlement=None) -> int:
    """Store settlements for every venue contract logged for games in [start, end]."""
    lo, _ = et_day_bounds(start)
    _, hi = et_day_bounds(end)
    want = storage.query("""
        SELECT DISTINCT venue, ticker FROM venue_signals WHERE tip_ts >= ? AND tip_ts < ?
          AND venue IN ('kalshi', 'polymarket_us') AND ticker IS NOT NULL
        UNION SELECT DISTINCT t.venue, t.ticker FROM tickets t""", [lo, hi])
    have = set(map(tuple, storage.query("SELECT DISTINCT venue, ticker FROM venue_settlements")
                   [["venue", "ticker"]].itertuples(index=False)))
    rows = []
    for v, t in want.itertuples(index=False):
        if (v, t) in have:
            continue
        if v == "kalshi" and kalshi_market is not None:
            m = kalshi_market(t) or {}
            result = m.get("result")
            if result in ("yes", "no", "scalar") and m.get("status") in ("finalized", "settled", "determined"):
                value = {"yes": 1.0, "no": 0.0}.get(result)
                if value is None and m.get("settlement_value_dollars") not in (None, ""):
                    value = float(m["settlement_value_dollars"])
                rows.append({"ts": now, "venue": v, "ticker": t, "result": result, "settlement_value": value,
                             "settled_ts": m.get("settlement_ts")})
        elif v == "polymarket_us" and pm_us_settlement is not None:
            value = pm_us_settlement(t)
            if value is not None:
                rows.append({"ts": now, "venue": v, "ticker": t, "settlement_value": value,
                             "result": {1.0: "yes", 0.0: "no"}.get(value, "scalar")})
    return storage.append("venue_settlements", rows)


def _settled(storage: Storage) -> pd.DataFrame:
    return storage.query("""
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY venue, ticker ORDER BY ts DESC) rn FROM venue_settlements)
        WHERE rn = 1""")


def venue_graded(storage: Storage, start: date, end: date) -> pd.DataFrame:
    """First actionable decision per contract side, with settlement, P&L per contract and venue CLV."""
    lo, _ = et_day_bounds(start)
    _, hi = et_day_bounds(end)
    sig = storage.query("""
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY venue, ticker, side ORDER BY ts) rn
          FROM venue_signals WHERE decision = 'actionable' AND tip_ts >= ? AND tip_ts < ?) WHERE rn = 1""",
                        [lo, hi])
    if sig.empty:
        return sig
    close = storage.query("""
        SELECT * EXCLUDE (rn) FROM (
          SELECT venue, ticker, yes_bid, yes_ask,
                 row_number() OVER (PARTITION BY venue, ticker ORDER BY ts DESC) rn
          FROM venue_snapshots WHERE ts < tip_ts) WHERE rn = 1""")
    df = sig.merge(_settled(storage)[["venue", "ticker", "result", "settlement_value"]],
                   on=["venue", "ticker"], how="left").merge(close, on=["venue", "ticker"], how="left")
    yes_value = df.settlement_value
    df["value"] = yes_value.where(df.side == "YES", 1 - yes_value)
    df["pnl_per_contract"] = df.value - df.cost
    mid_yes = (df.yes_bid + df.yes_ask) / 2
    df["close_mid"] = mid_yes.where(df.side == "YES", 1 - mid_yes)
    df["clv_venue"] = df.close_mid - df.ask
    df["game_date"] = df.tip_ts.map(et_date)
    return df


def fills_graded(storage: Storage) -> pd.DataFrame:
    t = storage.query("SELECT * FROM tickets")
    if t.empty:
        return t
    df = t.merge(_settled(storage)[["venue", "ticker", "result", "settlement_value"]],
                 on=["venue", "ticker"], how="left")
    value = df.settlement_value.where(df.side == "YES", 1 - df.settlement_value)
    df["pnl"] = df.contracts * (value - df.price) - df.fees.fillna(0.0)
    return df


def venue_summary(df: pd.DataFrame, min_n: int = 50) -> dict:
    """Yield and hit rate are shown only with at least `min_n` settled contracts."""
    if df.empty:
        return {"actionable": 0}
    s = df[df.value.notna()]
    binary = s[s.result.isin(["yes", "no"])]
    out = {"actionable": len(df), "settled": len(s), "fair_price_settlements": int((s.result == "scalar").sum()),
           "avg_ev_logged": float(df.ev_blend.mean()),
           "avg_clv_venue": float(df.clv_venue.dropna().mean()) if df.clv_venue.notna().any() else None}
    if len(s) >= min_n:
        out.update(yield_per_contract=float(s.pnl_per_contract.sum() / s.cost.sum()),
                   hit_rate=float((binary.value == 1).mean()) if len(binary) else None)
    return out
