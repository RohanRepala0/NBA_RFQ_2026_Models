"""Rebounds and assists next to points: the model, SportsGameOdds ingest and per-stat consensus,
the venue parsers, decisions and grouping per stat, the projection runs (scenario reuse and
fill-in), the explicit-ID guard and the storage migration. All offline."""
from __future__ import annotations

import copy
import dataclasses
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from cold_start_usage import config, polymarket_us
from cold_start_usage import catalog as cat
from cold_start_usage.consensus import Consensus, consensus_by_player
from cold_start_usage.decision import Context, evaluate_contract, pick_per_group, size_positions
from cold_start_usage.ingest import player_stat_results, player_stat_side, quote_rows
from cold_start_usage.kalshi import parse_markets
from cold_start_usage.pipeline import (events_without_projections, ingest_results, latest_projections,
                                       run_projections, snapshot_from_file)
from cold_start_usage.players import map_players
from cold_start_usage.storage import Storage
from cold_start_usage.usage_model import league_budget, load_players, project_scenario
from cold_start_usage.venues import Fetchers, kalshi_series_markets, scan
from tests.fixtures.synthetic import EVENT_ID, FETCHED, TIP, events_response, synthetic_event

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SGO = json.loads((FIXTURES / "sgo_multistat_bos_det.json").read_text())       # trimmed real BOS @ DET response
BOS_DET = "YcuJMzH3KxfKzxVKzSQs"
READ_AT = datetime(2026, 10, 19, 17, 32, 30)                                 # when it was fetched
DAY = TIP.date()


def points_only(body: dict) -> dict:
    body = copy.deepcopy(body)
    for ev in body["data"]:
        ev["odds"] = {k: v for k, v in ev["odds"].items() if v["statID"] == "points"}
    return body


# --- the model ------------------------------------------------------------------------------
def team(rows: list[tuple]) -> pd.DataFrame:
    """(player, usg, mpg, ppg, rpg, apg) -> a players table with every model column."""
    return pd.DataFrame([{"player": p, "team_2025_26": "AAA", "team_2026_27": "AAA", "usg_pct": u, "games": 60,
                          "mpg": m, "ppg": pts, "rpg": r, "apg": a, "verified": "yes", "source": "src"}
                         for p, u, m, pts, r, a in rows])


ROSTER = team([("Big", 20, 34, 15, 12.0, 2.0), ("Guard", 25, 34, 20, 4.0, 8.0), ("Wing", 20, 34, 14, 5.0, 3.0),
               ("Forward", 18, 30, 11, 6.0, 2.0), ("Guard2", 22, 30, 15, 3.0, 5.0), ("Bench", 16, 20, 7, 3.0, 2.0),
               ("Bench2", 15, 20, 6, 2.5, 1.5), ("Reserve", 15, 28, 8, 3.0, 2.0)])


def mins(**m) -> pd.DataFrame:
    return pd.DataFrame({"player": list(m), "proj_mpg": list(m.values())})


FULL = mins(Big=36, Guard=36, Wing=34, Forward=32, Guard2=32, Bench=24, Bench2=24, Reserve=22)


def test_rebound_and_assist_budget_identity_at_rho_one():
    res = project_scenario(ROSTER, FULL, dataclasses.replace(config.MODEL, rho_reb=1.0, rho_ast=1.0))
    assert res.reb_proj.sum() == pytest.approx(league_budget("rebounds"), rel=1e-9)   # the team total is the budget
    assert res.ast_proj.sum() == pytest.approx(league_budget("assists"), rel=1e-9)
    assert 42 < league_budget("rebounds") < 45 and 25 < league_budget("assists") < 28
    raw = project_scenario(ROSTER, FULL, dataclasses.replace(config.MODEL, rho_reb=0.0, rho_ast=0.0))
    assert (raw.reb_scale_k == 1.0).all()                                               # rho = 0: last season's rates
    assert raw.reb_proj.iloc[0] == pytest.approx(12.0 / 34 * 36)


def test_a_rebounder_leaving_lifts_the_others_by_less_than_one_for_one():
    with_big = project_scenario(ROSTER, FULL).set_index("player")
    without = project_scenario(ROSTER, mins(Guard=36, Wing=34, Forward=32, Guard2=32, Bench=36, Bench2=36,
                                            Reserve=34)).set_index("player")
    for p in ("Guard", "Wing", "Forward"):
        assert without.loc[p, "reb_proj"] > with_big.loc[p, "reb_proj"]                 # vacuum: teammates' boards rise
    assert without.reb_scale_k.iloc[0] > with_big.reb_scale_k.iloc[0]
    assert without.reb_proj.sum() < with_big.reb_proj.sum()                             # diminishing returns (rho < 1)
    assert with_big.loc["Big", "reb_sd"] == pytest.approx((1.30 * with_big.loc["Big", "reb_proj"]) ** 0.5)


