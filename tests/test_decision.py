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


def test_one_pick_per_player_game_and_capped_kelly_sizing():
    rows = pd.DataFrame([
        {"event_id": "E", "player_id": "P", "event_ticker": "K", "player": "X", "venue": "kalshi", "contract": "20+ YES",
         "decision": "actionable", "ev_blend": 0.06, "p_blend": 0.55, "cost": 0.49, "size_at_edge": 500},
        {"event_id": "E", "player_id": "P", "event_ticker": "K", "player": "X", "venue": "kalshi", "contract": "25+ NO",
         "decision": "actionable", "ev_blend": 0.09, "p_blend": 0.70, "cost": 0.61, "size_at_edge": 500},
        {"event_id": "E", "player_id": "Q", "event_ticker": "K", "player": "Y", "venue": "kalshi", "contract": "15+ YES",
         "decision": "actionable", "ev_blend": 0.05, "p_blend": 0.60, "cost": 0.55, "size_at_edge": 4},
    ])
    picked = pick_per_group(rows)
    assert picked.decision.tolist() == ["abstain", "actionable", "actionable"]
    assert "already has a pick" in picked.reason.iloc[0]
    assert kelly_fraction(0.55, 0.50) == pytest.approx(0.10)
    sized = size_positions(picked, bankroll=1000.0)
    top = sized.iloc[1]
    assert top.contracts == 8 and top.stake_usd == pytest.approx(4.88)     # $5 = 0.5% cap, at 61c
    assert sized.iloc[2].contracts == 4                                     # limited by size at the price
    assert size_positions(picked, bankroll=None).contracts.isna().all()     # no bankroll, no stakes


def test_config_hash_is_stable_and_changes_with_a_threshold(monkeypatch):
    h = config_hash()
    assert h == config_hash()
    monkeypatch.setitem(config.VENUE_MIN_EDGE, "kalshi", 0.05)
    assert config_hash() != h
