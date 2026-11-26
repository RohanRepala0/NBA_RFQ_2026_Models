# CFB outputs: where these files came from

`2026/`, `record_2026.json`, `record_2026.md`, `totals_picks_2026_w12.csv` and `backtest_totals_2026-11-18.md` are
copied from a run of `RohanRepala0/CollegeFootballRatings2026` (default branch `claude/bold-ptolemy-99yocz`, commit
`850efc1`) on **Tue Nov 17, 2026, 9:35 PM ET** (2026-11-18T02:35Z), with a fresh DuckDB built from public sources:

```bash
uv run cfb init-db
uv run cfb backfill-cfbd                                   # CFBD games, lines, Elo: 2014-2026 (no 2020), 25 API calls
for s in 2021 2022 2023 2024 2025 2026; do uv run cfb ingest-sp --season $s --download; done
for s in 2022 2023 2024 2025 2026; do uv run cfb ingest-bcf --season $s --fresh; done
uv run cfb fit
uv run cfb record --season 2026
uv run cfb picks --season 2026 --week 12
uv run cfb publish --season 2026 --week 8 --week 9 --week 10 --week 11 --week 12
uv run cfb backtest-totals
```

Checks:
- The rebuilt record reproduces the committed weeks 1-8 signals exactly: 53 of 53, same game, rule, side and line.
- `cfb backtest-totals` reproduces the committed Oct 21 report (337 signals, 178-154-5, +7.8u). The only differences
  are in the 4th decimal of two distributions that were not selected.
- `games_2022_2026.csv` (from `perf_report/scripts/cfb_export.py`) reproduces `totals.run` (337 signals) and the
  2026 record (65 signals) exactly. The script refuses to write if it doesn't.

What each week is:
- Weeks 1-6: backtest (published before this session, after the games).
- Weeks 7-8: **live**, posted before kickoff (Oct 15 and Oct 21 ET; the git history of the CFB repo shows it).
  This session only filled in week 8's final scores.
- Weeks 9-11: published in this session, after the games: every signal is `backfilled` (backtest), from the
  walk-forward record (model fit on 2021-2025 only; SP+ and BCF projections are each week's pre-game archive).
- Week 12: posted live (`status = posted`) before every listed kickoff. The first is Wed Nov 18, 7:00 PM ET.
  These files are not committed or pushed yet, so nothing outside this session shows when they were posted.
