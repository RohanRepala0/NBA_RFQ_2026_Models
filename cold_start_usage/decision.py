"""The one decision path for prediction-market contracts.

Every Kalshi rung and Polymarket market becomes one row per side with a
decision in {actionable, watch, abstain, reference} and a reason. Nothing else
in the package may call a contract actionable (or READY).

Fair value. One distribution per player-game and stat (points, rebounds or
assists), leaning on the market:
    m = consensus_mean + w * (model_mean - consensus_mean)
with w = W_MODEL while the model sits within Z_GAP_MAX consensus SDs of the
market (the stat's own SD), else w = 0 and the row is flagged (a big gap is more
often a minutes or injury input than a mispriced market). A contract's
probability is the lower of two models (distributions.robust_p: for points the
linear and compound-Poisson SDs, for rebounds and assists a negative binomial at
phi and phi_alt), so rungs far from the books' line aren't priced off one
assumption. EV_market is the same with w = 0: the venue against the sportsbook
consensus alone.

Gates, in order (the first that fails is the reason):
  reference venue -> after tip -> unparsed (or a quote of another stat) -> player out
  (questionable: watch) -> no / stale consensus -> leak (consensus newer than the quote)
  -> tail rung -> no ask -> EV_market above the sanity cap ("check inputs")
  -> EV_blend below tau -> EV_market < 0 ("model-only value")
  -> size at the max price below the minimum ("thin": watch)
Then one pick per player-game and stat, and fractional-Kelly contracts under caps. The
per-bet cap is per player-game across stats: a player's points and rebounds picks share
it, since both ride on his minutes.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from . import config, distributions
from .config import MODEL, ModelParams
from .distributions import normal_side_p as side_p    # noqa: F401  (points: P(YES) under N(mean, sd))
from .distributions import sd_compound                # noqa: F401
from .fees import fee_per_contract, fee_total


def robust_p(mean: float, line: float, side: str, params: ModelParams = MODEL,
             stat: str = "points") -> tuple[float, float]:
    """(lower of the two models, spread between them): see distributions.robust_p."""
    return distributions.robust_p(stat, mean, line, side, params)


def blend(model_mean: float | None, cons_mean: float, params: ModelParams = MODEL,
          w: float = config.W_MODEL, z_max: float = config.Z_GAP_MAX,
          stat: str = "points") -> tuple[float, float, str | None]:
    """(blended mean, weight used, flag). The gap is judged in the stat's own SD."""
    if model_mean is None or (isinstance(model_mean, float) and math.isnan(model_mean)):
        return cons_mean, 0.0, "no projection: market only"
    gap = model_mean - cons_mean
    if abs(gap) > z_max * distributions.sd(stat, cons_mean, params):
        return cons_mean, 0.0, (f"model {gap:+.1f} {distributions.unit(stat)} from market (> {z_max} SD): "
                                "check minutes/injury inputs")
    return cons_mean + w * gap, w, None


def max_price(p: float, venue: str, tau: float, contracts: float = config.PLANNED_CONTRACTS,
              fee_rate: float | None = None) -> float | None:
    """Largest whole-cent price c with p - c - fee(c) >= tau, for an order of `contracts`."""
    for cents in range(99, 0, -1):
        c = cents / 100
        if p - c - fee_per_contract(venue, contracts, c, rate=fee_rate) >= tau - 1e-12:
            return c
    return None


def size_at(levels: list[tuple[float, float]] | None, cap: float | None) -> float:
    """Contracts offered at or under `cap` (dollars)."""
    if not levels or cap is None:
        return 0.0
    return float(sum(s for p, s in levels if p <= cap + 1e-9))


def vwap(levels: list[tuple[float, float]], n: float) -> float | None:
    got, cost = 0.0, 0.0
    for p, s in levels:
        take = min(s, n - got)
        got += take
        cost += take * p
        if got >= n - 1e-9:
            return cost / got
    return None


def tau_for(venue: str, n_books: int) -> float:
    tau = config.VENUE_MIN_EDGE.get(venue, max(config.VENUE_MIN_EDGE.values()))
    return tau + (config.THIN_CONSENSUS_EXTRA_EDGE if n_books <= config.MIN_PRICED_BOOKS else 0.0)


