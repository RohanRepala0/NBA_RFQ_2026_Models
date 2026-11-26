"""Is everyone in a team's minutes actually on the team? ESPN's public team roster pages, read once
per team per slate (Rohan's ask), checked against the scenario the team's game is projected with.

A player in the minutes who isn't on the roster (released, traded, unsigned) gets no prop and plays
no minutes, so his teammates are projected short. `scenario_without` writes a reviewed scenario with
such players taken out: their minutes go to the rest in proportion to their minutes (cap 37), and the
rotation is topped up to 9 from players on the roster. Mechanical minutes, so review them.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from pathlib import Path
from typing import Callable

import pandas as pd

from . import config
from .usage_model import load_players, scenario_path

ROSTER_URL = "https://www.espn.com/nba/team/roster/_/name/{slug}"
ESPN_SLUG = {"GSW": "gs", "NOP": "no", "NYK": "ny", "SAS": "sa", "UTA": "utah", "WAS": "wsh"}  # else lower-case
USER_AGENT = "Mozilla/5.0 (cold-start-usage-research/1.0)"
MIN_ROSTER = 8                 # fewer names than this: the page didn't parse, so check nothing
MINUTES_CAP = 37.0
ROTATION_SIZE = 9
PAUSE_S = 2.0                  # between roster pages: one at a time, politely
_PLAYER = re.compile(r'"name":"((?:[^"\\]|\\.)+)","href":"https://www\.espn\.com/nba/player/_/id/\d+')
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def roster_url(team: str) -> str:
    return ROSTER_URL.format(slug=ESPN_SLUG.get(team, team.lower()))


def fetch_roster_page(team: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(roster_url(team), headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def parse_espn_roster(page: str) -> list[str]:
    """Player names on an ESPN team roster page, in page order, once each."""
    seen: dict[str, None] = {}
    for raw in _PLAYER.findall(page):
        seen.setdefault(json.loads(f'"{raw}"'), None)
    return list(seen)


def _parts(name: str) -> list[str]:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = [re.sub(r"[^a-z]", "", w) for w in ascii_name.replace("-", " ").split()]
    return [w for w in words if w and w not in _SUFFIXES]


def _direct(me: list[str], others: list[list[str]], known: set[tuple] = frozenset()) -> list[int]:
    """Roster indexes for the same name (ignoring accents, punctuation and Jr./III), else for the
    same last name and first initial (Cam / Cameron) where that roster name isn't another player we
    know (Keegan Murray on the roster is not Kris Murray)."""
    exact = [i for i, o in enumerate(others) if o == me]
    return exact or [i for i, o in enumerate(others)
                     if o and me and o[-1] == me[-1] and o[0][0] == me[0][0] and tuple(o) not in known]


def _known(names) -> set[tuple]:
    return {tuple(_parts(k)) for k in (names or ())}


def on_roster(player: str, roster: list[str], known: set[str] | None = None) -> bool:
    me = _parts(player)
    return bool(me) and bool(_direct(me, [_parts(r) for r in roster], _known(known)))


def off_roster(scen: pd.DataFrame, roster: list[str], known: set[str] | None = None) -> pd.DataFrame:
    """Rows of one scenario whose player isn't on the roster. Beyond direct matches, a player
    matches the one roster player left with his last name that no one else matched (a nickname,
    Bones / Nah'Shon), unless that roster name is itself a player we know (`known`, names from the
    players file): Keegan Murray on the roster is not Kris Murray."""
    known_parts = _known(known)
    others = [_parts(r) for r in roster]
    matched, claimed = set(), set()
    for p in scen.player:
        hits = _direct(_parts(p), others, known_parts)
        if hits:
            matched.add(p)
            claimed.add(hits[0])
    for p in scen.player:
        me = _parts(p)
        if p in matched or not me:
            continue
        left = [i for i, o in enumerate(others)
                if o and o[-1] == me[-1] and i not in claimed and tuple(o) not in known_parts]
        if len(left) == 1:
            matched.add(p)
            claimed.add(left[0])
    return scen[~scen.player.isin(matched)]


def scenario_without(team: str, base: str, new: str, outs: list[str], roster: list[str] | None = None,
                     scenarios_dir: Path | None = None, players: pd.DataFrame | None = None) -> pd.DataFrame:
    """Write scenario `new` = `base` minus `outs` into the team's reviewed file (copying the auto
    file's full_strength there first if the team has no reviewed file) and return its rows."""
    scenarios_dir = scenarios_dir or config.SCENARIOS_DIR
    reviewed = scenarios_dir / f"{team}.csv"
    if not reviewed.exists():
        source = scenario_path(team, scenarios_dir)
        if source is None:
            raise ValueError(f"{team}: no minutes file to start from")
        auto = pd.read_csv(source)
        auto[auto.scenario == "full_strength"].to_csv(reviewed, index=False, float_format="%.1f")
    df = pd.read_csv(reviewed)
    if new in set(df.scenario):
        raise ValueError(f"{team}: scenario {new} already exists")
    rows = df[df.scenario == base][["player", "proj_mpg"]]
    if rows.empty:
        raise ValueError(f"{team}: no scenario {base}")
    gone = {tuple(_parts(o)) for o in outs}
    keep = rows[~rows.player.map(lambda p: tuple(_parts(p)) in gone).astype(bool)].reset_index(drop=True)
    pool = float(rows.proj_mpg.sum() - keep.proj_mpg.sum())
    players = load_players() if players is None else players
    bench = players[(players.team_2026_27 == team) & ~players.player.isin(keep.player)
                    & ~players.player.map(lambda p: tuple(_parts(p)) in gone).astype(bool)]
    if roster is not None:
        bench = bench[bench.player.map(lambda p: on_roster(p, roster, set(players.player))).astype(bool)]
    for r in bench.sort_values("mpg", ascending=False).itertuples():
        if len(keep) >= ROTATION_SIZE or pool <= 0:
            break
        add = round(min(pool, 0.6 * r.mpg, 14.0), 1)
        keep.loc[len(keep)] = [r.player, add]
        pool -= add
    while pool > 0.05:
        room = (MINUTES_CAP - keep.proj_mpg).clip(lower=0)
        weight = keep.proj_mpg.where(room > 0, 0)
        if weight.sum() <= 0:
            raise ValueError(f"{team}: no room left under the {MINUTES_CAP:g}-minute cap")
        give = (pool * weight / weight.sum()).clip(upper=room)
        keep.proj_mpg += give
        pool -= float(give.sum())
    keep.proj_mpg = keep.proj_mpg.round(1)
    top = keep.proj_mpg.idxmax()                         # the rounding remainder goes to the top player
    keep.loc[top, "proj_mpg"] = round(keep.loc[top, "proj_mpg"] + 240 - keep.proj_mpg.sum(), 1)
    keep = keep.sort_values("proj_mpg", ascending=False)
    keep.insert(0, "scenario", new)
    pd.concat([df, keep], ignore_index=True).to_csv(reviewed, index=False, float_format="%.1f")
    return keep.reset_index(drop=True)


