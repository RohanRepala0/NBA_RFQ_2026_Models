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
        KAL["Kalshi market data<br/>series KXNBAPTS"]
        PM["Polymarket<br/>Gamma events · CLOB books"]
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
        VQ[("venue_quotes")]
        RES[("results")]
        LEDGER[("api_calls<br/>object ledger")]
    end

    subgraph MODEL["Model layer"]
        direction TB
        CAT["catalog.py<br/>roster precedence ·<br/>offseason effect · tiers"]
        USG["usage_model.py + spacing.py<br/>usage squeeze per scenario"]
        CONS["consensus.py<br/>no-vig · weighted median ·<br/>abstain rules"]
        SIG["signals.py<br/>edge · 4pp bar · 15pp cap"]
    end

    subgraph OUT["Outputs"]
        direction TB
        CATMD["docs/CATALOG.md<br/>data/catalog/usage_tiers/"]
        BOARD["board.py → docs/BOARD.md<br/>the waiting list"]
        VEN["venues.py →<br/>reports/venues_DATE.csv"]
        WL["watchlist.py →<br/>max prices after fees"]
        GRADE["grade.py · report.py<br/>CLV · Brier · calibration"]
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
    KAL --> VQ
    CAT --> BOARD
    CONS --> BOARD
    VQ --> BOARD
    PM --> VEN
    CONS --> VEN
    PROJ --> VEN
    SIGT --> WL
    SGO -- "final scores" --> RES
    SIGT --> GRADE
    RES --> GRADE
    MKT -- "closing line" --> GRADE
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

Only **reference** books build the consensus. Target venues (Kalshi, Novig, Polymarket) are stored next to the consensus but never enter it. DFS apps are logged as unpriced.

## A game day, end to end

The cron entry runs every 5 minutes (see the README). It calls the API only when a game reaches a new checkpoint, so a typical slate costs a handful of objects.

```mermaid
sequenceDiagram
    autonumber
    participant Cron as cron (every 5 min)
    participant CLI as cli.py
    participant SGO as SportsGameOdds
    participant DB as DuckDB log
    participant Venues as Kalshi / Polymarket
    participant You as Rohan

    Cron->>CLI: snapshot --due --with-signals
    CLI->>SGO: slate for the ET day (once)
    SGO-->>DB: events, event_players
    loop each game at T-6h, T-2h, T-60m, T-15m
        CLI->>SGO: player points for that game
        SGO-->>DB: odds_snapshots (allowlisted books only)
        CLI->>DB: signals at T-60m and T-15m
    end
    You->>CLI: project --scenario TEAM=name (after the injury report)
    CLI->>DB: projections (logged before tip)
    You->>CLI: board / venues / watchlist
    CLI->>Venues: public market data (read-only)
    Venues-->>DB: venue_quotes (Kalshi)
    CLI-->>You: READY / waiting, edge, ROI, size at edge
    Note over CLI,You: Positions are entered by hand on the venue. No code path places an order.
    You->>CLI: grade --date (next morning)
    CLI->>SGO: final scores for the slate
    SGO-->>DB: results + closing consensus
    CLI-->>You: CLV, hit rate, Brier, calibration
```

## Catalog build (no API calls)

`cli catalog` turns last season's lines and this offseason's moves into the league-wide list of role changes. The same code runs twice: once on the 2026-27 rosters, and once on a counterfactual where nobody moved. The difference between the two is the offseason effect, so a team's normal rotation churn never shows up as a role change.

```mermaid
flowchart LR
    SPLITS["data/league_2025_26/*.csv<br/>StatMuse lines, ≥100 min"] --> PT["players table<br/>usg · min · ppg"]
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

Hand-reviewed scenarios in `nba_cold_start/scenarios/` (Miami, Toronto) take precedence over `scenarios/auto/`.

## Tables

| Table | Written by | Read by | One row is |
|---|---|---|---|
| `api_calls` | `sgo_client` | budget guard, `usage` | one billable request and its object count |
| `events` | `ingest` | everything game-scoped | one game at one snapshot |
| `event_players` | `ingest` | `project` | one rostered player and injury status |
| `odds_snapshots` | `ingest` | `consensus` | one book's over/under on one player at one checkpoint |
| `books_seen` | `ingest` | `books`, allowlist audit | one book seen on one call, with its role |
| `projections` | `project` | `signals`, `board`, `venues`, `grade` | one player's mean and SD under one scenario, before tip |
| `signals` | `signals` | `watchlist`, `grade`, `report` | one model-vs-consensus comparison, `paper` or `abstain` with a reason |
| `venue_quotes` | `kalshi`, `board`, `venues` | `board`, `watchlist` | one prediction-market rung's bid and ask at one time |
| `results` | `grade` | `grade`, `report` | one player's actual points plus the closing consensus |

Every timestamp is UTC. `--now` (simulated time) is refused on the default database, so the real log can't be back-dated.
