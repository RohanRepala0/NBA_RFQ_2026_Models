"""Strategies for the Kalshi backtest (backtest.py).

Each one sees only data stamped before its decision time and returns orders.
They use Kalshi's own prices only: a sportsbook consensus for 2025-26 would
cost SportsGameOdds objects, and our usage model's 2025-26 inputs are season
averages that include the future. So these test the *market* side: where
Kalshi misprices itself, when to enter, and how to enter.

- Baseline: buy every YES at the ask. The cost of spread + fee, for scale.
- Calibration ("longshot bias"): learn on past dates how often contracts in
  each price bucket paid, and take the side the history favours.
- LadderFit: a player's rungs must agree with one points distribution; buy
  the rung that sits off the curve fitted to the others (plus strict
  arbitrage when one rung's ask is below a higher rung's bid).
- TeammateVacuum ("news from prices"): when several teammates' ladders jump
  together (a star ruled out), buy the teammates that haven't moved yet.
- Reversion / Momentum: one-minute price moves without team news. Not
  executable by hand; reported to see whether automation would ever pay.
- Maker(base): the same orders as resting limits at one tick better than the
  bid, instead of taking the ask.
Every strategy runs at T-6h, T-2h, T-60m and T-15m where it makes sense, which
is the entry-timing study.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
import pandas as pd

from .backtest import ORDER_COLUMNS, Strategy, Tape
from .fees import fee_per_contract
from .odds_math import norm_cdf

TWO_SIDED = (0.0, 1.0)


def _two_sided(b: pd.DataFrame, max_spread: float) -> pd.DataFrame:
    return b[(b.bid > TWO_SIDED[0]) & (b.ask < TWO_SIDED[1]) & (b.spread <= max_spread + 1e-9)]


def _fee(price, n=10) -> float:
    return fee_per_contract("kalshi", n, float(price)) if 0 < price < 1 else 0.0


def _orders(df: pd.DataFrame, strategy: str, contracts: int, note: str = "") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=ORDER_COLUMNS)
    out = pd.DataFrame({"strategy": strategy, "ticker": df.ticker.values, "side": df.side.values,
                        "kind": df.get("kind", pd.Series("take", index=df.index)).values,
                        "limit": df["limit"].values, "contracts": contracts, "decided_at": df["at"].values,
                        "signal": df.signal.values, "note": note})
    return out[ORDER_COLUMNS]


@dataclass
class BuyEveryYes(Strategy):
    name: str = "baseline: buy every YES"
    params: dict = field(default_factory=lambda: {"offset": 60, "max_spread": 0.10, "contracts": 10})

    def decide(self, tape, test):
        b = _two_sided(tape.books_at([self.params["offset"]], test.ticker), self.params["max_spread"])
        b = b.assign(side="YES", limit=b.ask, signal=0.0)
        return _orders(b, self.name, self.params["contracts"])


@dataclass
class Calibration(Strategy):
    """Price-bucket calibration learned on earlier dates (the favourite-longshot bias, if any)."""
    name: str = "calibration"
    params: dict = field(default_factory=lambda: {
        "offset": 60, "edges": (0, .05, .10, .20, .30, .40, .50, .60, .70, .80, .90, .95, 1.0),
        "min_n": 60, "min_edge": 0.03, "max_spread": 0.10, "contracts": 10})
    rules: dict = field(default_factory=dict)

    def _bucketed(self, tape, markets):
        b = _two_sided(tape.books_at([self.params["offset"]], markets.ticker), self.params["max_spread"])
        b = b.merge(markets[["ticker", "value"]], on="ticker")
        b["bucket"] = pd.cut(b.mid, bins=list(self.params["edges"]), include_lowest=True)
        return b

    def fit(self, tape, train):
        self.rules = {}
        if train.empty:
            return
        b = self._bucketed(tape, train).dropna(subset=["value"])
        b["yes_edge"] = b.value - b.ask - b.ask.map(_fee)
        b["no_edge"] = (1 - b.value) - (1 - b.bid) - (1 - b.bid).map(_fee)
        g = b.groupby("bucket", observed=True).agg(n=("value", "size"), yes=("yes_edge", "mean"), no=("no_edge", "mean"))
        for bucket, r in g.iterrows():
            if r.n < self.params["min_n"]:
                continue
            side, edge = ("YES", r.yes) if r.yes >= r.no else ("NO", r.no)
            if edge >= self.params["min_edge"]:
                self.rules[bucket] = (side, float(edge))

    def decide(self, tape, test):
        if not self.rules:
            return pd.DataFrame(columns=ORDER_COLUMNS)
        b = self._bucketed(tape, test)
        bucket = b.bucket.astype(object)                  # plain intervals, not the full category list
        b = b[bucket.isin(list(self.rules))].assign(bucket=bucket)
        b = b.assign(side=b.bucket.map(lambda k: self.rules[k][0]), signal=b.bucket.map(lambda k: self.rules[k][1]))
        b["limit"] = np.where(b.side == "YES", b.ask, 1 - b.bid)
        return _orders(b, self.name, self.params["contracts"], note=f"{len(self.rules)} buckets")


def fit_mean(thresholds: np.ndarray, mids: np.ndarray, sd_floor: float = 4.0, sd_frac: float = 0.30) -> float:
    """Points mean whose P(X >= N) best matches the rung mids (least squares, grid then refine)."""
    def loss(m):
        sd = max(sd_floor, sd_frac * m)
        p = 1 - np.array([norm_cdf((n - 0.5 - m) / sd) for n in thresholds])
        return float(((p - mids) ** 2).sum())
    grid = np.arange(0.5, 60.0, 0.5)
    m0 = grid[int(np.argmin([loss(m) for m in grid]))]
    fine = np.arange(max(0.1, m0 - 0.5), m0 + 0.5, 0.05)
    return float(fine[int(np.argmin([loss(m) for m in fine]))])


@dataclass
class LadderFit(Strategy):
    """Each player's rungs should agree with one distribution; buy the rung off the fitted curve."""
    name: str = "ladder fit"
    params: dict = field(default_factory=lambda: {"offset": 60, "min_edge": 0.05, "max_spread": 0.10,
                                                  "fit_spread": 0.25, "min_rungs": 3, "contracts": 10})

    def decide(self, tape, test):
        p = self.params
        b = tape.books_at([p["offset"]], test.ticker).merge(test[["ticker", "game", "player", "threshold"]], on="ticker")
        b = b[(b.bid > 0) & (b.ask < 1)]
        picks = []
        for _, g in b.groupby(["game", "player"]):
            fit_on = g[g.spread <= p["fit_spread"]]
            if len(fit_on) < p["min_rungs"]:
                continue
            g = g.sort_values("threshold")
            best = None
            for r in g.itertuples():
                # Leave the rung out of its own fit, so it can't pull the curve toward itself.
                others = fit_on[fit_on.ticker != r.ticker]
                if len(others) < p["min_rungs"] - 1 or r.spread > p["max_spread"]:
                    continue
                m = fit_mean(others.threshold.to_numpy(float), others.mid.to_numpy(float))
                fair = 1 - norm_cdf((r.threshold - 0.5 - m) / max(4.0, 0.3 * m))
                for side, price, prob in (("YES", r.ask, fair), ("NO", 1 - r.bid, 1 - fair)):
                    edge = prob - price - _fee(price)
                    if edge >= p["min_edge"] and (best is None or edge > best[0]):
                        best = (edge, r.ticker, side, price, r.at)
            if best:
                picks.append({"ticker": best[1], "side": best[2], "limit": best[3], "at": best[4], "signal": best[0]})
        return _orders(pd.DataFrame(picks), self.name, p["contracts"])


