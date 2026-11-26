"""CFB totals model: export per-game and per-bet probabilities from the CollegeFootballRatings2026 DuckDB.

Run it with the CFB repo's own environment (it imports `cfbmodel` and needs `data/cfb.duckdb` built:
see perf_report/data/cfb/PROVENANCE.md):

    cd $CFB_REPO && uv run python $NBA_REPO/perf_report/scripts/cfb_export.py

It replays the walk-forward loop of `cfbmodel.totals.run` (the same functions, fit only on seasons
before each test season) for 2022-2025 and for 2026, and for EVERY game with an early total and a
model total writes:
    - the model's blended total at the early number and at the close
    - the side the headline rule takes at the early number, its EV at -110, and whether it is a signal
    - P(win) / P(push) / P(loss) for that side from the model, from the closing market, and from the
      early market (each a distribution centred on that total)
    - the model's P(over) at the closing total, and the result
Then checks that its signals reproduce `totals.run` (2022-2025) and `record.season_signals` (2026).

    -> perf_report/data/cfb/games_2022_2026.csv
"""

from __future__ import annotations

import sys
from copy import copy
from pathlib import Path

import numpy as np
import pandas as pd
from cfbmodel import db, totals
from cfbmodel.backtest import BacktestConfig
from cfbmodel.blend import combine, fit_weights
from cfbmodel.conventions import american_to_decimal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import DATA  # noqa: E402

OUT = DATA / "cfb"


def probs(dist, centre: float, side: str, line: float) -> tuple[float, float, float]:
    return totals.total_probs(dist.pmf(centre), side, line)


def season_rows(frame, sources, dist_df, cfg, s) -> list[dict]:
    train, test = frame[frame.season < s], frame[frame.season == s]
    dtrain = dist_df[dist_df.season < s]
    name = cfg.distribution if cfg.distribution in totals.REGISTRY else totals.best_model(
        dtrain, cfg.distribution_metric, min_train=max(1, dtrain.season.nunique() - 2))
    dist = totals.make(name).fit(dtrain.center.values, dtrain.total.values)
    weights = fit_weights(train[sources], train.total)
    f_train, f_test = combine(train[sources], weights), combine(test[sources], weights)
    a_close = totals._alpha(f_train, train.mkt_total.values, train.total.values, cfg)
    a_early = totals._alpha(f_train, train.early_total.values, train.total.values, cfg)
    payout = american_to_decimal(cfg.american) - 1
    rows = []
    for g, f in zip(test.itertuples(), f_test):
        if pd.isna(f) or pd.isna(g.early_total) or pd.isna(g.total):
            continue
        m_early = float(a_early.blend(np.array([g.early_total]), np.array([f]))[0])
        m_close = float(a_close.blend(np.array([g.mkt_total]), np.array([f]))[0]) if not pd.isna(g.mkt_total) else np.nan
        quotes = []
        for side in ("over", "under"):
            w, p, l = probs(dist, m_early, side, g.early_total)
            quotes.append((w * payout - l, side, w, p, l))
        ev, side, w, p, l = max(quotes)
        row = {"season": s, "week": g.week, "game_id": g.game_id, "start_date": g.start_date,
               "game": f"{g.away_team} at {g.home_team}", "early_total": g.early_total, "close_total": g.mkt_total,
               "final_total": g.total, "F": float(f), "model_total_early": m_early, "model_total_close": m_close,
               "distribution": name, "alpha_early": a_early.alpha, "alpha_close": a_close.alpha,
               "side": side, "ev": ev, "signal": ev >= cfg.min_ev,
               "model_p_win": w, "model_p_push": p, "model_p_loss": l,
               "result": totals.total_outcome(int(g.total), side, g.early_total)}
        if not pd.isna(g.mkt_total):
            cw, cp, cl = probs(dist, g.mkt_total, side, g.early_total)
            ow, _, ol = probs(dist, m_close, "over", g.mkt_total)
            row.update({"close_p_win": cw, "close_p_push": cp, "close_p_loss": cl,
                        "clv_points": (g.mkt_total - g.early_total) if side == "over" else (g.early_total - g.mkt_total),
                        "model_p_over_at_close": ow / (ow + ol) if ow + ol else np.nan,
                        "over_at_close": np.nan if g.total == g.mkt_total else float(g.total > g.mkt_total)})
        ew, ep, el = probs(dist, g.early_total, side, g.early_total)
        row.update({"early_mkt_p_win": ew, "early_mkt_p_push": ep, "early_mkt_p_loss": el})
        rows.append(row)
    return rows


def main() -> None:
    con = db.connect()
    base = BacktestConfig.from_settings()
    out = []
    # 2022-2025: exactly the CLI's backtest-totals configuration
    frame, sources = totals.totals_frame(con, base)
    dist_df = totals.distribution_frame(con, base)
    for s in sorted(frame.season.unique())[base.min_train_seasons:]:
        out += season_rows(frame, sources, dist_df, base, s)
    # 2026: the record's configuration (2026 added to the frame, fit on earlier seasons only)
    cfg26 = copy(base)
    cfg26.seasons = sorted(set(base.seasons) | {2026})
    f26, src26 = totals.totals_frame(con, cfg26)
    d26 = totals.distribution_frame(con, cfg26)
    out += season_rows(f26, src26, d26, cfg26, 2026)
    df = pd.DataFrame(out)
    df["start_date"] = pd.to_datetime(df.start_date, utc=True)
    df = df.sort_values(["season", "start_date", "game_id"]).reset_index(drop=True)

    # Reproduction checks against the repo's own functions
    ref = totals.run(con, base).bets["blend_early"]
    mine = df[(df.season <= 2025) & df.signal]
    ok_bt = (len(ref) == len(mine) and set(ref.game_id) == set(mine.game_id)
             and abs(ref.profit.sum() - mine.result.map({"win": 0.9090909, "push": 0, "loss": -1}).sum()) < 1e-3)
    from cfbmodel.record import season_signals
    rec = season_signals(con, base, 2026)
    rec = rec[(rec.market == "total") & (rec.timing == "early")]
    mine26 = df[(df.season == 2026) & df.signal]
    ok_26 = set(rec.game_id) == set(mine26.game_id)
    print(f"2022-2025 signals: {len(mine)} (totals.run: {len(ref)}) reproduce={ok_bt}")
    print(f"2026 signals (games with finals): {len(mine26)} (record: {len(rec)}) reproduce={ok_26}")
    if not (ok_bt and ok_26):
        raise SystemExit("export does not reproduce the repo's signals; not writing")
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "games_2022_2026.csv", index=False)
    print(f"wrote {OUT / 'games_2022_2026.csv'} ({len(df)} games)")


if __name__ == "__main__":
    main()
