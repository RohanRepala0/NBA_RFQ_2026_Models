"""Command line: usage | books | snapshot | project | signals | watchlist | grade | report | fit |
catalog | board | kalshi | venues | tickets | fill | journal | roster | boxscores | evaluate | shifts |
dashboard | history | backtest.

    python -m cold_start_usage.cli snapshot --date 2026-10-21
    python -m cold_start_usage.cli project --date 2026-10-21 --scenario MIA=full_strength --scenario TOR=kawhi_out
    python -m cold_start_usage.cli signals --date 2026-10-21
    python -m cold_start_usage.cli watchlist --date 2026-10-21
    python -m cold_start_usage.cli grade --date 2026-10-21
    python -m cold_start_usage.cli journal --date 2026-10-21

Research only: `tickets` suggests a limit price and size to enter by hand; nothing here
places or routes an order anywhere.
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
from .consensus import consensus_by_player
from .grade import calibration, graded_signals, summarize
from .ingest import player_points_side
from .pipeline import (events_on, events_without_projections, fetch_results, ledger_for, run_projections,
                       run_signals, snapshot_due, snapshot_from_file, snapshot_slate, venue_due_plan)
from .report import write_report
from .schedule import et_date, iso_z
from .sgo_client import SGOClient, SGOError
from .signals import make_signal
from .storage import Storage, to_naive_utc, utcnow

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


def _snapshot_due(args, storage, now_fn, now) -> int:
    """Cron tick. The SportsGameOdds step and the venue step are independent: a budget
    stop or a missing key never blocks the free venue reads, and the other way round."""
    out = {"due": {}}
    try:
        out = snapshot_due(_client(storage, now_fn), storage, now)
        if out["slate"]:
            print(f"Slate {et_date(now)}: {out['slate']['events']} event(s) stored")
        print("Due: " + (", ".join(f"{e}={t}" for e, t in sorted(out["due"].items())) or "nothing due"))
        usage = out.get("usage_before") or (out["slate"] or {}).get("usage_before")
        if usage is None:
            print(f"No API call this run. Local ledger: {storage.objects_used_this_month()} objects this month")
        else:
            print(_budget_line(storage, usage, out["objects"]))
    except SGOError as exc:
        print(f"SportsGameOdds step skipped: {exc}")
    venue_plan = venue_due_plan(storage, now) if args.with_venues else {}
    if args.with_projections:
        due_ids = set(out["due"]) | set(venue_plan)
        missing = events_without_projections(storage, due_ids)
        done = 0
        for eid in sorted(missing):
            try:
                run_projections(storage, et_date(now), now, {}, event_ids={eid})
                done += 1
            except Exception as exc:                 # one team's bad scenario file never stops the tick
                print(f"Auto-projection skipped for {eid}: {type(exc).__name__}: {exc}")
        if done:
            print(f"Auto-projected {done} game(s) (missing, an older model version, or a stat short; each team "
                  "keeps its latest scenario, else full_strength); `project --scenario` later replaces a team's run")
    if args.with_signals:
        for tag in config.SIGNAL_TIMINGS:
            ids = {e for e, t in out["due"].items() if t == tag}
            if ids:
                df, msgs = run_signals(storage, et_date(now), now, timing=tag, event_ids=ids)
                for m in msgs:
                    print(f"note: {m}")
                n_lean = int((df.decision == "paper").sum()) if not df.empty else 0
                print(f"Sportsbook signals at {tag}: {len(df)} logged ({n_lean} leans)"
                      + ("" if len(df) else " - no projections logged for these events yet"))
    for tag in sorted(set(venue_plan.values()), key=lambda t: -config.VENUE_OFFSETS_MIN[t]):
        ids = {e for e, t in venue_plan.items() if t == tag}
        try:
            _venue_scan(storage, now, tag=tag, event_ids=ids, simulated=args.now is not None)
        except Exception as exc:
            print(f"Venue step at {tag} failed: {type(exc).__name__}: {exc}")
    return 0


def cmd_snapshot(args, storage, now_fn) -> int:
    now = now_fn()
    if args.from_file:
        out = snapshot_from_file(storage, json.loads(Path(args.from_file).read_text()), now)
        print(f"Loaded {out['events']} event(s) from file: {out['odds_snapshots']} quotes, "
              f"tags {sorted(set(out['tags'].values()))} (0 API objects)")
        return 0
    if args.due:
        return _snapshot_due(args, storage, now_fn, now)
    client = _client(storage, now_fn)
    d = args.date or et_date(now)
    out = snapshot_slate(client, storage, d, now)
    print(f"Stored {out['events']} event(s), {out['odds_snapshots']} player-prop quotes "
          f"({', '.join(config.STATS)}), {out['event_players']} roster rows for {d}")
    for n in out["notices"]:
        print(f"API notice: {n}")
    targets = storage.query("""SELECT book, count(DISTINCT player_id) AS players FROM odds_snapshots
                               WHERE ts = ? AND book_role = 'target' AND coalesce(stat, 'points') = 'points'
                               GROUP BY book""", [now])
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
    table, messages = run_projections(storage, d, now, _scenario_choice(args.scenario), source=args.source)
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
    print(f"Logged projections at {now:%Y-%m-%d %H:%M} UTC (model {config.current_model_version(args.source)}; points, "
          "rebounds and assists; the sportsbook preview is points)")
    _print_table(table, ["team", "scenario", "player", "status", "min", "usg", "usg_proj", "ppg_25_26",
                         "proj", "sd", "reb", "ast", "spc_old", "spc_new", "cons_line", "cons_mean", "side", "edge",
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
    """Sportsbook leans (model vs books at the books' line) next to what the venues list.
    A lean is never a recommendation: only `tickets` are actionable."""
    from .venues import latest_venue_signals
    now = now_fn()
    d = args.date or et_date(now)
    sig = latest_signals(storage, d, now)
    if sig.empty:
        print("No signals logged for this date yet.")
        return 1
    leans = sig[sig.decision == "paper"]
    vs = latest_venue_signals(storage, now)
    lines = [f"# Leans vs the books: {d}", "",
             "Model vs the sportsbook consensus at the books' own line. Rohan can't trade at the books, so a",
             "lean only says where to look; the venue columns show what Kalshi / Polymarket US list for the",
             "player and the logged decision. Only `tickets` are actionable. Research only.", ""]
    rows = []
    if len(vs):
        vs = vs[vs.stat.fillna("points") == "points"]                     # the leans are points
    for s in leans.itertuples():
        mine = vs[vs.player_id == s.player_id] if len(vs) else vs
        listed = "; ".join(f"{r.venue} {r.contract} {100 * r.ask:.0f}c: {r.decision}"
                           for r in mine.sort_values("ev_blend", ascending=False).head(3).itertuples()
                           if isinstance(r.contract, str) and r.ask is not None and not pd.isna(r.ask))
        rows.append({"player": s.player_name, "team": s.team, "lean": f"{s.side} {s.line:g}",
                     "edge_pp": round(100 * s.edge, 1), "proj": round(s.model_mean, 1),
                     "books": round(s.consensus_mean, 1), "venues": listed or "no venue listing"})
    wl = pd.DataFrame(rows)
    if wl.empty:
        print("No leans on this slate.")
        lines.append("No leans on this slate.")
    else:
        _print_table(wl)
        cols = list(wl.columns)
        lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in wl.itertuples(index=False)]
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORTS_DIR / f"watchlist_{d}.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}")
    return 0


def cmd_grade(args, storage, now_fn) -> int:
    now = now_fn()
    d = args.date
    if not args.offline and not args.venues_only:
        objects, n, messages = fetch_results(_client(storage, now_fn), storage, d, now)
        for m in messages:
            print(f"note: {m}")
        print(f"Stored {n} result row(s) ({objects} API objects)")
    if not args.venues_only:
        df = graded_signals(storage, d, d)
        s_all, s_lean = summarize(df), summarize(df[df.decision == "paper"]) if not df.empty else {}
        print(f"Model vs books {d} (sportsbook line):")
        for label, s in (("all", s_all), ("leans", s_lean)):
            print(f"  {label:5s}: " + ", ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                                              for k, v in s.items()))
        if not df.empty:
            _print_table(df, ["player_name", "timing", "side", "line", "model_p", "consensus_p", "edge",
                              "decision", "actual_points", "outcome", "close_consensus_line", "clv_p", "clv_line"])
            print("Calibration:")
            _print_table(calibration(df))
    _grade_venues(storage, d, now, offline=args.offline)
    from .grade import shadow_graded, shadow_summary
    sh = shadow_summary(shadow_graded(storage, d, d))
    if not sh.empty:
        print(f"Shadow stats {d} (graded from box scores; never tickets): Brier of our price, the books', the venue ask;"
              " would-be tickets at the ask:")
        _print_table(sh.round(3))
    return 0


def _grade_venues(storage, d, now, offline: bool = False) -> None:
    """Kalshi / Polymarket US settlements (free public reads), then P&L at the venue's price."""
    from .grade import fetch_venue_settlements, fills_graded, venue_graded, venue_summary, venue_summary_by_stat
    if not offline:
        import requests

        from . import kalshi, polymarket_us
        reader, session = kalshi.KalshiReader(), requests.Session()
        n = fetch_venue_settlements(storage, d, d, now, kalshi_market=reader.market,
                                    pm_us_settlement=lambda t: polymarket_us.settlement(t, session))
        print(f"Stored {n} venue settlement(s)")
    vg = venue_graded(storage, d, d)
    fmt = lambda summ: ", ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"  # noqa: E731
                                 for k, v in summ.items())
    print(f"Venue contracts {d} (first actionable decision per player-game and stat, paper):")
    print("  all     : " + fmt(venue_summary(vg)))
    for stat, summ in venue_summary_by_stat(vg).items():
        print(f"  {stat:8s}: " + fmt(summ))
    if not vg.empty:
        _print_table(vg, ["game", "venue", "player", "stat", "contract", "ask", "cost", "p_blend", "ev_blend",
                          "result", "value", "pnl_per_contract", "close_mid", "clv_venue"])
    fills = fills_graded(storage)
    if not fills.empty:
        from .journal import FILL_KINDS, fills_journal
        fj = fills_journal(storage)
        cur = fj[fj.status == "current"]
        kinds = "; ".join(f"{k} {int((cur.kind == k).sum())}: ${cur[cur.kind == k].pnl_usd.sum():.2f}"
                          for k in FILL_KINDS if (cur.kind == k).any())
        print(f"Your fills: {len(fills)}, settled {int(fills.pnl.notna().sum())}, P&L ${fills.pnl.sum():.2f} ({kinds})")


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


