# 2026-10-26 (Mon)

Paper record at the suggested sizes: one ticket per player-game and stat, the first time it was actionable, at the logged all-in cost. Real money only where a fill is logged. Times are ET. Rebuilt by `python -m cold_start_usage.cli journal` (see `bets/README.md`). Research only.

## Slate

| Game | Tip | Status | Tickets | Actionable rows |
|---|---|---|---|---|
| MIN @ CLE | 19:00 |  | 1 | 2 |
| WAS @ CHA | 19:00 |  | 0 | 0 |
| CHI @ BOS | 19:30 |  | 1 | 2 |
| DAL @ MIA | 19:30 |  | 1 | 1 |
| IND @ MIL | 20:00 |  | 4 | 10 |
| PHX @ OKC | 20:00 |  | 1 | 1 |
| ATL @ HOU | 20:30 |  | 0 | 0 |
| MEM @ UTA | 21:00 |  | 2 | 6 |
| GSW @ DEN | 22:00 |  | 0 | 0 |

## Tickets

| Tip | Game | Player | Contract | Venue | Checkpoint | Entry | All-in | Size | Stake | Fair | Close | CLV | Result | P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 19:00 | MIN @ CLE | Peyton Watson | 10+ YES | Kalshi | t-60m | 65c | 66.6c | 30 | $19.98 | 71.6c | 64.5c | -0.5c | won | +$10.02 |
| 19:30 | CHI @ BOS | Tre Jones | 4+ AST YES | PM US | t-2h | 58c | 59.7c | 41 | $24.47 | 67.6c | 57.5c | -0.5c | lost | -$24.47 |
| 19:30 | DAL @ MIA | Max Christie | 4+ AST YES | Kalshi | t-2h | 21c | 22.2c | 26 | $5.77 | 26.4c | 19.5c | -1.5c | lost | -$5.77 |
| 20:00 | IND @ MIL | Aaron Nesmith | 6+ REB YES | PM US | t-2h | 20c | 21.1c | 118 | $24.91 | 27.3c | 13.5c | -6.5c | lost | -$24.91 |
| 20:00 | IND @ MIL | Jaime Jaquez Jr. | 4+ AST YES | Kalshi | t-2h | 55c | 56.8c | 44 | $24.97 | 63.1c | 55.5c | +0.5c | lost | -$24.97 |
| 20:00 | IND @ MIL | Aaron Nesmith | 10+ YES | Kalshi | t-60m | 61c | 62.7c | 25 | $15.67 | 69.3c | 61.5c | +0.5c | won | +$9.33 |
| 20:00 | IND @ MIL | Pascal Siakam | 6+ AST YES | Kalshi | t-60m | 16c | 17c | 6 | $1.02 | 22.4c | 17.5c | +1.5c | won | +$4.98 |
| 20:00 | PHX @ OKC | Jaylin Williams | 10+ YES | PM US | adhoc | 45c | 47.7c | 34 | $16.22 | 53c | 31.5c | -13.5c | lost | -$16.22 |
| 21:00 | MEM @ UTA | Ace Bailey | 10+ YES | Kalshi | t-6h | 60c | 61.7c | 40 | $24.68 | 70.7c | 62c | +2c | won | +$15.32 |
| 21:00 | MEM @ UTA | Isaiah Collier | 4+ AST YES | Kalshi | t-6h | 65c | 66.6c | 37 | $24.64 | 71c | 62c | -3c | won | +$12.36 |

Entry is the ask when first actionable; all-in adds the venue fee. Fair is p_blend. Close is the venue's last two-sided mid before tip; CLV = close - entry. 22 actionable rows logged across checkpoints: 10 tickets, 8 repeats of a contract already actionable, 4 on a different contract for a player-stat already ticketed (`tickets.csv`).

## Totals (paper, at suggested sizes)

- Tickets: 10 (10 settled, 0 pending)
- Staked: $182.33 ($182.33 settled)
- P&L: -$44.33 on the settled stake, yield -24.3%
- Hits: 5 of 10 settled vs 5.42 expected (sum of p_blend; a fair-price settlement counts its fraction)
- Average CLV: -2.1c over 10 tickets with a close

### By stat

| Stat | Tickets | With close | Avg CLV | Settled stake | P&L |
|---|---|---|---|---|---|
| assists | 5 | 5 | -0.6c | $80.87 | -$37.87 |
| points | 4 | 4 | -2.9c | $76.55 | +$18.45 |
| rebounds | 1 | 1 | -6.5c | $24.91 | -$24.91 |

## Fills

None logged.

## Reviewed scenarios

| Team | Game | Scenario | First logged | Players | In force at tip |
|---|---|---|---|---|---|
| ATL | ATL @ HOU | full_strength_roster | 2026-10-26 17:08 | 9 | yes |
| CLE | MIN @ CLE | full_strength_roster | 2026-10-26 17:08 | 9 | yes |
| DAL | DAL @ MIA | full_strength_roster | 2026-10-26 17:08 | 9 | no |
| DEN | GSW @ DEN | full_strength_roster | 2026-10-26 17:08 | 9 | no |
| HOU | ATL @ HOU | full_strength_roster | 2026-10-26 17:08 | 9 | no |
| MEM | MEM @ UTA | full_strength_roster | 2026-10-26 17:08 | 9 | yes |
| MIL | IND @ MIL | full_strength_roster | 2026-10-26 17:08 | 9 | yes |
| UTA | MEM @ UTA | full_strength_roster | 2026-10-26 17:08 | 9 | no |
| WAS | WAS @ CHA | full_strength_roster | 2026-10-26 17:08 | 9 | yes |
| CHA | WAS @ CHA | report_1026 | 2026-10-26 17:10 | 9 | yes |
| CHI | CHI @ BOS | report_1026 | 2026-10-26 17:10 | 9 | no |
| DAL | DAL @ MIA | report_1026 | 2026-10-26 17:10 | 8 | yes |
| DEN | GSW @ DEN | report_1026 | 2026-10-26 17:10 | 9 | yes |
| GSW | GSW @ DEN | report_1026 | 2026-10-26 17:10 | 7 | yes |
| HOU | ATL @ HOU | report_1026 | 2026-10-26 17:10 | 9 | yes |
| IND | IND @ MIL | report_1026 | 2026-10-26 17:10 | 9 | no |
| MIN | MIN @ CLE | report_1026 | 2026-10-26 17:10 | 9 | yes |
| OKC | PHX @ OKC | report_1026 | 2026-10-26 17:10 | 8 | yes |
| PHX | PHX @ OKC | report_1026 | 2026-10-26 17:10 | 9 | yes |
| UTA | MEM @ UTA | report_1026 | 2026-10-26 17:10 | 8 | yes |
| CHI | CHI @ BOS | report_1026_b | 2026-10-26 18:02 | 9 | yes |
| IND | IND @ MIL | report_1026_b | 2026-10-26 19:19 | 9 | yes |

## Pending

Nothing pending: every ticket and fill is settled.
