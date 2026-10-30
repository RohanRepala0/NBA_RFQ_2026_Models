"""Persistence study: parsing Court AI text (checked against its own averages) and the k fit."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cold_start_usage import persistence as P

SEASON = """Jane Doe, 2024-25 Regular Season: team BOS, age 28; GP 60, W 40, L 20.
Per game: PTS 20.0, REB 5.0, AST 4.0, STL 1.0, BLK 0.3, TOV 2.0, MIN 30.0, 3PM 2.0.
Advanced: TS 58.0%, REB% 8.0%, AST% 20.0%, USG 25.0%.
Totals: PTS 1200, REB 300, AST 240, STL 60, BLK 18, TOV 120, MIN 1800, 3PM 120, 3PA 330, FGM 450, FGA 960, FTM 180, FTA 240.
"""


def _logs(market: str, games: list[tuple[str, int, float]], others=(10, 4, 3)) -> str:
    lines = [f"{d} vs NYK: MIN {m}, {market} {v:g}, PTS {others[0]}, REB {others[1]}, AST {others[2]}" for d, m, v in games]
    n = len(games)
    avg = (f"MIN {np.mean([g[1] for g in games]):.2f}; {market} {np.mean([g[2] for g in games]):.2f}; "
           f"PTS {others[0]:.2f}; REB {others[1]:.2f}; AST {others[2]:.2f}.")
    return "\n".join([f"Sample: {n} 2025-26 games for him, {n} matching the filters.",
                      f"Season averages (CourtAI, {n} games): {avg}", "Games, oldest first:", *lines])


def test_parse_season_totals_and_usage():
    s = P.parse_season(SEASON)
    assert s["team"] == "BOS" and s["gp"] == 60 and s["usg"] == 25.0
    assert s["tot_MIN"] == 1800 and s["tot_3PM"] == 120 and s["tot_FTA"] == 240


def test_parse_logs_reads_lines_and_checks_its_own_averages():
    text = _logs("3PM", [("2025-10-22", 30, 2), ("2025-10-24", 34, 4)])
    df = P.parse_logs(text, "3PM")
    assert list(df["3PM"]) == [2, 4] and list(df.MIN) == [30, 34] and df.home.all()
    with pytest.raises(ValueError, match="average"):           # a mis-copied line no longer matches
        P.parse_logs(text.replace("MIN 34, 3PM 4", "MIN 34, 3PM 5"), "3PM")
    with pytest.raises(ValueError, match="sample says"):         # a dropped line
        P.parse_logs("\n".join(text.splitlines()[:-1]), "3PM")


def _write_player(tmp_path, name: str, n: int, early_fga: int, late_fga: int, team: str = "BOS"):
    s = P.slug(name)
    (tmp_path / f"{s}__season_2024-25.txt").write_text(SEASON.replace("team BOS", f"team {team}"))
    dates = pd.date_range("2025-10-22", periods=n, freq="2D").strftime("%Y-%m-%d")
    fga = [early_fga if i < 5 else late_fga for i in range(n)]
    vals = {"FGA": fga, "FTA": [4] * n, "TOV": [2] * n, "3PM": [2] * n}
    for m, v in vals.items():
        (tmp_path / f"{s}__{m}.txt").write_text(_logs(m, [(d, 30, x) for d, x in zip(dates, v)]))


def test_study_scales_the_proxy_to_official_usage_and_fits(tmp_path):
    _write_player(tmp_path, "Jane Doe", 40, early_fga=20, late_fga=20)
    _write_player(tmp_path, "Vít Krejčí", 40, early_fga=10, late_fga=10, team="NYK")
    players = pd.DataFrame({"player": ["Jane Doe", "Vít Krejčí"], "usg_pct": [27.0, 15.0],
                            "team_2025_26": ["BOS", "ATL"]})
    df, notes = P.study(tmp_path, players)
    assert not notes and set(df.player) == {"Jane Doe", "Vít Krejčí"}
    jane = df[(df.player == "Jane Doe") & (df.n == 5)].iloc[0]
    # A steady player: early and late usage both equal his official 2025-26 usage.
    assert jane.early_usg_x_min / jane.early_min == pytest.approx(27.0)
    assert jane.rest_usg_x_min / jane.rest_min == pytest.approx(27.0)
    assert jane.prior_mpg == 30 and jane.prior_points == pytest.approx(1200 / 1800)
    assert df[df.player == "Vít Krejčí"].new_team.all() and not df[df.player == "Jane Doe"].new_team.any()
    assert df.n.max() == 15 and (df.rest_games >= P.MIN_REST_GAMES).all()


def test_fit_finds_no_prior_weight_when_every_shift_lasts(tmp_path):
    # Season-long shifts from the prior (usage 25): the sample alone predicts the rest best.
    for i, (fga, usg) in enumerate([(26, 33.0), (8, 14.0), (18, 27.0), (12, 19.0)]):
        _write_player(tmp_path, f"Player {i}", 40, early_fga=fga, late_fga=fga)
    players = pd.DataFrame({"player": [f"Player {i}" for i in range(4)], "usg_pct": [33.0, 14.0, 27.0, 19.0],
                            "team_2025_26": ["BOS"] * 4})
    df, _ = P.study(tmp_path, players)
    assert P.best_k(df, "usage") == 0.0
    assert P.direction(df, 5)["kept_pct"] == 100.0


def test_fit_leans_on_the_prior_when_early_shifts_fade(tmp_path):
    # Early usage off the prior for 5 games, then back to it: the prior predicts the rest best.
    for i, early in enumerate([26, 8]):
        _write_player(tmp_path, f"Player {i}", 40, early_fga=early, late_fga=16)
    players = pd.DataFrame({"player": ["Player 0", "Player 1"], "usg_pct": [25.0, 25.0], "team_2025_26": ["BOS"] * 2})
    df, _ = P.study(tmp_path, players)
    five = df[df.n == 5]
    assert P.best_k(five, "usage") == max(P.K_GRID)
    assert P.loss(five, "usage", 100) < P.loss(five, "usage", 0)
