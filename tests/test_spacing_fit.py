from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nba_cold_start.fit import add_spacing_columns, fit_efficiency
from nba_cold_start.spacing import (LEAGUE_AVERAGE, load_team_shooting, old_context,
                                    projected_team_shooting, spacing_score)
from nba_cold_start.usage_model import add_spacing


@pytest.fixture
def ref():
    return load_team_shooting()


def test_team_table_is_complete(ref):
    assert len(ref) == 30 and ref.team.is_unique
    assert ref.source.str.startswith("https://").all()


def test_league_mean_scores_fifty_and_scale_is_monotonic(ref):
    assert spacing_score(ref.fg3a_pg.mean(), ref.fg3_pct.mean(), ref) == pytest.approx(LEAGUE_AVERAGE)
    base = spacing_score(36.0, 36.0, ref)
    assert spacing_score(38.0, 36.0, ref) > base and spacing_score(36.0, 37.0, ref) > base
    # No clipping: far outside the league range still moves the score.
    assert spacing_score(25.0, 36.0, ref) < spacing_score(27.0, 36.0, ref)


def test_old_context_for_traded_or_unknown_teams_is_league_average(ref):
    assert old_context("TOT", ref) == LEAGUE_AVERAGE
    assert old_context(None, ref) == LEAGUE_AVERAGE
    assert old_context("MIL", ref) > old_context("TOR", ref)          # 39.1 @ 38.7% vs 32.1 @ 35.4%


def test_projected_team_shooting_scales_with_minutes_and_usage():
    df = pd.DataFrame({"proj_mpg": [120.0, 120.0], "mpg": [30.0, 30.0], "usg_pct": [20.0, 20.0],
                       "usg_proj": [20.0, 10.0], "fg3a_pg": [6.0, 6.0], "fg3_pct": [40.0, 30.0]})
    att, pct, cov = projected_team_shooting(df)
    # 6 * (120/30) * 1.0 = 24 and 6 * 4 * 0.5 = 12 -> 36 attempts; pct weighted by attempts.
    assert att == pytest.approx(36.0) and cov == 1.0
    assert pct == pytest.approx((24 * 40 + 12 * 30) / 36)


def test_spacing_skipped_when_coverage_is_low(ref):
    df = pd.DataFrame({"proj_mpg": [200.0, 40.0], "mpg": [30.0, 30.0], "usg_pct": [20.0, 20.0],
                       "usg_proj": [20.0, 20.0], "fg3a_pg": [None, 6.0], "fg3_pct": [None, 40.0],
                       "team_2025_26": ["MIA", "MIA"]})
    add_spacing(df, ref)
    assert df.spacing_new.isna().all() and (df.spacing_mult == 1.0).all()


def test_fit_recovers_known_coefficients():
    rng = np.random.default_rng(7)
    n = 400
    d_usg = rng.normal(0, 3, n)                  # usg_old - usg_new
    d_spc = rng.normal(0, 8, n)                  # spacing_new - spacing_old
    a, b, c = 0.005, 0.0015, -0.01
    ts_old = rng.uniform(52, 62, n)
    ts_new = ts_old * (1 + a * d_usg + b * d_spc + c + rng.normal(0, 0.01, n))
    df = pd.DataFrame({"player": [f"p{i}" for i in range(n)], "usg_old": 20 + d_usg, "usg_new": 20.0,
                       "ts_old": ts_old, "ts_new": ts_new, "spacing_old": 50.0, "spacing_new": 50 + d_spc,
                       "min_old": 1500, "min_new": 1500})
    res = fit_efficiency(df)
    assert res["n"] == n
    assert res["eff_per_usg_point"] == pytest.approx(a, abs=0.001)
    assert res["spacing_coef"] == pytest.approx(b, abs=0.0005)
    assert res["intercept"] == pytest.approx(c, abs=0.003)


def test_fit_requires_enough_rows_and_filters_small_samples():
    df = pd.DataFrame({"player": list("abcdefghijkl"), "usg_old": 20.0, "usg_new": 18.0, "ts_old": 55.0,
                       "ts_new": 56.0, "spacing_old": 50.0, "spacing_new": 52.0,
                       "min_old": [100] * 6 + [900] * 6, "min_new": 1000})
    with pytest.raises(ValueError, match="at least 10"):
        fit_efficiency(df)


def test_fit_can_derive_spacing_from_team_tables(ref):
    df = pd.DataFrame({"player": ["x"], "team_old": ["MIL"], "team_new": ["MIA"]})
    out = add_spacing_columns(df, ref, ref)
    assert out.spacing_old.iloc[0] == pytest.approx(old_context("MIL", ref))
    assert out.spacing_new.iloc[0] == pytest.approx(old_context("MIA", ref))


def test_missing_shooting_pct_never_blanks_projections(ref):
    df = pd.DataFrame({"proj_mpg": [120.0, 120.0], "mpg": [30.0, 30.0], "usg_pct": [20.0, 20.0],
                       "usg_proj": [20.0, 20.0], "fg3a_pg": [6.0, 4.0], "fg3_pct": [None, None],
                       "team_2025_26": ["MIA", None]})
    add_spacing(df, ref)
    assert (df.spacing_mult == 1.0).all()
