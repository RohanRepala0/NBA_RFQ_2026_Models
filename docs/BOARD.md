# Pre-market board: role changes waiting on prediction markets

Each row is a player whose usage should move this season. **Fair** prices are what our
projection says an "N+ points" YES contract is worth, in cents. Once a sportsbook line
posts, the status shows the gap to the market consensus; `READY` rows clear the 4pp
threshold, and **max** is the most to pay after a 0.07 x P x (1-P) taker fee.

## How many situations

| tier (2025-26 usage) | arrival | vacuum | squeeze | steady | total |
|---|---|---|---|---|---|
| high | 10 | 7 | 13 | 28 | 58 |
| medium | 34 | 14 | 23 | 56 | 127 |
| low | 19 | 16 | 16 | 55 | 106 |

## High usage (30)

| player | team | situation | thesis | proj (25-26) | fair ladder | status |
|---|---|---|---|---|---|---|
| Jayson Tatum | BOS | vacuum | Jaylen Brown (36.1%), Nikola Vučević (21.4%) gone; usage 30.0 last season, 30.6 projected, offseason effect +3.1 | 22.1 (21.8) | 15+ 87c  20+ 65c  25+ 36c | line up: edge 24.7pp > 15.0pp sanity cap: check inputs - 27+ NO max 69.0c |
| Darius Garland | LAC | vacuum | Kawhi Leonard (33.4%), Bennedict Mathurin (25.1%), John Collins (19.5%) gone; usage 27.5 last season, 29.2 projected, offseason effect +3.0 | 19.8 (18.8) | 15+ 81c  20+ 52c  25+ 22c | waiting for a line - nan max nanc |
| Cooper Flagg | DAL | vacuum | Brandon Williams (24.9%), Klay Thompson (22.8%), Khris Middleton (20.6%) gone; usage 26.9 last season, 28.4 projected, offseason effect +2.1 | 22.1 (21.0) | 15+ 87c  20+ 65c  25+ 36c | waiting for a line - nan max nanc |
| Cam Thomas | MIL | vacuum | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Taurean Prince (16.3%) gone; usage 30.2 last season, 28.5 projected, offseason effect +1.2 | 9.4 (13.5) | 5+ 89c  10+ 49c  15+ 10c | waiting for a line - nan max nanc |
| Ty Jerome | MEM | vacuum | Ja Morant (32.4%), Santi Aldama (20.2%), Kentavious Caldwell-Pope (17.7%) gone; usage 32.7 last season, 32.0 projected, offseason effect +1.1 | 21.9 (19.7) | 15+ 87c  20+ 64c  25+ 34c | waiting for a line - nan max nanc |
| Brandon Miller | CHA | vacuum | LaMelo Ball (32.1%), Miles Bridges (22.3%), Buddy Hield (19.8%) gone; usage 28.1 last season, 28.0 projected, offseason effect +0.9 | 20.1 (20.2) | 15+ 82c  20+ 54c  25+ 23c | waiting for a line - nan max nanc |
| Coby White | CHA | vacuum | LaMelo Ball (32.1%), Miles Bridges (22.3%), Buddy Hield (19.8%) gone; usage 28.6 last season, 28.5 projected, offseason effect +0.9 | 13.8 (17.4) | 10+ 85c  15+ 43c  20+ 8c | waiting for a line - nan max nanc |
| Ja Morant | POR | arrival | New team (MEM -> POR); usage 32.4 last season, 28.5 projected, offseason effect -2.1 | 17.4 (19.4) | 10+ 93c  15+ 71c  20+ 34c | waiting for a line - nan max nanc |
| Collin Sexton | LAL | arrival | New team (CHI -> LAL); usage 25.9 last season, 23.1 projected, offseason effect -2.0 | 13.9 (15.4) | 10+ 86c  15+ 45c  20+ 9c | waiting for a line - nan max nanc |
| Brandon Ingram | LAC | arrival | New team (TOR -> LAC); usage 26.9 last season, 28.6 projected, offseason effect +2.0 | 22.7 (21.5) | 20+ 68c  25+ 40c  30+ 16c | waiting for a line - nan max nanc |
| Giannis Antetokounmpo | MIA | arrival | New team (MIL -> MIA); usage 36.6 last season, 34.2 projected, offseason effect +1.3 | 29.8 (27.6) | 25+ 72c  30+ 51c  35+ 30c | waiting for a line - nan max nanc |
| Kawhi Leonard | TOR | arrival | New team (LAC -> TOR); usage 33.4 last season, 32.8 projected, offseason effect +0.6 | 27.4 (27.9) | 20+ 83c  25+ 64c  30+ 40c | waiting for a line - nan max nanc |
| Julius Randle | BKN | arrival | New team (MIN -> BKN); usage 26.4 last season, 25.4 projected, offseason effect -0.6 | 20.4 (21.1) | 15+ 83c  20+ 56c  25+ 25c | waiting for a line - nan max nanc |
| Bennedict Mathurin | NOP | arrival | New team (LAC -> NOP); usage 25.1 last season, 23.6 projected, offseason effect -0.2 | 16.6 (17.6) | 10+ 92c  15+ 66c  20+ 28c | waiting for a line - nan max nanc |
| LaMelo Ball | MIN | arrival | New team (CHA -> MIN); usage 32.1 last season, 30.8 projected, offseason effect -0.2 | 19.4 (20.1) | 15+ 80c  20+ 49c  25+ 19c | waiting for a line - nan max nanc |
| Norman Powell | CHI | arrival | New team (MIA -> CHI); usage 27.1 last season, 26.8 projected, offseason effect +0.2 | 21.5 (21.7) | 15+ 86c  20+ 62c  25+ 32c | waiting for a line - nan max nanc |
| D'Angelo Russell | MEM | arrival | New team (WAS -> MEM); usage 26.0 last season, 25.3 projected | 11.2 (10.2) | 5+ 95c  10+ 67c  15+ 21c | waiting for a line - nan max nanc |
| Shaedon Sharpe | POR | squeeze | Ja Morant (32.4%), Micah Potter (17.9%), Branden Carlson (19.0%) added; usage 30.5 last season, 26.6 projected, offseason effect -1.6 | 18.5 (20.8) | 15+ 76c  20+ 43c  25+ 14c | waiting for a line - nan max nanc |
| Deni Avdija | POR | squeeze | Ja Morant (32.4%), Micah Potter (17.9%), Branden Carlson (19.0%) added; usage 29.1 last season, 25.2 projected, offseason effect -1.6 | 21.3 (24.2) | 15+ 86c  20+ 61c  25+ 31c | waiting for a line - nan max nanc |
| Luka Dončić | LAL | squeeze | Collin Sexton (25.9%), Quentin Grimes (19.0%), Walker Kessler (16.4%) added; usage 38.0 last season, 35.2 projected, offseason effect -1.1 | 31.4 (33.5) | 25+ 77c  30+ 58c  35+ 37c | waiting for a line - nan max nanc |
| Austin Reaves | LAL | squeeze | Collin Sexton (25.9%), Quentin Grimes (19.0%), Walker Kessler (16.4%) added; usage 26.6 last season, 23.9 projected, offseason effect -1.1 | 21.1 (23.3) | 15+ 85c  20+ 60c  25+ 30c | waiting for a line - nan max nanc |
| James Harden | CLE | squeeze | Peyton Watson (20.5%), Cam Whitmore (23.7%) added; usage 28.5 last season, 26.1 projected, offseason effect -0.9 | 21.8 (23.6) | 15+ 87c  20+ 64c  25+ 34c | waiting for a line - nan max nanc |
| Donovan Mitchell | CLE | squeeze | Peyton Watson (20.5%), Cam Whitmore (23.7%) added; usage 32.1 last season, 29.7 projected, offseason effect -0.9 | 26.1 (27.9) | 20+ 80c  25+ 58c  30+ 33c | waiting for a line - nan max nanc |
| Anthony Edwards | MIN | squeeze | LaMelo Ball (32.1%), Jonathan Kuminga (23.3%), Cody Williams (16.0%) added; usage 31.4 last season, 30.1 projected, offseason effect -0.9 | 27.8 (28.8) | 25+ 65c  30+ 42c  35+ 21c | waiting for a line - nan max nanc |
| Zion Williamson | NOP | squeeze | Bennedict Mathurin (25.1%), Trendon Watford (17.9%), AJ Johnson (20.6%) added; usage 25.5 last season, 24.0 projected, offseason effect -0.9 | 19.9 (21.0) | 15+ 82c  20+ 53c  25+ 22c | waiting for a line - nan max nanc |
| Jeremiah Fears | NOP | squeeze | Bennedict Mathurin (25.1%), Trendon Watford (17.9%), AJ Johnson (20.6%) added; usage 25.5 last season, 24.0 projected, offseason effect -0.9 | 10.0 (14.3) | 5+ 92c  10+ 55c  15+ 13c | waiting for a line - nan max nanc |
| Jordan Poole | NOP | squeeze | Bennedict Mathurin (25.1%), Trendon Watford (17.9%), AJ Johnson (20.6%) added; usage 25.2 last season, 23.7 projected, offseason effect -0.9 | 9.4 (13.4) | 5+ 89c  10+ 49c  15+ 10c | waiting for a line - nan max nanc |
| Michael Porter Jr. | BKN | squeeze | Julius Randle (26.4%), Moritz Wagner (24.2%), Keon Ellis (13.1%) added; usage 30.5 last season, 29.5 projected, offseason effect -0.7 | 23.5 (24.2) | 20+ 72c  25+ 44c  30+ 20c | waiting for a line - nan max nanc |
| Stephen Curry | GSW | squeeze | Brandon Williams (24.9%) added; usage 32.5 last season, 31.1 projected, offseason effect -0.5 | 25.6 (26.6) | 20+ 79c  25+ 55c  30+ 30c | waiting for a line - nan max nanc |
| De'Anthony Melton | GSW | squeeze | Brandon Williams (24.9%) added; usage 25.4 last season, 24.0 projected, offseason effect -0.5 | 10.5 (12.3) | 5+ 93c  10+ 60c  15+ 16c | waiting for a line - nan max nanc |