def _kalshi_markets(now) -> pd.DataFrame | None:
    """Open Kalshi player-points markets (public, read-only), parsed; None if unreachable."""
    from . import kalshi
    try:
        df = kalshi.parse_markets(kalshi.fetch_open_markets())
    except Exception as exc:                       # network trouble never blocks the board
        print(f"Kalshi check skipped: {type(exc).__name__}")
        return None
    bad = int(df.parse_error.notna().sum()) if len(df) else 0
    print(f"Kalshi: {len(df)} open player-points markets across {df.event_ticker.nunique() if len(df) else 0} games"
          + (f" ({bad} unparsed: check the format)" if bad else ""))
    return df


def _venue_scan(storage, now, d=None, tag="adhoc", event_ids=None, quiet=False, simulated=False) -> pd.DataFrame:
    """Read the venues for un-tipped games on the stored slate, decide, and log (free reads)."""
    from .venues import live_fetchers, scan
    if simulated:
        print("Venue reads skipped: live prices can't be logged at a simulated --now time")
        return pd.DataFrame()
    f = live_fetchers()
    df = scan(storage, d or et_date(now), now, f, tag=tag, event_ids=event_ids, bankroll=config.bankroll_usd())
    for e in f.errors:
        print(f"venue note: {e}")
    if not quiet:
        n_act = int((df.decision == "actionable").sum()) if len(df) else 0
        print(f"Venues ({tag}): {len(df)} contract sides logged, {n_act} actionable")
    return df


