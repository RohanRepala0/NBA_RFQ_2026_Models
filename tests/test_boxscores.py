"""Box scores from a saved SportsGameOdds results response (one overtime game, CLE vs MIN)."""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from cold_start_usage.boxscores import (backfill_from_raw, box_score_rows, overtimes, possessions,
                                        store_box_scores, usage_pct)
from cold_start_usage.pipeline import ingest_results
from cold_start_usage.storage import Storage

FIXTURE = Path(__file__).parent / "fixtures" / "sgo_results_ot_game.json"
NOW = datetime(2026, 10, 27, 14, 0)


@pytest.fixture
def game():
    return json.loads(FIXTURE.read_text())


def test_usage_matches_the_formula_by_hand():
    # Anthony Edwards in the overtime game: 33 FGA, 6 FTA, 5 TOV in 2469 s; MIN 100 FGA, 22 FTA, 18 TOV.
    by_hand = 100 * ((33 + 0.44 * 6 + 5) * (265 / 5)) / ((2469 / 60) * (100 + 0.44 * 22 + 18))
    assert usage_pct(33, 6, 5, 2469 / 60, 100, 22, 18, 265) == pytest.approx(by_hand)
    assert by_hand == pytest.approx(41.0, abs=0.1)
    assert usage_pct(3, 0, 0, 0.0, 100, 22, 18, 240) != usage_pct(3, 0, 0, 0.0, 100, 22, 18, 240)   # NaN


def test_parse_overtime_game(game):
    players, teams = box_score_rows(game, NOW, "test")
    assert overtimes(game) == 1
    assert {t["team"] for t in teams} == {"CLE", "MIN"}
    assert all(t["team_minutes"] == 265 for t in teams)
    cle = next(t for t in teams if t["team"] == "CLE")
    assert cle["home"] and cle["opponent"] == "MIN" and cle["pts"] == 127
    assert cle["possessions"] == pytest.approx(possessions(102, 24, 13, 10))
    ant = next(p for p in players if p["player_id"] == "ANTHONY_EDWARDS_1_NBA")
    assert ant["team"] == "MIN" and not ant["home"] and ant["played"]
    assert ant["minutes"] == pytest.approx(2469 / 60) and ant["fga"] == 33 and ant["tov"] == 5
    assert ant["usg_pct"] == pytest.approx(usage_pct(33, 6, 5, 2469 / 60, 100, 22, 18, 265))
    assert len(players) == len(game["players"])
    # Listed players play less than the team's minutes (the deep bench isn't listed) and never more.
    for t in teams:
        mine = sum(p["minutes"] or 0 for p in players if p["team"] == t["team"])
        assert mine == pytest.approx(t["listed_minutes"]) and mine <= t["team_minutes"] + 0.5


def test_team_totals_come_from_the_team_rows_not_the_listed_players(game):
    players, teams = box_score_rows(game, NOW, "test")
    cle = next(t for t in teams if t["team"] == "CLE")
    listed = sum(p["pts"] or 0 for p in players if p["team"] == "CLE")
    assert listed < cle["pts"] == 127


def test_a_listed_player_without_a_line_did_not_play(game):
    pid = "ANTHONY_EDWARDS_1_NBA"
    del game["results"]["game"][pid]
    players, _ = box_score_rows(game, NOW, "test")
    ant = next(p for p in players if p["player_id"] == pid)
    assert not ant["played"] and ant["minutes"] is None and ant["pts"] is None and ant["usg_pct"] is None


def test_a_line_without_seconds_played_still_counts_as_played(game):
    pid = "ANTHONY_EDWARDS_1_NBA"
    del game["results"]["game"][pid]["secondsPlayed"]
    players, _ = box_score_rows(game, NOW, "test")
    ant = next(p for p in players if p["player_id"] == pid)
    assert ant["played"] and ant["minutes"] is None and ant["pts"] is not None and ant["usg_pct"] is None


def test_a_game_that_is_not_final_stores_nothing(game):
    game["status"]["finalized"] = False
    assert box_score_rows(game, NOW, "test") == ([], [])


def test_storing_a_game_twice_adds_nothing(game, tmp_path):
    with Storage(":memory:") as s:
        first = store_box_scores(s, [game], NOW)
        again = store_box_scores(s, [copy.deepcopy(game)], NOW)
        assert first["games"] == 1 and first["players"] == len(game["players"])
        assert again == {"games": 0, "players": 0, "skipped": 1}
        assert s.count("team_box_scores") == 2 and s.count("box_scores") == len(game["players"])


def test_backfill_reads_saved_results_files_once(game, tmp_path):
    day = tmp_path / "2026-10-27"
    day.mkdir()
    (day / "142022_results_2026-10-26.json").write_text(json.dumps({"fetched_at": "x", "data": [game]}))
    (day / "120000_slate_2026-10-27.json").write_text(json.dumps({"fetched_at": "x", "data": [game]}))
    with Storage(":memory:") as s:
        c = backfill_from_raw(s, NOW, tmp_path)
        assert c["files"] == 1 and c["games"] == 1
        assert backfill_from_raw(s, NOW, tmp_path)["games"] == 0
        assert s.query("SELECT DISTINCT source FROM box_scores").source.tolist() == [
            "raw:2026-10-27/142022_results_2026-10-26.json"]


def test_grading_stores_box_scores_for_every_listed_player(game):
    with Storage(":memory:") as s:
        ingest_results(s, [game], NOW)            # no stored event or projection: results skip it
        assert s.count("results") == 0
        assert s.count("box_scores") == len(game["players"]) and s.count("team_box_scores") == 2
