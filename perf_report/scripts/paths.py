"""Where the three repositories live. Override with env vars if your checkouts are elsewhere.

    NBA_REPO  this repository (default: two levels above this file)
    CFB_REPO  RohanRepala0/CollegeFootballRatings2026 checkout
    NIL_REPO  RohanRepala0/College_Football_NIL_Models checkout
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT = HERE.parent                      # perf_report/
NBA_REPO = Path(os.environ.get("NBA_REPO", REPORT.parent))
CFB_REPO = Path(os.environ.get("CFB_REPO", "/home/user/rohanrepala0/collegefootballratings2026"))
NIL_REPO = Path(os.environ.get("NIL_REPO", "/home/user/rohanrepala0/college_football_nil_models"))
DATA = REPORT / "data"
CHARTS = REPORT / "charts"