def cmd_kalshi(args, storage, now_fn) -> int:
    """Read-only: Kalshi listings for catalog players, with our fair price next to each ask."""
    from .board import build_board
    df = _kalshi_markets(now_fn())
    if df is None or df.empty:
        print("No open Kalshi player-points markets yet. The board shows them as soon as they list.")
        return 0
    catalog = pd.read_csv(config.DATA_DIR / "catalog" / "players.csv")
    board = build_board(catalog, storage, now_fn(), kalshi=df)
    listed = board[board.kalshi != ""]
    print(f"{len(listed)} catalog players have Kalshi ladders (decisions come from `venues` / the cron scan)")
    _print_table(listed, ["team", "player", "situation", "proj", "kalshi", "status"])
    return 0


def cmd_venues(args, storage, now_fn) -> int:
    """Read Kalshi + Polymarket US (and the international book as a reference) for a slate,
    decide every contract side, and log it before tip."""
    now = now_fn()
    d = args.date or et_date(now)
    df = _venue_scan(storage, now, d, simulated=args.now is not None)
    if df.empty:
        print(f"No venue prices mapped for {d}: the slate must be stored first (the cron's daily slate fetch, "
              "or `snapshot --date`), and the venues must list the games.")
        return 0
    order = {"actionable": 0, "watch": 1, "abstain": 2, "reference": 3}
    show = df.assign(_o=df.decision.map(order)).sort_values(["_o", "ev_blend"], ascending=[True, False])
    _print_table(show.head(args.top), ["game", "venue", "player", "stat", "contract", "ask", "ask_size", "p_market",
                                       "p_blend", "ev_market", "ev_blend", "max_price", "size_at_edge",
                                       "contracts", "decision", "reason"])
    print(df.assign(stat=df.stat.fillna("-")).groupby(["venue", "stat", "decision"]).size().to_string())
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.REPORTS_DIR / f"venues_{d}_{now:%H%M}.csv"
    df.to_csv(out, index=False)
    print(f"Logged to venue_signals; export {out}")
    return 0


def cmd_board(args, storage, now_fn) -> int:
    """The waiting list: catalog situations plus whatever the venues have listed and decided."""
    from . import catalog as cat
    from .board import board_markdown, build_board
    path = config.DATA_DIR / "catalog" / "players.csv"
    if not path.exists():
        print("No catalog yet: run `catalog` first.")
        return 1
    catalog = pd.read_csv(path)
    now = now_fn()
    if not args.no_scan and not events_on(storage, et_date(now)).empty:
        _venue_scan(storage, now, simulated=args.now is not None)
    kalshi_df = None if args.no_kalshi else _kalshi_markets(now)
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
    print(f"{len(board)} situations on the board: {waiting} waiting for a line, {ready} READY on a venue")
    _print_table(board.head(args.top), ["tier", "situation", "team", "player", "proj", "ppg_2025_26",
                                        "usg_change", "fair_ladder", "status"])
    print(f"Wrote {out}")
    return 0


