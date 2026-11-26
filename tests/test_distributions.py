"""Per-stat distributions: points must match the old normal path exactly; rebounds and assists
are a negative binomial (Var = phi * mean) with an exact discrete CDF."""
from __future__ import annotations

import math

import pytest

from cold_start_usage import config, distributions as dist
from cold_start_usage.decision import robust_p as decision_robust_p
from cold_start_usage.odds_math import implied_mean, p_over_normal, points_sd


def brute_sf(mean: float, line: float, phi: float, upper: int = 400) -> float:
    """P(X > line) summed upward from floor(line) + 1, with the pmf by recurrence (a different
    route from distributions.count_sf, which sums lgamma terms below the line)."""
    if phi <= 1:
        pmf, step = math.exp(-mean), (lambda k: mean / (k + 1))
    else:
        r, p = mean / (phi - 1), 1 / phi
        pmf, step = p ** r, (lambda k: (k + r) / (k + 1) * (1 - p))
    total = 0.0
    for k in range(upper):
        if k > line:
            total += pmf
        pmf *= step(k)
    return total


@pytest.mark.parametrize("phi", [1.0, 1.15, 1.30, 1.50, 2.0])
def test_negative_binomial_matches_a_brute_force_sum(phi):
    for mean in (0.4, 2.0, 5.5, 8.0, 12.5):
        for line in (0.5, 1.5, 4.5, 7.5, 13.5):
            assert dist.count_sf(mean, line, phi) == pytest.approx(brute_sf(mean, line, phi), abs=1e-10)
    # Var = phi * mean: E[X] and E[X^2] from the pmf.
    pmf = [dist.count_sf(6.0, k - 0.5, phi) - dist.count_sf(6.0, k + 0.5, phi) for k in range(200)]
    mean = sum(k * q for k, q in enumerate(pmf))
    var = sum(k * k * q for k, q in enumerate(pmf)) - mean ** 2
    assert mean == pytest.approx(6.0, abs=1e-8) and var == pytest.approx(max(phi, 1.0) * 6.0, abs=1e-6)


def test_poisson_limit_and_guards():
    poisson = 1 - sum(math.exp(-4.0) * 4.0 ** k / math.factorial(k) for k in range(6))   # P(X >= 6)
    assert dist.count_sf(4.0, 5.5, 1.0) == pytest.approx(poisson, abs=1e-12)
    assert dist.count_sf(4.0, 5.5, 1.000001) == pytest.approx(poisson, abs=1e-5)       # NB -> Poisson
    assert dist.count_sf(4.0, 5.5, 0.9) == dist.count_sf(4.0, 5.5, 1.0)                # under-dispersed: Poisson
    assert dist.count_sf(0.0, 0.5, 1.3) == 0.0 and dist.count_sf(-1.0, 0.5, 1.3) == 0.0  # mean <= 0
    assert dist.count_sf(3.0, -0.5, 1.3) == 1.0
    assert dist.count_sf(5.0, 7.5, 1.3) == dist.count_sf(5.0, 7.0, 1.3)                # P(X > 7.5) = P(X >= 8)
    with pytest.raises(ValueError):
        dist.p_over("dunks", 2.0, 1.5)


def test_count_prices_rise_with_the_mean_and_round_trip():
    for stat in ("rebounds", "assists"):
        ps = [dist.p_over(stat, m / 4, 6.5) for m in range(1, 80)]
        assert ps == sorted(ps)
        for line in (1.5, 4.5, 7.5, 11.5):
            for p in (0.15, 0.4, 0.5, 0.62, 0.85):
                m = dist.implied_mean(stat, line, p)
                assert dist.p_over(stat, m, line) == pytest.approx(p, abs=1e-7)
        # Fatter tail: phi_alt prices a long rung above the mean higher.
        phi, phi_alt = config.COUNT_DISPERSION[stat]
        assert dist.p_over(stat, 6.0, 11.5, phi=phi_alt) > dist.p_over(stat, 6.0, 11.5, phi=phi)


def test_points_are_identical_to_the_normal_path():
    for mean in [x / 2 for x in range(1, 90)]:
        for line in (0.5, 4.5, 9.5, 14.5, 19.5, 24.5, 29.5, 34.5, 44.5):
            assert dist.p_over("points", mean, line) == p_over_normal(mean, line)
            assert dist.sd("points", mean) == points_sd(mean)
            for side in ("YES", "NO"):
                p1 = p_over_normal(mean, line, sd=points_sd(mean))
                p2 = p_over_normal(mean, line, sd=dist.sd_compound(mean))
                p1, p2 = (p1, p2) if side == "YES" else (1 - p1, 1 - p2)
                assert dist.robust_p("points", mean, line, side) == (min(p1, p2), abs(p1 - p2))
                assert decision_robust_p(mean, line, side) == (min(p1, p2), abs(p1 - p2))
    for line in (4.5, 19.5, 29.5):
        for p in (0.2, 0.5, 0.71):
            assert dist.implied_mean("points", line, p) == implied_mean(line, p)


def test_robust_count_price_is_the_lower_of_phi_and_phi_alt():
    phi, phi_alt = config.COUNT_DISPERSION["rebounds"]
    for line in (3.5, 7.5, 9.5, 14.5):
        for side in ("YES", "NO"):
            a = dist.side_p("rebounds", 8.0, line, side, phi=phi)
            b = dist.side_p("rebounds", 8.0, line, side, phi=phi_alt)
            assert dist.robust_p("rebounds", 8.0, line, side) == (min(a, b), abs(a - b))
    assert dist.side_p("assists", 6.0, 5.5, "YES") + dist.side_p("assists", 6.0, 5.5, "NO") == pytest.approx(1)
    assert dist.sd("rebounds", 9.0) == pytest.approx(math.sqrt(phi * 9.0))
    assert dist.unit("rebounds") == "reb" and dist.unit("points") == "pts"
