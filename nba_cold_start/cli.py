"""Command line: usage | books | snapshot | project | signals | watchlist | grade | report | fit |
catalog | board | kalshi | venues.

    python -m nba_cold_start.cli snapshot --date 2026-10-21
    python -m nba_cold_start.cli project --date 2026-10-21 --scenario MIA=full_strength --scenario TOR=kawhi_out
    python -m nba_cold_start.cli signals --date 2026-10-21
    python -m nba_cold_start.cli watchlist --date 2026-10-21
    python -m nba_cold_start.cli grade --date 2026-10-21

Research only: nothing here places, sizes or routes an order anywhere.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from . import config
from .consensus import consensus_by_player, venue_quotes
from .grade import calibration, graded_signals, summarize
from .ingest import player_points_side
from .pipeline import (events_on, fetch_results, ledger_for, run_projections, run_signals,
                       snapshot_due, snapshot_from_file, snapshot_slate)
from .report import write_report
from .schedule import et_date, iso_z
from .sgo_client import SGOClient, SGOError
from .signals import make_signal
from .storage import Storage, to_naive_utc, utcnow
from .watchlist import ladder, watchlist_rows

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 60)


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _print_table(df: pd.DataFrame, cols: list[str] | None = None) -> None:
    if df.empty:
        print("(no rows)")
        return
    cols = [c for c in (cols or df.columns) if c in df.columns]
    print(df[cols].round(3).to_string(index=False))


def _client(storage: Storage, now_fn) -> SGOClient:
    return SGOClient(ledger=ledger_for(storage, now_fn),
                     local_used=lambda: storage.objects_used_this_month())


def _budget_line(storage: Storage, usage, spent: int) -> str:
    server = usage.objects_used if usage else None
    est = None if server is None else server + config.USAGE_CALL_OBJECTS + spent
    local = storage.objects_used_this_month()
    used = max(v for v in (est, local) if v is not None)
    return (f"objects this run: {spent} | used this month: ~{used} "
            f"(server before run: {server}, local ledger: {local}) | "
            f"remaining to hard stop {config.MONTHLY_OBJECT_HARD_STOP}: {config.MONTHLY_OBJECT_HARD_STOP - used} | "
            f"plan limit {config.MONTHLY_OBJECT_LIMIT}")


# --- commands ---------------------------------------------------------------------
def cmd_usage(args, storage, now_fn) -> int:
    client = _client(storage, now_fn)
    u = client.usage()
    print(f"tier={u.tier} active={u.is_active} objects used this month={u.objects_used} "
          f"plan max={u.objects_max} | requests this minute={u.requests_this_minute}/{u.requests_max_minute}")
    if u.objects_used is not None:
        print(f"remaining to hard stop {config.MONTHLY_OBJECT_HARD_STOP}: {config.MONTHLY_OBJECT_HARD_STOP - u.objects_used}")
    if args.measure:
        u2 = client.usage()
        if None not in (u.objects_used, u2.objects_used):
            print(f"/account/usage costs {u2.objects_used - u.objects_used} object(s) per call "
                  f"(config.USAGE_CALL_OBJECTS = {config.USAGE_CALL_OBJECTS})")
    return 0


def cmd_books(args, storage, now_fn) -> int:
    """First task: which allowlisted books this key returns, and who posts NBA player points."""
    now = now_fn()
    client = _client(storage, now_fn)
    params = {"leagueID": config.LEAGUE_ID, "oddsAvailable": "true", "startsAfter": iso_z(now)}
    result = client.events(params, max_objects=1, note="books-discovery")
    if not result.events:
        print("No upcoming NBA event with available odds was returned.")
        return 1
    ev = result.events[0]
    roles = {"reference": set(), "target": set(), "unpriced": set()}
    points_books, ages = set(), {}
    for odd_id, odd in (ev.get("odds") or {}).items():
        is_points = player_points_side(odd_id, odd) is not None
        for book, q in (odd.get("byBookmaker") or {}).items():
            roles[config.book_role(book)].add(book)
            if is_points:
                points_books.add(book)
                ts = to_naive_utc(q.get("lastUpdatedAt"))
                if ts:
                    ages.setdefault(book, []).append((now - ts).total_seconds() / 60)
    # A "reference" book that only ever shows +100 is really a pick'em app: treat it as unpriced.
    for book in sorted(roles["reference"]):
        prices = {str(o["byBookmaker"][book].get("odds")) for o in ev["odds"].values() if book in o["byBookmaker"]}
        if prices <= {"+100", "100"}:
            roles["reference"].discard(book)
            roles["unpriced"].add(book)
    books = {"discovered_at": iso_z(now), "event_id": ev["eventID"],
             **{k: sorted(v) for k, v in roles.items()},
             "posts_player_points": sorted(points_books), "off_list_count": result.off_list_books}
    config.BOOKS_FILE.write_text(json.dumps(books, indent=2) + "\n")
    priced_points = sorted(roles["reference"] & points_books)
    print(f"Event {ev['eventID']}: {sum(len(v) for v in roles.values())} allowlisted books returned")
    for role, label in (("reference", "priced reference"), ("target", "prediction-market target"),
                        ("unpriced", "unpriced (DFS)")):
        print(f"  {label:26s}: {', '.join(sorted(roles[role])) or '-'}")
    print(f"  off-list books returned  : {result.off_list_books} (not stored, not shown)")
    print(f"Priced reference books posting NBA player points: {len(priced_points)} ({', '.join(priced_points) or '-'})")
    targets_posting = sorted(roles["target"] & points_books)
    print(f"Target venues posting NBA player points: {', '.join(targets_posting) or 'none yet'}")
    if ages:
        print("Player-points quote age at fetch (minutes, median / max) - checks STALENESS_CLOCK:")
        for b in sorted(ages):
            print(f"  {b:14s} {statistics.median(ages[b]):6.1f} / {max(ages[b]):6.1f}")
    print(f"Saved {config.BOOKS_FILE}")
    print(_budget_line(storage, result.usage_before, result.objects))
    return 0


def cmd_snapshot(args, storage, now_fn) -> int:
    now = now_fn()
    if args.from_file:
        out = snapshot_from_file(storage, json.loads(Path(args.from_file).read_text()), now)
        print(f"Loaded {out['events']} event(s) from file: {out['odds_snapshots']} quotes, "
              f"tags {sorted(set(out['tags'].values()))} (0 API objects)")
        return 0
    client = _client(storage, now_fn)
    if args.due:
        out = snapshot_due(client, storage, now)
        if out["slate"]:
            print(f"Slate {et_date(now)}: {out['slate']['events']} event(s) stored")
        print("Due: " + (", ".join(f"{e}={t}" for e, t in sorted(out["due"].items())) or "nothing due"))
        if args.with_signals:
            for tag in config.SIGNAL_TIMINGS:
                ids = {e for e, t in out["due"].items() if t == tag}
                if ids:
                    df, msgs = run_signals(storage, et_date(now), now, timing=tag, event_ids=ids)
                    for m in msgs:
                        print(f"note: {m}")
                    n_paper = int((df.decision == "paper").sum()) if not df.empty else 0
                    print(f"Signals at {tag}: {len(df)} logged ({n_paper} paper)"
                          + ("" if len(df) else " - no projections logged for these events yet"))
        usage = out.get("usage_before") or (out["slate"] or {}).get("usage_before")
        if usage is None:
            print(f"No API call this run. Local ledger: {storage.objects_used_this_month()} objects this month")
        else:
            print(_budget_line(storage, usage, out["objects"]))
        return 0
    d = args.date or et_date(now)
    out = snapshot_slate(client, storage, d, now)
    print(f"Stored {out['events']} event(s), {out['odds_snapshots']} player-points quotes, "
          f"{out['event_players']} roster rows for {d}")
    for n in out["notices"]:
        print(f"API notice: {n}")
    targets = storage.query("""SELECT book, count(DISTINCT player_id) AS players FROM odds_snapshots
                               WHERE ts = ? AND book_role = 'target' GROUP BY book""", [now])
    for r in targets.itertuples():
        print(f"Prediction market posted: {r.book} has player points for {r.players} player(s)")
    print(_budget_line(storage, out["usage_before"], out["objects"]))
    return 0


def _scenario_choice(pairs: list[str]) -> dict[str, str]:
    out = {}
    for p in pairs or []:
        team, _, name = p.partition("=")
        if not name:
            raise SystemExit(f"--scenario expects TEAM=name, got {p!r}")
        out[team.strip().upper()] = name.strip()
    return out


def cmd_project(args, storage, now_fn) -> int:
    now = now_fn()
    d = args.date or et_date(now)
    table, messages = run_projections(storage, d, now, _scenario_choice(args.scenario))
    for m in messages:
        print(f"note: {m}")
    if table.empty:
        return 1
    # Preview against the latest consensus (signals are logged by `signals`, not here).
    previews = []
    for eid in table.event.unique():
        cons = consensus_by_player(storage, eid, as_of=now, before=now)
        for r in table[table.event == eid].itertuples():
            c = cons.get(r.player_id)
            sig = make_signal({"mean": r.proj, "sd": r.sd} if r.proj is not None and not pd.isna(r.proj) else None, c)
            previews.append({"player": r.player, "cons_line": sig["line"], "cons_mean": sig["consensus_mean"],
                             "side": sig["side"], "edge": sig["edge"], "decision": sig["decision"],
                             "reason": sig["reason"]})
    table = table.merge(pd.DataFrame(previews), on="player", how="left")
    print(f"Logged projections at {now:%Y-%m-%d %H:%M} UTC (model {config.MODEL_VERSION})")
    _print_table(table, ["team", "scenario", "player", "status", "min", "usg", "usg_proj", "ppg_25_26",
                         "proj", "sd", "spc_old", "spc_new", "cons_line", "cons_mean", "side", "edge",
                         "decision", "reason"])
    return 0


def cmd_signals(args, storage, now_fn) -> int:
    now = now_fn()
    d = args.date or et_date(now)
    df, messages = run_signals(storage, d, now, timing=args.timing)
    for m in messages:
        print(f"note: {m}")
    if df.empty:
        print("No signals: run `project` first (and `snapshot` for market data).")
        return 1
    print(f"Logged {len(df)} signal row(s) at {now:%Y-%m-%d %H:%M} UTC "
          f"({(df.decision == 'paper').sum()} paper, {(df.decision == 'abstain').sum()} abstain)")
    df = df.rename(columns={"model_mean": "proj", "consensus_mean": "cons_mean"})
    _print_table(df, ["team", "player_name", "timing", "proj", "cons_mean", "line", "side",
                      "model_p", "consensus_p", "edge", "n_books", "decision", "reason"])
    return 0


def latest_signals(storage: Storage, d: date, now: datetime) -> pd.DataFrame:
    ev = events_on(storage, d)
    if ev.empty:
        return pd.DataFrame()
    df = storage.query("""
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY event_id, player_id ORDER BY ts DESC) rn
          FROM signals WHERE ts <= ?) WHERE rn = 1""", [now])
    return df[df.event_id.isin(set(ev.event_id))]


def cmd_watchlist(args, storage, now_fn) -> int:
    now = now_fn()
    d = args.date or et_date(now)
    sig = latest_signals(storage, d, now)
    if sig.empty:
        print("No signals logged for this date yet.")
        return 1
    venues = pd.concat([venue_quotes(storage, e, before=now) for e in sig.event_id.unique()],
                       ignore_index=True)
    wl = watchlist_rows(sig, venues)
    lines = [f"# Prediction-market watchlist: {d}", "",
             f"Built {now:%Y-%m-%d %H:%M} UTC from the latest logged signals. "
             f"Max price leaves {100 * config.EDGE_THRESHOLD:.0f}pp of edge after the taker fee "
             f"({', '.join(f'{v} {r:g}' for v, r in sorted(config.VENUE_FEE_RATE.items()))} x P x (1-P); "
             "verify fees per venue). Research only.", ""]
    if wl.empty:
        print("No paper signals: nothing to wait for on this slate.")
        lines.append("No paper signals on this slate.")
    else:
        cols = ["player", "team", "book_side", "contract", "model_cents", "market_cents", "edge_pp"] + \
               [f"max_{v}" for v in sorted(config.TARGET_VENUES)] + ["posted"]
        _print_table(wl, cols)
        lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |"
                  for r in wl[cols].itertuples(index=False)]
        lines += ["", "## Ladders (fair YES price in cents for 'N+ points')", ""]
        for r in sig[sig.decision == "paper"].itertuples():
            lad = ladder(r.model_mean, r.consensus_mean, r.line)
            lines += [f"**{r.player_name}** ({r.team}), book line {r.line:g}, model {r.model_mean:.1f} "
                      f"vs market {r.consensus_mean:.1f}", "",
                      "| " + " | ".join(lad.columns) + " |", "|" + "---|" * len(lad.columns)]
            lines += ["| " + " | ".join(str(v) for v in x) + " |" for x in lad.itertuples(index=False)]
            lines.append("")
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORTS_DIR / f"watchlist_{d}.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}")
    return 0


def cmd_grade(args, storage, now_fn) -> int:
    now = now_fn()
    d = args.date
    if not args.offline:
        objects, n, messages = fetch_results(_client(storage, now_fn), storage, d, now)
        for m in messages:
            print(f"note: {m}")
        print(f"Stored {n} result row(s) ({objects} API objects)")
    df = graded_signals(storage, d, d)
    s_all, s_paper = summarize(df), summarize(df[df.decision == "paper"]) if not df.empty else {}
    print(f"Grade {d}:")
    for label, s in (("all", s_all), ("paper", s_paper)):
        print(f"  {label:5s}: " + ", ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                                          for k, v in s.items()))
    if not df.empty:
        _print_table(df, ["player_name", "timing", "side", "line", "model_p", "consensus_p", "edge",
                          "decision", "actual_points", "outcome", "close_consensus_line", "clv_p", "clv_line"])
        print("Calibration:")
        _print_table(calibration(df))
    return 0


def cmd_fit(args, storage, now_fn) -> int:
    from .fit import add_spacing_columns, describe, fit_efficiency
    from .spacing import load_team_shooting
    df = pd.read_csv(args.input)
    if "spacing_old" not in df.columns:
        if not (args.teams_old and args.teams_new):
            print("Input has no spacing_old/spacing_new: pass --teams-old and --teams-new team shooting tables")
            return 2
        df = add_spacing_columns(df, load_team_shooting(Path(args.teams_old)), load_team_shooting(Path(args.teams_new)))
    print(describe(fit_efficiency(df, min_minutes=args.min_minutes)))
    return 0


def cmd_catalog(args, storage, now_fn) -> int:
    """Rebuild the league-wide role-change catalog (no API calls)."""
    from . import catalog as cat
    splits = cat.load_league_splits()
    lines = cat.combine_lines(splits)
    moves = cat._load_csv(config.DATA_DIR / "offseason_moves_2026.csv", ["player", "from_team", "to_team"])
    overrides = cat._load_csv(config.DATA_DIR / "roster_overrides_2026_27.csv", ["player", "team"])
    resolved, conflicts = cat.resolve_rosters(lines, cat.load_sgo_rosters(), moves, overrides)
    conflicts = conflicts[~conflicts.team_2026_27.isin(config.CATALOG_EXCLUDED_TEAMS)
                          & ~conflicts.sgo_team.isin(config.CATALOG_EXCLUDED_TEAMS)]
    players = cat.players_table(resolved)
    players = players[~players.team_2026_27.isin(config.CATALOG_EXCLUDED_TEAMS)]
    players.to_csv(config.PLAYERS_CSV, index=False)
    catalog, teams = cat.build_catalog(players, resolved, splits=splits, moves=moves, overrides=overrides,
                                       write_auto=True)
    out = config.DATA_DIR / "catalog"
    out.mkdir(parents=True, exist_ok=True)
    catalog.to_csv(out / "players.csv", index=False)
    teams.to_csv(out / "teams.csv", index=False)
    conflicts.to_csv(out / "roster_conflicts.csv", index=False)
    # One folder per usage tier, one CSV per situation: data/catalog/usage_tiers/high/vacuum.csv ...
    for tier_name, part in catalog.groupby("tier"):
        folder = out / "usage_tiers" / tier_name
        folder.mkdir(parents=True, exist_ok=True)
        for sit, rows in part.groupby("situation"):
            rows.sort_values("usg_change", key=lambda s: -s.abs()).to_csv(folder / f"{sit}.csv", index=False)
    docs = config.REPO_DIR / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "CATALOG.md").write_text(cat.catalog_markdown(catalog, teams, conflicts, resolved))
    counts = cat.summary(catalog)
    print(f"{len(players)} players placed on {players.team_2026_27.nunique()} teams "
          f"({(resolved.roster_source == 'assumed').sum()} assumed on last season's team, "
          f"{len(conflicts)} source conflicts in data/catalog/roster_conflicts.csv)")
    print(counts.to_string())
    _print_table(teams.sort_values("offseason_usage_effect_pct"),
                 ["team", "scenario_source", "offseason_usage_effect_pct", "usage_min_out", "usage_min_in",
                  "top_departures", "top_arrivals"])
    print(f"Wrote {config.PLAYERS_CSV}, {out}/players.csv, teams.csv, roster_conflicts.csv, "
          "scenarios/auto/, docs/CATALOG.md")
    return 0


def _kalshi_markets(storage, now) -> pd.DataFrame | None:
    """Open Kalshi player-points markets (public, read-only), stored as venue quotes."""
    from . import kalshi
    try:
        df = kalshi.parse_markets(kalshi.fetch_open_markets())
    except Exception as exc:                       # network trouble never blocks the board
        print(f"Kalshi check skipped: {type(exc).__name__}")
        return None
    if len(df):
        storage.append("venue_quotes", df.drop(columns=["key", "volume"]).assign(ts=now, venue="kalshi"))
    print(f"Kalshi: {len(df)} open player-points markets across {df.event_ticker.nunique() if len(df) else 0} games")
    return df


def cmd_kalshi(args, storage, now_fn) -> int:
    """Read-only check of Kalshi's NBA player-points markets against the catalog."""
    from .board import build_board
    df = _kalshi_markets(storage, now_fn())
    if df is None or df.empty:
        print("No open Kalshi player-points markets yet. The board prices them as soon as they list.")
        return 0
    catalog = pd.read_csv(config.DATA_DIR / "catalog" / "players.csv")
    board = build_board(catalog, storage, now_fn(), kalshi=df)
    listed = board[board.kalshi != ""]
    print(f"{len(listed)} catalog players have Kalshi ladders; "
          f"{listed.status.str.startswith('READY (Kalshi)').sum()} clear the 4pp bar after fees")
    _print_table(listed.sort_values("kalshi_roi", ascending=False, na_position="last"),
                 ["team", "player", "situation", "proj", "kalshi", "status"])
    return 0


