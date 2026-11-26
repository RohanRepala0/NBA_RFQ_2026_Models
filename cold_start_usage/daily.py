"""The daily job: one unattended pass over the whole pipeline, safe to repeat. GitHub Actions runs
`python -m cold_start_usage.cli daily` on a schedule (.github/workflows/nba-daily.yml,
docs/DAILY_JOB.md); a run with nothing due does nothing and spends nothing.

Each run, in order, only what's due:

1. Grade: past days (up to GRADE_LOOKBACK_DAYS back) with a stored slate and something still
   open: results and box scores (SportsGameOdds, 1 object a game), venue settlements (free
   public reads), then that day's journal.
2. Box scores for any of the last BACKFILL_DAYS dates with none stored (a fresh database, a
   missed night), so the rotations and the rolling model see recent games.
3. Today's slate once, then each game's due checkpoints (pipeline.snapshot_due).
4. Rotations once a day (autorotation: recent minutes, or a hand-built report_MMDD), and
   projections for every un-tipped game with the rolling model; again for each game at a
   checkpoint, so injury statuses from the latest snapshot apply.
5. Sportsbook signals at t-60m / t-15m, and the venue scan at each due venue checkpoint.
6. Today's journal, an alert for each new ticket and for each earlier ticket that no longer
   clears ("faded: cancel if unfilled"), and the morning's graded results.

Unattended, the job prices with the rolling model (config.DAILY_JOB_SOURCE): the season model
needs its minutes reviewed by hand every day, and the rolling model rebuilt them better out of
sample (docs/MODEL_V2_EVAL.md). A step that fails is reported and the others still run; the
exit code is 1 if any did. Research only: nothing here places an order.
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from . import autorotation, config, notify
from .features import history
from .journal import graded_tickets, write_journal
from .pipeline import (events_on, events_without_projections, fetch_results, events_needing_results,
                       run_projections, run_signals, snapshot_due, venue_due_plan)
from .schedule import et_date, et_day_bounds
from .sgo_client import BudgetExceeded, SGOError
from .storage import Storage

GRADE_LOOKBACK_DAYS = 3
GRADE_RETRY_HOURS = 3              # a day still open (a settlement or a result missing) is retried this often
BACKFILL_DAYS = 14
BOX_RETRY_HOURS = 20
STATE_VERSION = 1
STATE_KEYS = ("graded", "grade_tried", "rotations", "box_tried", "faded", "problems")


@dataclass
class Run:
    """What one run did, for the log and the alerts."""
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    new_tickets: pd.DataFrame = field(default_factory=pd.DataFrame)
    faded: list[str] = field(default_factory=list)
    graded: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)   # alerted once a day, not a failure (the budget stop)

    def say(self, msg: str) -> None:
        self.lines.append(msg)
        print(msg, flush=True)


# --- state between runs (cached with the database) -------------------------------------------
def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    state.setdefault("version", STATE_VERSION)
    for k in STATE_KEYS:
        state.setdefault(k, {})
    return state


def save_state(path: Path, state: dict, today: date) -> None:
    keep = (today - timedelta(days=BACKFILL_DAYS + GRADE_LOOKBACK_DAYS + 7)).isoformat()
    for k in STATE_KEYS:
        state[k] = {d: v for d, v in state.get(k, {}).items() if d >= keep}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


# --- steps ---------------------------------------------------------------------------------
def _step(run: Run, name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except BudgetExceeded as exc:           # expected near the month's end: venue reads and grading carry on
        run.notices.append(f"SportsGameOdds budget stop: {exc}")
        run.say(f"[{name}] SportsGameOdds budget stop: {exc}")
    except SGOError as exc:                 # a budget stop or a bad key: said plainly, the rest still runs
        run.problems.append(f"{name}: SportsGameOdds: {exc}")
        run.say(f"[{name}] SportsGameOdds: {exc}")
    except Exception as exc:
        run.problems.append(f"{name}: {type(exc).__name__}: {exc}")
        run.say(f"[{name}] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()


def _box_dates(storage: Storage) -> set[date]:
    df = storage.query("SELECT DISTINCT starts_at FROM box_scores")
    return {et_date(t) for t in df.starts_at} if len(df) else set()


def grade_day(storage: Storage, client, d: date, now: datetime, run: Run, settle=None) -> bool:
    """Results, box scores and venue settlements for `d`, then its journal. True when nothing
    is left open (every result stored, every ticket settled)."""
    if client is not None and events_needing_results(storage, d):
        objects, n, msgs = fetch_results(client, storage, d, now)
        run.say(f"{d}: stored {n} result rows ({objects} objects)")
    settle = settle or _live_settle
    n = settle(storage, d, now)
    res = write_journal(storage, config.BETS_DIR, [d])
    t = graded_tickets(storage)
    day = t[t.date_et == d] if len(t) else t
    done = day[day.outcome != "pending"] if len(day) else day
    complete = not events_needing_results(storage, d) and not (len(day) and (day.outcome == "pending").any())
    if len(day):
        pnl = float((done.contracts.fillna(0) * done.pnl_per_contract).sum()) if len(done) else 0.0
        won = float(done.value.sum()) if len(done) else 0.0
        line = (f"{d}: {len(day)} tickets, {len(done)} settled, won {won:g} vs {done.p_blend.sum():.1f} expected, "
                f"P&L ${pnl:+.2f}")
        if complete:                       # the alert goes out once, when the day is done
            run.graded.append(line)
        run.say(line)
    else:
        run.say(f"{d}: no tickets; {n} settlement(s) stored, {len(res['written'])} journal file(s) changed")
    return complete


def _live_settle(storage: Storage, d: date, now: datetime) -> int:
    import requests

    from . import kalshi, polymarket_us
    from .grade import fetch_venue_settlements
    reader, session = kalshi.KalshiReader(), requests.Session()
    lo, hi = et_day_bounds(d)
    events = storage.query("""SELECT DISTINCT event_ticker FROM venue_signals WHERE venue = 'kalshi'
                              AND event_ticker IS NOT NULL AND tip_ts >= ? AND tip_ts < ?""", [lo, hi]).event_ticker
    by_ticker: dict[str, dict] = {}
    for ev in events:                       # one read a game; a market it misses is read on its own
        try:
            by_ticker.update({m["ticker"]: m for m in reader.event_markets(ev) if m.get("ticker")})
        except Exception as exc:
            print(f"kalshi {ev}: {type(exc).__name__}; reading its markets one by one")
    return fetch_venue_settlements(storage, d, d, now,
                                   kalshi_market=lambda t: by_ticker.get(t) or reader.market(t),
                                   pm_us_settlement=lambda t: polymarket_us.settlement(t, session))


def backfill_box_scores(storage: Storage, client, today: date, now: datetime, state: dict, run: Run) -> None:
    from .boxscores import fetch_box_scores
    have = _box_dates(storage)
    for k in range(BACKFILL_DAYS, 0, -1):
        d = today - timedelta(days=k)
        if d < config.SEASON_OPENER:
            continue
        tried = state["box_tried"].get(d.isoformat())
        if d in have or tried == "done" or (tried and now - datetime.fromisoformat(tried) < timedelta(hours=BOX_RETRY_HOURS)):
            continue
        c = fetch_box_scores(client, storage, d, now)
        # A date with no games (or every game stored) is done; one with games not final yet is retried.
        state["box_tried"][d.isoformat()] = now.isoformat() if c["events"] > c["final"] else "done"
        run.say(f"box scores {d}: {c['games']} game(s), {c['players']} player rows ({c['objects']} objects)")


def rotations(storage: Storage, today: date, now: datetime, state: dict, run: Run) -> tuple[dict[str, str], set[str]]:
    """(team -> scenario for today's un-tipped games, the games projected here): built once a day,
    a later hand-built report_MMDD swapped in on the run that sees it. Projects the games of the
    teams whose scenario is new."""
    ev = events_on(storage, today)
    ev = ev[pd.to_datetime(ev.starts_at) > pd.Timestamp(now)] if len(ev) else ev
    if ev.empty:
        return {}, set()
    teams = sorted(set(ev.away_abbr) | set(ev.home_abbr))
    have = state["rotations"].get(today.isoformat())
    if have is None:
        box, _ = history(storage, now)
        choice, notes = autorotation.choose(box, teams, today)
        for n in notes:
            run.say(f"rotation {n}")
        changed = set(choice)
    else:
        choice = dict(have)
        for team in teams:
            if team not in choice:                         # a game added to the slate later
                box, _ = history(storage, now)
                choice.update(autorotation.choose(box, [team], today)[0])
            manual = autorotation.day_scenario(team, today)
            if manual and manual != choice[team]:
                run.say(f"rotation {team}: hand-built {manual} replaces {choice[team]}")
                choice[team] = manual
        changed = {t for t in choice if have.get(t) != choice[t]}
    state["rotations"][today.isoformat()] = choice
    ids = {e.event_id for e in ev.itertuples() if {e.away_abbr, e.home_abbr} & changed}
    if ids:
        _project(storage, today, now, choice, ids, run)
    return choice, ids


def _project(storage: Storage, d: date, now: datetime, choice: dict[str, str], event_ids: set[str], run: Run) -> None:
    for eid in sorted(event_ids):                 # one game's bad input never stops the others
        try:
            table, msgs = run_projections(storage, d, now, choice, event_ids={eid})
            for m in msgs:
                if "keeping scenario" not in m and "no scenario chosen" not in m:
                    print(f"note: {m}")
        except Exception as exc:
            run.problems.append(f"projections {eid}: {type(exc).__name__}: {exc}")
            run.say(f"projections {eid} skipped: {type(exc).__name__}: {exc}")


def _ticket_line(r) -> str:
    tip = pd.Timestamp(r.tip_ts).to_pydatetime().replace(tzinfo=timezone.utc)
    cancel = (tip - timedelta(minutes=config.TICKET_CANCEL_BEFORE_TIP_MIN)).astimezone(config.ET)
    venue = {"kalshi": "Kalshi", "polymarket_us": "PM US"}.get(r.venue, r.venue)
    size = "" if pd.isna(r.contracts) or pd.isna(r.stake_usd) else f" | {r.contracts:g} ct (~${r.stake_usd:.0f})"
    return (f"{r.player} {r.contract} | {venue} | ask {100 * r.ask:.0f}c, limit {100 * r.max_price:.0f}c{size} | "
            f"cancel {cancel:%-I:%M %p} ET | fair {100 * r.p_blend:.0f}%, books {100 * r.p_market:.0f}%, "
            f"EV {100 * r.ev_blend:+.1f}pp")


def faded(storage: Storage, today: date, now: datetime, state: dict) -> list[str]:
    """Today's un-tipped tickets whose contract, at the latest read, is no longer actionable."""
    t = graded_tickets(storage)
    if t.empty:
        return []
    t = t[(t.date_et == today) & (pd.to_datetime(t.tip_ts) > pd.Timestamp(now))]
    seen = set(state["faded"].get(today.isoformat(), []))
    out = []
    for r in t.itertuples():
        if r.signal_id in seen:
            continue
        last = storage.query("""SELECT decision, ask, ev_blend FROM venue_signals WHERE venue = ? AND ticker = ?
                                AND side = ? ORDER BY ts DESC LIMIT 1""", [r.venue, r.ticker, r.side])
        if last.empty or last.decision.iloc[0] == "actionable":
            continue
        ask = last.ask.iloc[0]
        out.append(f"FADED {r.player} {r.contract}: now {last.decision.iloc[0]}"
                   + ("" if pd.isna(ask) else f" at {100 * ask:.0f}c") + ": cancel if unfilled")
        seen.add(r.signal_id)
    state["faded"][today.isoformat()] = sorted(seen)
    return out


# --- the run -------------------------------------------------------------------------------
def run(storage: Storage, now_fn: Callable[[], datetime], client_factory: Callable[[], object],
        fetchers_factory=None, state_path: Path | None = None, settle=None, send=None) -> int:
    from .venues import live_fetchers, scan
    fetchers_factory = fetchers_factory or live_fetchers
    send = send or notify.send
    state_path = state_path or config.DATA_DIR / "daily_state.json"
    source, config.PROJECTION_SOURCE = config.PROJECTION_SOURCE, config.DAILY_JOB_SOURCE
    r = Run()
    try:
        now = now_fn()
        today = et_date(now)
        state = load_state(state_path)
        r.say(f"Daily job {now:%Y-%m-%d %H:%M} UTC (slate {today}), projections: {config.PROJECTION_SOURCE}")
        try:
            client = client_factory()
        except SGOError as exc:
            client = None
            r.problems.append(f"SportsGameOdds: {exc}")
            r.say(f"SportsGameOdds unavailable ({exc}): grading venue settlements only, no new slate")

        for k in range(GRADE_LOOKBACK_DAYS, 0, -1):
            d = today - timedelta(days=k)
            tried = state["grade_tried"].get(d.isoformat())
            if (state["graded"].get(d.isoformat()) or events_on(storage, d).empty
                    or (tried and now - datetime.fromisoformat(tried) < timedelta(hours=GRADE_RETRY_HOURS))):
                continue

            def g(d=d):
                state["grade_tried"][d.isoformat()] = now_fn().isoformat()
                if grade_day(storage, client, d, now_fn(), r, settle):
                    state["graded"][d.isoformat()] = now_fn().isoformat()
            _step(r, f"grade {d}", g)

        if client is not None:
            _step(r, "box scores", lambda: backfill_box_scores(storage, client, today, now_fn(), state, r))

        due: dict[str, str] = {}

        def snap():
            out = snapshot_due(client, storage, now_fn())
            due.update(out["due"])
            if out["slate"]:
                r.say(f"slate {today}: {out['slate']['events']} game(s) stored")
            if out["objects"]:
                r.say(f"SportsGameOdds: {out['objects']} object(s) this run, {storage.objects_used_this_month()} "
                      f"this month by the local ledger (hard stop {config.MONTHLY_OBJECT_HARD_STOP})")
        if client is not None:
            _step(r, "snapshot", snap)

        choice: dict[str, str] = {}
        projected: set[str] = set()

        def rot():
            c, ids = rotations(storage, today, now_fn(), state, r)
            choice.update(c)
            projected.update(ids)
        _step(r, "rotations", rot)

        venue_plan = venue_due_plan(storage, now_fn())
        # Re-project each game at a checkpoint (fresh injury statuses), unless done a moment ago.
        again = (set(due) | set(venue_plan)) - projected
        if choice and again:
            _project(storage, today, now_fn(), choice, again, r)

        for tag in config.SIGNAL_TIMINGS:
            ids = {e for e, t in due.items() if t == tag}
            if ids:
                _step(r, f"signals {tag}", lambda ids=ids, tag=tag: run_signals(storage, today, now_fn(), timing=tag,
                                                                               event_ids=ids))

        before = set(graded_tickets(storage).get("signal_id", pd.Series(dtype=str)))
        for tag in sorted(set(venue_plan.values()), key=lambda t: -config.VENUE_OFFSETS_MIN[t]):
            ids = {e for e, t in venue_plan.items() if t == tag}

            def read(tag=tag, ids=ids):
                f = fetchers_factory()
                df = scan(storage, today, now_fn(), f, tag=tag, event_ids=ids, bankroll=config.bankroll_usd())
                for e in f.errors:
                    print(f"venue note: {e}")
                n_act = int((df.decision == "actionable").sum()) if len(df) else 0
                r.say(f"venues {tag}: {len(ids)} game(s), {len(df)} contract sides, {n_act} actionable")
            _step(r, f"venues {tag}", read)

        if venue_plan:
            def journal_today():
                t = graded_tickets(storage)
                r.new_tickets = t[~t.signal_id.isin(before)] if len(t) else t
                r.faded = faded(storage, today, now_fn(), state)
                write_journal(storage, config.BETS_DIR, [today])
            _step(r, "journal", journal_today)
        if not (venue_plan or due or r.graded):
            r.say("Nothing due this run.")
        _alerts(r, today, send, state)
        save_state(state_path, state, today)
    finally:
        config.PROJECTION_SOURCE = source
    for p in r.notices:
        print(f"NOTICE: {p}")
    for p in r.problems:
        print(f"PROBLEM: {p}")
    return 1 if r.problems else 0


def _alerts(r: Run, today: date, send, state: dict) -> None:
    if len(r.new_tickets):
        lines = [_ticket_line(t) for t in r.new_tickets.sort_values("ev_blend", ascending=False).itertuples()]
        games = ", ".join(sorted(set(r.new_tickets.game)))
        send(f"PLAYS {today} {games}", "\n".join(lines + r.faded), "high")
        r.say("New tickets:\n  " + "\n  ".join(lines))
    elif r.faded:
        send(f"FADED {today}", "\n".join(r.faded), "default")
    if r.faded:
        r.say("\n".join(r.faded))
    if r.graded:
        send("Graded", "\n".join(r.graded) + "\nSeason: bets/SEASON.md", "default")
    # A problem or notice alerts once a day (a missing key would otherwise alert every run).
    told = state.setdefault("problems", {}).setdefault(today.isoformat(), [])
    for title, items, prio in (("RUN PROBLEM", r.problems, "high"), ("NOTICE", r.notices, "default")):
        new = [p for p in dict.fromkeys(items) if p not in told]
        if new:
            send(title, "\n".join(new)[:1500], prio)
            told += new