def cmd_tickets(args, storage, now_fn) -> int:
    """Order tickets to enter by hand: actionable decisions from a fresh venue read, pre-cancel-by."""
    from .venues import latest_venue_signals
    now = now_fn()
    d = args.date or et_date(now)
    if not args.no_scan and d == et_date(now) and not events_on(storage, d).empty:
        _venue_scan(storage, now, d, quiet=True, simulated=args.now is not None)
    vs = latest_venue_signals(storage, now)
    if len(vs):
        cancel_by = pd.to_datetime(vs.tip_ts) - pd.Timedelta(minutes=config.TICKET_CANCEL_BEFORE_TIP_MIN)
        vs = vs[(vs.tip_ts.map(et_date) == d) & (cancel_by > pd.Timestamp(now))]
    act = vs[vs.decision == "actionable"].sort_values("ev_blend", ascending=False) if len(vs) else vs
    lines = [f"# Tickets: {d}", "", "Enter by hand as limit orders. Limit = the max price that still leaves the edge "
             "after the venue fee (and never above what the books alone say it's worth); cancel anything "
             "unfilled by the cancel-by time. Log fills with `fill --signal-id ...`. Only decisions from a venue "
             f"read in the last {config.VENUE_SIGNAL_MAX_AGE_MIN} minutes are listed. Research only: nothing here "
             "places an order.", ""]
    if act.empty:
        print(f"No actionable venue contracts for {d} as of {now:%H:%M} UTC.")
        lines.append("Nothing actionable.")
    else:
        to_et = lambda x: pd.Timestamp(x).tz_localize("UTC").tz_convert(config.ET).strftime("%H:%M")  # noqa: E731
        t = act.assign(
            tip_et=act.tip_ts.map(to_et),
            cancel_by_et=(pd.to_datetime(act.tip_ts) - pd.Timedelta(minutes=config.TICKET_CANCEL_BEFORE_TIP_MIN)).map(to_et),
            limit_c=(100 * act.max_price).round(0), ask_c=(100 * act.ask).round(0),
            fair_c=(100 * act.p_blend).round(1), market_c=(100 * act.p_market).round(1),
            ev_pp=(100 * act.ev_blend).round(1),
            qty=act.contracts.where(act.contracts.notna(), act.size_at_edge))
        cols = ["game", "tip_et", "cancel_by_et", "venue", "ticker", "player", "stat", "contract", "ask_c",
                "limit_c", "qty", "fair_c", "market_c", "ev_pp", "stake_usd", "signal_id"]
        _print_table(t, cols)
        if t.stake_frac.isna().all():
            print(f"qty = contracts available at the edge; set {config.BANKROLL_ENV} (where the cron runs) for sized stakes.")
        lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in t[cols].itertuples(index=False)]
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORTS_DIR / f"tickets_{d}.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}")
    return 0


def cmd_fill(args, storage, now_fn) -> int:
    """Record a fill Rohan entered by hand on a venue. Append-only: a correction is a new row with
    --replaces <fill_id>, and grading then uses the correction only."""
    import hashlib
    now = now_fn()
    venue, ticker, side = args.venue, args.ticker, (args.side or "").upper() or None
    if args.signal_id:
        sig = storage.query("SELECT venue, ticker, side FROM venue_signals WHERE signal_id = ? LIMIT 1", [args.signal_id])
        if sig.empty:
            print(f"No logged signal {args.signal_id}")
            return 2
        venue, ticker, side = sig.iloc[0]
    if not (venue and ticker and side in ("YES", "NO")):
        print("Give --signal-id, or --venue, --ticker and --side YES|NO")
        return 2
    if not 0 < args.price < 1:
        print(f"--price is in dollars between 0 and 1 (e.g. 0.41 for 41c), got {args.price}")
        return 2
    if args.contracts <= 0:
        print("--contracts must be positive")
        return 2
    known = storage.query("SELECT count(*) AS n FROM venue_snapshots WHERE venue = ? AND ticker = ?", [venue, ticker])
    if int(known.n.iloc[0]) == 0:
        print(f"{venue} {ticker} was never read by the venue scan: check the ticker (nothing logged)")
        return 2
    if args.replaces:
        prev = storage.query("SELECT count(*) AS n FROM tickets WHERE fill_id = ?", [args.replaces])
        if int(prev.n.iloc[0]) == 0:
            print(f"No fill {args.replaces} to replace")
            return 2
    note = args.note
    if args.paper and not (note or "").strip().lower().startswith("paper"):
        note = f"paper: {note}" if note else "paper"
    from .fees import fee_total
    fees = args.fees if args.fees is not None else fee_total(venue, args.contracts, args.price)
    filled_at = to_naive_utc(args.filled_at) if args.filled_at else now
    fill_id = hashlib.blake2s(f"{now.isoformat()}|{venue}|{ticker}|{side}|{args.contracts}|{args.price}".encode(),
                              digest_size=6).hexdigest()
    storage.append("tickets", [{"ts": now, "filled_at": filled_at, "venue": venue, "ticker": ticker, "side": side,
                                "contracts": args.contracts, "price": args.price, "fees": fees,
                                "signal_id": args.signal_id, "note": note, "fill_id": fill_id,
                                "replaces": args.replaces}])
    print(f"Logged fill {fill_id}: {venue} {ticker} {side} {args.contracts:g} @ {100 * args.price:.0f}c, fees ${fees:.2f}"
          + (" (paper)" if args.paper else "") + (f" (replaces {args.replaces})" if args.replaces else ""))
    return 0


