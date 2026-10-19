"""Backtests on Kalshi's archive of settled NBA player-points markets.

Input: the research cache from `cli history` (kalshi_history.py): every 2025-26
KXNBAPTS market with its result and settlement value, and 1-minute candles. A
candle exists only for a minute in which the book or a trade changed, so the
book in between is the last candle's (an as-of join, never interpolation).

The engine is strategy-agnostic. A strategy sees only data stamped before its
decision time and returns orders; the engine fills, settles and scores them
the same way for every strategy:

- Fills. `take`: at the ask at the decision time (YES ask, or NO ask = 1 - YES
  bid), only if that ask is at or under the order's limit. `make`: a resting
  limit from the decision time until tip, filled only if a trade printed
  *through* it (YES: a trade below the limit; NO: a YES trade above 1 - limit).
  Candles carry no depth, so size is the order's own (strategies keep it small).
- Costs. Kalshi's taker fee per order (rounded up to the cent); makers pay 0
  on KXNBAPTS. Settlement pays 1 / 0, or the exchange's fair price for a player
  who never took the court; NO receives 1 - value.
- Scoring. Yield (P&L / cost), hit rate, CLV against the last pre-tip mid, max
  drawdown and daily Sharpe of the P&L curve, and a bootstrap interval for
  yield that resamples whole game dates (bets on one slate are correlated).
- Walk-forward. Folds by ET game date with a one-day embargo: each fold's
  parameters are fit only on earlier dates. Dates from HOLDOUT_START on are
  never used to choose anything; they are reported once, separately.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .fees import fee_total
from .kalshi_history import HISTORY_DB

HOLDOUT_START = date(2026, 4, 1)          # April + playoffs: never used for fitting
ORDER_COLUMNS = ["strategy", "ticker", "side", "kind", "limit", "contracts", "decided_at", "signal", "note"]


class Tape:
    """Read-only view of the archive: markets, as-of books, and trade extremes."""

    def __init__(self, path: Path | str | None = None, con: duckdb.DuckDBPyConnection | None = None):
        self.con = con or duckdb.connect(str(path or HISTORY_DB), read_only=True)
        m = self.con.execute("""
            SELECT ticker, event_ticker, player, team, threshold, result, settlement_value, volume, tip_est, open_time
            FROM markets WHERE tip_est IS NOT NULL AND ticker IN (SELECT DISTINCT ticker FROM candles)""").df()
        m["game_date"] = (pd.to_datetime(m.tip_est).dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.date)
        m["game"] = m.event_ticker.str.split("-").str[1]
        m["value"] = np.where(m.result == "yes", 1.0, np.where(m.result == "no", 0.0, m.settlement_value))
        self.markets = m

    def books_at(self, offsets_min: list[int], tickers: pd.Series | None = None) -> pd.DataFrame:
        """The book of every market as of tip - offset (as-of join on the candles)."""
        probe = pd.DataFrame([(t, off, tip - timedelta(minutes=off))
                              for t, tip in zip(self.markets.ticker, pd.to_datetime(self.markets.tip_est))
                              for off in offsets_min], columns=["ticker", "offset_min", "at"])
        if tickers is not None:
            probe = probe[probe.ticker.isin(set(tickers))]
        self.con.register("probe", probe)
        try:
            df = self.con.execute("""
                SELECT p.ticker, p.offset_min, p.at, c.end_ts AS book_ts, c.yes_bid_close AS bid, c.yes_ask_close AS ask
                FROM probe p ASOF LEFT JOIN candles c ON p.ticker = c.ticker AND c.end_ts <= p.at""").df()
        finally:
            self.con.unregister("probe")
        df["mid"] = (df.bid + df.ask) / 2
        df["spread"] = df.ask - df.bid
        return df

    def trade_extremes(self, orders: pd.DataFrame) -> pd.DataFrame:
        """Lowest and highest trade price between each order's decision time and tip."""
        probe = orders[["ticker", "decided_at"]].drop_duplicates().merge(self.markets[["ticker", "tip_est"]], on="ticker")
        self.con.register("probe", probe)
        try:
            return self.con.execute("""
                SELECT p.ticker, p.decided_at, min(c.price_low) AS low, max(c.price_high) AS high,
                       sum(c.volume) AS volume_after
                FROM probe p JOIN candles c ON c.ticker = p.ticker AND c.end_ts > p.decided_at AND c.end_ts <= p.tip_est
                GROUP BY 1, 2""").df()
        finally:
            self.con.unregister("probe")

    def series(self, tickers: list[str]) -> pd.DataFrame:
        """All candles for some markets (for strategies that watch prices move)."""
        self.con.register("want", pd.DataFrame({"ticker": list(tickers)}))
        try:
            return self.con.execute("""SELECT c.ticker, c.end_ts, c.yes_bid_close AS bid, c.yes_ask_close AS ask,
                                              c.price_close, c.volume FROM candles c JOIN want USING (ticker)
                                       ORDER BY c.ticker, c.end_ts""").df()
        finally:
            self.con.unregister("want")


