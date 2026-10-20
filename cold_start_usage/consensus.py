"""Per-player, per-stat market consensus built only from allowlisted reference books.

1. Per book: pair the over and under at its main line and remove the vig
   (power by default; multiplicative stored alongside for comparison).
2. Books post different lines (24.5 vs 25.5), so compare implied means: back
   out the mean m with P(X > line) = p_over under the stat's distribution
   (distributions.py: points N(m, max(4, 0.30 m)); rebounds and assists a
   negative binomial with Var = phi * m).
3. Consensus mean = weighted median of implied means (Pinnacle 2x). P(over)
   for any line comes from the same distribution at that mean.
4. Abstain if fewer than MIN_PRICED_BOOKS books, or any quote used is stale.

Each stat is its own consensus: rows are filtered to one stat (a NULL stat, from
rows logged before rebounds and assists were stored, is points), so a rebounds
quote can never move a points consensus. Every caller gets points by default.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from . import config, distributions
from .config import MODEL, ModelParams, book_role
from .odds_math import american_to_prob, devig, overround
from .storage import Storage


@dataclass
class BookView:
    book: str
    line: float
    over_odds: float
    under_odds: float
    p_over: float              # no-vig, configured method
    p_over_mult: float         # no-vig, multiplicative (for comparison)
    implied_mean: float
    weight: float
    age_min: float | None


@dataclass
class Consensus:
    event_id: str
    player_id: str
    as_of: datetime
    snapshot_ts: datetime | None
    mean: float | None
    line: float | None
    p_over: float | None
    books: list[BookView] = field(default_factory=list)
    abstain_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    params: ModelParams = MODEL
    stat: str = "points"

    @property
    def n_books(self) -> int:
        return len(self.books)

    @property
    def sd(self) -> float | None:
        return distributions.sd(self.stat, self.mean, self.params) if self.mean is not None else None

    def p_over_at(self, line: float) -> float | None:
        if self.mean is None:
            return None
        return distributions.p_over(self.stat, self.mean, line, self.params)

    def book_list(self) -> str:
        return ",".join(b.book for b in self.books)


def weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    total = sum(w for _, w in pairs)
    cum = 0.0
    for i, (v, w) in enumerate(pairs):
        cum += w
        if abs(cum - total / 2) < 1e-12 and i + 1 < len(pairs):
            return (v + pairs[i + 1][0]) / 2
        if cum > total / 2:
            return v
    return pairs[-1][0]


def _age_min(as_of: datetime, quote_ts, snapshot_ts) -> float | None:
    if config.STALENESS_CLOCK == "fetch" or quote_ts is None or pd.isna(quote_ts):
        ref = snapshot_ts
    else:
        ref = quote_ts
    if ref is None or pd.isna(ref):
        return None
    return (pd.Timestamp(as_of) - pd.Timestamp(ref)).total_seconds() / 60


def build_consensus(rows: pd.DataFrame, as_of: datetime, *, event_id: str, player_id: str,
                    snapshot_ts: datetime | None = None, method: str = config.VIG_METHOD,
                    weights: dict[str, float] | None = None,
                    min_books: int = config.MIN_PRICED_BOOKS,
                    max_age_min: float = config.MAX_QUOTE_AGE_MIN,
                    params: ModelParams = MODEL, stat: str = "points") -> Consensus:
    """`rows`: one snapshot's odds_snapshots rows for one player. Rows of other stats are
    dropped here too (defense in depth: callers already pass one stat)."""
    weights = config.BOOK_WEIGHTS if weights is None else weights
    out = Consensus(event_id=event_id, player_id=player_id, as_of=as_of,
                    snapshot_ts=snapshot_ts, mean=None, line=None, p_over=None, params=params,
                    stat=distributions.check_stat(stat))
    rows = only_stat(rows, stat)
    usable = rows[rows.book.map(lambda b: book_role(b) == "reference")
                  & rows.available.fillna(False).astype(bool)
                  & rows.is_main_line.fillna(True).astype(bool)
                  & rows.line.notna() & rows.odds_american.notna()]
    for book, grp in usable.groupby("book", sort=True):
        over, under = grp[grp.side == "over"], grp[grp.side == "under"]
        if over.empty or under.empty:
            out.notes.append(f"{book}: one side only")
            continue
        o, u = over.iloc[-1], under.iloc[-1]
        if o.line != u.line:
            out.notes.append(f"{book}: over/under lines differ ({o.line} vs {u.line})")
            continue
        if o.odds_american == 100 and u.odds_american == 100:
            out.notes.append(f"{book}: placeholder +100/+100 price")
            continue
        q = [american_to_prob(o.odds_american), american_to_prob(u.odds_american)]
        lo, hi = config.OVERROUND_RANGE
        if not lo <= overround(q) <= hi:
            out.notes.append(f"{book}: implausible overround {overround(q):.3f}")
            continue
        p_over = devig(q, method)[0]
        p_mult = devig(q, "multiplicative")[0]
        ages = [_age_min(as_of, r.quote_ts, snapshot_ts) for r in (o, u)]
        ages = [a for a in ages if a is not None]
        out.books.append(BookView(
            book=book, line=float(o.line), over_odds=float(o.odds_american),
            under_odds=float(u.odds_american), p_over=p_over, p_over_mult=p_mult,
            implied_mean=distributions.implied_mean(stat, float(o.line), p_over, params),
            weight=float(weights.get(book, config.DEFAULT_BOOK_WEIGHT)),
            age_min=max(ages) if ages else None))

    if out.books:
        out.mean = weighted_median([b.implied_mean for b in out.books], [b.weight for b in out.books])
        line_weight = Counter()
        for b in out.books:
            line_weight[b.line] += b.weight
        top = max(line_weight.values())
        out.line = min((ln for ln, w in line_weight.items() if w == top), key=lambda ln: abs(ln - out.mean))
        out.p_over = out.p_over_at(out.line)

    if out.n_books < min_books:
        out.abstain_reason = f"only {out.n_books} priced reference book(s), need {min_books}"
    else:
        stale = [b for b in out.books if b.age_min is None or b.age_min > max_age_min]
        if stale:
            worst = max(stale, key=lambda b: b.age_min if b.age_min is not None else float("inf"))
            age = "unknown age" if worst.age_min is None else f"{worst.age_min:.0f} min old"
            out.abstain_reason = f"stale quote: {worst.book} {age} (> {max_age_min:g})"
    return out


def only_stat(rows: pd.DataFrame, stat: str) -> pd.DataFrame:
    """Rows of one stat. A missing or NULL stat (rows logged before rebounds and assists) is points."""
    if rows.empty or "stat" not in rows.columns:
        return rows if stat == "points" else rows.iloc[0:0]
    return rows[rows.stat.fillna("points") == stat]


# --- Storage helpers -------------------------------------------------------------
def latest_snapshot_rows(storage: Storage, event_id: str, *, before: datetime | None = None,
                         tag: str | None = None) -> tuple[datetime | None, pd.DataFrame]:
    """Rows of the most recent snapshot of an event (optionally before a time / with a tag)."""
    clauses, args = ["event_id = ?"], [event_id]
    if before is not None:
        clauses.append("ts <= ?")
        args.append(before)
    if tag is not None:
        clauses.append("snapshot_tag = ?")
        args.append(tag)
    where = " AND ".join(clauses)
    ts = storage.query(f"SELECT max(ts) AS ts FROM odds_snapshots WHERE {where}", args).ts.iloc[0]
    if ts is None or pd.isna(ts):
        return None, pd.DataFrame()
    rows = storage.query("SELECT * FROM odds_snapshots WHERE event_id = ? AND ts = ?", [event_id, ts])
    return pd.Timestamp(ts).to_pydatetime(), rows


def consensus_by_player(storage: Storage, event_id: str, as_of: datetime, *,
                        before: datetime | None = None, tag: str | None = None,
                        stat: str = "points") -> dict[str, Consensus]:
    """player_id -> consensus for one stat (points unless asked) from the event's latest snapshot."""
    snapshot_ts, rows = latest_snapshot_rows(storage, event_id, before=before, tag=tag)
    rows = only_stat(rows, distributions.check_stat(stat))
    if rows.empty:
        return {}
    return {pid: build_consensus(grp, as_of, event_id=event_id, player_id=pid, snapshot_ts=snapshot_ts, stat=stat)
            for pid, grp in rows.groupby("player_id")}


def sgo_target_quotes(storage: Storage, event_id: str, before: datetime | None = None,
                      stat: str = "points") -> pd.DataFrame:
    """Prediction-market quotes as SportsGameOdds carries them (role 'target'), if a plan ever
    returns any. Prices Rohan can act on come from the venues' own APIs (venues.py)."""
    _, rows = latest_snapshot_rows(storage, event_id, before=before)
    rows = only_stat(rows, stat)
    if rows.empty:
        return rows
    return rows[(rows.book_role == "target") & rows.available.fillna(False).astype(bool)
                & rows.odds_american.notna()]