def check_teams(teams: dict[str, str], fetch: Callable[[str], str] = fetch_roster_page,
                save_dir: Path | None = None, scenarios_dir: Path | None = None,
                sleep: Callable[[float], None] | None = None) -> tuple[dict[str, list[str]], pd.DataFrame, list[str]]:
    """For each team -> the scenario its game uses: read the roster page (saved under `save_dir`),
    and list that scenario's players who aren't on it. Returns (rosters, off-roster rows, notes)."""
    from .usage_model import load_scenarios
    known = set(load_players().player)
    rosters, found, notes = {}, [], []
    for i, (team, scenario) in enumerate(sorted(teams.items())):
        if i and sleep:
            sleep(PAUSE_S)
        try:
            page = fetch(team)
        except Exception as exc:
            notes.append(f"{team}: roster page not read ({type(exc).__name__})")
            continue
        if save_dir is not None:
            save_dir.mkdir(parents=True, exist_ok=True)
            (save_dir / f"{team}.html").write_text(page)
        names = parse_espn_roster(page)
        if len(names) < MIN_ROSTER:
            notes.append(f"{team}: only {len(names)} names parsed from the roster page; not checked")
            continue
        rosters[team] = names
        scen = load_scenarios(team, scenarios_dir)
        scen = scen[scen.scenario == scenario]
        if scen.empty:
            notes.append(f"{team}: no scenario {scenario} in its minutes file")
            continue
        found.append(off_roster(scen, names, known).assign(team=team))
    off = pd.concat(found, ignore_index=True) if found else pd.DataFrame(columns=["team", "scenario", "player",
                                                                                   "proj_mpg"])
    return rosters, off[["team", "scenario", "player", "proj_mpg"]], notes