def test_missing_or_unverified_rates_blank_that_stat_only():
    base = project_scenario(ROSTER.drop(columns=["rpg", "apg"]), FULL)
    assert base.reb_proj.isna().all() and base.ast_proj.isna().all() and base.ppg_proj.notna().all()
    holes = ROSTER.copy()
    holes.loc[holes.player == "Bench", "rpg"] = float("nan")
    holes.loc[holes.player == "Reserve", "verified"] = "no"
    res = project_scenario(holes, FULL).set_index("player")
    pd.testing.assert_series_equal(res.ppg_proj.drop("Reserve"), base.set_index("player").ppg_proj.drop("Reserve"))
    assert pd.isna(res.loc["Bench", "reb_proj"]) and pd.notna(res.loc["Bench", "ast_proj"])
    assert res.loc[["Reserve"], ["ppg_proj", "reb_proj", "ast_proj"]].isna().all().all()
    # A player with no rate still takes minutes: he counts at the league rate, so k barely moves.
    assert res.reb_scale_k.iloc[0] == pytest.approx(project_scenario(ROSTER, FULL).reb_scale_k.iloc[0], rel=0.05)


# --- SportsGameOdds: ingest and consensus per stat --------------------------------------------
def test_multi_stat_event_ingests_every_stat_and_reads_combos_under_our_names():
    ev = SGO["data"][0]
    rows = pd.DataFrame(quote_rows(ev, READ_AT, "open"))
    assert set(rows.stat) == {"points", "rebounds", "assists"}
    assert rows.groupby("stat").player_id.nunique().to_dict() == {"assists": 5, "points": 6, "rebounds": 6}
    assert all(r.odd_id.startswith(r.stat + "-") for r in rows.itertuples())
    no_stat = {"byBookmaker": {}}                                     # the oddID regex path (no statID field)
    assert player_stat_side("rebounds-CADE_CUNNINGHAM_1_NBA-game-ou-under", no_stat) == (
        "CADE_CUNNINGHAM_1_NBA", "rebounds", "under")
    assert player_stat_side("points+rebounds+assists-CADE_CUNNINGHAM_1_NBA-game-ou-over", no_stat) == (
        "CADE_CUNNINGHAM_1_NBA", "pra", "over")                       # shadow stats, under our names
    assert player_stat_side("threePointersMade-CADE_CUNNINGHAM_1_NBA-game-ou-under", no_stat) == (
        "CADE_CUNNINGHAM_1_NBA", "threes", "under")
    combo = {"statID": "points+rebounds", "periodID": "game", "betTypeID": "ou", "sideID": "over", "playerID": "X_1_NBA"}
    assert player_stat_side("x", combo) == ("X_1_NBA", "pr", "over")
    assert player_stat_side("x", combo | {"statID": "assists", "periodID": "1q"}) is None
    assert player_stat_side("x", combo | {"statID": "dunks"}) is None


def test_rebounds_odds_never_move_the_points_consensus(storage):
    other = Storage(":memory:")
    snapshot_from_file(storage, SGO, READ_AT)
    snapshot_from_file(other, points_only(SGO), READ_AT)
    with_all = consensus_by_player(storage, BOS_DET, as_of=READ_AT, before=READ_AT)
    alone = consensus_by_player(other, BOS_DET, as_of=READ_AT, before=READ_AT)
    assert with_all.keys() == alone.keys() and repr(with_all) == repr(alone)         # byte-identical
    assert consensus_by_player(other, BOS_DET, as_of=READ_AT, before=READ_AT, stat="rebounds") == {}
    reb = consensus_by_player(storage, BOS_DET, as_of=READ_AT, before=READ_AT, stat="rebounds")
    ausar = reb["AUSAR_THOMPSON_1_NBA"]
    assert ausar.stat == "rebounds" and ausar.line == 6.5 and ausar.n_books == 4 and ausar.abstain_reason is None
    assert 6.0 < ausar.mean < 7.2 and ausar.p_over_at(6.5) == pytest.approx(ausar.p_over)
    ast = consensus_by_player(storage, BOS_DET, as_of=READ_AT, before=READ_AT, stat="assists")
    assert "MITCHELL_ROBINSON_1_NBA" not in ast                       # odds without any book quote
    assert 8.5 < ast["CADE_CUNNINGHAM_1_NBA"].mean < 10.0
    other.close()