def cmd_venues(args, storage, now_fn) -> int:
    """Read-only scan of Polymarket and Kalshi player-points prices for a slate."""
    import requests
    from . import kalshi, polymarket
    from .venues import scan
    now = now_fn()
    d = args.date or et_date(now)
    session = requests.Session()

    def pm_fetch(away, home, day):
        try:
            ev = polymarket.find_game(away, home, day, session)
            return None if ev is None else polymarket.points_markets(ev)
        except Exception as exc:
            print(f"Polymarket {away} @ {home} skipped: {type(exc).__name__}")
            return None

    def book_fetch(token):
        try:
            return polymarket.asks(token, session)
        except Exception:
            return []

    kq = _kalshi_markets(storage, now)
    df = scan(storage, d, now, polymarket_fetch=pm_fetch, kalshi_quotes=kq, book_fetch=book_fetch)
    if df.empty:
        print(f"No prediction-market player-points prices found for {d} (run `snapshot --date {d}` first "
              "so the slate and consensus are stored).")
        return 0
    stored = df.assign(ts=now)
    print(f"{len(df)} priced outcomes on {df.game.nunique()} game(s) across {df.venue.nunique()} venue(s)")
    _print_table(df.sort_values(["verdict", "edge_vs_market_pp"], ascending=[True, False]),
                 ["game", "venue", "player", "contract", "ask_cents", "fee_cents", "fair_market", "fair_model",
                  "edge_vs_market_pp", "edge_vs_model_pp", "roi", "size_at_edge", "verdict"])
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.REPORTS_DIR / f"venues_{d}.csv"
    stored.to_csv(out, index=False)
    print(f"Wrote {out}")
    return 0


