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
BETS_DIR = REPO_DIR / "bets"                    # the committed bet journal (`cli journal`)
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
# Target venues: prediction markets as SportsGameOdds labels them. Stored if a
# plan ever carries them, never part of the consensus. (Prices Rohan can act on
# are read from the venues' own public APIs: see "Venues" below.)
TARGET_VENUES = frozenset({"kalshi", "polymarket"})
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


# --- Stats ---------------------------------------------------------------------------
# The player stats the model, the consensus and the venue scan cover. Points are priced off
# a normal (odds_math); rebounds and assists are counts, priced off a negative binomial
# (distributions.py). The sportsbook-line `signals` stay points-only.
STATS = ("points", "rebounds", "assists")
STAT_LABELS = {"points": "PTS", "rebounds": "REB", "assists": "AST"}

# --- SportsGameOdds API --------------------------------------------------------
API_BASE = "https://api.sportsgameodds.com/v2"
API_KEY_ENV = "SPORTS_ODDS_API_KEY"
LEAGUE_ID = "NBA"
POINTS_ODD_FILTER = "points-PLAYER_ID-game-ou-over"   # + includeOpposingOdds=true
# Every /events call asks for all of STATS in one comma list. Billing is per event, so the
# extra stats cost nothing (checked live: 80 odds, 1 object).
STATS_ODD_FILTER = ("points-PLAYER_ID-game-ou-over,rebounds-PLAYER_ID-game-ou-over,"
                    "assists-PLAYER_ID-game-ou-over")
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
EDGE_THRESHOLD = 0.04                    # 4 percentage points (sportsbook-line signals)
MAX_CREDIBLE_EDGE = 0.15                 # above this: abstain, "check inputs" (None = off)
LADDER_HALF_WIDTH = 3                    # "N+ points" rungs either side of the line

# --- Venues (the only places Rohan can trade) -------------------------------------
# Actionable: Kalshi and Polymarket US (the CFTC-regulated US exchange). The
# international polymarket.com book is close-only for US persons, so it is read
# as a reference price and never actionable.
ACTIONABLE_VENUES = ("kalshi", "polymarket_us")
REFERENCE_VENUES = ("polymarket_intl",)
VENUES = ACTIONABLE_VENUES + REFERENCE_VENUES
# Kalshi series and Polymarket US sportsMarketTypes read, by stat. Other prop series
# (threes, steals, blocks, combos) are not read.
KALSHI_SERIES = {"points": "KXNBAPTS", "rebounds": "KXNBAREB", "assists": "KXNBAAST"}
PM_US_STAT_TYPES = {"basketball_player_points": "points", "basketball_player_rebounds": "rebounds",
                    "basketball_player_assists": "assists"}
# Taker fee per order = rate * C * P * (1 - P), rounded per order:
#   kalshi: up to the next cent (KXNBAPTS, KXNBAREB, KXNBAAST fee_type "quadratic": makers pay 0)
#   polymarket_us: to the cent, half to even (feeCoefficient 0.0695; no maker rebate at tier 1)
#   polymarket_intl: 5 decimals (feeSchedule rate 0.05, sports_fees_v3)
VENUE_FEES = {
    "kalshi": {"rate": 0.07, "rounding": "up_cent", "maker_rate": 0.0},
    "polymarket_us": {"rate": 0.0695, "rounding": "half_even_cent", "maker_rate": 0.0},
    "polymarket_intl": {"rate": 0.05, "rounding": "5dp", "maker_rate": 0.0},
}
VENUE_MIN_EDGE = {"kalshi": 0.04, "polymarket_us": 0.04}   # expected value per $1 contract, after fees
THIN_CONSENSUS_EXTRA_EDGE = 0.01         # +1pp when only 2 books make the consensus
# Extra edge by stat, on top of the venue's. Rohan's call after Oct 25: rebounds were the only stat
# whose closing line ran against us (-2.0c over its first 14 tickets). Revisit at 50 rebound tickets.
STAT_EXTRA_EDGE = {"rebounds": 0.02}
MIN_SIZE_AT_EDGE = {"kalshi": 10, "polymarket_us": 10}     # contracts available at or under the max price
PLANNED_CONTRACTS = 10                   # order size used to price fees before sizing
TAIL_P = (0.10, 0.90)                    # market P outside this: the rung is too far from the books' line
LEAK_TOLERANCE_MIN = 2                   # consensus may not be newer than the venue quote by more than this
QUESTIONABLE_STATUSES = frozenset({"questionable", "game time decision", "gtd", "probable"})
OUT_STATUSES = frozenset({"out", "doubtful", "suspended", "inactive", "injured", "not with team"})

