# Do early-season shifts last? The 2025-26 persistence study

The rolling model (model v2) shrinks each player's rates toward last season's with k games of
prior weight: `rate = (K * prior + sum) / (K + minutes)`, `K = k * prior minutes per game`. This
study asks what k should be, by replaying the rule on a whole past season, and whether an early
usage shift tends to hold.

## Data

- **Players:** 48 drawn at random (fixed seed) from the 217 in `players_2025_26.csv` with 45+
  games and 20+ minutes a game in 2025-26, leaving out 2025 rookies (they have no prior). Two
  dropped: Court AI could not resolve Saddiq Bey's 2024-25 line, and Brandon Ingram played 18
  games in 2024-25 (under the 25-game floor). That leaves 46, of whom 10 started 2025-26 on a new
  team (Cameron Johnson, Deandre Ayton, Dillon Brooks, Jake LaRavia, Jrue Holiday, Marcus Smart,
  Michael Porter Jr., Myles Turner, Nickeil Alexander-Walker, Norman Powell).
- **Prior:** each player's 2024-25 season totals and official usage (Court AI `get_season_stats`).
- **2025-26 games:** Court AI `query_game_logs`, one call per market (FGA, FTA, TOV, 3PM). Each
  game line also carries minutes, points, rebounds and assists. Five calls per player, about 230
  in all. The copies are checked against Court AI's own printed averages, and a file that doesn't
  match is rejected. Court AI's prices are never read.
- **Usage per game:** Court AI's game logs have no per-game usage, so it comes from the plays
  proxy `FGA + 0.44 FTA + TOV` per minute, scaled so the season matches the player's official
  2025-26 usage. Early and late usage keep their true ratio and the official scale.

## Method

For each player and each cut n = 1..15:

- **Early sample:** his first n games.
- **Target:** the rest of his season, or for the second target only games through 2026-01-31,
  before the trade deadline, so a mid-season trade doesn't count as a shift. A cut needs at least
  20 target games.
- **Estimate:** the rolling rule at each k, compared with the target by root-mean-square error
  (RMSE). Usage is in USG points, rates per 36 minutes, minutes per game.
- **Minutes:** follow `rolling_minutes`: the last 5 games against k games of the prior's minutes
  per game.
- **Bands:** the 10th-90th percentile of the best k over 500 player-level bootstrap resamples.
- **Players on a new team:** k is fitted on the players who stayed. The multiplier on k comes
  from the 10 who moved.

## Results

**1. Usage shifts hold.** A shift is usage 3+ points off last season's after n games. "Share of
shift kept" is the median of (rest − prior) / (early − prior), and "slope" is the regression of
rest-of-season shift on early shift across all players.

| After n games | Shifted | Kept direction | Share of shift kept | Slope |
|---|---|---|---|---|
| 3 | 24 of 46 | 22 (92%) | 0.63 | 0.58 |
| 4 | 21 | 19 (90%) | 0.72 | 0.66 |
| 5 | 22 | 20 (91%) | 0.75 | 0.68 |
| 10 | 21 | 20 (95%) | 0.79 | 0.77 |

With the pre-deadline target it's 95% kept after 3, 4 and 5 games (shares 0.49-0.65). So 9 in 10
early shifts keep their direction, and about two thirds of their size lasts after five games.
The two groups differ, though. After five games:
- **Players who stayed:** the slope is 0.43-0.47 and the median share kept 0.50-0.64. That is what
  k = 5-6 implies: five games against six of prior puts a 0.45-0.5 weight on the early sample.
- **Players who moved:** the slope is 1.0 and the share kept 0.97-0.98. A new team's usage after
  five games was, on average, the rest of his season's.

**2. Fitted k per stat.** Players who stayed, with the model's new-team multiplier for those
who moved:

| Stat | k before | k fitted, full season (band) | k fitted, pre-deadline (band) | k now |
|---|---|---|---|---|
| usage | 6 | 5 (3-8) | 6 (4-10) | 6 |
| points | 6 | 10 (7-20) | 12 (8-20) | **10** |
| rebounds | 5 | 20 (15-40) | 20 (15-40) | **20** |
| assists | 5 | 8 (5-12) | 6 (4-8) | 5 |
| threes | 12 | 25 (15-40) | 20 (10-40) | 12 |
| turnovers | 10 | 12 (8-20) | 15 (10-25) | 10 |
| minutes | 3 | 4 (2-10) | 3 (1.5-5) | 3 |

