"""League-wide role-change catalog for 2026-27.

Every rotation player whose usage should move, because he changed teams or his
team gained or lost usage, tagged by usage tier (high / medium / low) and by
situation:

- arrival:  on a new team this season
- vacuum:   incumbent on a team whose usage demand is below the 4,800 budget
            (a high-usage player left), so his share should grow
- squeeze:  incumbent on a team whose demand is above the budget (a
            high-usage player arrived), so his share should shrink
- steady:   no meaningful change

Where each player is in 2026-27, in order of precedence:
1. data/roster_overrides_2026_27.csv  (manual corrections, e.g. confirmed signings)
2. data/offseason_moves_2026.csv      (NBA.com offseason tracker, all 30 teams)
3. data/rosters_2026_27_sgo.json      (SportsGameOdds /players; has gaps: some
                                       veterans carry no team, some moves lag)
4. his only 2025-26 team, flagged "assumed"

2025-26 lines come from data/league_2025_26/*.csv (StatMuse team pages,
splits with >= 100 minutes, each row checked against its season totals).
Teams with a reviewed minutes file in nba_cold_start/scenarios/ use it;
every other team gets an automatic full-strength rotation from last season's
minutes, written to nba_cold_start/scenarios/auto/.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from . import config
from .config import MODEL, ModelParams, team_abbr
from .players import name_key
from .spacing import load_team_shooting
from .usage_model import project_scenario

STATMUSE = "https://www.statmuse.com/nba/ask/{slug}-players-usage-rate-2025-26"
TEAM_SLUGS = {
    "ATL": "hawks", "BOS": "celtics", "BKN": "nets", "CHA": "hornets", "CHI": "bulls",
    "CLE": "cavaliers", "DAL": "mavericks", "DEN": "nuggets", "DET": "pistons", "GSW": "warriors",
    "HOU": "rockets", "IND": "indiana-pacers", "LAC": "clippers", "LAL": "lakers", "MEM": "grizzlies",
    "MIA": "heat", "MIL": "bucks", "MIN": "minnesota-timberwolves", "NOP": "pelicans", "NYK": "knicks",
    "OKC": "thunder", "ORL": "magic", "PHI": "76ers", "PHX": "suns", "POR": "portland-trail-blazers",
    "SAC": "kings", "SAS": "spurs", "TOR": "raptors", "UTA": "jazz", "WAS": "wizards",
}
NICKNAMES = {"alex": "alexandre", "herb": "herbert", "nic": "nicolas", "mo": "mohamed",
             "cam": "cameron", "nick": "nicholas", "pj": "pj", "aj": "aj"}


def source_url(team: str) -> str:
    slug = TEAM_SLUGS[team]
    if slug.endswith(("pacers", "timberwolves", "blazers")):
        return f"https://www.statmuse.com/nba/ask/{slug}-usage-rate-2025-26"
    return STATMUSE.format(slug=slug)


def tier(usg: float) -> str:
    if usg >= config.USAGE_TIERS["high"]:
        return "high"
    if usg >= config.USAGE_TIERS["medium"]:
        return "medium"
    return "low"


# --- loading ---------------------------------------------------------------------
def load_league_splits(folder: Path | None = None) -> pd.DataFrame:
    folder = folder or config.DATA_DIR / "league_2025_26"
    frames = []
    for f in sorted(Path(folder).glob("*.csv")):
        d = pd.read_csv(f, thousands=",")
        d["team"] = f.stem
        d["source"] = source_url(f.stem)
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df = df[df["min"] >= 100].copy()
    df["key"] = df.name.map(name_key)
    return df


def combine_lines(splits: pd.DataFrame) -> pd.DataFrame:
    """One 2025-26 line per player across team splits (traded players)."""
    def agg(g: pd.DataFrame) -> pd.Series:
        att = g.fg3a * g.gp
        pct = (att * g.fg3pct.fillna(0)).sum() / att.sum() if att.sum() > 0 else float("nan")
        teams = tuple(sorted(set(g.team)))
        return pd.Series({
            "name": g["name"].iloc[0], "teams_2025_26": teams,
            "team_2025_26": teams[0] if len(teams) == 1 else "TOT",
            "usg_pct": round(float((g.usg * g["min"]).sum() / g["min"].sum()), 2),
            "games": int(g.gp.sum()), "min_total": float(g["min"].sum()),
            "mpg": round(float(g["min"].sum() / g.gp.sum()), 2),
            "ppg": round(float(g.pts.sum() / g.gp.sum()), 2),
            "fg3a_pg": round(float(att.sum() / g.gp.sum()), 2),
            "fg3_pct": round(pct, 1) if not math.isnan(pct) else float("nan"),
            "source": " + ".join(sorted(set(g.source))),
        })
    return splits.groupby("key").apply(agg, include_groups=False).reset_index()


def load_sgo_rosters(path: Path | None = None) -> pd.DataFrame:
    path = path or config.DATA_DIR / "rosters_2026_27_sgo.json"
    teams = json.loads(Path(path).read_text())["teams"]
    rows = [{"player_id": p["player_id"], "sgo_name": p["name"], "sgo_team": team_abbr(tid)}
            for tid, ps in teams.items() for p in ps]
    df = pd.DataFrame(rows)
    df["key"] = df.sgo_name.map(name_key)
    return df


def _load_csv(path: Path, cols: list[str]) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame(columns=cols + ["key"])
    df = pd.read_csv(path)
    df["key"] = df.player.map(name_key)
    return df


def fuzzy_join_keys(keys: pd.Series, candidates: pd.Series) -> dict[str, str]:
    """Map each unmatched key to a candidate key with the same last name and a
    compatible first name (nickname table or shared first 3 letters), if unique."""
    def split(k_name: str) -> tuple[str, str]:
        parts = str(k_name).split()
        return (parts[0].lower(), parts[-1].lower()) if len(parts) > 1 else ("", str(k_name).lower())
    out = {}
    cand = pd.DataFrame({"name": candidates})
    cand["first"], cand["last"] = zip(*cand.name.map(split))
    for name in keys:
        first, last = split(name)
        hits = cand[cand["last"].map(name_key) == name_key(last)]
        f = NICKNAMES.get(first, first)
        hits = hits[hits["first"].map(lambda c: NICKNAMES.get(c, c)[:3] == f[:3])]
        if len(hits) == 1:
            out[name_key(name)] = name_key(hits.name.iloc[0])
    return out


# --- 2026-27 rosters --------------------------------------------------------------------
def resolve_rosters(lines: pd.DataFrame, sgo: pd.DataFrame, moves: pd.DataFrame,
                    overrides: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (players with team_2026_27 and status, conflicts between sources)."""
    lines = lines.copy()
    # Bridge StatMuse <-> SportsGameOdds spellings (Alex/Alexandre Sarr, Herb/Herbert Jones).
    unmatched = lines[~lines.key.isin(set(sgo.key))]
    bridge = fuzzy_join_keys(unmatched.name, sgo.sgo_name)
    lines["sgo_key"] = lines.key.map(lambda k: bridge.get(k, k))
    merged = lines.merge(sgo, left_on="sgo_key", right_on="key", how="left", suffixes=("", "_sgo"))
    move_to = dict(zip(moves.key, moves.to_team))
    override_to = dict(zip(overrides.key, overrides.team))

    def resolve(r) -> tuple[str | None, str]:
        if r.key in override_to:
            return override_to[r.key], "override"
        if r.key in move_to:
            return move_to[r.key], "moves"
        if isinstance(r.sgo_team, str):
            return r.sgo_team, "sgo"
        if len(r.teams_2025_26) == 1:
            return r.teams_2025_26[0], "assumed"
        return None, "unknown"

    merged[["team_2026_27", "roster_source"]] = merged.apply(lambda r: pd.Series(resolve(r)), axis=1)
    conflicts = merged[merged.sgo_team.notna() & merged.team_2026_27.notna()
                       & (merged.sgo_team != merged.team_2026_27)][
        ["name", "teams_2025_26", "sgo_team", "team_2026_27", "roster_source"]]
    merged["status"] = merged.apply(
        lambda r: None if r.team_2026_27 is None else
        ("incumbent" if r.team_2026_27 in r.teams_2025_26 else "arrival"), axis=1)
    return merged.drop(columns=["key_sgo", "sgo_key"], errors="ignore"), conflicts


