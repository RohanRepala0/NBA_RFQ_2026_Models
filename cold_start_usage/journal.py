"""The bet journal: a committed record of every ticket, fill and result, rebuilt from the log.

The decision log (data/edge_lab.duckdb) is git-ignored, so the season's record is written out
to bets/ as plain CSV and markdown and committed:

    bets/ledger.csv                     one row per ticket, every date
    bets/fills.csv                      every fill logged with `cli fill`, corrections marked
    bets/days/YYYY-MM-DD/tickets.csv    every actionable row for that slate, repeats flagged
    bets/days/YYYY-MM-DD/results.csv    each ticket graded, with any fills on it
    bets/days/YYYY-MM-DD/summary.md     slate, tickets, totals, CLV by stat, scenarios, pending

A *ticket* is the paper bet: the first actionable decision per player-game and stat, at its
logged all-in cost and suggested size (grade.venue_graded's rule, which this reuses). A *fill*
is what Rohan entered by hand (the DB table named `tickets`). A day is the ET date of the
games' tip, so a decision logged the evening before files under the game's day.

Read-only: nothing here writes to the database or calls an API. Settlements come from
`cli grade`, which runs first; anything unsettled reads `pending`. Output is deterministic
(stable sorts, fixed float formats, no generated-at stamps), so a rebuild with no new data
leaves the tree byte-identical.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from . import config
from .grade import fills_graded, venue_graded
from .schedule import et_date
from .storage import Storage

VENUE_LABELS = {"kalshi": "Kalshi", "polymarket_us": "PM US"}
FILL_KINDS = ("real", "paper", "discretionary")

# --- column formats -------------------------------------------------------------------------
# price: dollars to 4 places; usd: 2 places; mean: 2 places; num: a count, trailing zeros cut.
FORMATS = {
    **dict.fromkeys(["ask", "bid", "limit", "cost", "p_market", "p_blend", "ev_market", "ev_blend",
                     "settlement_value", "pnl_per_contract", "close_mid", "clv", "fill_avg_price",
                     "price"], "price"),
    **dict.fromkeys(["suggested_stake_usd", "pnl_suggested_usd", "fill_pnl_usd", "fill_fees_usd",
                     "fees_usd", "cost_usd", "pnl_usd"], "usd"),
    **dict.fromkeys(["consensus_mean", "model_mean"], "mean"),
    **dict.fromkeys(["suggested_contracts", "size_at_edge", "filled_contracts", "contracts", "n_books"], "num"),
}

LEDGER_COLUMNS = [
    "date_et", "game", "tip_et", "tip_utc", "checkpoint", "first_seen_et", "first_seen_utc", "venue", "ticker",
    "player", "team", "stat", "contract", "side", "ask", "limit", "cost", "suggested_contracts",
    "suggested_stake_usd", "p_market", "p_blend", "ev_market", "ev_blend", "n_books", "consensus_mean",
    "model_mean", "signal_id", "result", "outcome", "settlement_value", "pnl_per_contract", "pnl_suggested_usd",
    "close_mid", "clv", "filled_contracts", "fill_avg_price", "fill_fees_usd", "fill_pnl_usd", "fill_kind",
]
RESULTS_COLUMNS = [
    "tip_et", "game", "player", "team", "stat", "contract", "side", "venue", "ticker", "checkpoint", "ask",
    "cost", "suggested_contracts", "suggested_stake_usd", "p_blend", "result", "outcome", "settlement_value",
    "pnl_per_contract", "pnl_suggested_usd", "close_mid", "clv", "filled_contracts", "fill_avg_price",
    "fill_fees_usd", "fill_pnl_usd", "fill_kind", "signal_id",
]
TICKETS_COLUMNS = [
    "logged_et", "logged_utc", "checkpoint", "game", "tip_et", "venue", "ticker", "player", "team", "stat",
    "contract", "side", "bid", "ask", "limit", "size_at_edge", "suggested_contracts", "suggested_stake_usd",
    "p_market", "p_blend", "ev_market", "ev_blend", "n_books", "consensus_mean", "model_mean", "reason",
    "signal_id", "flag",
]
FILLS_COLUMNS = [
    "fill_id", "date_et", "game", "tip_et", "filled_at_et", "filled_at_utc", "logged_utc", "venue", "ticker",
    "player", "team", "stat", "contract", "side", "contracts", "price", "fees_usd", "cost_usd", "kind",
    "status", "replaces", "superseded_by", "signal_id", "ticket_signal_id", "matches_ticket", "result",
    "settlement_value", "pnl_usd", "note",
]


def _missing(v) -> bool:
    return v is None or (not isinstance(v, str) and pd.isna(v))


def _fmt(v, kind: str = "str") -> str:
    if _missing(v):
        return ""
    if kind in ("price", "usd", "mean"):
        places = {"price": 4, "usd": 2, "mean": 2}[kind]
        x = round(float(v), places)
        return f"{0.0 if x == 0 else x:.{places}f}"
    if kind == "num":
        x = round(float(v), 2)
        return str(int(x)) if x == int(x) else f"{x:.2f}".rstrip("0")
    return str(v)


def _utc(ts) -> str | None:
    return None if _missing(ts) else pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def _et(ts, fmt: str = "%Y-%m-%d %H:%M") -> str | None:
    if _missing(ts):
        return None
    return pd.Timestamp(ts).tz_localize("UTC").tz_convert(config.ET).strftime(fmt)


def _csv(df: pd.DataFrame, columns: list[str]) -> str:
    out = pd.DataFrame({c: [_fmt(v, FORMATS.get(c, "str")) for v in (df[c] if c in df else [None] * len(df))]
                        for c in columns}, columns=columns)
    return out.to_csv(index=False, lineterminator="\n")


def _group_key(df: pd.DataFrame) -> pd.Series:
    """(game, player, stat) the way grade.venue_graded partitions: event id else event ticker,
    player id else name, a NULL stat as points."""
    game = df.event_id.where(df.event_id.notna(), df.event_ticker)
    player = df.player_id.where(df.player_id.notna(), df.player)
    stat = df.stat.where(df.stat.notna(), "points")
    return pd.Series(list(zip(game, player, stat)), index=df.index, dtype=object)


# --- what the journal reads -----------------------------------------------------------------

def journal_dates(storage: Storage, fills: pd.DataFrame | None = None) -> list[date]:
    """Every ET slate date with a logged venue decision or a fill."""
    tips = storage.query("SELECT DISTINCT tip_ts FROM venue_signals WHERE tip_ts IS NOT NULL").tip_ts
    days = {et_date(t) for t in tips}
    fills = fills_journal(storage) if fills is None else fills
    days |= {d for d in fills.date_et if not _missing(d)} if len(fills) else set()
    return sorted(days)


def graded_tickets(storage: Storage) -> pd.DataFrame:
    """Every ticket (grade.venue_graded across all dates), with its outcome and P&L at the
    suggested size."""
    tips = storage.query("SELECT min(tip_ts) AS lo, max(tip_ts) AS hi FROM venue_signals "
                         "WHERE decision = 'actionable'")
    if tips.empty or _missing(tips.lo.iloc[0]):
        return pd.DataFrame()
    g = venue_graded(storage, et_date(tips.lo.iloc[0]), et_date(tips.hi.iloc[0]))
    if g.empty:
        return g
    g = g.sort_values(["tip_ts", "ts", "game", "player", "stat", "signal_id"], kind="mergesort").reset_index(drop=True)
    g["date_et"] = g.game_date
    g["group"] = _group_key(g)

    def outcome(r):
        if _missing(r.value):
            return "pending"
        if r.result == "scalar":
            return "fair price"
        return "won" if r.value >= 1 - 1e-9 else "lost"

    g["outcome"] = g.apply(outcome, axis=1)
    g["result"] = g.result.where(g.result.notna(), "pending")
    g["pnl_suggested_usd"] = g.contracts * g.pnl_per_contract
    return g


def actionable_rows(storage: Storage, tickets: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every actionable decision at every checkpoint, oldest first, flagged: `ticket` (the graded
    one), `repeat of <signal_id>` (the same venue, ticker and side was already actionable), or
    `new contract after ticket <signal_id>` (another contract on a player-stat already ticketed)."""
    df = storage.query("""SELECT * REPLACE (coalesce(stat, 'points') AS stat) FROM venue_signals
                          WHERE decision = 'actionable' AND tip_ts IS NOT NULL""")
    if df.empty:
        return df
    tickets = graded_tickets(storage) if tickets is None else tickets
    df = df.sort_values(["ts", "ev_blend", "signal_id"], ascending=[True, False, True],
                        kind="mergesort").reset_index(drop=True)
    df["date_et"] = df.tip_ts.map(et_date)
    df["group"] = _group_key(df)
    chosen = set(zip(tickets.signal_id, pd.to_datetime(tickets.ts))) if len(tickets) else set()
    ticket_of = dict(zip(tickets.group, tickets.signal_id)) if len(tickets) else {}
    first_on_contract: dict[tuple, str] = {}
    flags = []
    for r in df.itertuples():
        contract = (r.venue, r.ticker, r.side)
        if (r.signal_id, pd.Timestamp(r.ts)) in chosen:
            flags.append("ticket")
        elif contract in first_on_contract:
            flags.append(f"repeat of {first_on_contract[contract]}")
        else:
            flags.append(f"new contract after ticket {ticket_of.get(r.group, '?')}")
        first_on_contract.setdefault(contract, r.signal_id)
    df["flag"] = flags
    return df


