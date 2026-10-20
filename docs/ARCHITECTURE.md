# Data architecture

Three layers:

- **Sources**, all read-only.
- **One append-only DuckDB log.** Every number the project relies on is written here before the game it concerns tips.
- **Outputs**, rebuilt from that log on demand.

Nothing flows back out: no venue account, no order endpoint, no write to any source.

## End to end

```mermaid
flowchart LR
    subgraph SRC["Sources (read-only)"]
        direction TB
        SGO["SportsGameOdds API<br/>/events · /players · /account/usage"]
        STAT["StatMuse team pages<br/>2025-26 lines · team 3PT"]
        MOVES["NBA.com offseason tracker<br/>+ roster overrides"]
        KAL["Kalshi public API<br/>KXNBAPTS · KXNBAREB · KXNBAAST<br/>ladders · books"]
        PMUS["Polymarket US gateway<br/>points · rebounds · assists props · books"]
        PMI["polymarket.com<br/>reference price only"]
    end

    subgraph GATE["Ingest gate"]
        direction TB
        BUDGET{"Budget guard<br/>2,200 objects/mo<br/>fails closed"}
        ALLOW{"Book allowlist<br/>request · parse · write"}
        RAW[("data/raw/<br/>filtered JSON cache")]
    end

    subgraph LOG["DuckDB log, append-only"]
        direction TB
        MKT[("events · event_players<br/>odds_snapshots · books_seen")]
        PROJ[("projections")]
        SIGT[("signals")]
        VS[("venue_snapshots<br/>venue_signals")]
        TIX[("tickets<br/>venue_settlements")]
        RES[("results")]
        LEDGER[("api_calls<br/>object ledger")]
    end

    subgraph MODEL["Model layer"]
        direction TB
        CAT["catalog.py<br/>roster precedence ·<br/>offseason effect · tiers"]
        USG["usage_model.py + spacing.py<br/>usage squeeze per scenario ·<br/>rebound / assist budgets"]
        CONS["consensus.py<br/>per stat: no-vig · weighted<br/>median · abstain rules"]
        SIG["signals.py<br/>leans vs the books"]
        DEC["decision.py + distributions.py<br/>market-leaning blend · gates ·<br/>one pick per stat · capped Kelly"]
    end

    subgraph OUT["Outputs"]
        direction TB
        CATMD["docs/CATALOG.md<br/>data/catalog/usage_tiers/"]
        BOARD["board.py → docs/BOARD.md<br/>READY only from a venue"]
        TICK["tickets → limit orders<br/>entered by hand"]
        GRADE["grade.py · report.py<br/>venue P&L · CLV · calibration"]
    end

    SGO --> BUDGET --> ALLOW --> RAW --> MKT
    BUDGET -.-> LEDGER
    STAT --> CAT
    MOVES --> CAT
    SGO -. "/players rosters" .-> CAT
    CAT --> CATMD
    CAT -- "scenarios/auto/" --> USG
    MKT --> CONS
    USG --> PROJ
    PROJ --> SIG
    CONS --> SIG
    SIG --> SIGT
    KAL --> DEC
    PMUS --> DEC
    PMI -. "reference" .-> DEC
    CONS --> DEC
    PROJ --> DEC
    DEC --> VS
    VS --> BOARD
    CAT --> BOARD
    VS --> TICK
    TICK -. "fill (by hand)" .-> TIX
    KAL -- "settlements" --> TIX
    PMUS -- "settlements" --> TIX
    SGO -- "final scores" --> RES
    SIGT --> GRADE
    RES --> GRADE
    VS --> GRADE
    TIX --> GRADE
```

Arrows into the log only append rows. Arrows out of it are reads, limited to `SELECT` by `Storage.query`.

## The three gates on sportsbook data

Every SportsGameOdds response passes the same checks in order. Anything that fails is dropped before it can reach a table.

