"""Prop Desk export: a ticket's win is its own side's result."""
from __future__ import annotations

import pandas as pd

from cold_start_usage.dashboard import ledger_tickets


def test_a_no_ticket_wins_when_the_contract_settles_no(tmp_path):
    base = {"date_et": "2026-10-27", "game": "A @ B", "player": "P", "stat": "points", "venue": "kalshi",
            "checkpoint": "t-60m", "ask": 0.7, "suggested_contracts": 10, "suggested_stake_usd": 7.0,
            "p_blend": 0.78, "p_market": 0.78, "ev_blend": 0.05, "clv": 0.01}
    rows = [{**base, "signal_id": "no-won", "contract": "15+ NO", "result": "no", "outcome": "won",
             "settlement_value": 0.0, "pnl_suggested_usd": 3.0},
            {**base, "signal_id": "no-lost", "contract": "15+ NO", "result": "yes", "outcome": "lost",
             "settlement_value": 1.0, "pnl_suggested_usd": -7.0},
            {**base, "signal_id": "open", "contract": "10+ YES", "result": None, "outcome": "pending",
             "settlement_value": None, "pnl_suggested_usd": None}]
    path = tmp_path / "ledger.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    t = ledger_tickets(path).set_index("ticket_id")
    assert t.at["no-won", "won"] == 1.0 and t.at["no-lost", "won"] == 0.0
    assert t.at["open", "result"] == "pending" and pd.isna(t.at["open", "won"]) and pd.isna(t.at["open", "pnl"])
    assert t.at["no-won", "fair_pct"] == 78.0 and t.at["no-won", "entry_c"] == 70.0
