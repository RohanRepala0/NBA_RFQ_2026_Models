"""Weekly markdown report: signal counts, CLV, model vs market Brier, calibration,
segments, and CLV by week of season (the edge-decay chart)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from . import config
from .grade import by_segment, calibration, graded_signals, summarize
from .storage import Storage


def _fmt(v, pct: bool = False, digits: int = 3) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    if pct:
        return f"{100 * v:+.1f}pp" if isinstance(v, float) and abs(v) < 1 else f"{100 * v:.1f}%"
    return f"{v:.{digits}f}" if isinstance(v, float) else str(v)


def _table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_none_\n"
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].map(lambda v: "-" if pd.isna(v) else f"{v:.3f}")
    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(map(str, r)) + " |" for r in df.astype(str).itertuples(index=False)]
    return "\n".join([head, sep, *body]) + "\n"


def _bar(v: float | None, scale: float = 0.01) -> str:
    if v is None or pd.isna(v):
        return ""
    n = min(30, int(round(abs(v) / scale)))
    return ("+" if v >= 0 else "-") * n


def build_report(storage: Storage, start: date, end: date) -> str:
    df = graded_signals(storage, start, end)
    lines = [f"# Cold Start Usage Projection Modeling report: {start} to {end}", ""]
    if df.empty:
        return "\n".join(lines + ["No signals logged in this window.", ""])
    paper = df[df.decision == "paper"]
    s_all, s_paper = summarize(df), summarize(paper)
    lines += [
        "## Summary", "",
        "| | all signals | paper only |", "|---|---|---|",
        f"| signals logged | {s_all['signals']} | {s_paper['signals']} |",
        f"| graded (no push, result in) | {s_all.get('graded', 0)} | {s_paper.get('graded', 0)} |",
        f"| hit rate | {_fmt(s_all.get('hit_rate'))} | {_fmt(s_paper.get('hit_rate'))} |",
        f"| avg CLV (prob) | {_fmt(s_all.get('avg_clv_p'), pct=True)} | {_fmt(s_paper.get('avg_clv_p'), pct=True)} |",
        f"| avg CLV (line, pts) | {_fmt(s_all.get('avg_clv_line'), digits=2)} | {_fmt(s_paper.get('avg_clv_line'), digits=2)} |",
        f"| Brier model / market | {_fmt(s_all.get('brier_model'))} / {_fmt(s_all.get('brier_market'))} "
        f"| {_fmt(s_paper.get('brier_model'))} / {_fmt(s_paper.get('brier_market'))} |",
        f"| log loss model / market | {_fmt(s_all.get('logloss_model'))} / {_fmt(s_all.get('logloss_market'))} "
        f"| {_fmt(s_paper.get('logloss_model'))} / {_fmt(s_paper.get('logloss_market'))} |",
        "", "Lower Brier / log loss is better. The market column is the consensus baseline.", "",
        "## Abstain reasons", "",
        _table(df[df.decision == "abstain"].reason.str.replace(r"[\d.]+", "#", regex=True)
               .value_counts().rename_axis("reason").reset_index(name="n")),
        "## Calibration (all graded signals, model_p buckets)", "", _table(calibration(df)),
        "## By timing", "", _table(by_segment(df, "timing")),
        "## By team", "", _table(by_segment(df, "team")),
        "## New team vs incumbent", "", _table(by_segment(df, "new_team")),
        "## CLV by week of season (edge decay)", "",
    ]
    weekly = df.groupby("week").agg(signals=("clv_p", "size"), avg_clv_p=("clv_p", "mean")).reset_index()
    weekly["chart (each mark = 1pp)"] = weekly.avg_clv_p.map(_bar)
    lines += [_table(weekly)]
    return "\n".join(lines)


def write_report(storage: Storage, start: date, end: date, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or config.REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{start}_{end}.md"
    path.write_text(build_report(storage, start, end))
    return path
