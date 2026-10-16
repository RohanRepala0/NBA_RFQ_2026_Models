from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from nba_cold_start.consensus import build_consensus, weighted_median
from nba_cold_start.odds_math import p_over_normal
from nba_cold_start.signals import make_signal
from nba_cold_start.watchlist import contract_for, contract_p, max_price

NOW = datetime(2026, 10, 20, 22, 0)


def quotes(spec, age_min=5):
    rows = []
    for book, (line, over, under) in spec.items():
        for side, odds in (("over", over), ("under", under)):
            rows.append({"book": book, "side": side, "line": line, "odds_american": odds,
                         "available": True, "is_main_line": True,
                         "quote_ts": NOW - timedelta(minutes=age_min)})
    return pd.DataFrame(rows)


def cons(spec, **kw):
    return build_consensus(quotes(spec, kw.pop("age_min", 5)), NOW, event_id="e", player_id="p",
                           snapshot_ts=NOW, **kw)


def test_weighted_median():
    assert weighted_median([1, 2, 3], [1, 1, 1]) == 2
    assert weighted_median([1, 2], [1, 1]) == 1.5
    assert weighted_median([1, 2, 3], [1, 1, 5]) == 3


def test_equal_lines_at_minus_110_give_line_as_mean():
    c = cons({"draftkings": (24.5, -110, -110), "betmgm": (24.5, -110, -110)})
    assert c.abstain_reason is None and c.n_books == 2
    assert c.mean == pytest.approx(24.5, abs=1e-6)
    assert c.line == 24.5 and c.p_over == pytest.approx(0.5, abs=1e-6)


def test_different_lines_are_normalized_via_implied_means():
    c = cons({"draftkings": (24.5, -110, -110), "betmgm": (25.5, +115, -135)})
    assert 24.0 < c.mean < 25.5
    assert c.p_over_at(24.5) > c.p_over_at(25.5)


def test_pinnacle_counts_double():
    spec = {"draftkings": (24.5, -110, -110), "pinnacle": (26.5, -110, -110)}
    assert cons(spec).mean == pytest.approx(26.5, abs=1e-6)              # weights 1 vs 2
    assert cons(spec, weights={}).mean == pytest.approx(25.5, abs=1e-6)  # equal weights: midpoint


def test_abstain_with_fewer_than_two_books():
    c = cons({"draftkings": (24.5, -110, -110)})
    assert c.abstain_reason.startswith("only 1 priced reference book")


def test_abstain_on_stale_quote():
    c = cons({"draftkings": (24.5, -110, -110), "betmgm": (24.5, -110, -110)}, age_min=31)
    assert c.abstain_reason.startswith("stale quote")


def test_non_reference_books_are_ignored():
    c = cons({"draftkings": (24.5, -110, -110), "prizepicks": (24.5, 100, 100),
              "kalshi": (24.5, 150, -180)})
    assert {b.book for b in c.books} == {"draftkings"}
    assert c.abstain_reason is not None


def test_signal_picks_side_and_threshold():
    c = cons({"draftkings": (24.5, -110, -110), "betmgm": (24.5, -110, -110)})
    s = make_signal({"mean": 27.0, "sd": None}, c)
    assert s["side"] == "over" and s["decision"] == "paper"
    assert s["edge"] == pytest.approx(p_over_normal(27.0, 24.5) - 0.5, abs=1e-9)
    small = make_signal({"mean": 24.7, "sd": None}, c)
    assert small["decision"] == "abstain" and "threshold" in small["reason"]
    under = make_signal({"mean": 22.0, "sd": None}, c)
    assert under["side"] == "under" and under["edge"] > 0


def test_signal_sanity_cap_and_missing_inputs():
    c = cons({"draftkings": (24.5, -110, -110), "betmgm": (24.5, -110, -110)})
    huge = make_signal({"mean": 40.0, "sd": None}, c)
    assert huge["decision"] == "abstain" and "sanity cap" in huge["reason"]
    assert make_signal(None, c)["reason"].startswith("no projection")
    assert make_signal({"mean": 20.0}, None)["reason"].startswith("no market")
    stale = cons({"draftkings": (24.5, -110, -110), "betmgm": (24.5, -110, -110)}, age_min=45)
    s = make_signal({"mean": 27.0}, stale)
    assert s["decision"] == "abstain" and s["edge"] is not None   # still logged with its numbers


def test_max_price_math():
    p, fee, edge = 0.60, 0.07, 0.04
    c = max_price(p, fee, edge)
    assert p - c - fee * c * (1 - c) == pytest.approx(edge, abs=1e-9)
    assert max_price(0.6, 0.0, 0.04) == pytest.approx(0.56)
    assert max_price(0.03, 0.07, 0.04) is None


def test_contract_mapping():
    assert contract_for("over", 24.5) == (25, "YES")
    assert contract_for("under", 24.5) == (25, "NO")
    assert contract_for("over", 25.0) == (26, "YES")
    assert contract_for("under", 25.0) == (25, "NO")
    assert contract_p(25, "YES", 24.5, 6) + contract_p(25, "NO", 24.5, 6) == pytest.approx(1.0)