# Model vs market: price contracts from a blend that leans on the market
# (mean space): m = consensus + W_MODEL * (model - consensus), and only while
# |model - consensus| <= Z_GAP_MAX consensus SDs (beyond that w = 0 and the row
# is flagged). Frozen until walk-forward grading has ~800 rows.
W_MODEL = 0.20
Z_GAP_MAX = 0.75
# Robust pricing away from the books' line: a contract's probability is the
# lower of the linear SD (sd_fraction) and a compound-Poisson SD,
# sqrt(a * m + (b * m)^2), so far rungs aren't priced off one SD assumption.
SD_COMPOUND = (2.2, 0.15)
# Rebounds and assists are counts: negative binomial with Var = phi * mean, as (phi, phi_alt).
# A contract is priced at the lower of the two, like SD_COMPOUND for points. phi sits on
# 2021-24 box scores (var / mean around a 20-game mean: 1.26 rebounds, 1.15 assists, plus a
# little for opening-night uncertainty about the mean); phi_alt on the top of the range the
# opening-week Kalshi and Polymarket US ladders imply. Frozen until graded.
COUNT_DISPERSION = {"rebounds": (1.30, 1.50), "assists": (1.15, 1.30)}

# --- Sizing (suggested contracts only; nothing is ever placed) ---------------------
# Set COLD_START_BANKROLL_USD in the environment (or .env) to see stakes; see bankroll_usd().
BANKROLL_ENV = "COLD_START_BANKROLL_USD"
KELLY_LAMBDA = 0.25                      # quarter Kelly
MAX_BET_FRAC = 0.005                     # per contract and per player-game, while ungraded
MAX_GAME_FRAC = 0.015                    # both teams in one game
MAX_SLATE_FRAC = 0.03                    # one ET slate
TICKET_CANCEL_BEFORE_TIP_MIN = 5         # cancel unfilled limit orders this long before tip
VENUE_SIGNAL_MAX_AGE_MIN = 20            # tickets and READY come only from a venue read this recent

# Venue snapshots (free public reads), minutes before tip. t-5m is the venue close for CLV.
VENUE_OFFSETS_MIN = {"t-6h": 360, "t-2h": 120, "t-60m": 60, "t-15m": 15, "t-5m": 5}
VENUE_CLOSE_TAG = "t-5m"

# --- League-wide catalog (catalog.py) ------------------------------------------------
USAGE_TIERS = {"high": 25.0, "medium": 18.0}   # 2025-26 USG%: >= 25 high, >= 18 medium, else low
CATALOG_PRESSURE_PCT = 2.0               # team usage demand beyond +-2% of budget counts as a change
CATALOG_MIN_USG_SHIFT = 0.5              # player usage must move at least this many points
# Teams left out of the catalog, the board, the projections and the venue scan. Empty: all 30
# teams are modeled. The mechanism stays so a team can be parked again in one line.
CATALOG_EXCLUDED_TEAMS: frozenset[str] = frozenset()