# --- rotations --------------------------------------------------------------------
def auto_minutes(team_players: pd.DataFrame, n: int = 10, cap: float = 37.0, starters: int = 5,
                 min_games: int = 15, min_mpg: float = 8.0) -> pd.DataFrame:
    """Full-strength rotation from last season's minutes.

    The top `starters` by minutes keep last season's minutes (capped); the bench
    absorbs whatever is left of 240. Scaling all ten evenly would trim every
    starter by 3-4 minutes and bias stars low, which the market readily punishes.
    """
    pool = team_players[(team_players.games >= min_games) & (team_players.mpg >= min_mpg)]
    pool = pool.sort_values("mpg", ascending=False).head(n)
    if len(pool) < 7:
        raise ValueError(f"only {len(pool)} rotation players with a 2025-26 line")
    mins = pool.set_index("player").mpg.astype(float).clip(upper=cap)
    top, bench = mins.iloc[:starters], mins.iloc[starters:]
    target = 240.0 - top.sum()
    if target > 0 and len(bench) and 0.4 <= target / bench.sum() <= 2.0:
        mins = pd.concat([top, (bench * target / bench.sum()).clip(upper=cap)])
    for _ in range(50):                         # proportional fallback / cap clean-up
        capped = mins >= cap - 1e-9
        rest = 240.0 - cap * capped.sum()
        new = mins.copy()
        new[~capped] = (mins[~capped] * rest / mins[~capped].sum()).clip(upper=cap)
        if (new - mins).abs().max() < 1e-9:
            break
        mins = new
    mins = mins.round(1)
    mins.iloc[-1] += round(240.0 - mins.sum(), 1)              # exact 240 after rounding
    return pd.DataFrame({"scenario": "full_strength", "player": mins.index, "proj_mpg": mins.values})


