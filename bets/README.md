# Bet journal

Every bet the system called and every fill Rohan logged, with its result. The decision log (`data/edge_lab.duckdb`) is git-ignored, so this folder is the season's record in git. Everything here except this README is generated. Don't edit it by hand: rebuild it.

Research only. Nothing here places an order. A **ticket** is the system's paper bet. A **fill** is what Rohan entered by hand on Kalshi or Polymarket US and logged with `cli fill` (the database table holding fills is also named `tickets`; in this folder "ticket" always means the paper bet).

## How it's generated

```bash
python -m cold_start_usage.cli grade --date 2026-10-20     # first: stores the venue settlements (free public reads)
python -m cold_start_usage.cli journal --date 2026-10-20   # then: rebuild that day, plus ledger.csv and fills.csv in full
python -m cold_start_usage.cli journal --all               # or every day (also the default with no flag)
```

`journal` only reads the log: it makes no API calls and writes nothing to the database. A contract `grade` hasn't settled yet shows `pending`, and the next `grade` and `journal` fill it in. `--out DIR` writes somewhere else (the default is this folder). The output is deterministic (stable sort order, fixed decimal places, no generated-at stamps), so a rebuild with no new data changes no file, and `git diff` shows only what really changed: a new day, a settlement, a fill.

## Layout

| Path | What's in it |
|---|---|
| `ledger.csv` | The season ledger: one row per ticket, every date, sorted by tip and then first-seen time |
| `fills.csv` | Every fill logged with `cli fill`, corrections included (a replaced fill stays, marked `superseded`) |
| `days/YYYY-MM-DD/tickets.csv` | Every actionable row logged for that slate, at every checkpoint, with re-confirmations flagged |
| `days/YYYY-MM-DD/results.csv` | Each of that slate's tickets graded, plus any fills on it |
| `days/YYYY-MM-DD/summary.md` | The slate, tickets with entry / close / result, totals, CLV by stat, fills by kind, reviewed scenarios, pending items |

A day is the **ET date of the games' tip**. A decision logged late the evening before, for a next-day game, files under the game's day. A day gets a folder once it has a logged venue decision or a fill.

## Conventions

- **Ticket rule.** One ticket per player-game and stat: the first time it was actionable, on whatever contract and venue that was, at that row's ask, all-in cost and suggested size. This is the same rule `grade.venue_graded` uses for paper P&L, and the journal calls it rather than restating it. Points, rebounds and assists on one player are separate tickets.
- **Repeats.** The scan re-decides every contract at each checkpoint (T-6h, T-2h, T-60m, T-15m, T-5m, plus ad hoc reads), so an actionable contract usually shows up several times. `tickets.csv` keeps every row and flags it in the `flag` column:
  - `ticket`: the graded one.
  - `repeat of <signal_id>`: the same venue, ticker and side was already actionable earlier (the id is its first actionable row).
  - `new contract after ticket <signal_id>`: a different contract on a player-stat that already has a ticket (not graded).
- **Money.** Prices are dollars per contract (0.6000 = 60c). `cost` is the all-in price per contract: the ask plus the venue fee at the suggested size. P&L at suggested size = `suggested_contracts` × (value at settlement − `cost`).
- **Settlement.** `result` is the venue's result for the YES contract: `yes`, `no`, `scalar` (a fair price for a player who never took the court) or `pending`. `settlement_value` is what YES paid (1, 0 or the fair price), and a NO ticket is worth 1 − that. `outcome` reads the ticket's own side: `won`, `lost`, `fair price` or `pending`.
- **CLV.** `close_mid` is the venue's last two-sided mid before tip, for the ticket's side (a NO close is 1 − the YES mid). `clv` = `close_mid` − `ask`, as `grade.py` computes it. Positive means the market moved toward the ticket.
- **Hits vs expected.** In `summary.md`, hits are the settled tickets' value summed (a win counts 1, a fair-price settlement its fraction). Expected is the sum of `p_blend` over the same tickets.
- **Times.** Columns ending `_et` are US Eastern, for reading; columns ending `_utc` are UTC (ISO, `Z`), as stored.

### Fill kinds: paper, real, discretionary

| Kind | How it's recorded | Meaning |
|---|---|---|
| `paper` | `fill ... --paper` (writes note `paper`; with `--note x` it writes `paper: x`), or any note starting with `paper` | Tracked as if traded; no money moved |
| `discretionary` | A note starting with `discretionary`, or a fill logged with `--venue/--ticker/--side` (no signal id) on a contract the scan never made actionable | Rohan's own call, not a system ticket |
| `real` | Anything else (normally `fill --signal-id <id>`) | Real money on a system ticket |

A correction (`fill ... --replaces <fill_id>`) with no note of its own keeps the kind of the fill it replaces. A paper fill counts toward the bankroll caps and blocks a new pick on that player-stat, just like a real one, so a paper record follows the same rules as real trading. The fill columns on a ticket's row (`filled_contracts`, `fill_avg_price`, `fill_fees_usd`, `fill_pnl_usd`, `fill_kind`) cover current fills on the ticket's exact venue, ticker and side, at the price paid. When the kinds are mixed, `fill_kind` lists them (`real+paper`). Every fill, on a ticket or not, is in `fills.csv` and in the day's `summary.md`.

