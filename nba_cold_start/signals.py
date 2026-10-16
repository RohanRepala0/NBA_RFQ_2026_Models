"""Edge calculation and abstain logic.

edge = model P(side at the consensus line) - consensus no-vig P(side). The side
is whichever of over/under the model favours relative to the market, so the
logged edge is never negative. `paper` needs EDGE_THRESHOLD <= edge <=
MAX_CREDIBLE_EDGE and a consensus that did not abstain; everything else is
logged as `abstain` with the reason. An edge that large against a multi-book
consensus is far more often a model or input error than a mispriced market.
Losing and abstained rows stay in the data (and are still graded).
"""
from __future__ import annotations

import math

from . import config
from .config import MODEL, ModelParams
from .consensus import Consensus
from .odds_math import p_over_normal


def _pp(x: float) -> str:
    return f"{100 * x:.1f}pp"


def make_signal(projection: dict | None, consensus: Consensus | None, *,
                threshold: float = config.EDGE_THRESHOLD,
                max_edge: float | None = config.MAX_CREDIBLE_EDGE,
                params: ModelParams = MODEL) -> dict:
    mean = None if projection is None else projection.get("mean")
    if mean is not None and (isinstance(mean, float) and math.isnan(mean)):
        mean = None
    row = {
        "side": None, "model_p": None, "consensus_p": None, "line": None, "edge": None,
        "model_mean": mean,
        "consensus_mean": None if consensus is None else consensus.mean,
        "n_books": 0 if consensus is None else consensus.n_books,
        "books": None if consensus is None else (consensus.book_list() or None),
        "snapshot_ts": None if consensus is None else consensus.snapshot_ts,
        "decision": "abstain",
    }
    if consensus is None or consensus.mean is None:
        reason = "no market: no priced reference quotes" if consensus is None else consensus.abstain_reason
        return {**row, "reason": reason or "no market"}
    if mean is None:
        return {**row, "line": consensus.line,
                "reason": "no projection (placeholder stats or not in the active scenario)"}

    sd = projection.get("sd")
    p_model_over = p_over_normal(mean, consensus.line, sd=sd, params=params)
    p_cons_over = consensus.p_over
    edge_over = p_model_over - p_cons_over
    if edge_over >= 0:
        side, model_p, cons_p, edge = "over", p_model_over, p_cons_over, edge_over
    else:
        side, model_p, cons_p, edge = "under", 1 - p_model_over, 1 - p_cons_over, -edge_over
    row.update(side=side, model_p=model_p, consensus_p=cons_p, line=consensus.line, edge=edge)

    if consensus.abstain_reason:
        return {**row, "reason": consensus.abstain_reason}
    if edge < threshold:
        return {**row, "reason": f"edge {_pp(edge)} < {_pp(threshold)} threshold"}
    if max_edge is not None and edge > max_edge:
        return {**row, "reason": f"edge {_pp(edge)} > {_pp(max_edge)} sanity cap: check inputs"}
    return {**row, "decision": "paper", "reason": f"edge {_pp(edge)} >= {_pp(threshold)} threshold"}