def config_hash() -> str:
    """Fingerprint of every number that changes a decision, logged on each row."""
    keys = ["EDGE_THRESHOLD", "MAX_CREDIBLE_EDGE", "VIG_METHOD", "BOOK_WEIGHTS", "VENUE_FEES", "VENUE_MIN_EDGE",
            "THIN_CONSENSUS_EXTRA_EDGE", "MIN_SIZE_AT_EDGE", "PLANNED_CONTRACTS", "TAIL_P", "W_MODEL",
            "Z_GAP_MAX", "SD_COMPOUND", "KELLY_LAMBDA", "MAX_BET_FRAC", "MAX_GAME_FRAC", "MAX_SLATE_FRAC",
            "MAX_QUOTE_AGE_MIN", "MIN_PRICED_BOOKS", "LEAK_TOLERANCE_MIN", "STATS", "COUNT_DISPERSION"]
    blob = json.dumps({k: getattr(config, k) for k in keys} | {"MODEL": MODEL.__dict__},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def signal_id(venue: str, ticker: str, side: str, tag: str | None, quote_ts) -> str:
    raw = f"{venue}|{ticker}|{side}|{tag}|{pd.Timestamp(quote_ts).isoformat() if quote_ts is not None else ''}"
    return hashlib.blake2s(raw.encode(), digest_size=8).hexdigest()


@dataclass
class Context:
    """What is known about one player-game when a venue quote is read."""
    now: datetime
    tip: datetime | None
    event_id: str | None = None
    game: str | None = None
    player_id: str | None = None
    stat: str = "points"                      # points | rebounds | assists
    status: str | None = None                 # roster / injury status, lower case
    consensus: object | None = None           # consensus.Consensus
    model_mean: float | None = None
    projection_ts: datetime | None = None
    params: ModelParams = MODEL


def contract_label(q: dict, side: str, stat: str = "points") -> str:
    """'25+ YES' / 'over 24.5' for points (as always); '8+ REB YES' / 'over 7.5 REB' for others."""
    tag = "" if stat == "points" else f" {config.STAT_LABELS.get(stat, stat)}"
    if q.get("threshold") is not None and not pd.isna(q.get("threshold")):
        return f"{int(q['threshold'])}+{tag} {side}"
    return f"{'over' if side == 'YES' else 'under'} {q['line']:g}{tag}"


def evaluate_contract(q: dict, side: str, ctx: Context, levels: list[tuple[float, float]] | None = None,
                      tag: str | None = None) -> dict:
    """One venue contract side -> one decision row (see the module docstring for the gates)."""
    venue = q["venue"]
    ask = q.get("yes_ask") if side == "YES" else q.get("no_ask")
    bid = q.get("yes_bid") if side == "YES" else q.get("no_bid")
    top_size = q.get("yes_ask_size") if side == "YES" else q.get("no_ask_size")
    ask = None if ask is None or pd.isna(ask) or not 0 < ask < 1 else float(ask)
    quote_ts = q.get("quote_ts") or ctx.now
    c = ctx.consensus
    stat = ctx.stat
    q_stat = q.get("stat") if isinstance(q.get("stat"), str) else None
    row = {
        "ts": ctx.now, "signal_id": signal_id(venue, q.get("ticker"), side, tag, quote_ts), "tag": tag,
        "event_id": ctx.event_id, "game": ctx.game, "player_id": ctx.player_id, "player": q.get("player"),
        "team": q.get("team"), "venue": venue, "ticker": q.get("ticker"), "event_ticker": q.get("event_ticker"),
        "stat": q_stat if "stat" in q else stat,
        "contract": (contract_label(q, side, q_stat or stat) if q.get("line") is not None
                     and not pd.isna(q.get("line")) else None),
        "side": side, "threshold": q.get("threshold"), "line": q.get("line"), "quote_ts": quote_ts,
        "tip_ts": ctx.tip, "status": ctx.status, "bid": bid, "ask": ask,
        "ask_size": None if top_size is None or pd.isna(top_size) else float(top_size),
        "fee_rate": q.get("fee_rate"), "n_books": 0 if c is None else c.n_books,
        "consensus_ts": None if c is None else c.snapshot_ts,
        "consensus_mean": None if c is None else c.mean, "consensus_line": None if c is None else c.line,
        "model_mean": ctx.model_mean, "projection_ts": ctx.projection_ts,
        "model_version": config.MODEL_VERSION, "config_hash": config_hash(),
        "decision": "abstain", "reason": None,
    }

    def done(decision: str, reason: str) -> dict:
        return {**row, "decision": decision, "reason": reason}

    if venue not in config.ACTIONABLE_VENUES:
        return done("reference", f"{venue}: reference price only (not tradable from the US)")
    if ctx.tip is None:
        return done("abstain", "no tip time: game not mapped to the schedule")
    if ctx.now >= ctx.tip or pd.Timestamp(quote_ts) >= pd.Timestamp(ctx.tip):
        return done("abstain", "after tip: in-game price")
    if isinstance(q.get("parse_error"), str) and q["parse_error"]:   # NaN from pandas is not an error
        return done("abstain", f"unparsed: {q['parse_error']}")
    if "stat" in q and q_stat != stat:                                # never price one stat off another
        return done("abstain", f"unparsed: a {q_stat or 'stat-less'} quote priced as {stat}")
    if ctx.player_id is None:
        return done("abstain", "unmatched name: not on this game's roster")
    status = (ctx.status or "").lower()
    if status in config.OUT_STATUSES:
        return done("abstain", f"player listed {status}")
    if c is not None and getattr(c, "stat", stat) != stat:            # a points consensus never prices rebounds
        return done("abstain", f"no consensus: the one given is for {c.stat}, not {stat}")
    if c is None or c.mean is None:
        return done("abstain", "no consensus: fewer than 2 priced books" if c is None else
                    (c.abstain_reason or "no consensus"))
    if c.abstain_reason:
        return done("abstain", c.abstain_reason)
    if c.snapshot_ts is not None and pd.Timestamp(c.snapshot_ts) > pd.Timestamp(quote_ts) + timedelta(
            minutes=config.LEAK_TOLERANCE_MIN):
        return done("abstain", "leak: consensus is newer than the venue quote")

    line = float(q["line"])
    row["rung_distance"] = round(line - c.line, 2) if c.line is not None else None
    p_mkt, _ = distributions.robust_p(stat, c.mean, line, side, ctx.params)
    p_mkt_center = distributions.side_p(stat, c.mean, line, side, ctx.params)
    m_b, w_eff, flag = blend(ctx.model_mean, c.mean, ctx.params, stat=stat)
    p_bl, spread = distributions.robust_p(stat, m_b, line, side, ctx.params)
    tau = tau_for(venue, c.n_books)
    row.update(p_market=p_mkt, w_model=w_eff, blend_mean=m_b, p_blend=p_bl, p_spread=spread, tau=tau)
    lo, hi = config.TAIL_P
    p_yes_center = p_mkt_center if side == "YES" else 1 - p_mkt_center
    if not lo <= p_yes_center <= hi:
        return done("abstain", f"tail rung: market P(YES) {100 * p_yes_center:.0f}% is outside "
                               f"{100 * lo:.0f}-{100 * hi:.0f}% (too far from the books' line)")
    if ask is None:
        return done("abstain", "no ask on this side")

    n_plan = config.PLANNED_CONTRACTS
    rate = _rate(q.get("fee_rate"))
    cost = ask + fee_per_contract(venue, n_plan, ask, rate=rate)
    ev_m, ev_b = p_mkt - cost, p_bl - cost
    # The limit must keep the edge on the blend AND never pay more than the market alone says
    # it's worth: otherwise the counted depth reaches prices the model-only gate would refuse.
    caps = [max_price(p_bl, venue, tau, n_plan, rate), max_price(p_mkt, venue, 0.0, n_plan, rate)]
    cap_price = None if None in caps else min(caps)
    book = levels if levels is not None else ([(ask, row["ask_size"])] if row["ask_size"] else [])
    size = size_at(book, cap_price)
    row.update(cost=cost, ev_market=ev_m, ev_blend=ev_b, max_price=cap_price, size_at_edge=size,
               ladder=";".join(f"{p:.4f}:{q_:g}" for p, q_ in sorted(book) if cap_price is not None
                               and p <= cap_price + 1e-9))
    if config.MAX_CREDIBLE_EDGE is not None and ev_m > config.MAX_CREDIBLE_EDGE:
        return done("abstain", f"edge {100 * ev_m:.1f}pp > {100 * config.MAX_CREDIBLE_EDGE:.0f}pp cap: "
                               "check inputs or a stale book")
    if ev_b < tau:
        return done("abstain", f"EV {100 * ev_b:.1f}pp < {100 * tau:.1f}pp after fees" + (f" ({flag})" if flag else ""))
    if ev_m < 0:
        return done("abstain", f"model-only value: the market says {100 * ev_m:.1f}pp")
    if status in config.QUESTIONABLE_STATUSES:
        return done("watch", f"player listed {status}: wait for the report")
    need = config.MIN_SIZE_AT_EDGE.get(venue, 10)
    if size < need:
        cap_txt = "?" if cap_price is None else f"{100 * cap_price:.0f}c"
        return done("watch", f"thin: {size:g} contracts at or under {cap_txt} (need {need})")
    return done("actionable", f"EV {100 * ev_b:.1f}pp (market {100 * ev_m:.1f}pp) at {100 * ask:.0f}c"
                              + (f"; {flag}" if flag else ""))


def _rate(rate) -> float | None:
    return None if rate is None or (isinstance(rate, float) and math.isnan(rate)) else float(rate)


def parse_ladder(text) -> list[tuple[float, float]]:
    if not isinstance(text, str) or not text:
        return []
    return sorted((float(p), float(q)) for p, q in (lv.split(":") for lv in text.split(";")))


def fill_cost(levels: list[tuple[float, float]], n: int, venue: str, rate: float | None) -> float | None:
    """All-in dollars for n contracts bought up the ladder: price paid level by level plus the
    venue fee for the order (taken at the average price, which can only overstate it)."""
    got, paid = 0.0, 0.0
    for p, s in levels:
        take = min(s, n - got)
        got += take
        paid += take * p
        if got >= n - 1e-9:
            return paid + fee_total(venue, n, paid / n, rate=rate)
    return None


def _stats(rows: pd.DataFrame) -> pd.Series:
    return rows.stat.fillna("points") if "stat" in rows else pd.Series("points", index=rows.index)


def pick_per_group(rows: pd.DataFrame, filled: set | None = None) -> pd.DataFrame:
    """Keep the best actionable contract per player-game and stat (across venues, rungs and
    sides). A (game, player, stat) Rohan already holds (`filled`) gets no new pick on that stat;
    a bare (game, player) key in `filled` blocks every stat of that player-game."""
    if rows.empty or "decision" not in rows:
        return rows
    rows = rows.copy()
    act = rows[rows.decision == "actionable"]
    if act.empty:
        return rows
    for key, grp in act.groupby([act.event_id.fillna(act.event_ticker), act.player_id.fillna(act.player),
                                 _stats(act)]):
        if filled and (key in filled or key[:2] in filled):
            what = "player-game" if key[2] == "points" else f"player-game ({key[2]})"
            rows.loc[grp.index, ["decision", "reason"]] = ["abstain", f"already holding this {what}"]
            continue
        best = grp.ev_blend.idxmax()
        for i in grp.index:
            if i != best:
                rows.loc[i, ["decision", "reason"]] = ["abstain",
                                                      f"player already has a pick: {rows.loc[best, 'venue']} "
                                                      f"{rows.loc[best, 'contract']}"]
    return rows


def kelly_fraction(p: float, cost: float) -> float:
    """Full Kelly for a $1 binary bought at all-in cost c: (p - c) / (1 - c)."""
    return 0.0 if cost >= 1 else max(0.0, (p - cost) / (1 - cost))


@dataclass
class Exposure:
    """Stake already committed today, as fractions of bankroll: fills plus live picks from
    earlier scans of other games. Caps hold across scans, not just within one."""
    slate: float = 0.0
    game: dict = field(default_factory=dict)        # event id -> fraction
    group: dict = field(default_factory=dict)       # (event id, player id) -> fraction, across stats
    filled: set = field(default_factory=set)        # (event id, player id, stat) already held


def size_positions(rows: pd.DataFrame, bankroll: float | None, prior: Exposure | None = None) -> pd.DataFrame:
    """Suggested contracts for actionable rows, highest EV first. Each contract's cost is walked up
    its ladder (VWAP plus the fee at the real order size), and the count is the largest that keeps
    EV >= tau on the blend, >= 0 on the market alone, quarter Kelly, and the per-bet, per-game
    and per-slate caps (counting `prior` exposure). The per-bet cap is per player-game across
    stats (points and rebounds on one player share it). No bankroll: the size available at the edge."""
    rows = rows.copy()
    for col in ("kelly", "stake_frac", "contracts", "stake_usd", "ev_blend", "p_blend", "p_market",
                "cost", "size_at_edge", "ladder", "tau"):
        if col not in rows:
            rows[col] = None
    act = rows[rows.decision == "actionable"].sort_values("ev_blend", ascending=False)
    if act.empty:
        return rows
    prior = prior or Exposure()
    game_used, group_used, slate_used = dict(prior.game), dict(prior.group), prior.slate
    for i, r in act.iterrows():
        levels = parse_ladder(r.ladder) or ([(r.ask, r.size_at_edge)] if r.size_at_edge else [])
        rate = _rate(r.fee_rate)
        game = r.event_id or r.event_ticker
        group = (game, r.player_id or r.player)
        room = None
        if bankroll is not None:
            room = bankroll * max(0.0, min(config.MAX_BET_FRAC - group_used.get(group, 0.0),
                                           config.MAX_GAME_FRAC - game_used.get(game, 0.0),
                                           config.MAX_SLATE_FRAC - slate_used))
        best = None
        n_max = min(int(sum(s for _, s in levels)), 20000)
        for n in range(1, n_max + 1):
            total = fill_cost(levels, n, r.venue, rate)
            if total is None:
                break
            if room is not None and total > room + 1e-9:
                break                                    # stakes only grow with n
            unit = total / n
            # Per-order fee rounding makes 1-2 contracts dearer per contract than 10, so a small n
            # can miss the bar while a larger one clears it: keep scanning, keep the largest valid n.
            if r.p_blend - unit < r.tau - 1e-12 or r.p_market - unit < -1e-12:
                continue
            if room is not None and total > config.KELLY_LAMBDA * kelly_fraction(r.p_blend, unit) * bankroll + 1e-9:
                continue
            best = (n, total, unit)
        if best is None:
            if room is not None and room < 0.01:
                # Name the cap that binds: a player's stats share one per-player cap.
                player_room = config.MAX_BET_FRAC - group_used.get(group, 0.0)
                other_room = min(config.MAX_GAME_FRAC - game_used.get(game, 0.0), config.MAX_SLATE_FRAC - slate_used)
                reason = (f"per-player cap ({100 * config.MAX_BET_FRAC:g}% per player-game, all stats) "
                          "used by an earlier pick" if player_room <= other_room else "over the game or slate cap")
            else:
                reason = "stake rounds to 0 contracts" if bankroll is not None else "no size at the edge"
            rows.loc[i, ["decision", "reason"]] = ["watch", reason]
            continue
        n, total, unit = best
        rows.loc[i, ["contracts", "cost", "ev_blend", "ev_market", "kelly"]] = [
            n, unit, r.p_blend - unit, r.p_market - unit, kelly_fraction(r.p_blend, unit)]
        rows.loc[i, "stake_usd"] = round(total, 2)
        if bankroll is not None:
            frac = total / bankroll
            rows.loc[i, "stake_frac"] = frac
            game_used[game] = game_used.get(game, 0.0) + frac
            group_used[group] = group_used.get(group, 0.0) + frac
            slate_used += frac
    return rows
