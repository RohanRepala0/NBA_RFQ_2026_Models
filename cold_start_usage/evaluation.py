"""Walk-forward check of the projection sources against what happened and against the books.

For every game with box scores and a projection run logged before tip:
- season: the projections actually logged (each team's last run before tip);
- rolling: recomputed as of that tip with the same scenarios (features.py reads only earlier
  ET dates' box scores), never logged;
- books: the closing consensus mean per stat (t-15m snapshot, else the latest before tip).

Scored against the box-score actuals on the player-games all three cover: MAE and bias per
stat, Brier on the books' closing lines, and minutes for the two model sources. The extra
stats (threes, steals, blocks, turnovers) have no book line stored: rolling against actuals only.
"""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from . import config, distributions
from .features import RATE_STATS
from .pipeline import close_consensus, events_on, run_projections
from .schedule import et_date
from .storage import Storage

BOX_COL = {"points": "pts", "rebounds": "reb", "assists": "ast", **{s: RATE_STATS[s] for s in config.EXTRA_STATS}}
PRINTED_COL = {"points": "proj", "rebounds": "reb", "assists": "ast", **{s: s for s in config.EXTRA_STATS}}


def _logged_runs(storage: Storage, event_id: str, starts: datetime) -> pd.DataFrame:
    """Each team's last projection run for the game before tip."""
    return storage.query("""
        WITH runs AS (SELECT team, max(ts) AS ts FROM projections WHERE event_id = ? AND ts < ? GROUP BY team)
        SELECT p.* REPLACE (coalesce(p.stat, 'points') AS stat)
        FROM projections p JOIN runs USING (team, ts) WHERE p.event_id = ?""", [event_id, starts, event_id])