@dataclass
class LadderArbitrage(Strategy):
    """Strict arbitrage: YES on rung N plus NO on a higher rung M costs < $1 after fees.
    Pays at least $1 whatever happens (2 if N <= points < M)."""
    name: str = "ladder arbitrage"
    params: dict = field(default_factory=lambda: {"offset": 60, "min_profit": 0.01, "contracts": 10})

    def decide(self, tape, test):
        p = self.params
        b = tape.books_at([p["offset"]], test.ticker).merge(test[["ticker", "game", "player", "threshold"]], on="ticker")
        b = b[(b.bid > 0) & (b.ask < 1)]
        rows = []
        for _, g in b.groupby(["game", "player"]):
            g = g.sort_values("threshold").to_dict("records")
            for i, lo in enumerate(g):
                for hi in g[i + 1:]:
                    cost = lo["ask"] + _fee(lo["ask"]) + (1 - hi["bid"]) + _fee(1 - hi["bid"])
                    if 1 - cost >= p["min_profit"]:
                        rows += [{"ticker": lo["ticker"], "side": "YES", "limit": lo["ask"], "at": lo["at"], "signal": 1 - cost},
                                 {"ticker": hi["ticker"], "side": "NO", "limit": 1 - hi["bid"], "at": hi["at"], "signal": 1 - cost}]
        return _orders(pd.DataFrame(rows), self.name, p["contracts"], note="paired legs")