```mermaid
flowchart TB
    REQ["Request planned<br/>(slate, checkpoint, or results)"] --> B{"/account/usage (free):<br/>objects left under<br/>the 2,200 hard stop?"}
    B -- no --> STOP["Refuse, no call made<br/>(also when usage can't be read)"]
    B -- yes --> F["Capped at what's left;<br/>filtered to books discovered<br/>on this key (books.json)"]
    F --> CALL["GET /events<br/>x-api-key header only"]
    CALL --> L["api_calls row<br/>(failed calls count as 1 object)"]
    CALL --> P{"Parse: book on the<br/>allowlist?"}
    P -- no --> DROP["Dropped, counted as off-list"]
    P -- yes --> ROLE["Tagged by role<br/>reference · target venue · unpriced"]
    ROLE --> PRE["SportsGameOdds' own consensus<br/>fields stripped"]
    PRE --> W{"Write: assert_allowed_books<br/>on every book column"}
    W -- fail --> RAISE["Raise, nothing written"]
    W -- pass --> SNAP[("odds_snapshots")]
```

Only **reference** books build the consensus. Prediction markets that SportsGameOdds labels as targets are stored next to it but never enter it (this plan carries none). DFS apps are logged as unpriced. Kalshi and Polymarket US prices come from the venues' own public APIs, through the venue path below, and never touch the SportsGameOdds client or its budget.

## The venue decision path

Every Kalshi and Polymarket US contract side goes through the same gates in `decision.py`, against the consensus and projection of its own stat (points, rebounds or assists). The first gate that fails becomes the logged reason. Every side is logged, so nothing silently drops out.

```mermaid
flowchart TB
    Q["Venue quote<br/>(read at T-6h · T-2h · T-60m · T-15m · T-5m)"] --> V{"Kalshi or<br/>Polymarket US?"}
    V -- no --> REF["reference<br/>(polymarket.com)"]
    V -- yes --> T{"Before tip?<br/>Parsed? On this game's roster?"}
    T -- no --> AB1["abstain"]
    T -- yes --> S{"Player out?"}
    S -- yes --> AB2["abstain"]
    S -- no --> C{"Fresh consensus,<br/>2+ books, no leak?"}
    C -- no --> AB3["abstain"]
    C -- yes --> TL{"Market P(YES)<br/>between 10% and 90%?"}
    TL -- no --> AB4["abstain: tail rung"]
    TL -- yes --> EV{"EV after fee >= 4pp,<br/>market EV >= 0,<br/>market EV <= 15pp?"}
    EV -- no --> AB5["abstain: no edge /<br/>model-only / check inputs"]
    EV -- yes --> Z{"Questionable?<br/>10+ contracts at<br/>the max price?"}
    Z -- "questionable or thin" --> W["watch"]
    Z -- ok --> A["actionable"]
    A --> P["one pick per player-game and stat ·<br/>quarter Kelly, 0.5% per player-game<br/>across stats / 1.5% / 3% caps"]
    P --> TK["ticket: venue · market · side ·<br/>limit price · quantity · cancel-by"]
```

## A game day, end to end

The cron entry runs every 5 minutes (see the README). It has two independent parts:
- the metered SportsGameOdds step, which calls only at a new checkpoint, so a typical slate costs a handful of objects;
- the free venue step, which runs even if the sportsbook step fails.

```mermaid
sequenceDiagram
    autonumber
    participant Cron as cron (every 5 min)
    participant CLI as cli.py
    participant SGO as SportsGameOdds
    participant Venues as Kalshi / Polymarket US
    participant DB as DuckDB log
    participant You as Rohan

    Cron->>CLI: snapshot --due --with-signals --with-venues --with-projections
    CLI->>SGO: slate for the ET day (once)
    SGO-->>DB: events, event_players
    loop each game at T-6h, T-2h, T-60m, T-15m
        CLI->>SGO: player points, rebounds, assists for that game (metered, 1 object)
        SGO-->>DB: odds_snapshots (allowlisted books only)
        CLI->>DB: auto projections if none current · leans at T-60m / T-15m
    end
    loop each game at T-6h, T-2h, T-60m, T-15m, T-5m (free)
        CLI->>Venues: markets + order books (public GETs)
        Venues-->>DB: venue_snapshots
        CLI->>DB: venue_signals (every side: actionable / watch / abstain)
    end
    You->>CLI: project --scenario TEAM=name (after the injury report)
    You->>CLI: tickets
    CLI-->>You: venue · market · side · limit · quantity · cancel-by
    Note over Venues,You: You enter the limit orders in the app. No code path places an order.
    You->>CLI: fill --signal-id ... --contracts --price
    CLI->>DB: tickets
    You->>CLI: grade --date (next morning)
    CLI->>Venues: settlements (1, 0, or a fair price)
    CLI->>SGO: final scores for the slate
    CLI-->>You: venue P&L, venue CLV, model vs books CLV, calibration
```