def cmd_journal(args, storage, now_fn) -> int:
    """Rebuild the committed bet journal (bets/) from the log. Reads only; no API calls."""
    from .journal import write_journal
    out = Path(args.out) if args.out else config.BETS_DIR
    res = write_journal(storage, out, None if args.all or not args.date else [args.date])
    for d in res["skipped"]:
        print(f"No venue decisions or fills logged for {d}: no day folder written")
    days = ", ".join(map(str, res["days"])) or "none"
    print(f"Journal in {res['out']}: {res['tickets']} ticket(s) ({res['pending']} pending), {res['fills']} fill(s); "
          f"days: {days}; {len(res['written'])} file(s) changed")
    if res["pending"]:
        print("Pending tickets settle via `grade --date YYYY-MM-DD` (venue settlements); then rerun journal.")
    return 0


def cmd_report(args, storage, now_fn) -> int:
    today = et_date(now_fn())
    end = args.end or today - timedelta(days=1)
    start = args.start or end - timedelta(days=6)
    path = write_report(storage, start, end)
    print(f"Wrote {path}")
    return 0


def cmd_history(args, storage, now_fn) -> int:
    """Download Kalshi's public archive of settled player-prop markets for backtesting."""
    from .kalshi_history import HistoryStore, download
    store = HistoryStore(args.history_db)
    try:
        out = download(args.series, store=store, limit=args.limit, refresh_markets=not args.no_refresh)
    finally:
        store.close()
    print(f"{out['markets']} archive markets; {out['fetched_requests']} candle requests this run")
    return 0


def cmd_backtest(args, storage, now_fn) -> int:
    """Walk-forward backtests of every strategy on Kalshi's 2025-26 archive (read-only)."""
    from .backtest import Tape, monthly_folds, report, walk_forward
    from .strategies import default_suite
    path = Path(args.history_db) if args.history_db else None
    tape = Tape(path)
    if tape.markets.empty:
        print("No archive yet: run `history` first.")
        return 1
    folds = monthly_folds(tape.markets.game_date)
    if not args.reveal_holdout:                       # the holdout stays sealed until strategies are frozen
        folds = [f for f in folds if not f.holdout]
    print(f"{len(tape.markets):,} markets, {tape.markets.game.nunique():,} games; folds: "
          + ", ".join(f.name for f in folds))
    results = {}
    for st in default_suite():
        if args.only and not any(k.lower() in st.name.lower() for k in args.only):
            continue
        bets = walk_forward(tape, st, folds)
        bets.attrs["executable_by_hand"] = st.executable_by_hand
        results[st.name] = bets
        print(f"  {st.name}: {int(bets.filled.sum()) if len(bets) else 0} fills")
    md = report(results, tape)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.REPORTS_DIR / "backtest.md"
    out.write_text(md)
    nonempty = [b for b in results.values() if len(b)]
    if nonempty:
        pd.concat(nonempty, ignore_index=True).to_csv(config.REPORTS_DIR / "backtest_bets.csv", index=False)
    if args.docs:
        (config.REPO_DIR / "docs" / "BACKTEST.md").write_text(md)
    print(md)
    return 0


def cmd_roster(args, storage, now_fn) -> int:
    """Check each un-tipped team's minutes against its ESPN roster page (one public read per team);
    --apply writes a rotation without the missing players and re-projects with it."""
    import time

    from . import rosters
    from .pipeline import latest_scenarios
    from .usage_model import modeled_teams
    now = now_fn()
    d = args.date or et_date(now)
    ev = events_on(storage, d)
    ev = ev[pd.to_datetime(ev.starts_at) > pd.Timestamp(now)] if len(ev) else ev
    if ev.empty:
        print(f"No un-tipped games stored for {d}: run `snapshot --date {d}` first.")
        return 1
    modeled, teams = set(modeled_teams()), {}
    for e in ev.itertuples():
        used = latest_scenarios(storage, e.event_id, now)
        for team in (e.away_abbr, e.home_abbr):
            if team in modeled:
                teams[team] = used.get(team, "full_strength")
    found, off, notes = rosters.check_teams(teams, fetch=rosters.fetch_roster_page,
                                            save_dir=config.DATA_DIR / "rosters" / d.isoformat(),
                                            sleep=time.sleep)
    for n in notes:
        print(f"note: {n}")
    if off.empty:
        print(f"All {len(found)} rotations checked match their ESPN rosters ({d}).")
        return 0
    print(f"In the minutes but not on the team's ESPN roster ({d}):")
    _print_table(off, ["team", "scenario", "player", "proj_mpg"])
    if not args.apply:
        print("Run with --apply to write rotations without them and re-project.")
        return 0
    choice = {}
    for team, grp in off.groupby("team"):
        base = grp.scenario.iloc[0]
        try:
            rows = rosters.scenario_without(team, base, f"{base}_roster", grp.player.tolist(), roster=found[team])
        except ValueError as exc:
            print(f"note: {exc}")
            continue
        choice[team] = f"{base}_roster"
        print(f"{team}: wrote {base}_roster to scenarios/{team}.csv: "
              + ", ".join(f"{r.player} {r.proj_mpg:g}" for r in rows.itertuples()))
    if choice:
        table, messages = run_projections(storage, d, now, choice)
        for m in messages:
            print(f"note: {m}")
        print(f"Re-projected {', '.join(sorted(choice))} ({len(table)} rows). The minutes are mechanical: review "
              "them, then commit the scenario files.")
    return 0


