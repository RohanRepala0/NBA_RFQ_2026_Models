# 2026-10-31 (Sat)

Paper record at the suggested sizes: one ticket per player-game and stat, the first time it was actionable, at the logged all-in cost. Real money only where a fill is logged. Times are ET. Rebuilt by `python -m cold_start_usage.cli journal` (see `bets/README.md`). Research only.

## Slate

| Game | Tip | Status | Tickets | Actionable rows |
|---|---|---|---|---|
| POR @ UTA | 15:00 |  | 1 | 1 |
| PHI @ CHA | 18:00 |  | 5 | 5 |
| ATL @ NOP | 19:00 |  | 2 | 4 |
| CLE @ MIL | 20:00 |  | 0 | 0 |
| MIN @ SAS | 20:00 |  | 1 | 2 |
| SAC @ MEM | 20:00 |  | 0 | 0 |
| OKC @ HOU | 20:30 |  | 2 | 2 |

## Tickets

| Tip | Game | Player | Contract | Venue | Checkpoint | Entry | All-in | Size | Stake | Fair | Close | CLV | Result | P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15:00 | POR @ UTA | Jrue Holiday | 6+ AST YES | PM US | t-60m | 34c | 36.6c | 22 | $8.05 | 40.8c | 34.5c | +0.5c | lost | -$8.05 |
| 18:00 | PHI @ CHA | Brandon Miller | 2+ AST YES | PM US | t-6h | 75c | 76.3c | 12 | $9.16 | 81.4c | 74.5c | -0.5c | won | +$2.84 |
| 18:00 | PHI @ CHA | Dennis Schroder | 4+ AST YES | PM US | t-6h | 78c | 79.2c | 12 | $9.50 | 83.5c | 77.5c | -0.5c | won | +$2.50 |
| 18:00 | PHI @ CHA | Dennis Schroder | 10+ YES | PM US | t-6h | 74c | 75.3c | 12 | $9.04 | 79.6c | 73.5c | -0.5c | lost | -$9.04 |
| 18:00 | PHI @ CHA | Anfernee Simons | 4+ AST YES | PM US | t-60m | 20c | 21.1c | 106 | $22.38 | 25.2c | 19.5c | -0.5c | lost | -$22.38 |
| 18:00 | PHI @ CHA | Grayson Allen | 4+ AST YES | PM US | t-60m | 30c | 35.6c | 70 | $24.89 | 39.7c | 29.5c | -0.5c | lost | -$24.89 |
| 19:00 | ATL @ NOP | Kingston Flemings | 5+ YES | PM US | t-2h | 65c | 66.6c | 12 | $7.99 | 72c | 64.5c | -0.5c | won | +$4.01 |
| 19:00 | ATL @ NOP | Trey Murphy III | 15+ YES | Kalshi | t-2h | 59c | 60.7c | 36 | $21.85 | 65c | 64.5c | +5.5c | won | +$14.15 |
| 20:00 | MIN @ SAS | Keldon Johnson | 10+ YES | Kalshi | t-2h | 52c | 53.8c | 20 | $10.75 | 58.9c | 50.5c | -1.5c | lost | -$10.75 |
| 20:30 | OKC @ HOU | Kevin Durant | 6+ AST YES | Kalshi | t-6h | 13c | 13.8c | 131 | $18.07 | 18c | 11.5c | -1.5c | lost | -$18.07 |
| 20:30 | OKC @ HOU | Marcus Smart | 2+ AST YES | PM US | t-6h | 80c | 81.1c | 10 | $8.11 | 85.5c | 78.5c | -1.5c | won | +$1.89 |

Entry is the ask when first actionable; all-in adds the venue fee. Fair is p_blend. Close is the venue's last two-sided mid before tip; CLV = close - entry. 14 actionable rows logged across checkpoints: 11 tickets, 2 repeats of a contract already actionable, 1 on a different contract for a player-stat already ticketed (`tickets.csv`).

## Totals (paper, at suggested sizes)

- Tickets: 11 (11 settled, 0 pending)
- Staked: $149.79 ($149.79 settled)
- P&L: -$67.79 on the settled stake, yield -45.3%
- Hits: 5 of 11 settled vs 6.49 expected (sum of p_blend; a fair-price settlement counts its fraction)
- Average CLV: -0.1c over 11 tickets with a close