def cmd_board(args, storage, now_fn) -> int:
    """The waiting list: catalog situations plus whatever markets have posted."""
    from . import catalog as cat
    from .board import board_markdown, build_board
    path = config.DATA_DIR / "catalog" / "players.csv"
    if not path.exists():
        print("No catalog yet: run `catalog` first.")
        return 1
    catalog = pd.read_csv(path)
    now = now_fn()
    kalshi_df = None if args.no_kalshi else _kalshi_markets(storage, now)
    board = build_board(catalog, storage, now, kalshi=kalshi_df)
    md = board_markdown(board, cat.summary(catalog), now)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.REPORTS_DIR / f"board_{now:%Y-%m-%d}.md"
    out.write_text(md)
    if args.docs:
        (config.REPO_DIR / "docs").mkdir(exist_ok=True)
        (config.REPO_DIR / "docs" / "BOARD.md").write_text(md)
    ready = board.status.str.startswith("READY").sum() if not board.empty else 0
    waiting = board.status.eq("waiting for a line").sum() if not board.empty else 0
    print(f"{len(board)} situations on the board: {waiting} waiting for a line, {ready} ready")
    _print_table(board.head(args.top), ["tier", "situation", "team", "player", "proj", "ppg_2025_26",
                                        "usg_change", "fair_ladder", "status"])
    print(f"Wrote {out}")
    return 0