def cmd_boxscores(args, storage, now_fn) -> int:
    """Box scores stored per date; --from-raw first backfills them from saved results files."""
    from .boxscores import backfill_from_raw, coverage, fetch_box_scores
    if args.date:
        if args.date >= et_date(now_fn()):
            print(f"{args.date} isn't over yet: fetch a past date (today's games come with tomorrow's `grade`)")
            return 1
        c = fetch_box_scores(_client(storage, now_fn), storage, args.date, now_fn())
        print(f"{args.date}: {c['events']} game(s) returned, {c['final']} final; stored {c['games']} game(s), "
              f"{c['players']} player row(s) ({c['objects']} API objects)")
        if c["pending_statuses"]:
            print(f"note: {c['events'] - c['final']} game(s) not finalized by SportsGameOdds yet "
                  f"(status flags: {', '.join(c['pending_statuses'])}); saved as boxscores_pending_{args.date}, retry later")
    if args.from_raw:
        c = backfill_from_raw(storage, now_fn(), Path(args.dir) if args.dir else None)
        print(f"Read {c['files']} results file(s): stored {c['games']} game(s), {c['players']} player row(s); "
              f"{c['skipped']} game(s) already stored")
    cov = coverage(storage)
    if cov.empty:
        print("No box scores stored. Run `boxscores --from-raw`, or `grade` a date.")
        return 0
    _print_table(cov)
    return 0


def cmd_evaluate(args, storage, now_fn) -> int:
    """Walk-forward: season vs rolling projections vs the books' close, against box scores."""
    from .evaluation import by_date, markdown, walk_forward, windows
    df = walk_forward(storage, args.since, args.until)
    if df.empty:
        print("Nothing to evaluate: run `boxscores --from-raw` (or `grade`) first.")
        return 1
    parts, dates = windows(df), by_date(df)
    for label, summary in parts:
        print(f"== {label}")
        for name in ("accuracy", "minutes", "extra"):
            print(f"{name}:")
            _print_table(summary[name].round(3))
    print("points MAE by date:")
    _print_table(dates.round(3))
    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")
    if args.docs:
        path = config.REPO_DIR / "docs" / "MODEL_V2_EVAL.md"
        path.write_text(markdown(parts, dates.round(3), args.since, args.until))
        print(f"Wrote {path}")
    return 0


def cmd_shifts(args, storage, now_fn) -> int:
    """Role shifts: this season's usage, minutes and threes volume against last season's (no API calls)."""
    from .shifts import shifts
    from .usage_model import load_players
    df = shifts(storage, now_fn(), load_players())
    if df.empty:
        print("No box scores yet: run `boxscores --from-raw` or `grade` first.")
        return 1
    show = df[df.flagged] if not args.all else df
    print(f"{int(df.flagged.sum())} flagged of {len(df)} players (min {config.SHIFT_MIN_MINUTES:g} minutes; "
          "gap = this season's usage minus the rolling model's shrunk usage):")
    _print_table(show.head(args.top), ["player", "team", "team_2025_26", "games", "mpg", "mpg_prior", "usg", "usg_prior",
                                       "usg_model", "gap", "pts36", "pts36_prior", "fg3a36", "fg3a36_prior", "flags"])
    if args.json:
        Path(args.json).write_text(df.to_json(orient="records"))
        print(f"Wrote {args.json}")
    return 0


def cmd_persistence(args, storage, now_fn) -> int:
    """Fit the rolling model's shrinkage on 2025-26: first n games against the rest (no API calls)."""
    from . import persistence as P
    from .usage_model import load_players
    raw = Path(args.dir) if args.dir else config.RAW_DIR / "courtai" / "persist_2025_26"
    df, notes = P.study(raw, load_players())
    for n in notes:
        print("note:", n)
    if df.empty:
        print(f"No usable players under {raw}.")
        return 1
    print(f"{df.player.nunique()} players ({int(df.groupby('player').new_team.first().sum())} on a new team), "
          f"{len(df)} player-cuts")
    fit = P.fit(df, reps=args.reps)
    _print_table(fit)
    _print_table(pd.concat([P.fit_by_cut(df, s) for s in P.STUDY_STATS]))
    _print_table(P.team_scale(df))
    _print_table(pd.DataFrame([P.direction(df, n) for n in (3, 4, 5, 10)]))
    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")
    return 0


