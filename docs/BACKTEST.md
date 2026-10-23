# Backtest: Kalshi NBA player points, 2025-26

Archive: 18,186 settled `KXNBAPTS` markets with candles across 867 games, 2025-11-18 to 2026-06-13 (`cli history`; `cli backtest --docs` rebuilds this page).

**Partial archive: 18,186 of 23,562 markets (77%), 867 of 1,096 games.** The download fetches whole games in random order (after November and part of December, which came first), so this is a season-wide sample, but a small one. Treat every number here as preliminary.

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
| 2025-12 | 2,328 | 71% | 6c | 250 |
| 2026-01 | 3,025 | 88% | 5c | 507 |
| 2026-02 | 2,346 | 79% | 4c | 1,257 |
| 2026-03 | 4,844 | 87% | 4c | 1,084 |
| 2026-04 | 3,204 | 91% | 3c | 2,325 |
| 2026-05 | 1,099 | 95% | 1c | 13,737 |
| 2026-06 | 225 | 98% | 1c | 30,536 |

## Results

| strategy | by hand? | period | fills | contracts | cost | P&L | yield | 95% CI (by date) | hit rate | avg CLV | max DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline: buy every YES | yes | walk-forward | 8979 | 89,790 | 40,037.12 | -3,513.42 | -8.8% | -11.6% to -6.1% | +40.7% | -0.02 | 3,570.55 |
| baseline: buy every YES | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-6h | | both | 0 | | | | | | | | |
| ladder fit @ t-6h | yes | walk-forward | 748 | 7,480 | 5,103.40 | -18.40 | -0.4% | -4.9% to +4.8% | +68.1% | -0.01 | 97.81 |
| ladder fit @ t-6h | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-2h | | both | 0 | | | | | | | | |
| ladder fit @ t-2h | yes | walk-forward | 926 | 9,260 | 6,368.79 | -151.09 | -2.4% | -6.3% to +1.8% | +67.0% | -0.01 | 253.75 |
| ladder fit @ t-2h | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-60m | | both | 0 | | | | | | | | |
| ladder fit @ t-60m | yes | walk-forward | 989 | 9,890 | 6,825.74 | -244.74 | -3.6% | -7.9% to +0.7% | +66.5% | -0.01 | 320.46 |
| ladder fit @ t-60m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| calibration @ t-15m | yes | walk-forward | 263 | 2,630 | 169.34 | -2.44 | -1.4% | -45.2% to +47.5% | +6.3% | -0.02 | 28.60 |
| calibration @ t-15m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder fit @ t-15m | yes | walk-forward | 1063 | 10,630 | 7,338.07 | -150.67 | -2.1% | -6.0% to +1.7% | +67.6% | -0.01 | 248.10 |
| ladder fit @ t-15m | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder arbitrage | | both | 0 | | | | | | | | |
| teammate vacuum (1-min, automated) | no | walk-forward | 1 | 10 | 4.68 | -4.68 | -100.0% |  | +0.0% | -0.02 | 4.68 |
| teammate vacuum (1-min, automated) | no | holdout | 0 | 0 |  |  |  |  |  |  |  |
| teammate vacuum (10-min, by hand) | yes | walk-forward | 1 | 10 | 4.68 | -4.68 | -100.0% |  | +0.0% | -0.02 | 4.68 |
| teammate vacuum (10-min, by hand) | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| reversion (1-min) | no | walk-forward | 53 | 530 | 236.63 | -31.23 | -13.2% | -40.5% to +18.0% | +36.2% | -0.00 | 65.21 |
| reversion (1-min) | no | holdout | 0 | 0 |  |  |  |  |  |  |  |
| momentum (1-min) | no | walk-forward | 53 | 530 | 333.97 | -9.37 | -2.8% | -25.2% to +16.7% | +63.8% | -0.04 | 51.92 |
| momentum (1-min) | no | holdout | 0 | 0 |  |  |  |  |  |  |  |
| ladder fit @ t-60m (as limit orders) | yes | walk-forward | 280 | 2,800 | 1,869.80 | 109.30 | +5.8% | -2.5% to +13.2% | +70.7% | 0.00 | 103.70 |
| ladder fit @ t-60m (as limit orders) | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |
| teammate vacuum (10-min, by hand) (as limit orders) | yes | walk-forward | 0 | 0 |  |  |  |  |  |  |  |
| teammate vacuum (10-min, by hand) (as limit orders) | yes | holdout | 0 | 0 |  |  |  |  |  |  |  |