def _minute_mids(series: pd.DataFrame, start, end) -> pd.DataFrame:
    """Per-minute as-of mids (rows: minutes, columns: tickers) from sparse candles."""
    s = series[(series.bid > 0) & (series.ask < 1)].assign(mid=lambda d: (d.bid + d.ask) / 2)
    if s.empty:
        return pd.DataFrame()
    wide = s.pivot_table(index="end_ts", columns="ticker", values="mid", aggfunc="last")
    grid = pd.date_range(pd.Timestamp(start).floor("min"), pd.Timestamp(end).floor("min"), freq="1min")
    return wide.reindex(wide.index.union(grid)).ffill().reindex(grid)


@dataclass
class TeammateVacuum(Strategy):
    """Several teammates' ladders jumping together is the market hearing that a star is out.
    Buy the teammates that haven't moved yet, before they reprice."""
    name: str = "teammate vacuum"
    params: dict = field(default_factory=lambda: {"window_min": 15, "jump": 0.10, "min_movers": 2,
                                                  "laggard_max": 0.03, "max_spread": 0.12, "lookback_h": 8,
                                                  "contracts": 10})
    detections: list = field(default_factory=list)

    def decide(self, tape, test):
        p = self.params
        self.detections = []
        # One rung per player: the one nearest 50% at the start of the window.
        start_off = int(p["lookback_h"] * 60)
        b0 = tape.books_at([start_off], test.ticker).merge(test[["ticker", "game", "team", "player", "tip_est"]], on="ticker")
        b0 = b0[(b0.bid > 0) & (b0.ask < 1)].assign(dist=lambda d: (d.mid - 0.5).abs())
        reps = b0.sort_values("dist").groupby(["game", "player"]).head(1)
        orders = []
        for (game, team), g in reps.groupby(["game", "team"]):
            if len(g) < p["min_movers"] + 1:
                continue
            tip = pd.Timestamp(g.tip_est.iloc[0])
            series = tape.series(g.ticker.tolist())
            mids = _minute_mids(series, tip - timedelta(hours=p["lookback_h"]), tip - timedelta(minutes=2))
            if mids.empty:
                continue
            delta = mids - mids.shift(p["window_min"])
            movers = (delta >= p["jump"]).sum(axis=1)
            hits = movers[movers >= p["min_movers"]]
            if hits.empty:
                continue
            t = hits.index[0]
            decide_at = t + timedelta(minutes=1)            # act a minute after seeing it
            if decide_at >= tip:
                continue
            laggards = [c for c in mids.columns if pd.notna(delta.loc[t, c]) and delta.loc[t, c] <= p["laggard_max"]]
            self.detections.append({"game": game, "team": team, "at": t, "movers": int(hits.iloc[0]),
                                    "laggards": len(laggards)})
            if not laggards:
                continue
            book = series[series.ticker.isin(laggards) & (series.end_ts <= decide_at)].groupby("ticker").tail(1)
            book = book[(book.bid > 0) & (book.ask < 1) & (book.ask - book.bid <= p["max_spread"])]
            for r in book.itertuples():
                orders.append({"ticker": r.ticker, "side": "YES", "limit": r.ask, "at": decide_at,
                               "signal": float(delta.loc[t].max())})
        return _orders(pd.DataFrame(orders), self.name, p["contracts"], note="team jump")


