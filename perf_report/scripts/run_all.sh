#!/usr/bin/env bash
# Rebuild every number, table and chart in perf_report/.
#
#   NBA_REPO  this repository (default: the repo containing this script)
#   CFB_REPO  a CollegeFootballRatings2026 checkout with its DuckDB built (see data/cfb/PROVENANCE.md)
#   NIL_REPO  a College_Football_NIL_Models checkout (inventory only)
#
# Needs: python3 with pandas, numpy, matplotlib (perf_report/scripts/requirements.txt); `uv` for the CFB repo.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export NBA_REPO="${NBA_REPO:-$(cd "$HERE/../.." && pwd)}"
export CFB_REPO="${CFB_REPO:-/home/user/rohanrepala0/collegefootballratings2026}"
export NIL_REPO="${NIL_REPO:-/home/user/rohanrepala0/college_football_nil_models}"

(cd "$CFB_REPO" && uv run python "$HERE/inventory.py")        # uses the CFB env so DuckDB tables are counted
(cd "$CFB_REPO" && uv run python "$HERE/cfb_export.py")       # per-game probabilities; checks it reproduces the repo
python3 "$HERE/nba_metrics.py"
python3 "$HERE/cfb_metrics.py"
python3 "$HERE/make_charts.py"
python3 "$HERE/summary_table.py"
