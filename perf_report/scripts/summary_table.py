"""Build the portfolio summary table (markdown) straight from the metrics files, so the docs can't drift.

    python perf_report/scripts/summary_table.py  ->  perf_report/data/summary_table.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import DATA  # noqa: E402

NA = "not available"


def ci(d, fmt="{:+.2f}", scale=1.0):
    if d is None or d.get("value") is None:
        return NA
    v, lo, hi = d["value"] * scale, d.get("lo"), d.get("hi")
    if lo is None:
        return fmt.format(v)
    return f"{fmt.format(v)} [{fmt.format(lo * scale)}, {fmt.format(hi * scale)}]"


def main():
    nba = json.loads((DATA / "nba/metrics.json").read_text())
    cfb = json.loads((DATA / "cfb/metrics.json").read_text())
    s = nba["scores"]
    bt, wf, live = cfb["backtest_2022_2025"], cfb["walkforward_2026_w1_11"], cfb["live_2026"]
    rows = [
        ("NBA cold-start player props", "Kalshi + Polymarket US", "Paper (system tickets; 0 fills logged)",
         "2026-10-20", f"{nba['settled']} tickets (low-conf.)",
         f"{s['brier_model_p_blend']:.4f} vs {s['brier_venue_close_mid']:.4f} (gap {ci(s['brier_gap_vs_close'], '{:+.4f}')})",
         f"{nba['clv_cents']['value']:+.2f}¢ [{nba['clv_cents']['lo']:+.2f}, {nba['clv_cents']['hi']:+.2f}]",
         f"−${abs(nba['pnl_net_usd']):,.2f} paper (real: {NA})",
         f"{nba['roi_on_capital'] * 100:+.1f}% [{nba['roi_ci_by_ticket']['lo'] * 100:+.1f}%, {nba['roi_ci_by_ticket']['hi'] * 100:+.1f}%]"),
        ("CFB totals, backtest 2022–2025", "Sportsbooks (FanDuel/DK/Fanatics)", "Backtest (walk-forward)",
         "n/a", f"{bt['signals']} signals",
         f"{bt['scores_on_signals']['brier_model']:.4f} vs {bt['scores_on_signals']['brier_close_market']:.4f} "
         f"(gap {ci(bt['scores_on_signals']['brier_gap_vs_close'], '{:+.4f}')})",
         f"{bt['clv_points']['value']:+.2f} pts [{bt['clv_points']['lo']:+.2f}, {bt['clv_points']['hi']:+.2f}]",
         f"{bt['units']:+.2f}u (no $: {NA})", f"{ci(bt['roi_per_unit'], '{:+.1%}')}"),
        ("CFB totals, 2026 wks 1–11", "Sportsbooks", "Walk-forward (wks 7–8 also posted live)", "2026-10-15 ET (live)",
         f"{wf['signals']} signals (low-conf.)",
         f"{wf['scores_on_signals']['brier_model']:.4f} vs {wf['scores_on_signals']['brier_close_market']:.4f} "
         f"(gap {ci(wf['scores_on_signals']['brier_gap_vs_close'], '{:+.4f}')})",
         f"{wf['clv_points']['value']:+.2f} pts [{wf['clv_points']['lo']:+.2f}, {wf['clv_points']['hi']:+.2f}]",
         f"{wf['units']:+.2f}u", f"{ci(wf['roi_per_unit'], '{:+.1%}')}"),
        ("CFB totals, posted live", "Sportsbooks", "Live signals, no real bets logged", "2026-10-15 ET",
         f"{live['graded']} graded + {live['pending']} pending (low-conf.)",
         f"{live['scores']['brier_model']:.4f} vs {live['scores']['brier_close_market']:.4f} "
         f"(gap {ci(live['scores']['brier_gap_vs_close'], '{:+.4f}')})",
         f"{live['clv_points']['value']:+.2f} pts [{live['clv_points']['lo']:+.2f}, {live['clv_points']['hi']:+.2f}]",
         f"{live['units_at_posted_number']:+.2f}u ({live['record_at_posted_number']})",
         f"{ci(live['roi_per_unit'], '{:+.1%}')}"),
        ("Live arbitrage system", "—", "Not found in any repo", NA, "0", NA, NA, NA, NA),
    ]
    head = ("| Model | Venue | Status | Live since | n | Brier: model vs market close (gap, + = model better) "
            "| Mean CLV [95% CI] | Net P&L | ROI [95% CI] |\n|---|---|---|---|---|---|---|---|---|\n")
    md = head + "\n".join("| " + " | ".join(r) + " |" for r in rows) + "\n"
    (DATA / "summary_table.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