@dataclass
class MoveFollow(Strategy):
    """Single-market one-minute moves with no team-wide move: fade (reversion) or follow (momentum).
    Needs automation to act within a minute, so it is not executable by hand."""
    name: str = "reversion"
    params: dict = field(default_factory=lambda: {"mode": "fade", "move": 0.10, "window_min": 5,
                                                  "max_spread": 0.10, "lookback_h": 6, "contracts": 10})
    executable_by_hand: bool = False

    def decide(self, tape, test):
        p = self.params
        b0 = tape.books_at([int(p["lookback_h"] * 60)], test.ticker).merge(test[["ticker", "game", "player", "tip_est"]], on="ticker")
        b0 = b0[(b0.bid > 0) & (b0.ask < 1)].assign(dist=lambda d: (d.mid - 0.5).abs())
        reps = b0.sort_values("dist").groupby(["game", "player"]).head(1)
        orders = []
        for game, g in reps.groupby("game"):
            tip = pd.Timestamp(g.tip_est.iloc[0])
            series = tape.series(g.ticker.tolist())
            mids = _minute_mids(series, tip - timedelta(hours=p["lookback_h"]), tip - timedelta(minutes=2))
            if mids.empty:
                continue
            delta = mids - mids.shift(p["window_min"])
            team_wide = (delta.abs() >= p["move"]).sum(axis=1) >= 2
            for c in mids.columns:
                d = delta[c][~team_wide]
                hits = d[d.abs() >= p["move"]]
                if hits.empty:
                    continue
                t = hits.index[0]
                decide_at = t + timedelta(minutes=1)
                if decide_at >= tip:
                    continue
                up = hits.iloc[0] > 0
                side = ("NO" if up else "YES") if p["mode"] == "fade" else ("YES" if up else "NO")
                last = series[(series.ticker == c) & (series.end_ts <= decide_at)].tail(1)
                if last.empty or not (0 < last.bid.iloc[0] and last.ask.iloc[0] < 1):
                    continue
                if last.ask.iloc[0] - last.bid.iloc[0] > p["max_spread"]:
                    continue
                limit = last.ask.iloc[0] if side == "YES" else 1 - last.bid.iloc[0]
                orders.append({"ticker": c, "side": side, "limit": limit, "at": decide_at, "signal": float(hits.iloc[0])})
        return _orders(pd.DataFrame(orders), self.name, p["contracts"], note=p["mode"])


@dataclass
class Maker(Strategy):
    """Wrap a strategy: post its orders as resting limits one tick better than the current bid,
    never above the price it would have paid as a taker. Kalshi charges makers no fee on KXNBAPTS."""
    base: Strategy | None = None
    name: str = "maker"

    def __post_init__(self):
        self.name = f"{self.base.name} (as limit orders)"
        self.executable_by_hand = self.base.executable_by_hand

    def fit(self, tape, train):
        self.base.fit(tape, train)

    def decide(self, tape, test):
        o = self.base.decide(tape, test)
        if o is None or o.empty:
            return o
        o = o.copy()
        tape.con.register("probe", o[["ticker", "decided_at"]].drop_duplicates())
        try:
            at = tape.con.execute("""SELECT p.ticker, p.decided_at, c.yes_bid_close bid, c.yes_ask_close ask FROM probe p
                                     ASOF LEFT JOIN candles c ON p.ticker = c.ticker AND c.end_ts <= p.decided_at""").df()
        finally:
            tape.con.unregister("probe")
        o = o.merge(at, on=["ticker", "decided_at"], how="left")
        better_bid = np.where(o.side == "YES", o.bid + 0.01, (1 - o.ask) + 0.01)
        o["limit"] = np.minimum(better_bid, o["limit"] - 0.01).round(2)
        o["kind"] = "make"
        return o[o["limit"] > 0][ORDER_COLUMNS]


def default_suite() -> list[Strategy]:
    """Every strategy, with entry timing as a sweep over T-6h / T-2h / T-60m / T-15m."""
    suite: list[Strategy] = [BuyEveryYes()]
    for off, tag in ((360, "t-6h"), (120, "t-2h"), (60, "t-60m"), (15, "t-15m")):
        cal = Calibration(name=f"calibration @ {tag}")
        cal.params = {**cal.params, "offset": off}
        lad = LadderFit(name=f"ladder fit @ {tag}")
        lad.params = {**lad.params, "offset": off}
        suite += [cal, lad]
    suite += [LadderArbitrage(), TeammateVacuum(), MoveFollow(name="reversion (1-min)"),
              MoveFollow(name="momentum (1-min)", params={"mode": "follow", "move": 0.10, "window_min": 5,
                                                         "max_spread": 0.10, "lookback_h": 6, "contracts": 10})]
    lad60 = LadderFit(name="ladder fit @ t-60m")
    suite.append(Maker(base=lad60))
    suite.append(Maker(base=TeammateVacuum()))
    return suite
