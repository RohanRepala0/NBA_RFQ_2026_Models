# 2026-10-20 (Tue)

Paper record at the suggested sizes: one ticket per player-game and stat, the first time it was actionable, at the logged all-in cost. Real money only where a fill is logged. Times are ET. Rebuilt by `python -m cold_start_usage.cli journal` (see `bets/README.md`). Research only.

## Slate

| Game | Tip | Status | Tickets | Actionable rows |
|---|---|---|---|---|
| BOS @ DET | 15:00 |  | 1 | 2 |
| PHI @ NYK | 19:00 |  | 3 | 9 |
| OKC @ SAS | 21:30 |  | 3 | 5 |

## Tickets

| Tip | Game | Player | Contract | Venue | Checkpoint | Entry | All-in | Size | Stake | Fair | Close | CLV | Result | P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15:00 | BOS @ DET | John Collins | 10+ YES | Kalshi | t-60m | 60c | 61.7c | 40 | $24.68 | 70.3c | 69.5c | +9.5c | lost | -$24.68 |
| 19:00 | PHI @ NYK | Jaylen Brown | 8+ REB YES | Kalshi | t-2h | 26c | 27.4c | 91 | $24.89 | 32.1c | 26.5c | +0.5c | won | +$66.11 |
| 19:00 | PHI @ NYK | Tyrese Maxey | 6+ REB YES | Kalshi | t-2h | 12c | 13.7c | 59 | $8.06 | 18.3c | 13c | +1c | lost | -$8.06 |
| 19:00 | PHI @ NYK | LeBron James | 10+ AST NO | PM US | t-15m | 72c | 73.4c | 34 | $24.96 | 77.7c | 71.5c | -0.5c | won | +$9.04 |
| 21:30 | OKC @ SAS | Cason Wallace | 15+ NO | Kalshi | t-6h | 81c | 82.1c | 10 | $8.21 | 86.4c | 81.5c | +0.5c | won | +$1.79 |
| 21:30 | OKC @ SAS | De'Aaron Fox | 8+ AST YES | Kalshi | t-6h | 14c | 14.8c | 168 | $24.94 | 18.9c | 15.5c | +1.5c | lost | -$24.94 |
| 21:30 | OKC @ SAS | Isaiah Hartenstein | 4+ AST YES | Kalshi | t-15m | 24c | 26.3c | 95 | $24.99 | 31.2c | 22.5c | -1.5c | lost | -$24.99 |

Entry is the ask when first actionable; all-in adds the venue fee. Fair is p_blend. Close is the venue's last two-sided mid before tip; CLV = close - entry. 16 actionable rows logged across checkpoints: 7 tickets, 9 repeats of a contract already actionable, 0 on a different contract for a player-stat already ticketed (`tickets.csv`).

## Totals (paper, at suggested sizes)

- Tickets: 7 (7 settled, 0 pending)
- Staked: $140.73 ($140.73 settled)
- P&L: -$5.73 on the settled stake, yield -4.1%
- Hits: 3 of 7 settled vs 3.35 expected (sum of p_blend; a fair-price settlement counts its fraction)
- Average CLV: +1.6c over 7 tickets with a close

### By stat

| Stat | Tickets | With close | Avg CLV | Settled stake | P&L |
|---|---|---|---|---|---|
| assists | 3 | 3 | -0.2c | $74.89 | -$40.89 |
| points | 2 | 2 | +5c | $32.89 | -$22.89 |
| rebounds | 2 | 2 | +0.8c | $32.95 | +$58.05 |

## Fills

None logged.

## Reviewed scenarios

| Team | Game | Scenario | First logged | Players | In force at tip |
|---|---|---|---|---|---|
| PHI | PHI @ NYK | barlow_out | 2026-10-20 11:56 | 6 | yes |
| SAS | OKC @ SAS | harris_out | 2026-10-20 11:56 | 9 | yes |

## Pending

Nothing pending: every ticket and fill is settled.