A setting moved only where a band excluded it and both targets agreed: points to 10 and
rebounds to 20. The rest stay as set.
- **Rebounds** settle slowly. At the old k of 5 the rolling estimate was worse than last
  season's rate alone (RMSE 0.95 against 0.94). The original guess that rebounds settle fast was
  wrong.
- **Threes** lean the same way (k 20-25) but the pre-deadline band includes 12.
- **Steals and blocks** weren't studied (two more calls per player).

**3. A new team: trust the first games.** RMSE for the 10 players who moved, by the multiplier
on k:

| Multiplier | 0 | 0.1 | 0.25 | 0.5 (before) | 1 |
|---|---|---|---|---|---|
| usage | 2.24 | **2.19** | 2.47 | 2.95 | 3.65 |
| points | 3.06 | **2.80** | 2.98 | 3.37 | 3.94 |
| rebounds | 1.32 | 0.75 | 0.56 | **0.51** | 0.55 |
| assists | 1.11 | 0.76 | 0.61 | **0.59** | 0.68 |
| threes | 0.83 | 0.65 | 0.60 | **0.60** | 0.62 |

A mover's usage and scoring on his new team show in his first games, and last season's barely
helps. His per-minute box rates move much less. Dropping any one of the 10 players leaves the
order 0.1 < 0.25 < 0.5 for usage and points every time. The model now keeps a tenth of the
prior's weight for a mover's usage and points and half for the rest
(`config.TEAM_CHANGE_PRIOR_SCALE`). Ten players is a small sample.

**What the changes buy on 2025-26** (RMSE, old settings → new):

| | Full season | Pre-deadline |
|---|---|---|
| usage | 2.52 → 2.30 | 2.21 → 1.99 |
| points per 36 | 2.77 → 2.69 | 2.61 → 2.47 |
| rebounds per 36 | 0.95 → 0.85 | 0.92 → 0.81 |

**This season's games** say nothing either way yet. Replaying the graded 2026-27 games
(`evaluate`'s walk-forward, 677 player-games, players' first four or five games) under both
settings:
- points MAE rises 0.024 (standard error 0.016);
- rebounds MAE falls 0.016 (0.010).

The settings come from 2025-26 only, so every 2026-27 game stays out of sample for them, and
`evaluate` keeps scoring them under `usage-squeeze-1.1+rolling-0.2`.

## What it means for the bets

The season model, which still prices every ticket, starts from last season's usage and the
reviewed rotation. It doesn't read this season's games. The study says about two thirds of an
early usage shift lasts, and nearly all of a new team's, which is what `shifts` flags: the priors
most likely to be stale. The rolling model reads those games. Whether it takes over still goes
by the promotion rules in `docs/MODEL_V2_PLAN.md` (two more weeks out of sample against the season
model and the books).

## Caveats

- **Usage is the plays proxy, not the official box-score number.** Minutes in the game lines are
  whole minutes.
- **The prior is last season's raw rate.** That is the live model's prior too, apart from rookies.
- **The minutes fit uses last season's minutes per game as the prior.** Live, it's the reviewed
  scenario, which is a better prior, so the minutes k wasn't changed.
- **The target is the rest of the season, not the next game.** The k that predicts a player's
  true rate best is the one wanted, and next-game noise is the same for every k.
- **A random sample of rotation players**, so few stars and few big role changes. The new-team
  results rest on 10 players.

## Reproducing

The copied Court AI text sits under `data/raw/courtai/persist_2025_26/` (git-ignored, like the
rest of the raw data). Files are `<slug>__season_2024-25.txt` (the `get_season_stats` output) and
`<slug>__<FGA|FTA|TOV|3PM>.txt` (the `Sample:` and `Season averages` lines and every game line of
`query_game_logs`, season 2025-26).

    python -m cold_start_usage.cli persistence                          # full-season target
    python -m cold_start_usage.cli persistence --target-end 2026-01-31  # before the trade deadline

The command prints the fit table, the fitted k by cut, the new-team multipliers and the
direction table (`--csv` writes the player-cut rows).
