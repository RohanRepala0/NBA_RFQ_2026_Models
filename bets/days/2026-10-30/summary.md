# 2026-10-30 (Fri)

Paper record at the suggested sizes: one ticket per player-game and stat, the first time it was actionable, at the logged all-in cost. Real money only where a fill is logged. Times are ET. Rebuilt by `python -m cold_start_usage.cli journal` (see `bets/README.md`). Research only.

## Slate

| Game | Tip | Status | Tickets | Actionable rows |
|---|---|---|---|---|
| CHA @ WAS | 19:00 |  | 1 | 1 |
| CHI @ BOS | 19:30 |  | 0 | 0 |
| DET @ BKN | 19:30 |  | 0 | 0 |
| NYK @ PHI | 19:30 |  | 1 | 2 |
| ORL @ TOR | 19:30 |  | 0 | 0 |
| HOU @ DAL | 20:00 |  | 1 | 1 |
| IND @ MIA | 20:00 |  | 0 | 0 |
| LAC @ MIN | 20:00 |  | 0 | 0 |
| DEN @ PHX | 22:00 |  | 2 | 2 |
| LAL @ GSW | 22:00 |  | 1 | 1 |

## Tickets

| Tip | Game | Player | Contract | Venue | Checkpoint | Entry | All-in | Size | Stake | Fair | Close | CLV | Result | P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 19:00 | CHA @ WAS | Bilal Coulibaly | 10+ YES | Kalshi | t-15m | 32c | 34.4c | 72 | $24.78 | 40c | 31c | -1c | lost | -$24.78 |
| 19:30 | NYK @ PHI | Joel Embiid | 20+ YES | PM US | t-2h | 66c | 68.5c | 36 | $24.67 | 75.7c | 65.5c | -0.5c | lost | -$24.67 |
| 20:00 | HOU @ DAL | Tari Eason | 10+ YES | PM US | t-2h | 60c | 62.6c | 39 | $24.43 | 66.9c | 59.5c | -0.5c | won | +$14.57 |
| 22:00 | DEN @ PHX | Collin Gillespie | 2+ AST YES | PM US | t-15m | 78c | 79.2c | 22 | $17.42 | 83.6c | 77.5c | -0.5c | won | +$4.58 |
| 22:00 | DEN @ PHX | Jordan Goodwin | 4+ AST YES | PM US | t-15m | 11c | 11.7c | 21 | $2.45 | 16c | 10.5c | -0.5c | won | +$18.55 |
| 22:00 | LAL @ GSW | Sandro Mamukelashvili | 5+ YES | PM US | t-15m | 78c | 79.2c | 21 | $16.63 | 85.2c | 77.5c | -0.5c | lost | -$16.63 |

Entry is the ask when first actionable; all-in adds the venue fee. Fair is p_blend. Close is the venue's last two-sided mid before tip; CLV = close - entry. 7 actionable rows logged across checkpoints: 6 tickets, 1 repeats of a contract already actionable, 0 on a different contract for a player-stat already ticketed (`tickets.csv`).

## Totals (paper, at suggested sizes)

- Tickets: 6 (6 settled, 0 pending)
- Staked: $110.38 ($110.38 settled)
- P&L: -$28.38 on the settled stake, yield -25.7%
- Hits: 3 of 6 settled vs 3.67 expected (sum of p_blend; a fair-price settlement counts its fraction)
- Average CLV: -0.6c over 6 tickets with a close

### By stat

| Stat | Tickets | With close | Avg CLV | Settled stake | P&L |
|---|---|---|---|---|---|
| assists | 2 | 2 | -0.5c | $19.87 | +$23.13 |
| points | 4 | 4 | -0.6c | $90.51 | -$51.51 |

## Fills

None logged.

## Reviewed scenarios

