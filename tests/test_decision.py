"""The one decision path: blend, robust pricing, gates, one pick per player-game, sizing."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from cold_start_usage import config
from cold_start_usage.consensus import Consensus
from cold_start_usage.decision import (Context, blend, config_hash, evaluate_contract, kelly_fraction, max_price,
                                       pick_per_group, robust_p, side_p, size_at, size_positions, vwap)
from cold_start_usage.fees import fee_per_contract
from cold_start_usage.odds_math import points_sd

NOW = datetime(2026, 10, 21, 22, 30)
TIP = NOW + timedelta(hours=1)


def cons(mean=20.0, line=19.5, n_books=3, abstain=None, snap=NOW - timedelta(minutes=1)):
    return Consensus(event_id="E", player_id="P", as_of=NOW, snapshot_ts=snap, mean=mean, line=line,
                     p_over=None, books=[object()] * n_books, abstain_reason=abstain)


def quote(ask, line=19.5, threshold=20, size=100, **kw):
    q = {"venue": "kalshi", "ticker": "T", "player": "X", "line": line, "threshold": threshold,
         "yes_ask": ask, "yes_bid": ask - 0.02, "no_ask": 1 - ask + 0.02, "no_bid": 1 - ask,
         "yes_ask_size": size, "no_ask_size": size, "quote_ts": NOW, "parse_error": None}
    return q | kw


def ctx(**kw):
    base = dict(now=NOW, tip=TIP, event_id="E", game="A @ B", player_id="P", consensus=cons(), model_mean=20.0)
    return Context(**(base | kw))


def test_blend_leans_on_the_market_and_drops_big_gaps():
    m, w, flag = blend(23.0, 20.0)
    assert w == config.W_MODEL and m == pytest.approx(20.6) and flag is None
    m, w, flag = blend(26.0, 20.0)                     # 1.0 SD away (sd(20) = 6)
    assert (m, w) == (20.0, 0.0) and "check minutes" in flag
    assert blend(None, 20.0)[0] == 20.0


def test_robust_price_is_the_lower_of_two_sd_models_and_coherent():
    for n in range(5, 45, 5):
        p, spread = robust_p(22.0, n - 0.5, "YES")
        p1 = side_p(22.0, n - 0.5, "YES", points_sd(22.0))
        assert p <= p1 + 1e-12 and spread >= 0
    ladder = [side_p(22.0, n - 0.5, "YES", points_sd(22.0)) for n in range(5, 45, 5)]
    assert ladder == sorted(ladder, reverse=True)
    assert side_p(22.0, 19.5, "YES", 6) + side_p(22.0, 19.5, "NO", 6) == pytest.approx(1)


def test_max_price_and_size_respect_the_fee():
    cap = max_price(0.55, "kalshi", 0.04, contracts=10)
    assert 0.55 - cap - fee_per_contract("kalshi", 10, cap) >= 0.04
    nxt = cap + 0.01
    assert 0.55 - nxt - fee_per_contract("kalshi", 10, nxt) < 0.04
    assert size_at([(0.40, 5), (0.41, 30), (0.47, 100)], 0.41) == 35
    assert vwap([(0.40, 5), (0.41, 30)], 20) == pytest.approx((5 * 0.40 + 15 * 0.41) / 20)


def test_gates_in_order():
    assert evaluate_contract(quote(0.40) | {"venue": "polymarket_intl"}, "YES", ctx())["decision"] == "reference"
    assert evaluate_contract(quote(0.40), "YES", ctx(now=TIP))["reason"].startswith("after tip")
    assert evaluate_contract(quote(0.40, parse_error="bad"), "YES", ctx())["reason"].startswith("unparsed")
    assert evaluate_contract(quote(0.40), "YES", ctx(player_id=None))["reason"].startswith("unmatched")
    assert evaluate_contract(quote(0.40), "YES", ctx(status="out"))["reason"] == "player listed out"
    assert evaluate_contract(quote(0.40), "YES", ctx(consensus=None))["reason"].startswith("no consensus")
    stale = ctx(consensus=cons(abstain="stale quote: draftkings 45 min old"))
    assert evaluate_contract(quote(0.40), "YES", stale)["reason"].startswith("stale quote")
    leak = ctx(consensus=cons(snap=NOW + timedelta(minutes=5)))
    assert evaluate_contract(quote(0.40), "YES", leak)["reason"].startswith("leak")
    far = evaluate_contract(quote(0.03, line=39.5, threshold=40), "YES", ctx())
    assert far["reason"].startswith("tail rung")


def test_value_needs_the_market_to_agree_size_and_a_sane_edge():
    # Consensus 20.0 at 19.5: P(YES) ~ 0.53. A 40c ask is ~11pp of value after fees.
    good = evaluate_contract(quote(0.40), "YES", ctx())
    assert good["decision"] == "actionable" and good["ev_market"] > 0 and good["size_at_edge"] >= 10
    assert evaluate_contract(quote(0.40, size=3), "YES", ctx())["reason"].startswith("thin")
    assert evaluate_contract(quote(0.40), "YES", ctx(status="questionable"))["decision"] == "watch"
    assert "cap" in evaluate_contract(quote(0.30), "YES", ctx())["reason"]          # > 15pp: check inputs
    no_edge = evaluate_contract(quote(0.52), "YES", ctx())
    assert no_edge["decision"] == "abstain" and "after fees" in no_edge["reason"]
    # The model alone can't make it actionable: market fair just under the ask.
    model_only = evaluate_contract(quote(0.54), "YES", ctx(model_mean=24.0))
    assert model_only["decision"] == "abstain"


def _act(event, player, contract, ev, p, ask, ladder, p_market=None, tau=0.04):
    return {"event_id": event, "player_id": player, "event_ticker": "K", "player": player, "venue": "kalshi",
            "contract": contract, "decision": "actionable", "ev_blend": ev, "p_blend": p,
            "p_market": p if p_market is None else p_market, "ask": ask, "cost": ask + 0.02, "tau": tau,
            "fee_rate": None, "size_at_edge": sum(float(x.split(":")[1]) for x in ladder.split(";")),
            "ladder": ladder}


def test_one_pick_per_player_game_and_holdings():
    rows = pd.DataFrame([_act("E", "P", "20+ YES", 0.06, 0.55, 0.49, "0.49:500"),
                         _act("E", "P", "25+ NO", 0.09, 0.70, 0.61, "0.61:500"),
                         _act("E", "Q", "15+ YES", 0.05, 0.60, 0.55, "0.55:4")])
    picked = pick_per_group(rows)
    assert picked.decision.tolist() == ["abstain", "actionable", "actionable"]
    assert "already has a pick" in picked.reason.iloc[0]
    held = pick_per_group(rows, filled={("E", "P")})
    assert held.decision.tolist()[:2] == ["abstain", "abstain"] and "already holding" in held.reason.iloc[1]


def test_sizing_walks_the_ladder_and_respects_caps_across_scans():
    from cold_start_usage.decision import Exposure, fill_cost
    assert kelly_fraction(0.55, 0.50) == pytest.approx(0.10)
    # 3 @ 44c then 200 @ 47c, p = 0.55: cost is walked up the ladder, fee at the real order size.
    assert fill_cost([(0.44, 3), (0.47, 200)], 5, "kalshi", None) == pytest.approx(3 * 0.44 + 2 * 0.47 + 0.09)
    row = _act("E", "P", "20+ YES", 0.09, 0.55, 0.44, "0.44:3;0.47:200")
    sized = size_positions(pd.DataFrame([row]), bankroll=1000.0).iloc[0]
    assert sized.stake_usd <= 5.0 + 1e-9                         # 0.5% of $1000, VWAP and fee included
    assert sized.contracts == 10 and sized.cost == pytest.approx(sized.stake_usd / 10, abs=1e-3)
    assert sized.ev_blend >= 0.04 - 1e-9                        # EV re-priced at the real cost
    # The same player-game already took 0.4% in an earlier scan's fill: only 0.1% left.
    prior = Exposure(slate=0.004, game={"E": 0.004}, group={("E", "P"): 0.004})
    assert size_positions(pd.DataFrame([row]), 1000.0, prior).iloc[0].contracts == 2
    # The slate is already at its 3% cap from other games: nothing more today.
    full = size_positions(pd.DataFrame([row]), 1000.0, Exposure(slate=0.03))
    assert full.decision.iloc[0] == "watch" and "cap" in full.reason.iloc[0]
    assert size_positions(pd.DataFrame([row]), bankroll=None).iloc[0].stake_frac is None


def test_limit_never_exceeds_what_the_market_alone_pays():
    # Model 24.4 vs books 20.0 (0.73 SD: w = 0.2) lifts p_blend above p_market; the ladder's
    # deep level at 51c is fine on the blend but negative EV on the market alone.
    q = quote(0.44, size=3)
    r = evaluate_contract(q, "YES", ctx(model_mean=24.4), levels=[(0.44, 3), (0.51, 200)])
    assert r["max_price"] <= 0.51 - 0.01 and r["p_market"] - r["max_price"] - fee_per_contract("kalshi", 10, r["max_price"]) >= 0
    assert r["size_at_edge"] == 3                                # the 51c level isn't counted
    assert evaluate_contract(q, "YES", ctx(), levels=[])["reason"].startswith("thin: 0")   # empty book is empty


def test_config_hash_is_stable_and_changes_with_a_threshold(monkeypatch):
    h = config_hash()
    assert h == config_hash()
    monkeypatch.setitem(config.VENUE_MIN_EDGE, "kalshi", 0.05)
    assert config_hash() != h