def players_table(resolved: pd.DataFrame, curated: pd.DataFrame | None = None) -> pd.DataFrame:
    """Model input table (usage_model.PLAYER_COLUMNS + shooting + sgo id) for every placed player."""
    df = resolved[resolved.team_2026_27.notna()].copy()
    out = pd.DataFrame({
        "player": df.name, "team_2025_26": df.team_2025_26, "team_2026_27": df.team_2026_27,
        "usg_pct": df.usg_pct, "games": df.games, "mpg": df.mpg, "ppg": df.ppg,
        "fg3a_pg": df.fg3a_pg, "fg3_pct": df.fg3_pct, "verified": "yes", "source": df.source,
        "sgo_player_id": df.player_id,
    })
    if curated is not None and len(curated):
        cur = curated.set_index("player")
        keep = out[~out.player.isin(cur.index)]
        cur = curated.copy()
        cur["team_2026_27"] = cur.player.map(dict(zip(out.player, out.team_2026_27))).fillna(cur.team_2026_27)
        out = pd.concat([keep, cur[out.columns]], ignore_index=True)
    return out.sort_values(["team_2026_27", "player"]).reset_index(drop=True)


# --- the catalog --------------------------------------------------------------------
def prior_teams(resolved: pd.DataFrame, splits: pd.DataFrame, moves: pd.DataFrame,
                overrides: pd.DataFrame | None = None) -> pd.Series:
    """Each player's team in the no-moves world.

    Only listed offseason transactions count (NBA.com tracker + manual overrides).
    A player who sits on a new team without a listed move most likely changed teams
    at the trade deadline with under 100 minutes there (e.g. a mid-season trade),
    so he is treated as already belonging to his current team.
    """
    move_from = dict(zip(moves.key, moves.from_team))
    override_keys = set(overrides.key) if overrides is not None else set()
    games = splits.groupby(["key", "team"]).gp.sum()

    def prior(r) -> str | None:
        if r.key in move_from and move_from[r.key] != r.team_2026_27:
            return move_from[r.key]
        if r.key in override_keys and r.team_2026_27 not in r.teams_2025_26:
            if len(r.teams_2025_26) == 1:
                return r.teams_2025_26[0]
            return games.loc[r.key].idxmax()
        return r.team_2026_27
    return resolved.apply(prior, axis=1)


