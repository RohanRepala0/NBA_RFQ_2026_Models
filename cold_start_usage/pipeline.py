"""Orchestration behind the CLI: snapshot, project, signals, results."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from . import config
from .boxscores import store_box_scores
from .config import CLOSE_TAG, MODEL_VERSION
from .consensus import consensus_by_player, latest_snapshot_rows
from .ingest import player_stat_results, save_raw, store_snapshot
from .players import candidates_for_event, map_players
from .schedule import current_timing, due_tag, et_date, et_day_bounds, iso_z
from .sgo_client import SGOClient, filter_event
from .signals import make_signal
from .spacing import load_team_shooting
from .storage import Storage, to_naive_utc
from .usage_model import (PROJECTION_COLUMNS, inputs_hash, load_players, load_scenarios, modeled_teams,
                          project_scenario)


def ledger_for(storage: Storage, now_fn):
    def ledger(endpoint: str, params: dict, status: int, objects: int, note: str) -> None:
        storage.append("api_calls", [{"ts": now_fn(), "endpoint": endpoint,
                                      "params": str(sorted(params.items())), "http_status": status,
                                      "objects": objects, "note": note}])
    return ledger


def events_on(storage: Storage, d: date) -> pd.DataFrame:
    ev = storage.latest_events()
    if ev.empty:
        return ev
    ev = ev[ev.starts_at.notna() & ~ev.cancelled.fillna(False).astype(bool)]
    return ev[ev.starts_at.map(et_date) == d].sort_values("starts_at").reset_index(drop=True)


def _tags_taken(storage: Storage, event_id: str) -> set[str]:
    df = storage.query("SELECT DISTINCT snapshot_tag FROM events WHERE event_id = ?", [event_id])
    return set(df.snapshot_tag.dropna())


def slate_params(d: date) -> dict:
    start, end = et_day_bounds(d)
    return {"leagueID": config.LEAGUE_ID, "oddsAvailable": "true",
            "startsAfter": iso_z(start), "startsBefore": iso_z(end),
            "oddID": config.STATS_ODD_FILTER, "includeOpposingOdds": "true",
            "bookmakerID": config.request_bookmaker_filter()}


def _tag_events(storage: Storage, events: list[dict], now: datetime, default: str) -> dict[str, str]:
    seen = set(storage.latest_events().event_id) if storage.count("events") else set()
    tags = {}
    for ev in events:
        eid = ev["eventID"]
        if eid not in seen:
            tags[eid] = "open"
            continue
        starts = to_naive_utc((ev.get("status") or {}).get("startsAt"))
        tags[eid] = (due_tag(starts, now, _tags_taken(storage, eid)) if starts else None) or default
    return tags


def ingest(storage: Storage, events: list[dict], now: datetime, default_tag: str,
           label: str, tags: dict[str, str] | None = None, raw: bool = True) -> dict:
    tags = tags or _tag_events(storage, events, now, default_tag)
    counts = store_snapshot(storage, events, now, tags)
    if raw and events:
        counts["raw_file"] = str(save_raw(events, now, label))
    counts["tags"] = tags
    return counts


def snapshot_slate(client: SGOClient, storage: Storage, d: date, now: datetime) -> dict:
    result = client.events(slate_params(d), note=f"slate:{d.isoformat()}")
    counts = ingest(storage, result.events, now, "adhoc", f"slate_{d.isoformat()}")
    return {"objects": result.objects, "usage_before": result.usage_before,
            "notices": result.notices, **counts}


def snapshot_from_file(storage: Storage, payload, now: datetime) -> dict:
    events = payload.get("data", payload) if isinstance(payload, dict) else payload
    events = [filter_event(e) for e in events]          # same parse-time filter as the API path
    return {"objects": 0, **ingest(storage, events, now, "adhoc", "file", raw=False)}


SLATE_RETRY_AFTER_MIN = 60
SLATE_MAX_FAILURES = 3


def slate_already_fetched(storage: Storage, d: date, now: datetime | None = None) -> bool:
    """True once the day's slate is stored, and also while a failed fetch is backing off: a failed
    /events call is billed, so retrying it every 5-minute cron tick would burn the budget. At most
    SLATE_MAX_FAILURES attempts a day, an hour apart."""
    df = storage.query("""SELECT count(*) FILTER (WHERE note = ?) AS ok,
                                 count(*) FILTER (WHERE note = ?) AS failed,
                                 max(ts) FILTER (WHERE note = ?) AS last_failed
                          FROM api_calls""", [f"slate:{d.isoformat()}", f"slate:{d.isoformat()} | failed",
                                             f"slate:{d.isoformat()} | failed"])
    r = df.iloc[0]
    if int(r.ok) > 0 or int(r.failed) >= SLATE_MAX_FAILURES:
        return True
    if now is not None and int(r.failed) > 0 and pd.notna(r.last_failed):
        return pd.Timestamp(now) - pd.Timestamp(r.last_failed) < pd.Timedelta(minutes=SLATE_RETRY_AFTER_MIN)
    return False


def due_snapshot_plan(storage: Storage, now: datetime) -> dict[str, str]:
    plan = {}
    for ev in events_on(storage, et_date(now)).itertuples():
        tag = due_tag(pd.Timestamp(ev.starts_at).to_pydatetime(), now, _tags_taken(storage, ev.event_id))
        if tag:
            plan[ev.event_id] = tag
    return plan


def snapshot_due(client: SGOClient, storage: Storage, now: datetime) -> dict:
    """For cron: fetch today's slate once, then only events at a new checkpoint."""
    today = et_date(now)
    out = {"objects": 0, "slate": None, "due": {}}
    if not slate_already_fetched(storage, today, now):
        out["slate"] = snapshot_slate(client, storage, today, now)
        out["objects"] += out["slate"]["objects"]
    plan = due_snapshot_plan(storage, now)
    out["due"] = plan
    if plan:
        params = {"eventIDs": ",".join(sorted(plan)), "oddID": config.STATS_ODD_FILTER,
                  "includeOpposingOdds": "true", "bookmakerID": config.request_bookmaker_filter()}
        result = client.events(params, max_objects=len(plan), note="due:" + ",".join(sorted(set(plan.values()))))
        ingest(storage, result.events, now, "adhoc", "due", tags=plan)
        out["objects"] += result.objects
        out["usage_before"] = result.usage_before
    return out