def simulate(tape: Tape, orders: pd.DataFrame) -> pd.DataFrame:
    """Fill, settle and score orders. One row per order, filled or not."""
    if orders.empty:
        return orders.assign(filled=pd.Series(dtype=bool))
    o = orders.copy()
    o["decided_at"] = pd.to_datetime(o.decided_at)
    m = tape.markets[["ticker", "game", "game_date", "player", "team", "threshold", "tip_est", "result", "value"]]
    o = o.merge(m, on="ticker", how="left")
    if (o.decided_at >= pd.to_datetime(o.tip_est)).any():
        raise ValueError("an order was decided at or after tip: strategies may only trade pre-game")
    # Book at the decision time and the close (last book before tip).
    probe = o[["ticker", "decided_at"]].drop_duplicates()
    tape.con.register("probe", probe)
    try:
        at = tape.con.execute("""
            SELECT p.ticker, p.decided_at, c.yes_bid_close AS bid, c.yes_ask_close AS ask
            FROM probe p ASOF LEFT JOIN candles c ON p.ticker = c.ticker AND c.end_ts <= p.decided_at""").df()
    finally:
        tape.con.unregister("probe")
    o = o.merge(at, on=["ticker", "decided_at"], how="left")
    close = tape.books_at([0], tickers=o.ticker.unique())[["ticker", "mid"]].rename(columns={"mid": "close_mid"})
    o = o.merge(close, on="ticker", how="left")
    ext = tape.trade_extremes(o)
    o = o.merge(ext, on=["ticker", "decided_at"], how="left")

    yes = o.side == "YES"
    side_ask = np.where(yes, o.ask, 1 - o.bid)
    take = o.kind == "take"
    take_fill = take & pd.notna(side_ask) & (side_ask > 0) & (side_ask < 1) & (side_ask <= o["limit"] + 1e-9)
    through = np.where(yes, o.low < o["limit"] - 1e-9, o.high > 1 - o["limit"] + 1e-9)
    make_fill = (~take) & pd.Series(through, index=o.index).fillna(False).astype(bool)
    o["filled"] = take_fill | make_fill
    o["price"] = np.where(take, side_ask, o["limit"])
    o["fee"] = [fee_total("kalshi", n, p, maker=(k == "make")) if f else 0.0
                for n, p, k, f in zip(o.contracts, o.price, o.kind, o.filled)]
    o["cost"] = np.where(o.filled, o.contracts * o.price + o.fee, 0.0)
    side_value = np.where(yes, o.value, 1 - o.value)
    o["payout"] = np.where(o.filled, o.contracts * side_value, 0.0)
    o["pnl"] = o.payout - o.cost
    o["clv"] = np.where(o.filled, np.where(yes, o.close_mid, 1 - o.close_mid) - o.price, np.nan)
    o["won"] = np.where(o.filled & o.result.isin(["yes", "no"]), side_value == 1, np.nan)
    return o


def summarize(bets: pd.DataFrame) -> dict:
    f = bets[bets.filled] if len(bets) else bets
    out = {"orders": int(len(bets)), "fills": int(len(f)), "contracts": float(f.contracts.sum()) if len(f) else 0.0}
    if f.empty:
        return out
    daily = f.groupby("game_date").pnl.sum().sort_index()
    curve = daily.cumsum()
    out.update({
        "cost": round(float(f.cost.sum()), 2), "pnl": round(float(f.pnl.sum()), 2),
        "yield": float(f.pnl.sum() / f.cost.sum()) if f.cost.sum() > 0 else None,
        "hit_rate": float(pd.to_numeric(f.won, errors="coerce").mean()),
        "avg_price": float(f.price.mean()), "avg_clv": float(f.clv.mean()),
        "fair_price_settlements": int((f.result == "scalar").sum()),
        "max_drawdown": round(float((curve.cummax() - curve).max()), 2),
        "daily_sharpe": float(daily.mean() / daily.std()) if len(daily) > 1 and daily.std() > 0 else None,
        "days": int(len(daily)),
    })
    return out