def test_results_parse_all_three_stats(storage):
    snapshot_from_file(storage, SGO, READ_AT)
    storage.append("projections", [{"ts": READ_AT, "event_id": BOS_DET, "player_id": p, "team": "DET",
                                    "stat": "points", "mean": 10.0, "model_version": config.MODEL_VERSION}
                                   for p in ("CADE_CUNNINGHAM_1_NBA", "AUSAR_THOMPSON_1_NBA")])
    final = copy.deepcopy(SGO["data"][0])
    final["status"]["finalized"] = True
    final["results"] = {"game": {"home": {"points": 120}, "CADE_CUNNINGHAM_1_NBA": {"points": 31, "rebounds": 6,
                                                                                     "assists": 11},
                                 "AUSAR_THOMPSON_1_NBA": {"points": 9, "rebounds": 8}}}
    assert player_stat_results(final)["AUSAR_THOMPSON_1_NBA"] == {"points": 9.0, "rebounds": 8.0, "pr": 17.0}
    assert player_stat_results(final)["CADE_CUNNINGHAM_1_NBA"]["pra"] == 48.0       # combos sum their parts
    n, _ = ingest_results(storage, [final], READ_AT + timedelta(days=1))
    res = storage.query("SELECT * FROM results ORDER BY player_id").set_index("player_id")
    assert n == 2 and res.loc["CADE_CUNNINGHAM_1_NBA", ["actual_points", "actual_rebounds", "actual_assists"]].tolist() == [
        31, 6, 11]
    assert pd.isna(res.loc["AUSAR_THOMPSON_1_NBA", "actual_assists"])


# --- venue parsers ------------------------------------------------------------------------------
def kalshi(ticker: str, title: str, floor: float, bid: float, ask: float, size: float = 200) -> dict:
    """Shaped like the live KXNBAREB / KXNBAAST markets for BOS @ DET on Oct 20."""
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 2)[0], "title": title, "floor_strike": floor,
            "strike_type": "greater", "status": "active", "yes_bid_dollars": f"{bid:.4f}", "yes_ask_dollars": f"{ask:.4f}",
            "no_bid_dollars": f"{1 - ask:.4f}", "no_ask_dollars": f"{1 - bid:.4f}", "yes_ask_size_fp": f"{size:.2f}",
            "yes_bid_size_fp": f"{size:.2f}", "volume_fp": "41.58", "occurrence_datetime": "2026-10-20T22:00:00Z"}


REB_ASK = [kalshi("KXNBAREB-26OCT20BOSDET-DETATHOMPSON9-6", "Ausar Thompson: 6+ rebounds", 5.5, 0.55, 0.63),
           kalshi("KXNBAREB-26OCT20BOSDET-DETATHOMPSON9-8", "Ausar Thompson: 8+ rebounds", 7.5, 0.30, 0.36),
           kalshi("KXNBAAST-26OCT20BOSDET-DETCCUNNINGHAM2-10", "Cade Cunningham: 10+ assists", 9.5, 0.42, 0.46)]


def test_kalshi_takes_the_stat_from_the_series_and_checks_the_title():
    bad = [kalshi("KXNBAREB-26OCT20BOSDET-BOSDWHITE9-4", "Derrick White: 4+ assists", 3.5, 0.5, 0.55),   # wrong word
           kalshi("KXNBA3PT-26OCT20BOSDET-BOSDWHITE9-2", "Derrick White: 2+ threes", 1.5, 0.5, 0.55),     # a shadow stat
           kalshi("KXNBAAST-26OCT20BOSDET-BOSDWHITE9-4", "Derrick White: 4+", 3.5, 0.5, 0.55)]            # sub-title form
    df = parse_markets(REB_ASK + bad)
    assert df.stat.fillna("-").tolist() == ["rebounds", "rebounds", "assists", "rebounds", "threes", "assists"]
    assert df.parse_error.iloc[:3].isna().all() and df.threshold.iloc[:3].tolist() == [6, 8, 10]
    assert "title says 'assists'" in df.parse_error.iloc[3] and pd.isna(df.parse_error.iloc[4])
    pra = parse_markets([kalshi("KXNBAPRA-26OCT20BOSDET-BOSDWHITE9-35", "Derrick White: 35+ points, rebounds, and assists",
                                34.5, 0.2, 0.25),
                         kalshi("KXNBAPRA-26OCT20BOSDET-BOSDWHITE9-30", "Derrick White: 30+ points", 29.5, 0.2, 0.25),
                         kalshi("KXNBA9ZZ-26OCT20BOSDET-BOSDWHITE9-2", "Derrick White: 2+ dunks", 1.5, 0.5, 0.55)])
    assert pra.stat.fillna("-").tolist() == ["pra", "pra", "-"] and pd.isna(pra.parse_error.iloc[0])
    assert "title says 'points'" in pra.parse_error.iloc[1] and "unknown series 'KXNBA9ZZ'" in pra.parse_error.iloc[2]
    assert pd.isna(df.parse_error.iloc[5])                           # no stat word: the series decides
    assert df.team.iloc[0] == "DET" and df.player.iloc[0] == "Ausar Thompson"


