# 2026-10-27 (Tue)

Paper record at the suggested sizes: one ticket per player-game and stat, the first time it was actionable, at the logged all-in cost. Real money only where a fill is logged. Times are ET. Rebuilt by `python -m cold_start_usage.cli journal` (see `bets/README.md`). Research only.

## Slate

| Game | Tip | Status | Tickets | Actionable rows |
|---|---|---|---|---|
| BKN @ BOS | 19:30 |  | 4 | 9 |
| DET @ NYK | 20:00 |  | 3 | 9 |
| SAC @ SAS | 20:00 |  | 1 | 4 |
| POR @ LAL | 23:00 |  | 1 | 1 |

## Tickets

| Tip | Game | Player | Contract | Venue | Checkpoint | Entry | All-in | Size | Stake | Fair | Close | CLV | Result | P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 19:30 | BKN @ BOS | Derrick White | 10+ YES | Kalshi | t-60m | 76c | 77.3c | 32 | $24.73 | 82.9c | 75c | -1c | won | +$7.27 |
| 19:30 | BKN @ BOS | Neemias Queta | 4+ REB YES | PM US | t-60m | 75c | 76.3c | 10 | $7.63 | 84.7c | 75c | 0c | lost | -$7.63 |
| 19:30 | BKN @ BOS | Paul George | 15+ YES | PM US | t-60m | 65c | 66.6c | 37 | $24.64 | 70.9c | 63c | -2c | won | +$12.36 |
| 19:30 | BKN @ BOS | Payton Pritchard | 15+ YES | PM US | t-60m | 56c | 57.7c | 31 | $17.89 | 61.9c | 57.5c | +1.5c | lost | -$17.89 |
| 20:00 | DET @ NYK | Josh Hart | 4+ AST YES | PM US | t-2h | 55c | 56.8c | 12 | $6.81 | 61.2c | 54.5c | -0.5c | won | +$5.19 |
| 20:00 | DET @ NYK | Josh Hart | 10+ YES | Kalshi | t-2h | 59c | 60.7c | 29 | $17.61 | 64.8c | 58c | -1c | lost | -$17.61 |
| 20:00 | SAC @ SAS | Keldon Johnson | 15+ NO | Kalshi | t-2h | 71c | 73.4c | 34 | $24.96 | 77.9c | 72.5c | +1.5c | won | +$9.04 |
| 20:00 | DET @ NYK | John Collins | 10+ YES | PM US | t-15m | 78c | 79c | 1 | $0.79 | 83.8c | 77.5c | -0.5c | lost | -$0.79 |
| 23:00 | POR @ LAL | Jrue Holiday | 15+ NO | PM US | t-6h | 69c | 70.5c | 35 | $24.67 | 79.4c | 74.5c | +5.5c | lost | -$24.67 |

Entry is the ask when first actionable; all-in adds the venue fee. Fair is p_blend. Close is the venue's last two-sided mid before tip; CLV = close - entry. 23 actionable rows logged across checkpoints: 9 tickets, 12 repeats of a contract already actionable, 2 on a different contract for a player-stat already ticketed (`tickets.csv`).

## Totals (paper, at suggested sizes)

- Tickets: 9 (9 settled, 0 pending)
- Staked: $149.73 ($149.73 settled)
- P&L: -$34.73 on the settled stake, yield -23.2%
- Hits: 4 of 9 settled vs 6.67 expected (sum of p_blend; a fair-price settlement counts its fraction)
- Average CLV: +0.4c over 9 tickets with a close

### By stat

| Stat | Tickets | With close | Avg CLV | Settled stake | P&L |
|---|---|---|---|---|---|
| assists | 1 | 1 | -0.5c | $6.81 | +$5.19 |
| points | 7 | 7 | +0.6c | $135.29 | -$32.29 |
| rebounds | 1 | 1 | 0c | $7.63 | -$7.63 |

## Fills

None logged.

## Reviewed scenarios

| Team | Game | Scenario | First logged | Players | In force at tip |
|---|---|---|---|---|---|
| NYK | DET @ NYK | full_strength_roster | 2026-10-27 15:47 | 9 | no |
| POR | POR @ LAL | full_strength_roster | 2026-10-27 15:47 | 9 | no |
| SAC | SAC @ SAS | full_strength_roster | 2026-10-27 15:47 | 9 | no |
| BKN | BKN @ BOS | report_1027 | 2026-10-27 15:48 | 8 | yes |
| DET | DET @ NYK | duren_out | 2026-10-27 15:48 | 10 | no |
| NYK | DET @ NYK | report_1027 | 2026-10-27 15:48 | 9 | yes |
| POR | POR @ LAL | report_1027 | 2026-10-27 15:48 | 9 | yes |
| SAC | SAC @ SAS | report_1027 | 2026-10-27 15:48 | 8 | yes |
| SAS | SAC @ SAS | report_1027 | 2026-10-27 15:48 | 9 | yes |
| DET | DET @ NYK | duren_out_b | 2026-10-27 19:18 | 9 | yes |

## Pending

Nothing pending: every ticket and fill is settled.
