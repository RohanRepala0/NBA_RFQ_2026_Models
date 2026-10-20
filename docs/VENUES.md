# Venues: where positions can be taken, and how this project reads them

Rohan can trade on two venues: **Kalshi** and **Polymarket US**. Sportsbooks are used only as the fair-value reference. The project only ever **reads** public market data: there is no wallet, key, account or order code anywhere (hard rule 4), and positions are entered by hand from `cli tickets`.

| | Kalshi | Polymarket US | polymarket.com (international) |
|---|---|---|---|
| Who | KalshiEX LLC, a CFTC-registered exchange (DCM) | QCX LLC, a CFTC-regulated exchange (DCM and DCO) | Offshore exchange |
| Can a US resident open positions? | Yes, except in states where sports contracts are blocked or geofenced. Confirm in the app. | Yes, except in some states (Nevada is out; reports differ on others). Confirm in the app. | **No.** The US is close-only ("can close existing positions but cannot open new ones"). |
| Role here | Actionable | Actionable | Reference price only, never actionable |
| Public market data | `api.elections.kalshi.com/trade-api/v2`, no key | `gateway.polymarket.us`, no key | Gamma + CLOB, no key |
| NBA player props read | Series `KXNBAPTS` ("N+ points", steps of 5: 10+, 15+, ...), `KXNBAREB` ("N+ rebounds") and `KXNBAAST` ("N+ assists"), the last two in steps of 1-2 (2+, 4+, 6+, ...), 3-5 rungs per player | `basketball_player_points`, `basketball_player_rebounds` and `basketball_player_assists` "N+" ladders. NBA ones appeared on Oct 19 for the opening games: points in steps of 5 (5+, 10+, ...), rebounds and assists in steps of 1-2. | "Points O/U X.5" markets (points only) |
| Taker fee | 0.07 × C × P × (1 − P), rounded up to the cent per order | 0.0695 × C × P × (1 − P), rounded to the cent (half to even) | 0.05 × C × P × (1 − P) |
| Maker fee | 0 on `KXNBAPTS`, `KXNBAREB` and `KXNBAAST` (fee type "quadratic", multiplier 1) | 0 (no maker rebate at tier 1) | 0 |
| Player doesn't play | Settles at a "fair price" set by the exchange | Settles at the last fair market price | Resolves NO |
| Overtime | Counts | Counts | Counts |
| Reader | `kalshi.py` | `polymarket_us.py` | `polymarket.py` |

## Kalshi

- **Events and tickers.** One event per game and series, with the away team first and the ET date: `KXNBAPTS-26OCT20BOSDET` is Celtics at Pistons. Markets look like `KXNBAPTS-26OCT20BOSDET-BOSDWHITE9-25`, titled "Derrick White: 25+ points", with `floor_strike` 24.5 (YES if he scores more than 24.5). The archive also uses the title form "Tyler Herro records 30+ points". The reader therefore takes the rung from `floor_strike` and checks the title against it. Unparseable markets are logged with the reason, never dropped.
- **Rebounds and assists** are separate series with the same shape: `KXNBAREB-26OCT20BOSDET-DETATHOMPSON9-8` is "Ausar Thompson: 8+ rebounds" (`floor_strike` 7.5), and `KXNBAAST-...` reads "Cade Cunningham: 10+ assists". The stat comes from the ticker's series prefix, and the title's stat word must agree with it. A mismatch, or a series the project doesn't read, is logged as a parse error. Each series is one market-list read; if one fails, the others are still decided.
- **Other prop series** exist (threes `KXNBA3PT`, steals, blocks, points + rebounds + assists, double-doubles) and aren't used yet.
- **Prices** are dollar strings (`yes_ask_dollars`). Sizes are fixed-point strings (`yes_ask_size_fp`, `volume_fp`); the old integer-cent fields and `volume` are gone.
- **The order book holds bids only.** The YES ask is 1 − the best NO bid, with that bid's size. Depth for many markets comes from one call to `GET /markets/orderbooks?tickers=...` (up to 100 at a time).
- **Timing.** The Oct 20 ladders opened on Oct 16, about 4 days before tip; preseason ladders opened 3-8 hours ahead. `close_time` is tip + 48 hours and markets trade in-game, so the tip comes from the schedule, never from `close_time`. `occurrence_datetime` is the scheduled tip + 3 hours.
- **Fees.** The series reports `fee_type` "quadratic" and `fee_multiplier` 1, with no fee changes on record. Fees accumulate per order. The official schedule PDF was unreachable, so the round-up-to-the-cent rule comes from secondary sources. Kalshi's rounding docs also say accounts held directly with Kalshi are charged on a $0.0001 grid. The code keeps the conservative cent rounding (`config.VENUE_FEES`); check it against one real fill.
- **Rate limits.** Unauthenticated limits aren't documented, and HTTP 429 (with no Retry-After header) has come after short bursts and sometimes at one call every few seconds. Readers go at most one call a second and back off 30 seconds or more.
- **Players who don't play.** Their markets settle "scalar" at an exchange-chosen fair price, which isn't the last trade. On Oct 8 Paul George's 10+/15+/20+/25+ rungs settled at 0.64 / 0.39 / 0.21 / 0.09 while his 10+ last traded at 0.07.