def test_polymarket_us_reads_points_rebounds_and_assists_from_real_markets():
    event = json.loads((FIXTURES / "pmus_okc_sa_props.json").read_text())
    df = polymarket_us.prop_markets(event)
    assert df.stat.value_counts().to_dict() == {"rebounds": 3, "assists": 3, "points": 2}     # threes and totals ignored
    assert df.parse_error.isna().all()
    wemby = df[(df.player == "Victor Wembanyama") & (df.threshold == 12)].iloc[0]
    assert (wemby.stat, wemby.line, wemby.team, wemby.yes_ask, wemby.no_ask) == ("rebounds", 11.5, "SAS", 0.54, 0.51)
    fox = df[(df.player == "De'Aaron Fox") & (df.stat == "assists")].sort_values("threshold")
    assert fox.threshold.tolist() == [5, 10] and set(fox.team) == {"SAS"}
    assert set(polymarket_us.points_markets(event).stat) == {"points"}
    wrong = copy.deepcopy(event)
    m = next(x for x in wrong["markets"] if x["sportsMarketType"] == "basketball_player_assists")
    m["sportsMarketType"] = "basketball_player_rebounds"                        # "... 5 assists" under a rebounds type
    assert "sportsMarketType" in polymarket_us.prop_markets(wrong).parse_error.dropna().iloc[0]


# --- decisions per stat ---------------------------------------------------------------------------
NOW = datetime(2026, 10, 21, 22, 30)


def reb_cons(mean=8.0, line=7.5, stat="rebounds"):
    return Consensus(event_id="E", player_id="P", as_of=NOW, snapshot_ts=NOW - timedelta(minutes=1), mean=mean,
                     line=line, p_over=None, books=[object()] * 3, stat=stat)


def quote(ask, line=7.5, threshold=8, stat="rebounds", **kw):
    q = {"venue": "kalshi", "ticker": "T", "player": "X", "stat": stat, "line": line, "threshold": threshold,
         "yes_ask": ask, "yes_bid": ask - 0.02, "no_ask": 1 - ask + 0.02, "no_bid": 1 - ask, "yes_ask_size": 100,
         "no_ask_size": 100, "quote_ts": NOW, "parse_error": None}
    return q | kw


def rctx(**kw):
    base = dict(now=NOW, tip=NOW + timedelta(hours=1), event_id="E", game="A @ B", player_id="P", stat="rebounds",
                consensus=reb_cons(), model_mean=8.0)
    return Context(**(base | kw))


def test_rebound_contracts_are_priced_off_the_count_distribution():
    from cold_start_usage import distributions as dist
    r = evaluate_contract(quote(0.40), "YES", rctx())
    assert r["stat"] == "rebounds" and r["contract"] == "8+ REB YES"
    assert r["p_market"] == pytest.approx(dist.robust_p("rebounds", 8.0, 7.5, "YES")[0])
    assert r["decision"] == "actionable"
    assert evaluate_contract(quote(0.40, threshold=None), "NO", rctx())["contract"] == "under 7.5 REB"
    assert evaluate_contract(quote(0.40, stat="points"), "YES", Context(now=NOW, tip=NOW + timedelta(hours=1),
                                                                        player_id="P"))["contract"] in ("8+ YES",)
    # Tail gate on the centre count model: 14+ boards on a mean of 8 is about 6%.
    tail = evaluate_contract(quote(0.05, line=13.5, threshold=14), "YES", rctx())
    assert tail["reason"].startswith("tail rung: market P(YES) 6%")
    # The blend's gap is judged in rebounds SDs (sqrt(1.3 x 8) = 3.2): +1.5 blends, +3.0 is flagged.
    near = evaluate_contract(quote(0.40), "YES", rctx(model_mean=9.5))
    assert near["w_model"] == config.W_MODEL and near["blend_mean"] == pytest.approx(8.3)
    far = evaluate_contract(quote(0.40), "YES", rctx(model_mean=11.0))
    assert far["w_model"] == 0.0 and "model +3.0 reb from market" in far["reason"]
    # Never one stat's price off another's quote or consensus.
    assert evaluate_contract(quote(0.40, stat="assists"), "YES", rctx())["reason"].startswith("unparsed")
    assert evaluate_contract(quote(0.40), "YES", rctx(consensus=reb_cons(stat="points")))["reason"].startswith(
        "no consensus")