def cmd_report(args, storage, now_fn) -> int:
    today = et_date(now_fn())
    end = args.end or today - timedelta(days=1)
    start = args.start or end - timedelta(days=6)
    path = write_report(storage, start, end)
    print(f"Wrote {path}")
    return 0


COMMANDS = {"usage": cmd_usage, "books": cmd_books, "snapshot": cmd_snapshot, "project": cmd_project,
            "signals": cmd_signals, "watchlist": cmd_watchlist, "grade": cmd_grade, "report": cmd_report,
            "fit": cmd_fit, "catalog": cmd_catalog, "board": cmd_board, "kalshi": cmd_kalshi,
            "venues": cmd_venues}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="nba_cold_start.cli", description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=str(config.DB_PATH), help="DuckDB path (default data/edge_lab.duckdb)")
    ap.add_argument("--now", help="Simulated UTC time (ISO). Only allowed with a non-default --db.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("usage", help="Show API object usage")
    p.add_argument("--measure", action="store_true", help="Call twice to measure the usage call's own cost")
    sub.add_parser("books", help="Discover which allowlisted books this key returns (1 object)")
    p = sub.add_parser("snapshot", help="Snapshot player-points odds")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--date", type=_parse_date, help="ET slate date (default today)")
    g.add_argument("--due", action="store_true", help="Cron mode: only events at a new checkpoint")
    g.add_argument("--from-file", help="Ingest a saved /events response (no API call)")
    p.add_argument("--with-signals", action="store_true",
                   help="With --due: log signals for events that just hit t-60m / t-15m")
    p = sub.add_parser("project", help="Log projections for modeled teams on a date")
    p.add_argument("--date", type=_parse_date)
    p.add_argument("--scenario", action="append", help="TEAM=scenario, e.g. TOR=kawhi_out")
    p = sub.add_parser("signals", help="Log signals vs the latest consensus")
    p.add_argument("--date", type=_parse_date)
    p.add_argument("--timing", choices=list(config.SIGNAL_TIMINGS) + ["early", "adhoc"])
    p = sub.add_parser("watchlist", help="Prediction-market max prices for paper signals")
    p.add_argument("--date", type=_parse_date)
    p = sub.add_parser("grade", help="Fetch results and grade a date")
    p.add_argument("--date", type=_parse_date, required=True)
    p.add_argument("--offline", action="store_true", help="Use stored results only")
    sub.add_parser("catalog", help="Rebuild the league-wide role-change catalog (no API calls)")
    p = sub.add_parser("board", help="Pre-market board: situations waiting on prediction markets")
    p.add_argument("--top", type=int, default=25, help="Rows to print (the file has them all)")
    p.add_argument("--docs", action="store_true", help="Also refresh the committed docs/BOARD.md snapshot")
    p.add_argument("--no-kalshi", action="store_true", help="Skip the read-only Kalshi market check")
    sub.add_parser("kalshi", help="Read-only: Kalshi NBA player-points prices vs our fair values")
    p = sub.add_parser("venues", help="Read-only: Polymarket + Kalshi player-points prices vs consensus and model")
    p.add_argument("--date", type=_parse_date)
    p = sub.add_parser("fit", help="Fit eff_per_usg_point and spacing_coef from team-changers")
    p.add_argument("--input", required=True, help="CSV of player-season pairs (see nba_cold_start/fit.py)")
    p.add_argument("--teams-old", help="Team shooting table for the earlier season")
    p.add_argument("--teams-new", help="Team shooting table for the later season")
    p.add_argument("--min-minutes", type=float, default=500.0)
    p = sub.add_parser("report", help="Write the weekly markdown report")
    p.add_argument("--start", type=_parse_date)
    p.add_argument("--end", type=_parse_date)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.now:
        if Path(args.db).resolve() == config.DEFAULT_DB_PATH.resolve():
            print("--now is only allowed with a separate --db (the real log is never back-dated)")
            return 2
        fixed = to_naive_utc(args.now)
        now_fn = lambda: fixed  # noqa: E731
    else:
        now_fn = utcnow
    with Storage(args.db) as storage:
        try:
            return COMMANDS[args.command](args, storage, now_fn)
        except SGOError as exc:
            print(f"API error: {exc}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
