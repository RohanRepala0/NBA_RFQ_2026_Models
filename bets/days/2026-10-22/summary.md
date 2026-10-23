# 2026-10-22 (Thu)

Paper record at the suggested sizes: one ticket per player-game and stat, the first time it was actionable, at the logged all-in cost. Real money only where a fill is logged. Times are ET. Rebuilt by `python -m cold_start_usage.cli journal` (see `bets/README.md`). Research only.

## Slate

| Game | Tip | Status | Tickets | Actionable rows |
|---|---|---|---|---|
| CLE @ PHI | 19:00 |  | 2 | 2 |
| DEN @ OKC | 21:30 |  | 2 | 2 |

## Tickets

| Tip | Game | Player | Contract | Venue | Checkpoint | Entry | All-in | Size | Stake | Fair | Close | CLV | Result | P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 19:00 | CLE @ PHI | Anfernee Simons | 15+ NO | Kalshi | t-15m | 79c | 80.2c | 31 | $24.86 | 87c | 78.5c | -0.5c | won | +$6.14 |
| 19:00 | CLE @ PHI | Jaylen Brown | 10+ REB YES | Kalshi | t-15m | 10c | 10.6c | 117 | $12.44 | 15.7c | 9c | -1c | lost | -$12.44 |
| 21:30 | DEN @ OKC | Jamal Murray | 6+ AST YES | Kalshi | t-60m | 50c | 51.7c | 48 | $24.84 | 56.1c | 49.5c | -0.5c | lost | -$24.84 |
| 21:30 | DEN @ OKC | Jared McCain | 15+ NO | Kalshi | t-60m | 76c | 77.3c | 12 | $9.28 | 82.3c | 75.5c | -0.5c | won | +$2.72 |

Entry is the ask when first actionable; all-in adds the venue fee. Fair is p_blend. Close is the venue's last two-sided mid before tip; CLV = close - entry. 4 actionable rows logged across checkpoints: 4 tickets, 0 repeats of a contract already actionable, 0 on a different contract for a player-stat already ticketed (`tickets.csv`).

## Totals (paper, at suggested sizes)

- Tickets: 4 (4 settled, 0 pending)
- Staked: $71.42 ($71.42 settled)
- P&L: -$28.42 on the settled stake, yield -39.8%
- Hits: 2 of 4 settled vs 2.41 expected (sum of p_blend; a fair-price settlement counts its fraction)
- Average CLV: -0.6c over 4 tickets with a close

### By stat

| Stat | Tickets | With close | Avg CLV | Settled stake | P&L |
|---|---|---|---|---|---|
| assists | 1 | 1 | -0.5c | $24.84 | -$24.84 |
| points | 2 | 2 | -0.5c | $34.14 | +$8.86 |
| rebounds | 1 | 1 | -1c | $12.44 | -$12.44 |

## Fills

None logged.

## Reviewed scenarios

| Team | Game | Scenario | First logged | Players | In force at tip |
|---|---|---|---|---|---|
| PHI | CLE @ PHI | barlow_out | 2026-10-22 16:30 | 7 | yes |

## Pending

Nothing pending: every ticket and fill is settled.
