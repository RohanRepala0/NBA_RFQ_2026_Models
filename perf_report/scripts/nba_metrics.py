"""Step 2: NBA cold-start player-prop model (Kalshi + Polymarket US): every metric from the bets/ journal.

Inputs (all committed in this repo):
    bets/ledger.csv              one row per paper ticket (first actionable decision per player-game and stat)
    bets/fills.csv               fills logged by hand with `cli fill` (real, paper or discretionary)
    bets/days/*/tickets.csv      every actionable row at every checkpoint (repeats flagged)
    bets/days/*/summary.md       the journal's own day totals (used only as a cross-check)

What a "trade" is here: a PAPER ticket at the system's suggested size and logged all-in cost. No
fill of any kind was logged (bets/fills.csv is header-only), so real-money P&L is not available.

Definitions
    y            1 if the ticket's side won, 0 if lost, the fair-price fraction for a scratch
    p_model      p_blend: the traded probability (sportsbook consensus mean moved 20% toward the model)
    p_close      close_mid: mid of the last two-sided venue book read before tip (normally the T-5m read),
                 for the ticket's side. This is the market benchmark.
    p_entry      ask when first actionable (the venue price paid, before fee)
    p_books      p_market: the sportsbook consensus alone (no model)
    CLV          close_mid - ask, in cents per contract and as % of the ask
    P&L          suggested_contracts x (settlement value - all-in cost); cost = ask + venue fee (+ any
                 walk up the book) at the suggested size, so P&L is net of Kalshi / Polymarket US fees

    python perf_report/scripts/nba_metrics.py
    -> perf_report/data/nba/*.csv, perf_report/data/nba/metrics.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import DATA, NBA_REPO  # noqa: E402
from stats_util import (boot_ci, brier, calibration, conf_flag, log_loss, longest_run,  # noqa: E402
                        max_drawdown, mean_ci, paired, wilson)

sys.path.insert(0, str(NBA_REPO))
from cold_start_usage.fees import fee_total  # noqa: E402  (the repo's own fee schedule and rounding)

OUT = DATA / "nba"


def load() -> pd.DataFrame:
    df = pd.read_csv(NBA_REPO / "bets/ledger.csv")
    df["tip_utc"] = pd.to_datetime(df.tip_utc, utc=True)
    df["first_seen_utc"] = pd.to_datetime(df.first_seen_utc, utc=True)
    df = df.sort_values(["tip_utc", "first_seen_utc", "signal_id"]).reset_index(drop=True)
    settled = df.outcome.isin(["won", "lost", "fair price"])
    df["settled"] = settled
    side_value = np.where(df.side == "YES", df.settlement_value, 1 - df.settlement_value)
    df["y"] = np.where(settled, side_value, np.nan)
    df["contracts"] = df.suggested_contracts
    df["stake_usd"] = df.suggested_stake_usd
    df["pnl_usd"] = df.pnl_suggested_usd
    # execution cost per ticket = contracts x (all-in cost - ask); split into the venue fee (recomputed
    # with cold_start_usage/fees.py at the ask) and the remainder (walk up the book / rounding).
    df["exec_cost_usd"] = df.contracts * (df.cost - df.ask)
    df["fee_usd"] = [fee_total(v, c, a) for v, c, a in zip(df.venue, df.contracts, df.ask)]
    df["book_walk_usd"] = df.exec_cost_usd - df.fee_usd
    df["gross_pnl_usd"] = df.contracts * (df.y - df.ask)          # before fees and book walk
    df["edge_model"] = df.p_blend - df.ask                         # model prob minus price, pre-fee
    df["edge_books"] = df.p_market - df.ask
    df["clv_c"] = (df.close_mid - df.ask) * 100                    # cents per contract
    df["clv_pct"] = (df.close_mid - df.ask) / df.ask * 100         # % of the entry price
    df["clv_net_c"] = (df.close_mid - df.cost) * 100               # vs the all-in cost (after fee)
    df["clv_implied_pnl_usd"] = df.contracts * (df.close_mid - df.cost)   # P&L if the close were the truth
    df["month"] = df.tip_utc.dt.tz_convert("America/New_York").dt.strftime("%Y-%m")
    return df


def score_block(d: pd.DataFrame) -> dict:
    """Brier / log loss of the model vs the market on the same settled contracts, with paired intervals."""
    d = d[d.settled & d.close_mid.notna()]
    y = d.y.values
    out = {"n": len(d)}
    for name, col in (("model_p_blend", "p_blend"), ("venue_close_mid", "close_mid"), ("venue_entry_ask", "ask"),
                      ("sportsbook_consensus", "p_market")):
        out[f"brier_{name}"] = float(brier(d[col], y).mean()) if len(d) else None
        out[f"logloss_{name}"] = float(log_loss(d[col], y).mean()) if len(d) else None
    # positive gap = the model scored better than that benchmark
    for bench, col in (("close", "close_mid"), ("entry", "ask"), ("books", "p_market")):
        out[f"brier_gap_vs_{bench}"] = paired(brier(d[col], y), brier(d.p_blend, y))
        out[f"logloss_gap_vs_{bench}"] = paired(log_loss(d[col], y), log_loss(d.p_blend, y))
    return out


def summary_block(d: pd.DataFrame) -> dict:
    s = d[d.settled]
    wins = float((s.outcome == "won").sum())
    clv = d.dropna(subset=["close_mid"])
    return {
        "tickets": len(d), "settled": len(s), "confidence": conf_flag(len(s)),
        "date_range_et": [str(d.date_et.min()), str(d.date_et.max())] if len(d) else None,
        "win_rate": wilson(wins, len(s)),
        "hits": float(s.y.sum()), "expected_hits_model": float(s.p_blend.sum()),
        "expected_hits_close": float(s.close_mid.sum()), "expected_hits_entry_ask": float(s.ask.sum()),
        "expected_hits_books": float(s.p_market.sum()),
        "stake_usd_median": float(d.stake_usd.median()) if len(d) else None,
        "stake_usd_max": float(d.stake_usd.max()) if len(d) else None,
        "contracts_median": float(d.contracts.median()) if len(d) else None,
        "hits_minus_expected_model_z": float((s.y.sum() - s.p_blend.sum()) / np.sqrt((s.p_blend * (1 - s.p_blend)).sum()))
        if len(s) else None,
        "avg_edge_model_minus_ask": mean_ci(d.edge_model),
        "avg_edge_books_minus_ask": mean_ci(d.edge_books),
        "avg_ev_after_fee_model": mean_ci(d.ev_blend),
        "clv_cents": mean_ci(clv.clv_c), "clv_cents_median": float(clv.clv_c.median()) if len(clv) else None,
        "clv_pct": mean_ci(clv.clv_pct), "clv_pct_median": float(clv.clv_pct.median()) if len(clv) else None,
        "clv_net_of_fee_cents": mean_ci(clv.clv_net_c),
        "clv_beat_close": wilson(float((clv.clv_c > 1e-9).sum()), len(clv)),
        "clv_tied_close": wilson(float((clv.clv_c.abs() <= 1e-9).sum()), len(clv)),
        "clv_worse_than_close": wilson(float((clv.clv_c < -1e-9).sum()), len(clv)),
        "contracts": int(d.contracts.sum()), "capital_deployed_usd": float(d.stake_usd.sum()),
        "pnl_net_usd": float(s.pnl_usd.sum()), "pnl_gross_before_exec_usd": float(s.gross_pnl_usd.sum()),
        "fees_usd": float(s.fee_usd.sum()), "book_walk_and_rounding_usd": float(s.book_walk_usd.sum()),
        "pnl_per_contract_usd": float(s.pnl_usd.sum() / s.contracts.sum()) if len(s) else None,
        "roi_on_capital": float(s.pnl_usd.sum() / s.stake_usd.sum()) if len(s) else None,
        "clv_implied_pnl_usd": float(clv.clv_implied_pnl_usd.sum()),
        "scores": score_block(d),
    }


def split(df: pd.DataFrame, by: str) -> pd.DataFrame:
    rows = []
    for key, d in df.groupby(by, sort=True):
        b = summary_block(d)
        sc = b["scores"]
        rows.append({by: key, "tickets": b["tickets"], "confidence": b["confidence"],
                     "win_rate": b["win_rate"]["value"], "win_lo": b["win_rate"]["lo"], "win_hi": b["win_rate"]["hi"],
                     "hits": b["hits"], "expected_hits_model": b["expected_hits_model"],
                     "brier_model": sc["brier_model_p_blend"], "brier_close": sc["brier_venue_close_mid"],
                     "brier_gap_vs_close": sc["brier_gap_vs_close"]["value"],
                     "brier_gap_se": sc["brier_gap_vs_close"]["se"],
                     "logloss_model": sc["logloss_model_p_blend"], "logloss_close": sc["logloss_venue_close_mid"],
                     "mean_clv_c": b["clv_cents"]["value"], "clv_c_lo": b["clv_cents"]["lo"],
                     "clv_c_hi": b["clv_cents"]["hi"], "median_clv_c": b["clv_cents_median"],
                     "pct_beat_close": b["clv_beat_close"]["value"],
                     "avg_edge_model_minus_ask": b["avg_edge_model_minus_ask"]["value"],
                     "capital_usd": b["capital_deployed_usd"], "pnl_net_usd": b["pnl_net_usd"],
                     "fees_usd": b["fees_usd"], "roi": b["roi_on_capital"]})
    return pd.DataFrame(rows)


def journal_crosscheck(df: pd.DataFrame) -> pd.DataFrame:
    """The journal's own per-day P&L (summary.md) against the ledger, so a mismatch is caught."""
    rows = []
    for f in sorted((NBA_REPO / "bets/days").glob("*/summary.md")):
        txt = f.read_text()
        m = re.search(r"- P&L: ([+-]?)\$([\d,]+\.\d+)", txt)
        jr = (-1 if m and m.group(1) == "-" else 1) * float(m.group(2).replace(",", "")) if m else None
        led = float(df[df.date_et == f.parent.name].pnl_usd.sum())
        rows.append({"date_et": f.parent.name, "journal_pnl_usd": jr, "ledger_pnl_usd": round(led, 2),
                     "match": jr is not None and abs(jr - led) < 0.011})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = load()
    fills = pd.read_csv(NBA_REPO / "bets/fills.csv")
    actionable = pd.concat([pd.read_csv(f).assign(day=f.parent.name)
                            for f in sorted((NBA_REPO / "bets/days").glob("*/tickets.csv"))], ignore_index=True)
    flag_kind = actionable.flag.fillna("").str.extract(r"^(ticket|repeat|new contract)")[0]

    s = df[df.settled]
    head = summary_block(df)
    # intervals that respect same-slate correlation (bets on one night move together)
    roi = lambda d: d.pnl_usd.sum() / d.stake_usd.sum()                     # noqa: E731
    head["roi_ci_by_ticket"] = boot_ci(s, roi)
    head["roi_ci_by_date"] = boot_ci(s, roi, cluster="date_et")
    head["pnl_ci_by_ticket"] = boot_ci(s, lambda d: d.pnl_usd.sum())
    head["pnl_ci_by_date"] = boot_ci(s, lambda d: d.pnl_usd.sum(), cluster="date_et")
    head["brier_gap_vs_close_ci_by_date"] = boot_ci(
        s, lambda d: float((brier(d.close_mid, d.y) - brier(d.p_blend, d.y)).mean()), cluster="date_et")
    head["clv_cents_ci_by_date"] = boot_ci(s, lambda d: float(d.clv_c.mean()), cluster="date_et")
    head["clv_median_ci_by_ticket"] = boot_ci(s, lambda d: float(d.clv_c.median()))

    # daily series, drawdown, streaks, Sharpe
    daily = (s.groupby("date_et").agg(tickets=("signal_id", "count"), capital_usd=("stake_usd", "sum"),
                                      pnl_usd=("pnl_usd", "sum"), wins=("y", "sum"))
             .reset_index())
    daily["return_on_day_capital"] = daily.pnl_usd / daily.capital_usd
    daily["cum_pnl_usd"] = daily.pnl_usd.cumsum()
    d_m = mean_ci(daily.pnl_usd)
    sd = float(daily.pnl_usd.std(ddof=1))
    r_sd = float(daily.return_on_day_capital.std(ddof=1))
    head["daily"] = {
        "trading_days": len(daily), "confidence": conf_flag(len(daily)),
        "mean_daily_pnl_usd": d_m, "sd_daily_pnl_usd": sd,
        "sharpe_daily_pnl": float(daily.pnl_usd.mean() / sd) if sd else None,
        "sharpe_daily_return": float(daily.return_on_day_capital.mean() / r_sd) if r_sd else None,
        "sharpe_se_approx": float(np.sqrt((1 + 0.5 * (daily.pnl_usd.mean() / sd) ** 2) / len(daily))) if sd else None,
        "losing_days": int((daily.pnl_usd < 0).sum()), "longest_losing_day_run": longest_run(daily.pnl_usd < 0),
        "max_drawdown_daily": max_drawdown(daily.pnl_usd),
    }
    seq = s.reset_index(drop=True)
    seq["cum_pnl_usd"] = seq.pnl_usd.cumsum()
    head["per_ticket_path"] = {"max_drawdown": max_drawdown(seq.pnl_usd),
                               "longest_losing_streak_tickets": longest_run(seq.outcome == "lost"),
                               "longest_winning_streak_tickets": longest_run(seq.outcome == "won")}
    head["pipeline_counts"] = {
        "actionable_rows_logged": len(actionable),
        "actionable_rows_by_flag": flag_kind.value_counts().to_dict(),
        "tickets": len(df), "fills_logged_any_kind": len(fills),
        "real_fills": int((fills.get("kind", pd.Series(dtype=str)) == "real").sum()),
        "paper_fills": int((fills.get("kind", pd.Series(dtype=str)) == "paper").sum()),
    }
    # capacity: contracts the book offered at or under the limit price when each ticket was first actionable
    tk = actionable[actionable.flag == "ticket"].merge(df[["signal_id", "contracts"]], on="signal_id")
    head["capacity_at_ticket"] = {
        "n": len(tk), "size_at_edge_median": float(tk.size_at_edge.median()),
        "size_at_edge_p25": float(tk.size_at_edge.quantile(0.25)),
        "size_at_edge_p75": float(tk.size_at_edge.quantile(0.75)),
        "size_at_edge_sum": float(tk.size_at_edge.sum()),
        "dollars_at_edge_sum_usd": float((tk.size_at_edge * tk.ask).sum()),
        "suggested_contracts_median": float(tk.contracts.median()),
        "share_where_suggested_exceeds_offered": float((tk.contracts > tk.size_at_edge).mean()),
        "by_venue_median_size_at_edge": tk.merge(df[["signal_id", "venue"]], on="signal_id")
        .groupby("venue_y").size_at_edge.median().to_dict(),
    }
    head["definitions"] = {
        "trade": "paper ticket at suggested size (no fill logged; real-money P&L not available)",
        "close": "mid of the last two-sided venue book read before tip (normally the T-5m checkpoint), ticket side",
        "clv": "close_mid - ask; cents per contract; pct = / ask",
        "pnl": "contracts x (settlement value - all-in cost); net of Kalshi / Polymarket US taker fees",
        "fees_usd": "recomputed at the ask with cold_start_usage/fees.py; book_walk = (cost-ask)*contracts - fee",
        "positive brier/logloss gap": "the model (p_blend) scored better than the benchmark on the same contracts",
    }
    head["tickets_by_venue"] = df.venue.value_counts().to_dict()
    head["tickets_by_stat"] = df.stat.value_counts().to_dict()

    cal_model = calibration(s.p_blend, s.y).assign(forecast="model p_blend")
    cal_close = calibration(s.close_mid, s.y).assign(forecast="venue close mid")
    pd.concat([cal_model, cal_close]).to_csv(OUT / "calibration.csv", index=False)

    for by in ("stat", "venue", "month", "date_et", "checkpoint", "side"):
        split(df, by).to_csv(OUT / f"by_{by}.csv", index=False)
    daily.to_csv(OUT / "daily_pnl.csv", index=False)
    seq[["date_et", "tip_utc", "player", "stat", "contract", "venue", "outcome", "pnl_usd", "cum_pnl_usd"]].to_csv(
        OUT / "cumulative_pnl_by_ticket.csv", index=False)
    cols = ["date_et", "tip_utc", "game", "player", "team", "stat", "contract", "side", "venue", "checkpoint", "ask",
            "cost", "p_blend", "p_market", "close_mid", "y", "outcome", "contracts", "stake_usd", "fee_usd",
            "book_walk_usd", "gross_pnl_usd", "pnl_usd", "edge_model", "edge_books", "ev_blend", "clv_c", "clv_pct",
            "clv_net_c", "clv_implied_pnl_usd", "n_books", "consensus_mean", "model_mean", "signal_id"]
    df[cols].to_csv(OUT / "tickets_enriched.csv", index=False)
    cc = journal_crosscheck(df)
    cc.to_csv(OUT / "journal_crosscheck.csv", index=False)
    head["journal_crosscheck_all_days_match"] = bool(cc.match.all())

    (OUT / "metrics.json").write_text(json.dumps(head, indent=1, default=float))
    print(json.dumps({k: head[k] for k in ("tickets", "settled", "date_range_et", "pnl_net_usd", "roi_on_capital",
                                           "capital_deployed_usd", "journal_crosscheck_all_days_match")}, default=float))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
