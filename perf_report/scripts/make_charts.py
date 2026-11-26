"""Step 4: charts (PNG, light and dark variants) from the computed data files.

Run after nba_metrics.py and cfb_metrics.py:
    python perf_report/scripts/make_charts.py
-> perf_report/charts/*-light.png, *-dark.png
   perf_report/data/cfb/calibration_zoom.csv (the CFB reliability table at 1pp bins; its 10-bin table is degenerate)

Palette: the dataviz reference palette (slot 1 blue, slot 2 orange), validated light and dark.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import CHARTS, DATA  # noqa: E402
from stats_util import wilson  # noqa: E402

THEMES = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
              "axis": "#c3c2b7", "s1": "#2a78d6", "s2": "#eb6834"},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
             "axis": "#383835", "s1": "#3987e5", "s2": "#d95926"},
}


def style(ax, t, ygrid=True, xgrid=False):
    ax.set_facecolor(t["surface"])
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(t["axis"])
        ax.spines[s].set_linewidth(1)
    ax.tick_params(colors=t["muted"], labelcolor=t["ink2"], labelsize=9, length=0, pad=6)
    if ygrid:
        ax.yaxis.grid(True, color=t["grid"], linewidth=0.8, linestyle="-")
    if xgrid:
        ax.xaxis.grid(True, color=t["grid"], linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(t["ink2"])
    ax.yaxis.label.set_color(t["ink2"])


def figure(t, w=8.0, h=4.6, ncols=1):
    fig, axes = plt.subplots(1, ncols, figsize=(w, h), dpi=200)
    fig.patch.set_facecolor(t["surface"])
    return fig, axes


def titles(fig, t, title, subtitle):
    fig.text(0.012, 0.975, title, ha="left", va="top", fontsize=12.5, fontweight="semibold", color=t["ink"])
    fig.text(0.012, 0.915, subtitle, ha="left", va="top", fontsize=9, color=t["ink2"])


def legend(ax, t, **kw):
    lg = ax.legend(frameon=False, fontsize=9, labelcolor=t["ink2"], **kw)
    return lg


def save(fig, name, mode):
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    fig.savefig(CHARTS / f"{name}-{mode}.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def money(v: float) -> str:
    return f"{'−' if v < 0 else ''}${abs(v):,.0f}"


def sparse_ticks(ax, positions, labels, min_gap):
    """Keep a tick label only when it is at least `min_gap` x-units from the last kept one."""
    keep_p, keep_l, last = [], [], None
    for pos, lab in zip(positions, labels):
        if last is None or pos - last >= min_gap:
            keep_p.append(pos)
            keep_l.append(lab)
            last = pos
    ax.set_xticks(keep_p)
    ax.set_xticklabels(keep_l, fontsize=8)


def end_label(ax, t, x, y, text, dy=0):
    ax.annotate(text, (x, y), xytext=(6, dy), textcoords="offset points", va="center", ha="left",
                fontsize=9, color=t["ink"])


# ---------------------------------------------------------------- NBA

def nba_cumulative(mode):
    t = THEMES[mode]
    d = pd.read_csv(DATA / "nba/tickets_enriched.csv")
    d["tip_utc"] = pd.to_datetime(d.tip_utc, utc=True)
    x = np.arange(1, len(d) + 1)
    real = d.pnl_usd.cumsum()
    exp = d.clv_implied_pnl_usd.cumsum()
    fig, ax = figure(t)
    style(ax, t)
    ax.axhline(0, color=t["axis"], linewidth=1)
    ax.plot(x, real, color=t["s1"], linewidth=2, solid_capstyle="round", label="Realized paper P&L (settled)")
    ax.plot(x, exp, color=t["s2"], linewidth=2, solid_capstyle="round", label="Worth at the venue close (CLV)")
    for series, col in ((real, "s1"), (exp, "s2")):
        ax.plot(x[-1], series.iloc[-1], "o", ms=7, color=t[col], mec=t["surface"], mew=1.5)
        end_label(ax, t, x[-1], series.iloc[-1], money(series.iloc[-1]))
    # slate boundaries as x ticks (crowded ones dropped)
    starts = d.groupby("date_et").cumcount().eq(0).to_numpy().nonzero()[0] + 1
    sparse_ticks(ax, starts, [pd.Timestamp(v).strftime("%b %-d") for v in d.date_et.iloc[starts - 1]], 5)
    ax.set_xlim(0, len(d) + 9)
    ax.set_ylabel("Cumulative P&L, $ (net of fees)")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: money(v)))
    legend(ax, t, loc="lower left")
    titles(fig, t, "NBA player props (Kalshi + Polymarket US): cumulative paper P&L",
           f"{len(d)} paper tickets at suggested size, Oct 20–31, 2026 (low confidence, n<100). "
           f"No real fills were logged.")
    save(fig, "nba_cumulative_pnl", mode)


def nba_calibration(mode):
    t = THEMES[mode]
    c = pd.read_csv(DATA / "nba/calibration.csv").dropna(subset=["predicted"])
    fig, ax = figure(t, w=6.4, h=5.6)
    style(ax, t, ygrid=True, xgrid=True)
    ax.plot([0, 1], [0, 1], color=t["axis"], linewidth=1.2, zorder=1)
    ax.text(0.93, 0.965, "perfect", color=t["muted"], fontsize=8, ha="right", rotation=40)
    for forecast, col, lab, off in (("model p_blend", "s1", "Model (p_blend)", -0.006),
                                    ("venue close mid", "s2", "Venue close mid", 0.006)):
        s = c[c.forecast == forecast]
        ax.vlines(s.predicted + off, s.actual_lo, s.actual_hi, color=t[col], linewidth=1, alpha=0.55, zorder=2)
        ax.plot(s.predicted + off, s.actual, "o", ms=7, color=t[col], mec=t["surface"], mew=1.5, label=lab, zorder=3)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Predicted probability (10 bins)")
    ax.set_ylabel("Actual win rate (95% Wilson interval)")
    legend(ax, t, loc="upper left")
    titles(fig, t, "NBA props: calibration on the 79 tickets",
           "Below the line = overconfident. Each bin has 0–18 tickets: low confidence.")
    save(fig, "nba_calibration", mode)


def nba_clv(mode):
    t = THEMES[mode]
    d = pd.read_csv(DATA / "nba/tickets_enriched.csv").dropna(subset=["clv_c"])
    v = d.clv_c.round(1)
    counts = v.value_counts().sort_index()
    fig, ax = figure(t)
    style(ax, t)
    ax.bar(counts.index, counts.values, width=0.38, color=t["s1"], zorder=2)
    ax.axvline(0, color=t["axis"], linewidth=1)
    m, med = d.clv_c.mean(), d.clv_c.median()
    ax.annotate(f"mean {m:+.2f}¢ · median {med:+.1f}¢ · {100 * (d.clv_c > 0).mean():.0f}% beat the close",
                (0.99, 0.95), xycoords="axes fraction", ha="right", va="top", fontsize=9, color=t["ink"])
    ax.set_xlabel("CLV: close mid − entry ask (cents per contract; + = market moved toward the ticket)")
    ax.set_ylabel("Tickets")
    titles(fig, t, "NBA props: closing line value per ticket",
           "Close = mid of the last two-sided venue book before tip (normally T-5m). n = 79, low confidence.")
    save(fig, "nba_clv_distribution", mode)


# ---------------------------------------------------------------- CFB

def cfb_cumulative(mode):
    t = THEMES[mode]
    bt = pd.read_csv(DATA / "cfb/signals_backtest_2022_2025.csv")
    wf = pd.read_csv(DATA / "cfb/signals_walkforward_2026.csv")
    live = pd.read_csv(DATA / "cfb/live_signals_2026.csv")
    fig, (a1, a2) = figure(t, w=10.5, h=4.6, ncols=2)
    for ax in (a1, a2):
        style(ax, t)
        ax.axhline(0, color=t["axis"], linewidth=1)
        ax.set_ylabel("Cumulative units (1u per signal, −110)")
    x = np.arange(1, len(bt) + 1)
    a1.plot(x, bt.cum_units, color=t["s1"], linewidth=2)
    a1.plot(x[-1], bt.cum_units.iloc[-1], "o", ms=7, color=t["s1"], mec=t["surface"], mew=1.5)
    end_label(a1, t, x[-1], bt.cum_units.iloc[-1], f"{bt.cum_units.iloc[-1]:+.1f}u")
    starts = bt.groupby("season").cumcount().eq(0).to_numpy().nonzero()[0] + 1
    sparse_ticks(a1, starts, bt.season.iloc[starts - 1].astype(str), 20)
    a1.set_xlim(0, len(bt) + 45)
    a1.set_title("Backtest 2022–2025: 337 signals, 178–154–5", fontsize=10, color=t["ink"], loc="left")
    x2 = np.arange(1, len(wf) + 1)
    a2.plot(x2, wf.cum_units, color=t["s1"], linewidth=2, label="2026 walk-forward signal", zorder=2)
    is_live = wf.game_id.isin(live[(live.market == "total") & live.graded].game_id)
    a2.plot(x2[is_live], wf.cum_units[is_live], "o", ms=7, color=t["s2"], mec=t["surface"], mew=1.5,
            label="Posted live before kickoff", zorder=3, linestyle="none")
    a2.plot(x2[-1], wf.cum_units.iloc[-1], "o", ms=7, color=t["s1"], mec=t["surface"], mew=1.5)
    end_label(a2, t, x2[-1], wf.cum_units.iloc[-1], f"{wf.cum_units.iloc[-1]:+.1f}u")
    wk = wf.groupby("week").cumcount().eq(0).to_numpy().nonzero()[0] + 1
    sparse_ticks(a2, wk, [f"W{w}" for w in wf.week.iloc[wk - 1]], 4)
    a2.set_xlim(0, len(wf) + 9)
    a2.set_title("2026 weeks 1–11: 65 signals, 36–29", fontsize=10, color=t["ink"], loc="left")
    legend(a2, t, loc="upper left")
    titles(fig, t, "College football totals model: cumulative units at SP+'s early-week number",
           "Walk-forward (fit on earlier seasons only). Units, not dollars: no real bets were logged.")
    save(fig, "cfb_cumulative_units", mode)


def cfb_clv(mode):
    t = THEMES[mode]
    bt = pd.read_csv(DATA / "cfb/signals_backtest_2022_2025.csv").dropna(subset=["clv_points"])
    counts = (np.round(bt.clv_points * 2) / 2).value_counts().sort_index()   # half-point bins (medians make quarters)
    fig, ax = figure(t)
    style(ax, t)
    ax.bar(counts.index, counts.values, width=0.38, color=t["s1"], zorder=2)
    ax.axvline(0, color=t["axis"], linewidth=1)
    ax.annotate(f"mean {bt.clv_points.mean():+.2f} pts · median {bt.clv_points.median():+.1f} · "
                f"{100 * (bt.clv_points > 0).mean():.0f}% beat the close, {100 * (bt.clv_points == 0).mean():.0f}% tied",
                (0.99, 0.95), xycoords="axes fraction", ha="right", va="top", fontsize=9, color=t["ink"])
    ax.set_xlabel("CLV: points the closing total moved toward the bet from SP+'s early number (0.5-pt bins)")
    ax.set_ylabel("Signals")
    titles(fig, t, "College football totals: closing line value, 2022–2025 backtest",
           "337 walk-forward signals. Close = median closing total across CFBD's sportsbooks.")
    save(fig, "cfb_clv_distribution", mode)


def cfb_calibration_zoom(mode, write=False):
    t = THEMES[mode]
    g = pd.read_csv(DATA / "cfb/games_2022_2026.csv")
    g = g[(g.season <= 2025) & g.result.isin(["win", "loss"])].copy()
    g["y"] = (g.result == "win").astype(float)
    g["p_model"] = g.model_p_win / (g.model_p_win + g.model_p_loss)
    g["p_close"] = g.close_p_win / (g.close_p_win + g.close_p_loss)
    edges = np.round(np.arange(0.50, 0.585, 0.01), 2)
    rows = []
    for col, lab in (("p_model", "model"), ("p_close", "closing market")):
        b = pd.cut(g[col], np.r_[0, edges[1:-1], 1], right=False)
        for k, d in g.groupby(b, observed=True):
            w = wilson(d.y.sum(), len(d))
            rows.append({"forecast": lab, "bin": str(k), "n": len(d), "predicted": d[col].mean(),
                         "actual": w["value"], "actual_lo": w["lo"], "actual_hi": w["hi"]})
    tab = pd.DataFrame(rows)
    if write:
        tab.to_csv(DATA / "cfb/calibration_zoom.csv", index=False)
    fig, ax = figure(t, w=6.4, h=5.6)
    style(ax, t, ygrid=True, xgrid=True)
    ax.plot([0.3, 0.8], [0.3, 0.8], color=t["axis"], linewidth=1.2, zorder=1)
    for lab, col, off in (("model", "s1", -0.0012), ("closing market", "s2", 0.0012)):
        s = tab[(tab.forecast == lab) & (tab.n >= 20)]
        ax.vlines(s.predicted + off, s.actual_lo, s.actual_hi, color=t[col], linewidth=1, alpha=0.55)
        ax.plot(s.predicted + off, s.actual, "o", ms=7, color=t[col], mec=t["surface"], mew=1.5,
                label=f"{'Model' if lab == 'model' else 'Closing market, same bet'}")
    ax.set_xlim(0.38, 0.66)
    ax.set_ylim(0.38, 0.66)
    ax.set_xlabel("Predicted P(win) of the model's side at the early number")
    ax.set_ylabel("Actual win rate (95% Wilson interval)")
    legend(ax, t, loc="upper left")
    titles(fig, t, "College football totals: calibration, every game 2022–2025",
           "2,919 games (pushes excluded); 1pp bins with 20+ games. The 10-bin table is degenerate.")
    save(fig, "cfb_calibration", mode)


def main():
    for mode in ("light", "dark"):
        nba_cumulative(mode)
        nba_calibration(mode)
        nba_clv(mode)
        cfb_cumulative(mode)
        cfb_clv(mode)
        cfb_calibration_zoom(mode, write=(mode == "light"))
    print(f"wrote {sorted(p.name for p in CHARTS.glob('*.png'))}")


if __name__ == "__main__":
    main()
