from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from cold_start_usage.pipeline import run_projections, snapshot_from_file
from cold_start_usage.polymarket import points_markets, taker_fee
from cold_start_usage.venues import evaluate, kalshi_event_code, max_price, scan
from tests.fixtures.synthetic import FETCHED, TIP, events_response, synthetic_event

POLY_EVENT = {
    "slug": "nba-min-mia-2026-10-21",
    "markets": [
        {"id": 1, "question": "Timberwolves vs. Heat", "clobTokenIds": '["a", "b"]', "bestBid": 0.49, "bestAsk": 0.5},
        {"id": 2, "question": "Giannis Antetokounmpo: Points O/U 29.5", "clobTokenIds": '["y1", "n1"]',
         "bestBid": 0.30, "bestAsk": 0.36, "feesEnabled": True, "takerBaseFee": 1000},
        {"id": 3, "question": "Bam Adebayo: Rebounds O/U 9.5", "clobTokenIds": '["y2", "n2"]', "bestBid": 0.4, "bestAsk": 0.5},
    ],
}


def test_polymarket_points_markets_parse():
    df = points_markets(POLY_EVENT)
    assert len(df) == 1
    r = df.iloc[0]
    assert r.player == "Giannis Antetokounmpo" and r.line == 29.5
    assert (r.yes_ask, r.yes_bid, r.no_ask) == (pytest.approx(36.0), pytest.approx(30.0), pytest.approx(70.0))
    assert r.fee_bps == 1000 and r.token_yes == "y1"


def test_polymarket_fee_formula():
    assert taker_fee(0.42, 1000) == pytest.approx(0.042)
    assert taker_fee(0.87, 1000) == pytest.approx(0.013)
    assert taker_fee(0.5, 0) == 0.0


def test_evaluate_separates_market_and_model_value_and_counts_size():
    q = {"venue": "polymarket", "player": "X", "line": 29.5, "yes_ask": 42.0, "no_ask": 87.0, "fee_bps": 1000}
    rows = {r["contract"]: r for r in evaluate(q, p_cons_over=0.527, p_model_over=0.527,
                                               book={"YES": [(0.42, 5), (0.55, 5), (0.56, 250)], "NO": [(0.87, 40)]})}
    over = rows["over 29.5"]
    assert over["verdict"] == "market + model value" and over["edge_vs_market_pp"] == pytest.approx(6.5, abs=0.05)
    assert over["size_at_edge"] == 5                                  # only the 5 shares at 42c clear the bar
    assert rows["under 29.5"]["verdict"] == "no edge"
    only_model = evaluate(q, p_cons_over=0.47, p_model_over=0.60)[0]
    assert only_model["verdict"] == "model value only"


def test_max_price_respects_fee():
    cap = max_price(0.527, "polymarket", 1000, 0.04)
    assert cap == 0.44 and 0.527 - 0.45 - taker_fee(0.45, 1000) < 0.04


def test_kalshi_event_code():
    from datetime import date
    assert kalshi_event_code(date(2026, 10, 8), "BOS", "CLE") == "26OCT08BOSCLE"


def test_scan_reads_both_venues_against_stored_consensus(storage):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    run_projections(storage, TIP.date(), FETCHED, {})
    kalshi = pd.DataFrame([{"ticker": "K1", "event_ticker": "KXNBAPTS-26OCT21MINMIA", "player": "Bam Adebayo",
                            "key": "bamadebayo", "threshold": 20, "yes_bid": 20.0, "yes_ask": 22.0,
                            "no_bid": 76.0, "no_ask": 78.0, "volume": 10, "close_time": None}])
    df = scan(storage, TIP.date(), FETCHED + timedelta(minutes=1),
              polymarket_fetch=lambda a, h, d: points_markets(POLY_EVENT) if (a, h) == ("MIN", "MIA") else None,
              kalshi_quotes=kalshi)
    assert set(df.venue) == {"polymarket", "kalshi"} and set(df.game) == {"MIN @ MIA"}
    g = df[(df.player == "Giannis Antetokounmpo") & (df.contract == "over 29.5")].iloc[0]
    assert g.fair_market is not None and g.fair_model is not None
    assert g.verdict in {"market value", "market + model value"}      # 36c ask vs a ~48c consensus
    assert df[df.venue == "kalshi"].contract.tolist() == ["over 19.5", "under 19.5"]
