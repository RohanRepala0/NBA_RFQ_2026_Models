"""The ESPN roster check: page parsing, name matching, the mechanical rotation that replaces a
player who isn't on the team, and the `roster` command end to end (no network)."""
from __future__ import annotations

import shutil

import pandas as pd
import pytest

from cold_start_usage import cli, config, rosters
from cold_start_usage.pipeline import snapshot_from_file
from tests.fixtures.synthetic import FETCHED, TIP, events_response, synthetic_event

DAY = TIP.date()
MIA_ROSTER = ["Bam Adebayo", "Andrew Wiggins", "Davion Mitchell", "Tim Hardaway Jr.", "Pelle Larsson",
              "Bobby Portis", "Nikola Jovic", "Simone Fontecchio", "Nick Richards", "Dru Smith"]   # no Giannis


def page(*names: str) -> str:
    """An ESPN roster page, reduced to the part the parser reads."""
    rows = ",".join(f'{{"name":"{n}","href":"https://www.espn.com/nba/player/_/id/{i}/x"}}'
                    for i, n in enumerate(names))
    return f'<html><script>window.__espn={{"athletes":[{rows}]}};</script></html>'


def test_roster_page_names_and_matching():
    assert rosters.parse_espn_roster(page("Bam Adebayo", "Nikola Vu\\u010devi\\u0107", "Bam Adebayo")) == [
        "Bam Adebayo", "Nikola Vučević"]
    assert rosters.roster_url("NYK").endswith("/name/ny") and rosters.roster_url("MIA").endswith("/name/mia")
    assert rosters.on_roster("Nikola Vučević", ["Nikola Vucevic"])            # accents
    assert rosters.on_roster("Derrick Jones Jr.", ["Derrick Jones"])          # suffixes
    assert rosters.on_roster("Cameron Payne", ["Cam Payne"])                  # same last name and initial
    known = {"Bones Hyland", "Kris Murray", "Keegan Murray"}
    scen = pd.DataFrame({"scenario": "x", "player": ["Bones Hyland", "Kris Murray"], "proj_mpg": [20.0, 20.0]})
    # A nickname matches the roster's only Hyland; Kris is not the roster's Keegan Murray.
    assert rosters.off_roster(scen, ["Nah'Shon Hyland", "Keegan Murray"], known).player.tolist() == ["Kris Murray"]


def test_rotation_without_a_player_sums_to_240_and_starts_from_the_auto_file(tmp_path):
    scen_dir = tmp_path / "scenarios"
    shutil.copytree(config.SCENARIOS_DIR, scen_dir)
    rows = rosters.scenario_without("MIA", "full_strength", "full_strength_roster", ["Giannis Antetokounmpo"],
                                    roster=MIA_ROSTER, scenarios_dir=scen_dir)
    assert rows.proj_mpg.sum() == pytest.approx(240.0) and "Giannis Antetokounmpo" not in set(rows.player)
    assert rows.proj_mpg.max() <= rosters.MINUTES_CAP + 0.2
    assert "full_strength_roster" in set(pd.read_csv(scen_dir / "MIA.csv").scenario)
    with pytest.raises(ValueError, match="already exists"):
        rosters.scenario_without("MIA", "full_strength", "full_strength_roster", ["Bam Adebayo"],
                                 scenarios_dir=scen_dir)
    # A team with only the catalog's auto file gets a reviewed file, its full_strength copied in first.
    (scen_dir / "auto").mkdir()
    pd.DataFrame({"scenario": "full_strength", "player": [f"Player {c}" for c in "ABCDEFGHIJ"],
                  "proj_mpg": [24.0] * 10}).to_csv(scen_dir / "auto" / "XYZ.csv", index=False)
    none = pd.DataFrame(columns=["player", "team_2026_27", "mpg"])
    out = rosters.scenario_without("XYZ", "full_strength", "a_out", ["Player A"], scenarios_dir=scen_dir, players=none)
    assert out.proj_mpg.sum() == pytest.approx(240.0) and len(out) == 9
    assert set(pd.read_csv(scen_dir / "XYZ.csv").scenario) == {"full_strength", "a_out"}


def test_roster_command_flags_then_applies(storage, tmp_path, monkeypatch, capsys):
    scen_dir = tmp_path / "scenarios"
    shutil.copytree(config.SCENARIOS_DIR, scen_dir)
    monkeypatch.setattr(config, "SCENARIOS_DIR", scen_dir)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(rosters, "PAUSE_S", 0.0)
    reads = []
    monkeypatch.setattr(rosters, "fetch_roster_page", lambda team: reads.append(team) or page(*MIA_ROSTER))
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    check = cli.build_parser().parse_args(["roster", "--date", DAY.isoformat()])
    assert cli.cmd_roster(check, storage, lambda: FETCHED) == 0
    out = capsys.readouterr().out
    assert "Giannis Antetokounmpo" in out and "--apply" in out
    assert reads == ["MIA"]                                       # MIN has no minutes file: nothing to check
    assert (tmp_path / "data" / "rosters" / DAY.isoformat() / "MIA.html").exists()
    apply = cli.build_parser().parse_args(["roster", "--date", DAY.isoformat(), "--apply"])
    assert cli.cmd_roster(apply, storage, lambda: FETCHED) == 0
    assert "wrote full_strength_roster" in capsys.readouterr().out
    latest = storage.query("""SELECT scenario, player_name FROM projections
                              WHERE team = 'MIA' AND ts = (SELECT max(ts) FROM projections WHERE team = 'MIA')""")
    assert set(latest.scenario) == {"full_strength_roster"}
    assert "Giannis Antetokounmpo" not in set(latest.player_name)
    assert cli.cmd_roster(check, storage, lambda: FETCHED) == 0          # the new rotation is in force
    assert "match their ESPN rosters" in capsys.readouterr().out
    # After tip there is nothing left to check.
    assert cli.cmd_roster(check, storage, lambda: TIP) == 1
