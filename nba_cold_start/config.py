"""Central configuration: book allowlist, budgets, thresholds, model params.

Every tunable number in the pipeline lives here so a change is one diff in one
file. Timestamps everywhere in this project are UTC unless a name says `_et`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

# --- Paths -------------------------------------------------------------------
PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
DATA_DIR = REPO_DIR / "data"
RAW_DIR = DATA_DIR / "raw"                      # allowlist-filtered API responses
REPORTS_DIR = REPO_DIR / "reports"
SCENARIOS_DIR = PACKAGE_DIR / "scenarios"
PLAYERS_CSV = DATA_DIR / "players_2025_26.csv"
TEAM_SHOOTING_CSV = DATA_DIR / "team_shooting_2025_26.csv"   # spacing context
PLAYER_ID_OVERRIDES_CSV = DATA_DIR / "player_id_overrides.csv"
BOOKS_FILE = PACKAGE_DIR / "books.json"         # written by `cli books`
DEFAULT_DB_PATH = DATA_DIR / "edge_lab.duckdb"
DB_PATH = Path(os.environ.get("NBA_CS_DB", DEFAULT_DB_PATH))

# --- Book allowlist (hard rule 1) ---------------------------------------------------
# Only these SportsGameOdds bookmakerIDs are ever requested, parsed, stored or
# shown. Everything else is dropped at request time (bookmakerID filter), at
# parse time (sgo_client) and at write time (storage); tests/test_book_allowlist.py
# fails if anything off the list leaks. IDs: sportsgameodds.com/docs/data-types/bookmakers
#
# Reference books: priced sportsbooks that make up the market consensus.
REFERENCE_BOOKS = frozenset({
    "pinnacle", "circa", "draftkings", "betmgm", "caesars", "bet365",
    "betonline", "bovada", "lowvig", "espnbet", "fanatics", "hardrockbet",
    "betrivers", "williamhill", "ballybet", "betparx", "thescorebet",
})
# Target venues: the prediction markets we are waiting on. Stored so we can see
# when (and at what price) they post, but never part of the consensus.
TARGET_VENUES = frozenset({"kalshi", "novig", "polymarket"})
# DFS pick'em apps post placeholder prices (+100 both ways): logged, never priced.
UNPRICED_BOOKS = frozenset({"prizepicks", "underdog", "sleeper", "parlayplay", "hotstreak"})

ALLOWED_BOOKS = REFERENCE_BOOKS | TARGET_VENUES | UNPRICED_BOOKS


def is_allowed_book(book_id) -> bool:
    return str(book_id).strip().lower() in ALLOWED_BOOKS


def book_role(book_id: str) -> str | None:
    b = str(book_id).strip().lower()
    if b in REFERENCE_BOOKS:
        return "reference"
    if b in TARGET_VENUES:
        return "target"
    if b in UNPRICED_BOOKS:
        return "unpriced"
    return None


def request_bookmaker_filter(path: Path | None = None) -> str | None:
    """Comma list for the `bookmakerID` request param: allowlisted books this key can see.

    The API answers HTTP 400 if the list names a book outside the plan, so this
    uses what `cli books` discovered. None before discovery: the request then
    carries no book filter and the parse-time filter drops off-list books.
    """
    books = load_books(path or BOOKS_FILE)
    found = sorted(set(books["reference"]) | set(books["target"]) | set(books["unpriced"]))
    return ",".join(found) or None


# --- SportsGameOdds API --------------------------------------------------------
API_BASE = "https://api.sportsgameodds.com/v2"
API_KEY_ENV = "SPORTS_ODDS_API_KEY"
LEAGUE_ID = "NBA"
POINTS_ODD_FILTER = "points-PLAYER_ID-game-ou-over"   # + includeOpposingOdds=true
REQUESTS_PER_MINUTE = 10                 # Amateur plan
MONTHLY_OBJECT_LIMIT = 2500              # Amateur plan
MONTHLY_OBJECT_HARD_STOP = 2200          # our own ceiling, below the plan limit
REQUEST_TIMEOUT_S = 30
MAX_RETRIES = 4                          # backoff 2s, 4s, 8s, 16s
EVENTS_PAGE_LIMIT = 50
# Measured with `cli usage --measure`: the usage check costs 0 objects.
# (Event responses still cost at least 1 object each, even when empty.)
USAGE_CALL_OBJECTS = 0

# --- Snapshot schedule (minutes before tip) ------------------------------------
# "open" is the first slate fetch of a day; the rest are taken by `snapshot --due`.
SNAPSHOT_OFFSETS_MIN = {"t-6h": 360, "t-2h": 120, "t-60m": 60, "t-15m": 15}
CLOSE_TAG = "t-15m"
SIGNAL_TIMINGS = ("t-60m", "t-15m")

# --- Consensus -----------------------------------------------------------------
VIG_METHOD = "power"                     # power | multiplicative | shin
BOOK_WEIGHTS = {"pinnacle": 2.0}         # v1: equal weights, Pinnacle 2x
DEFAULT_BOOK_WEIGHT = 1.0
MIN_PRICED_BOOKS = 2
MAX_QUOTE_AGE_MIN = 30
# Which clock decides staleness: "quote" = the book's lastUpdatedAt (spec),
# "fetch" = when our snapshot was taken. Checked on live player
# points: each book's quotes share one refresh time ~10 min old (none > 30),
# so lastUpdatedAt behaves like "last confirmed" and "quote" is safe.
STALENESS_CLOCK = "quote"
OVERROUND_RANGE = (0.98, 1.25)           # outside this a book's pair is ignored

# --- Signals and the watchlist ----------------------------------------------------
EDGE_THRESHOLD = 0.04                    # 4 percentage points
MAX_CREDIBLE_EDGE = 0.15                 # above this: abstain, "check inputs" (None = off)
# Prediction-market taker fee per contract = rate * price * (1 - price).
# 0.07 is Kalshi's published general formula; the Novig and Polymarket values
# are conservative placeholders, not verified. Check each venue's fee page.
VENUE_FEE_RATE = {"kalshi": 0.07, "novig": 0.07, "polymarket": 0.07}
LADDER_HALF_WIDTH = 3                    # "N+ points" rungs either side of the line

# --- League-wide catalog (catalog.py) ------------------------------------------------
USAGE_TIERS = {"high": 25.0, "medium": 18.0}   # 2025-26 USG%: >= 25 high, >= 18 medium, else low
CATALOG_PRESSURE_PCT = 2.0               # team usage demand beyond +-2% of budget counts as a change
CATALOG_MIN_USG_SHIFT = 0.5              # player usage must move at least this many points
CATALOG_EXCLUDED_TEAMS = frozenset({"PHI"})   # left out of the catalog and the board by choice


# --- Usage-squeeze model ---------------------------------------------------------
@dataclass(frozen=True)
class ModelParams:
    league_avg_usg: float = 20.0         # elasticity anchor
    gamma: float = 1.0                   # e_i = (20 / usg_i) ** gamma
    eff_per_usg_point: float = 0.004     # +0.4% efficiency per usage point given up
    sd_fraction: float = 0.30            # points SD = max(sd_floor, sd_fraction * mean)
    sd_floor: float = 4.0
    usage_budget: float = 100 * 48       # percent-minutes per team game
    # Spacing: points multiplier 1 + spacing_coef * (new - old spacing, 0-100 scale).
    # 0 = reported but not applied, until fit.py estimates it from team-changers.
    spacing_coef: float = 0.0
    spacing_min_coverage: float = 0.9    # share of scenario minutes with 3PA data
    minutes_total: float = 240.0
    minutes_tolerance: float = 0.5


MODEL = ModelParams()
MODEL_VERSION = "usage-squeeze-1.0"

# --- Season --------------------------------------------------------------------
ET = ZoneInfo("America/New_York")
SEASON_OPENER = date(2026, 10, 20)

# SportsGameOdds team IDs look like MIAMI_HEAT_NBA. Matching on the
# nickname token is robust to city formatting. Override exact IDs if needed.
TEAM_NICKNAMES = {
    "HAWKS": "ATL", "CELTICS": "BOS", "NETS": "BKN", "HORNETS": "CHA",
    "BULLS": "CHI", "CAVALIERS": "CLE", "MAVERICKS": "DAL", "NUGGETS": "DEN",
    "PISTONS": "DET", "WARRIORS": "GSW", "ROCKETS": "HOU", "PACERS": "IND",
    "CLIPPERS": "LAC", "LAKERS": "LAL", "GRIZZLIES": "MEM", "HEAT": "MIA",
    "BUCKS": "MIL", "TIMBERWOLVES": "MIN", "PELICANS": "NOP", "KNICKS": "NYK",
    "THUNDER": "OKC", "MAGIC": "ORL", "76ERS": "PHI", "SUNS": "PHX",
    "BLAZERS": "POR", "KINGS": "SAC", "SPURS": "SAS", "RAPTORS": "TOR",
    "JAZZ": "UTA", "WIZARDS": "WAS",
}
TEAM_ID_OVERRIDES: dict[str, str] = {}


def team_abbr(team_id: str | None) -> str | None:
    if not team_id:
        return None
    if team_id in TEAM_ID_OVERRIDES:
        return TEAM_ID_OVERRIDES[team_id]
    tokens = set(str(team_id).upper().split("_"))
    hits = {abbr for nick, abbr in TEAM_NICKNAMES.items() if nick in tokens}
    return hits.pop() if len(hits) == 1 else None


# --- Discovered books (written by `cli books`) ---------------------------------------
def load_books(path: Path = BOOKS_FILE) -> dict:
    """Which allowlisted books this API key actually returns, by role."""
    if not path.exists():
        return {"reference": [], "target": [], "unpriced": [], "discovered_at": None}
    books = json.loads(path.read_text())
    for key in ("reference", "target", "unpriced"):
        books[key] = [b for b in books.get(key, []) if is_allowed_book(b)]
    return books