## Catalog build (no API calls)

`cli catalog` turns last season's lines and this offseason's moves into the league-wide list of role changes. The same code runs twice: once on the 2026-27 rosters, and once on a counterfactual where nobody moved. The difference between the two is the offseason effect, so a team's normal rotation churn never shows up as a role change.

```mermaid
flowchart LR
    SPLITS["data/league_2025_26/*.csv<br/>StatMuse lines, ≥100 min"] --> PT["players table<br/>usg · min · ppg · rpg · apg"]
    OVR["roster_overrides_2026_27.csv"] --> RR{"Roster precedence<br/>overrides > NBA.com moves ><br/>SGO /players > last season"}
    MV["offseason_moves_2026.csv"] --> RR
    SGOR["rosters_2026_27_sgo.json"] --> RR
    RR --> CONF["roster_conflicts.csv"]
    RR --> NEW["2026-27 rosters"]
    PT --> NEW
    PT --> NOMOVE["No-moves counterfactual<br/>(listed moves reversed)"]
    NEW --> AM1["auto_minutes + usage model"]
    NOMOVE --> AM2["auto_minutes + usage model"]
    AM1 --> DIFF["Offseason effect<br/>= new minus no-moves"]
    AM2 --> DIFF
    DIFF --> TAG["Situation: arrival · vacuum · squeeze<br/>Tier: high ≥25 · medium ≥18 · low"]
    TAG --> OUTS["data/catalog/players.csv · teams.csv<br/>usage_tiers/TIER/SITUATION.csv<br/>scenarios/auto/TEAM.csv · docs/CATALOG.md"]
```

Hand-reviewed scenarios in `cold_start_usage/scenarios/` (Miami, Toronto) take precedence over `scenarios/auto/`.

## Tables

| Table | Written by | Read by | One row is |
|---|---|---|---|
| `api_calls` | `sgo_client` | budget guard, `usage` | one billable request and its object count |
| `events` | `ingest` | everything game-scoped | one game at one snapshot |
| `event_players` | `ingest` | `project` | one rostered player and injury status |
| `odds_snapshots` | `ingest` | `consensus` | one book's over/under on one player and stat at one checkpoint |
| `books_seen` | `ingest` | `books`, allowlist audit | one book seen on one call, with its role |
| `projections` | `project`, cron (`--with-projections`) | `signals`, `venues`, `grade` | one player's mean and SD for one stat under one scenario, before tip (NULL mean: that stat had no inputs) |
| `signals` | `signals` | `watchlist`, `grade`, `report` | one model-vs-books comparison: a `paper` lean or `abstain` with a reason (never actionable) |
| `venue_snapshots` | `venues` (cron, `venues`, `board`) | `grade` (venue close for CLV) | one venue market's bid, ask and sizes at one checkpoint, with its stat; refused at or after tip |
| `venue_signals` | `venues` via `decision` | `board`, `tickets`, `watchlist`, `grade` | one contract side's decision and reason, with its stat, fair prices, EV, max price, size and a config hash; refused at or after tip |
| `tickets` | `fill` | `grade` | one fill entered by hand on a venue |
| `venue_settlements` | `grade` | `grade` | a market's settlement: 1, 0, or a fair price |
| `results` | `grade` | `grade`, `report` | one player's actual points, rebounds and assists plus the closing points consensus |

The `stat` column on odds, projections, signals and venue rows was added to existing tables in place; rows logged before it are NULL there, and every read treats NULL as points. Every timestamp is UTC. `--now` (simulated time) is refused on the default database, so the real log can't be back-dated.
