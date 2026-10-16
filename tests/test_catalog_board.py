from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from cold_start_usage import catalog as cat
from cold_start_usage.board import build_board, rungs
from cold_start_usage.pipeline import snapshot_from_file
from cold_start_usage.players import name_key
from tests.fixtures.synthetic import FETCHED, events_response, synthetic_event


def split(name, team, usg, gp, mpg, ppg, fg3a=3.0, fg3pct=36.0):
    return {"name": name, "team": team, "usg": usg, "gp": gp, "mpg": mpg, "ppg": ppg, "fg3a": fg3a,
            "fg3pct": fg3pct, "min": gp * mpg, "pts": gp * ppg, "source": f"src/{team}", "key": name_key(name)}


def test_combine_lines_weights_traded_players():
    s = pd.DataFrame([split("Pat Traded", "AAA", 20.0, 30, 20.0, 10.0), split("Pat Traded", "BBB", 30.0, 10, 30.0, 20.0)])
    line = cat.combine_lines(s).iloc[0]
    assert line.games == 40 and line.team_2025_26 == "TOT" and line.teams_2025_26 == ("AAA", "BBB")
    assert line.usg_pct == pytest.approx((20 * 600 + 30 * 300) / 900, abs=0.01)   # minute-weighted
    assert line.ppg == pytest.approx((300 + 200) / 40, abs=0.01)


def test_fuzzy_name_bridge_handles_nicknames():
    bridge = cat.fuzzy_join_keys(pd.Series(["Alex Sarr", "Herbert Jones", "Nobody Here"]),
                                 pd.Series(["Alexandre Sarr", "Herb Jones", "Someone Else"]))
    assert bridge == {name_key("Alex Sarr"): name_key("Alexandre Sarr"),
                      name_key("Herbert Jones"): name_key("Herb Jones")}


def test_roster_precedence_override_then_moves_then_sgo_then_assumed():
    lines = cat.combine_lines(pd.DataFrame([split("A One", "AAA", 20, 50, 30, 15), split("B Two", "AAA", 20, 50, 30, 15),
                                            split("C Three", "AAA", 20, 50, 30, 15), split("D Four", "AAA", 20, 50, 30, 15)]))
    sgo = pd.DataFrame({"player_id": ["A_1", "B_1", "C_1"], "sgo_name": ["A One", "B Two", "C Three"],
                        "sgo_team": ["CCC", "CCC", "CCC"]})
    sgo["key"] = sgo.sgo_name.map(name_key)
    moves = pd.DataFrame({"player": ["B Two"], "from_team": ["AAA"], "to_team": ["BBB"]})
    moves["key"] = moves.player.map(name_key)
    overrides = pd.DataFrame({"player": ["A One"], "team": ["DDD"]})
    overrides["key"] = overrides.player.map(name_key)
    res, conflicts = cat.resolve_rosters(lines, sgo, moves, overrides)
    got = dict(zip(res.name, zip(res.team_2026_27, res.roster_source)))
    assert got == {"A One": ("DDD", "override"), "B Two": ("BBB", "moves"),
                   "C Three": ("CCC", "sgo"), "D Four": ("AAA", "assumed")}
    assert set(conflicts.name) == {"A One", "B Two"}                 # SGO disagreed with both


def test_unlisted_moves_are_not_offseason_departures():
    lines = cat.combine_lines(pd.DataFrame([split("Deadline Guy", "AAA", 25, 40, 30, 18),
                                            split("Summer Guy", "AAA", 25, 40, 30, 18)]))
    res = lines.assign(team_2026_27=["BBB", "BBB"], player_id=None)
    moves = pd.DataFrame({"key": [name_key("Summer Guy")], "from_team": ["AAA"], "to_team": ["BBB"]})
    prior = dict(zip(res.name, cat.prior_teams(res, pd.DataFrame([split("x", "AAA", 1, 1, 1, 1)]), moves)))
    assert prior == {"Deadline Guy": "BBB", "Summer Guy": "AAA"}


def test_auto_minutes_sum_to_240_with_cap():
    tp = pd.DataFrame({"player": [f"p{i}" for i in range(12)], "games": 60,
                       "mpg": [38, 37, 36, 34, 30, 28, 25, 22, 20, 18, 12, 9]})
    scen = cat.auto_minutes(tp)
    assert len(scen) == 10 and scen.proj_mpg.sum() == pytest.approx(240.0, abs=0.05)
    assert scen.proj_mpg.max() <= 37.0 + 1e-9
    # Starters keep last season's minutes (capped); the bench absorbs the rest.
    assert list(scen.proj_mpg.head(5)) == [37.0, 37.0, 36.0, 34.0, 30.0]
    assert scen.proj_mpg.iloc[5:].sum() == pytest.approx(66.0, abs=0.05)
    with pytest.raises(ValueError):
        cat.auto_minutes(tp.head(5))


