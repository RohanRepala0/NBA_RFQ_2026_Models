# Cold Start Usage Projection Modeling

Points, rebounds and assists projections for every NBA player whose role changed this offseason, compared against a sportsbook consensus. These are **cold starts**: the player has no games yet in his new role, so the projection is built from last season's usage, rebounding and passing and the new roster instead of recent form. Positions are taken only on **Kalshi** and **Polymarket US**, the two prediction markets Rohan can trade. The sportsbooks are used only as the fair-value reference, never as a place to bet. When a venue lists "Giannis 30+ points" or "Bam 10+ rebounds", the fair price, the most it's worth paying after the venue's fee, and how many contracts to buy are already known.

- **League-wide:** [`docs/CATALOG.md`](docs/CATALOG.md) lists **162 offseason role changes** across all 30 teams. They're tagged by usage tier (high / medium / low) and by situation: *arrival* (new team), *vacuum* (a star left, so the remaining players' usage grows) or *squeeze* (a star arrived, so it shrinks).
- **Case studies:** Giannis to Miami and Kawhi to Toronto, with hand-reviewed minutes.
- **The waiting list:** [`docs/BOARD.md`](docs/BOARD.md) shows the thesis, projection and fair "N+ points" prices for each situation, and fills in the market as lines post. There's also an interactive version: [Offseason Usage Board](https://claude.ai/artifact/PrSUHQ8ouReBWT3E3ybbGX).

Research only: this tool doesn't connect to any venue account and doesn't place orders. It prints limit-order tickets that you enter by hand. Every projection, venue price and decision is logged before tip and graded afterwards at the venue's own settlement, with CLV and calibration. See `HANDOFF.md` for the spec, rules and open decisions.

## Setup

```bash
pip install -r requirements.txt          # Python 3.11+
export SPORTS_ODDS_API_KEY=...           # or put it in .env (git-ignored); never commit it
export COLD_START_BANKROLL_USD=1000     # optional: turns on suggested contract counts (never read from any account)
python -m pytest -q                      # 181 offline tests
```

## Opening Night plan: cron goes live before Tue 10/20

The job is installed on a local machine **before Opening Night (Tuesday, October 20, 2026; first tip 3:00 PM ET)**, so the first snapshot history starts with the first tip of the season. It runs every 5 minutes:

- **Sportsbooks** (metered): calls SportsGameOdds only when a game reaches a new checkpoint (T-6h, T-2h, T-60m, T-15m). Each day's slate is fetched once. Every call asks for player points, rebounds and assists together; it's billed per event, so the extra stats cost nothing.
- **Venues** (free): reads Kalshi (points, rebounds and assists series) and Polymarket US at T-6h, T-2h, T-60m, T-15m and T-5m, decides every contract, and logs prices and decisions. T-5m is the venue close used for CLV. This step runs even if the sportsbook step fails (budget stop, missing key).
- **Projections**: a game with no current projections gets them automatically. That covers a game with none logged, a team whose latest run came from an older model version, and a run missing a stat (say, points-only rows logged before rebounds and assists). Each team keeps the scenario of its latest run (full strength / the auto rotation when it has none), so a fill-in never undoes your `project --scenario` choice. A later `project --scenario` replaces a team's run, and teams you don't name keep theirs.

```
*/5 * * * * cd ~/NBA_RFQ_2026_Models && python -m cold_start_usage.cli snapshot --due --with-signals --with-venues --with-projections >> data/cron.log 2>&1
```

Before the first game day:

```bash
python -m cold_start_usage.cli usage                 # objects used / left (this call is free)
python -m cold_start_usage.cli catalog               # rebuild the league-wide catalog (no API calls)
python -m cold_start_usage.cli board --docs          # refresh the waiting list
python -m cold_start_usage.cli roster --date 2026-10-26 --apply   # minutes vs ESPN rosters; writes and projects fixes
```

On each game day:

```bash
# ~65 min before tip, after the injury report: confirm or change each team's scenario
python -m cold_start_usage.cli project --scenario MIA=full_strength --scenario TOR=kawhi_out
python -m cold_start_usage.cli venues                # read Kalshi + Polymarket US now, decide, log (cron does this at each checkpoint)
python -m cold_start_usage.cli tickets               # reads the venues now, then lists the actionable contracts: venue, ticker,
                                                     # side, limit price, quantity, cancel-by (only reads from the last 20 min)
# enter the tickets by hand as limit orders, then record what you got (a typo? log the right one with --replaces):
python -m cold_start_usage.cli fill --signal-id <id> --contracts 10 --price 0.41
python -m cold_start_usage.cli fill --signal-id <id> --contracts 10 --price 0.41 --paper   # tracked, no money
python -m cold_start_usage.cli board                 # the waiting list: READY only when a venue price clears the bar
python -m cold_start_usage.cli watchlist             # sportsbook leans next to what the venues list (not actionable)
```

