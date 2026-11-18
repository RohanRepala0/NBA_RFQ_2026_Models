"""Step 2 (CFB): college football totals model, metrics from the exported games and the posted week files.

Inputs
    perf_report/data/cfb/games_2022_2026.csv   from cfb_export.py (every game, model vs market probabilities)
    perf_report/data/cfb/2026/week-NN/bets.csv the posted week files (status `posted` = live, before kickoff;
                                               `backfilled` = published after the games, backtest)

Samples
    backtest_2022_2025   walk-forward signals under the headline rule (totals at SP+'s early-week O/U, EV >= +2%
                         at -110), each season fit only on earlier seasons
    walkforward_2026     the same rule on 2026 weeks 1-11 (fit on 2021-2025 only)
    live_2026            signals posted before kickoff (weeks 7, 8 graded; week 12 pending)

Definitions
    p (binary)   P(win) / (P(win) + P(loss)) for the signal's side at the early number, pushes excluded
    benchmarks   the closing market (a distribution centred on the closing total, priced at the same early
                 line: "what the close says this exact bet was worth") and the early market (centred on the
                 early number itself, ~50%)
    CLV          closing total minus the early number, in the bet's favour, in points; and in probability
                 (close p - 0.50), 1pp = 1c on a $1 binary contract. clv_net subtracts the season's average
                 early-to-close drift (totals fall every season, which flatters unders)
    units        1 unit risked per signal at -110: win +0.909, push 0, loss -1. ROI = units / signals.
                 No dollars: no real bets were logged (cfb log-bet table is empty), so $ P&L is not available.

    python perf_report/scripts/cfb_metrics.py   ->  perf_report/data/cfb/metrics.json and CSVs
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import DATA  # noqa: E402
from stats_util import (boot_ci, brier, calibration, conf_flag, log_loss, longest_run,  # noqa: E402
                        max_drawdown, mean_ci, paired, wilson)

CFB = DATA / "cfb"
WIN = 100 / 110
BREAK_EVEN = 110 / 210


def outcome(final: float, side: str, line: float) -> str:
    if final == line:
        return "push"
    return "win" if (final > line) == (side == "over") else "loss"


def load_games() -> pd.DataFrame:
    g = pd.read_csv(CFB / "games_2022_2026.csv")
    g["start_date"] = pd.to_datetime(g.start_date, utc=True)
    g["units"] = g.result.map({"win": WIN, "push": 0.0, "loss": -1.0})
    g["y"] = g.result.map({"win": 1.0, "loss": 0.0})                   # pushes -> NaN (excluded)
    g["p_model"] = g.model_p_win / (g.model_p_win + g.model_p_loss)
    g["p_close"] = g.close_p_win / (g.close_p_win + g.close_p_loss)
    g["p_early_mkt"] = g.early_mkt_p_win / (g.early_mkt_p_win + g.early_mkt_p_loss)
    g["clv_prob_pp"] = (g.p_close - 0.5) * 100
    drift = (g.close_total - g.early_total).groupby(g.season).mean()   # all games of the season
    g["season_drift"] = g.season.map(drift)
    g["clv_net_points"] = g.clv_points - np.where(g.side == "over", 1.0, -1.0) * g.season_drift
    return g


def scores(d: pd.DataFrame) -> dict:
    d = d.dropna(subset=["y", "p_model", "p_close"])
    out = {"n": len(d)}
    for name, col in (("model", "p_model"), ("close_market", "p_close"), ("early_market", "p_early_mkt")):
        out[f"brier_{name}"] = float(brier(d[col], d.y).mean()) if len(d) else None
        out[f"logloss_{name}"] = float(log_loss(d[col], d.y).mean()) if len(d) else None
    out["brier_gap_vs_close"] = paired(brier(d.p_close, d.y), brier(d.p_model, d.y))       # + = model better
    out["logloss_gap_vs_close"] = paired(log_loss(d.p_close, d.y), log_loss(d.p_model, d.y))
    out["brier_gap_vs_early_market"] = paired(brier(d.p_early_mkt, d.y), brier(d.p_model, d.y))
    out["logloss_gap_vs_early_market"] = paired(log_loss(d.p_early_mkt, d.y), log_loss(d.p_model, d.y))
    return out


def record_block(d: pd.DataFrame, label: str) -> dict:
    d = d.sort_values(["start_date", "game_id"])
    w, l, p = int((d.result == "win").sum()), int((d.result == "loss").sum()), int((d.result == "push").sum())
    clv = d.dropna(subset=["clv_points"])
    weekly = d.groupby(["season", "week"]).units.sum()
    wsd = float(weekly.std(ddof=1)) if len(weekly) > 1 else float("nan")
    blk = {
        "sample": label, "signals": len(d), "confidence": conf_flag(len(d)),
        "date_range": [str(d.start_date.min().date()), str(d.start_date.max().date())] if len(d) else None,
        "record": f"{w}-{l}-{p}", "win_rate_ex_push": wilson(w, w + l), "break_even": BREAK_EVEN,
        "units": float(d.units.sum()), "roi_per_unit": mean_ci(d.units),
        "units_ci_by_week": boot_ci(d, lambda x: x.units.sum(), cluster="wk") if len(d) > 1 else None,
        "expected_wins_model": float(d.dropna(subset=["y"]).p_model.sum()),
        "wins": w,
        "avg_ev_at_entry": mean_ci(d.ev),
        "avg_edge_pp_model_minus_50": mean_ci((d.p_model - 0.5) * 100),
        "clv_points": mean_ci(clv.clv_points), "clv_points_median": float(clv.clv_points.median()) if len(clv) else None,
        "clv_net_points": mean_ci(clv.clv_net_points),
        "clv_prob_pp": mean_ci(clv.clv_prob_pp), "clv_prob_pp_median": float(clv.clv_prob_pp.median()) if len(clv) else None,
        "beat_close": wilson(float((clv.clv_points > 0).sum()), len(clv)),
        "tied_close": wilson(float((clv.clv_points == 0).sum()), len(clv)),
        "worse_than_close": wilson(float((clv.clv_points < 0).sum()), len(clv)),
        "scores_on_signals": scores(d),
        "max_drawdown_units": max_drawdown(d.units),
        "longest_losing_streak": longest_run(d.result == "loss"),
        "weeks": int(len(weekly)), "losing_weeks": int((weekly < 0).sum()),
        "sharpe_weekly_units": float(weekly.mean() / wsd) if wsd and not np.isnan(wsd) else None,
    }
    return blk


def live_block(games: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    parts = []
    for f in sorted((CFB / "2026").glob("week-*/bets.csv")):
        b = pd.read_csv(f)
        if len(b):
            parts.append(b)
    allb = pd.concat(parts, ignore_index=True)
    live = allb[allb.status == "posted"].copy()
    live = live.merge(games[["game_id", "final_total", "close_total", "early_total"]].drop_duplicates("game_id"),
                      on="game_id", how="left")
    live["graded"] = live.result.isin(["win", "loss", "push"])
    # grade each total again at the number your book actually showed when it was posted (week 8 onward)
    has_now = live.get("now_line") is not None
    live["result_at_now_line"] = [
        outcome(r.final_total, r.side, r.now_line) if (r.market == "total" and r.graded and has_now
                                                        and not pd.isna(r.now_line)) else ""
        for r in live.itertuples()]
    live["units_at_now_line"] = live.result_at_now_line.map({"win": WIN, "push": 0.0, "loss": -1.0})
    g = live[live.graded]
    w, l, p = (int((g.result == x).sum()) for x in ("win", "loss", "push"))
    n_now = g[g.result_at_now_line != ""]
    # The graded live totals are the walk-forward signals (same game, side and line): take their CLV and
    # probabilities from the per-game export, and check that the side and line really match.
    gt = g[g.market == "total"]
    wfm = games[games.signal & (games.season == 2026)].set_index("game_id")
    m = gt.join(wfm[["side", "early_total", "clv_points", "p_model", "p_close", "y", "clv_prob_pp"]],
                on="game_id", rsuffix="_wf")
    same = (m.side == m.side_wf) & (m.line == m.early_total_wf)
    m = m[same]
    blk_scores = scores(m.assign(p_early_mkt=0.5)) if len(m) else None
    blk = {
        "posted": len(live), "graded": len(g), "pending": int((~live.graded).sum()),
        "confidence": conf_flag(len(g)),
        "first_posted_utc": str(live.posted_at.min()),
        "weeks_posted": sorted(live.week.unique().tolist()),
        "graded_totals_matched_to_walkforward": f"{len(m)} of {len(gt)}",
        "clv_points": mean_ci(m.clv_points), "clv_prob_pp": mean_ci(m.clv_prob_pp),
        "beat_close": wilson(float((m.clv_points > 0).sum()), len(m)),
        "scores": blk_scores,
        "record_at_posted_number": f"{w}-{l}-{p}", "win_rate_ex_push": wilson(w, w + l),
        "units_at_posted_number": float(g.units.sum()), "roi_per_unit": mean_ci(g.units),
        "regraded_at_book_number_when_posted": {
            "n": len(n_now), "record": "-".join(str(int((n_now.result_at_now_line == x).sum()))
                                                for x in ("win", "loss", "push")),
            "units": float(n_now.units_at_now_line.sum()),
            "units_same_picks_at_posted_number": float(n_now.units.sum()),
            "share_with_now_ev_below_2pct": float((n_now.now_ev < 0.02).mean()) if len(n_now) else None,
            # CLV still available when posted: closing total vs your book's number at posting time
            "clv_points_from_book_number": mean_ci(np.where(n_now.side == "over", n_now.close_total - n_now.now_line,
                                                            n_now.now_line - n_now.close_total)) if len(n_now) else None,
            "clv_points_from_early_number_same_picks": mean_ci(np.where(n_now.side == "over",
                                                                        n_now.close_total - n_now.line,
                                                                        n_now.line - n_now.close_total))
            if len(n_now) else None},
        "week12_pending": live[live.week == 12][["kickoff", "game", "rule", "pick", "ev", "now_line", "now_ev"]]
        .astype(str).to_dict(orient="records"),
    }
    return blk, live


def main() -> None:
    g = load_games()
    g["wk"] = g.season.astype(str) + "-" + g.week.astype(str).str.zfill(2)
    sig = g[g.signal]
    bt = sig[sig.season <= 2025]
    wf26 = sig[(sig.season == 2026) & (sig.week <= 11)]
    out = {"definitions": {k: v for k, v in {
        "p": "push-excluded P(win) of the signal's side at the early number",
        "positive gap": "the model scored better than that benchmark on the same bets",
        "close benchmark": "closing-market distribution priced at the bet's own early line",
        "units": "1 unit risked per signal at -110; no $ amounts (no real bets logged)",
        "clv_net_points": "CLV minus the season's average early-to-close drift (sign by side)"}.items()}}
    out["backtest_2022_2025"] = record_block(bt, "walk-forward backtest 2022-2025 (fit on earlier seasons only)")
    out["walkforward_2026_w1_11"] = record_block(wf26, "2026 weeks 1-11, walk-forward (fit on 2021-2025)")
    out["backtest_2022_2025"]["by_season"] = {int(s): {"signals": len(d), "record": record_block(d, str(s))["record"],
                                                      "units": float(d.units.sum()),
                                                      "clv_points": float(d.clv_points.mean())}
                                              for s, d in bt.groupby("season")}
    out["backtest_2022_2025"]["by_side"] = {s: {"signals": len(d), "record": record_block(d, s)["record"],
                                               "units": float(d.units.sum()), "clv_points": float(d.clv_points.mean()),
                                               "clv_net_points": float(d.clv_net_points.mean())}
                                           for s, d in bt.groupby("side")}
    # every game, not only signals: is the model's probability at the early number better than the market's?
    allg = g[g.season <= 2025]
    out["all_games_2022_2025"] = {"games": int(allg.y.notna().sum()), "at_early_number": scores(allg),
                                  "at_close_p_over": {
                                      "n": int(allg.dropna(subset=["over_at_close", "model_p_over_at_close"]).shape[0]),
                                      "logloss_model": float(log_loss(*allg.dropna(subset=["over_at_close", "model_p_over_at_close"])[
                                          ["model_p_over_at_close", "over_at_close"]].T.values).mean()),
                                      "logloss_market_0.5": float(np.log(2)),
                                      "brier_model": float(brier(*allg.dropna(subset=["over_at_close", "model_p_over_at_close"])[
                                          ["model_p_over_at_close", "over_at_close"]].T.values).mean()),
                                      "brier_market_0.5": 0.25}}
    live, live_rows = live_block(g)
    out["live_2026"] = live
    cal = pd.concat([calibration(allg.dropna(subset=["y"]).p_model, allg.dropna(subset=["y"]).y)
                     .assign(sample="all games 2022-2025, model p at early number"),
                     calibration(bt.dropna(subset=["y"]).p_model, bt.dropna(subset=["y"]).y)
                     .assign(sample="signals 2022-2025"),
                     calibration(bt.dropna(subset=["y"]).p_close, bt.dropna(subset=["y"]).y)
                     .assign(sample="signals 2022-2025, closing market p")])
    cal.to_csv(CFB / "calibration.csv", index=False)
    for name, d in (("backtest_2022_2025", bt), ("walkforward_2026", wf26)):
        dd = d.sort_values(["start_date", "game_id"]).assign(cum_units=lambda x: x.units.cumsum())
        dd.to_csv(CFB / f"signals_{name}.csv", index=False)
        dd.groupby("wk").units.sum().reset_index().assign(cum_units=lambda x: x.units.cumsum()).to_csv(
            CFB / f"weekly_units_{name}.csv", index=False)
    live_rows.to_csv(CFB / "live_signals_2026.csv", index=False)
    (CFB / "metrics.json").write_text(json.dumps(out, indent=1, default=float))
    for k in ("backtest_2022_2025", "walkforward_2026_w1_11"):
        b = out[k]
        print(k, b["signals"], b["record"], f"units {b['units']:+.2f}", f"clv {b['clv_points']['value']:+.2f}")
    print("live", live["record_at_posted_number"], f"{live['units_at_posted_number']:+.2f}u",
          "regraded:", live["regraded_at_book_number_when_posted"])
    print(f"wrote {CFB}/metrics.json")


if __name__ == "__main__":
    main()
