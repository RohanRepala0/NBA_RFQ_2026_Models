# 2026-10-21 (Wed)

Paper record at the suggested sizes: one ticket per player-game and stat, the first time it was actionable, at the logged all-in cost. Real money only where a fill is logged. Times are ET. Rebuilt by `python -m cold_start_usage.cli journal` (see `bets/README.md`). Research only.

## Slate

| Game | Tip | Status | Tickets | Actionable rows |
|---|---|---|---|---|
| ATL @ ORL | 19:00 |  | 0 | 0 |
| MIL @ WAS | 19:00 |  | 0 | 0 |
| CHA @ BKN | 19:30 |  | 0 | 0 |
| CHI @ TOR | 19:30 |  | 0 | 0 |
| MIN @ MIA | 19:30 |  | 0 | 0 |
| IND @ NOP | 20:00 |  | 0 | 0 |
| UTA @ MEM | 20:00 |  | 0 | 0 |
| DAL @ HOU | 20:30 |  | 0 | 0 |
| GSW @ LAL | 22:00 |  | 2 | 2 |
| PHX @ POR | 22:00 |  | 0 | 0 |
| SAC @ LAC | 22:30 |  | 0 | 0 |

## Tickets

| Tip | Game | Player | Contract | Venue | Checkpoint | Entry | All-in | Size | Stake | Fair | Close | CLV | Result | P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 22:00 | GSW @ LAL | Luka Dončić | 25+ NO | Kalshi | t-15m | 15c | 15.9c | 157 | $24.96 | 20.6c | 14.5c | -0.5c | lost | -$24.96 |
| 22:00 | GSW @ LAL | Walker Kessler | 8+ REB YES | Kalshi | t-15m | 78c | 79.2c | 31 | $24.56 | 83.5c | 77c | -1c | won | +$6.44 |

Entry is the ask when first actionable; all-in adds the venue fee. Fair is p_blend. Close is the venue's last two-sided mid before tip; CLV = close - entry. 2 actionable rows logged across checkpoints: 2 tickets, 0 repeats of a contract already actionable, 0 on a different contract for a player-stat already ticketed (`tickets.csv`).

## Totals (paper, at suggested sizes)

- Tickets: 2 (2 settled, 0 pending)
- Staked: $49.52 ($49.52 settled)
- P&L: -$18.52 on the settled stake, yield -37.4%
- Hits: 1 of 2 settled vs 1.04 expected (sum of p_blend; a fair-price settlement counts its fraction)
- Average CLV: -0.7c over 2 tickets with a close

### By stat

| Stat | Tickets | With close | Avg CLV | Settled stake | P&L |
|---|---|---|---|---|---|
| points | 1 | 1 | -0.5c | $24.96 | -$24.96 |
| rebounds | 1 | 1 | -1c | $24.56 | +$6.44 |

## Fills

None logged.

## Reviewed scenarios

Every team ran full_strength.

## Pending

Nothing pending: every ticket and fill is settled.