## Medium usage (71)

| player | team | situation | thesis | proj (25-26) | fair ladder | status |
|---|---|---|---|---|---|---|
| Derrick White | BOS | vacuum | Jaylen Brown (36.1%), Nikola Vučević (21.4%) gone; usage 22.0 last season, 22.6 projected, offseason effect +3.1 | 16.8 (16.4) | 10+ 93c  15+ 68c  20+ 30c | READY: edge 8.1pp >= 4.0pp threshold - 16+ YES max 54.0c |
| Payton Pritchard | BOS | vacuum | Jaylen Brown (36.1%), Nikola Vučević (21.4%) gone; usage 21.5 last season, 22.1 projected, offseason effect +3.1 | 17.5 (17.0) | 10+ 94c  15+ 71c  20+ 35c | line up: only 1 priced reference book(s), need 2 - 16+ YES max 58.0c |
| Ronald Holland II | BOS | vacuum | Jaylen Brown (36.1%), Nikola Vučević (21.4%) gone; usage 18.9 last season, 19.4 projected, offseason effect +3.1 | 7.1 (8.2) | 5+ 74c  10+ 27c | waiting for a line - nan max nanc |
| Jordan Miller | LAC | vacuum | Kawhi Leonard (33.4%), Bennedict Mathurin (25.1%), John Collins (19.5%) gone; usage 18.0 last season, 19.7 projected, offseason effect +3.0 | 10.4 (10.0) | 5+ 93c  10+ 59c  15+ 15c | waiting for a line - nan max nanc |
| P.J. Washington | DAL | vacuum | Brandon Williams (24.9%), Klay Thompson (22.8%), Khris Middleton (20.6%) gone; usage 20.1 last season, 21.6 projected, offseason effect +2.2 | 15.1 (14.2) | 10+ 89c  15+ 55c  20+ 17c | waiting for a line - nan max nanc |
| Naji Marshall | DAL | vacuum | Brandon Williams (24.9%), Klay Thompson (22.8%), Khris Middleton (20.6%) gone; usage 20.5 last season, 22.0 projected, offseason effect +2.2 | 16.2 (15.2) | 10+ 92c  15+ 64c  20+ 25c | waiting for a line - nan max nanc |
| Kevin Porter Jr. | MIL | vacuum | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Taurean Prince (16.3%) gone; usage 24.2 last season, 22.5 projected, offseason effect +1.2 | 16.3 (17.4) | 10+ 92c  15+ 64c  20+ 25c | waiting for a line - nan max nanc |
| Ryan Rollins | MIL | vacuum | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Taurean Prince (16.3%) gone; usage 24.2 last season, 22.5 projected, offseason effect +1.2 | 16.2 (17.3) | 10+ 92c  15+ 64c  20+ 25c | waiting for a line - nan max nanc |
| Kyle Kuzma | MIL | vacuum | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Taurean Prince (16.3%) gone; usage 21.7 last season, 20.0 projected, offseason effect +1.2 | 8.8 (13.0) | 5+ 86c  10+ 43c  15+ 8c | waiting for a line - nan max nanc |
| Myles Turner | MIL | vacuum | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Taurean Prince (16.3%) gone; usage 18.6 last season, 16.9 projected, offseason effect +1.2 | 8.0 (11.9) | 5+ 81c  10+ 35c  15+ 5c | waiting for a line - nan max nanc |
| GG Jackson | MEM | vacuum | Ja Morant (32.4%), Santi Aldama (20.2%), Kentavious Caldwell-Pope (17.7%) gone; usage 23.5 last season, 22.8 projected, offseason effect +1.1 | 13.8 (12.5) | 10+ 85c  15+ 43c  20+ 8c | waiting for a line - nan max nanc |
| Jaylen Wells | MEM | vacuum | Ja Morant (32.4%), Santi Aldama (20.2%), Kentavious Caldwell-Pope (17.7%) gone; usage 19.3 last season, 18.6 projected, offseason effect +1.1 | 12.1 (12.5) | 5+ 97c  10+ 75c  15+ 28c | waiting for a line - nan max nanc |
| Olivier-Maxence Prosper | MEM | vacuum | Ja Morant (32.4%), Santi Aldama (20.2%), Kentavious Caldwell-Pope (17.7%) gone; usage 18.9 last season, 18.2 projected, offseason effect +1.1 | 10.9 (10.0) | 5+ 95c  10+ 64c  15+ 19c | waiting for a line - nan max nanc |
| Kon Knueppel | CHA | vacuum | LaMelo Ball (32.1%), Miles Bridges (22.3%), Buddy Hield (19.8%) gone; usage 22.3 last season, 22.2 projected, offseason effect +0.9 | 18.4 (18.5) | 15+ 76c  20+ 42c  25+ 13c | waiting for a line - nan max nanc |
| Santi Aldama | DAL | arrival | New team (MEM -> DAL); usage 20.2 last season, 21.7 projected, offseason effect +3.3 | 15.0 (14.0) | 10+ 89c  15+ 54c  20+ 16c | waiting for a line - nan max nanc |
| Sandro Mamukelashvili | LAL | arrival | New team (TOR -> LAL); usage 18.8 last season, 16.1 projected, offseason effect -2.4 | 9.4 (11.2) | 5+ 89c  10+ 49c  15+ 10c | waiting for a line - nan max nanc |
| Ziaire Williams | LAL | arrival | New team (BKN -> LAL); usage 18.8 last season, 16.1 projected, offseason effect -2.4 | 8.6 (10.2) | 5+ 85c  10+ 41c  15+ 7c | waiting for a line - nan max nanc |
| Peyton Watson | CLE | arrival | New team (DEN -> CLE); usage 20.5 last season, 18.2 projected, offseason effect -2.1 | 13.1 (14.6) | 10+ 81c  15+ 36c  20+ 5c | waiting for a line - nan max nanc |
| Grayson Allen | CHA | arrival | New team (PHX -> CHA); usage 23.8 last season, 23.7 projected, offseason effect +1.9 | 16.4 (16.5) | 10+ 92c  15+ 65c  20+ 27c | waiting for a line - nan max nanc |
| Jerami Grant | MEM | arrival | New team (POR -> MEM); usage 23.7 last season, 23.0 projected, offseason effect +1.6 | 18.1 (18.6) | 15+ 75c  20+ 40c  25+ 12c | waiting for a line - nan max nanc |
| Tim Hardaway Jr. | MIA | arrival | New team (DEN -> MIA); usage 18.5 last season, 16.2 projected, offseason effect -1.4 | 9.9 (13.5) | 5+ 91c  10+ 54c  15+ 12c | waiting for a line - nan max nanc |
| Dennis Schröder | CHA | arrival | New team (CLE -> CHA); usage 21.0 last season, 20.9 projected, offseason effect +1.3 | 8.6 (10.8) | 5+ 84c  10+ 41c  15+ 7c | waiting for a line - nan max nanc |
| Miles Bridges | PHX | arrival | New team (CHA -> PHX); usage 22.3 last season, 20.0 projected, offseason effect -1.3 | 15.4 (17.1) | 10+ 90c  15+ 58c  20+ 19c | waiting for a line - nan max nanc |
| Bobby Portis | MIA | arrival | New team (MIL -> MIA); usage 23.2 last season, 20.9 projected, offseason effect +1.2 | 10.3 (13.7) | 5+ 93c  10+ 58c  15+ 15c | waiting for a line - nan max nanc |
| Tyler Herro | MIL | arrival | New team (MIA -> MIL); usage 24.8 last season, 23.1 projected, offseason effect -1.2 | 19.2 (20.5) | 15+ 79c  20+ 48c  25+ 18c | waiting for a line - nan max nanc |
| Jaime Jaquez Jr. | MIL | arrival | New team (MIA -> MIL); usage 22.4 last season, 20.7 projected, offseason effect -1.2 | 14.3 (15.4) | 10+ 87c  15+ 48c  20+ 11c | waiting for a line - nan max nanc |
| Kel'el Ware | MIL | arrival | New team (MIA -> MIL); usage 18.1 last season, 16.4 projected, offseason effect -1.2 | 7.4 (11.1) | 5+ 76c  10+ 30c | waiting for a line - nan max nanc |
| Klay Thompson | MIA | arrival | New team (DAL -> MIA); usage 22.8 last season, 20.5 projected, offseason effect -1.0 | 9.8 (11.7) | 5+ 91c  10+ 53c  15+ 12c | waiting for a line - nan max nanc |
| Bogdan Bogdanović | HOU | arrival | New team (LAC -> HOU); usage 18.7 last season, 18.2 projected, offseason effect +0.7 | 4.6 (7.4) | 5+ 51c  10+ 11c | waiting for a line - nan max nanc |
| Nikola Vučević | ORL | arrival | New team (BOS -> ORL); usage 21.4 last season, 19.6 projected, offseason effect +0.7 | 10.2 (15.1) | 5+ 92c  10+ 57c  15+ 14c | waiting for a line - nan max nanc |
| Brandon Williams | GSW | arrival | New team (DAL -> GSW); usage 24.9 last season, 23.5 projected, offseason effect -0.7 | 11.1 (13.0) | 5+ 95c  10+ 65c  15+ 20c | waiting for a line - nan max nanc |
| DeMar DeRozan | DEN | arrival | New team (SAC -> DEN); usage 22.7 last season, 22.2 projected, offseason effect +0.7 | 18.1 (18.4) | 15+ 74c  20+ 39c  25+ 12c | waiting for a line - nan max nanc |
| Buddy Hield | CHI | arrival | New team (CHA -> CHI); usage 19.8 last season, 19.5 projected, offseason effect +0.7 | 6.8 (8.1) | 5+ 72c  10+ 25c | waiting for a line - nan max nanc |
| John Collins | DET | arrival | New team (LAC -> DET); usage 19.5 last season, 18.9 projected, offseason effect +0.7 | 13.2 (13.6) | 10+ 82c  15+ 37c  20+ 6c | waiting for a line - nan max nanc |
| Khris Middleton | WAS | arrival | New team (DAL -> WAS); usage 20.6 last season, 19.2 projected, offseason effect -0.7 | 7.3 (10.2) | 5+ 76c  10+ 29c | waiting for a line - nan max nanc |
| Tobias Harris | SAS | arrival | New team (DET -> SAS); usage 18.9 last season, 17.9 projected, offseason effect -0.5 | 12.6 (13.3) | 10+ 78c  15+ 32c  20+ 4c | waiting for a line - nan max nanc |
| Isaiah Joe | DET | arrival | New team (OKC -> DET); usage 18.5 last season, 17.9 projected, offseason effect +0.3 | 9.9 (11.1) | 5+ 91c  10+ 54c  15+ 13c | waiting for a line - nan max nanc |
| Aaron Wiggins | ATL | arrival | New team (OKC -> ATL); usage 19.9 last season, 18.7 projected, offseason effect -0.3 | 6.4 (9.4) | 5+ 68c  10+ 22c | waiting for a line - nan max nanc |
| Naz Reid | CHA | arrival | New team (MIN -> CHA); usage 22.2 last season, 22.1 projected, offseason effect +0.2 | 13.5 (13.6) | 10+ 84c  15+ 40c  20+ 7c | waiting for a line - nan max nanc |
| Marvin Bagley III | DEN | arrival | New team (DAL -> DEN); usage 18.6 last season, 18.1 projected, offseason effect +0.2 | 7.0 (10.4) | 5+ 74c  10+ 27c | waiting for a line - nan max nanc |
| Jonathan Kuminga | MIN | arrival | New team (ATL -> MIN); usage 23.3 last season, 22.0 projected, offseason effect -0.1 | 9.3 (12.2) | 5+ 88c  10+ 48c  15+ 10c | waiting for a line - nan max nanc |
| Devin Carter | ATL | arrival | New team (SAC -> ATL); usage 23.5 last season, 22.3 projected | 6.1 (8.9) | 5+ 66c  10+ 20c | waiting for a line - nan max nanc |
| Paul George | BOS | arrival | New team (PHI -> BOS); usage 23.3 last season, 23.9 projected | 17.7 (17.3) | 15+ 73c  20+ 37c  25+ 10c | READY: edge 14.5pp >= 4.0pp threshold - 16+ YES max 60.0c |
| Cam Whitmore | CLE | arrival | New team (WAS -> CLE); usage 23.7 last season, 21.3 projected | 6.3 (9.2) | 5+ 68c  10+ 21c | waiting for a line - nan max nanc |
| Kelly Oubre Jr. | IND | arrival | New team (PHI -> IND); usage 18.2 last season, 17.6 projected | 13.7 (14.1) | 10+ 84c  15+ 42c  20+ 8c | waiting for a line - nan max nanc |
| Quentin Grimes | LAL | arrival | New team (PHI -> LAL); usage 19.0 last season, 16.3 projected | 11.6 (13.4) | 5+ 96c  10+ 70c  15+ 24c | waiting for a line - nan max nanc |
| Jaden Hardy | LAL | arrival | New team (WAS -> LAL); usage 24.4 last season, 21.7 projected | 8.0 (9.2) | 5+ 81c  10+ 35c  15+ 5c | waiting for a line - nan max nanc |
| Nick Richards | MIA | arrival | New team (CHI -> MIA); usage 18.1 last season, 15.8 projected | 3.5 (5.8) | 5+ 40c  10+ 7c | waiting for a line - nan max nanc |
| Scoot Henderson | POR | squeeze | Ja Morant (32.4%), Micah Potter (17.9%), Branden Carlson (19.0%) added; usage 24.9 last season, 21.1 projected, offseason effect -1.6 | 9.3 (14.2) | 5+ 88c  10+ 48c  15+ 10c | waiting for a line - nan max nanc |
| Jrue Holiday | POR | squeeze | Ja Morant (32.4%), Micah Potter (17.9%), Branden Carlson (19.0%) added; usage 23.6 last season, 19.8 projected, offseason effect -1.5 | 13.9 (16.3) | 10+ 85c  15+ 44c  20+ 9c | waiting for a line - nan max nanc |
| Caleb Love | POR | squeeze | Ja Morant (32.4%), Micah Potter (17.9%), Branden Carlson (19.0%) added; usage 23.1 last season, 19.3 projected, offseason effect -1.5 | 6.7 (10.4) | 5+ 71c  10+ 24c | waiting for a line - nan max nanc |
| Bam Adebayo | MIA | squeeze | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Klay Thompson (22.8%) added; usage 24.9 last season, 22.6 projected, offseason effect -1.1 | 18.7 (20.1) | 15+ 77c  20+ 45c  25+ 15c | waiting for a line - nan max nanc |
| Andrew Wiggins | MIA | squeeze | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Klay Thompson (22.8%) added; usage 19.7 last season, 17.4 projected, offseason effect -1.1 | 13.1 (15.4) | 10+ 82c  15+ 36c  20+ 5c | waiting for a line - nan max nanc |
| Evan Mobley | CLE | squeeze | Peyton Watson (20.5%), Cam Whitmore (23.7%) added; usage 22.5 last season, 20.1 projected, offseason effect -0.9 | 16.4 (18.1) | 10+ 92c  15+ 65c  20+ 26c | waiting for a line - nan max nanc |
| Jarrett Allen | CLE | squeeze | Peyton Watson (20.5%), Cam Whitmore (23.7%) added; usage 19.8 last season, 17.5 projected, offseason effect -0.9 | 13.7 (15.4) | 10+ 84c  15+ 42c  20+ 8c | waiting for a line - nan max nanc |
| Jaylon Tyson | CLE | squeeze | Peyton Watson (20.5%), Cam Whitmore (23.7%) added; usage 19.4 last season, 17.1 projected, offseason effect -0.9 | 8.9 (13.2) | 5+ 87c  10+ 44c  15+ 8c | waiting for a line - nan max nanc |
| Jaden McDaniels | MIN | squeeze | LaMelo Ball (32.1%), Jonathan Kuminga (23.3%), Cody Williams (16.0%) added; usage 18.6 last season, 17.4 projected, offseason effect -0.9 | 13.9 (14.8) | 10+ 85c  15+ 44c  20+ 9c | waiting for a line - nan max nanc |
| Ayo Dosunmu | MIN | squeeze | LaMelo Ball (32.1%), Jonathan Kuminga (23.3%), Cody Williams (16.0%) added; usage 20.2 last season, 18.9 projected, offseason effect -0.9 | 11.2 (14.8) | 5+ 95c  10+ 66c  15+ 20c | waiting for a line - nan max nanc |
| Bones Hyland | MIN | squeeze | LaMelo Ball (32.1%), Jonathan Kuminga (23.3%), Cody Williams (16.0%) added; usage 20.6 last season, 19.4 projected, offseason effect -0.9 | 6.4 (8.5) | 5+ 69c  10+ 22c | waiting for a line - nan max nanc |
| Trey Murphy III | NOP | squeeze | Bennedict Mathurin (25.1%), Trendon Watford (17.9%), AJ Johnson (20.6%) added; usage 22.8 last season, 21.3 projected, offseason effect -0.9 | 20.2 (21.5) | 15+ 83c  20+ 55c  25+ 24c | waiting for a line - nan max nanc |
| Saddiq Bey | NOP | squeeze | Bennedict Mathurin (25.1%), Trendon Watford (17.9%), AJ Johnson (20.6%) added; usage 21.6 last season, 20.1 projected, offseason effect -0.9 | 16.5 (17.6) | 10+ 92c  15+ 66c  20+ 27c | waiting for a line - nan max nanc |
| Derik Queen | NOP | squeeze | Bennedict Mathurin (25.1%), Trendon Watford (17.9%), AJ Johnson (20.6%) added; usage 21.8 last season, 20.3 projected, offseason effect -0.9 | 8.1 (11.7) | 5+ 82c  10+ 37c  15+ 6c | waiting for a line - nan max nanc |
| Noah Clowney | BKN | squeeze | Julius Randle (26.4%), Moritz Wagner (24.2%), Keon Ellis (13.1%) added; usage 20.3 last season, 19.3 projected, offseason effect -0.7 | 11.7 (12.3) | 5+ 96c  10+ 71c  15+ 24c | waiting for a line - nan max nanc |
| Egor Dëmin | BKN | squeeze | Julius Randle (26.4%), Moritz Wagner (24.2%), Keon Ellis (13.1%) added; usage 18.9 last season, 17.9 projected, offseason effect -0.7 | 9.8 (10.3) | 5+ 91c  10+ 53c  15+ 12c | waiting for a line - nan max nanc |
| Nolan Traore | BKN | squeeze | Julius Randle (26.4%), Moritz Wagner (24.2%), Keon Ellis (13.1%) added; usage 22.9 last season, 21.9 projected, offseason effect -0.7 | 8.0 (8.9) | 5+ 81c  10+ 35c  15+ 5c | waiting for a line - nan max nanc |
| Ben Saraf | BKN | squeeze | Julius Randle (26.4%), Moritz Wagner (24.2%), Keon Ellis (13.1%) added; usage 21.0 last season, 20.0 projected, offseason effect -0.7 | 6.7 (7.5) | 5+ 71c  10+ 24c | waiting for a line - nan max nanc |
| Danny Wolf | BKN | squeeze | Julius Randle (26.4%), Moritz Wagner (24.2%), Keon Ellis (13.1%) added; usage 20.6 last season, 19.6 projected, offseason effect -0.7 | 7.9 (8.9) | 5+ 80c  10+ 35c  15+ 5c | waiting for a line - nan max nanc |
| Jimmy Butler III | GSW | squeeze | Brandon Williams (24.9%) added; usage 23.1 last season, 21.7 projected, offseason effect -0.5 | 18.9 (20.0) | 15+ 78c  20+ 46c  25+ 16c | waiting for a line - nan max nanc |
| Brandin Podziemski | GSW | squeeze | Brandon Williams (24.9%) added; usage 20.1 last season, 18.7 projected, offseason effect -0.5 | 12.9 (13.8) | 10+ 80c  15+ 35c  20+ 5c | waiting for a line - nan max nanc |
| Moses Moody | GSW | squeeze | Brandon Williams (24.9%) added; usage 18.3 last season, 16.9 projected, offseason effect -0.5 | 11.3 (12.1) | 5+ 96c  10+ 67c  15+ 21c | waiting for a line - nan max nanc |
| Gui Santos | GSW | squeeze | Brandon Williams (24.9%) added; usage 18.7 last season, 17.3 projected, offseason effect -0.5 | 7.7 (9.2) | 5+ 79c  10+ 33c  15+ 5c | waiting for a line - nan max nanc |

