"""Step 1: list every data source in the three repos and how much data each holds.

Counts rows in every CSV, entries in every JSON / JSON.gz, rows per table in any DuckDB
file present, and lines in any log. Also records the stores the code writes to that are
git-ignored and therefore NOT in the repos (the source of most "not available" entries).

    python perf_report/scripts/inventory.py
    -> perf_report/data/inventory_sources.csv
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import CFB_REPO, DATA, NBA_REPO, NIL_REPO  # noqa: E402

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", "perf_report"}

# Stores the code reads/writes that .gitignore keeps out of git (checked for presence below).
IGNORED_STORES = [
    ("nba", "data/edge_lab.duckdb", "NBA decision log: odds_snapshots, projections, signals, venue_snapshots, "
                                    "venue_signals (every decision incl. non-actionable), tickets (fills), "
                                    "venue_settlements, results"),
    ("nba", "data/history/", "Kalshi 2025-26 KXNBAPTS archive with 1-min candles (input to docs/BACKTEST.md)"),
    ("nba", "data/cron.log", "cron run log (uptime / run history)"),
    ("cfb", "data/cfb.duckdb", "CFB log: games, lines, source_projections, bets (cfb log-bet)"),
    ("nil", "data/nil.duckdb", "NIL CSC releases database (rebuildable from data/csc/releases)"),
]


def category(rel: str) -> str:
    r = rel.lower()
    if r.startswith("tests/"):
        return "test fixture"
    if r.startswith("bets/"):
        return "trade journal (paper tickets / fills)"
    if r.startswith("2026/") and r.endswith("bets.csv"):
        return "weekly signals (graded)"
    if r.startswith("2026/") and r.endswith("ratings.csv"):
        return "weekly model ratings (every game)"
    if "scenarios" in r:
        return "model input: minutes scenarios"
    if r.startswith("data/csc") or r.startswith("data/benchmark") or r.startswith("data/players"):
        return "NIL data / outputs"
    if r.startswith("data/") or r.startswith("cold_start_usage/") or r.startswith("examples/"):
        return "model input / reference data"
    if r.startswith("reports/") or r.startswith("docs/"):
        return "generated report data"
    return "other"


def count(path: Path) -> tuple[str, int | None, str]:
    name = path.name.lower()
    try:
        if name.endswith(".csv"):
            with path.open(newline="", encoding="utf-8", errors="replace") as f:
                rows = sum(1 for _ in csv.reader(f))
            return "csv", max(rows - 1, 0), "data rows (header excluded)"
        if name.endswith(".json.gz") or name.endswith(".json"):
            opener = gzip.open if name.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as f:
                obj = json.load(f)
            n = len(obj) if isinstance(obj, (list, dict)) else None
            return "json", n, "top-level entries"
        if name.endswith(".log"):
            return "log", sum(1 for _ in path.open(errors="replace")), "lines"
    except Exception as e:  # unreadable file: record it, never guess a count
        return "error", None, f"unreadable: {type(e).__name__}"
    return "", None, ""


def duckdb_tables(path: Path) -> list[tuple[str, int]]:
    try:
        import duckdb
    except ImportError:
        return [("(duckdb not installed in this Python: run with the CFB repo's `uv run python`)", -1)]
    con = duckdb.connect(str(path), read_only=True)
    out = [(t, con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0])
           for (t,) in con.execute("SELECT table_name FROM information_schema.tables "
                                   "WHERE table_schema='main' ORDER BY 1").fetchall()]
    con.close()
    return out


def main() -> None:
    rows = []
    for repo_key, root in (("nba", NBA_REPO), ("cfb", CFB_REPO), ("nil", NIL_REPO)):
        if not root.exists():
            rows.append({"repo": repo_key, "path": str(root), "kind": "missing", "rows": "",
                         "unit": "checkout not found", "category": "", "in_git": ""})
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or SKIP_DIRS & set(p.relative_to(root).parts):
                continue
            rel = p.relative_to(root).as_posix()
            if p.suffix == ".duckdb":
                for table, n in duckdb_tables(p):
                    rows.append({"repo": repo_key, "path": f"{rel}::{table}", "kind": "duckdb table",
                                 "rows": n if n >= 0 else "", "unit": "rows", "category": "database (git-ignored)",
                                 "in_git": "no"})
                continue
            kind, n, unit = count(p)
            if not kind:
                continue
            ignored = rel.startswith("data/raw/") or (rel.startswith("reports/") and p.suffix in {".csv", ".json"})
            rows.append({"repo": repo_key, "path": rel, "kind": kind, "rows": "" if n is None else n, "unit": unit,
                         "category": category(rel), "in_git": "no (generated this session)" if ignored else "yes"})
    for repo_key, rel, what in IGNORED_STORES:
        root = {"nba": NBA_REPO, "cfb": CFB_REPO, "nil": NIL_REPO}[repo_key]
        present = (root / rel).exists()
        rows.append({"repo": repo_key, "path": rel, "kind": "git-ignored store", "rows": "",
                     "unit": "present here" if present else "NOT AVAILABLE (git-ignored; lives on the owner's machine)",
                     "category": what, "in_git": "no"})
    # A Kalshi / Polymarket fills export: searched for by name, never found so far.
    exports = [p for root in (NBA_REPO, CFB_REPO, NIL_REPO) if root.exists()
               for p in root.rglob("*") if p.is_file() and not (SKIP_DIRS & set(p.parts))
               and any(k in p.name.lower() for k in ("kalshi_fills", "fills_export", "polymarket_fills",
                                                     "trade_history", "orders.csv", "portfolio"))]
    rows.append({"repo": "all", "path": "; ".join(str(p) for p in exports) or "(none)", "kind": "venue fills export search",
                 "rows": len(exports), "unit": "files matching kalshi_fills / fills_export / trade_history / orders",
                 "category": "venue exports", "in_git": ""})
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "inventory_sources.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["repo", "path", "kind", "rows", "unit", "category", "in_git"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
