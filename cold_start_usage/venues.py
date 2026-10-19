"""Venue scan: Kalshi and Polymarket prices for a slate, decided and logged before tip.

For every game on the stored slate that hasn't tipped:
1. read the venues: the game's Kalshi KXNBAPTS event, its Polymarket US event,
   and the international Polymarket event as a reference price only;
2. map each market to the game and to a player on one of its two rosters (by
   name within the game, never league-wide; Kalshi's team code must match);
3. evaluate both sides with decision.evaluate_contract, reading order-book
   depth only for contracts that already clear the bar at the top of the book;
4. keep one pick per player-game, size it, and append every quote to
   venue_snapshots and every decision to venue_signals.

Every parsed market yields two rows, actionable or not, so nothing in the
cold-start population disappears silently. Venue reads are free public GETs
and never go through the SportsGameOdds client or its budget.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

import pandas as pd

from . import config
from .consensus import consensus_by_player
from .decision import Context, evaluate_contract, pick_per_group, size_positions
from .kalshi import SERIES, event_code
from .pipeline import events_on, latest_projections
from .players import name_key
from .schedule import et_date
from .storage import Storage

Levels = list[tuple[float, float]]


@dataclass
class Fetchers:
    """Injected venue readers, so tests (and a run without network) never touch a venue.
    Any of them may be None; errors are reported per game, never fatal."""
    kalshi_markets: Callable[[], list[dict]] | None = None             # all open KXNBAPTS markets
    kalshi_books: Callable[[list[str]], dict[str, dict[str, Levels]]] | None = None  # tickers -> ladders
    pm_us_event: Callable[[str, str, date], dict | None] | None = None
    pm_us_book: Callable[[str], dict[str, Levels]] | None = None        # market slug -> ladders
    pm_intl_event: Callable[[str, str, date], dict | None] | None = None
    errors: list[str] = field(default_factory=list)


def live_fetchers() -> Fetchers:
    import requests

    from . import kalshi, polymarket, polymarket_us
    session = requests.Session()
    reader = kalshi.KalshiReader(session)
    return Fetchers(kalshi_markets=lambda: reader.open_markets(SERIES), kalshi_books=reader.orderbooks,
                    pm_us_event=lambda a, h, d: polymarket_us.find_game(a, h, d, session),
                    pm_us_book=lambda s: polymarket_us.book(s, session),
                    pm_intl_event=lambda a, h, d: polymarket.find_game(a, h, d, session))


def _roster(storage: Storage, event_id: str) -> pd.DataFrame:
    return storage.query("""
        SELECT player_id, name, team_abbr, status FROM (
          SELECT *, row_number() OVER (PARTITION BY player_id ORDER BY ts DESC) rn
          FROM event_players WHERE event_id = ?) WHERE rn = 1""", [event_id])


def game_quotes(ev, fetchers: Fetchers, kalshi_df: pd.DataFrame | None, now: datetime) -> pd.DataFrame:
    """All venue quotes for one game, normalized (prices in dollars)."""
    from . import polymarket, polymarket_us
    d = et_date(ev.starts_at)
    parts = []
    if kalshi_df is not None and len(kalshi_df):
        k = kalshi_df[kalshi_df.event_ticker == f"{SERIES}-{event_code(d, ev.away_abbr, ev.home_abbr)}"]
        parts.append(k.assign(venue="kalshi", fee_rate=None))
    for name, getter, parse in (("polymarket_us", fetchers.pm_us_event, polymarket_us.points_markets),
                                ("polymarket_intl", fetchers.pm_intl_event, polymarket.points_markets)):
        if getter is None:
            continue
        try:
            event = getter(ev.away_abbr, ev.home_abbr, d)
        except Exception as exc:                         # one venue's outage never blocks the others
            fetchers.errors.append(f"{name} {ev.away_abbr}@{ev.home_abbr}: {type(exc).__name__}")
            continue
        if event:
            parts.append(parse(event))
    parts = [p for p in parts if len(p)]
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True).assign(quote_ts=now)


def scan(storage: Storage, d: date, now: datetime, fetchers: Fetchers, tag: str = "adhoc",
         log: bool = True, event_ids: set[str] | None = None,
         bankroll: float | None = None) -> pd.DataFrame:
    from .kalshi import parse_markets
    kalshi_df = None
    if fetchers.kalshi_markets is not None:
        try:
            kalshi_df = parse_markets(fetchers.kalshi_markets())
        except Exception as exc:
            fetchers.errors.append(f"kalshi markets: {type(exc).__name__}: {exc}")
    out = []
    for ev in events_on(storage, d).itertuples():
        if event_ids is not None and ev.event_id not in event_ids:
            continue
        tip = pd.Timestamp(ev.starts_at).to_pydatetime()
        if now >= tip or bool(getattr(ev, "cancelled", False)):
            continue
        quotes = game_quotes(ev, fetchers, kalshi_df, now)
        if quotes.empty:
            continue
        roster = _roster(storage, ev.event_id).assign(key=lambda r: r.name.map(name_key))
        dupes = set(roster.key[roster.key.duplicated()])
        by_key = {r.key: r for r in roster.itertuples() if r.key not in dupes}
        cons = consensus_by_player(storage, ev.event_id, as_of=now, before=now)
        projs = {p.player_id: p for p in latest_projections(storage, ev.event_id, now).itertuples()}
        game = f"{ev.away_abbr} @ {ev.home_abbr}"
        snaps, rows, pending = [], [], []
        for q in quotes.to_dict("records"):
            r = by_key.get(q.get("key"))
            if r is not None and r.team_abbr in config.CATALOG_EXCLUDED_TEAMS:
                continue
            team_ok = r is not None and (q.get("team") in (None, r.team_abbr) or pd.isna(q.get("team")))
            pid = r.player_id if team_ok else None
            p = projs.get(pid)
            ctx = Context(now=now, tip=tip, event_id=ev.event_id, game=game, player_id=pid,
                          status=None if r is None or pd.isna(r.status) else str(r.status).lower(),
                          consensus=cons.get(pid), model_mean=None if p is None or pd.isna(p.mean) else float(p.mean),
                          projection_ts=None if p is None else p.ts)
            if q.get("key") in dupes:
                q = {**q, "parse_error": "ambiguous name on this game's rosters"}
            snaps.append({k: q.get(k) for k in ("venue", "event_ticker", "ticker", "player", "team", "threshold",
                                                "line", "yes_bid", "yes_ask", "no_bid", "no_ask", "yes_ask_size",
                                                "no_ask_size", "volume", "fee_rate", "parse_error")}
                         | {"ts": now, "tag": tag, "event_id": ev.event_id, "player_id": pid, "tip_ts": tip,
                            "open_interest": q.get("open_interest")})
            for side in ("YES", "NO"):
                row = evaluate_contract(q, side, ctx, tag=tag)
                rows.append(row)
                # Depth only for contracts that already clear the bar at the top of the book.
                if row["decision"] in ("actionable", "watch") and str(row["reason"]).startswith(("thin", "EV")):
                    pending.append((len(rows) - 1, q, side, ctx))
        books = _depth(pending, fetchers)
        for i, q, side, ctx in pending:
            ladders = books.get((q["venue"], q["ticker"]))
            if ladders is not None:
                rows[i] = evaluate_contract(q, side, ctx, levels=ladders[side], tag=tag)
        if log:
            storage.append("venue_snapshots", snaps)
        out += rows
    df = pd.DataFrame(out)
    if df.empty:
        return df
    df = size_positions(pick_per_group(df), bankroll)
    if log:
        storage.append("venue_signals", df)
    return df


def _depth(pending: list, fetchers: Fetchers) -> dict[tuple[str, str], dict[str, Levels]]:
    """Order books for the candidate contracts: Kalshi in batches of 100, Polymarket US per market."""
    out: dict[tuple[str, str], dict[str, Levels]] = {}
    kalshi = sorted({q["ticker"] for _, q, _, _ in pending if q["venue"] == "kalshi"})
    if kalshi and fetchers.kalshi_books is not None:
        try:
            out.update({("kalshi", t): b for t, b in fetchers.kalshi_books(kalshi).items()})
        except Exception as exc:
            fetchers.errors.append(f"kalshi books: {type(exc).__name__}")
    for t in sorted({q["ticker"] for _, q, _, _ in pending if q["venue"] == "polymarket_us"}):
        if fetchers.pm_us_book is None:
            break
        try:
            out[("polymarket_us", t)] = fetchers.pm_us_book(t)
        except Exception as exc:
            fetchers.errors.append(f"book {t}: {type(exc).__name__}")
    return out


def latest_venue_signals(storage: Storage, now: datetime) -> pd.DataFrame:
    """The most recent decision per contract side for games that haven't tipped."""
    return storage.query("""
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY venue, ticker, side ORDER BY ts DESC) rn
          FROM venue_signals WHERE tip_ts > ? AND ts <= ?) WHERE rn = 1""", [now, now])
