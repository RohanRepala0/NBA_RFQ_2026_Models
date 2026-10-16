from __future__ import annotations

import pytest

from nba_cold_start.odds_math import (american_to_decimal, american_to_prob, devig, implied_mean,
                                      no_vig_two_way, p_over_normal, parse_american, points_sd,
                                      prob_to_american)


@pytest.mark.parametrize("method", ["multiplicative", "power", "shin"])
def test_minus_110_both_sides_is_fifty_fifty(method):
    over, under = no_vig_two_way(-110, -110, method)
    assert over == pytest.approx(0.5, abs=1e-9)
    assert under == pytest.approx(0.5, abs=1e-9)


@pytest.mark.parametrize("method", ["multiplicative", "power", "shin"])
@pytest.mark.parametrize("pair", [(-150, 130), (-200, 170), (-115, -105), (110, -130)])
def test_devig_sums_to_one(method, pair):
    p = devig([american_to_prob(o) for o in pair], method)
    assert sum(p) == pytest.approx(1.0, abs=1e-9)
    assert all(0 < x < 1 for x in p)


def test_power_and_shin_shade_the_longshot_more_than_multiplicative():
    q = [american_to_prob(-200), american_to_prob(170)]
    mult, power, shin = (devig(q, m)[0] for m in ("multiplicative", "power", "shin"))
    assert power > mult and shin > mult


def test_american_conversions():
    assert american_to_prob(-110) == pytest.approx(110 / 210)
    assert american_to_prob("+150") == pytest.approx(0.4)
    assert american_to_prob("EVEN") == pytest.approx(0.5)
    assert american_to_decimal(-200) == pytest.approx(1.5)
    assert american_to_decimal(150) == pytest.approx(2.5)
    for odds in (-250, -110, 100, 145, 400):
        assert prob_to_american(american_to_prob(odds)) == pytest.approx(odds if odds != 100 else -100)


@pytest.mark.parametrize("bad", ["", "abc", 50, "-99", 0])
def test_parse_american_rejects_nonsense(bad):
    with pytest.raises(ValueError):
        parse_american(bad)


def test_unknown_vig_method():
    with pytest.raises(ValueError):
        devig([0.5, 0.55], "additive")


def test_points_sd_floor_and_fraction():
    assert points_sd(5) == 4.0
    assert points_sd(20) == pytest.approx(6.0)


@pytest.mark.parametrize("line,p", [(24.5, 0.5), (24.5, 0.55), (6.5, 0.45), (30.5, 0.3)])
def test_implied_mean_round_trips(line, p):
    m = implied_mean(line, p)
    assert p_over_normal(m, line) == pytest.approx(p, abs=1e-6)


def test_fifty_percent_at_line_means_mean_equals_line():
    assert implied_mean(24.5, 0.5) == pytest.approx(24.5, abs=1e-6)
