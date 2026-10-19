# Cold Start Usage Projection Modeling

Point projections for every NBA player whose role changed this offseason, compared against a sportsbook consensus. These are **cold starts**: the player has no games yet in his new role, so the projection is built from last season's usage and the new roster instead of recent form. Positions are taken only on **Kalshi** and **Polymarket US**, the two prediction markets Rohan can trade. The sportsbooks are used only as the fair-value reference, never as a place to bet. When a venue lists "Giannis 30+ points", the fair price, the most it's worth paying after the venue's fee, and how many contracts to buy are already known.

- **League-wide:** [`docs/CATALOG.md`](docs/CATALOG.md) lists **152 offseason role changes** across 29 teams. They're tagged by usage tier (high / medium / low) and by situation: *arrival* (new team), *vacuum* (a star left, so the remaining players' usage grows) or *squeeze* (a star arrived, so it shrinks).
- **Case studies:** Giannis to Miami and Kawhi to Toronto, with hand-reviewed minutes.
- **The waiting list:** [`docs/BOARD.md`](docs/BOARD.md) shows the thesis, projection and fair "N+ points" prices for each situation, and fills in the market as lines post. There's also an interactive version: [Offseason Usage Board](https://claude.ai/artifact/PrSUHQ8ouReBWT3E3ybbGX).

Research only: this tool doesn't connect to any venue account and doesn't place orders. It prints limit-order tickets that you enter by hand. Every projection, venue price and decision is logged before tip and graded afterwards at the venue's own settlement, with CLV and calibration. See `HANDOFF.md` for the spec, rules and open decisions.

## Setup

```bash
pip install -r requirements.txt          # Python 3.11+
export SPORTS_ODDS_API_KEY=...           # or put it in .env (git-ignored); never commit it
export COLD_START_BANKROLL_USD=1000     # optional: turns on suggested contract counts (never read from any account)
python -m pytest -q                      # 147 offline tests
```

## Opening Night plan: cron goes live before Tue 10/20

The job is installed on a local machine **before Opening Night (Tuesday, October 20, 2026; first tip 3:00 PM ET)**, so the first snapshot history starts with the first tip of the season. It runs every 5 minutes:

- **Sportsbooks** (metered): calls SportsGameOdds only when a game reaches a new checkpoint (T-6h, T-2h, T-60m, T-15m). Each day's slate is fetched once.
- **Venues** (free): reads Kalshi and Polymarket US at T-6h, T-2h, T-60m, T-15m and T-5m, decides every contract, and logs prices and decisions. T-5m is the venue close used for CLV. This step runs even if the sportsbook step fails (budget stop, missing key).
- **Projections**: a game with none logged gets full-strength / auto-rotation projections automatically; your `project --scenario` after the injury report replaces them.

```
*/5 * * * * cd ~/NBA_RFQ_2026_Models && python -m cold_start_usage.cli snapshot --due --with-signals --with-venues --with-projections >> data/cron.log 2>&1
```

Before the first game day:

```bash
python -m cold_start_usage.cli usage                 # objects used / left (this call is free)
python -m cold_start_usage.cli catalog               # rebuild the league-wide catalog (no API calls)
python -m cold_start_usage.cli board --docs          # refresh the waiting list
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
python -m cold_start_usage.cli board                 # the waiting list: READY only when a venue price clears the bar
python -m cold_start_usage.cli watchlist             # sportsbook leans next to what the venues list (not actionable)
```

