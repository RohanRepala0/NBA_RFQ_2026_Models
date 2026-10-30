"""Pre-market board: the positions waiting on Kalshi and Polymarket US.

One row per catalog player whose role changed (arrival / vacuum / squeeze):
the thesis, our projection, and fair "N+ points" prices. As markets open the
row moves through:
  waiting for a line -> lean vs books (no venue price) / listed on Kalshi
  -> listed, no edge / watch (thin, questionable) -> READY (venue)
READY comes only from a logged venue decision (venues.scan ->
decision.evaluate_contract): a Kalshi or Polymarket US price that clears the
bar after fees, with size behind it and the sportsbook market not against it.
A sportsbook line alone is never READY: Rohan can't trade there.

The thesis, projection and fair ladder are points. The venue status is the
player's best logged decision on any stat, labelled with it ("READY (Kalshi):
buy 8+ REB YES ...") when that is a rebounds or assists contract.

Research only: the board lists what to look at; it never places anything.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from . import config
from .consensus import consensus_by_player
from .players import name_from_player_id, name_key
from .signals import make_signal
from .storage import Storage
from .watchlist import p_at_least

SITUATION_ORDER = {"vacuum": 0, "arrival": 1, "squeeze": 2}
TIER_ORDER = {"high": 0, "medium": 1, "low": 2}
VENUE_NAME = {"kalshi": "Kalshi", "polymarket_us": "Polymarket US", "polymarket_intl": "Polymarket intl"}


def rungs(mean: float) -> list[int]:
    """Kalshi's player-points ladders step by 5 (10+, 15+, 20+, ...): the three around the projection."""
    base = max(5, int(round(mean / 5.0)) * 5)
    return [n for n in (base - 5, base, base + 5) if n >= 5]


def market_view(storage: Storage | None, now: datetime) -> dict[str, dict]:
    """name_key -> latest sportsbook consensus across stored, un-tipped events."""
    if storage is None or storage.count("odds_snapshots") == 0:
        return {}
    ev = storage.latest_events()
    ev = ev[(ev.starts_at > now) & ~ev.cancelled.fillna(False).astype(bool)]
    out: dict[str, dict] = {}
    for e in ev.itertuples():
        for pid, c in consensus_by_player(storage, e.event_id, as_of=now, before=now).items():
            out[name_key(name_from_player_id(pid))] = {"event_id": e.event_id, "starts_at": e.starts_at, "consensus": c}
    return out


def venue_view(storage: Storage | None, now: datetime) -> dict[tuple[str, str], pd.DataFrame]:
    """(name_key, team) -> latest logged venue decisions for games that haven't tipped."""
    if storage is None or storage.count("venue_signals") == 0:
        return {}
    from .venues import latest_venue_signals
    df = latest_venue_signals(storage, now)
    if df.empty:
        return {}
    df = df.assign(key=df.player.fillna("").map(name_key))
    return {k: g for k, g in df.groupby(["key", df.team.fillna("")])}


def _cents(x) -> str:
    return "?" if x is None or pd.isna(x) else f"{100 * x:.0f}c"


def venue_status(rows: pd.DataFrame) -> dict:
    """Best line of the board from a player's logged venue decisions."""
    if "stat" in rows:                                   # a shadow stat is never a player's displayed line
        rows = rows[~rows.stat.isin(config.SHADOW_STATS)]
    act = rows[rows.decision == "actionable"]
    if len(act):
        r = act.sort_values("ev_blend", ascending=False).iloc[0]
        size = (f" x {int(r.contracts)} (${r.stake_usd:.2f})" if pd.notna(r.contracts)
                else " (set COLD_START_BANKROLL_USD for a size)")
        return {"status": f"READY ({VENUE_NAME[r.venue]}): buy {r.contract} at or under {_cents(r.max_price)}"
                          f"{size}, EV {100 * r.ev_blend:.1f}pp",
                "venue": r.venue, "contract": r.contract, "max_cents": round(100 * r.max_price),
                "ev_pp": round(100 * r.ev_blend, 1), "contracts": r.contracts}
    watch = rows[rows.decision == "watch"]
    if len(watch):
        r = watch.sort_values("ev_blend", ascending=False).iloc[0]
        return {"status": f"watch ({VENUE_NAME[r.venue]} {r.contract} at {_cents(r.ask)}): {r.reason}",
                "venue": r.venue, "contract": r.contract, "max_cents": None, "ev_pp": round(100 * r.ev_blend, 1),
                "contracts": None}
    priced = rows[rows.ev_blend.notna()] if "ev_blend" in rows else rows.iloc[0:0]
    if len(priced):
        r = priced.sort_values("ev_blend", ascending=False).iloc[0]
        return {"status": f"listed, no edge: best is {VENUE_NAME[r.venue]} {r.contract} at {_cents(r.ask)} "
                          f"({r.reason})", "venue": r.venue, "contract": None, "max_cents": None,
                "ev_pp": round(100 * r.ev_blend, 1), "contracts": None}
    r = rows.iloc[0]
    return {"status": f"listed on {VENUE_NAME.get(r.venue, r.venue)}: {r.reason}", "venue": r.venue,
            "contract": None, "max_cents": None, "ev_pp": None, "contracts": None}