def _model_table(df: pd.DataFrame, team_col: str) -> pd.DataFrame:
    return pd.DataFrame({
        "player": df.name, "team_2025_26": df.team_2025_26, "team_2026_27": df[team_col],
        "usg_pct": df.usg_pct, "games": df.games, "mpg": df.mpg, "ppg": df.ppg,
        "fg3a_pg": df.fg3a_pg, "fg3_pct": df.fg3_pct, "verified": "yes", "source": df.source,
        "sgo_player_id": df.player_id,
    })


def _project_world(table: pd.DataFrame, team: str, ref, params: ModelParams) -> pd.DataFrame:
    tp = table[table.team_2026_27 == team]
    scen = auto_minutes(tp)
    return project_scenario(table, scen[["player", "proj_mpg"]], params, ref)


def build_catalog(players: pd.DataFrame, resolved: pd.DataFrame, splits: pd.DataFrame | None = None,
                  moves: pd.DataFrame | None = None, overrides: pd.DataFrame | None = None,
                  scenarios_dir: Path | None = None,
                  excluded: set[str] | None = None, params: ModelParams = MODEL,
                  write_auto: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Offseason effect = (2026-27 roster) minus (same roster with no offseason moves),
    both run through the same automatic rotation so the method's own bias cancels.
    Displayed projections use the reviewed minutes file where one exists."""
    scenarios_dir = scenarios_dir or config.SCENARIOS_DIR
    excluded = config.CATALOG_EXCLUDED_TEAMS if excluded is None else excluded
    splits = load_league_splits() if splits is None else splits
    moves = pd.DataFrame(columns=["key", "from_team", "to_team"]) if moves is None else moves
    ref = load_team_shooting()
    placed = resolved[resolved.team_2026_27.notna()].copy()
    placed["prior_team"] = prior_teams(placed, splits, moves, overrides)
    now_tbl = _model_table(placed, "team_2026_27")
    base_tbl = _model_table(placed, "prior_team")

    base = {}
    for team in sorted(set(base_tbl.team_2026_27)):
        try:
            base[team] = _project_world(base_tbl, team, ref, params)
        except ValueError:
            continue
    base_usg = pd.concat(base.values()).set_index("player").usg_proj if base else pd.Series(dtype=float)
    base_demand = {t: float(r.budget_pressure_pct.iloc[0]) for t, r in base.items()}

    rows, teams = [], []
    auto_dir = scenarios_dir / "auto"
    for team in sorted(set(players.team_2026_27) - set(excluded)):
        auto_now = _project_world(now_tbl, team, ref, params)
        effect = float(auto_now.budget_pressure_pct.iloc[0]) - base_demand.get(team, 0.0)
        reviewed = scenarios_dir / f"{team}.csv"
        if reviewed.exists():
            scen = pd.read_csv(reviewed)
            shown = project_scenario(players, scen[scen.scenario == "full_strength"][["player", "proj_mpg"]],
                                     params, ref)
            scen_source = "reviewed"
        else:
            shown = project_scenario(players, auto_minutes(players[players.team_2026_27 == team])
                                     [["player", "proj_mpg"]], params, ref)
            scen_source = "auto"
            if write_auto:
                auto_dir.mkdir(parents=True, exist_ok=True)
                auto_minutes(players[players.team_2026_27 == team]).to_csv(auto_dir / f"{team}.csv", index=False)
        delta = (auto_now.set_index("player").usg_proj - base_usg.reindex(auto_now.player).values)

        left = placed[(placed.prior_team == team) & (placed.team_2026_27 != team)]
        came = placed[(placed.team_2026_27 == team) & (placed.prior_team != team)]

        def top(df: pd.DataFrame) -> str:
            df = df.assign(load=df.usg_pct * df.mpg).sort_values("load", ascending=False).head(3)
            return ", ".join(f"{n} ({u:.1f}%)" for n, u in zip(df.name, df.usg_pct))

        teams.append({
            "team": team, "scenario_source": scen_source, "offseason_usage_effect_pct": round(effect, 1),
            "usage_min_out": round(float((left.usg_pct * left.mpg).sum()), 0),
            "usage_min_in": round(float((came.usg_pct * came.mpg).sum()), 0),
            "top_departures": top(left), "top_arrivals": top(came),
            "spacing_new": round(float(shown.spacing_new.iloc[0]), 1) if shown.spacing_new.notna().any() else None,
        })
        prior = dict(zip(placed.name, placed.prior_team))
        for r in shown.itertuples():
            d_usg = float(delta.get(r.player, float("nan")))
            moved = prior.get(r.player, team) != team
            if moved:
                situation = "arrival"
            elif math.isnan(d_usg):
                situation = "steady"
            elif effect <= -config.CATALOG_PRESSURE_PCT and d_usg >= config.CATALOG_MIN_USG_SHIFT:
                situation = "vacuum"
            elif effect >= config.CATALOG_PRESSURE_PCT and d_usg <= -config.CATALOG_MIN_USG_SHIFT:
                situation = "squeeze"
            else:
                situation = "steady"
            rows.append({
                "team": team, "player": r.player, "sgo_player_id": r.sgo_player_id,
                "team_2025_26": r.team_2025_26, "prior_team": prior.get(r.player, team),
                "tier": tier(r.usg_pct), "situation": situation,
                "usg_2025_26": r.usg_pct, "usg_proj": round(r.usg_proj, 2),
                "usg_change": None if math.isnan(d_usg) else round(d_usg, 2),
                "mpg_2025_26": r.mpg, "proj_mpg": r.proj_mpg, "ppg_2025_26": r.ppg,
                "proj": None if pd.isna(r.ppg_proj) else round(float(r.ppg_proj), 2),
                "sd": None if pd.isna(r.sd_proj) else round(float(r.sd_proj), 2),
                "spacing_old": None if pd.isna(r.spacing_old) else round(float(r.spacing_old), 1),
                "spacing_new": None if pd.isna(r.spacing_new) else round(float(r.spacing_new), 1),
                "team_offseason_effect_pct": round(effect, 1), "scenario_source": scen_source,
            })
    cat = pd.DataFrame(rows)
    cat["thesis"] = cat.apply(lambda r: thesis(r, teams), axis=1)
    return cat, pd.DataFrame(teams)


def thesis(r, teams: list[dict]) -> str:
    info = next(t for t in teams if t["team"] == r.team)
    shift = "" if pd.isna(r.usg_change) else f", offseason effect {r.usg_change:+.1f}"
    arrow = f"usage {r.usg_2025_26:.1f} last season, {r.usg_proj:.1f} projected{shift}"
    if r.situation == "arrival":
        return f"New team ({r.prior_team} -> {r.team}); {arrow}"
    if r.situation == "vacuum":
        return f"{info['top_departures'] or 'Departures'} gone; {arrow}"
    if r.situation == "squeeze":
        return f"{info['top_arrivals'] or 'Arrivals'} added; {arrow}"
    return f"Little change; {arrow}"


def summary(cat: pd.DataFrame) -> pd.DataFrame:
    t = pd.crosstab(cat.tier, cat.situation).reindex(index=["high", "medium", "low"], fill_value=0)
    t = t[[c for c in ("arrival", "vacuum", "squeeze", "steady") if c in t.columns]]
    t["total"] = t.sum(axis=1)
    return t


def catalog_markdown(cat: pd.DataFrame, teams: pd.DataFrame, conflicts: pd.DataFrame,
                     resolved: pd.DataFrame, per_cell: int = 6) -> str:
    counts = summary(cat)
    changed = cat[cat.situation != "steady"]
    lines = [
        "# 2026-27 role-change catalog", "",
        "Generated by `python -m nba_cold_start.cli catalog` (no API calls).",
        "",
        f"**{len(changed)} of {len(cat)} rotation players** on {cat.team.nunique()} teams have an offseason role "
        "change. Tiers use 2025-26 usage: high is 25% or more, medium 18-25%, low under 18%.",
        "",
        "| tier | " + " | ".join(counts.columns) + " |", "|---|" + "---|" * len(counts.columns),
        *[f"| {t} | " + " | ".join(str(int(v)) for v in r.values) + " |" for t, r in counts.iterrows()],
        "",
        "## How it is measured", "",
        "- **Offseason effect, not method noise.** Every team is run twice through the same automatic "
        "rotation: once on its 2026-27 roster, once with this summer's moves undone. The difference is the "
        "offseason's effect on each player's usage, so the rotation method's own bias cancels out.",
        "- **Situations.** *arrival*: new team. *vacuum*: incumbent on a team that lost usage (team effect "
        f"<= -{config.CATALOG_PRESSURE_PCT:g}%) whose own usage rises by >= {config.CATALOG_MIN_USG_SHIFT:g} points. "
        "*squeeze*: the reverse. *steady*: everything else.",
        "- **Where players are.** Manual overrides, then the NBA.com offseason tracker, then SportsGameOdds "
        f"rosters, then last season's team ({(resolved.roster_source == 'assumed').sum()} players assumed). "
        "Only listed offseason moves count as arrivals or departures, so trade-deadline moves don't.",
        "- **Projections** use reviewed minutes where they exist (MIA, TOR) and the automatic rotation "
        "elsewhere, which assumes everyone is healthy and ignores rookies.",
        "- **Model property.** The elasticity spreads a team's usage change almost evenly in *points*, so "
        "low-usage players get the biggest *relative* change. That is where the model has the most to say.",
        "",
        "## Teams by offseason usage effect", "",
        "| team | effect | usage-min out | usage-min in | biggest departures | biggest arrivals |",
        "|---|---|---|---|---|---|",
        *[f"| {t.team} | {t.offseason_usage_effect_pct:+.1f}% | {t.usage_min_out:.0f} | {t.usage_min_in:.0f} | "
          f"{t.top_departures} | {t.top_arrivals} |"
          for t in teams.sort_values("offseason_usage_effect_pct").itertuples()],
    ]
    for tier_name in ("high", "medium", "low"):
        lines += ["", f"## {tier_name.capitalize()} usage"]
        for sit in ("vacuum", "arrival", "squeeze"):
            part = changed[(changed.tier == tier_name) & (changed.situation == sit)].copy()
            if part.empty:
                continue
            part["mag"] = part.usg_change.abs()
            part = part.sort_values("mag", ascending=False).head(per_cell)
            lines += ["", f"**{sit}** ({int(((changed.tier == tier_name) & (changed.situation == sit)).sum())})", "",
                      "| player | team | usage 25-26 | offseason shift | ppg 25-26 | proj |", "|---|---|---|---|---|---|"]
            lines += [f"| {r.player} | {r.team} | {r.usg_2025_26:.1f} | {r.usg_change:+.1f} | {r.ppg_2025_26:.1f} | "
                      f"{r.proj:.1f} |" for r in part.itertuples()]
    if len(conflicts):
        lines += ["", "## Roster conflicts to confirm", "",
                  "SportsGameOdds and the NBA.com tracker disagree. The resolved team is used; add a row to "
                  "`data/roster_overrides_2026_27.csv` to correct one.", "",
                  "| player | SportsGameOdds | resolved | from |", "|---|---|---|---|"]
        lines += [f"| {r.name} | {r.sgo_team} | {r.team_2026_27} | {r.roster_source} |" for r in conflicts.itertuples()]
    return "\n".join(lines) + "\n"