### By stat

| Stat | Tickets | With close | Avg CLV | Settled stake | P&L |
|---|---|---|---|---|---|
| assists | 7 | 7 | -0.6c | $100.16 | -$66.16 |
| points | 4 | 4 | +0.8c | $49.63 | -$1.63 |

## Fills

None logged.

## Reviewed scenarios

| Team | Game | Scenario | First logged | Players | In force at tip |
|---|---|---|---|---|---|
| ATL | ATL @ NOP | full_strength_roster | 2026-10-31 11:33 | 9 | no |
| CHA | PHI @ CHA | report_1030 | 2026-10-31 11:33 | 9 | no |
| CLE | CLE @ MIL | full_strength_roster | 2026-10-31 11:33 | 9 | no |
| HOU | OKC @ HOU | report_1030 | 2026-10-31 11:33 | 8 | no |
| MEM | SAC @ MEM | full_strength_roster | 2026-10-31 11:33 | 9 | no |
| MIL | CLE @ MIL | full_strength_roster | 2026-10-31 11:33 | 9 | no |
| MIN | MIN @ SAS | report_1030 | 2026-10-31 11:33 | 10 | no |
| NOP | ATL @ NOP | report_1029_b | 2026-10-31 11:33 | 9 | no |
| OKC | OKC @ HOU | report_1026 | 2026-10-31 11:33 | 8 | no |
| PHI | PHI @ CHA | brown_out_1030 | 2026-10-31 11:33 | 5 | no |
| POR | POR @ UTA | report_1027 | 2026-10-31 11:33 | 9 | no |
| SAC | SAC @ MEM | report_1027 | 2026-10-31 11:33 | 8 | no |
| SAS | MIN @ SAS | report_1027 | 2026-10-31 11:33 | 9 | no |
| UTA | POR @ UTA | report_1026 | 2026-10-31 11:33 | 8 | no |
| ATL | ATL @ NOP | report_1031 | 2026-10-31 11:35 | 10 | yes |
| CHA | PHI @ CHA | report_1031 | 2026-10-31 11:35 | 10 | yes |
| CLE | CLE @ MIL | report_1031 | 2026-10-31 11:35 | 9 | yes |
| HOU | OKC @ HOU | report_1031 | 2026-10-31 11:35 | 9 | no |
| MEM | SAC @ MEM | report_1031 | 2026-10-31 11:35 | 10 | no |
| MIL | CLE @ MIL | report_1031 | 2026-10-31 11:35 | 10 | yes |
| MIN | MIN @ SAS | report_1031 | 2026-10-31 11:35 | 10 | no |
| NOP | ATL @ NOP | report_1031 | 2026-10-31 11:35 | 10 | no |
| OKC | OKC @ HOU | report_1031 | 2026-10-31 11:35 | 10 | yes |
| PHI | PHI @ CHA | report_1031 | 2026-10-31 11:35 | 5 | no |
| POR | POR @ UTA | report_1031 | 2026-10-31 11:35 | 10 | no |
| SAC | SAC @ MEM | report_1031 | 2026-10-31 11:35 | 9 | yes |
| SAS | MIN @ SAS | report_1031 | 2026-10-31 11:35 | 10 | yes |
| UTA | POR @ UTA | report_1031 | 2026-10-31 11:35 | 10 | no |
| HOU | OKC @ HOU | report_1031_b | 2026-10-31 14:04 | 9 | yes |
| PHI | PHI @ CHA | report_1031_b | 2026-10-31 14:04 | 7 | no |
| POR | POR @ UTA | report_1031_b | 2026-10-31 14:47 | 10 | yes |
| UTA | POR @ UTA | report_1031_b | 2026-10-31 14:47 | 10 | yes |
| NOP | ATL @ NOP | report_1031_b | 2026-10-31 17:47 | 10 | yes |
| PHI | PHI @ CHA | report_1031_c | 2026-10-31 17:47 | 8 | yes |
| MIN | MIN @ SAS | gobert_out_1031 | 2026-10-31 18:47 | 9 | yes |
| MEM | SAC @ MEM | jerome_out_1031 | 2026-10-31 19:32 | 9 | yes |

## Pending

Nothing pending: every ticket and fill is settled.
