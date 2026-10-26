"""Venue scan: Kalshi and Polymarket prices for a slate, decided and logged before tip.

For every game on the stored slate that hasn't tipped:
1. read the venues: the game's Kalshi events in the points, rebounds and assists
   series (config.KALSHI_SERIES), its Polymarket US event (points, rebounds and
   assists props), and the international Polymarket event as a points reference
   price only;
2. map each market to the game and to a player on one of its two rosters (by
   name within the game, never league-wide; Kalshi's team code must match);
3. evaluate both sides with decision.evaluate_contract against that stat's
   consensus and projection, reading order-book depth only for contracts that
   already clear the bar at the top of the book;
4. keep one pick per player-game and stat, size it (the per-bet cap is shared
   across a player's stats), and append every quote to venue_snapshots and every
   decision to venue_signals, each with its stat.

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
from .decision import Context, Exposure, evaluate_contract, pick_per_group, size_positions
from .kalshi import event_code
from .pipeline import events_on, latest_projections
from .players import name_key
from .schedule import et_date
from .storage import Storage

Levels = list[tuple[float, float]]


@dataclass
class Fetchers:
    """Injected venue readers, so tests (and a run without network) never touch a venue.
    Any of them may be None; errors are reported per game, never fatal. `clock` stamps each
    read with when the venue actually answered (live: wall-clock UTC; tests: the scan time)."""
    kalshi_markets: Callable[[], list[dict]] | None = None             # open markets of every KALSHI_SERIES
    kalshi_books: Callable[[list[str]], dict[str, dict[str, Levels]]] | None = None  # tickers -> ladders
    pm_us_event: Callable[[str, str, date], dict | None] | None = None
    pm_us_book: Callable[[str], dict[str, Levels]] | None = None        # market slug -> ladders
    pm_intl_event: Callable[[str, str, date], dict | None] | None = None
    clock: Callable[[], datetime] | None = None
    errors: list[str] = field(default_factory=list)


def live_fetchers() -> Fetchers:
    import requests

    from . import kalshi, polymarket, polymarket_us
    from .storage import utcnow
    session = requests.Session()
    reader = kalshi.KalshiReader(session)
    f = Fetchers(kalshi_books=reader.orderbooks,
                 pm_us_event=lambda a, h, d: polymarket_us.find_game(a, h, d, session),
                 pm_us_book=lambda s: polymarket_us.book(s, session),
                 pm_intl_event=lambda a, h, d: polymarket.find_game(a, h, d, session), clock=utcnow)
    f.kalshi_markets = lambda: kalshi_series_markets(reader.open_markets, f.errors)
    return f


def kalshi_series_markets(read: Callable[[str], list[dict]], errors: list[str]) -> list[dict]:
    """Open markets of every configured Kalshi series, one read each. A series that fails is
    recorded and skipped, so a rebounds outage never drops the points ladders; only when
    every series fails does the read fail (and the checkpoint stays open for the next tick)."""
    out, failed = [], []
    for series in config.KALSHI_SERIES.values():
        try:
            out += read(series)
        except Exception as exc:
            failed.append(series)
            errors.append(f"kalshi {series}: {type(exc).__name__}: {exc}")
    if len(failed) == len(config.KALSHI_SERIES):
        raise RuntimeError(f"every Kalshi series failed ({', '.join(failed)})")
    return out


def _roster(storage: Storage, event_id: str) -> pd.DataFrame:
    return storage.query("""
        SELECT player_id, name, team_abbr, status FROM (
          SELECT *, row_number() OVER (PARTITION BY player_id ORDER BY ts DESC) rn
          FROM event_players WHERE event_id = ?) WHERE rn = 1""", [event_id])


def roster_keys(roster: pd.DataFrame) -> tuple[dict, set]:
    """name_key -> roster row, using the display name, the name inside the player ID, and the
    stats-name overrides; keys shared by two players are returned as ambiguous."""
    from .players import load_overrides, name_from_player_id
    by_pid_name = {pid: name for name, pid in load_overrides().items()}
    keys: dict[str, set] = {}
    rows = {r.player_id: r for r in roster.itertuples()}
    for r in roster.itertuples():
        for n in {r.name, name_from_player_id(r.player_id), by_pid_name.get(r.player_id)}:
            if isinstance(n, str) and n:
                keys.setdefault(name_key(n), set()).add(r.player_id)
    by_key = {k: rows[next(iter(v))] for k, v in keys.items() if len(v) == 1}
    return by_key, {k for k, v in keys.items() if len(v) > 1}


def game_quotes(ev, fetchers: Fetchers, kalshi_df: pd.DataFrame | None, kalshi_ts: datetime | None,
                clock: Callable[[], datetime]) -> pd.DataFrame:
    """All venue quotes for one game, normalized (prices in dollars), each stamped with its read time."""
    from . import polymarket, polymarket_us
    d = et_date(ev.starts_at)
    parts = []
    if kalshi_df is not None and len(kalshi_df):
        code = event_code(d, ev.away_abbr, ev.home_abbr)
        k = kalshi_df[kalshi_df.event_ticker.isin({f"{series}-{code}" for series in config.KALSHI_SERIES.values()})]
        parts.append(k.assign(venue="kalshi", fee_rate=None, quote_ts=kalshi_ts))
    for name, getter, parse in (("polymarket_us", fetchers.pm_us_event, polymarket_us.prop_markets),
                                ("polymarket_intl", fetchers.pm_intl_event, polymarket.points_markets)):
        if getter is None:
            continue
        try:
            event = getter(ev.away_abbr, ev.home_abbr, d)
        except Exception as exc:                         # one venue's outage never blocks the others
            fetchers.errors.append(f"{name} {ev.away_abbr}@{ev.home_abbr}: {type(exc).__name__}")
            continue
        if event:
            parts.append(parse(event).assign(quote_ts=clock()))
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def issued_tickets(storage: Storage, d: date, now: datetime) -> pd.DataFrame:
    """Every ticket already sent on this ET slate by `now`: the first actionable decision per
    player-game and stat (the journal's ticket), however old, tipped or not."""
    df = storage.query("""
        SELECT * FROM (
          SELECT *, row_number() OVER (
                   PARTITION BY coalesce(event_id, event_ticker), coalesce(player_id, player), coalesce(stat, 'points')
                   ORDER BY ts, ev_blend DESC, signal_id) AS rn
          FROM venue_signals WHERE decision = 'actionable' AND stake_usd IS NOT NULL
                                   AND tip_ts IS NOT NULL AND ts <= ?)
        WHERE rn = 1""", [now])
    return df[df.tip_ts.map(et_date) == d] if len(df) else df


def prior_exposure(storage: Storage, d: date, now: datetime, bankroll: float | None) -> Exposure:
    """What's already committed on this ET slate: Rohan's fills, plus every ticket already sent
    (`issued_tickets`), so a later scan can't stack new stakes past the caps. A rescan's pick on
    a player-stat that already has a ticket replaces it (see size_positions)."""
    out = Exposure()
    fills = fills_with_games(storage)
    if len(fills):
        fills = fills[fills.tip_ts.notna()]
        fills = fills[fills.tip_ts.map(et_date) == d]
        for r in fills.itertuples():
            out.filled.add((r.event_id, r.player_id, "points" if pd.isna(r.stat) else r.stat))
            if bankroll:
                frac = (r.contracts * r.price + (0.0 if pd.isna(r.fees) else r.fees)) / bankroll
                out.game[r.event_id] = out.game.get(r.event_id, 0.0) + frac
                out.group[(r.event_id, r.player_id)] = out.group.get((r.event_id, r.player_id), 0.0) + frac
                out.slate += frac
    if bankroll:
        for r in issued_tickets(storage, d, now).itertuples():
            game = r.event_ticker if pd.isna(r.event_id) else r.event_id
            player = r.player if pd.isna(r.player_id) else r.player_id
            key = (game, player, "points" if pd.isna(r.stat) else r.stat)
            if key in out.filled:
                continue
            frac = r.stake_usd / bankroll
            out.issued[key] = frac
            out.game[game] = out.game.get(game, 0.0) + frac
            out.group[(game, player)] = out.group.get((game, player), 0.0) + frac
            out.slate += frac
    return out


def fills_with_games(storage: Storage) -> pd.DataFrame:
    """Rohan's current fills (corrections applied), with the game, player and stat they belong to."""
    t = storage.query("SELECT * FROM tickets")
    if t.empty:
        return t
    replaced = set(t.replaces.dropna())
    t = t[~t.fill_id.isin(replaced)]
    games = storage.query("""SELECT DISTINCT venue, ticker, event_id, player_id, coalesce(stat, 'points') AS stat,
                                    tip_ts FROM venue_signals
                             WHERE ticker IS NOT NULL""").drop_duplicates(["venue", "ticker"])
    return t.merge(games, on=["venue", "ticker"], how="left")


def scan(storage: Storage, d: date, now: datetime, fetchers: Fetchers, tag: str = "adhoc",
         log: bool = True, event_ids: set[str] | None = None,
         bankroll: float | None = None) -> pd.DataFrame:
    from .kalshi import parse_markets
    clock = fetchers.clock or (lambda: now)
    kalshi_df, kalshi_ts = None, None
    if fetchers.kalshi_markets is not None:
        try:
            raw = fetchers.kalshi_markets()
            kalshi_ts = clock()
            kalshi_df = parse_markets(raw)
        except Exception as exc:
            fetchers.errors.append(f"kalshi markets: {type(exc).__name__}: {exc}")
    out = []
    for ev in events_on(storage, d).itertuples():
        if event_ids is not None and ev.event_id not in event_ids:
            continue
        tip = pd.Timestamp(ev.starts_at).to_pydatetime()
        if now >= tip or bool(getattr(ev, "cancelled", False)):
            continue
        quotes = game_quotes(ev, fetchers, kalshi_df, kalshi_ts, clock)
        snaps = []
        # Kalshi answered but lists nothing for this game: log that, so the checkpoint counts as
        # read. A failed Kalshi read logs nothing, and the next cron tick retries the checkpoint.
        if kalshi_df is not None and (quotes.empty or not (quotes.venue == "kalshi").any()) and kalshi_ts < tip:
            snaps.append({"ts": kalshi_ts, "tag": tag, "venue": "kalshi", "event_id": ev.event_id, "tip_ts": tip,
                          "parse_error": "no listing"})
        if quotes.empty:
            if log and snaps:
                storage.append("venue_snapshots", snaps)
            continue
        roster = _roster(storage, ev.event_id)
        by_key, dupes = roster_keys(roster)
        cons = {stat: consensus_by_player(storage, ev.event_id, as_of=now, before=now, stat=stat)
                for stat in config.STATS}
        projs = {(p.player_id, p.stat): p for p in latest_projections(storage, ev.event_id, now).itertuples()}
        game = f"{ev.away_abbr} @ {ev.home_abbr}"
        rows, pending = [], []
        for q in quotes.to_dict("records"):
            r = by_key.get(q.get("key"))
            if r is not None and r.team_abbr in config.CATALOG_EXCLUDED_TEAMS:
                continue
            q_team = q.get("team") if isinstance(q.get("team"), str) else None
            team_ok = r is not None and q_team in (None, r.team_abbr)
            pid = r.player_id if team_ok else None
            if team_ok and q_team is None:
                q = {**q, "team": r.team_abbr}               # venues without a team code take the roster's
            stat = q.get("stat") if q.get("stat") in config.STATS else None   # unknown: already a parse error
            p = projs.get((pid, stat))
            ctx = Context(now=now, tip=tip, event_id=ev.event_id, game=game, player_id=pid, stat=stat or "points",
                          status=None if r is None or pd.isna(r.status) else str(r.status).lower(),
                          consensus=cons.get(stat, {}).get(pid),
                          model_mean=None if p is None or pd.isna(p.mean) else float(p.mean),
                          projection_ts=None if p is None else p.ts)
            if q.get("key") in dupes:
                q = {**q, "parse_error": "ambiguous name on this game's rosters"}
            qts = q.get("quote_ts")
            if qts is not None and pd.Timestamp(qts) < pd.Timestamp(tip):
                snaps.append({k: q.get(k) for k in ("venue", "event_ticker", "ticker", "player", "team", "stat",
                                                    "threshold", "line", "yes_bid", "yes_ask", "no_bid", "no_ask",
                                                    "yes_ask_size", "no_ask_size", "volume", "fee_rate", "parse_error")}
                             | {"ts": qts, "tag": tag, "event_id": ev.event_id, "player_id": pid, "tip_ts": tip,
                                "open_interest": q.get("open_interest")})
            for side in ("YES", "NO"):
                row = evaluate_contract(q, side, ctx, tag=tag)
                rows.append(row)
                # Depth only for contracts that already clear the bar at the top of the book.
                if row["decision"] in ("actionable", "watch") and str(row["reason"]).startswith(("thin", "EV")):
                    pending.append((len(rows) - 1, q, side, ctx))
        books, book_ts = _depth(pending, fetchers), clock()
        for i, q, side, ctx in pending:
            ladders = books.get((q["venue"], q["ticker"]))
            if ladders is not None:                          # an empty side is an empty book, not "unknown"
                rows[i] = evaluate_contract({**q, "quote_ts": max(pd.Timestamp(q["quote_ts"]), pd.Timestamp(book_ts))},
                                            side, ctx, levels=ladders.get(side, []), tag=tag)
        # A read that came back at or after tip is an in-game price: never log it as pre-game.
        late = [r for r in rows if pd.Timestamp(r["quote_ts"]) >= pd.Timestamp(tip)]
        if late:
            fetchers.errors.append(f"{game}: {len(late)} contract side(s) read at or after tip, not logged")
        rows = [r for r in rows if pd.Timestamp(r["quote_ts"]) < pd.Timestamp(tip)]
        if log and snaps:
            storage.append("venue_snapshots", snaps)
        out += rows
    df = pd.DataFrame(out)
    if df.empty:
        return df
    prior = prior_exposure(storage, d, now, bankroll)
    df = size_positions(pick_per_group(df, prior.filled), bankroll, prior)
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


def latest_venue_signals(storage: Storage, now: datetime,
                         max_age_min: float = config.VENUE_SIGNAL_MAX_AGE_MIN) -> pd.DataFrame:
    """Decisions from the most recent read of each game on each venue, if that read is fresh and
    the game hasn't tipped. A contract missing from the latest read (a failed fetch, a delisted
    market) drops out instead of leaving an old decision live."""
    df = storage.query("""
        WITH last AS (SELECT event_id, venue, max(ts) AS ts FROM venue_signals
                      WHERE tip_ts > ? AND ts <= ? GROUP BY 1, 2)
        SELECT s.* FROM venue_signals s JOIN last USING (event_id, venue, ts)
        WHERE s.tip_ts > ?""", [now, now, now])
    if df.empty:
        return df
    return df[pd.to_datetime(df.ts) >= pd.Timestamp(now) - pd.Timedelta(minutes=max_age_min)]