## Columns

### `ledger.csv` (one row per ticket)

| Column | Meaning |
|---|---|
| `date_et` | ET slate date (the tip's) |
| `game` | `AWAY @ HOME` |
| `tip_et`, `tip_utc` | Tip time |
| `checkpoint` | Checkpoint tag of the row that became the ticket (`t-6h`, `t-2h`, `t-60m`, `t-15m`, `t-5m`, `adhoc`) |
| `first_seen_et`, `first_seen_utc` | When it was first actionable |
| `venue` | `kalshi` or `polymarket_us` |
| `ticker` | The venue's market ticker or slug |
| `player`, `team`, `stat` | Player, his team, and `points`, `rebounds` or `assists` |
| `contract`, `side` | Label (`25+ YES`, `8+ REB NO`) and side |
| `ask` | Ask on that side when first actionable |
| `limit` | Max price that still kept the edge after fees (the limit to enter) |
| `cost` | All-in cost per contract at the suggested size |
| `suggested_contracts`, `suggested_stake_usd` | Suggested size and its all-in dollars (quarter Kelly under the caps) |
| `p_market` | Fair probability from the sportsbook consensus alone |
| `p_blend` | Fair probability from the market-leaning blend of consensus and model |
| `ev_market`, `ev_blend` | EV per contract after fees on each |
| `n_books` | Books in the consensus |
| `consensus_mean`, `model_mean` | The books' implied mean and the model's projection for the stat |
| `signal_id` | The decision row's id (what `fill --signal-id` takes) |
| `result`, `outcome`, `settlement_value` | See Settlement above |
| `pnl_per_contract` | Value at settlement minus `cost` |
| `pnl_suggested_usd` | P&L at the suggested size |
| `close_mid`, `clv` | See CLV above |
| `filled_contracts`, `fill_avg_price`, `fill_fees_usd`, `fill_pnl_usd`, `fill_kind` | Current fills on this contract (blank if none; P&L blank until settled) |

### `days/YYYY-MM-DD/results.csv`

The day's ledger rows, with the identity, sizing and grading columns above (`tip_et`, `game`, `player`, `team`, `stat`, `contract`, `side`, `venue`, `ticker`, `checkpoint`, `ask`, `cost`, `suggested_contracts`, `suggested_stake_usd`, `p_blend`, `result`, `outcome`, `settlement_value`, `pnl_per_contract`, `pnl_suggested_usd`, `close_mid`, `clv`, the fill columns, `signal_id`).

### `days/YYYY-MM-DD/tickets.csv` (every actionable row)

| Column | Meaning |
|---|---|
| `logged_et`, `logged_utc` | When the decision was logged |
| `checkpoint` | Checkpoint tag of that read |
| `game`, `tip_et`, `venue`, `ticker`, `player`, `team`, `stat`, `contract`, `side` | As in the ledger |
| `bid`, `ask` | Top of book on that side |
| `limit` | Max price |
| `size_at_edge` | Contracts offered at or under the limit |
| `suggested_contracts`, `suggested_stake_usd` | Suggested size at that read |
| `p_market`, `p_blend`, `ev_market`, `ev_blend`, `n_books`, `consensus_mean`, `model_mean` | As in the ledger, at that read |
| `reason` | The decision's reason text |
| `signal_id` | The row's id |
| `flag` | `ticket`, `repeat of <signal_id>` or `new contract after ticket <signal_id>` |

### `fills.csv`

| Column | Meaning |
|---|---|
| `fill_id` | The fill's id (what `--replaces` takes) |
| `date_et` | ET slate date of the contract's game (the fill's own ET date if the game is unknown) |
| `game`, `tip_et`, `player`, `team`, `stat`, `contract` | The contract filled |
| `filled_at_et`, `filled_at_utc` | When it filled (`--filled-at`, else when it was logged) |
| `logged_utc` | When it was logged |
| `venue`, `ticker`, `side` | What was bought |
| `contracts`, `price` | Contracts and average price paid |
| `fees_usd`, `cost_usd` | Fees paid; contracts × price + fees |
| `kind` | `paper`, `real` or `discretionary` (above) |
| `status` | `current`, or `superseded` when a later fill replaced it |
| `replaces`, `superseded_by` | Correction links (fill ids) |
| `signal_id` | The decision it was logged against (blank for a `--ticker` fill) |
| `ticket_signal_id` | The ticket for the same player-game and stat, if there is one |
| `matches_ticket` | `yes` when the fill is on that ticket's exact venue, ticker and side |
| `result`, `settlement_value` | The venue's result (current fills only) |
| `pnl_usd` | contracts × (value − price) − fees, from `grade.fills_graded`; blank while pending or superseded |
| `note` | The fill's note |