# --- Usage-squeeze model ---------------------------------------------------------
# Rebounds and assists use a team budget too, with diminishing returns: a team's raw demand
# D = sum(rate_i * minutes_i) is pulled toward the league budget B by k = (B / D) ** rho
# (rho = 1: the team total always equals B; rho = 0: no pull). Frozen priors from the
# lineup-regression literature, not fitted here: about 0.3 of a player's above-average
# defensive rebounding and 0.7 of his offensive rebounding reach the team total, about 0.4
# by volume, so rho = 1 - 0.4 = 0.6 for total rebounds (if split: ~0.7 defensive, ~0.3
# offensive); assists sit between the two (0.5, weak evidence).
# Check them out of sample on team-changers once graded.
RHO_REB = 0.6
RHO_AST = 0.5


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
    rho_reb: float = RHO_REB             # rebound budget pull (see RHO_REB above)
    rho_ast: float = RHO_AST             # assist budget pull


MODEL = ModelParams()
MODEL_VERSION = "usage-squeeze-1.1"      # 1.1: rebounds and assists

# --- Rolling projections (features.py) ------------------------------------------------
# Where a projection's inputs come from: "season" = last season's averages and the scenario's
# minutes (the model above, unchanged); "rolling" = the same usage model fed by this season's
# box scores before tip, shrunk to last season. "season" stays until `evaluate` shows rolling
# beating it out of sample (docs/MODEL_V2_PLAN.md).
PROJECTION_SOURCE = "season"
ROLLING_MODEL_VERSION = "usage-squeeze-1.1+rolling-0.1"
# Prior weight in games of last season's rate: shrunk = (K * prior + sum) / (K + minutes),
# K = games * prior minutes per game; "minutes" is in games of the scenario's minutes. Frozen
# priors from how fast each stat settles (rebounds and usage fast, threes and steals slow), to
# fit on 2025-26 box scores (stage 2).
ROLLING_PRIOR_GAMES = {"minutes": 3, "usage": 6, "points": 6, "rebounds": 5, "assists": 5,
                       "threes": 12, "steals": 15, "blocks": 10, "turnovers": 10}
TEAM_CHANGE_PRIOR_SCALE = 0.5            # a new team halves the prior's weight
ROLLING_MINUTES_CAP = 38.0               # added minutes stop here (a player already above keeps his)
TEAM_PRIOR_GAMES = 10                    # pace and opponent allowances, in games of league average
CONTEXT_CLAMP = (0.90, 1.10)             # pace and opponent multipliers
# Role stability over the last 10 games (coefficients of variation), and the points SD multiplier
# per class. Fewer than min_games: "unknown".
ROLE_CLASSES = {"min_games": 4, "engine_minutes": 30.0, "engine_cv_minutes": 0.12, "engine_cv_usage": 0.20,
                "heat_check_cv_points": 0.40, "volatile_cv_minutes": 0.25}
ROLE_SD_MULT = {"engine": 1.0, "steady": 1.0, "volatile_role": 1.10, "heat_check": 1.10, "unknown": 1.0}
# Logged for validation only (extra_projections): the venue scan never reads them.
EXTRA_STATS = ("threes", "steals", "blocks", "turnovers")


def current_model_version(source: str | None = None) -> str:
    """The model_version a projection run logs under `source` (default PROJECTION_SOURCE)."""
    return ROLLING_MODEL_VERSION if (source or PROJECTION_SOURCE) == "rolling" else MODEL_VERSION

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


def env_value(name: str) -> str | None:
    """An environment variable, falling back to the git-ignored .env file."""
    value = os.environ.get(name)
    if value:
        return value.strip()
    env_file = REPO_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() == name:
                return val.strip().strip('"').strip("'") or None
    return None


def bankroll_usd() -> float | None:
    """Rohan's bankroll for suggested contract counts. Typed in by him; no account is ever read."""
    raw = env_value(BANKROLL_ENV)
    try:
        value = float(raw) if raw else None
    except ValueError:
        return None
    return value if value and value > 0 else None
