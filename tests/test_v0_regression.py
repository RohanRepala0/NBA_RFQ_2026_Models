"""The package must reproduce the v0 reference implementation exactly (+-0.01).

Inputs are frozen copies in tests/fixtures/regression/, so editing the live data
in data/ never moves these numbers. Spacing is computed but must not change any
projection while spacing_coef is 0.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from cold_start_usage.config import MODEL
from cold_start_usage.spacing import load_team_shooting
from cold_start_usage.usage_model import load_players, project_team

REPO = Path(__file__).resolve().parents[1]
V0 = REPO / "v0" / "usage_model.py"
FROZEN = REPO / "tests" / "fixtures" / "regression"

# Usage demand vs budget (%), then projected points, as produced by v0 on the frozen inputs.
EXPECTED = {
    "MIA": {"full_strength": (8.9, {"Giannis Antetokounmpo": 30.17, "Bam Adebayo": 19.14, "Bobby Portis": 10.52}),
            "giannis_out": (-2.2, {"Bam Adebayo": 22.06, "Bobby Portis": 16.13}),
            "bam_out": (6.1, {"Giannis Antetokounmpo": 32.46, "Bobby Portis": 15.09})},
    "TOR": {"full_strength": (3.1, {"Kawhi Leonard": 27.35, "Scottie Barnes": 17.92, "RJ Barrett": 18.69}),
            "kawhi_out": (-8.2, {"Scottie Barnes": 20.66, "RJ Barrett": 22.20})},
}


def run_v0(team: str, tmp: Path) -> pd.DataFrame:
    shutil.copy(V0, tmp / "usage_model.py")
    shutil.copy(FROZEN / "players_2025_26.csv", tmp / "players_2025_26.csv")
    shutil.copy(FROZEN / "scenarios" / f"{team}.csv", tmp / "scenarios.csv")
    subprocess.run([sys.executable, "usage_model.py"], cwd=tmp, check=True, capture_output=True)
    return pd.read_csv(tmp / "projections.csv")


def check(df: pd.DataFrame, team: str) -> None:
    for scenario, (pressure, points) in EXPECTED[team].items():
        s = df[df.scenario == scenario].set_index("player")
        assert s.budget_pressure_pct.iloc[0] == pytest.approx(pressure, abs=0.01)
        for player, pts in points.items():
            assert s.loc[player, "ppg_proj"] == pytest.approx(pts, abs=0.01), (team, scenario, player)
    assert "Giannis Antetokounmpo" not in set(df[df.scenario == "giannis_out"].player)
    assert "Kawhi Leonard" not in set(df[df.scenario == "kawhi_out"].player)


@pytest.mark.parametrize("team", ["MIA", "TOR"])
def test_v0_reference_reproduces_expected(team, tmp_path):
    check(run_v0(team, tmp_path), team)


@pytest.mark.parametrize("team", ["MIA", "TOR"])
def test_package_matches_v0_with_spacing_off(team, tmp_path):
    v0 = run_v0(team, tmp_path)
    res = project_team(team, load_players(FROZEN / "players_2025_26.csv"), scenarios_dir=FROZEN / "scenarios",
                       team_shooting=load_team_shooting(FROZEN / "team_shooting_2025_26.csv"))
    check(res, team)
    assert res.spacing_new.notna().all() and (res.spacing_mult == 1.0).all()
    merged = res.merge(v0, on=["scenario", "player"], suffixes=("", "_v0"), validate="one_to_one")
    assert len(merged) == len(v0)
    for col in ("usg_proj", "ppg_proj", "fair_line", "budget_pressure_pct"):
        diff = (merged[col].round(2) - merged[f"{col}_v0"]).abs().max()
        assert pd.isna(diff) or diff <= 0.01, col


def test_spacing_coef_moves_projections_in_the_right_direction():
    players = load_players(FROZEN / "players_2025_26.csv")
    ref = load_team_shooting(FROZEN / "team_shooting_2025_26.csv")
    base = project_team("MIA", players, scenarios_dir=FROZEN / "scenarios", team_shooting=ref)
    on = project_team("MIA", players, scenarios_dir=FROZEN / "scenarios", team_shooting=ref,
                      params=replace(MODEL, spacing_coef=0.002))
    m = base.merge(on, on=["scenario", "player"], suffixes=("", "_on"))
    worse = m[m.spacing_delta < 0]
    better = m[m.spacing_delta > 0]
    assert len(worse) and (worse.ppg_proj_on < worse.ppg_proj).all()
    assert len(better) and (better.ppg_proj_on > better.ppg_proj).all()
