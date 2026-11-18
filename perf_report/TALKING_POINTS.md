# Talking points: 20-minute recruiter call

Every number here is in `MODEL_PORTFOLIO.md` with its sample size and interval. Small samples are flagged.

## Say these (6–8 points)

1. **"I build pricing models for event contracts and grade them the way a desk would: against the closing
   price, not by wins and losses."**
2. **"My NBA system prices player props on Kalshi and Polymarket US."** Before every game it reads both order books
   and prices each contract against a sportsbook consensus plus my own projections. It nets out each venue's fee,
   sizes with capped quarter Kelly, and logs every decision before tip-off.
3. **"I paper-traded it from opening night, and the data said no edge, so I didn't scale it."** 79 tickets,
   Oct 20–31: −25% on paper, closing line value about −0.5¢ a contract, and the venue's own price was better
   calibrated than the sportsbooks I benchmarked against. *Small sample (79).*
4. **"What I learned is useful: these venues aren't simply lagging the sportsbooks on player props."** Where I
   disagreed with the venue, the venue's price turned out to be the better forecast. Next, I'd use the venue price as an input, rest limit orders
   instead of paying the spread, and trade only on sportsbook moves the venue hasn't followed yet.
5. **"My college football totals model shows real closing line value."** Across 337 walk-forward picks from 2022 to
   2025, the closing total moved +0.70 points toward my side on average (95% interval +0.46 to +0.93). 57% of
   picks beat the close, and closing line value was positive in all four seasons.
6. **"I'm careful about what the P&L proves."** That backtest made +7.8 units, +2.3% ROI, but with a ±5% standard
   error, which luck could produce. The closing line value is the evidence; the P&L isn't, yet.
7. **"This season it's +0.89 points of closing line value over 65 picks.** The 9 picks I posted publicly before
   kickoff went 7–2." *Small samples.*
8. **"Everything is reproducible."** I rebuilt the football pipeline from scratch and it reproduced all 53 published
   picks exactly. Every metric in my write-up has a script.

## Don't say

- **"Live arbitrage system."** There isn't one in my code. The only arbitrage work is a backtest of Kalshi ladder
  arbitrage, buying YES on one rung and NO on a higher rung for under $1 combined. Checked an hour
  before tip, it found **zero** opportunities across 23,543 markets after fees. If the recruiter brings it up:
  > "Let me correct that: I haven't run a live arbitrage system. I backtested ladder arbitrage on Kalshi's NBA
  > points markets for last season, an hour before tip, and after fees there were no opportunities at all. That's part of why I moved
  > to pricing models."
- **"Automated bets" or "real P&L."** No fills were logged on any venue, so both records are paper or
  backtest. Say "paper-traded" and "backtested".

## Likely questions

**"How do you know it's edge and not luck?"**
> "For P&L alone, I don't, and I'd say that about any few-hundred-bet sample. That's why I track closing line value.
> On the football model, the closing number moved toward my side by 0.70 points a pick over 337 picks. That's 5.8
> standard errors from zero, and it was positive in every season, though only barely in 2024. The close also moves
> about a tenth of a point toward my rating sources for every point they disagree with the early line. The profit,
> +2.3%, is inside what luck could do, so I don't claim it yet. On the NBA side the same test came back *negative*,
> so I concluded there was no edge rather than calling it bad luck."

**"What's your CLV?"**
> "College football: +0.70 points per pick over 337 backtest picks, or about +2 percentage points of win
> probability. It's +0.89 this season over 65 picks, and +2.4 points on the 9 I posted publicly. NBA props on Kalshi
> and Polymarket US: −0.51 cents a contract on 79 paper tickets, median −0.5 cents. That's half the one-cent
> spread: I was paying the spread and the market wasn't moving my way."

**"How did you size positions?"**
> "NBA: quarter Kelly on the expected value after the venue fee. It was capped at 0.5% of bankroll per player-game,
> since a player's points and rebounds ride on the same minutes, 1.5% per game and 3% per slate. The caps counted
> every ticket already sent, so repeated signals couldn't stack. Stakes topped out around $25 a ticket. Football:
> the record is 1 unit flat per pick so the results are comparable; the configured rule for real money is quarter
> Kelly capped at 2% of bankroll."

**"What capacity does the arb have?"**
> "There's no arb strategy to size. The backtest found none after fees. For the NBA pricing strategy I measured
> depth: when a ticket triggered, the median book offered 166 contracts at or better than my limit, and the middle
> half ranged from 22 to 599. Kalshi's median was 192, Polymarket US's 129. Across all 79 tickets that's about
> $48,000 of contracts at the prices I wanted, and my suggested size never exceeded what was offered. So depth
> wasn't the constraint on that strategy; edge was."

**"What would you do differently?"** (if time)
> "Get a small real-money record on the football early-number rule, so I can measure execution against the
> backtest. Post picks the moment the early numbers come out: on one week, 4 of 5 picks were already priced away at
> my book when I posted. On NBA, quote passively instead of crossing the spread."
