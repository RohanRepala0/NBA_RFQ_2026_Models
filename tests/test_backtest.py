"""Backtest engine and strategies on a small synthetic archive (no network)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb
import pandas as pd
import pytest

from cold_start_usage.backtest import Fold, Tape, bootstrap_yield, monthly_folds, simulate, summarize, walk_forward
from cold_start_usage.kalshi_history import SCHEMA
from cold_start_usage.strategies import Calibration, LadderArbitrage, LadderFit, Maker, TeammateVacuum

TIP = datetime(2026, 1, 15, 0, 30)          # 7:30 PM ET on Jan 14


def market(ticker, player="A Player", team="MIA", n=20, result="yes", value=None, tip=TIP, event="KXNBAPTS-26JAN14BOSMIA"):
    return {"ticker": ticker, "event_ticker": event, "series": "KXNBAPTS", "title": f"{player}: {n}+ points",
            "player": player, "team": team, "player_uuid": None, "threshold": n, "floor_strike": n - 0.5,
            "strike_type": "structured", "result": result,
            "settlement_value": value if value is not None else {"yes": 1.0, "no": 0.0}.get(result),
            "volume": 100.0, "open_time": tip - timedelta(hours=20), "close_time": tip + timedelta(hours=3),
            "occurrence_time": tip + timedelta(hours=3), "tip_est": tip, "fetched_at": tip}


def candle(ticker, ts, bid, ask, low=None, high=None, volume=0.0):
    return {"ticker": ticker, "interval_min": 1, "end_ts": ts,
            "yes_bid_open": bid, "yes_bid_high": bid, "yes_bid_low": bid, "yes_bid_close": bid,
            "yes_ask_open": ask, "yes_ask_high": ask, "yes_ask_low": ask, "yes_ask_close": ask,
            "price_open": None, "price_high": high, "price_low": low, "price_close": None, "price_mean": None,
            "volume": volume, "open_interest": 0.0}


def make_tape(markets, candles) -> Tape:
    con = duckdb.connect(":memory:")
    for table in ("markets", "candles"):
        con.execute(f"CREATE TABLE {table} ({SCHEMA[table]})")
    for table, rows in (("markets", markets), ("candles", candles)):
        df = pd.DataFrame(rows)
        con.register("incoming", df)
        con.execute(f"INSERT INTO {table} SELECT {', '.join(df.columns)} FROM incoming")
        con.unregister("incoming")
    return Tape(con=con)


def orders(*rows):
    cols = ["strategy", "ticker", "side", "kind", "limit", "contracts", "decided_at", "signal", "note"]
    return pd.DataFrame([dict(zip(cols, ("t",) + r + (0.0, ""))) for r in rows])


def test_take_and_make_fills_fees_and_settlement():
    t = TIP - timedelta(hours=2)
    tape = make_tape(
        [market("Y"), market("N", result="no"), market("S", result="scalar", value=0.21)],
        [candle("Y", t - timedelta(minutes=5), 0.38, 0.40), candle("N", t - timedelta(minutes=5), 0.58, 0.60),
         candle("S", t - timedelta(minutes=5), 0.30, 0.34),
         candle("Y", t + timedelta(minutes=30), 0.36, 0.37, low=0.35, high=0.37)])     # a trade at 35c later
    bets = simulate(tape, orders(("Y", "YES", "take", 0.40, 10, t), ("Y", "YES", "take", 0.39, 10, t),
                                 ("N", "NO", "take", 0.42, 10, t), ("S", "YES", "take", 0.34, 10, t),
                                 ("Y", "YES", "make", 0.36, 10, t), ("Y", "YES", "make", 0.35, 10, t)))
    took, missed, no, scalar, made, not_made = (bets.iloc[i] for i in range(6))
    assert took.filled and took.fee == 0.17 and took.pnl == pytest.approx(10 - 4.0 - 0.17)
    assert not missed.filled and missed.pnl == 0                       # limit under the ask
    assert no.filled and no.price == pytest.approx(0.42) and no.pnl == pytest.approx(10 - 4.2 - 0.18)
    assert scalar.filled and scalar.payout == pytest.approx(2.1)        # fair-price settlement, not a void
    assert made.filled and made.fee == 0 and made.price == 0.36        # a trade printed through 36c
    assert not not_made.filled                                         # 35c was touched, not traded through
    assert took.clv == pytest.approx(0.365 - 0.40)                     # close mid vs price paid
    s = summarize(bets)
    assert s["fills"] == 4 and s["fair_price_settlements"] == 1


def test_orders_at_or_after_tip_are_refused():
    tape = make_tape([market("Y")], [candle("Y", TIP - timedelta(hours=1), 0.4, 0.42)])
    with pytest.raises(ValueError, match="after tip"):
        simulate(tape, orders(("Y", "YES", "take", 0.5, 10, TIP)))


def test_monthly_folds_embargo_and_holdout():
    dates = pd.Series([date(2025, 11, 18), date(2025, 12, 5), date(2026, 1, 10), date(2026, 4, 5), date(2026, 5, 1)])
    folds = monthly_folds(dates, holdout_start=date(2026, 4, 1))
    names = [f.name for f in folds]
    assert names == ["2025-12", "2026-01", "holdout"]
    dec = folds[0]
    assert dec.train_end == date(2025, 11, 30) and dec.test_start == date(2025, 12, 1)   # one-day embargo
    assert folds[-1].holdout and folds[-1].test_start == date(2026, 4, 1)


def _calibration_world():
    """Cheap YES (5-10c) never pays in December; the January test market is the same kind."""
    ms, cs = [], []
    for i in range(70):
        tip = datetime(2025, 12, 10, 0, 30) + timedelta(days=i % 20)
        tk = f"D{i}"
        ms.append(market(tk, n=40, result="no", tip=tip, event=f"KXNBAPTS-25DEC{i:02d}BOSMIA"))
        cs.append(candle(tk, tip - timedelta(hours=2), 0.06, 0.08))
    tk = "J1"
    ms.append(market(tk, n=40, result="yes", tip=TIP))                 # the test market happens to pay
    cs.append(candle(tk, TIP - timedelta(hours=2), 0.06, 0.08))
    return make_tape(ms, cs)


def test_calibration_learns_only_from_earlier_dates():
    tape = _calibration_world()
    st = Calibration()
    fold = Fold("2026-01", date(2025, 12, 31), date(2026, 1, 1), date(2026, 2, 1))
    bets = walk_forward(tape, st, [fold])
    assert len(st.rules) == 1 and list(st.rules.values())[0][0] == "NO"   # learned: fade cheap YES
    assert len(bets) == 1 and bets.side.iloc[0] == "NO" and bets.filled.iloc[0]
    assert bets.pnl.iloc[0] < 0                                          # the January outcome was not peeked at


def test_ladder_arbitrage_and_ladder_fit():
    t = TIP - timedelta(hours=2)
    ms = [market(f"L{n}", n=n, result="yes" if n <= 20 else "no") for n in (10, 15, 20, 25, 30)]
    mids = {10: 0.90, 15: 0.70, 20: 0.45, 25: 0.22, 30: 0.08}
    cs = [candle(f"L{n}", t, mids[n] - 0.01, mids[n] + 0.01) for n in mids]
    cs[2] = candle("L20", t, 0.15, 0.17)          # 20+ sits far below the curve, even under the 25+ bid
    tape = make_tape(ms, cs)
    fold = Fold("x", date(2026, 1, 1), date(2026, 1, 1), date(2026, 2, 1))
    fit = walk_forward(tape, LadderFit(params={"offset": 60, "min_edge": 0.05, "max_spread": 0.10,
                                               "fit_spread": 0.25, "min_rungs": 3, "contracts": 10}), [fold])
    assert fit.ticker.tolist() == ["L20"] and fit.side.iloc[0] == "YES"
    arb = walk_forward(tape, LadderArbitrage(), [fold])
    assert set(arb.ticker) >= {"L20", "L25"}            # 20+ YES at 17c + 25+ NO at 79c < $1 after fees
    assert (arb.groupby("ticker").side.first()["L20"], arb.groupby("ticker").side.first()["L25"]) == ("YES", "NO")


def test_teammate_vacuum_buys_the_laggard_after_a_team_jump():
    start = TIP - timedelta(hours=8)
    ms = [market("A", player="Alpha", n=15), market("B", player="Beta", n=15), market("C", player="Gamma", n=15),
          market("X", player="Opp", team="BOS", n=15)]
    cs = [candle(t, start, 0.49, 0.51) for t in "ABCX"]
    jump = TIP - timedelta(hours=3)
    cs += [candle("A", jump, 0.64, 0.66), candle("B", jump + timedelta(minutes=2), 0.65, 0.67)]
    tape = make_tape(ms, cs)
    st = TeammateVacuum()
    bets = walk_forward(tape, st, [Fold("x", date(2026, 1, 1), date(2026, 1, 1), date(2026, 2, 1))])
    assert bets.ticker.tolist() == ["C"] and bets.side.iloc[0] == "YES"
    assert pd.Timestamp(bets.decided_at.iloc[0]) > pd.Timestamp(jump)     # acts after it saw the move
    assert st.detections and st.detections[0]["movers"] == 2


def test_maker_wrapper_posts_one_tick_over_the_bid():
    t = TIP - timedelta(hours=2)
    ms = [market(f"L{n}", n=n, result="yes" if n <= 20 else "no") for n in (10, 15, 20, 25, 30)]
    mids = {10: 0.90, 15: 0.70, 20: 0.21, 25: 0.22, 30: 0.08}
    tape = make_tape(ms, [candle(f"L{n}", t, mids[n] - 0.01, mids[n] + 0.01) for n in mids])
    maker = Maker(base=LadderFit())
    o = maker.decide(tape, tape.markets)
    assert (o.kind == "make").all() and o["limit"].iloc[0] == pytest.approx(0.21)   # bid 20c + 1c, under the 22c ask


def test_bootstrap_interval_brackets_the_yield():
    rows = []
    for d in range(10):
        rows.append({"filled": True, "game_date": date(2026, 1, 1) + timedelta(days=d), "pnl": 1.0 if d % 2 else -0.5,
                     "cost": 5.0})
    bets = pd.DataFrame(rows)
    lo, hi = bootstrap_yield(bets)
    y = bets.pnl.sum() / bets.cost.sum()
    assert lo <= y <= hi
