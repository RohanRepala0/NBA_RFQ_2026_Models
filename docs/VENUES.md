# Prediction-market venues: who exposes prices, and how this project reads them

Every venue below was checked for a public, no-account way to read NBA player-points prices. The project only ever **reads** market data: there is no wallet, key, account or order code anywhere (hard rule 4).

| Venue | Public market data | NBA player points | How this project reads it |
|---|---|---|---|
| **Kalshi** | Yes. `GET https://api.elections.kalshi.com/trade-api/v2/markets`, no key | Series `KXNBAPTS` ("NBA Player Points"), plus rebounds, assists, PRA, threes, doubles. Ladders step by 5: "Paul George: 25+ points" (strike 24.5). They have run on preseason games; regular-season ladders weren't open yet at the last check. | `cold_start_usage/kalshi.py`, `cli kalshi`, `cli venues`; the board prices Kalshi rungs directly |
| **Polymarket** | Yes. Gamma API (`/public-search`, `/events`) and the CLOB order book (`/book`), no key | Each game is an event (`nba-bos-det-2026-10-20`) with moneyline, spreads, totals and a few player props: "Jayson Tatum: Points O/U 26.5". Books are thin and fees are on (taker base fee per market). | `cold_start_usage/polymarket.py`, `cli venues` (with order-book depth) |
| **Novig** | No public API found | Yes, in the app | Only through a licensed aggregator (SportsGameOdds carries `novig` on higher plans) |
| **ProphetX** | Partner-only API | Yes | Through an aggregator (SportsGameOdds `prophetexchange`) |
| **Sporttrade** | No public API found | Yes | Through an aggregator (SportsGameOdds `sporttrade`) |
| **Smarkets** | Refuses unauthenticated requests (HTTP 403) | Not checked | – |
| **Betfair Exchange, Matchbook** | Account and app key required | Limited US relevance | Through an aggregator if ever needed |

The single licensed route to the venues without public data is a higher SportsGameOdds plan. It lists `kalshi`, `novig`, `polymarket`, `prophetexchange`, `sporttrade`, `betfairexchange` and `matchbook` as bookmakers, so their prices would arrive in the same snapshots as the sportsbooks. That costs money, so it's Rohan's call (see `docs/SCALING.md`).

## Reading a venue price

`cli venues --date YYYY-MM-DD` takes every player-points price on the slate and prices both sides:

- **Fair (market):** the multi-book sportsbook consensus at that exact line (no-vig, weighted median of implied means).
- **Fair (model):** our projection's probability at that line.
- **Edge:** fair minus (ask + the venue's taker fee). Kalshi: 0.07 × P × (1 − P). Polymarket: the market's base rate × min(P, 1 − P).
- **Verdict:**
  - *market value*: the venue is cheaper than the sportsbook consensus by 4pp or more after fees. No model needed, so this is the more trustworthy kind.
  - *model value only*: only our ungraded projection likes it.
  - *market + model value*: both agree.
- **Size at edge:** contracts on the Polymarket order book at or below the price that still leaves 4pp. A great price with 5 contracts behind it is not a trade.

## First scan (Opening Night, BOS @ DET and OKC @ SAS)

Kalshi had no regular-season player-points ladders open. Polymarket had points markets for four players:

| Player | Contract | Ask | Fee | Fair (market) | Fair (model) | Edge vs market | Size at edge | Verdict |
|---|---|---|---|---|---|---|---|---|
| Shai Gilgeous-Alexander | over 29.5 | 42¢ | 4.2¢ | 52.7¢ | 52.7¢ | +6.5pp | 5 | market + model value |
| Victor Wembanyama | over 26.5 | 48¢ | 4.8¢ | 48.9¢ | 38.2¢ | −3.9pp | 0 | no edge |
| Jayson Tatum | over 26.5 | 53¢ | 4.7¢ | 50.0¢ | 25.3¢ | −7.7pp | 0 | no edge |
| Cade Cunningham | over 24.5 | 54¢ | 4.6¢ | 48.0¢ | 44.3¢ | −10.6pp | 0 | no edge |

The unders were all offered at 87–89¢, far above fair. The one value price had 5 contracts behind it before the book jumped to 55–56¢. That's typical of these early books: the listing exists, but real size arrives closer to tip. That's why `snapshot --due` and `venues` are worth running on a schedule.