## Polymarket US

- **Public reads only:**
  - `GET /v1/events/slug/{slug}` returns the full event, props included. Since Oct 15 the list endpoints return only each game's main market.
  - `/v1/markets/{slug}/book` returns the order book.
  - `/v1/markets/{slug}/settlement` returns the result.
- **The host is never called.** `api.polymarket.us` is the authenticated trading host.
- **Game slugs** use US team codes (`nba-ny-sa-...`). The docs say slugs aren't a stable contract, so the reader falls back to matching teams and start date in the league's event list.
- **Props** read "Will Veronica Burton record at least 10 points ...?" with `line` 10 (= 10 or more); YES is the `long` side, and each side carries the player's team. Rebounds read "... record at least 10 total rebounds ..." and assists "... record at least 5 assists ...". The stat comes from `sportsMarketType` (`basketball_player_points` / `_rebounds` / `_assists`), and a question whose stat word disagrees with it is a parse error. The reader trusts the type and the numeric line over any title text. Other types (threes, steals, blocks, team and game markets) aren't read.
- **The book** lists `offers` (YES asks) and `bids`; a bid at p is a NO offer at 1 − p.
- **Fees** come from `feeCoefficient` (0.0695).
- **Rate limit:** 20 requests a second per IP for the public gateway.
- **Maintenance:** every Thursday 6-8am ET the API returns 503 and resting orders are cancelled.
- **Props are listed close to game time.** WNBA props appeared about 36 hours before tip and NFL props about 4 days before. The venue step re-reads each game at every checkpoint.

## International polymarket.com (reference only)

Each game is a Gamma event (`nba-bos-det-2026-10-20`) with "Points O/U X.5" markets. Only points are read (it's a reference price). The rules are:
- **Fees:** come from each market's `feeSchedule` (0.05, `sports_fees_v3`). The legacy `takerBaseFee` is ignored; an unknown schedule is refused rather than guessed.
- **Tokens:** mapped by their outcome labels, never by position.
- **Who can trade:** US persons can't open positions, so these prices are logged as `polymarket_intl` with the decision `reference`.

## How a price becomes a decision

See "How a venue contract becomes actionable" in the README and `cold_start_usage/decision.py`. Every parsed market produces two logged rows (YES and NO) with its stat, a decision and a reason, at every checkpoint. A rebounds contract is priced only against the rebounds consensus and projection (`distributions.py` has the count model), never against points. `cli tickets` turns the actionable ones into limit orders, and `cli grade` settles them at the venue's own result.

## What was listed on Oct 18

- **Kalshi:** 86 `KXNBAPTS` markets across the three Oct 20 games, about 7-9 players per game.
  - The median spread was 12c; only 8 rungs were within 2c, and 36 of 86 had no volume yet.
  - Liquidity was concentrated: LeBron's 15+ and 20+ rungs made up about 63k of the slate's 70k contracts traded.
  - No Oct 21 ladders were up yet.
- **Polymarket US:** no NBA player props on Oct 18; the 14 opening-week games listed only moneylines, spreads and totals. On Oct 19 it listed 96 points markets for the three Oct 20 games. 38 were two-sided, with a median spread of 17.5c (Kalshi's 70 two-sided markets: 14.5c). All parsed and mapped to the rosters, except two players not yet on the stored sportsbook roster.
- **polymarket.com:** 54 points markets across 9 games, only 6 with a real two-sided quote.

On Oct 19 Kalshi also had 75 `KXNBAREB` and 68 `KXNBAAST` markets across the three Oct 20 games, and Polymarket US carried rebounds and assists ladders on the same events as its points markets. The parsers read all of them; none raised a parse error.

## Out of scope

Novig, ProphetX, Sporttrade, Smarkets, Betfair and Matchbook: Rohan doesn't trade on them, and none of them offers a public, keyless data API that this project would use.