def cmd_dashboard(args, storage, now_fn) -> int:
    """Write the Prop Desk dashboard's row files (no API calls)."""
    from .dashboard import export
    counts = export(storage, Path(args.out), now_fn())
    print("Wrote " + ", ".join(f"{k} ({v} rows)" for k, v in counts.items()) + f" to {args.out}")
    return 0


COMMANDS = {"usage": cmd_usage, "books": cmd_books, "snapshot": cmd_snapshot, "project": cmd_project,
            "signals": cmd_signals, "watchlist": cmd_watchlist, "grade": cmd_grade, "report": cmd_report,
            "fit": cmd_fit, "catalog": cmd_catalog, "board": cmd_board, "kalshi": cmd_kalshi,
            "venues": cmd_venues, "history": cmd_history, "tickets": cmd_tickets, "fill": cmd_fill,
            "journal": cmd_journal, "roster": cmd_roster, "boxscores": cmd_boxscores,
            "evaluate": cmd_evaluate, "dashboard": cmd_dashboard, "shifts": cmd_shifts,
            "persistence": cmd_persistence,
            "backtest": cmd_backtest}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cold_start_usage.cli", description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=str(config.DB_PATH), help="DuckDB path (default data/edge_lab.duckdb)")
    ap.add_argument("--now", help="Simulated UTC time (ISO). Only allowed with a non-default --db.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("usage", help="Show API object usage")
    p.add_argument("--measure", action="store_true", help="Call twice to measure the usage call's own cost")
    sub.add_parser("books", help="Discover which allowlisted books this key returns (1 object)")
    p = sub.add_parser("snapshot", help="Snapshot player points, rebounds and assists odds")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--date", type=_parse_date, help="ET slate date (default today)")
    g.add_argument("--due", action="store_true", help="Cron mode: only events at a new checkpoint")
    g.add_argument("--from-file", help="Ingest a saved /events response (no API call)")
    p.add_argument("--with-signals", action="store_true",
                   help="With --due: log sportsbook signals for events that just hit t-60m / t-15m")
    p.add_argument("--with-venues", action="store_true",
                   help="With --due: read Kalshi / Polymarket US at t-6h, t-2h, t-60m, t-15m and t-5m, decide, log")
    p.add_argument("--with-projections", action="store_true",
                   help="With --due: auto-log projections for due games that have none current (missing, an "
                        "older model version, or a stat short), keeping each team's latest scenario")
    p = sub.add_parser("project", help="Log projections for modeled teams on a date")
    p.add_argument("--date", type=_parse_date)
    p.add_argument("--scenario", action="append", help="TEAM=scenario, e.g. TOR=kawhi_out")
    p.add_argument("--source", choices=["season", "rolling"],
                   help=f"Projection inputs (default config.PROJECTION_SOURCE, now {config.PROJECTION_SOURCE!r})")
    p = sub.add_parser("signals", help="Log signals vs the latest consensus")
    p.add_argument("--date", type=_parse_date)
    p.add_argument("--timing", choices=list(config.SIGNAL_TIMINGS) + ["early", "adhoc"])
    p = sub.add_parser("watchlist", help="Sportsbook leans next to what the venues list (not actionable)")
    p.add_argument("--date", type=_parse_date)
    p = sub.add_parser("grade", help="Fetch results and grade a date")
    p.add_argument("--date", type=_parse_date, required=True)
    p.add_argument("--offline", action="store_true", help="Use stored results and settlements only")
    p.add_argument("--venues-only", action="store_true",
                   help="Skip the metered SportsGameOdds results call; grade venue contracts only")
    sub.add_parser("catalog", help="Rebuild the league-wide role-change catalog (no API calls)")
    p = sub.add_parser("board", help="Pre-market board: situations waiting on prediction markets")
    p.add_argument("--top", type=int, default=25, help="Rows to print (the file has them all)")
    p.add_argument("--docs", action="store_true", help="Also refresh the committed docs/BOARD.md snapshot")
    p.add_argument("--no-kalshi", action="store_true", help="Skip the read-only Kalshi listings")
    p.add_argument("--no-scan", action="store_true", help="Don't read and log venue decisions first")
    sub.add_parser("kalshi", help="Read-only: Kalshi listings for catalog players vs our fair values")
    p = sub.add_parser("venues", help="Read Kalshi + Polymarket US for a slate, decide every contract, log it")
    p.add_argument("--date", type=_parse_date)
    p.add_argument("--top", type=int, default=30)
    p = sub.add_parser("tickets", help="Actionable venue contracts as limit-order tickets to enter by hand")
    p.add_argument("--date", type=_parse_date)
    p.add_argument("--no-scan", action="store_true", help="Don't read the venues first (list the last read only)")
    p = sub.add_parser("fill", help="Record a fill you entered by hand (append-only)")
    p.add_argument("--signal-id")
    p.add_argument("--venue", choices=list(config.ACTIONABLE_VENUES))
    p.add_argument("--ticker")
    p.add_argument("--side", choices=["YES", "NO", "yes", "no"])
    p.add_argument("--contracts", type=float, required=True)
    p.add_argument("--price", type=float, required=True, help="Average price in dollars, e.g. 0.61")
    p.add_argument("--fees", type=float, help="Fees paid in dollars (default: the venue formula)")
    p.add_argument("--filled-at", help="UTC time of the fill (default now)")
    p.add_argument("--note")
    p.add_argument("--paper", action="store_true",
                   help="A paper fill (no money): writes note 'paper' (combines with --note)")
    p.add_argument("--replaces", help="fill_id of an earlier fill this one corrects")
    p = sub.add_parser("journal", help="Rebuild the committed bet journal in bets/ (reads the log; no API calls)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--date", type=_parse_date, help="Rebuild one ET day's folder (ledger and fills are always full)")
    g.add_argument("--all", action="store_true", help="Rebuild every day with a venue decision or fill (the default)")
    p.add_argument("--out", help="Output folder (default: the repo's bets/)")
    p = sub.add_parser("roster", help="Check each team's minutes against its ESPN roster (one read per team)")
    p.add_argument("--date", type=_parse_date)
    p.add_argument("--apply", action="store_true",
                   help="Write a rotation without the missing players (TEAM.csv) and re-project with it")
    p = sub.add_parser("boxscores", help="Box scores per date; --from-raw backfills saved results (free), "
                                          "--date fetches a past night (1 object a game)")
    p.add_argument("--from-raw", action="store_true", help="Store box scores from every saved results file first")
    p.add_argument("--date", type=_parse_date, help="Fetch and store a past ET date's box scores (1 object a game)")
    p.add_argument("--dir", help="Raw folder (default data/raw)")
    p = sub.add_parser("evaluate", help="Walk-forward: season vs rolling projections vs the books (no API calls)")
    p.add_argument("--since", type=_parse_date, default=config.SEASON_OPENER,
                   help=f"First ET date (default the season opener, {config.SEASON_OPENER})")
    p.add_argument("--until", type=_parse_date, help="Last ET date (default: every graded date)")
    p.add_argument("--csv", help="Also write the per player-game rows here")
    p.add_argument("--docs", action="store_true", help="Also write docs/MODEL_V2_EVAL.md")
    p = sub.add_parser("shifts", help="Role shifts: this season's usage, minutes and 3PA vs last season (no API calls)")
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--all", action="store_true", help="Every player, not only the flagged ones")
    p.add_argument("--json", help="Also write every row here")
    p = sub.add_parser("persistence", help="Fit the rolling shrinkage on 2025-26 game logs copied from Court AI (no API calls)")
    p.add_argument("--dir", help="Folder of the copied text (default data/raw/courtai/persist_2025_26)")
    p.add_argument("--reps", type=int, default=200, help="Bootstrap resamples for the k band")
    p.add_argument("--csv", help="Also write the player-cut rows here")
    p = sub.add_parser("dashboard", help="Write the Prop Desk dashboard's row files (no API calls)")
    p.add_argument("--out", required=True, help="Folder for tickets.json, model_eval.json, minutes_eval.json")
    p = sub.add_parser("history", help="Download Kalshi's archive of settled player props (resumable, no key)")
    p.add_argument("--series", default="KXNBAPTS")
    p.add_argument("--limit", type=int, help="Markets to fetch this run (default: all remaining)")
    p.add_argument("--history-db", help="Research cache path (default data/history/kalshi_history.duckdb)")
    p.add_argument("--no-refresh", action="store_true", help="Reuse the stored market list")
    p = sub.add_parser("backtest", help="Walk-forward backtests on the Kalshi archive (run `history` first)")
    p.add_argument("--history-db", help="Research cache path (default data/history/kalshi_history.duckdb)")
    p.add_argument("--only", nargs="*", help="Run only strategies whose name contains one of these words")
    p.add_argument("--docs", action="store_true", help="Also write docs/BACKTEST.md")
    p.add_argument("--reveal-holdout", action="store_true",
                   help="Also score the holdout (April on). Do this once, after strategies and parameters are frozen")
    p = sub.add_parser("fit", help="Fit eff_per_usg_point and spacing_coef from team-changers")
    p.add_argument("--input", required=True, help="CSV of player-season pairs (see cold_start_usage/fit.py)")
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
    if args.command in ("history", "backtest"):     # the research cache: don't hold the decision log open
        return COMMANDS[args.command](args, None, now_fn)
    with Storage(args.db) as storage:
        try:
            return COMMANDS[args.command](args, storage, now_fn)
        except SGOError as exc:
            print(f"API error: {exc}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
