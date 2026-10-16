# Cold Start Usage Projection Modeling

Point projections for every NBA player whose role changed this offseason, compared against a sportsbook consensus. These are **cold starts**: the player has no games yet in his new role, so the projection is built from last season's usage and the new roster instead of recent form. Each disagreement becomes a **pre-market board** entry for prediction markets (Novig, Kalshi, Polymarket) that haven't posted player props yet. When a venue lists "Giannis 30+ points", the fair price and the most it's worth paying are already known.

- **League-wide:** [`docs/CATALOG.md`](docs/CATALOG.md) lists **152 offseason role changes** across 29 teams. They're tagged by usage tier (high / medium / low) and by situation: *arrival* (new team), *vacuum* (a star left, so the remaining players' usage grows) or *squeeze* (a star arrived, so it shrinks).
- **Case studies:** Giannis to Miami and Kawhi to Toronto, with hand-reviewed minutes.
- **The waiting list:** [`docs/BOARD.md`](docs/BOARD.md) shows the thesis, projection and fair "N+ points" prices for each situation, and fills in the market as lines post.

Research only: this tool doesn't connect to any venue account and doesn't place orders. Every projection and signal is logged before tip and graded afterwards with CLV and calibration. See `HANDOFF.md` for the spec, rules and open decisions.

## Setup

```bash
pip install -r requirements.txt          # Python 3.11+
export SPORTS_ODDS_API_KEY=...           # or put it in .env (git-ignored); never commit it
python -m pytest -q                      # 108 offline tests
```

## Opening Night plan: cron goes live before Tue 10/20

The job is installed on a local machine **before Opening Night (Tuesday, October 20, 2026)**, so the first snapshot history starts with the first tip of the season. It runs every 5 minutes and only calls the API when a game reaches a new checkpoint (T-6h, T-2h, T-60m, T-15m). Each day's slate is fetched once.

```
*/5 * * * * cd ~/NBA_RFQ_2026_Models && python -m nba_cold_start.cli snapshot --due --with-signals >> data/cron.log 2>&1
```

Before the first game day:

```bash
python -m nba_cold_start.cli usage                 # objects used / left (this call is free)
python -m nba_cold_start.cli catalog               # rebuild the league-wide catalog (no API calls)
python -m nba_cold_start.cli board --docs          # refresh the waiting list
```

On each game day:

```bash
# ~65 min before tip, after the injury report: confirm or change each team's scenario
python -m nba_cold_start.cli project --scenario MIA=full_strength --scenario TOR=kawhi_out
# cron logs signals at T-60m and T-15m on its own (--with-signals)
python -m nba_cold_start.cli board                 # what's waiting, what's READY vs sportsbooks, and Kalshi rungs once listed
python -m nba_cold_start.cli venues                # Polymarket + Kalshi player-points prices vs consensus and model, with depth
python -m nba_cold_start.cli watchlist             # paper signals as prediction-market contracts with max prices
```

The next morning: `grade --date YYYY-MM-DD`, and weekly: `report`.

Teams without hand-reviewed minutes use the catalog's automatic rotation (`nba_cold_start/scenarios/auto/`). Copy one up to `nba_cold_start/scenarios/` and edit it to make it reviewed.

## Dry run without the API

```bash
DB=/tmp/demo.duckdb
python -m nba_cold_start.cli --db $DB --now 2026-10-21T22:30:00Z snapshot --from-file examples/synthetic_slate_2026-10-21.json
python -m nba_cold_start.cli --db $DB --now 2026-10-21T22:31:00Z project --date 2026-10-21
python -m nba_cold_start.cli --db $DB --now 2026-10-21T22:32:00Z signals --date 2026-10-21
python -m nba_cold_start.cli --db $DB --now 2026-10-21T22:33:00Z board
```

The matchup and player IDs are real; the odds are invented. `--now` only works with a separate `--db`, so the real log can never be back-dated.

## Where the data comes from

| Data | Source | Notes |
|---|---|---|
| Odds and results | SportsGameOdds API (licensed, free Amateur plan) | 9 books on this key; 3 post player points. No prediction markets on this plan. |
| Prediction-market prices | Kalshi and Polymarket public market-data APIs (read-only, no account) | Venue-by-venue access notes in [`docs/VENUES.md`](docs/VENUES.md). Novig, ProphetX and Sporttrade have no public API. |
| 2025-26 player lines (all 30 teams) | StatMuse team pages, one source URL per row | Every row is checked against its season totals. |
| 2026-27 rosters | Manual overrides > NBA.com offseason tracker > SportsGameOdds `/players` > last season's team | SportsGameOdds has gaps (Curry, Butler and Horford show no team; Klay was stale), so it isn't trusted alone. Confirmed corrections go in `data/roster_overrides_2026_27.csv`. |
| Team 3-point volume and accuracy (spacing) | StatMuse team pages | |

Basketball-Reference isn't used: its terms bar using site data "to create any database", which an automated pull here would do. NBA.com's statistics terms bar gambling-related use. See `HANDOFF.md` section 4b.

How the data moves from source to signal, with diagrams: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

What the free plan can't do, and the paid feed options, are noted in [`docs/SCALING.md`](docs/SCALING.md).

## Rules the code enforces

- **Book allowlist** (`config.py`): reference sportsbooks build the consensus, target venues are stored but never enter the consensus, and DFS apps are logged as unpriced. Any other book is dropped at request time, at parse time and at write time.
- SportsGameOdds' precomputed consensus fields are dropped at parse time.
- Tables are append-only, and nothing is logged for a game that has already tipped.
- Budget guard: the hard stop is 2,200 objects/month. It checks usage before every billable request and fails closed. Failed requests count too.
- The API key is sent only as a header and never printed.

## Before trusting a signal

- **The model leans against stars.** It ignores star staggering, so stars keep more usage than it projects. On opening night's real lines it has Tatum at 21 vs the market's 26.5. Edges above 15pp are logged as `abstain` ("sanity cap"). Grade first.
- **Auto rotations** assume everyone is healthy and ignore rookies. Review the scenario minutes for any team you act on.
- **Fees:** 0.07 × P × (1 − P) is Kalshi's published general formula, used as a conservative placeholder for Novig and Polymarket.

## Layout

| Folder | What's in it |
|---|---|
| `nba_cold_start/` | The package (module map in `HANDOFF.md` section 5) |
| `data/` | Inputs, the catalog outputs and the roster sources. The DuckDB file and raw cache are git-ignored. |
| `docs/` | Architecture diagrams, catalog, board snapshot, venue and scaling notes |
| `v0/` | The reference implementation |
| `examples/` | Synthetic payloads |
| `reports/` | Generated outputs (git-ignored) |
