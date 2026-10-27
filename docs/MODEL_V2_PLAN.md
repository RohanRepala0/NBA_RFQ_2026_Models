# Model v2: from season averages to opportunity

The v1 model projects a player from last season's usage, minutes and per-minute output, squeezed
into this season's rotation (the usage budget in `usage_model.py`). It has been a coin flip against
the books: on the season's first graded week its blended prices tie the closing consensus on Brier
night after night, closing line value runs slightly negative (about -1c a ticket), and its misses
share one cause. They are opportunity misses, not skill misses.

| What we saw | Why it matters |
|---|---|
| Players in the projected rotation play 191 of the 240 minutes we give them; the rest of the roster takes about 50 a game | every rotation player is projected too many minutes, so too many points (+1.0 on average, +2.5 on the worst night) |
| Mechanical injury rotations over-projected the teammates of an absent star (DEN +5.9, IND +3.6, DAL +2.4 points a player one night) | vacated minutes and usage don't spread evenly; the books knew |
| 16 players in our minutes were not on their team's roster | static rotations go stale |

So v2 predicts the opportunity first (minutes and usage from what each player is doing now) and
the production second, in two stages: rolling features now, a learned model once we hold a full
season of box scores.

## Stage 1: rolling opportunity (built, behind a switch)

**Data.** `boxscores.py` stores every listed player's line and both teams' totals from the same
SportsGameOdds results responses `grade` already fetches: no new source, no extra cost.
`boxscores --from-raw` backfills them from saved responses. SportsGameOdds lists only the players
it carries props for (about 21 a game, 95-100% of team minutes), so team totals come from the team
rows and team minutes from the periods played (240, plus 25 per overtime).

**Usage rate** (the standard box-score formula), stored per player-game:

    USG% = 100 * ((FGA + 0.44 FTA + TOV) * (team minutes / 5)) / (minutes * (team FGA + 0.44 team FTA + team TOV))

**Features** (`features.py`), as of each tip, from games on earlier ET dates only:

| Feature | Definition |
|---|---|
| minutes, FGA, FTA, TOV, usage | means over the last 5 and last 20 games (usage minute-weighted) |
| momentum | 5-game minus 20-game minutes, usage and points per minute |
| per-minute rates | points, rebounds, assists, threes, steals, blocks, turnovers over the last 20 games |
| shrinkage | `rate = (K * prior + sum) / (K + minutes)`, `K = k games x prior minutes per game`; k per stat in `config.ROLLING_PRIOR_GAMES` (rebounds and usage settle fast, threes and steals slowly), halved for a player on a new team; rookies take the league rate for their minutes tier |
| role stability | coefficient of variation of minutes, usage and points per minute over the last 10 games: `engine` (30+ minutes, steady minutes and usage), `heat_check` (points per minute swing), `volatile_role` (minutes swing), `steady`, or `unknown` under 4 games; volatile classes widen the points SD 10% |
| pace | each team's possessions per 48 (`FGA + 0.44 FTA - OREB + TOV`), shrunk to the league over 10 games; the game's expected pace over the team's own is a multiplier |
| opponent resistance | what the opponent allows per possession in each stat, shrunk to the league over 10 games |

Both context multipliers are clamped to 0.90-1.10 until fitted.

**Minutes, the opportunity piece.** Who plays: the chosen scenario (reviewed or official-report
rotation) plus anyone else who played for the team in its last 5 games, less players ruled out
(in full strength but not in tonight's scenario, or listed out for the event). Each player's recent
minutes are shrunk toward the scenario's (3 games of prior weight), then the team is brought to
240: a shortfall goes out by headroom under a 38-minute cap, so rotation players absorb more than a
starter already near the cap; an excess comes off in proportion.

**Production.** The rolling inputs feed the same usage model: shrunk usage in the usage budget,
shrunk rates times projected minutes into the points, rebound and assist budgets, then the pace
and opponent multipliers. Threes, steals, blocks and turnovers are projected the same way and
logged to `extra_projections` only: the venue scan never reads them.

**The switch.** `config.PROJECTION_SOURCE` is `season` (v1, unchanged). `project --source rolling`
runs v2 under its own `model_version`; flipping the config makes the cron re-project every game
under the new version.

### Promotion rules

1. `evaluate` replays every graded game: the season projections as logged live, the rolling ones
   recomputed as of each tip with the same scenarios, and the books' closing consensus mean, on the
   player-games all three cover. Results: `docs/MODEL_V2_EVAL.md`.
2. Rolling replaces season when it beats it on points MAE and Brier over at least two more weeks
   of games it has not seen (the parameters above are frozen until then).
3. `W_MODEL` stays 0.20 for a stat until the model beats the books' closing mean on that stat out
   of sample; today the books still win every stat.
4. A new stat (threes, steals, blocks, combos) gets venue tickets only after it beats the books out
   of sample (Kalshi lists threes, steals, blocks and points + rebounds + assists series). Turnovers
   have no venue market and stay a feature.

### First results

On the season's first five graded nights, the 395 points player-games all three cover:

| Source | Points MAE | Bias | Brier | Minutes MAE | Minutes bias |
|---|---|---|---|---|---|
| season (v1, logged) | 5.14 | +0.96 | 0.268 | 5.56 | +2.07 |
| rolling (v2) | 5.01 | +0.09 | 0.269 | 5.04 | +0.21 |
| books' close | 4.82 | +0.20 | 0.249 | | |

Rolling removes the minutes and points bias and closes part of the gap where it has history (the
latest night: MAE 4.88 season, 4.49 rolling, 4.24 books); with two or three games a team, the
rates are still mostly priors, so Brier doesn't move yet. These nights shaped the design (the
bench finding came from them), so they are in-sample; the out-of-sample record starts with the
next graded night. Not enough to switch: rule 2 applies.

## Stage 2: a learned model (after the November budget reset)

**History.** Last season's box scores and closing lines through the same SportsGameOdds `/events`
endpoint, one object per game: about 1,230 games, half of a month's 2,500 (the client's hard stop
is 2,200). That also gives every player a real 5- and 20-game history from the first night of
this season (the rolling windows carry across seasons, with the team-change rule).

**Models.** Gradient-boosted trees (XGBoost), in two layers like the box score itself:

1. *Minutes*: Stage 1's minutes features plus rest days, back-to-backs, home or away, the spread
   and total when stored, vacated minutes (the minutes of tonight's absent teammates over their
   last 5 games), role class and the scenario's minutes.
2. *Per-minute rates* for points, rebounds, assists, threes, steals, blocks and turnovers, with
   usage, momentum, opponent resistance and pace, and the vacated usage.

The projection is minutes times rate, with dispersion fitted per stat and role class.

**Validation.** Time-ordered splits by month (train on everything before, test on the month), never
a random split; calibration checked per stat on the books' lines; the same promotion rules as
Stage 1 against the books' closing mean, on games after the training window.

## Known gaps

- Only players with props are listed in results, so a rotation's last man can be missing from the
  box scores (his minutes still count in the team's). A results call without the props filter may
  list everyone: worth one object to check.
- Results for two early nights were never fetched; one object a game backfills them.
- The prior for steals, blocks and turnovers is the league rate (last season's table lacks them).