# --- Projections ---------------------------------------------------------------------
def _odds_player_ids(storage: Storage, event_id: str) -> list[str]:
    return storage.query("SELECT DISTINCT player_id FROM odds_snapshots WHERE event_id = ?",
                         [event_id]).player_id.tolist()


def _roster(storage: Storage, event_id: str) -> pd.DataFrame:
    return storage.query("""
        SELECT player_id, name, team_abbr, status FROM (
          SELECT *, row_number() OVER (PARTITION BY player_id ORDER BY ts DESC) rn
          FROM event_players WHERE event_id = ?) WHERE rn = 1""", [event_id])


def latest_scenarios(storage: Storage, event_id: str, now: datetime) -> dict[str, str]:
    """team -> the scenario of its latest projection run for this game logged by `now`."""
    df = storage.query("""
        SELECT team, scenario FROM (
          SELECT team, scenario, row_number() OVER (PARTITION BY team ORDER BY ts DESC) rn
          FROM projections WHERE event_id = ? AND ts <= ?) WHERE rn = 1""", [event_id, now])
    return dict(zip(df.team, df.scenario))


def run_projections(storage: Storage, d: date, now: datetime, scenario_choice: dict[str, str],
                    players: pd.DataFrame | None = None, scenarios_dir=None,
                    log: bool = True, event_ids: set[str] | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Project every modeled team on the date's un-tipped games and log one row per player and
    stat (config.STATS; a stat the inputs can't project is logged with a NULL mean). A team
    named in `scenario_choice` runs that scenario; any other team keeps the scenario of its
    latest logged run for the game (full_strength only when it has none), so
    `project --scenario TOR=...` never resets an earlier `--scenario MIA=...`."""
    players = load_players() if players is None else players
    team_shooting = load_team_shooting()
    teams = set(modeled_teams(scenarios_dir))
    explicit = (dict(zip(players.player, players.sgo_player_id))
                if "sgo_player_id" in players.columns else {})
    printed, messages = [], []
    events = events_on(storage, d)
    if events.empty:
        messages.append(f"No stored events for {d}. Run `snapshot --date {d}` first.")
    for ev in events.itertuples():
        if event_ids is not None and ev.event_id not in event_ids:
            continue
        starts = pd.Timestamp(ev.starts_at).to_pydatetime()
        previous = latest_scenarios(storage, ev.event_id, now)
        for team in (ev.away_abbr, ev.home_abbr):
            if team not in teams:
                continue
            if now >= starts:
                messages.append(f"{team} {ev.event_id}: already tipped, not logging (log before outcome)")
                continue
            name = scenario_choice.get(team) or previous.get(team) or "full_strength"
            scen_all = load_scenarios(team, scenarios_dir)
            scen = scen_all[scen_all.scenario == name]
            if scen.empty:
                raise ValueError(f"{team}: no scenario {name!r}; have {sorted(scen_all.scenario.unique())}")
            if team not in scenario_choice:
                messages.append(f"{team}: keeping scenario {name} from the last run (pass --scenario {team}=... "
                                "to change it)" if team in previous else
                                f"{team}: no scenario chosen, using full_strength (pass --scenario {team}=...)")
            res = project_scenario(players, scen, team_shooting=team_shooting)
            roster = _roster(storage, ev.event_id)
            cands = candidates_for_event(roster, _odds_player_ids(storage, ev.event_id))
            mapping, problems = map_players(res.player.tolist(), cands, team, explicit)
            messages += [f"{team}: {p}" for p in problems]
            roster_status = dict(zip(roster.player_id, roster.status))
            h = inputs_hash(players, scen)
            rows = []
            for r in res.itertuples():
                pid = mapping.get(r.player)
                mean = None if pd.isna(r.ppg_proj) else float(r.ppg_proj)
                if pid:
                    for stat in config.STATS:
                        mean_col, sd_col = PROJECTION_COLUMNS[stat]
                        m = getattr(r, mean_col, None)
                        m = None if m is None or pd.isna(m) else float(m)
                        rows.append({"ts": now, "event_id": ev.event_id, "player_id": pid,
                                     "player_name": r.player, "team": team,
                                     "new_team": None if r.new_team is None else bool(r.new_team),
                                     "scenario": name, "stat": stat, "mean": m,
                                     "sd": None if m is None else float(getattr(r, sd_col)),
                                     "proj_mpg": float(r.proj_mpg), "usg_proj": float(r.usg_proj),
                                     "inputs_hash": h, "model_version": MODEL_VERSION})
                status = roster_status.get(pid)
                reb, ast = getattr(r, "reb_proj", float("nan")), getattr(r, "ast_proj", float("nan"))
                printed.append({"event": ev.event_id, "team": team, "scenario": name, "player": r.player,
                                "player_id": pid or "UNMAPPED", "status": status,
                                "min": r.proj_mpg, "usg": r.usg_pct, "usg_proj": round(r.usg_proj, 2),
                                "ppg_25_26": r.ppg, "proj": None if mean is None else round(mean, 2),
                                "spc_old": None if pd.isna(r.spacing_old) else round(r.spacing_old, 1),
                                "spc_new": None if pd.isna(r.spacing_new) else round(r.spacing_new, 1),
                                "sd": None if mean is None else round(float(r.sd_proj), 2),
                                "fair_line": r.fair_line,
                                "reb": None if pd.isna(reb) else round(float(reb), 2),
                                "ast": None if pd.isna(ast) else round(float(ast), 2)})
                if status in ("out", "ir", "suspended", "doubtful"):
                    messages.append(f"{team}: {r.player} is listed {status} but is in scenario {name}")
            if log:
                storage.append("projections", rows)
    return pd.DataFrame(printed), messages


# --- Signals -------------------------------------------------------------------------
def latest_projections(storage: Storage, event_id: str, now: datetime) -> pd.DataFrame:
    """Each team's most recent projection run for the game, one row per player and stat (a NULL
    stat, from runs logged before rebounds and assists, reads as points). A later run (say
    `project --scenario MIA=giannis_out` after an auto full_strength) replaces the whole team,
    so a player left out of the new scenario doesn't keep his stale earlier projection."""
    return storage.query("""
        WITH runs AS (SELECT team, max(ts) AS ts FROM projections WHERE event_id = ? AND ts <= ? GROUP BY team)
        SELECT * EXCLUDE (rn) FROM (
          SELECT p.* REPLACE (coalesce(p.stat, 'points') AS stat),
                 row_number() OVER (PARTITION BY p.player_id, coalesce(p.stat, 'points') ORDER BY p.ts DESC) rn
          FROM projections p JOIN runs USING (team, ts) WHERE p.event_id = ?) WHERE rn = 1""",
                         [event_id, now, event_id])


def run_signals(storage: Storage, d: date, now: datetime, timing: str | None = None,
                log: bool = True, event_ids: set[str] | None = None) -> tuple[pd.DataFrame, list[str]]:
    out, messages = [], []
    for ev in events_on(storage, d).itertuples():
        if event_ids is not None and ev.event_id not in event_ids:
            continue
        starts = pd.Timestamp(ev.starts_at).to_pydatetime()
        if now >= starts:
            messages.append(f"{ev.event_id}: already tipped, not logging (log before outcome)")
            continue
        projs = latest_projections(storage, ev.event_id, now)
        projs = projs[projs.stat == "points"] if len(projs) else projs       # leans are points-only
        if projs.empty:
            continue
        cons = consensus_by_player(storage, ev.event_id, as_of=now, before=now)
        when = timing or current_timing(starts, now)
        rows = []
        for p in projs.itertuples():
            proj = None if p.mean is None or pd.isna(p.mean) else {"mean": p.mean, "sd": p.sd}
            sig = make_signal(proj, cons.get(p.player_id))
            rows.append({"ts": now, "event_id": ev.event_id, "player_id": p.player_id,
                         "player_name": p.player_name, "team": p.team,
                         "new_team": None if pd.isna(p.new_team) else bool(p.new_team),
                         "timing": when, "stat": "points", "projection_ts": p.ts,
                         "model_version": p.model_version, **sig})
        if log:
            storage.append("signals", rows)
        out += rows
    return pd.DataFrame(out), messages


# --- Results (for grading) -------------------------------------------------------------
def close_consensus(storage: Storage, event_id: str, starts_at: datetime):
    snap_ts, _ = latest_snapshot_rows(storage, event_id, before=starts_at, tag=CLOSE_TAG)
    source = CLOSE_TAG
    if snap_ts is None:
        snap_ts, _ = latest_snapshot_rows(storage, event_id, before=starts_at)
        source = "latest-pre-tip"
    if snap_ts is None:
        return {}, None
    tag = CLOSE_TAG if source == CLOSE_TAG else None
    return consensus_by_player(storage, event_id, as_of=snap_ts, before=starts_at, tag=tag), source


def ingest_results(storage: Storage, events: list[dict], now: datetime) -> tuple[int, list[str]]:
    """Append results (points, rebounds, assists) for every projected player on finalized events,
    and the box scores of every listed player (boxscores.py). The close consensus columns are the
    points consensus."""
    messages, n = [], 0
    store_box_scores(storage, events, now)
    stored = storage.latest_events().set_index("event_id")
    for ev in events:
        eid = ev["eventID"]
        if not (ev.get("status") or {}).get("finalized"):
            messages.append(f"{eid}: not final yet")
            continue
        if eid not in stored.index:
            continue
        starts = pd.Timestamp(stored.loc[eid, "starts_at"]).to_pydatetime()
        actual = player_stat_results(ev)
        players = storage.query("SELECT DISTINCT player_id FROM projections WHERE event_id = ?", [eid]).player_id
        cons, source = close_consensus(storage, eid, starts)
        rows = []
        for pid in players:
            if pid not in actual:
                messages.append(f"{eid}/{pid}: no result (DNP?)")
                continue
            c = cons.get(pid)
            ok = c is not None and c.mean is not None and c.n_books >= config.MIN_PRICED_BOOKS
            got = actual[pid]
            rows.append({"ts": now, "event_id": eid, "player_id": pid, "actual_points": got.get("points"),
                         "actual_rebounds": got.get("rebounds"), "actual_assists": got.get("assists"),
                         "close_consensus_line": c.line if ok else None,
                         "close_consensus_p": c.p_over if ok else None,
                         "close_consensus_mean": c.mean if ok else None,
                         "close_n_books": c.n_books if c else 0,
                         "close_snapshot_ts": c.snapshot_ts if c else None,
                         "close_source": source})
        n += storage.append("results", rows)
    return n, messages


def events_needing_results(storage: Storage, d: date) -> list[str]:
    ev = events_on(storage, d)
    if ev.empty:
        return []
    have = set(storage.query("SELECT DISTINCT event_id FROM results").event_id)
    projected = set(storage.query("SELECT DISTINCT event_id FROM projections").event_id)
    return [e for e in ev.event_id if e in projected and e not in have]


def fetch_results(client: SGOClient, storage: Storage, d: date, now: datetime) -> tuple[int, int, list[str]]:
    need = events_needing_results(storage, d)
    if not need:
        return 0, 0, ["results already stored (or nothing projected) for this date"]
    params = {"eventIDs": ",".join(need), "oddID": config.STATS_ODD_FILTER,
              "includeOpposingOdds": "true", "bookmakerID": config.request_bookmaker_filter()}
    result = client.events(params, max_objects=len(need), note=f"results:{d.isoformat()}")
    if result.events:
        save_raw(result.events, now, f"results_{d.isoformat()}")
    n, messages = ingest_results(storage, result.events, now)
    return result.objects, n, messages


# --- Venue checkpoints (free public reads) ----------------------------------------------
def venue_due_plan(storage: Storage, now: datetime) -> dict[str, str]:
    """event_id -> venue checkpoint (t-6h ... t-5m) that has passed and not been read yet."""
    plan = {}
    for ev in events_on(storage, et_date(now)).itertuples():
        # Taken only once Kalshi answered for the game (a listing or a "no listing" marker): a
        # failed Kalshi read, or reference-only rows, leave the checkpoint open for the next tick.
        taken = set(storage.query("SELECT DISTINCT tag FROM venue_snapshots WHERE event_id = ? AND venue = 'kalshi'",
                                  [ev.event_id]).tag.dropna())
        tag = due_tag(pd.Timestamp(ev.starts_at).to_pydatetime(), now, taken, config.VENUE_OFFSETS_MIN)
        if tag:
            plan[ev.event_id] = tag
    return plan


def events_without_projections(storage: Storage, event_ids: set[str], scenarios_dir=None) -> set[str]:
    """Events where a modeled team has no current projection run: none logged, a latest run
    logged under an older MODEL_VERSION, or one missing a configured stat (say, points-only rows
    from before rebounds and assists). The cron re-runs them, and run_projections keeps each
    team's latest scenario, so a model update never leaves stale projections driving the scan."""
    if not event_ids:
        return set()
    teams = set(modeled_teams(scenarios_dir))
    ev = storage.latest_events()
    ev = ev[ev.event_id.isin(set(event_ids))] if len(ev) else ev
    runs = storage.query("""
        WITH last AS (SELECT event_id, team, max(ts) AS ts FROM projections GROUP BY 1, 2)
        SELECT p.event_id, p.team, min(p.model_version) AS v_min, max(p.model_version) AS v_max,
               list(DISTINCT coalesce(p.stat, 'points')) AS stats
        FROM projections p JOIN last USING (event_id, team, ts) GROUP BY 1, 2""")
    current = {(r.event_id, r.team) for r in runs.itertuples()
               if r.v_min == MODEL_VERSION and r.v_max == MODEL_VERSION and set(config.STATS) <= set(r.stats)}
    out = set()
    for e in ev.itertuples():
        if any(t in teams and (e.event_id, t) not in current for t in (e.away_abbr, e.home_abbr)):
            out.add(e.event_id)
    return out
