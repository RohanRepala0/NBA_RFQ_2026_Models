"""Venue readers (Kalshi, Polymarket US, international reference), fees, and the logged scan."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from cold_start_usage import polymarket, polymarket_us
from cold_start_usage.fees import all_in_cost, fee_total
from cold_start_usage.kalshi import asks_from_orderbook, event_code, parse_markets, team_from_ticker
from cold_start_usage.pipeline import run_projections, snapshot_from_file
from cold_start_usage.storage import AfterTipError
from cold_start_usage.venues import Fetchers, scan
from tests.fixtures.synthetic import FETCHED, TIP, events_response, synthetic_event

DAY = TIP.date()
EVENT = "KXNBAPTS-26OCT21MINMIA"


def kalshi_market(code: str, name: str, n: int, yes_bid: float, yes_ask: float, ask_size: float,
                  bid_size: float, event: str = EVENT) -> dict:
    """One live-shaped KXNBAPTS market (dollar strings, *_fp sizes)."""
    return {"ticker": f"{event}-{code}-{n}", "event_ticker": event, "title": f"{name}: {n}+ points",
            "floor_strike": n - 0.5, "strike_type": "greater", "status": "active",
            "yes_bid_dollars": f"{yes_bid:.4f}", "yes_ask_dollars": f"{yes_ask:.4f}",
            "no_bid_dollars": f"{1 - yes_ask:.4f}", "no_ask_dollars": f"{1 - yes_bid:.4f}",
            "yes_ask_size_fp": f"{ask_size:.2f}", "yes_bid_size_fp": f"{bid_size:.2f}", "volume_fp": "100.00",
            "occurrence_datetime": (TIP + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")}


# --- fees ----------------------------------------------------------------------------
def test_kalshi_fee_rounds_up_to_the_cent_per_order():
    assert fee_total("kalshi", 1, 0.50) == 0.02          # 1.75c exact
    assert fee_total("kalshi", 10, 0.50) == 0.18
    assert fee_total("kalshi", 100, 0.55) == 1.74        # Kalshi's worked example
    assert fee_total("kalshi", 10, 0.50, maker=True) == 0.0   # KXNBAPTS: resting orders pay nothing


def test_polymarket_fees():
    assert fee_total("polymarket_us", 1, 0.49) == 0.02    # 1.74c exact, banker's rounding to the cent
    assert fee_total("polymarket_us", 5, 0.49) == 0.09
    assert fee_total("polymarket_us", 100, 0.50) == 1.74
    assert fee_total("polymarket_us", 1, 0.05) == 0.0     # 0.33c rounds down to $0.00
    assert fee_total("polymarket_intl", 1, 0.42) == pytest.approx(0.01218)   # 0.05 x p x (1-p), not 4.2c
    assert all_in_cost("kalshi", 0.40, 10) == pytest.approx(0.417)
    with pytest.raises(KeyError):
        fee_total("novig", 1, 0.5)


# --- Kalshi ----------------------------------------------------------------------------
def test_kalshi_codes_and_order_book():
    assert event_code(date(2026, 10, 20), "BOS", "DET") == "26OCT20BOSDET"
    assert team_from_ticker("KXNBAPTS-26OCT20BOSDET-BOSDWHITE9-25") == "BOS"
    assert team_from_ticker("KXNBAPTS-26JUN13NYKSAS-SASVWEMBANYAMA1-30") == "SAS"
    book = asks_from_orderbook({"orderbook_fp": {"no_dollars": [["0.6000", "1"], ["0.6400", "203.43"], ["0.6500", "333.19"]],
                                                 "yes_dollars": [["0.3200", "30"], ["0.3400", "20.02"]]}})
    assert book["YES"] == [(0.35, 333.19), (0.36, 203.43), (0.4, 1.0)]   # 1 - NO bid, best first
    assert book["NO"] == [(0.66, 20.02), (0.68, 30.0)]


def test_kalshi_rejects_mismatched_strike():
    bad = kalshi_market("MIABADEBAYO13", "Bam Adebayo", 30, 0.3, 0.32, 10, 10) | {"floor_strike": 24.5}
    assert "floor_strike" in parse_markets([bad]).parse_error.iloc[0]


# --- Polymarket ------------------------------------------------------------------------
INTL_EVENT = {"slug": "nba-min-mia-2026-10-21", "markets": [
    {"id": 1, "slug": "m1", "question": "Timberwolves vs. Heat", "outcomes": '["Timberwolves", "Heat"]'},
    {"id": 2, "slug": "m2", "question": "Giannis Antetokounmpo: Points O/U 29.5", "outcomes": '["No", "Yes"]',
     "clobTokenIds": '["no_tok", "yes_tok"]', "bestBid": 0.30, "bestAsk": 0.36, "feesEnabled": True,
     "feeType": "sports_fees_v3", "feeSchedule": {"rate": 0.05, "exponent": 1}, "takerBaseFee": 1000},
    {"id": 3, "slug": "m3", "question": "Bam Adebayo: Points O/U 18.5", "outcomes": '["Yes", "No"]',
     "clobTokenIds": '["y", "n"]', "bestBid": 0.4, "bestAsk": 0.5, "feesEnabled": True, "feeType": "mystery_v9",
     "feeSchedule": {"rate": 0.2, "exponent": 2}},
]}


def test_international_reader_maps_tokens_by_label_and_refuses_unknown_fees():
    df = polymarket.points_markets(INTL_EVENT)
    g = df[df.player == "Giannis Antetokounmpo"].iloc[0]
    assert (g.token_yes, g.token_no) == ("yes_tok", "no_tok")          # labels, not index 0
    assert g.fee_rate == 0.05 and g.line == 29.5 and pd.isna(g.parse_error)
    assert (g.yes_ask, g.no_ask) == (0.36, 0.70) and g.venue == "polymarket_intl"
    assert "unknown fee schedule" in df[df.player == "Bam Adebayo"].parse_error.iloc[0]


US_EVENT = {"slug": "nba-min-mia-2026-10-21", "markets": [
    {"slug": "astatc-nba-min-mia-2026-10-21-pts-gant-gte30", "sportsMarketType": "basketball_player_points",
     "question": "Will Giannis Antetokounmpo record at least 30 points in MIN vs MIA?",
     "title": "Giannis Antetokounmpo 30+ points", "line": 30, "feeCoefficient": 0.0695,
     "status": "MARKET_STATUS_OPEN", "bestBidQuote": {"value": "0.4100"}, "bestAskQuote": {"value": "0.4400"},
     "marketSides": [{"description": "Yes", "long": True, "team": {"abbreviation": "mia"}},
                     {"description": "No", "long": False, "team": {"abbreviation": "mia"}}],
     "gameStartTime": "2026-10-21T23:30:00Z"},
    {"slug": "astatc-nba-min-mia-2026-10-21-pts-bam-ou", "sportsMarketType": "basketball_player_points",
     "question": "Will Bam Adebayo score over 18.5 points vs the Timberwolves?", "line": 18.5,
     "feeCoefficient": 0.0695, "status": "MARKET_STATUS_OPEN",
     "marketSides": [{"description": "Yes", "long": True}, {"description": "No", "long": False}]},
    {"slug": "x-reb", "sportsMarketType": "basketball_player_rebounds", "question": "Will Bam record 10+ rebounds?"},
]}


def test_polymarket_us_reader_handles_ladders_and_over_unders():
    df = polymarket_us.points_markets(US_EVENT)
    assert len(df) == 2 and df.parse_error.isna().all()
    g = df.iloc[0]
    assert (g.player, g.team, g.threshold, g.line) == ("Giannis Antetokounmpo", "MIA", 30, 29.5)
    assert (g.yes_ask, g.no_ask, g.fee_rate) == (0.44, 0.59, 0.0695)
    b = df.iloc[1]
    assert b.threshold is None or pd.isna(b.threshold)
    assert b.line == 18.5 and b.player == "Bam Adebayo"
    book = polymarket_us.book_from_response({"marketData": {
        "bids": [{"px": {"value": "0.41"}, "qty": "10"}, {"px": {"value": "0.40"}, "qty": "5"}],
        "offers": [{"px": {"value": "0.45"}, "qty": "20"}, {"px": {"value": "0.44"}, "qty": "7"}]}})
    assert book == {"YES": [(0.44, 7.0), (0.45, 20.0)], "NO": [(0.59, 10.0), (0.6, 5.0)]}
    assert polymarket_us.slug("NYK", "SAS", date(2026, 10, 20)) == "nba-ny-sa-2026-10-20"
    assert polymarket_us.slug("BOS", "DET", date(2026, 10, 20)) == "nba-bos-det-2026-10-20"


# --- the scan ----------------------------------------------------------------------------
def _slate(storage):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    run_projections(storage, DAY, FETCHED, {})


def test_scan_logs_two_rows_per_market_and_decides(storage):
    _slate(storage)
    markets = [kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 30, 0.38, 0.40, 50, 50),
               kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 45, 0.01, 0.03, 50, 50),
               kalshi_market("MIAXUNKNOWN1", "Unknown Guy", 20, 0.4, 0.5, 10, 10),
               kalshi_market("MINBADEBAYO13", "Bam Adebayo", 20, 0.3, 0.33, 200, 200),       # wrong team code
               kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 30, 0.38, 0.40, 50, 50,
                             event="KXNBAPTS-26OCT22MIAORL")]                                # another game
    f = Fetchers(kalshi_markets=lambda: markets + [{"ticker": "KXNBAPTS-26OCT21MINMIA-ODD", "event_ticker": EVENT,
                                                    "title": "Something else"}],
                 pm_us_event=lambda a, h, d: US_EVENT, pm_intl_event=lambda a, h, d: INTL_EVENT)
    df = scan(storage, DAY, FETCHED + timedelta(minutes=1), f, tag="t-60m")
    # 5 Kalshi in this game (1 unparsed), 3 US (the rebounds market is read too, unparsed: no line), 2 intl
    assert len(df) == 2 * (5 + 3 + 2)
    assert storage.count("venue_signals") == len(df) and storage.count("venue_snapshots") == 10
    assert df[df.ticker == "KXNBAPTS-26OCT21MINMIA-ODD"].reason.str.startswith("unparsed").all()
    reb = df[df.ticker == "x-reb"]
    assert set(reb.stat) == {"rebounds"} and reb.reason.str.startswith("unparsed").all()
    by = {(r.venue, r.contract): r for r in df.itertuples()}
    act = by[("kalshi", "30+ YES")]
    assert act.decision == "actionable" and act.ev_blend >= 0.04 and act.ev_market >= 0
    assert act.max_price >= 0.40 and act.size_at_edge >= 10
    assert by[("kalshi", "45+ NO")].reason.startswith("tail rung")
    unknown = df[df.player.isin(["Unknown Guy", "Bam Adebayo"]) & (df.venue == "kalshi")]
    assert set(unknown.reason.str[:14]) == {"unmatched name"}           # name and team must both match
    assert set(df[df.venue == "polymarket_intl"].decision) == {"reference"}
    us = df[(df.venue == "polymarket_us") & (df.player == "Giannis Antetokounmpo")]
    assert set(us.decision) <= {"abstain", "watch"}          # same player already has a Kalshi pick or no edge
    assert (df.groupby(["event_id", "player_id"]).apply(lambda g: (g.decision == "actionable").sum()) <= 1).all()


def test_scan_never_logs_after_tip_and_respects_stale_books(storage):
    _slate(storage)
    f = Fetchers(kalshi_markets=lambda: [kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 30,
                                                       0.38, 0.40, 50, 50)])
    assert scan(storage, DAY, TIP + timedelta(minutes=1), f).empty
    stale = scan(storage, DAY, FETCHED + timedelta(minutes=45), f)
    assert set(stale.decision) == {"abstain"} and stale.reason.str.startswith("stale quote").all()
    with pytest.raises(AfterTipError):
        storage.append("venue_signals", [{"venue": "kalshi", "quote_ts": TIP, "tip_ts": TIP}])


def test_one_venue_failing_does_not_block_the_others(storage):
    _slate(storage)

    def boom(*a):
        raise ConnectionError("down")
    f = Fetchers(kalshi_markets=lambda: [kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 30,
                                                       0.38, 0.40, 50, 50)], pm_us_event=boom)
    df = scan(storage, DAY, FETCHED + timedelta(minutes=1), f)
    assert len(df) == 2 and any("polymarket_us" in e for e in f.errors)