The next morning, settle and then journal the day, and commit `bets/`:

```bash
python -m cold_start_usage.cli grade --date 2026-10-20     # venue settlements, P&L at the price paid, venue CLV
python -m cold_start_usage.cli journal --date 2026-10-20   # bets/: ledger, fills, the day's tickets/results/summary
```

`grade` also stores the box scores of every listed player (`boxscores --from-raw` backfills them from saved results, free). Model v2 runs on them: `project --source rolling` projects from this season's games (recent minutes, usage and rates shrunk to last season, the team's recent bench, pace and opponent) and `evaluate --docs` replays every graded game, season vs rolling vs the books' close. The default stays the season model until rolling wins out of sample: [`docs/MODEL_V2_PLAN.md`](docs/MODEL_V2_PLAN.md), results in [`docs/MODEL_V2_EVAL.md`](docs/MODEL_V2_EVAL.md).

Add `--venues-only` to `grade` to skip the metered SportsGameOdds results call (model-vs-books grading). `journal` makes no API calls and only reads the log (anything `grade` hasn't settled reads `pending`); `journal --all` rebuilds every day. A fill logged with `--paper` (or a note starting `paper`) is journaled as paper, one with a note starting `discretionary` (or logged by `--ticker` on a contract the scan never made actionable) as discretionary, anything else as real; see [`bets/README.md`](bets/README.md). Weekly: `report`.

Teams without hand-reviewed minutes use the catalog's automatic rotation (`cold_start_usage/scenarios/auto/`). Copy one up to `cold_start_usage/scenarios/` and edit it to make it reviewed.

## Dry run without the API

```bash
DB=/tmp/demo.duckdb
python -m cold_start_usage.cli --db $DB --now 2026-10-21T22:30:00Z snapshot --from-file examples/synthetic_slate_2026-10-21.json
python -m cold_start_usage.cli --db $DB --now 2026-10-21T22:31:00Z project --date 2026-10-21
python -m cold_start_usage.cli --db $DB --now 2026-10-21T22:32:00Z signals --date 2026-10-21
python -m cold_start_usage.cli --db $DB --now 2026-10-21T22:33:00Z board
```

The matchup and player IDs are real; the odds are invented. `--now` only works with a separate `--db`, so the real log can never be back-dated.

## Where the data comes from

| Data | Source | Notes |
|---|---|---|
| Odds, results and box scores | SportsGameOdds API (licensed, free Amateur plan) | 9 books on this key; 4 post player points, rebounds and assists (Caesars joined Bovada, DraftKings and ESPN Bet for the opener). No prediction markets on this plan. |
| Prediction-market prices | Kalshi (`api.elections.kalshi.com`) and Polymarket US (`gateway.polymarket.us`) public market-data APIs: read-only, no key | What each venue lists, its fees and its settlement rules: [`docs/VENUES.md`](docs/VENUES.md). The international polymarket.com book is read only as a reference price (US persons can't open positions there). |
| Backtest archive | Kalshi `/historical/...`: every 2025-26 player-points ladder, result and 1-minute candles | `cli history` downloads it into `data/history/` (git-ignored). It's resumable, in random game order, so a partial download is a season-wide sample; the full download takes ~7 hours at the public rate limit. `cli backtest --docs` writes [`docs/BACKTEST.md`](docs/BACKTEST.md); the April-onward holdout stays sealed until `--reveal-holdout`. |
| 2025-26 player lines (all 30 teams) | StatMuse team pages, one source URL per row | Usage, minutes, points, 3-point shooting, and season rebound and assist totals (offensive and defensive too). Every row is checked against its season totals. |
| 2026-27 rosters | Manual overrides > NBA.com offseason tracker > SportsGameOdds `/players` > last season's team | SportsGameOdds has gaps (Curry, Butler and Horford show no team; Klay was stale), so it isn't trusted alone. Confirmed corrections go in `data/roster_overrides_2026_27.csv`. |
| Team 3-point volume and accuracy (spacing) | StatMuse team pages | |

Basketball-Reference isn't used: its terms bar using site data "to create any database", which an automated pull here would do. NBA.com's statistics terms bar gambling-related use. See `HANDOFF.md` section 4b.

How the data moves from source to signal, with diagrams: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

What the free plan can't do, and the paid feed options, are noted in [`docs/SCALING.md`](docs/SCALING.md).

## How a venue contract becomes actionable

`decision.py` is the only code that can call a contract actionable. It works out one fair price per player-game and stat, leaning on the market: that stat's sportsbook consensus mean, moved 20% toward the model while they're within 0.75 of the stat's SD of each other. Each contract is priced at the lower of two models (`distributions.py`):

- **Points:** a normal with SD max(4, 0.3 × mean), and a compound-Poisson SD.
- **Rebounds and assists:** counts, so a negative binomial with variance φ × mean, priced at φ and at a fatter-tailed φ_alt (rebounds 1.30 / 1.50, assists 1.15 / 1.30).

A Kalshi rung or Polymarket US market is then actionable only if all of these hold:

1. The game hasn't tipped, the player isn't listed out, and the consensus is fresh (2+ books, no quote older than 30 min, not newer than the venue quote).
2. The rung isn't a tail: the market puts 10-90% on it.
3. The edge after the venue's fee is at least 4pp (5pp with only 2 books), the sportsbook market alone isn't against it, and it's below the 15pp "check inputs" cap.
4. At least 10 contracts are offered at or under the max price.

It's one pick per player-game and stat, sized at quarter Kelly, capped at 0.5% of bankroll per player-game (a player's points and rebounds picks share it, since both ride on his minutes), 1.5% per game and 3% per slate while ungraded. The caps count your logged fills and every ticket already sent on the slate, however old, so following every ticket can't stack past them; each player-stat counts at the largest stake it was ever ticketed at, and a later pick on it re-prices that ticket rather than adding to it (a smaller re-pricing frees nothing for other picks, since you may hold the bigger one); a stat you already hold on a player-game gets no new pick. Rebounds need 2pp more edge than points and assists (`STAT_EXTRA_EDGE` in `config.py`). Each contract's cost is walked up the order book (average price plus the fee at the real order size). The limit price never exceeds what the sportsbook market alone says the contract is worth. Questionable players and thin books show as `watch`.

## Rules the code enforces

- **Venues:** only Kalshi and Polymarket US are actionable; anything else is refused at write time. No code path can place an order: venue modules make public GETs only, and a test checks the source for order, portfolio and key usage.
- **Book allowlist** (`config.py`): reference sportsbooks build the consensus, SportsGameOdds-labelled prediction markets are stored but never enter it, and DFS apps are logged as unpriced. Any other book is dropped at request time, at parse time and at write time.
- SportsGameOdds' precomputed consensus fields are dropped at parse time.
- Tables are append-only, and nothing is logged for a game that has already tipped. Venue prices and decisions stamped at or after tip are refused by storage itself: Kalshi markets keep trading in-game, so the tip always comes from the schedule.
- Budget guard: the hard stop is 2,200 objects/month. It checks usage before every billable request and fails closed. Failed requests count too.
- The API key is sent only as a header and never printed.

## Before trusting a signal

- **The model leans against stars.** It ignores star staggering, so stars keep more usage than it projects. On opening night's real lines it has Tatum at 21 vs the market's 26.5. Edges above 15pp are logged as `abstain` ("sanity cap"). Grade first.
- **Rebounds and assists use frozen priors.** A team's rebounds (assists) are pulled toward the league's 43.6 (26.6) per game with diminishing returns, ρ = 0.6 (0.5), taken from the lineup-regression literature rather than fitted here. The count dispersions φ come from 2021-24 box scores and the opening-week venue ladders. All of them stay fixed until graded results exist.
- **Auto rotations** assume everyone is healthy and ignore rookies. Review the scenario minutes for any team you act on.
- **Fees** (`fees.py`), per order:
  - Kalshi: 0.07 × C × P × (1 − P), rounded up to the cent; resting orders on player points, rebounds and assists pay no maker fee. Accounts held directly with Kalshi may be charged on a finer $0.0001 grid, so check one real fill.
  - Polymarket US: 0.0695 × C × P × (1 − P), rounded to the cent.
- **Players who don't play** aren't voids. Kalshi settles their markets at a "fair price" the exchange sets (Paul George's preseason 20+ settled at 21c), and Polymarket US settles at the last fair market price. A position bought far from that value loses on a scratch.
- **Polymarket US listed NBA player props on Oct 19** for the three opening games: 96 "N+ points" markets in 5-point steps. Only 38 had a two-sided book (median spread 17.5c, vs 14.5c on Kalshi's 70 two-sided markets), and none had depth yet. Rebounds and assists ladders (steps of 1-2) came with them. Kalshi had 75 rebounds and 68 assists markets up for the same three games. Both venues are read at every checkpoint.

## Layout

| Folder | What's in it |
|---|---|
| `cold_start_usage/` | The package (module map in `HANDOFF.md` section 5) |
| `data/` | Inputs, the catalog outputs and the roster sources. The DuckDB file and raw cache are git-ignored. |
| `bets/` | The bet journal, committed: every ticket, fill and result by day (`cli journal`; see [`bets/README.md`](bets/README.md)) |
| `docs/` | Architecture diagrams, catalog, board snapshot, venue and scaling notes |
| `v0/` | The reference implementation |
| `examples/` | Synthetic payloads |
| `reports/` | Generated outputs (git-ignored) |
