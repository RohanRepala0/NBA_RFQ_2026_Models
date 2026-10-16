# Scaling ingestion

## What runs today

- **Polling:** a cron job polls the SportsGameOdds REST API every 5 minutes on the free Amateur plan.
  - It snapshots each game at T-6h, T-2h, T-60m and T-15m.
  - It stays under a 2,200-object monthly budget.
  - Odds refresh about every 10 minutes upstream.
- **Why that's enough here:** pre-game player props move slowly hours before tip, so this catches the open, the moves, and a clean close for CLV grading.
- **What it can't do:**
  - react to a line move within seconds;
  - see a prediction market list a prop the moment it happens;
  - backfill history (the free plan has none, which is why every snapshot is kept).

## The upgrade path (paid feeds)

The paid tiers and commercial odds feeds remove those limits.
- **SportsGameOdds' own higher plans:** sub-minute updates and historical odds on Pro, real-time WebSocket streaming on AllStar.
- **Other commercial low-latency odds APIs:** these exist too.
