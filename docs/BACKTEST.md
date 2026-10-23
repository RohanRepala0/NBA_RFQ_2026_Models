# Backtest: Kalshi NBA player points, 2025-26

Archive: 23,543 settled `KXNBAPTS` markets with candles across 1,096 games, 2025-11-18 to 2026-06-13 (`cli history`; `cli backtest --docs` rebuilds this page).

Every game is in. 19 of 23,562 markets have no candles (they never traded) and are left out.

**How it's scored.**
- Fills:
  - A taker order fills at the ask at the decision time, but only if that ask is at or under its limit.
  - A resting limit fills only if a later trade printed *through* it before tip.
- Fees: Kalshi's taker fee per 10-contract order, rounded up to the cent. Makers pay nothing on this series.
- Settlement: a player who never played settles at the exchange's fair price.
- CLV: the last pre-tip mid minus the price paid.
- Folds: walk-forward monthly folds; each fold's parameters come only from earlier dates, with a one-day embargo.
- **Holdout: 2026-04-01 on.** It was never used to choose anything and is reported once, separately.
- The 95% interval on yield resamples whole game dates, because bets on one slate move together.

## Liquidity by month (books an hour before tip)

| month | markets | two-sided | median spread | median volume |
|---|---|---|---|---|
| 2025-11 | 1,115 | 42% | 45c | 295 |
| 2025-12 | 2,877 | 74% | 6c | 251 |
| 2026-01 | 3,657 | 87% | 5c | 508 |
| 2026-02 | 3,232 | 79% | 4c | 1,226 |
| 2026-03 | 6,684 | 87% | 4c | 1,096 |
| 2026-04 | 4,220 | 91% | 3c | 2,127 |
| 2026-05 | 1,473 | 95% | 1c | 14,116 |
| 2026-06 | 285 | 97% | 1c | 31,478 |

## Results

| strategy | by hand? | period | fills | contracts | cost | P&L | yield | 95% CI (by date) | hit rate | avg CLV | max DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline: buy every YES | yes | walk-forward | 11898 | 118,980 | 52,970.84 | -4,822.44 | -9.1% | -11.7% to -6.7% | +40.4% | -0.02 | 4,905.72 |
| baseline: buy every YES | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-6h | | both | 0 | | | | | | | | |
| ladder fit @ t-6h | yes | walk-forward | 998 | 9,980 | 6,821.02 | -229.72 | -3.4% | -7.5% to +0.7% | +66.1% | -0.01 | 291.10 |
| ladder fit @ t-6h | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-2h | | both | 0 | | | | | | | | |
| ladder fit @ t-2h | yes | walk-forward | 1253 | 12,530 | 8,578.99 | -264.59 | -3.1% | -6.7% to +0.5% | +66.3% | -0.01 | 397.73 |
| ladder fit @ t-2h | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-60m | | both | 0 | | | | | | | | |
| ladder fit @ t-60m | yes | walk-forward | 1336 | 13,360 | 9,191.44 | -471.54 | -5.1% | -9.1% to -1.2% | +65.2% | -0.01 | 547.50 |
| ladder fit @ t-60m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-15m | yes | walk-forward | 356 | 3,560 | 227.15 | -20.25 | -8.9% | -49.8% to +36.3% | +5.8% | -0.02 | 47.41 |
| calibration @ t-15m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder fit @ t-15m | yes | walk-forward | 1455 | 14,550 | 10,025.19 | -307.99 | -3.1% | -6.9% to +0.8% | +66.8% | -0.01 | 347.78 |
| ladder fit @ t-15m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder arbitrage | | both | 0 | | | | | | | | |
| teammate vacuum (1-min, automated) | no | walk-forward | 2 | 20 | 11.05 | -1.05 | -9.5% |  | +50.0% | -0.01 | 4.68 |
| teammate vacuum (1-min, automated) | no | holdout | 0 | 0 |  |  |  |  |  |  |  |
| teammate vacuum (10-min, by hand) | yes | walk-forward | 1 | 10 | 4.68 | -4.68 | -100.0% |  | +0.0% | -0.02 | 4.68 |
| teammate vacuum (10-min, by hand) | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| reversion (1-min) | no | walk-forward | 70 | 700 | 313.24 | -65.84 | -21.0% | -41.5% to +2.7% | +32.3% | -0.01 | 79.36 |
| reversion (1-min) | no | holdout | 0 | 0 |  |  |  |  |  |  |  |
| momentum (1-min) | no | walk-forward | 70 | 700 | 441.17 | 11.43 | +2.6% | -14.4% to +17.3% | +67.7% | -0.04 | 43.93 |
| momentum (1-min) | no | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder fit @ t-60m (as limit orders) | yes | walk-forward | 366 | 3,660 | 2,435.80 | 117.40 | +4.8% | -2.6% to +11.4% | +69.7% | 0.00 | 123.20 |
| ladder fit @ t-60m (as limit orders) | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| teammate vacuum (10-min, by hand) (as limit orders) | yes | walk-forward | 0 | 0 |  |  |  |  |  |  |  |
| teammate vacuum (10-min, by hand) (as limit orders) | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |

**Holdout (2026-04-01 on): sealed.** It is scored once, with `--reveal-holdout`, after the strategies and their parameters are frozen.

## Entry timing (walk-forward only)

| strategy | entry | fills | yield | avg CLV |
|---|---|---|---|---|
| ladder fit | t-6h | 998 | -3.4% | -0.01 |
| ladder fit | t-2h | 1253 | -3.1% | -0.01 |
| ladder fit | t-60m | 1336 | -5.1% | -0.01 |
| calibration | t-15m | 356 | -8.9% | -0.02 |
| ladder fit | t-15m | 1455 | -3.1% | -0.01 |
| ladder fit | t-60m (as limit orders) | 366 | +4.8% | 0.00 |

## By month

| strategy | month | fills | yield |
|---|---|---|---|
| baseline: buy every YES | 2025-12 | 1916 | -8.1% |
| baseline: buy every YES | 2026-01 | 2651 | -12.3% |
| baseline: buy every YES | 2026-02 | 2102 | -9.9% |
| baseline: buy every YES | 2026-03 | 5229 | -7.4% |
| ladder fit @ t-6h | 2025-12 | 23 | -3.2% |
| ladder fit @ t-6h | 2026-01 | 160 | -2.8% |
| ladder fit @ t-6h | 2026-02 | 163 | -1.1% |
| ladder fit @ t-6h | 2026-03 | 652 | -4.1% |
| ladder fit @ t-2h | 2025-12 | 38 | -13.2% |
| ladder fit @ t-2h | 2026-01 | 199 | -4.6% |
| ladder fit @ t-2h | 2026-02 | 237 | -4.3% |
| ladder fit @ t-2h | 2026-03 | 779 | -1.7% |
| ladder fit @ t-60m | 2025-12 | 56 | -7.7% |
| ladder fit @ t-60m | 2026-01 | 193 | -3.1% |
| ladder fit @ t-60m | 2026-02 | 248 | -9.2% |
| ladder fit @ t-60m | 2026-03 | 839 | -4.2% |
| calibration @ t-15m | 2026-02 | 77 | +0.1% |
| calibration @ t-15m | 2026-03 | 279 | -11.6% |
| ladder fit @ t-15m | 2025-12 | 55 | -6.9% |
| ladder fit @ t-15m | 2026-01 | 203 | -2.1% |
| ladder fit @ t-15m | 2026-02 | 303 | -4.9% |
| ladder fit @ t-15m | 2026-03 | 894 | -2.4% |
| teammate vacuum (1-min, automated) | 2026-03 | 2 | -9.5% |
| teammate vacuum (10-min, by hand) | 2026-03 | 1 | -100.0% |
| reversion (1-min) | 2025-12 | 2 | +15.6% |
| reversion (1-min) | 2026-01 | 18 | +2.6% |
| reversion (1-min) | 2026-02 | 11 | +17.8% |
| reversion (1-min) | 2026-03 | 39 | -43.9% |
| momentum (1-min) | 2025-12 | 2 | -22.1% |
| momentum (1-min) | 2026-01 | 18 | -16.0% |
| momentum (1-min) | 2026-02 | 11 | -21.4% |
| momentum (1-min) | 2026-03 | 39 | +19.7% |
| ladder fit @ t-60m (as limit orders) | 2025-12 | 10 | -19.8% |
| ladder fit @ t-60m (as limit orders) | 2026-01 | 51 | +17.1% |
| ladder fit @ t-60m (as limit orders) | 2026-02 | 86 | +1.1% |
| ladder fit @ t-60m (as limit orders) | 2026-03 | 219 | +4.5% |

## The strategies

- **baseline**: Buy every YES at the ask an hour before tip. What the spread and fee cost with no edge at all.
- **calibration**: Learn on earlier dates how often contracts in each price bucket paid, net of the spread and fee, and take the side history favours (the favourite-longshot bias, if Kalshi has one).
- **ladder fit**: A player's rungs should agree with one points distribution. Fit it to the other rungs and buy the rung that sits off the curve.
- **ladder arbitrage**: YES on a lower rung plus NO on a higher rung for under $1 after fees: pays at least $1 whatever happens.
- **teammate vacuum**: Several teammates' ladders jumping together is the market hearing that a star is out. Buy the teammates that haven't moved yet.
- **reversion**: Fade a one-minute move in one market with no team-wide move. Needs automation.
- **momentum**: Follow a one-minute move in one market with no team-wide move. Needs automation.
- **as limit orders**: The same orders resting one tick over the bid instead of taking the ask (no maker fee).

## Caveats

- **No sportsbook consensus here.** These strategies use Kalshi's own prices only. The live system's main strategy (venue vs the books' consensus) needs historical sportsbook lines (SportsGameOdds objects, Rohan's call) or this season's own logs, which start on Opening Night.
- **No usage model here either.** Its 2025-26 inputs are season averages that include the games being tested, which would leak the future.
- **No depth in candles.** Every order is a fixed 10 contracts. Thin books may not have had even that.
- **Many strategies, one season.** Some will look good by luck. Trust a result only if the holdout agrees and CLV is positive, not just P&L.