def walk_forward(storage: Storage, since: date, until: date | None = None) -> pd.DataFrame:
    """One row per player-game and stat: season, rolling, books (mean, line, P(over)), actual,
    and minutes for the model sources."""
    teams = storage.query("SELECT DISTINCT event_id, starts_at FROM team_box_scores")
    dates = sorted({et_date(t) for t in teams.starts_at})
    dates = [d for d in dates if d >= since and (until is None or d <= until)]
    boxed = set(teams.event_id)
    out = []
    for d in dates:
        for ev in events_on(storage, d).itertuples():
            if ev.event_id not in boxed:
                continue
            starts = pd.Timestamp(ev.starts_at).to_pydatetime()
            logged = _logged_runs(storage, ev.event_id, starts)
            if logged.empty:
                continue
            choice = logged.groupby("team").scenario.first().to_dict()
            roll, _ = run_projections(storage, d, starts - pd.Timedelta(minutes=1), choice, log=False,
                                      event_ids={ev.event_id}, source="rolling")
            roll = roll[roll.player_id != "UNMAPPED"].drop_duplicates("player_id").set_index("player_id")
            actual = storage.query("SELECT * FROM box_scores WHERE event_id = ? AND played",
                                   [ev.event_id]).drop_duplicates("player_id").set_index("player_id")
            season = logged.pivot_table(index="player_id", columns="stat", values="mean", aggfunc="first")
            season_min = logged.groupby("player_id").proj_mpg.first()
            names = logged.groupby("player_id").player_name.first()
            cons = {s: close_consensus(storage, ev.event_id, starts, stat=s)[0] for s in config.STATS}
            for pid in sorted(set(actual.index) & (set(roll.index) | set(season.index))):
                a = actual.loc[pid]
                for stat, col in BOX_COL.items():
                    c = cons.get(stat, {}).get(pid)
                    ok = c is not None and c.mean is not None and c.n_books >= config.MIN_PRICED_BOOKS
                    out.append({
                        "event_id": ev.event_id, "et_date": d, "player_id": pid,
                        "player": names.get(pid, a.player_name), "team": a.team, "stat": stat,
                        "season": season.at[pid, stat] if pid in season.index and stat in season.columns else np.nan,
                        "rolling": roll.at[pid, PRINTED_COL[stat]] if pid in roll.index else np.nan,
                        "books": c.mean if ok else np.nan, "line": c.line if ok else np.nan,
                        "p_books": c.p_over if ok else np.nan, "actual": a[col],
                        "season_min": season_min.get(pid, np.nan),
                        "rolling_min": roll.at[pid, "min"] if pid in roll.index else np.nan,
                        "actual_min": a.minutes, "role": roll.at[pid, "role"] if pid in roll.index else None,
                        "in_season_rotation": pid in season.index})
    df = pd.DataFrame(out)
    for col in ("season", "rolling", "books", "line", "p_books", "actual", "season_min", "rolling_min", "actual_min"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _p(stat: str, mean, line) -> float:
    if pd.isna(mean) or pd.isna(line):
        return np.nan
    return distributions.p_over(stat, max(float(mean), 0.01), float(line))


def summarize(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """'accuracy': per stat on the player-games every source covers; 'minutes'; 'extra'."""
    acc = []
    for stat in config.STATS:
        part = df[(df.stat == stat)].dropna(subset=["season", "rolling", "books", "actual"])
        if part.empty:
            continue
        row = {"stat": stat, "n": len(part)}
        for src in ("season", "rolling", "books"):
            err = part[src] - part.actual
            row[f"mae_{src}"], row[f"bias_{src}"] = err.abs().mean(), err.mean()
        lined = part.dropna(subset=["line", "p_books"])
        y = (lined.actual > lined.line).astype(float)
        row["n_lines"] = len(lined)
        for src in ("season", "rolling"):
            p = np.array([_p(stat, m, ln) for m, ln in zip(lined[src], lined.line)])
            row[f"brier_{src}"] = float(np.mean((p - y) ** 2)) if len(lined) else np.nan
        row["brier_books"] = float(np.mean((lined.p_books - y) ** 2)) if len(lined) else np.nan
        acc.append(row)
    mins = df[df.stat == "points"].dropna(subset=["season_min", "rolling_min", "actual_min"])
    minutes = pd.DataFrame([{"n": len(mins),
                             **{f"{k}_{src}": f(mins[f"{src}_min"] - mins.actual_min)
                                for src in ("season", "rolling")
                                for k, f in (("mae", lambda e: e.abs().mean()), ("bias", lambda e: e.mean()))}}])
    deep = df[(df.stat == "points") & ~df.in_season_rotation].dropna(subset=["rolling_min", "actual_min"])
    minutes["n_beyond_rotation"] = len(deep)
    minutes["rolling_bias_beyond_rotation"] = (deep.rolling_min - deep.actual_min).mean() if len(deep) else np.nan
    extra = []
    for stat in config.EXTRA_STATS:
        part = df[df.stat == stat].dropna(subset=["rolling", "actual"])
        if len(part):
            err = part["rolling"] - part.actual
            extra.append({"stat": stat, "n": len(part), "mae_rolling": err.abs().mean(), "bias_rolling": err.mean(),
                          "mean_actual": part.actual.mean()})
    return {"accuracy": pd.DataFrame(acc), "minutes": minutes, "extra": pd.DataFrame(extra)}


def by_date(df: pd.DataFrame) -> pd.DataFrame:
    """Points MAE per ET date on the common player-games (rolling only differs once there's history)."""
    part = df[df.stat == "points"].dropna(subset=["season", "rolling", "books", "actual"])
    g = part.assign(e_s=(part.season - part.actual).abs(), e_r=(part["rolling"] - part.actual).abs(),
                    e_b=(part.books - part.actual).abs())
    return g.groupby("et_date").agg(n=("e_s", "size"), mae_season=("e_s", "mean"), mae_rolling=("e_r", "mean"),
                                    mae_books=("e_b", "mean")).reset_index()


def markdown(summary: dict[str, pd.DataFrame], dates: pd.DataFrame, since: date, until: date | None) -> str:
    def table(df: pd.DataFrame) -> list[str]:
        if df.empty:
            return ["(none)"]
        cols = list(df.columns)
        fmt = lambda v: f"{v:.3f}" if isinstance(v, float) else str(v)  # noqa: E731
        return ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + [
            "| " + " | ".join(fmt(v) for v in r) + " |" for r in df.itertuples(index=False)]
    span = f"{since} to {until}" if until else f"from {since}"
    lines = ["# Model v2: walk-forward evaluation", "",
             f"Every graded game {span} with box scores and a projection run logged before tip. "
             "`season` is what was logged live; `rolling` is recomputed as of each tip with the same "
             "scenarios, from earlier dates' box scores only; `books` is the closing consensus mean. "
             "Errors are projection minus actual, on the player-games all three cover. The opening "
             "week shaped the rolling design, so it is in-sample; later nights are out of sample. "
             "Generated by `python -m cold_start_usage.cli evaluate --docs`.", "",
             "## Points, rebounds, assists", ""] + table(summary["accuracy"]) + [
             "", "## Minutes", "",
             "`beyond_rotation`: players the logged season run didn't project (mostly the bench rolling "
             "adds from the team's last 5 games, plus a few the season run left unmapped).", ""] + table(summary["minutes"]) + [
             "", "## Points MAE by date", ""] + table(dates) + [
             "", "## Logged-only stats (no book line stored)", ""] + table(summary["extra"]) + [""]
    return "\n".join(lines)
