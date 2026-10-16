"""Pre-market board: the positions waiting on prediction markets.

One row per catalog player whose role changed (arrival / vacuum / squeeze):
the thesis, our projection, and fair "N+ points" prices. As markets open,
the same rows fill in the sportsbook consensus, the edge, and any
prediction-market price SportsGameOdds reports, so the board turns from
"waiting for a line" into "line up, here is the gap" without a new tool.

Research only: the board lists what to look at, it never places anything.
"""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from . import config
from .consensus import consensus_by_player, venue_quotes
from .players import name_from_player_id, name_key
from .signals import make_signal
from .storage import Storage
from .watchlist import cents_floor, contract_for, contract_p, max_price, p_at_least

SITUATION_ORDER = {"vacuum": 0, "arrival": 1, "squeeze": 2}
TIER_ORDER = {"high": 0, "medium": 1, "low": 2}


def rungs(mean: float) -> list[int]:
    """Kalshi's player-points ladders step by 5 (10+, 15+, 20+, ...): the three around the projection."""
    base = max(5, int(round(mean / 5.0)) * 5)
    return [n for n in (base - 5, base, base + 5) if n >= 5]


def market_view(storage: Storage | None, now: datetime) -> dict[str, dict]:
    """name_key -> latest consensus + venue quotes across stored events (pre-tip only)."""
    if storage is None or storage.count("odds_snapshots") == 0:
        return {}
    ev = storage.latest_events()
    ev = ev[(ev.starts_at > now) & ~ev.cancelled.fillna(False).astype(bool)]
    out: dict[str, dict] = {}
    for e in ev.itertuples():
        cons = consensus_by_player(storage, e.event_id, as_of=now, before=now)
        venues = venue_quotes(storage, e.event_id, before=now)
        for pid, c in cons.items():
            key = name_key(name_from_player_id(pid))
            out[key] = {"event_id": e.event_id, "starts_at": e.starts_at, "consensus": c,
                        "venues": venues[venues.player_id == pid] if not venues.empty else venues}
    return out


def build_board(catalog: pd.DataFrame, storage: Storage | None = None,
                now: datetime | None = None, kalshi: pd.DataFrame | None = None) -> pd.DataFrame:
    """`kalshi`: parsed open Kalshi markets (kalshi.parse_markets); rows with a rung
    priced below our fair value by EDGE_THRESHOLD after fees become READY (Kalshi)."""
    from .kalshi import best_trade
    from .storage import utcnow
    now = now or utcnow()
    markets = market_view(storage, now)
    kalshi = pd.DataFrame() if kalshi is None else kalshi
    rows = []
    live = catalog[(catalog.situation != "steady") & catalog.proj.notna()
                   & ~catalog.team.isin(config.CATALOG_EXCLUDED_TEAMS)]
    for r in live.itertuples():
        sd = r.sd if not pd.isna(r.sd) else max(config.MODEL.sd_floor, config.MODEL.sd_fraction * r.proj)
        row = {
            "tier": r.tier, "situation": r.situation, "team": r.team, "player": r.player,
            "thesis": r.thesis, "proj": r.proj, "ppg_2025_26": r.ppg_2025_26,
            "usg_change": r.usg_change, "scenario_source": r.scenario_source,
        }
        for n in rungs(r.proj):
            row[f"fair_{n}+"] = round(100 * p_at_least(n, r.proj, sd), 0)
        row["fair_ladder"] = "  ".join(f"{n}+ {100 * p_at_least(n, r.proj, sd):.0f}c" for n in rungs(r.proj))
        m = markets.get(name_key(r.player))
        if m is None:
            row.update(status="waiting for a line", line=None, side=None, edge_pp=None,
                       contract=None, max_cents=None, posted="")
        else:
            c = m["consensus"]
            sig = make_signal({"mean": r.proj, "sd": sd}, c)
            contract, max_c = None, None
            if sig["side"]:
                n, outcome = contract_for(sig["side"], sig["line"])
                p = contract_p(n, outcome, r.proj, sd)
                contract = f"{n}+ {outcome}"
                max_c = cents_floor(max_price(p, max(config.VENUE_FEE_RATE.values())))
            posted = "; ".join(f"{q.book} {q.side} {q.line:g} @ {round(100 * (100 / (q.odds_american + 100) if q.odds_american > 0 else -q.odds_american / (-q.odds_american + 100)))}c"
                               for q in m["venues"].itertuples()) if len(m["venues"]) else ""
            row.update(status=("READY: " if sig["decision"] == "paper" else "line up: ") + sig["reason"],
                       line=sig["line"], side=sig["side"],
                       edge_pp=None if sig["edge"] is None else round(100 * sig["edge"], 1),
                       contract=contract, max_cents=max_c, posted=posted)
        row.update(kalshi="", kalshi_roi=None)
        k = kalshi[kalshi.key == name_key(r.player)] if len(kalshi) else kalshi
        if len(k):
            p_yes = {int(n): p_at_least(int(n), r.proj, sd) for n in k.threshold.unique()}
            trade = best_trade(p_yes, k, config.VENUE_FEE_RATE["kalshi"], config.EDGE_THRESHOLD)
            listed = ", ".join(f"{int(q.threshold)}+ {q.yes_ask:.0f}c" for q in k.sort_values("threshold").itertuples()
                               if q.yes_ask is not None and not pd.isna(q.yes_ask))
            if trade:
                row.update(status=f"READY (Kalshi): buy {trade['contract']} @ {trade['ask_cents']:.0f}c, "
                                  f"fair {trade['fair_cents']:.0f}c, ROI {100 * trade['roi']:+.0f}%",
                           kalshi=listed, kalshi_roi=trade["roi"])
            else:
                row.update(kalshi=listed, status=row["status"] if row["status"] != "waiting for a line"
                           else "Kalshi listed: no rung clears 4pp")
        rows.append(row)
    board = pd.DataFrame(rows)
    if board.empty:
        return board
    board["_s"] = board.situation.map(SITUATION_ORDER)
    board["_t"] = board.tier.map(TIER_ORDER)
    board["_m"] = -board.usg_change.abs()
    return board.sort_values(["_t", "_s", "_m"]).drop(columns=["_s", "_t", "_m"]).reset_index(drop=True)


def board_markdown(board: pd.DataFrame, counts: pd.DataFrame, built: datetime) -> str:
    lines = ["# Pre-market board: role changes waiting on prediction markets", "",
             "Each row is a player whose usage should move this season. **Fair** prices are what our",
             "projection says an \"N+ points\" YES contract is worth, in cents. Once a sportsbook line",
             "posts, the status shows the gap to the market consensus; `READY` rows clear the 4pp",
             "threshold, and **max** is the most to pay after a 0.07 x P x (1-P) taker fee.", "",
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
            status = r.status + (f" - {r.contract} max {r.max_cents}c" if r.contract else "")
            if r.posted:
                status += f" - posted: {r.posted}"
            lines.append(f"| {r.player} | {r.team} | {r.situation} | {r.thesis} | "
                         f"{r.proj:.1f} ({r.ppg_2025_26:.1f}) | {r.fair_ladder} | {status} |")
    return "\n".join(lines) + "\n"
