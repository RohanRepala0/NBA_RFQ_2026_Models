# The daily job

One command runs the whole pipeline unattended: `python -m cold_start_usage.cli daily`. GitHub
Actions runs it on a schedule ([`.github/workflows/nba-daily.yml`](../.github/workflows/nba-daily.yml))
and commits the results to `bets/`. Each run does only what's due, so running it again right away
does nothing and spends nothing. Research only: it logs paper tickets and never places an order.

## What a run does

1. **Grades past days.** For each of the last 3 days with a stored slate and anything still open,
   it fetches results and box scores (SportsGameOdds, 1 object a game) and venue settlements
   (free public reads: one Kalshi read a game, one Polymarket US read a contract). Then it rebuilds
   that day's journal. A day stops being retried once every ticket is settled.
2. **Fills in box scores.** Any of the last 14 days with none stored is fetched (1 object a game),
   so the rotations and the rolling model see recent games after a fresh start or a missed night.
3. **Takes today's slate**, once a day, then each game's due checkpoints (t-6h, t-2h, t-60m, t-15m
   for the books; also t-5m for the venues). A late run takes a due checkpoint late, but never after tip.
4. **Builds rotations**, once a day: each team's minutes over its last 10 games, without anyone
   who missed all of the last 3, brought to 240 with nobody over 37 (`autorotation.py`, written as
   the `auto` scenario in `cold_start_usage/scenarios/TEAM.csv`). Players listed out come off at
   each checkpoint, from the injury statuses in the latest SportsGameOdds snapshot.
5. **Projects with the rolling model** for every un-tipped game. It projects again at each
   checkpoint, so the latest statuses apply.
6. **Logs signals and reads the venues.** It logs the sportsbook signals and reads Kalshi and
   Polymarket US at each due checkpoint. Then it decides every contract with the usual gates and caps.
7. **Writes the journal and sends alerts.** It rebuilds today's journal and sends ntfy alerts:
   - `PLAYS`: each new ticket.
   - `FADED`: a ticket that no longer clears before tip ("cancel if unfilled").
   - `Graded`: the morning's results.
   - `RUN PROBLEM`: something failed. This alert goes out at most once a day per problem.

A step that fails is reported and the others still run. The run then exits 1, so GitHub marks it
failed and emails the repository owner.

**Why the rolling model.** Unattended, the job prices with the rolling model
(`config.DAILY_JOB_SOURCE`). The season model needs a person to review each team's minutes every
day, and the rolling model rebuilds them from box scores. Rolling also had the smaller errors in
both graded windows so far ([`MODEL_V2_EVAL.md`](MODEL_V2_EVAL.md); out of sample, Oct 27-31:
points MAE 5.64 against 5.80, minutes 5.3 against 6.0). Both still trail the books' closing
consensus, and the blend gives the model only a fifth of the weight. Commands run by hand keep
`config.PROJECTION_SOURCE`.

**A hand-built rotation wins.** Commit a scenario named `report_MMDD` (or `report_MMDD_b`, and so
on) for the day to a team's file, and the next run projects that team with it instead of `auto`.

## Results

- [`bets/SEASON.md`](../bets/SEASON.md): the season record. Totals, by stat and by day: tickets,
  wins against expected, stake, P&L, yield and closing-line value.
- `bets/days/YYYY-MM-DD/summary.md`: one slate's tickets with entry, close, result and P&L.
- `bets/ledger.csv`: every ticket.

The job commits these after any run that changed them, with a message like `Daily job: journal and
rotations, YYYY-MM-DD HH:MM ET`.

## Setup

1. **Merge to the default branch.** GitHub runs scheduled workflows only from the repository's
   default branch.
2. **Add the secrets** (Settings > Secrets and variables > Actions):
   - `SPORTS_ODDS_API_KEY`: required for odds, results and box scores. Without it the job only
     settles venue contracts, and it alerts that the key is missing.
   - `NTFY_TOPIC`: optional, for phone alerts through ntfy.
   - Optional variable `COLD_START_BANKROLL_USD`: sets the suggested sizes. The default is 5000.
3. **Run it once by hand:** Actions > NBA daily job > Run workflow. The first run fetches up to
   14 days of box scores (about 100 objects) and the day's slate.

To pause it, use Actions > NBA daily job > ... > Disable workflow.

## Schedule and costs

- **Schedule (ET, standard time).** Hourly from 10:50 AM to 4:50 PM, then every 30 minutes from
  5:20 PM to 10:50 PM. That's 19 runs a day, so most games get a read about 40 and about 10
  minutes before tip. GitHub can start a scheduled run several minutes late. Afternoon tips get
  hourly reads only.
- **SportsGameOdds.** About 1 object a game for the slate, 1 a game at each checkpoint (4) and 1 a
  game for results: roughly 50 a day on a 9-game night, under the plan's 2,500 a month.
  `config.MONTHLY_OBJECT_HARD_STOP` (2,200) stops metered calls before the limit, and the venue
  reads and grading carry on.
- **GitHub Actions minutes.** A quiet run takes about a minute and the morning grade a few more,
  so roughly 25 to 40 minutes a day. A private repository on the free plan gets 2,000 minutes a
  month; a public one is free.

## Where the state lives

The decision log (`data/edge_lab.duckdb`, git-ignored) and the run state (`data/daily_state.json`)
are kept in the Actions cache. Each run restores the newest entry and saves a new one. GitHub
evicts entries that go unused for 7 days, so the log survives as long as the job keeps running.

If the cache is lost, the next run starts a fresh log: it refetches the box scores and carries on.
The committed `bets/` folder is the durable record. `journal` keeps every committed day the log
doesn't cover, so a fresh log never drops earlier tickets from `ledger.csv` or `SEASON.md`.
