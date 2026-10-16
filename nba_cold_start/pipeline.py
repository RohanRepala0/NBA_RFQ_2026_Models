"""Orchestration behind the CLI: snapshot, project, signals, results."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from . import config
from .config import CLOSE_TAG, MODEL_VERSION
from .consensus import consensus_by_player, latest_snapshot_rows
from .ingest import player_points_results, save_raw, store_snapshot
from .players import candidates_for_event, map_players
from .schedule import current_timing, due_tag, et_date, et_day_bounds, iso_z
from .sgo_client import SGOClient, filter_event
from .signals import make_signal
from .spacing import load_team_shooting
from .storage import Storage, to_naive_utc
from .usage_model import inputs_hash, load_players, load_scenarios, modeled_teams, project_scenario


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
            "oddID": config.POINTS_ODD_FILTER, "includeOpposingOdds": "true",
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


def slate_already_fetched(storage: Storage, d: date) -> bool:
    df = storage.query("SELECT count(*) AS n FROM api_calls WHERE note = ?", [f"slate:{d.isoformat()}"])
    return int(df.n.iloc[0]) > 0


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
    if not slate_already_fetched(storage, today):
        out["slate"] = snapshot_slate(client, storage, today, now)
        out["objects"] += out["slate"]["objects"]
    plan = due_snapshot_plan(storage, now)
    out["due"] = plan
    if plan:
        params = {"eventIDs": ",".join(sorted(plan)), "oddID": config.POINTS_ODD_FILTER,
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


def run_projections(storage: Storage, d: date, now: datetime, scenario_choice: dict[str, str],
                    players: pd.DataFrame | None = None, scenarios_dir=None,
                    log: bool = True) -> tuple[pd.DataFrame, list[str]]:
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
        starts = pd.Timestamp(ev.starts_at).to_pydatetime()
        for team in (ev.away_abbr, ev.home_abbr):
            if team not in teams:
                continue
            if now >= starts:
                messages.append(f"{team} {ev.event_id}: already tipped, not logging (log before outcome)")
                continue
            name = scenario_choice.get(team, "full_strength")
            scen_all = load_scenarios(team, scenarios_dir)
            scen = scen_all[scen_all.scenario == name]
            if scen.empty:
                raise ValueError(f"{team}: no scenario {name!r}; have {sorted(scen_all.scenario.unique())}")
            if team not in scenario_choice:
                messages.append(f"{team}: no scenario chosen, using full_strength (pass --scenario {team}=...)")
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
                    rows.append({"ts": now, "event_id": ev.event_id, "player_id": pid,
                                 "player_name": r.player, "team": team,
                                 "new_team": None if r.new_team is None else bool(r.new_team),
                                 "scenario": name, "mean": mean,
                                 "sd": None if mean is None else float(r.sd_proj),
                                 "proj_mpg": float(r.proj_mpg), "usg_proj": float(r.usg_proj),
                                 "inputs_hash": h, "model_version": MODEL_VERSION})
                status = roster_status.get(pid)
                printed.append({"event": ev.event_id, "team": team, "scenario": name, "player": r.player,
                                "player_id": pid or "UNMAPPED", "status": status,
                                "min": r.proj_mpg, "usg": r.usg_pct, "usg_proj": round(r.usg_proj, 2),
                                "ppg_25_26": r.ppg, "proj": None if mean is None else round(mean, 2),
                                "spc_old": None if pd.isna(r.spacing_old) else round(r.spacing_old, 1),
                                "spc_new": None if pd.isna(r.spacing_new) else round(r.spacing_new, 1),
                                "sd": None if mean is None else round(float(r.sd_proj), 2),
                                "fair_line": r.fair_line})
                if status in ("out", "ir", "suspended", "doubtful"):
                    messages.append(f"{team}: {r.player} is listed {status} but is in scenario {name}")
            if log:
                storage.append("projections", rows)
    return pd.DataFrame(printed), messages


# --- Signals -------------------------------------------------------------------------
def latest_projections(storage: Storage, event_id: str, now: datetime) -> pd.DataFrame:
    return storage.query("""
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY player_id ORDER BY ts DESC) rn
          FROM projections WHERE event_id = ? AND ts <= ?) WHERE rn = 1""", [event_id, now])


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
                         "timing": when, "projection_ts": p.ts, "model_version": p.model_version,
                         **sig})
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
    """Append results for every projected player on finalized events."""
    messages, n = [], 0
    stored = storage.latest_events().set_index("event_id")
    for ev in events:
        eid = ev["eventID"]
        if not (ev.get("status") or {}).get("finalized"):
            messages.append(f"{eid}: not final yet")
            continue
        if eid not in stored.index:
            continue
        starts = pd.Timestamp(stored.loc[eid, "starts_at"]).to_pydatetime()
        actual = player_points_results(ev)
        players = storage.query("SELECT DISTINCT player_id FROM projections WHERE event_id = ?", [eid]).player_id
        cons, source = close_consensus(storage, eid, starts)
        rows = []
        for pid in players:
            if pid not in actual:
                messages.append(f"{eid}/{pid}: no points result (DNP?)")
                continue
            c = cons.get(pid)
            ok = c is not None and c.mean is not None and c.n_books >= config.MIN_PRICED_BOOKS
            rows.append({"ts": now, "event_id": eid, "player_id": pid, "actual_points": actual[pid],
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
    params = {"eventIDs": ",".join(need), "oddID": config.POINTS_ODD_FILTER,
              "includeOpposingOdds": "true", "bookmakerID": config.request_bookmaker_filter()}
    result = client.events(params, max_objects=len(need), note=f"results:{d.isoformat()}")
    if result.events:
        save_raw(result.events, now, f"results_{d.isoformat()}")
    n, messages = ingest_results(storage, result.events, now)
    return result.objects, n, messages