def test_a_smaller_repricing_frees_nothing_for_other_picks():
    from cold_start_usage.decision import Exposure
    # The slate is at its 3% cap; 0.5% of it is his rebounds ticket. This scan re-prices that ticket
    # smaller (only 5 contracts left at the edge) and finds a new pick on someone else.
    used = Exposure(slate=0.03, game={"E": 0.01}, group={("E", "P"): 0.005},
                    issued={("E", "P", "rebounds"): 0.005})
    rows = pd.DataFrame([act("P", "rebounds", "8+ REB YES", 0.09, 0.40, "0.40:5"),
                         act("Q", "points", "20+ YES", 0.05, 0.49, "0.49:500")])
    out = size_positions(rows, 1000.0, used).set_index("player")
    assert out.loc["P", "decision"] == "actionable" and out.loc["P", "stake_usd"] < 5.0   # re-priced in place
    assert out.loc["Q", "decision"] == "watch" and "cap" in out.loc["Q", "reason"]       # Rohan may hold the $5


def test_rebounds_need_two_more_points_of_edge():
    from cold_start_usage.decision import tau_for
    assert tau_for("kalshi", 5, "points") == tau_for("kalshi", 5, "assists") == pytest.approx(0.04)
    assert tau_for("kalshi", 5, "rebounds") == pytest.approx(0.06)
    assert tau_for("polymarket_us", 2, "rebounds") == pytest.approx(0.07)          # plus the thin-consensus 1pp
    assert evaluate_contract(quote(0.40), "YES", rctx(model_mean=9.5))["tau"] == pytest.approx(0.06)


def act(player, stat, contract, ev, ask, ladder):
    return {"event_id": "E", "player_id": player, "event_ticker": "K", "player": player, "venue": "kalshi",
            "stat": stat, "contract": contract, "decision": "actionable", "ev_blend": ev, "p_blend": ask + ev + 0.02,
            "p_market": ask + ev + 0.02, "ask": ask, "cost": ask + 0.02, "tau": 0.04, "fee_rate": None,
            "size_at_edge": sum(float(x.split(":")[1]) for x in ladder.split(";")), "ladder": ladder}


def test_one_pick_per_player_game_and_stat_and_a_shared_cap():
    rows = pd.DataFrame([act("P", "points", "20+ YES", 0.08, 0.49, "0.49:500"),
                         act("P", "rebounds", "8+ REB YES", 0.07, 0.40, "0.40:500"),
                         act("P", "rebounds", "10+ REB YES", 0.05, 0.20, "0.20:500")])
    picked = pick_per_group(rows)
    assert picked.decision.tolist() == ["actionable", "actionable", "abstain"]
    assert "already has a pick: kalshi 8+ REB YES" in picked.reason.iloc[2]
    held = pick_per_group(rows, filled={("E", "P", "rebounds")})
    assert held.decision.tolist() == ["actionable", "abstain", "abstain"]
    assert "already holding this player-game (rebounds)" in held.reason.iloc[1]
    sized = size_positions(picked, bankroll=1000.0)
    live = sized[sized.decision == "actionable"]
    assert len(live) == 2 and live.stake_usd.sum() <= 1000 * config.MAX_BET_FRAC + 1e-9   # 0.5% across his stats


def test_a_pick_blocked_by_the_shared_player_cap_names_that_cap():
    from cold_start_usage.decision import Exposure
    row = act("P", "rebounds", "8+ REB YES", 0.07, 0.40, "0.40:500")
    used = Exposure(slate=0.005, game={"E": 0.005}, group={("E", "P"): 0.005})   # his points pick took 0.5%
    out = size_positions(pd.DataFrame([row]), 1000.0, used)
    assert out.decision.iloc[0] == "watch" and "per-player cap" in out.reason.iloc[0]
    full = size_positions(pd.DataFrame([row]), 1000.0, Exposure(slate=0.03))
    assert "game or slate cap" in full.reason.iloc[0]


def test_a_repeat_replaces_its_ticket_while_his_other_stats_share_what_is_left():
    from cold_start_usage.decision import Exposure
    # An earlier scan's rebounds ticket took 0.4% of his 0.5% player-game cap.
    used = Exposure(slate=0.004, game={"E": 0.004}, group={("E", "P"): 0.004},
                    issued={("E", "P", "rebounds"): 0.004})
    reb = size_positions(pd.DataFrame([act("P", "rebounds", "8+ REB YES", 0.07, 0.40, "0.40:500")]), 1000.0, used)
    assert reb.decision.iloc[0] == "actionable" and 4.0 < reb.stake_usd.iloc[0] <= 5.0 + 1e-9   # replaces it
    pts = size_positions(pd.DataFrame([act("P", "points", "20+ YES", 0.08, 0.49, "0.49:500")]), 1000.0, used)
    assert (pts.stake_usd.iloc[0] or 0.0) <= 1.0 + 1e-9                                        # only 0.1% left