**Holdout (2026-04-01 on): sealed.** It is scored once, with `--reveal-holdout`, after the strategies and their parameters are frozen.

## Entry timing (walk-forward only)

| strategy | entry | fills | yield | avg CLV |
|---|---|---|---|---|
| ladder fit | t-6h | 748 | -0.4% | -0.01 |
| ladder fit | t-2h | 926 | -2.4% | -0.01 |
| ladder fit | t-60m | 989 | -3.6% | -0.01 |
| calibration | t-15m | 263 | -1.4% | -0.02 |
| ladder fit | t-15m | 1063 | -2.1% | -0.01 |
| ladder fit | t-60m (as limit orders) | 280 | +5.8% | 0.00 |

## By month

| strategy | month | fills | yield |
|---|---|---|---|
| baseline: buy every YES | 2025-12 | 1472 | -8.3% |
| baseline: buy every YES | 2026-01 | 2221 | -11.9% |
| baseline: buy every YES | 2026-02 | 1512 | -8.5% |
| baseline: buy every YES | 2026-03 | 3774 | -7.1% |
| ladder fit @ t-6h | 2025-12 | 20 | +2.7% |
| ladder fit @ t-6h | 2026-01 | 135 | +3.8% |
| ladder fit @ t-6h | 2026-02 | 108 | -1.1% |
| ladder fit @ t-6h | 2026-03 | 485 | -1.5% |
| ladder fit @ t-2h | 2025-12 | 29 | -10.0% |
| ladder fit @ t-2h | 2026-01 | 165 | -1.9% |
| ladder fit @ t-2h | 2026-02 | 160 | -4.6% |
| ladder fit @ t-2h | 2026-03 | 572 | -1.5% |
| ladder fit @ t-60m | 2025-12 | 42 | -0.3% |
| ladder fit @ t-60m | 2026-01 | 160 | +0.2% |
| ladder fit @ t-60m | 2026-02 | 176 | -8.6% |
| ladder fit @ t-60m | 2026-03 | 611 | -3.4% |
| calibration @ t-15m | 2026-02 | 50 | +22.9% |
| calibration @ t-15m | 2026-03 | 213 | -7.7% |
| ladder fit @ t-15m | 2025-12 | 40 | -3.2% |
| ladder fit @ t-15m | 2026-01 | 162 | +1.5% |
| ladder fit @ t-15m | 2026-02 | 207 | -5.3% |
| ladder fit @ t-15m | 2026-03 | 654 | -1.9% |
| teammate vacuum (1-min, automated) | 2026-03 | 1 | -100.0% |
| teammate vacuum (10-min, by hand) | 2026-03 | 1 | -100.0% |
| reversion (1-min) | 2025-12 | 2 | +15.6% |
| reversion (1-min) | 2026-01 | 15 | +8.2% |
| reversion (1-min) | 2026-02 | 10 | +34.0% |
| reversion (1-min) | 2026-03 | 26 | -43.6% |
| momentum (1-min) | 2025-12 | 2 | -22.1% |
| momentum (1-min) | 2026-01 | 15 | -20.2% |
| momentum (1-min) | 2026-02 | 10 | -30.0% |
| momentum (1-min) | 2026-03 | 26 | +20.3% |
| ladder fit @ t-60m (as limit orders) | 2025-12 | 8 | -3.2% |
| ladder fit @ t-60m (as limit orders) | 2026-01 | 42 | +21.7% |
| ladder fit @ t-60m (as limit orders) | 2026-02 | 62 | -0.2% |
| ladder fit @ t-60m (as limit orders) | 2026-03 | 168 | +4.2% |

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
