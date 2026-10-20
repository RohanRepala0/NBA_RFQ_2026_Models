# Backtest: Kalshi NBA player points, 2025-26

Archive: 2,622 settled `KXNBAPTS` markets with candles across 176 games, 2025-11-18 to 2026-05-19 (`cli history`; `cli backtest --docs` rebuilds this page).

**Partial archive: 2,622 of 23,562 markets (11%), 176 of 1,096 games.** The download fetches whole games in random order (after November and part of December, which came first), so this is a season-wide sample, but a small one. Treat every number here as preliminary.

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
| 2025-12 | 839 | 49% | 7c | 200 |
| 2026-01 | 95 | 94% | 5c | 300 |
| 2026-02 | 130 | 68% | 6c | 1,002 |
| 2026-03 | 152 | 92% | 4c | 1,698 |
| 2026-04 | 210 | 98% | 3c | 2,065 |
| 2026-05 | 81 | 95% | 1c | 13,507 |

## Results

| strategy | by hand? | period | fills | contracts | cost | P&L | yield | 95% CI (by date) | hit rate | avg CLV | max DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline: buy every YES | yes | walk-forward | 625 | 6,250 | 2,936.10 | -365.80 | -12.5% | -24.7% to -2.9% | +41.1% | -0.03 | 422.93 |
| baseline: buy every YES | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-6h | | both | 0 | | | | | | | | |
| ladder fit @ t-6h | yes | walk-forward | 36 | 360 | 259.14 | 47.56 | +18.4% | +1.7% to +35.8% | +85.7% | -0.02 | 8.96 |
| ladder fit @ t-6h | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-2h | | both | 0 | | | | | | | | |
| ladder fit @ t-2h | yes | walk-forward | 38 | 380 | 273.44 | 18.16 | +6.6% | -12.2% to +19.7% | +77.8% | -0.02 | 14.73 |
| ladder fit @ t-2h | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-60m | yes | walk-forward | 22 | 220 | 120.32 | -50.32 | -41.8% | -75.6% to +2.6% | +31.8% | -0.02 | 50.32 |
| calibration @ t-60m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder fit @ t-60m | yes | walk-forward | 39 | 390 | 277.06 | 14.54 | +5.2% | -20.3% to +25.5% | +75.7% | -0.02 | 23.13 |
| ladder fit @ t-60m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-15m | yes | walk-forward | 17 | 170 | 116.89 | -16.89 | -14.4% | -46.9% to +3.9% | +58.8% | -0.02 | 21.92 |
| calibration @ t-15m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder fit @ t-15m | yes | walk-forward | 55 | 550 | 390.27 | 6.43 | +1.6% | -16.0% to +19.1% | +72.2% | -0.02 | 22.94 |
| ladder fit @ t-15m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder arbitrage | | both | 0 | | | | | | | | |
| teammate vacuum (1-min, automated) | | both | 0 | | | | | | | | |
| teammate vacuum (10-min, by hand) | | both | 0 | | | | | | | | |
| reversion (1-min) | no | walk-forward | 2 | 20 | 8.84 | -8.84 | -100.0% |  | +0.0% | -0.02 | 8.84 |
| reversion (1-min) | no | holdout | 0 | 0 |  |  |  |  |  |  |  |
| momentum (1-min) | no | walk-forward | 2 | 20 | 12.44 | 7.56 | +60.8% |  | +100.0% | -0.02 | 0.00 |
| momentum (1-min) | no | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder fit @ t-60m (as limit orders) | yes | walk-forward | 13 | 130 | 88.40 | 8.30 | +9.4% | -18.2% to +31.8% | +75.0% | 0.01 | 8.20 |
| ladder fit @ t-60m (as limit orders) | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| teammate vacuum (10-min, by hand) (as limit orders) | | both | 0 | | | | | | | | |

**Holdout (2026-04-01 on): sealed.** It is scored once, with `--reveal-holdout`, after the strategies and their parameters are frozen.

## Entry timing (walk-forward only)

| strategy | entry | fills | yield | avg CLV |
|---|---|---|---|---|
| ladder fit | t-6h | 36 | +18.4% | -0.02 |
| ladder fit | t-2h | 38 | +6.6% | -0.02 |
| calibration | t-60m | 22 | -41.8% | -0.02 |
| ladder fit | t-60m | 39 | +5.2% | -0.02 |
| calibration | t-15m | 17 | -14.4% | -0.02 |
| ladder fit | t-15m | 55 | +1.6% | -0.02 |
| ladder fit | t-60m (as limit orders) | 13 | +9.4% | 0.01 |

## By month

| strategy | month | fills | yield |
|---|---|---|---|
| baseline: buy every YES | 2025-12 | 350 | +2.1% |
| baseline: buy every YES | 2026-01 | 79 | -45.5% |
| baseline: buy every YES | 2026-02 | 61 | -26.3% |
| baseline: buy every YES | 2026-03 | 135 | -27.4% |
| ladder fit @ t-6h | 2025-12 | 7 | +31.3% |
| ladder fit @ t-6h | 2026-01 | 8 | +18.0% |
| ladder fit @ t-6h | 2026-02 | 5 | +15.7% |
| ladder fit @ t-6h | 2026-03 | 16 | +13.2% |
| ladder fit @ t-2h | 2025-12 | 8 | -5.2% |
| ladder fit @ t-2h | 2026-01 | 6 | +12.6% |
| ladder fit @ t-2h | 2026-02 | 6 | +7.7% |
| ladder fit @ t-2h | 2026-03 | 18 | +10.2% |
| calibration @ t-60m | 2026-01 | 22 | -41.8% |
| ladder fit @ t-60m | 2025-12 | 11 | -9.8% |
| ladder fit @ t-60m | 2026-01 | 6 | +15.8% |
| ladder fit @ t-60m | 2026-02 | 6 | +21.9% |
| ladder fit @ t-60m | 2026-03 | 16 | +7.7% |
| calibration @ t-15m | 2026-03 | 17 | -14.4% |
| ladder fit @ t-15m | 2025-12 | 15 | -13.6% |
| ladder fit @ t-15m | 2026-01 | 7 | +22.3% |
| ladder fit @ t-15m | 2026-02 | 15 | +16.2% |
| ladder fit @ t-15m | 2026-03 | 18 | -4.6% |
| reversion (1-min) | 2026-03 | 2 | -100.0% |
| momentum (1-min) | 2026-03 | 2 | +60.8% |
| ladder fit @ t-60m (as limit orders) | 2025-12 | 2 | -37.5% |
| ladder fit @ t-60m (as limit orders) | 2026-01 | 1 | +26.6% |
| ladder fit @ t-60m (as limit orders) | 2026-02 | 1 | +96.1% |
| ladder fit @ t-60m (as limit orders) | 2026-03 | 9 | +12.3% |

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