def test_tiers():
    assert [cat.tier(u) for u in (31.0, 25.0, 24.9, 18.0, 17.9)] == ["high", "high", "medium", "medium", "low"]


def test_live_catalog_files_are_consistent():
    c = pd.read_csv(cat.config.DATA_DIR / "catalog" / "players.csv")
    assert not c.team.isin(cat.config.CATALOG_EXCLUDED_TEAMS).any()
    assert set(c.situation) <= {"arrival", "vacuum", "squeeze", "steady"}
    assert set(c.tier) <= {"high", "medium", "low"}
    giannis = c[c.player == "Giannis Antetokounmpo"].iloc[0]
    assert giannis.team == "MIA" and giannis.situation == "arrival" and giannis.prior_team == "MIL"
    assert c[c.player == "Klay Thompson"].team.iloc[0] == "MIA"           # manual override applied


def test_board_waits_then_fills_in_when_lines_post(storage):
    catalog = pd.DataFrame([{
        "tier": "high", "situation": "arrival", "team": "MIA", "player": "Giannis Antetokounmpo",
        "thesis": "New team (MIL -> MIA)", "proj": 32.0, "sd": 9.6, "ppg_2025_26": 27.6,
        "usg_change": 1.2, "scenario_source": "reviewed"}])
    waiting = build_board(catalog, storage, FETCHED)
    assert waiting.status.iloc[0] == "waiting for a line"
    assert waiting.fair_ladder.iloc[0].startswith("25+")          # Kalshi-style 5-point rungs
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    live = build_board(catalog, storage, FETCHED + timedelta(minutes=1))
    row = live.iloc[0]
    assert row.line == 29.5 and row.side == "over"
    assert row.status.startswith("READY") and row.contract == "30+ YES" and row.max_cents > 0
    assert "kalshi" in row.posted


def test_rungs_follow_kalshi_five_point_ladders():
    assert rungs(22.4) == [15, 20, 25]
    assert rungs(30.2) == [25, 30, 35]
    assert rungs(3.1) == [5, 10]


KALSHI_MARKETS = [
    {"ticker": "KXNBAPTS-26OCT21MINMIA-MIAGANTETOKOUNMPO34-30", "event_ticker": "KXNBAPTS-26OCT21MINMIA",
     "title": "Giannis Antetokounmpo: 30+ points", "floor_strike": 29.5, "strike_type": "greater",
     "yes_bid": 38, "yes_ask": 40, "no_bid": 59, "no_ask": 61, "volume": 250},
    {"ticker": "KXNBAPTS-26OCT21MINMIA-MIAGANTETOKOUNMPO34-35", "event_ticker": "KXNBAPTS-26OCT21MINMIA",
     "title": "Giannis Antetokounmpo: 35+ points", "yes_bid_dollars": "0.2100", "yes_ask_dollars": "0.2300",
     "no_bid_dollars": "0.7600", "no_ask_dollars": "0.7800"},
    {"ticker": "KXNBAPTS-X", "event_ticker": "KXNBAPTS-X", "title": "Total team points 220+"},
]


def test_kalshi_parse_handles_cents_and_dollars():
    from cold_start_usage.kalshi import parse_markets
    df = parse_markets(KALSHI_MARKETS)
    assert list(df.threshold) == [30, 35] and set(df.player) == {"Giannis Antetokounmpo"}
    assert df.yes_ask.tolist() == [40.0, 23.0] and df.no_ask.tolist() == [61.0, 78.0]


def test_kalshi_best_trade_roi_after_fee():
    from cold_start_usage.kalshi import best_trade, fee, parse_markets
    df = parse_markets(KALSHI_MARKETS)
    trade = best_trade({30: 0.52, 35: 0.25}, df, rate=0.07, min_edge=0.04)
    cost = 0.40 + fee(0.40, 0.07)
    assert trade["contract"] == "30+ YES" and trade["edge_pp"] == round(100 * (0.52 - cost), 1)
    assert trade["roi"] == pytest.approx((0.52 - cost) / cost, abs=1e-3)
    assert best_trade({30: 0.42, 35: 0.22}, df, rate=0.07, min_edge=0.04) is None   # nothing clears 4pp


def test_board_marks_kalshi_value_ready(storage):
    from cold_start_usage.kalshi import parse_markets
    catalog = pd.DataFrame([{
        "tier": "high", "situation": "arrival", "team": "MIA", "player": "Giannis Antetokounmpo",
        "thesis": "New team (MIL -> MIA)", "proj": 32.0, "sd": 9.6, "ppg_2025_26": 27.6,
        "usg_change": 1.2, "scenario_source": "reviewed"}])
    board = build_board(catalog, storage, FETCHED, kalshi=parse_markets(KALSHI_MARKETS))
    row = board.iloc[0]
    assert row.status.startswith("READY (Kalshi): buy 30+ YES @ 40c") and row.kalshi_roi > 0
    assert "30+ 40c" in row.kalshi
