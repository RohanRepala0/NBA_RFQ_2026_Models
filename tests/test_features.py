"""Rolling features: as-of reads, shrinkage, minutes to 240, role classes, the source switch."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cold_start_usage import config
from cold_start_usage.boxscores import store_box_scores
from cold_start_usage.features import (Prior, history, player_features, recent_rotation, role_class,
                                       rolling_minutes, shrink, team_context)
from cold_start_usage.storage import Storage

FIXTURE = Path(__file__).parent / "fixtures" / "sgo_results_ot_game.json"


def _game(event_id: str, starts: str) -> dict:
    g = json.loads(FIXTURE.read_text())
    g["eventID"] = event_id
    g["status"]["startsAt"] = starts
    return g


def test_history_reads_only_earlier_et_dates():
    with Storage(":memory:") as s:
        store_box_scores(s, [_game("early", "2026-10-25T23:00:00Z"),        # Oct 25, 7 pm ET
                             _game("same_day", "2026-10-26T23:00:00Z"),     # Oct 26, 7 pm ET
                             _game("later", "2026-10-28T00:00:00Z")], datetime(2026, 10, 28, 12))
        box, teams = history(s, datetime(2026, 10, 27, 2, 0))               # Oct 26, 10 pm ET tip
        assert set(box.event_id) == {"early"} and set(teams.event_id) == {"early"}
        assert box.played.all()


def test_shrinkage_runs_from_the_prior_to_the_sample():
    assert shrink(0.5, 100.0, 0.0, 0.0) == 0.5
    assert shrink(0.5, 100.0, 300.0, 1000.0) == pytest.approx((50 + 300) / 1100)
    assert shrink(0.5, 100.0, 3000.0, 1e6) == pytest.approx(0.003, abs=1e-4)


def _games(minutes, pts, usg) -> pd.DataFrame:
    n = len(minutes)
    return pd.DataFrame({"minutes": minutes, "pts": pts, "usg_pct": usg, "reb": [5.0] * n, "ast": [3.0] * n,
                         "fg3m": [1.0] * n, "stl": [1.0] * n, "blk": [0.5] * n, "tov": [2.0] * n,
                         "fga": [10.0] * n, "fta": [3.0] * n})


PRIOR = Prior(mpg=30.0, usg=20.0, rates={s: 0.5 for s in ("points", "rebounds", "assists", "threes", "steals",
                                                           "blocks", "turnovers")}, new_team=False, has_row=True)


def test_no_games_means_the_prior_and_momentum_is_five_minus_twenty():
    empty = player_features(_games([], [], []), PRIOR)
    assert empty["games"] == 0 and empty["rate_points"] == 0.5 and empty["usg"] == 20.0
    mins = [36.0] * 5 + [24.0] * 15                                  # newest first: minutes went up
    f = player_features(_games(mins, [18.0] * 20, [25.0] * 20), PRIOR)
    assert f["min_5"] == 36 and f["min_20"] == pytest.approx(27) and f["d_min"] == pytest.approx(9)
    assert 20.0 < f["usg"] < 25.0
    k = config.ROLLING_PRIOR_GAMES["points"] * 30.0
    assert f["rate_points"] == pytest.approx((k * 0.5 + 360) / (k + sum(mins)))


def test_a_new_team_halves_the_prior_weight():
    games = _games([30.0] * 3, [30.0] * 3, [20.0] * 3)
    same = player_features(games, PRIOR)
    moved = player_features(games, Prior(**{**PRIOR.__dict__, "new_team": True}))
    assert abs(moved["rate_points"] - 1.0) < abs(same["rate_points"] - 1.0)


def test_role_classes():
    assert role_class(3, 34.0, 0.05, 0.05, 0.05) == "unknown"
    assert role_class(10, 34.0, 0.08, 0.10, 0.20) == "engine"
    assert role_class(10, 24.0, 0.10, 0.30, 0.55) == "heat_check"
    assert role_class(10, 18.0, 0.35, 0.20, 0.30) == "volatile_role"
    assert role_class(10, 26.0, 0.15, 0.20, 0.30) == "steady"


def test_rolling_minutes_sum_to_240_and_shortfalls_respect_the_cap():
    scen = pd.DataFrame({"player": list("ABCDEFGH"), "proj_mpg": [36, 34, 32, 30, 28, 30, 25, 25.0]})
    recent = {"A": (40.0, 5), "B": (20.0, 5), "C": (32.0, 2)}
    m = rolling_minutes(scen, recent).set_index("player")
    assert m.proj_mpg.sum() == pytest.approx(240)
    assert m.at["A", "proj_mpg"] >= (3 * 36 + 5 * 40) / 8 - 1e-9          # above the cap already: keeps his
    assert (m.drop(index="A").proj_mpg <= config.ROLLING_MINUTES_CAP + 1e-6).all()
    assert m.at["B", "proj_mpg"] < 34                                       # a smaller recent role sticks
    over = rolling_minutes(scen.assign(proj_mpg=scen.proj_mpg + 10), {})
    assert over.proj_mpg.sum() == pytest.approx(240)


def test_recent_rotation_leaves_out_players_ruled_out():
    with Storage(":memory:") as s:
        store_box_scores(s, [_game("g1", "2026-10-25T23:00:00Z")], datetime(2026, 10, 26))
        box, _ = history(s, datetime(2026, 10, 27, 23))
        allin = recent_rotation(box, "MIN", set())
        assert "ANTHONY_EDWARDS_1_NBA" in set(allin.player_id)
        out = recent_rotation(box, "MIN", {"ANTHONY_EDWARDS_1_NBA"})
        assert "ANTHONY_EDWARDS_1_NBA" not in set(out.player_id) and len(out) == len(allin) - 1
        assert (allin.proj_mpg > 0).all()


def test_team_context_is_neutral_without_history_and_clamped_with_it():
    empty = pd.DataFrame(columns=["team", "opponent", "possessions", "team_minutes", "pts"])
    ctx = team_context(empty, "MIN", "CLE")
    assert ctx["pace_mult"] == 1.0 and ctx["def_points"] == 1.0
    with Storage(":memory:") as s:
        store_box_scores(s, [_game("g1", "2026-10-25T23:00:00Z")], datetime(2026, 10, 26))
        _, teams = history(s, datetime(2026, 10, 27, 23))
        ctx = team_context(teams, "MIN", "CLE")
        lo, hi = config.CONTEXT_CLAMP
        assert all(lo <= v <= hi for k, v in ctx.items() if k.startswith(("def_", "pace")))
        assert ctx["team_games"] == 1 and ctx["opp_games"] == 1


def test_the_default_source_is_still_the_season_model():
    assert config.PROJECTION_SOURCE == "season"
    assert config.current_model_version() == config.MODEL_VERSION
    assert config.current_model_version("rolling") == config.ROLLING_MODEL_VERSION != config.MODEL_VERSION
    assert not set(config.EXTRA_STATS) & set(config.STATS)          # the venue scan never sees them


def test_rolling_runs_without_history_match_the_season_model_and_log_the_extra_stats(storage):
    from cold_start_usage.pipeline import events_without_projections, run_projections, snapshot_from_file
    from tests.fixtures.synthetic import EVENT_ID, FETCHED, TIP, events_response, synthetic_event
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    season, _ = run_projections(storage, TIP.date(), FETCHED, {"MIA": "full_strength"}, log=False)
    rolling, _ = run_projections(storage, TIP.date(), FETCHED, {"MIA": "full_strength"}, source="rolling")
    m = season.merge(rolling, on="player", suffixes=("_s", "_r"))
    assert len(m) == len(season)
    known = m.dropna(subset=["proj_s"])
    assert np.allclose(known.proj_s, known.proj_r, atol=1e-6)          # no box scores: priors and the scenario
    assert np.allclose(m.min_s, m.min_r)
    logged = storage.query("SELECT DISTINCT model_version FROM projections").model_version.tolist()
    assert logged == [config.ROLLING_MODEL_VERSION]
    extra = storage.query("SELECT stat, count(*) n FROM extra_projections GROUP BY 1")
    assert set(extra.stat) == set(config.SHADOW_STATS)
    # A rolling run is stale for a cron on the season source, so switching back re-projects.
    assert EVENT_ID in events_without_projections(storage, {EVENT_ID})


def test_a_player_who_never_shoots_threes_has_a_zero_threes_prior():
    from cold_start_usage.features import prior_rates
    players = pd.DataFrame([{"player": "Center", "team_2025_26": "AAA", "team_2026_27": "AAA", "usg_pct": 15.0,
                             "mpg": 25.0, "ppg": 10.0, "rpg": 9.0, "apg": 1.0, "fg3a_pg": 0.0, "fg3_pct": np.nan,
                             "verified": "yes", "sgo_player_id": "C_1_NBA"},
                            {"player": "Shooter", "team_2025_26": "AAA", "team_2026_27": "AAA", "usg_pct": 20.0,
                             "mpg": 30.0, "ppg": 15.0, "rpg": 3.0, "apg": 2.0, "fg3a_pg": 6.0, "fg3_pct": 40.0,
                             "verified": "yes", "sgo_player_id": "S_1_NBA"}])
    pr = prior_rates(players).set_index("player")
    assert pr.at["Center", "prior_threes"] == 0.0
    assert pr.at["Shooter", "prior_threes"] == pytest.approx(6 * 0.4 / 30)


def test_a_bench_candidate_tagged_with_the_wrong_team_stays_off_its_rotation():
    from cold_start_usage.features import rolling_inputs
    with Storage(":memory:") as s:
        game = _game("g1", "2026-10-25T23:00:00Z")
        # Tag a CLE player as MIN's, the way SportsGameOdds once tagged a MIA player as DAL's.
        cle = next(pid for pid, p in game["players"].items() if p["teamID"].startswith("CLEVELAND")
                   and (game["results"]["game"].get(pid) or {}).get("secondsPlayed"))
        name = game["players"][cle]["name"]
        game["players"][cle]["teamID"] = game["teams"]["away"]["teamID"]
        store_box_scores(s, [game], datetime(2026, 10, 26))
        box, teams = history(s, datetime(2026, 10, 27, 23))
        assert cle in set(box[box.team == "MIN"].player_id)
        row = {"team_2025_26": "MIN", "usg_pct": 20.0, "games": 60, "mpg": 30.0, "ppg": 15.0, "rpg": 4.0,
               "apg": 3.0, "fg3a_pg": 5.0, "fg3_pct": 36.0, "verified": "yes", "source": "src"}
        players = pd.DataFrame([{**row, "player": "Anthony Edwards", "team_2026_27": "MIN",
                                 "sgo_player_id": "ANTHONY_EDWARDS_1_NBA"},
                                {**row, "player": name, "team_2025_26": "CLE", "team_2026_27": "CLE",
                                 "sgo_player_id": cle}])
        scen = pd.DataFrame({"player": ["Anthony Edwards"], "proj_mpg": [240.0]})
        _, mins, _, _ = rolling_inputs(players, scen, "MIN", "CLE", box, teams)
        assert name not in set(mins.player) and len(mins) > 1          # the rest of MIN's bench is in


def test_the_rolling_hash_moves_with_the_opponent_context():
    from cold_start_usage.features import rolling_inputs_hash
    like = pd.DataFrame({"player": ["A"], "team_2025_26": ["AAA"], "team_2026_27": ["AAA"], "usg_pct": [20.0],
                         "games": [3], "mpg": [30.0], "ppg": [15.0], "verified": ["yes"], "source": ["rolling"]})
    mins = pd.DataFrame({"player": ["A"], "proj_mpg": [30.0]})
    a = rolling_inputs_hash(like, mins, {"pace_mult": 1.0, "def_points": 0.99})
    b = rolling_inputs_hash(like, mins, {"pace_mult": 1.0, "def_points": 0.97})
    assert a != b and len(a) == 16


def test_rolling_never_logs_a_player_it_could_not_map(storage, monkeypatch):
    from cold_start_usage import pipeline
    from cold_start_usage.pipeline import run_projections, snapshot_from_file
    from tests.fixtures.synthetic import FETCHED, TIP, events_response, synthetic_event
    real = pipeline.map_players

    def drop_one(names, *a, **k):
        mapping, problems = real(names, *a, **k)
        mapping.pop("Bam Adebayo", None)
        return mapping, problems + ["Bam Adebayo: no match on the event roster"]
    monkeypatch.setattr(pipeline, "map_players", drop_one)
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    table, _ = run_projections(storage, TIP.date(), FETCHED, {"MIA": "full_strength"}, source="rolling")
    assert table.loc[table.player == "Bam Adebayo", "player_id"].tolist() == ["UNMAPPED"]
    for t in ("projections", "extra_projections"):
        assert storage.query(f"SELECT count(*) n FROM {t} WHERE player_id IS NULL").n.iloc[0] == 0
        assert "Bam Adebayo" not in set(storage.query(f"SELECT player_name FROM {t}").player_name)


def test_a_replay_never_sees_roster_rows_stored_after_its_now(storage):
    from datetime import timedelta

    from cold_start_usage.pipeline import _roster, snapshot_from_file
    from tests.fixtures.synthetic import EVENT_ID, FETCHED, events_response, synthetic_event
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    before = _roster(storage, EVENT_ID, FETCHED)
    pid = before.player_id.iloc[0]
    storage.append("event_players", [{"ts": FETCHED + timedelta(hours=3), "event_id": EVENT_ID, "player_id": pid,
                                      "team_abbr": before.team_abbr.iloc[0], "name": "x", "status": "out"}])
    assert _roster(storage, EVENT_ID, FETCHED).set_index("player_id").status.get(pid) != "out"
    assert _roster(storage, EVENT_ID, FETCHED + timedelta(hours=4)).set_index("player_id").status.get(pid) == "out"


def test_a_projected_player_who_sat_counts_in_minutes_but_not_in_stat_accuracy():
    from datetime import date

    from cold_start_usage.evaluation import summarize, windows
    base = {"event_id": "E", "player_id": "P", "player": "P", "team": "AAA", "line": 10.5, "p_books": 0.5,
            "role": None, "in_season_rotation": True, "listed": True}
    rows = []
    for d, played in ((date(2026, 10, 26), True), (date(2026, 10, 28), True), (date(2026, 10, 28), False)):
        for stat in config.STATS + config.EXTRA_STATS:
            rows.append({**base, "et_date": d, "stat": stat, "season": 12.0, "rolling": 11.0, "books": 10.0,
                         "actual": 10.0 if played else np.nan, "season_min": 30.0, "rolling_min": 28.0,
                         "actual_min": 30.0 if played else 0.0, "played": played})
    df = pd.DataFrame(rows)
    s = summarize(df)
    assert s["accuracy"].set_index("stat").at["points", "n"] == 2
    m = s["minutes"].set_index("players")
    assert m.iloc[0].n == 3 and m.iloc[0].bias_season == pytest.approx(10.0) and m.loc["played only"].n == 2
    labels = [label for label, _ in windows(df)]
    assert labels[0].startswith("Out of sample") and labels[1].startswith("In-sample")


def test_shifts_flag_a_big_usage_change_on_enough_minutes():
    from cold_start_usage.shifts import shifts
    with Storage(":memory:") as s:
        store_box_scores(s, [_game("g1", "2026-10-21T23:00:00Z"), _game("g2", "2026-10-23T23:00:00Z")], datetime(2026, 10, 24))
        row = {"team_2025_26": "MIN", "team_2026_27": "MIN", "games": 70, "ppg": 20.0, "rpg": 5.0, "apg": 4.0,
               "fg3a_pg": 7.0, "fg3_pct": 36.0, "verified": "yes", "source": "src"}
        players = pd.DataFrame([{**row, "player": "Anthony Edwards", "sgo_player_id": "ANTHONY_EDWARDS_1_NBA",
                                 "usg_pct": 20.0, "mpg": 34.0}])
        df = shifts(s, datetime(2026, 10, 25, 23), players).set_index("player_id")
        ant = df.loc["ANTHONY_EDWARDS_1_NBA"]
        assert ant.games == 2 and ant.minutes >= 60 and ant.usg > 35 and ant.d_usg > 15
        assert ant.flagged and "usage +" in ant["flags"]
        assert ant.usg_prior < ant.usg_model < ant.usg and ant.gap > 0          # the shrinkage holds some back
        assert not df[~df.has_prior].flagged.any()                               # no prior row: never flagged
