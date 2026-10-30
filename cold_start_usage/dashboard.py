"""Exports for the Prop Desk dashboard (a claude.ai artifact): JSON row files from the log.

The dashboard can't read this machine's database, so `cli dashboard --out DIR` writes the rows it
draws and the grading routine uploads them after each morning's grade:

- tickets.json: every paper ticket, graded ones from bets/ledger.csv and the latest slate's
  issued tickets still pending (first actionable decision per player-game and stat, at the largest
  stake it was given, as the caps count them);
- model_eval.json: `evaluate`'s accuracy table per window (out of sample / in-sample), stat and
  source (season model, rolling, books' close);
- minutes_eval.json: its minutes table per window and player set.

A ticket's `won` is its own side's result (a NO ticket wins when the YES contract settles no).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import config
from .schedule import et_date
from .storage import Storage


def ledger_tickets(path: Path | None = None) -> pd.DataFrame:
    path = path or config.BETS_DIR / "ledger.csv"
    if not path.exists():
        return pd.DataFrame()
    L = pd.read_csv(path)
    return pd.DataFrame({
        "ticket_id": L.signal_id, "date": L.date_et, "game": L.game, "player": L.player, "stat": L.stat,
        "contract": L.contract, "venue": L.venue, "checkpoint": L.checkpoint,
        "entry_c": (100 * L.ask).round(1), "contracts": L.suggested_contracts, "stake": L.suggested_stake_usd.round(2),
        "fair_pct": (100 * L.p_blend).round(1), "books_pct": (100 * L.p_market).round(1),
        "ev_pp": (100 * L.ev_blend).round(1),
        "result": L.outcome.where(L.outcome.isin(["won", "lost"]), "pending"),
        "won": (L.outcome == "won").astype(float).where(L.outcome.isin(["won", "lost"])),
        "pnl": L.pnl_suggested_usd.round(2).where(L.outcome.isin(["won", "lost"])),
        "clv_c": (100 * L.clv).round(1)})


def pending_tickets(storage: Storage, d: date, now: datetime, known: set[str]) -> pd.DataFrame:
    """The slate's issued tickets not in the ledger yet (not graded)."""
    from .venues import issued_tickets
    t = issued_tickets(storage, d, now)
    if t.empty:
        return pd.DataFrame()
    t = t[~t.signal_id.isin(known)]
    return pd.DataFrame({
        "ticket_id": t.signal_id, "date": d.isoformat(), "game": t.game, "player": t.player,
        "stat": t.stat.fillna("points"), "contract": t.contract, "venue": t.venue, "checkpoint": t.tag,
        "entry_c": (100 * t.ask).round(1), "contracts": t.contracts, "stake": t.stake_usd.round(2),
        "fair_pct": (100 * t.p_blend).round(1), "books_pct": (100 * t.p_market).round(1),
        "ev_pp": (100 * t.ev_blend).round(1), "result": "pending", "won": None, "pnl": None, "clv_c": None})


def eval_rows(storage: Storage) -> tuple[list[dict], list[dict]]:
    from .evaluation import walk_forward, windows
    df = walk_forward(storage, config.SEASON_OPENER)
    acc, mins = [], []
    if df.empty:
        return acc, mins
    for label, s in windows(df):
        window = "out_of_sample" if label.startswith("Out") else "in_sample"
        for r in s["accuracy"].itertuples():
            for src in ("season", "rolling", "books"):
                acc.append({"window": window, "stat": r.stat, "source": src, "n": int(r.n),
                            "mae": round(float(getattr(r, f"mae_{src}")), 3),
                            "bias": round(float(getattr(r, f"bias_{src}")), 3),
                            "brier": round(float(getattr(r, f"brier_{src}")), 4)})
        for r in s["minutes"].itertuples():
            for src in ("season", "rolling"):
                mins.append({"window": window, "players": "all_projected" if r.players.startswith("all") else "played",
                             "source": src, "n": int(r.n), "mae": round(float(getattr(r, f"mae_{src}")), 3),
                             "bias": round(float(getattr(r, f"bias_{src}")), 3)})
    return acc, mins


def export(storage: Storage, out: Path, now: datetime) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    graded = ledger_tickets()
    known = set(graded.ticket_id) if len(graded) else set()
    latest = et_date(now) if now.hour >= 12 else et_date(now - pd.Timedelta(hours=12))
    frames = [f for f in (graded, pending_tickets(storage, latest, now, known)) if len(f)]
    tickets = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    acc, mins = eval_rows(storage)
    files = {"tickets.json": json.loads(tickets.to_json(orient="records")) if len(tickets) else [],
             "model_eval.json": acc, "minutes_eval.json": mins}
    for name, rows in files.items():
        (out / name).write_text(json.dumps(rows, indent=0))
    return {k: len(v) for k, v in files.items()}
