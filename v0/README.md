# Usage-squeeze model, v0 reference implementation

`usage_model.py` is the original single-file model. It is kept unchanged (apart from
the example in its help text) as the reference that `nba_cold_start/usage_model.py`
must reproduce exactly. `tests/test_v0_regression.py` runs this script on frozen
Miami and Toronto inputs (`tests/fixtures/regression/`) and checks the package
output matches it to within 0.01, with spacing switched off.

**Method.** Five players on the floor use 100% of possessions, so across a game
`sum(USG% x minutes) = 4800`. When a team adds high-usage players, last season's
usage rates no longer fit. The model rescales everyone to fit the budget (stars hold
their share better than role players), then converts new usage and minutes into a
points projection. The same math handles vacated usage (a star sits, so the remaining
players expand).

Run it standalone from a folder holding `players_2025_26.csv` and `scenarios.csv`:
`python usage_model.py` or `python usage_model.py --line "Kawhi Leonard=27.5"`.