## Low usage (51)

| player | team | situation | thesis | proj (25-26) | fair ladder | status |
|---|---|---|---|---|---|---|
| Kris Dunn | LAC | vacuum | Kawhi Leonard (33.4%), Bennedict Mathurin (25.1%), John Collins (19.5%) gone; usage 12.4 last season, 14.2 projected, offseason effect +3.0 | 8.2 (7.3) | 5+ 83c  10+ 38c  15+ 6c | waiting for a line - nan max nanc |
| Neemias Queta | BOS | vacuum | Jaylen Brown (36.1%), Nikola Vučević (21.4%) gone; usage 14.6 last season, 15.2 projected, offseason effect +3.0 | 10.6 (10.2) | 5+ 94c  10+ 60c  15+ 16c | waiting for a line - nan max nanc |
| Sam Hauser | BOS | vacuum | Jaylen Brown (36.1%), Nikola Vučević (21.4%) gone; usage 14.6 last season, 15.2 projected, offseason effect +3.0 | 8.0 (9.2) | 5+ 81c  10+ 35c  15+ 5c | waiting for a line - nan max nanc |
| Derrick Jones Jr. | LAC | vacuum | Kawhi Leonard (33.4%), Bennedict Mathurin (25.1%), John Collins (19.5%) gone; usage 15.1 last season, 16.9 projected, offseason effect +3.0 | 11.2 (10.1) | 5+ 95c  10+ 66c  15+ 20c | waiting for a line - nan max nanc |
| Kobe Sanders | LAC | vacuum | Kawhi Leonard (33.4%), Bennedict Mathurin (25.1%), John Collins (19.5%) gone; usage 16.3 last season, 18.1 projected, offseason effect +3.0 | 7.7 (7.3) | 5+ 79c  10+ 33c  15+ 4c | waiting for a line - nan max nanc |
| Brook Lopez | LAC | vacuum | Kawhi Leonard (33.4%), Bennedict Mathurin (25.1%), John Collins (19.5%) gone; usage 17.3 last season, 19.0 projected, offseason effect +3.0 | 8.9 (8.4) | 5+ 86c  10+ 44c  15+ 8c | waiting for a line - nan max nanc |
| Baylor Scheierman | BOS | vacuum | Jaylen Brown (36.1%), Nikola Vučević (21.4%) gone; usage 12.0 last season, 12.6 projected, offseason effect +3.0 | 4.9 (5.5) | 5+ 54c  10+ 12c | waiting for a line - nan max nanc |
| Max Christie | DAL | vacuum | Brandon Williams (24.9%), Klay Thompson (22.8%), Khris Middleton (20.6%) gone; usage 16.5 last season, 18.0 projected, offseason effect +2.2 | 13.3 (12.3) | 10+ 83c  15+ 38c  20+ 6c | waiting for a line - nan max nanc |
| Daniel Gafford | DAL | vacuum | Brandon Williams (24.9%), Klay Thompson (22.8%), Khris Middleton (20.6%) gone; usage 15.7 last season, 17.2 projected, offseason effect +2.2 | 10.6 (9.5) | 5+ 94c  10+ 61c  15+ 16c | waiting for a line - nan max nanc |
| Gary Trent Jr. | MIL | vacuum | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Taurean Prince (16.3%) gone; usage 17.3 last season, 15.6 projected, offseason effect +1.1 | 5.4 (8.1) | 5+ 59c  10+ 15c | waiting for a line - nan max nanc |
| AJ Green | MIL | vacuum | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Taurean Prince (16.3%) gone; usage 14.1 last season, 12.4 projected, offseason effect +1.1 | 9.2 (10.4) | 5+ 88c  10+ 47c  15+ 9c | waiting for a line - nan max nanc |
| Cam Spencer | MEM | vacuum | Ja Morant (32.4%), Santi Aldama (20.2%), Kentavious Caldwell-Pope (17.7%) gone; usage 17.2 last season, 16.5 projected, offseason effect +1.1 | 10.7 (11.1) | 5+ 94c  10+ 62c  15+ 17c | waiting for a line - nan max nanc |
| Taylor Hendricks | MEM | vacuum | Ja Morant (32.4%), Santi Aldama (20.2%), Kentavious Caldwell-Pope (17.7%) gone; usage 16.2 last season, 15.5 projected, offseason effect +1.1 | 8.1 (7.4) | 5+ 82c  10+ 36c  15+ 5c | waiting for a line - nan max nanc |
| Moussa Diabaté | CHA | vacuum | LaMelo Ball (32.1%), Miles Bridges (22.3%), Buddy Hield (19.8%) gone; usage 11.4 last season, 11.3 projected, offseason effect +0.9 | 6.2 (7.9) | 5+ 66c  10+ 20c | waiting for a line - nan max nanc |
| Ryan Kalkbrenner | CHA | vacuum | LaMelo Ball (32.1%), Miles Bridges (22.3%), Buddy Hield (19.8%) gone; usage 11.5 last season, 11.4 projected, offseason effect +0.9 | 6.0 (7.5) | 5+ 64c  10+ 19c | waiting for a line - nan max nanc |
| Sion James | CHA | vacuum | LaMelo Ball (32.1%), Miles Bridges (22.3%), Buddy Hield (19.8%) gone; usage 11.0 last season, 10.9 projected, offseason effect +0.9 | 4.2 (5.4) | 5+ 47c  10+ 9c | waiting for a line - nan max nanc |
| Rui Hachimura | LAC | arrival | New team (LAL -> LAC); usage 15.3 last season, 17.1 projected, offseason effect +3.4 | 12.7 (11.5) | 10+ 79c  15+ 32c  20+ 4c | waiting for a line - nan max nanc |
| Micah Potter | POR | arrival | New team (IND -> POR); usage 17.9 last season, 14.2 projected, offseason effect -3.1 | 6.0 (9.7) | 5+ 65c  10+ 19c | waiting for a line - nan max nanc |
| Zaccharie Risacher | DAL | arrival | New team (ATL -> DAL); usage 17.6 last season, 19.1 projected, offseason effect +2.6 | 10.5 (9.6) | 5+ 93c  10+ 60c  15+ 16c | waiting for a line - nan max nanc |
| Taurean Prince | DET | arrival | New team (MIL -> DET); usage 16.3 last season, 15.7 projected, offseason effect +2.2 | 8.2 (9.2) | 5+ 82c  10+ 37c  15+ 6c | waiting for a line - nan max nanc |
| Royce O'Neale | CHA | arrival | New team (PHX -> CHA); usage 14.4 last season, 14.3 projected, offseason effect +1.9 | 9.7 (9.8) | 5+ 90c  10+ 52c  15+ 12c | waiting for a line - nan max nanc |
| Kris Murray | MEM | arrival | New team (POR -> MEM); usage 10.6 last season, 9.9 projected, offseason effect +1.5 | 5.5 (5.8) | 5+ 59c  10+ 16c | waiting for a line - nan max nanc |
| Marcus Smart | HOU | arrival | New team (LAL -> HOU); usage 15.5 last season, 15.0 projected, offseason effect +1.1 | 9.0 (9.3) | 5+ 87c  10+ 45c  15+ 9c | waiting for a line - nan max nanc |
| Mike Conley | BOS | arrival | New team (MIN -> BOS); usage 11.5 last season, 12.1 projected, offseason effect +0.9 | 4.0 (4.5) | 5+ 45c  10+ 8c | waiting for a line - nan max nanc |
| Cody Williams | MIN | arrival | New team (UTA -> MIN); usage 16.0 last season, 14.8 projected, offseason effect +0.7 | 6.5 (8.8) | 5+ 69c  10+ 23c | waiting for a line - nan max nanc |
| Luke Kennard | PHX | arrival | New team (LAL -> PHX); usage 13.5 last season, 11.3 projected, offseason effect -0.6 | 5.8 (8.4) | 5+ 63c  10+ 18c | waiting for a line - nan max nanc |
| Keon Ellis | BKN | arrival | New team (CLE -> BKN); usage 13.1 last season, 12.1 projected, offseason effect +0.5 | 5.7 (6.7) | 5+ 62c  10+ 17c | waiting for a line - nan max nanc |
| Deandre Ayton | WAS | arrival | New team (LAL -> WAS); usage 16.7 last season, 15.4 projected, offseason effect +0.3 | 8.8 (12.5) | 5+ 86c  10+ 43c  15+ 8c | waiting for a line - nan max nanc |
| Kyle Anderson | TOR | arrival | New team (MIN -> TOR); usage 13.1 last season, 12.5 projected, offseason effect -0.3 | 4.3 (5.9) | 5+ 48c  10+ 10c | waiting for a line - nan max nanc |
| Luguentz Dort | ATL | arrival | New team (OKC -> ATL); usage 14.2 last season, 13.0 projected, offseason effect -0.2 | 5.5 (8.3) | 5+ 60c  10+ 16c | waiting for a line - nan max nanc |
| Mitchell Robinson | BOS | arrival | New team (NYK -> BOS); usage 10.6 last season, 11.2 projected, offseason effect +0.2 | 5.0 (5.7) | 5+ 55c  10+ 13c | waiting for a line - nan max nanc |
| Isaiah Stewart | MEM | arrival | New team (DET -> MEM); usage 16.6 last season, 15.9 projected, offseason effect -0.1 | 9.6 (10.0) | 5+ 90c  10+ 51c  15+ 11c | waiting for a line - nan max nanc |
| Nic Claxton | CHI | arrival | New team (BKN -> CHI); usage 17.7 last season, 17.4 projected, offseason effect -0.1 | 11.5 (11.7) | 5+ 96c  10+ 69c  15+ 23c | waiting for a line - nan max nanc |
| Matisse Thybulle | LAL | arrival | New team (POR -> LAL); usage 14.7 last season, 12.1 projected | 4.7 (5.8) | 5+ 52c  10+ 11c | waiting for a line - nan max nanc |
| Andre Drummond | NYK | arrival | New team (PHI -> NYK); usage 14.9 last season, 15.0 projected | 4.6 (6.4) | 5+ 51c  10+ 11c | waiting for a line - nan max nanc |
| Donovan Clingan | POR | squeeze | Ja Morant (32.4%), Micah Potter (17.9%), Branden Carlson (19.0%) added; usage 16.8 last season, 13.1 projected, offseason effect -1.5 | 7.3 (12.1) | 5+ 76c  10+ 29c | waiting for a line - nan max nanc |
| Toumani Camara | POR | squeeze | Ja Morant (32.4%), Micah Potter (17.9%), Branden Carlson (19.0%) added; usage 16.4 last season, 12.7 projected, offseason effect -1.4 | 10.6 (13.4) | 5+ 94c  10+ 61c  15+ 16c | waiting for a line - nan max nanc |
| Vít Krejčí | POR | squeeze | Ja Morant (32.4%), Micah Potter (17.9%), Branden Carlson (19.0%) added; usage 14.7 last season, 11.1 projected, offseason effect -1.4 | 4.9 (8.5) | 5+ 54c  10+ 12c | waiting for a line - nan max nanc |
| Pelle Larsson | MIA | squeeze | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Klay Thompson (22.8%) added; usage 16.7 last season, 14.4 projected, offseason effect -1.1 | 7.5 (11.4) | 5+ 78c  10+ 31c  15+ 4c | waiting for a line - nan max nanc |
| Davion Mitchell | MIA | squeeze | Giannis Antetokounmpo (36.6%), Bobby Portis (23.2%), Klay Thompson (22.8%) added; usage 13.7 last season, 11.4 projected, offseason effect -1.1 | 7.2 (9.3) | 5+ 75c  10+ 28c | waiting for a line - nan max nanc |
| Jake LaRavia | LAL | squeeze | Collin Sexton (25.9%), Quentin Grimes (19.0%), Walker Kessler (16.4%) added; usage 14.4 last season, 11.8 projected, offseason effect -1.0 | 6.8 (8.2) | 5+ 72c  10+ 25c | waiting for a line - nan max nanc |
| Jarred Vanderbilt | LAL | squeeze | Collin Sexton (25.9%), Quentin Grimes (19.0%), Walker Kessler (16.4%) added; usage 12.5 last season, 9.9 projected, offseason effect -1.0 | 3.5 (4.4) | 5+ 40c  10+ 7c | waiting for a line - nan max nanc |
| Donte DiVincenzo | MIN | squeeze | LaMelo Ball (32.1%), Jonathan Kuminga (23.3%), Cody Williams (16.0%) added; usage 17.0 last season, 15.8 projected, offseason effect -0.9 | 11.4 (12.2) | 5+ 96c  10+ 68c  15+ 22c | waiting for a line - nan max nanc |
| Sam Merrill | CLE | squeeze | Peyton Watson (20.5%), Cam Whitmore (23.7%) added; usage 17.1 last season, 14.8 projected, offseason effect -0.9 | 8.5 (12.8) | 5+ 84c  10+ 40c  15+ 7c | waiting for a line - nan max nanc |
| Rudy Gobert | MIN | squeeze | LaMelo Ball (32.1%), Jonathan Kuminga (23.3%), Cody Williams (16.0%) added; usage 12.8 last season, 11.6 projected, offseason effect -0.9 | 9.9 (10.9) | 5+ 91c  10+ 54c  15+ 13c | waiting for a line - nan max nanc |
| Lonzo Ball | CLE | squeeze | Peyton Watson (20.5%), Cam Whitmore (23.7%) added; usage 13.8 last season, 11.5 projected, offseason effect -0.8 | 2.9 (4.6) | 5+ 35c  10+ 5c | waiting for a line - nan max nanc |
| Herbert Jones | NOP | squeeze | Bennedict Mathurin (25.1%), Trendon Watford (17.9%), AJ Johnson (20.6%) added; usage 15.2 last season, 13.7 projected, offseason effect -0.8 | 8.1 (8.9) | 5+ 81c  10+ 36c  15+ 5c | waiting for a line - nan max nanc |
| Bryce McGowens | NOP | squeeze | Bennedict Mathurin (25.1%), Trendon Watford (17.9%), AJ Johnson (20.6%) added; usage 13.9 last season, 12.4 projected, offseason effect -0.8 | 5.4 (8.1) | 5+ 59c  10+ 15c | waiting for a line - nan max nanc |
| Yves Missi | NOP | squeeze | Bennedict Mathurin (25.1%), Trendon Watford (17.9%), AJ Johnson (20.6%) added; usage 12.6 last season, 11.1 projected, offseason effect -0.8 | 3.7 (5.7) | 5+ 42c  10+ 7c | waiting for a line - nan max nanc |
| Terance Mann | BKN | squeeze | Julius Randle (26.4%), Moritz Wagner (24.2%), Keon Ellis (13.1%) added; usage 13.6 last season, 12.6 projected, offseason effect -0.7 | 6.7 (7.2) | 5+ 71c  10+ 24c | waiting for a line - nan max nanc |
| Drake Powell | BKN | squeeze | Julius Randle (26.4%), Moritz Wagner (24.2%), Keon Ellis (13.1%) added; usage 15.0 last season, 14.0 projected, offseason effect -0.7 | 5.7 (6.5) | 5+ 61c  10+ 17c | waiting for a line - nan max nanc |
