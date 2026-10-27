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
    assert set(extra.stat) == set(config.EXTRA_STATS)
    # A rolling run is stale for a cron on the season source, so switching back re-projects.
    assert EVENT_ID in events_without_projections(storage, {EVENT_ID})