def build_board(catalog: pd.DataFrame, storage: Storage | None = None, now: datetime | None = None,
                kalshi: pd.DataFrame | None = None) -> pd.DataFrame:
    """`kalshi`: parsed open Kalshi markets (kalshi.parse_markets), shown as listings with our
    fair price next to the ask. Listings alone never make a row READY."""
    from .storage import utcnow
    now = now or utcnow()
    markets = market_view(storage, now)
    venues = venue_view(storage, now)
    kalshi = pd.DataFrame() if kalshi is None else kalshi
    if len(kalshi):
        points = kalshi.stat.eq("points") if "stat" in kalshi else True     # the fair ladder is points
        kalshi = kalshi[kalshi.parse_error.isna() & (kalshi.tip_est > now) & points]
    rows = []
    live = catalog[(catalog.situation != "steady") & catalog.proj.notna()
                   & ~catalog.team.isin(config.CATALOG_EXCLUDED_TEAMS)]
    for r in live.itertuples():
        sd = r.sd if not pd.isna(r.sd) else max(config.MODEL.sd_floor, config.MODEL.sd_fraction * r.proj)
        key = name_key(r.player)
        row = {
            "tier": r.tier, "situation": r.situation, "team": r.team, "player": r.player,
            "thesis": r.thesis, "proj": r.proj, "ppg_2025_26": r.ppg_2025_26,
            "usg_change": r.usg_change, "scenario_source": r.scenario_source,
        }
        for n in rungs(r.proj):
            row[f"fair_{n}+"] = round(100 * p_at_least(n, r.proj, sd), 0)
        row["fair_ladder"] = "  ".join(f"{n}+ {100 * p_at_least(n, r.proj, sd):.0f}c" for n in rungs(r.proj))
        listed = ""
        k = kalshi[(kalshi.key == key) & (kalshi.team == r.team)] if len(kalshi) else kalshi
        if len(k):
            listed = ", ".join(f"{int(q.threshold)}+ {_cents(q.yes_ask)} (fair {100 * p_at_least(int(q.threshold), r.proj, sd):.0f}c)"
                               for q in k.sort_values("threshold").itertuples())
        row.update(kalshi=listed, venue=None, contract=None, max_cents=None, ev_pp=None, contracts=None)
        v = venues.get((key, r.team))
        if v is not None:
            row.update(venue_status(v))
        elif key in markets:
            sig = make_signal({"mean": r.proj, "sd": sd}, markets[key]["consensus"])
            if sig["decision"] == "paper":
                lean = f"lean vs books: {sig['side']} {sig['line']:g} by {100 * sig['edge']:.1f}pp"
            elif sig["line"] is not None:
                lean = f"books {sig['line']:g}: {sig['reason']}"
            else:
                lean = f"books: {sig['reason']}"
            row["status"] = f"{lean} (no venue price yet)"
        elif listed:
            row["status"] = "listed on Kalshi (no sportsbook consensus yet)"
        else:
            row["status"] = "waiting for a line"
        rows.append(row)
    board = pd.DataFrame(rows)
    if board.empty:
        return board
    board["_s"] = board.situation.map(SITUATION_ORDER)
    board["_t"] = board.tier.map(TIER_ORDER)
    board["_m"] = -board.usg_change.abs()
    return board.sort_values(["_t", "_s", "_m"]).drop(columns=["_s", "_t", "_m"]).reset_index(drop=True)


def board_markdown(board: pd.DataFrame, counts: pd.DataFrame, built: datetime) -> str:
    lines = ["# Pre-market board: role changes waiting on Kalshi and Polymarket US", "",
             "Each row is a player whose usage should move this season. **Fair** prices are what our",
             "projection says an \"N+ points\" YES contract is worth, in cents. A row turns `READY` only when",
             "a Kalshi or Polymarket US price clears the edge bar after the venue's fee, with size at or",
             "under the max price and the sportsbook consensus not against it. A sportsbook line on its",
             "own shows as a lean, never as READY.", "",
             "## How many situations", "",
             "| tier (2025-26 usage) | " + " | ".join(counts.columns) + " |",
             "|---|" + "---|" * len(counts.columns)]
    for t, r in counts.iterrows():
        lines.append(f"| {t} | " + " | ".join(str(int(v)) for v in r.values) + " |")
    for tier_name in ("high", "medium", "low"):
        part = board[board.tier == tier_name]
        lines += ["", f"## {tier_name.capitalize()} usage ({len(part)})", "",
                  "| player | team | situation | thesis | proj (25-26) | fair ladder | status |",
                  "|---|---|---|---|---|---|---|"]
        for r in part.itertuples():
            status = r.status
            if isinstance(r.kalshi, str) and r.kalshi and not status.startswith("READY"):
                status += f" - Kalshi: {r.kalshi}"
            lines.append(f"| {r.player} | {r.team} | {r.situation} | {r.thesis} | "
                         f"{r.proj:.1f} ({r.ppg_2025_26:.1f}) | {r.fair_ladder} | {status} |")
    return "\n".join(lines) + "\n"
