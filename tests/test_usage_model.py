from __future__ import annotations

import pandas as pd
import pytest

from nba_cold_start.config import MODEL
from nba_cold_start.usage_model import (ModelInputError, load_players, load_scenarios, modeled_teams,
                                        project_scenario, solve_scale, validate_minutes)


@pytest.fixture
def players():
    return load_players()


def scen(rows):
    return pd.DataFrame(rows, columns=["player", "proj_mpg"])


def test_minutes_must_sum_to_240(players):
    bad = scen([("Giannis Antetokounmpo", 40), ("Bam Adebayo", 40), ("Andrew Wiggins", 40),
                ("Davion Mitchell", 40), ("Bobby Portis", 40), ("Dru Smith", 39)])   # 239
    with pytest.raises(ModelInputError, match="sum to 239"):
        project_scenario(players, bad)
    validate_minutes(scen([("a", 240.4)]))                                           # within tolerance
    with pytest.raises(ModelInputError):
        validate_minutes(scen([("a", 240.6)]))


def test_player_without_usage_input_fails_loudly(players):
    s = scen([("Kawhi Leonard", 48), ("Scottie Barnes", 48), ("RJ Barrett", 48),
              ("Immanuel Quickley", 48), ("Somebody New", 48)])
    with pytest.raises(ModelInputError, match="No usage input for: \\['Somebody New'\\]"):
        project_scenario(players, s)


def test_duplicate_and_missing_minutes_rejected():
    with pytest.raises(ModelInputError, match="duplicate"):
        validate_minutes(scen([("a", 120), ("a", 120)]))
    with pytest.raises(ModelInputError, match="non-negative"):
        validate_minutes(scen([("a", 240), ("b", None)]))


def test_bundled_scenario_files_are_valid():
    for team in modeled_teams():
        df = load_scenarios(team)
        for _, grp in df.groupby("scenario"):
            assert grp.proj_mpg.sum() == pytest.approx(MODEL.minutes_total, abs=MODEL.minutes_tolerance)


def test_budget_identity_holds_after_rescale(players):
    s = load_scenarios("MIA")
    for _, grp in s.groupby("scenario"):
        res = project_scenario(players, grp)
        assert (res.usg_proj * res.proj_mpg).sum() == pytest.approx(MODEL.usage_budget, rel=1e-6)


def test_vacated_usage_expands_role_players():
    usg = pd.Series([15.0, 15.0, 15.0, 15.0, 15.0])
    mins = pd.Series([48.0] * 5)
    k = solve_scale(usg, mins)
    assert k > 1                                    # 75% demand < 100% budget, everyone expands


def test_unreachable_budget_raises():
    with pytest.raises(ModelInputError, match="not reachable"):
        solve_scale(pd.Series([100.0]), pd.Series([1.0]))     # max demand 100 * 3**0.2 < 4800


def test_players_csv_requires_a_source(tmp_path):
    df = load_players()
    df.loc[0, "source"] = ""
    path = tmp_path / "p.csv"
    df.to_csv(path, index=False)
    with pytest.raises(ModelInputError, match="without a source"):
        load_players(path)