def fill_kind(note, signal_id, actionable: bool) -> str:
    """paper: the note starts with 'paper'. discretionary: the note starts with 'discretionary', or
    no signal id on a contract the scan never made actionable. Anything else is real."""
    text = "" if _missing(note) else str(note).strip().lower()
    if text.startswith("paper"):
        return "paper"
    if text.startswith("discretionary") or (_missing(signal_id) and not actionable):
        return "discretionary"
    return "real"


def fills_journal(storage: Storage, tickets: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every fill Rohan logged, corrections included: a replaced fill stays, marked superseded
    (P&L only on the current one, from grade.fills_graded), with its kind and the game it's on."""
    t = storage.query("SELECT * FROM tickets")
    if t.empty:
        return pd.DataFrame(columns=FILLS_COLUMNS)
    t = t.sort_values(["ts", "fill_id"], kind="mergesort").reset_index(drop=True)
    graded = fills_graded(storage)
    t = t.merge(graded[["fill_id", "result", "settlement_value", "pnl"]], on="fill_id", how="left")
    info = storage.query("""
        SELECT * EXCLUDE (rn) FROM (
          SELECT venue, ticker, side, event_id, event_ticker, game, player_id, player, team,
                 coalesce(stat, 'points') AS stat, contract, tip_ts,
                 row_number() OVER (PARTITION BY venue, ticker, side ORDER BY ts, signal_id) rn
          FROM venue_signals WHERE ticker IS NOT NULL) WHERE rn = 1""")
    t = t.merge(info, on=["venue", "ticker", "side"], how="left")
    acted = set(map(tuple, storage.query("""SELECT DISTINCT venue, ticker, side FROM venue_signals
                                            WHERE decision = 'actionable'""").itertuples(index=False)))
    by_replaced: dict[str, list[str]] = {}
    for r in t[t.replaces.notna()].itertuples():
        by_replaced.setdefault(r.replaces, []).append(r.fill_id)
    kinds: dict[str, str] = {}
    for r in t.itertuples():
        own = fill_kind(r.note, r.signal_id, (r.venue, r.ticker, r.side) in acted)
        blank_note = _missing(r.note) or not str(r.note).strip()
        # A correction with no note of its own keeps the kind of the fill it replaces.
        kinds[r.fill_id] = kinds.get(r.replaces, own) if blank_note and not _missing(r.replaces) else own
    t["kind"] = t.fill_id.map(kinds)
    t["superseded_by"] = t.fill_id.map(lambda f: ",".join(by_replaced[f]) if f in by_replaced else None)
    t["status"] = t.superseded_by.map(lambda s: "current" if _missing(s) else "superseded")
    t["fees_usd"] = t.fees.fillna(0.0)
    t["cost_usd"] = t.contracts * t.price + t.fees_usd
    t["pnl_usd"] = t.pnl.where(t.status == "current")
    when = t.filled_at.where(t.filled_at.notna(), t.ts)
    t["date_et"] = [et_date(tip) if not _missing(tip) else et_date(w) for tip, w in zip(t.tip_ts, when)]
    t["tip_et"] = t.tip_ts.map(_et)
    t["filled_at_et"] = when.map(lambda x: _et(x, "%Y-%m-%d %H:%M:%S"))
    t["filled_at_utc"] = when.map(_utc)
    t["logged_utc"] = t.ts.map(_utc)
    tickets = graded_tickets(storage) if tickets is None else tickets
    if len(tickets):
        ticket_of = dict(zip(tickets.group, tickets.signal_id))
        on_ticket = set(zip(tickets.venue, tickets.ticker, tickets.side))
        known = t.game.notna()
        keys = _group_key(t[known]).to_dict() if known.any() else {}
        t["ticket_signal_id"] = [ticket_of.get(keys[i]) if i in keys else None for i in t.index]
        t["matches_ticket"] = [("yes" if (v, k, s) in on_ticket else "no") for v, k, s in zip(t.venue, t.ticker, t.side)]
    else:
        t["ticket_signal_id"], t["matches_ticket"] = None, "no"
    t = t.sort_values(["filled_at_utc", "logged_utc", "fill_id"], kind="mergesort").reset_index(drop=True)
    return t


def _with_fills(tickets: pd.DataFrame, fills: pd.DataFrame) -> pd.DataFrame:
    """Per ticket: current fills on the same venue, ticker and side, at the price paid."""
    out = tickets.copy()
    for c in ("filled_contracts", "fill_avg_price", "fill_fees_usd", "fill_pnl_usd", "fill_kind"):
        out[c] = None
    cur = fills[fills.status == "current"] if len(fills) else fills
    for i, r in out.iterrows():
        f = cur[(cur.venue == r.venue) & (cur.ticker == r.ticker) & (cur.side == r.side)] if len(cur) else cur
        if f.empty:
            continue
        n = float(f.contracts.sum())
        out.at[i, "filled_contracts"] = n
        out.at[i, "fill_avg_price"] = float((f.contracts * f.price).sum() / n)
        out.at[i, "fill_fees_usd"] = float(f.fees_usd.sum())
        out.at[i, "fill_pnl_usd"] = float(f.pnl_usd.sum()) if f.pnl_usd.notna().all() else None
        out.at[i, "fill_kind"] = "+".join(k for k in FILL_KINDS if k in set(f.kind))
    return out


def _ledger_frame(tickets: pd.DataFrame) -> pd.DataFrame:
    if tickets.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    t = tickets
    return t.assign(
        tip_et=t.tip_ts.map(_et), tip_utc=t.tip_ts.map(_utc), checkpoint=t.tag,
        first_seen_et=t.ts.map(lambda x: _et(x, "%Y-%m-%d %H:%M:%S")), first_seen_utc=t.ts.map(_utc),
        limit=t.max_price, suggested_contracts=t.contracts, suggested_stake_usd=t.stake_usd, clv=t.clv_venue)


def ledger(storage: Storage) -> pd.DataFrame:
    """The season ledger: one row per ticket, sorted by tip then first-seen time."""
    tickets = graded_tickets(storage)
    return _ledger_frame(_with_fills(tickets, fills_journal(storage, tickets)))


# --- the day files --------------------------------------------------------------------------

@dataclass
class Journal:
    tickets: pd.DataFrame          # graded tickets with fills (ledger rows)
    actionable: pd.DataFrame       # every actionable row, flagged
    fills: pd.DataFrame            # every fill, corrections marked


def build(storage: Storage) -> Journal:
    tickets = graded_tickets(storage)
    fills = fills_journal(storage, tickets)
    return Journal(tickets=_ledger_frame(_with_fills(tickets, fills)),
                   actionable=actionable_rows(storage, tickets), fills=fills)


def day_tickets(j: Journal, d: date) -> pd.DataFrame:
    a = j.actionable
    if a.empty:
        return pd.DataFrame(columns=TICKETS_COLUMNS)
    a = a[a.date_et == d]
    return a.assign(logged_et=a.ts.map(lambda x: _et(x, "%Y-%m-%d %H:%M:%S")), logged_utc=a.ts.map(_utc),
                    checkpoint=a.tag, tip_et=a.tip_ts.map(_et), limit=a.max_price,
                    suggested_contracts=a.contracts, suggested_stake_usd=a.stake_usd)


def day_results(j: Journal, d: date) -> pd.DataFrame:
    t = j.tickets
    return t[t.date_et == d] if len(t) else pd.DataFrame(columns=RESULTS_COLUMNS)


def day_fills(j: Journal, d: date) -> pd.DataFrame:
    f = j.fills
    return f[f.date_et == d] if len(f) else f


def _slate(storage: Storage, d: date) -> pd.DataFrame:
    ev = storage.latest_events()
    if ev.empty:
        return ev
    ev = ev[ev.starts_at.map(et_date) == d]
    ev = ev.assign(game=ev.away_abbr.astype(str) + " @ " + ev.home_abbr.astype(str))
    return ev.sort_values(["starts_at", "game"], kind="mergesort")


def _scenarios(storage: Storage, slate: pd.DataFrame) -> pd.DataFrame:
    """Projections on this slate whose scenario isn't full_strength: team, game, scenario, when it
    was first logged, and whether it was the team's run in force at tip."""
    if slate.empty:
        return pd.DataFrame()
    p = storage.query("""SELECT event_id, team, scenario, player_id, ts FROM projections
                         WHERE scenario IS NOT NULL""")
    p = p[p.event_id.isin(set(slate.event_id))]
    if p.empty:
        return p
    tips = dict(zip(slate.event_id, slate.starts_at))
    p = p.assign(tip=p.event_id.map(tips))
    pre = p[pd.to_datetime(p.ts) < pd.to_datetime(p.tip)].sort_values(["ts", "scenario"], kind="mergesort")
    at_tip = pre.groupby(["event_id", "team"]).scenario.last().to_dict()
    rev = p[p.scenario != "full_strength"]
    if rev.empty:
        return rev
    games = dict(zip(slate.event_id, slate.game))
    out = (rev.groupby(["event_id", "team", "scenario"])
              .agg(first_logged=("ts", "min"), players=("player_id", "nunique")).reset_index())
    out["game"] = out.event_id.map(games)
    out["in_force_at_tip"] = [("yes" if at_tip.get((e, t)) == s else "no")
                              for e, t, s in zip(out.event_id, out.team, out.scenario)]
    return out.sort_values(["first_logged", "team", "scenario"], kind="mergesort")


def _cents(x, signed: bool = False) -> str:
    if _missing(x):
        return ""
    c = round(100 * float(x), 1)
    c = 0.0 if c == 0 else c
    txt = f"{c:g}c"
    return f"+{txt}" if signed and c > 0 else txt


def _usd(x, signed: bool = False) -> str:
    if _missing(x):
        return ""
    v = round(float(x), 2)
    v = 0.0 if v == 0 else v
    sign = "-" if v < 0 else ("+" if signed and v > 0 else "")
    return f"{sign}${abs(v):,.2f}"


def _md_table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return lines


def day_summary(storage: Storage, j: Journal, d: date) -> str:
    res = day_results(j, d)
    acts = day_tickets(j, d)
    fills = day_fills(j, d)
    slate = _slate(storage, d)
    lines = [f"# {d:%Y-%m-%d} ({d:%a})", "",
             "Paper record at the suggested sizes: one ticket per player-game and stat, the first time it was "
             "actionable, at the logged all-in cost. Real money only where a fill is logged. Times are ET. "
             "Rebuilt by `python -m cold_start_usage.cli journal` (see `bets/README.md`). Research only.", ""]

    lines += ["## Slate", ""]
    if slate.empty:
        lines += ["No games stored for this date.", ""]
    else:
        per_game = res.game.value_counts().to_dict() if len(res) else {}
        reads = acts.game.value_counts().to_dict() if len(acts) else {}
        rows = [[g.game, _et(g.starts_at, "%H:%M") or "",
                 "cancelled" if not _missing(g.cancelled) and bool(g.cancelled) else "",
                 str(per_game.get(g.game, 0)), str(reads.get(g.game, 0))] for g in slate.itertuples()]
        lines += _md_table(["Game", "Tip", "Status", "Tickets", "Actionable rows"], rows) + [""]

    lines += ["## Tickets", ""]
    if res.empty:
        lines += ["Nothing actionable.", ""]
    else:
        rows = []
        for r in res.itertuples():
            rows.append([_et(r.tip_ts, "%H:%M"), r.game, r.player, r.contract, VENUE_LABELS.get(r.venue, r.venue),
                         r.checkpoint, _cents(r.ask), _cents(r.cost), _fmt(r.suggested_contracts, "num"),
                         _usd(r.suggested_stake_usd), _cents(r.p_blend), _cents(r.close_mid),
                         _cents(r.clv, signed=True), r.outcome, _usd(r.pnl_suggested_usd, signed=True)])
        lines += _md_table(["Tip", "Game", "Player", "Contract", "Venue", "Checkpoint", "Entry", "All-in", "Size",
                            "Stake", "Fair", "Close", "CLV", "Result", "P&L"], rows)
        repeats = int(acts.flag.str.startswith("repeat").sum()) if len(acts) else 0
        moved = int(acts.flag.str.startswith("new contract").sum()) if len(acts) else 0
        lines += ["", f"Entry is the ask when first actionable; all-in adds the venue fee. Fair is p_blend. Close is "
                      f"the venue's last two-sided mid before tip; CLV = close - entry. {len(acts)} actionable rows "
                      f"logged across checkpoints: {len(res)} tickets, {repeats} repeats of a contract already "
                      f"actionable, {moved} on a different contract for a player-stat already ticketed "
                      "(`tickets.csv`).", ""]

    lines += ["## Totals (paper, at suggested sizes)", ""]
    if res.empty:
        lines += ["No tickets.", ""]
    else:
        settled = res[res.outcome != "pending"]
        sized = settled[settled.suggested_contracts.notna()]
        staked_all = float(res.suggested_stake_usd.fillna(0).sum())
        staked = float(sized.suggested_stake_usd.fillna(0).sum())
        pnl = float(sized.pnl_suggested_usd.sum())
        clv = res.clv.dropna()
        lines += [f"- Tickets: {len(res)} ({len(settled)} settled, {len(res) - len(settled)} pending)",
                  f"- Staked: {_usd(staked_all)} ({_usd(staked)} settled)",
                  f"- P&L: {_usd(pnl, signed=True)} on the settled stake"
                  + (f", yield {100 * pnl / staked:+.1f}%" if staked > 0 else ""),
                  f"- Hits: {_fmt(settled.value.sum(), 'num')} of {len(settled)} settled vs "
                  f"{settled.p_blend.sum():.2f} expected (sum of p_blend; a fair-price settlement counts its "
                  "fraction)",
                  f"- Average CLV: {_cents(clv.mean(), signed=True) if len(clv) else 'n/a'} over {len(clv)} "
                  "tickets with a close"]
        if len(sized) < len(settled):
            lines.append(f"- {len(settled) - len(sized)} settled ticket(s) had no suggested size and are left out "
                         "of the dollar totals")
        lines += ["", "### By stat", ""]
        rows = []
        for stat in sorted(set(res.stat)):
            s = res[res.stat == stat]
            ss = s[(s.outcome != "pending") & s.suggested_contracts.notna()]
            c = s.clv.dropna()
            rows.append([stat, str(len(s)), str(len(c)), _cents(c.mean(), signed=True) if len(c) else "",
                         _usd(ss.suggested_stake_usd.sum()) if len(ss) else "",
                         _usd(ss.pnl_suggested_usd.sum(), signed=True) if len(ss) else ""])
        lines += _md_table(["Stat", "Tickets", "With close", "Avg CLV", "Settled stake", "P&L"], rows) + [""]

    lines += ["## Fills", ""]
    if fills.empty:
        lines += ["None logged.", ""]
    else:
        rows = [[(r.filled_at_et or "")[11:16], r.game or "", r.player or "", r.contract or "",
                 VENUE_LABELS.get(r.venue, r.venue), _fmt(r.contracts, "num"), _cents(r.price), _usd(r.fees_usd),
                 r.kind, r.status, r.outcome_label, _usd(r.pnl_usd, signed=True), r.fill_id]
                for r in fills.assign(outcome_label=fills.apply(_fill_outcome, axis=1)).itertuples()]
        lines += _md_table(["Filled", "Game", "Player", "Contract", "Venue", "Contracts", "Price", "Fees", "Kind",
                            "Status", "Result", "P&L", "Fill"], rows) + [""]
        cur = fills[fills.status == "current"]
        rows = []
        for kind in FILL_KINDS:
            k = cur[cur.kind == kind]
            if k.empty:
                continue
            done = k[k.pnl_usd.notna()]
            rows.append([kind, str(len(k)), _fmt(k.contracts.sum(), "num"), _usd(k.cost_usd.sum()),
                         _usd(done.pnl_usd.sum(), signed=True) if len(done) else "", str(len(k) - len(done))])
        if rows:
            lines += _md_table(["Kind", "Fills", "Contracts", "Cost", "P&L (settled)", "Pending"], rows) + [""]

    lines += ["## Reviewed scenarios", ""]
    sc = _scenarios(storage, slate)
    if sc.empty:
        lines += ["Every team ran full_strength.", ""]
    else:
        rows = [[r.team, r.game, r.scenario, _et(r.first_logged, "%Y-%m-%d %H:%M"), str(r.players), r.in_force_at_tip]
                for r in sc.itertuples()]
        lines += _md_table(["Team", "Game", "Scenario", "First logged", "Players", "In force at tip"], rows) + [""]

    lines += ["## Pending", ""]
    pend = res[res.outcome == "pending"] if len(res) else res
    pf = fills[(fills.status == "current") & fills.pnl_usd.isna()] if len(fills) else fills
    if pend.empty and pf.empty:
        lines += ["Nothing pending: every ticket and fill is settled.", ""]
    else:
        for r in pend.itertuples():
            lines.append(f"- Ticket {r.signal_id}: {r.player} {r.contract} ({VENUE_LABELS.get(r.venue, r.venue)} "
                         f"{r.ticker}) unsettled; run `cli grade --date {d}` after the venue settles")
        for r in pf.itertuples():
            lines.append(f"- Fill {r.fill_id}: {r.player or r.ticker} {r.contract or r.side} unsettled")
        lines.append("")
    return "\n".join(lines)


def _fill_outcome(r) -> str:
    if r.status != "current":
        return "superseded"
    if _missing(r.settlement_value):
        return "pending"
    if r.result == "scalar":
        return "fair price"
    value = r.settlement_value if r.side == "YES" else 1 - r.settlement_value
    return "won" if value >= 1 - 1e-9 else "lost"


# --- writing --------------------------------------------------------------------------------

def _write(path: Path, text: str) -> bool:
    """Write only on a change, so an unchanged rebuild touches nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return False
    path.write_text(text)
    return True


def write_journal(storage: Storage, out_dir: Path | str | None = None, dates: list[date] | None = None) -> dict:
    """Rebuild ledger.csv and fills.csv in full, and the day folders for `dates` (default: every
    date with a venue decision or a fill). Returns what was written."""
    out = Path(out_dir) if out_dir is not None else config.BETS_DIR
    j = build(storage)
    all_dates = journal_dates(storage, j.fills)
    dates = all_dates if dates is None else list(dates)
    written: list[Path] = []
    files = {out / "ledger.csv": _csv(j.tickets, LEDGER_COLUMNS),
             out / "fills.csv": _csv(j.fills, FILLS_COLUMNS)}
    days, skipped = [], []
    for d in dates:
        if d not in all_dates:
            skipped.append(d)
            continue
        day = out / "days" / d.isoformat()
        files[day / "tickets.csv"] = _csv(day_tickets(j, d), TICKETS_COLUMNS)
        files[day / "results.csv"] = _csv(day_results(j, d), RESULTS_COLUMNS)
        files[day / "summary.md"] = day_summary(storage, j, d)
        days.append(d)
    for path, text in files.items():
        if _write(path, text):
            written.append(path)
    pending = int((j.tickets.outcome == "pending").sum()) if len(j.tickets) else 0
    return {"out": out, "days": days, "skipped": skipped, "written": written, "tickets": len(j.tickets),
            "pending": pending, "fills": len(j.fills)}
