# 2026-10-29 (Thu)

Paper record at the suggested sizes: one ticket per player-game and stat, the first time it was actionable, at the logged all-in cost. Real money only where a fill is logged. Times are ET. Rebuilt by `python -m cold_start_usage.cli journal` (see `bets/README.md`). Research only.

## Slate

| Game | Tip | Status | Tickets | Actionable rows |
|---|---|---|---|---|
| CLE @ ATL | 20:00 |  | 1 | 1 |
| SAC @ NOP | 20:00 |  | 2 | 2 |
| MEM @ POR | 22:00 |  | 4 | 8 |

## Tickets

| Tip | Game | Player | Contract | Venue | Checkpoint | Entry | All-in | Size | Stake | Fair | Close | CLV | Result | P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20:00 | CLE @ ATL | Luguentz Dort | 10+ NO | Kalshi | t-15m | 67c | 68.6c | 36 | $24.68 | 73c | 66.5c | -0.5c | won | +$11.32 |
| 20:00 | SAC @ NOP | Bennedict Mathurin | 15+ NO | PM US | t-15m | 64c | 65.6c | 38 | $24.93 | 70.1c | 63.5c | -0.5c | won | +$13.07 |
| 20:00 | SAC @ NOP | Jeremiah Fears | 20+ NO | Kalshi | t-15m | 66c | 67.6c | 36 | $24.33 | 73.8c | 65.5c | -0.5c | lost | -$24.33 |
| 22:00 | MEM @ POR | Jrue Holiday | 6+ REB YES | PM US | t-6h | 19c | 20.1c | 11 | $2.21 | 26.3c | 18.5c | -0.5c | won | +$8.79 |
| 22:00 | MEM @ POR | Ty Jerome | 8+ AST YES | Kalshi | t-6h | 24c | 25.3c | 98 | $24.78 | 29.7c | 22.5c | -1.5c | lost | -$24.78 |
| 22:00 | MEM @ POR | Jerami Grant | 10+ YES | PM US | t-60m | 49c | 50.7c | 11 | $5.58 | 56.1c | 53.5c | +4.5c | lost | -$5.58 |
| 22:00 | MEM @ POR | Toumani Camara | 10+ YES | PM US | t-60m | 55c | 56.7c | 44 | $24.96 | 62.7c | 56c | +1c | won | +$19.04 |

Entry is the ask when first actionable; all-in adds the venue fee. Fair is p_blend. Close is the venue's last two-sided mid before tip; CLV = close - entry. 11 actionable rows logged across checkpoints: 7 tickets, 3 repeats of a contract already actionable, 1 on a different contract for a player-stat already ticketed (`tickets.csv`).

## Totals (paper, at suggested sizes)

- Tickets: 7 (7 settled, 0 pending)
- Staked: $131.47 ($131.47 settled)
- P&L: -$2.47 on the settled stake, yield -1.9%
- Hits: 4 of 7 settled vs 3.92 expected (sum of p_blend; a fair-price settlement counts its fraction)
- Average CLV: +0.3c over 7 tickets with a close

### By stat

| Stat | Tickets | With close | Avg CLV | Settled stake | P&L |
|---|---|---|---|---|---|
| assists | 1 | 1 | -1.5c | $24.78 | -$24.78 |
| points | 5 | 5 | +0.8c | $104.48 | +$13.52 |
| rebounds | 1 | 1 | -0.5c | $2.21 | +$8.79 |

## Fills

None logged.

## Reviewed scenarios

| Team | Game | Scenario | First logged | Players | In force at tip |
|---|---|---|---|---|---|
| ATL | CLE @ ATL | full_strength_roster | 2026-10-29 17:32 | 9 | yes |
| CLE | CLE @ ATL | full_strength_roster | 2026-10-29 17:32 | 9 | yes |
| MEM | MEM @ POR | full_strength_roster | 2026-10-29 17:32 | 9 | yes |
| NOP | SAC @ NOP | report_1029 | 2026-10-29 17:32 | 9 | no |
| POR | MEM @ POR | report_1027 | 2026-10-29 17:32 | 9 | yes |
| SAC | SAC @ NOP | report_1027 | 2026-10-29 17:32 | 8 | yes |
| CLE | CLE @ ATL | tyson_out | 2026-10-29 17:34 | 9 | no |
| NOP | SAC @ NOP | report_1029_b | 2026-10-29 19:02 | 9 | yes |

## Pending

Nothing pending: every ticket and fill is settled.