| Team | Game | Scenario | First logged | Players | In force at tip |
|---|---|---|---|---|---|
| BKN | DET @ BKN | report_1027 | 2026-10-30 15:36 | 8 | no |
| CHA | CHA @ WAS | report_1026 | 2026-10-30 15:36 | 9 | no |
| CHI | CHI @ BOS | report_1026_b | 2026-10-30 15:36 | 9 | no |
| DAL | HOU @ DAL | report_1026 | 2026-10-30 15:36 | 8 | no |
| DEN | DEN @ PHX | report_1026 | 2026-10-30 15:36 | 9 | no |
| DET | DET @ BKN | duren_out_b | 2026-10-30 15:36 | 9 | no |
| GSW | LAL @ GSW | report_1026 | 2026-10-30 15:36 | 7 | no |
| HOU | HOU @ DAL | report_1026 | 2026-10-30 15:36 | 9 | no |
| IND | IND @ MIA | report_1026_b | 2026-10-30 15:36 | 9 | no |
| LAC | LAC @ MIN | report_1025 | 2026-10-30 15:36 | 8 | no |
| MIN | LAC @ MIN | report_1026_edwards_out | 2026-10-30 15:36 | 9 | no |
| NYK | NYK @ PHI | report_1027 | 2026-10-30 15:36 | 9 | no |
| ORL | ORL @ TOR | banchero_out | 2026-10-30 15:36 | 9 | no |
| PHI | NYK @ PHI | embiid_bigs_edgecombe_out | 2026-10-30 15:36 | 6 | no |
| PHX | DEN @ PHX | report_1026 | 2026-10-30 15:36 | 9 | no |
| TOR | ORL @ TOR | kawhi_out | 2026-10-30 15:36 | 9 | no |
| WAS | CHA @ WAS | full_strength_roster | 2026-10-30 15:36 | 9 | no |
| BKN | DET @ BKN | report_1030 | 2026-10-30 15:44 | 10 | no |
| BOS | CHI @ BOS | report_1030 | 2026-10-30 15:44 | 10 | yes |
| CHA | CHA @ WAS | report_1030 | 2026-10-30 15:44 | 9 | yes |
| CHI | CHI @ BOS | report_1030 | 2026-10-30 15:44 | 10 | no |
| DAL | HOU @ DAL | report_1030 | 2026-10-30 15:44 | 10 | no |
| DEN | DEN @ PHX | report_1030 | 2026-10-30 15:44 | 9 | yes |
| DET | DET @ BKN | report_1030 | 2026-10-30 15:44 | 10 | yes |
| GSW | LAL @ GSW | report_1030 | 2026-10-30 15:44 | 9 | no |
| HOU | HOU @ DAL | report_1030 | 2026-10-30 15:44 | 8 | yes |
| IND | IND @ MIA | report_1030 | 2026-10-30 15:44 | 10 | yes |
| LAC | LAC @ MIN | report_1030 | 2026-10-30 15:44 | 10 | no |
| LAL | LAL @ GSW | report_1030 | 2026-10-30 15:44 | 10 | yes |
| MIA | IND @ MIA | report_1030 | 2026-10-30 15:44 | 10 | no |
| MIN | LAC @ MIN | report_1030 | 2026-10-30 15:44 | 10 | yes |
| NYK | NYK @ PHI | report_1030 | 2026-10-30 15:44 | 10 | yes |
| ORL | ORL @ TOR | report_1030 | 2026-10-30 15:44 | 10 | yes |
| PHI | NYK @ PHI | report_1030 | 2026-10-30 15:44 | 8 | no |
| PHX | DEN @ PHX | report_1030 | 2026-10-30 15:44 | 10 | no |
| TOR | ORL @ TOR | report_1030 | 2026-10-30 15:44 | 10 | yes |
| WAS | CHA @ WAS | report_1030 | 2026-10-30 15:44 | 9 | no |
| BKN | DET @ BKN | report_1030_b | 2026-10-30 18:03 | 10 | yes |
| PHI | NYK @ PHI | brown_out_1030 | 2026-10-30 18:03 | 7 | yes |
| CHI | CHI @ BOS | report_1030_b | 2026-10-30 18:04 | 9 | yes |
| DAL | HOU @ DAL | report_1030_b | 2026-10-30 18:04 | 10 | yes |
| LAC | LAC @ MIN | report_1030_b | 2026-10-30 18:04 | 10 | yes |
| MIA | IND @ MIA | report_1030_b | 2026-10-30 18:04 | 10 | yes |
| WAS | CHA @ WAS | report_1030_b | 2026-10-30 18:32 | 10 | yes |
| GSW | LAL @ GSW | report_1030_b | 2026-10-30 21:02 | 10 | yes |
| PHX | DEN @ PHX | report_1030_b | 2026-10-30 21:02 | 10 | yes |

## Pending

Nothing pending: every ticket and fill is settled.