# --- projection runs ---------------------------------------------------------------------------------
def players_with_rates() -> pd.DataFrame:
    p = load_players()
    return p.assign(rpg=(p.ppg / 3).round(2), apg=(p.ppg / 5).round(2))


def test_projections_are_logged_and_read_per_stat(storage):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    run_projections(storage, DAY, FETCHED, {"MIA": "full_strength"}, players=players_with_rates())
    lp = latest_projections(storage, EVENT_ID, FETCHED + timedelta(minutes=1))
    assert set(lp.stat) == set(config.STATS) and lp.groupby("stat").size().nunique() == 1
    giannis = lp[lp.player_name == "Giannis Antetokounmpo"].set_index("stat")
    assert giannis.loc["rebounds", "mean"] > 0 and giannis.loc["points", "mean"] > giannis.loc["assists", "mean"]
    # Points rows are the same numbers as a run on a table without the new columns.
    bare = Storage(":memory:")
    snapshot_from_file(bare, events_response([synthetic_event()]), FETCHED)
    run_projections(bare, DAY, FETCHED, {"MIA": "full_strength"})
    pts = lambda s: s.query("SELECT player_id, mean, sd FROM projections WHERE stat = 'points' ORDER BY 1")  # noqa: E731
    pd.testing.assert_frame_equal(pts(storage), pts(bare))
    nan = bare.query("SELECT count(*) n FROM projections WHERE stat = 'rebounds' AND mean IS NULL").n.iloc[0]
    assert nan == 11                                                  # no rates: logged, mean NULL
    bare.close()


def test_a_scenario_named_for_one_team_keeps_the_others(storage):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    run_projections(storage, DAY, FETCHED, {"MIA": "giannis_out"})
    _, msgs = run_projections(storage, DAY, FETCHED + timedelta(minutes=5), {"TOR": "kawhi_out"})
    lp = latest_projections(storage, EVENT_ID, FETCHED + timedelta(minutes=6))
    assert set(lp.scenario) == {"giannis_out"} and pd.Timestamp(lp.ts.max()) == FETCHED + timedelta(minutes=5)
    assert any("keeping scenario giannis_out" in m for m in msgs)
    fresh = Storage(":memory:")
    snapshot_from_file(fresh, events_response([synthetic_event()]), FETCHED)
    _, msgs = run_projections(fresh, DAY, FETCHED, {})
    assert any("using full_strength" in m for m in msgs)               # no earlier run: full strength
    fresh.close()


def test_cron_fill_in_reruns_stale_runs_with_their_scenario(storage):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    # A run from before rebounds and assists: points only, no stat column value, the old model.
    storage.append("projections", [{"ts": FETCHED - timedelta(hours=1), "event_id": EVENT_ID, "player_id": "BAM_ADEBAYO_1_NBA",
                                    "player_name": "Bam Adebayo", "team": "MIA", "scenario": "giannis_out", "mean": 22.0,
                                    "sd": 6.6, "model_version": "usage-squeeze-1.0"}])
    assert latest_projections(storage, EVENT_ID, FETCHED).stat.tolist() == ["points"]          # NULL reads as points
    assert events_without_projections(storage, {EVENT_ID}) == {EVENT_ID}
    run_projections(storage, DAY, FETCHED, {}, event_ids={EVENT_ID})
    lp = latest_projections(storage, EVENT_ID, FETCHED)
    assert set(lp.scenario) == {"giannis_out"} and set(lp.model_version) == {config.MODEL_VERSION}
    assert set(lp.stat) == set(config.STATS)
    assert events_without_projections(storage, {EVENT_ID}) == set()
    # Current version but a stat short (say a run logged before a stat was added): re-run too.
    storage.append("projections", [{"ts": FETCHED + timedelta(minutes=1), "event_id": EVENT_ID, "player_id": "BAM_ADEBAYO_1_NBA",
                                    "team": "MIA", "scenario": "giannis_out", "stat": "points", "mean": 22.0,
                                    "model_version": config.MODEL_VERSION}])
    assert events_without_projections(storage, {EVENT_ID}) == {EVENT_ID}