The next morning: `grade --date YYYY-MM-DD` (venue settlements, P&L at the price paid, venue CLV; add `--venues-only` to skip the metered results call), and weekly: `report`.

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
| Odds and results | SportsGameOdds API (licensed, free Amateur plan) | 9 books on this key; 3 post player points. No prediction markets on this plan. |
| Prediction-market prices | Kalshi (`api.elections.kalshi.com`) and Polymarket US (`gateway.polymarket.us`) public market-data APIs: read-only, no key | What each venue lists, its fees and its settlement rules: [`docs/VENUES.md`](docs/VENUES.md). The international polymarket.com book is read only as a reference price (US persons can't open positions there). |
| Backtest archive | Kalshi `/historical/...`: every 2025-26 player-points ladder, result and 1-minute candles | `cli history` downloads it into `data/history/` (git-ignored). It's resumable, in random game order, so a partial download is a season-wide sample; the full download takes ~7 hours at the public rate limit. `cli backtest --docs` writes [`docs/BACKTEST.md`](docs/BACKTEST.md); the April-onward holdout stays sealed until `--reveal-holdout`. |
| 2025-26 player lines (all 30 teams) | StatMuse team pages, one source URL per row | Every row is checked against its season totals. |
| 2026-27 rosters | Manual overrides > NBA.com offseason tracker > SportsGameOdds `/players` > last season's team | SportsGameOdds has gaps (Curry, Butler and Horford show no team; Klay was stale), so it isn't trusted alone. Confirmed corrections go in `data/roster_overrides_2026_27.csv`. |
| Team 3-point volume and accuracy (spacing) | StatMuse team pages | |

Basketball-Reference isn't used: its terms bar using site data "to create any database", which an automated pull here would do. NBA.com's statistics terms bar gambling-related use. See `HANDOFF.md` section 4b.

How the data moves from source to signal, with diagrams: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

What the free plan can't do, and the paid feed options, are noted in [`docs/SCALING.md`](docs/SCALING.md).

## How a venue contract becomes actionable

`decision.py` is the only code that can call a contract actionable. It works out one fair price per player-game, leaning on the market: the sportsbook consensus mean, moved 20% toward the model while they're within 0.75 SD of each other. Each contract is priced at the lower of two SD models. A Kalshi rung or Polymarket US market is then actionable only if all of these hold:

1. The game hasn't tipped, the player isn't listed out, and the consensus is fresh (2+ books, no quote older than 30 min, not newer than the venue quote).
2. The rung isn't a tail: the market puts 10-90% on it.
3. The edge after the venue's fee is at least 4pp (5pp with only 2 books), the sportsbook market alone isn't against it, and it's below the 15pp "check inputs" cap.
4. At least 10 contracts are offered at or under the max price.

It's one pick per player-game, sized at quarter Kelly, capped at 0.5% of bankroll per bet, 1.5% per game and 3% per slate while ungraded. The caps count your logged fills and the live picks from earlier scans, so following every ticket can't stack past them, and a player-game you already hold gets no new pick. Each contract's cost is walked up the order book (average price plus the fee at the real order size). The limit price never exceeds what the sportsbook market alone says the contract is worth. Questionable players and thin books show as `watch`.

## Rules the code enforces

- **Venues:** only Kalshi and Polymarket US are actionable; anything else is refused at write time. No code path can place an order: venue modules make public GETs only, and a test checks the source for order, portfolio and key usage.
- **Book allowlist** (`config.py`): reference sportsbooks build the consensus, SportsGameOdds-labelled prediction markets are stored but never enter it, and DFS apps are logged as unpriced. Any other book is dropped at request time, at parse time and at write time.
- SportsGameOdds' precomputed consensus fields are dropped at parse time.
- Tables are append-only, and nothing is logged for a game that has already tipped. Venue prices and decisions stamped at or after tip are refused by storage itself: Kalshi markets keep trading in-game, so the tip always comes from the schedule.
- Budget guard: the hard stop is 2,200 objects/month. It checks usage before every billable request and fails closed. Failed requests count too.
- The API key is sent only as a header and never printed.

## Before trusting a signal

- **The model leans against stars.** It ignores star staggering, so stars keep more usage than it projects. On opening night's real lines it has Tatum at 21 vs the market's 26.5. Edges above 15pp are logged as `abstain` ("sanity cap"). Grade first.
- **Auto rotations** assume everyone is healthy and ignore rookies. Review the scenario minutes for any team you act on.
- **Fees** (`fees.py`), per order:
  - Kalshi: 0.07 × C × P × (1 − P), rounded up to the cent; resting orders on player points pay no maker fee. Accounts held directly with Kalshi may be charged on a finer $0.0001 grid, so check one real fill.
  - Polymarket US: 0.0695 × C × P × (1 − P), rounded to the cent.
- **Players who don't play** aren't voids. Kalshi settles their markets at a "fair price" the exchange sets (Paul George's preseason 20+ settled at 21c), and Polymarket US settles at the last fair market price. A position bought far from that value loses on a scratch.
- **Polymarket US had no NBA player props** for the opening slate. It lists them for the WNBA, so they may appear close to tip; the reader picks them up when they do. Until then, Kalshi is the only venue with prices.

## Layout

| Folder | What's in it |
|---|---|
| `cold_start_usage/` | The package (module map in `HANDOFF.md` section 5) |
| `data/` | Inputs, the catalog outputs and the roster sources. The DuckDB file and raw cache are git-ignored. |
| `docs/` | Architecture diagrams, catalog, board snapshot, venue and scaling notes |
| `v0/` | The reference implementation |
| `examples/` | Synthetic payloads |
| `reports/` | Generated outputs (git-ignored) |