def bootstrap_yield(bets: pd.DataFrame, n: int = 1000, seed: int = 7) -> tuple[float, float] | None:
    """95% interval for yield, resampling whole game dates."""
    f = bets[bets.filled]
    if f.empty or f.game_date.nunique() < 5:
        return None
    by = f.groupby("game_date").agg(pnl=("pnl", "sum"), cost=("cost", "sum"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(by), size=(n, len(by)))
    pnl, cost = by.pnl.to_numpy()[idx].sum(axis=1), by.cost.to_numpy()[idx].sum(axis=1)
    ys = pnl / np.where(cost > 0, cost, np.nan)
    return float(np.nanpercentile(ys, 2.5)), float(np.nanpercentile(ys, 97.5))


@dataclass
class Fold:
    name: str
    train_end: date          # train on game dates < train_end - embargo
    test_start: date
    test_end: date           # exclusive
    holdout: bool = False


def monthly_folds(dates: pd.Series, holdout_start: date = HOLDOUT_START, embargo_days: int = 1,
                  min_train_days: int = 10) -> list[Fold]:
    """Expanding-window folds by calendar month; everything from holdout_start is one final fold."""
    ds = sorted(set(dates))
    if not ds:
        return []
    first = ds[0]
    folds, start = [], date(first.year, first.month, 1)
    while start < holdout_start:
        nxt = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        end = min(nxt, holdout_start)
        if (start - first).days >= min_train_days and any(start <= d < end for d in ds):
            folds.append(Fold(f"{start:%Y-%m}", start - timedelta(days=embargo_days), start, end))
        start = nxt
    if any(d >= holdout_start for d in ds):
        folds.append(Fold("holdout", holdout_start - timedelta(days=embargo_days), holdout_start,
                          max(ds) + timedelta(days=1), holdout=True))
    return folds


@dataclass
class Strategy:
    """Base class. `fit` sees only training markets; `decide` returns orders for test markets."""
    name: str = "base"
    params: dict = field(default_factory=dict)
    executable_by_hand: bool = True

    def fit(self, tape: Tape, train: pd.DataFrame) -> None:
        return None

    def decide(self, tape: Tape, test: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError


def walk_forward(tape: Tape, strategy: Strategy, folds: list[Fold] | None = None) -> pd.DataFrame:
    folds = folds if folds is not None else monthly_folds(tape.markets.game_date)
    out = []
    for f in folds:
        train = tape.markets[tape.markets.game_date < f.train_end]
        test = tape.markets[(tape.markets.game_date >= f.test_start) & (tape.markets.game_date < f.test_end)]
        if test.empty:
            continue
        strategy.fit(tape, train)
        orders = strategy.decide(tape, test)
        if orders is None or orders.empty:
            continue
        bets = simulate(tape, orders.assign(strategy=strategy.name))
        out.append(bets.assign(fold=f.name, holdout=f.holdout))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def report(results: dict[str, pd.DataFrame], tape: Tape) -> str:
    m = tape.markets
    lines = ["# Backtest: Kalshi NBA player points, 2025-26", "",
             f"Archive: {len(m):,} markets with candles across {m.game.nunique():,} games, "
             f"{m.game_date.min()} to {m.game_date.max()}. Holdout (never used to choose anything): "
             f"{HOLDOUT_START} on.", "",
             "Taker fills at the ask at decision time; maker fills only when a trade printed through the limit. "
             "Kalshi taker fee per order, rounded up to the cent; makers pay 0. Players who never played "
             "settle at the exchange's fair price.", "",
             "| strategy | by hand? | period | fills | contracts | cost | P&L | yield | 95% CI (by date) | hit rate | avg CLV | max DD |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, bets in results.items():
        if bets.empty:
            lines.append(f"| {name} | | | 0 | | | | | | | | |")
            continue
        hand = bets.attrs.get("executable_by_hand", True)
        for period, part in (("walk-forward", bets[~bets.holdout]), ("holdout", bets[bets.holdout])):
            s = summarize(part)
            ci = bootstrap_yield(part)
            fmt = lambda v, p=False: "" if v is None or (isinstance(v, float) and math.isnan(v)) else (f"{100 * v:+.1f}%" if p else f"{v:,.2f}")  # noqa: E731
            lines.append(f"| {name} | {'yes' if hand else 'no'} | {period} | {s.get('fills', 0)} | {s.get('contracts', 0):,.0f} | "
                         f"{fmt(s.get('cost'))} | {fmt(s.get('pnl'))} | {fmt(s.get('yield'), True)} | "
                         f"{'' if ci is None else f'{100 * ci[0]:+.1f}% to {100 * ci[1]:+.1f}%'} | "
                         f"{fmt(s.get('hit_rate'), True)} | {fmt(s.get('avg_clv'))} | {fmt(s.get('max_drawdown'))} |")
    return "\n".join(lines) + "\n"