# --- player IDs, the catalog bridge, Kalshi series failures --------------------------------------------
def test_an_explicit_id_shared_by_two_players_is_refused():
    cands = pd.DataFrame({"player_id": ["RON_HARPER_JR_1_NBA", "RON_HOLLAND_1_NBA"], "name": ["Ron Harper Jr.", "Ron Holland"],
                          "team_abbr": ["BOS", "DET"]})
    explicit = {"Ron Harper Jr.": "RON_HARPER_JR_1_NBA", "Ronald Holland II": "RON_HARPER_JR_1_NBA"}
    out, problems = map_players(["Ronald Holland II", "Ron Harper Jr."], cands, None, explicit, overrides={})
    assert out == {"Ronald Holland II": None, "Ron Harper Jr.": "RON_HARPER_JR_1_NBA"}    # name match only
    assert any("RON_HARPER_JR_1_NBA is given to Ron Harper Jr., Ronald Holland II" in p for p in problems)
    bridge = cat.fuzzy_join_keys(pd.Series(["Ronald Holland II"]), pd.Series(["Ron Harper Jr.", "Ron Holland"]))
    assert bridge == {"ronaldholland": "ronholland"}                   # the suffix is not a last name


def test_live_players_csv_has_no_shared_ids():
    from cold_start_usage.players import duplicate_ids
    p = pd.read_csv(config.DATA_DIR / "players_2025_26.csv")
    assert duplicate_ids(dict(zip(p.player, p.sgo_player_id))) == {}
    assert p.set_index("player").loc["Ronald Holland II", "sgo_player_id"] == "RON_HOLLAND_1_NBA"


def test_one_kalshi_series_failing_keeps_the_others():
    errors = []

    def read(series):
        if series == "KXNBAREB":
            raise RuntimeError("429")
        return [{"ticker": f"{series}-X"}]
    assert [m["ticker"] for m in kalshi_series_markets(read, errors)] == [
        f"{s}-X" for s in config.KALSHI_SERIES.values() if s != "KXNBAREB"]
    assert errors == ["kalshi KXNBAREB: RuntimeError: 429"]
    with pytest.raises(RuntimeError):
        kalshi_series_markets(lambda s: (_ for _ in ()).throw(RuntimeError("down")), [])


# --- the scan, end to end, on the real BOS @ DET response ------------------------------------------------
def test_scan_decides_rebounds_and_assists_against_their_own_consensus(storage):
    snapshot_from_file(storage, SGO, READ_AT)
    now = READ_AT + timedelta(minutes=1)
    df = scan(storage, date(2026, 10, 20), now, Fetchers(kalshi_markets=lambda: REB_ASK), tag="t-6h")
    assert len(df) == 6 and set(df.stat) == {"rebounds", "assists"}
    by = {(r.ticker, r.side): r for r in df.itertuples()}
    six = by[("KXNBAREB-26OCT20BOSDET-DETATHOMPSON9-6", "YES")]
    assert six.contract == "6+ REB YES" and six.consensus_line == 6.5 and six.player_id == "AUSAR_THOMPSON_1_NBA"
    cade = by[("KXNBAAST-26OCT20BOSDET-DETCCUNNINGHAM2-10", "NO")]
    assert cade.contract == "10+ AST NO" and 8.5 < cade.consensus_mean < 10
    snaps = storage.query("SELECT stat, count(*) n FROM venue_snapshots GROUP BY 1 ORDER BY 1")
    assert dict(zip(snaps.stat, snaps.n)) == {"assists": 1, "rebounds": 2}
    assert set(storage.query("SELECT DISTINCT stat FROM venue_signals").stat) == {"rebounds", "assists"}


# --- storage migration -------------------------------------------------------------------------------------
OLD_SCHEMA = {
    "odds_snapshots": "ts TIMESTAMP, event_id VARCHAR, odd_id VARCHAR, player_id VARCHAR, side VARCHAR, book VARCHAR, "
                      "book_role VARCHAR, line DOUBLE, odds_american DOUBLE, available BOOLEAN, is_main_line BOOLEAN, "
                      "quote_ts TIMESTAMP, snapshot_tag VARCHAR",
    "projections": "ts TIMESTAMP, event_id VARCHAR, player_id VARCHAR, player_name VARCHAR, team VARCHAR, "
                   "new_team BOOLEAN, scenario VARCHAR, mean DOUBLE, sd DOUBLE, proj_mpg DOUBLE, usg_proj DOUBLE, "
                   "inputs_hash VARCHAR, model_version VARCHAR",
    "results": "ts TIMESTAMP, event_id VARCHAR, player_id VARCHAR, actual_points DOUBLE",
}


def test_an_old_schema_database_migrates_additively(tmp_path):
    path = tmp_path / "old.duckdb"
    con = duckdb.connect(str(path))
    for table, ddl in OLD_SCHEMA.items():
        con.execute(f"CREATE TABLE {table} ({ddl})")
    t = "2026-10-21 22:25:00"
    for book, side, odds in (("draftkings", "over", -110), ("draftkings", "under", -110), ("betmgm", "over", -105),
                             ("betmgm", "under", -115)):
        con.execute("INSERT INTO odds_snapshots VALUES (?, 'E', ?, 'P', ?, ?, 'reference', 24.5, ?, true, true, ?, 'open')",
                    [t, f"points-P-game-ou-{side}", side, book, odds, t])
    con.execute(f"INSERT INTO projections VALUES ('{t}', 'E', 'P', 'Pat', 'MIA', false, 'full_strength', 25.0, 7.5, "
                "34, 25, 'h', 'usage-squeeze-1.0')")
    con.execute(f"INSERT INTO results VALUES ('{t}', 'E', 'P', 30)")
    con.close()
    with Storage(path) as s:
        assert s.count("odds_snapshots") == 4 and s.count("projections") == 1 and s.count("results") == 1   # kept
        for table in ("odds_snapshots", "projections", "signals", "venue_snapshots", "venue_signals"):
            assert "stat" in s.query(f"SELECT * FROM {table} LIMIT 0").columns
        assert {"actual_rebounds", "actual_assists"} <= set(s.query("SELECT * FROM results").columns)
        assert s.query("SELECT stat FROM odds_snapshots").stat.isna().all()                   # old rows: NULL
        as_of = datetime(2026, 10, 21, 22, 30)
        c = consensus_by_player(s, "E", as_of=as_of)["P"]                                   # NULL reads as points
        assert c.stat == "points" and c.n_books == 2 and c.line == 24.5
        assert consensus_by_player(s, "E", as_of=as_of, stat="rebounds") == {}
        assert latest_projections(s, "E", as_of).stat.tolist() == ["points"]


def test_a_shadow_stat_is_priced_against_its_own_books_and_never_becomes_a_ticket(storage, monkeypatch):
    from cold_start_usage.venues import issued_tickets
    monkeypatch.setattr(config, "bankroll_usd", lambda: 5000.0)
    snapshot_from_file(storage, SGO, READ_AT)
    odds = [{"ts": READ_AT, "event_id": BOS_DET, "odd_id": f"threePointersMade-AUSAR_THOMPSON_1_NBA-game-ou-{side}",
             "player_id": "AUSAR_THOMPSON_1_NBA", "stat": "threes", "side": side, "book": book, "book_role": "reference",
             "line": 1.5, "odds_american": price, "available": True, "is_main_line": True, "quote_ts": READ_AT,
             "snapshot_tag": "open"}
            for book in ("draftkings", "betmgm", "caesars") for side, price in (("over", -150), ("under", 120))]
    storage.append("odds_snapshots", odds)
    cheap = kalshi("KXNBA3PT-26OCT20BOSDET-DETATHOMPSON9-2", "Ausar Thompson: 2+ threes", 1.5, 0.44, 0.48)
    df = scan(storage, date(2026, 10, 20), READ_AT + timedelta(minutes=1),
              Fetchers(kalshi_markets=lambda: REB_ASK + [cheap]), tag="t-6h", bankroll=5000.0)
    yes = df[(df.ticker == cheap["ticker"]) & (df.side == "YES")].iloc[0]
    assert yes.stat == "threes" and 0.5 < yes.p_market < 0.65 and yes.consensus_line == 1.5
    assert yes.decision == "shadow", yes.reason
    assert yes.reason.startswith("shadow, would be actionable") and pd.isna(yes.stake_usd)
    logged = storage.query("SELECT decision, stake_usd FROM venue_signals WHERE stat = 'threes'")
    assert set(logged.decision) <= {"shadow", "abstain"} and logged.stake_usd.isna().all()
    assert "threes" not in set(issued_tickets(storage, date(2026, 10, 20), READ_AT + timedelta(minutes=2)).stat)
    assert set(df[df.stat == "rebounds"].decision) <= {"actionable", "watch", "abstain"}        # the real stats as before


def test_a_kalshi_outage_on_the_real_stats_keeps_the_checkpoint_open_whatever_the_shadow_series_do():
    def read(series):
        if series in ("KXNBAPTS", "KXNBAREB", "KXNBAAST"):
            raise RuntimeError("429")
        return []
    with pytest.raises(RuntimeError):
        kalshi_series_markets(read, [])


def test_shadow_settings_never_move_the_real_stats_config_hash():
    from cold_start_usage.decision import config_hash
    assert config_hash() == "377859dd66fc"                   # as before the shadow stats were added
    assert config_hash(shadow=True) != config_hash()


def test_kalshi_reads_every_spelling_of_threes():
    rows = parse_markets([kalshi(f"KXNBA3PT-26OCT20BOSDET-BOSDWHITE9-{i}", f"Derrick White: 3+ {w}", 2.5, 0.4, 0.45)
                          for i, w in enumerate(("threes", "three-pointers", "3-pointers", "three pointers made"))])
    assert rows.stat.tolist() == ["threes"] * 4 and rows.parse_error.isna().all()
