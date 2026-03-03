---
name: espn-api
description: Query any ESPN NBA API endpoint — scoreboard, game details, team stats, roster, injuries, standings, athlete stats, schedule, head-to-head, and play-by-play. Use when the user asks for ESPN data, game scores, team info, injuries, or player lookups.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: <subcommand> [args...]
---

# ESPN API Skill

Call any ESPN NBA endpoint and get structured JSON output.

## Subcommands

| Subcommand | Args | Description |
|------------|------|-------------|
| `scoreboard` | `[DATE]` | All games for a date (YYYYMMDD, default: today) |
| `live` | `[DATE]` | Live games only |
| `game` | `GAME_ID` | Detailed game state (boxscore, period scores, plays) |
| `game-context` | `GAME_ID` | Game state + both teams' season stats |
| `team-stats` | `TEAM` | Full team stats (ESPN base + NBA.com advanced merged) |
| `roster` | `TEAM` | Team roster with player IDs and positions |
| `injuries` | `[TEAM]` | Injuries for one team or all teams |
| `standings` | | Conference standings with rankings |
| `athlete` | `ATHLETE_ID` | Individual player season stats overview |
| `schedule` | `TEAM [SEASON]` | Team schedule (default: current season) |
| `head-to-head` | `TEAM1 TEAM2` | Season head-to-head record between two teams |
| `play-by-play` | `GAME_ID` | All play events from a game |

**TEAM** accepts abbreviation (LAL, BOS), city (Los Angeles), or mascot (Lakers).

## Understanding the Request

Parse `$ARGUMENTS` for the subcommand and its arguments. If no subcommand is given, show available subcommands.

## Build and Run the Command

```bash
cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.tools.espn_api $SUBCOMMAND $ARGS
```

Run with **120000ms Bash timeout** (2 minutes). Some endpoints (team-stats, game-context) make multiple API calls.

## Present Results

All output is JSON. Summarize the key information:

- **scoreboard/live**: Number of games, each game's teams, scores, status, tip time
- **game**: Score, period, clock, boxscore highlights (FG%, 3PT%, rebounds, assists)
- **game-context**: Game state + team season records, ratings, tiers for both teams
- **team-stats**: Record, net rating, ORtg/DRtg, advanced stats (eFG%, TS%, PIE), tier
- **roster**: Player count, notable players with positions
- **injuries**: Injured players with status (out/doubtful/questionable) and description
- **standings**: Conference seeds, records, win percentages
- **athlete**: Season averages (PPG, RPG, APG, MIN, shooting splits)
- **schedule**: Upcoming and recent games with opponents and results
- **head-to-head**: Season series record, average scores, last meeting
- **play-by-play**: Key plays, scoring runs, momentum shifts

### Error handling

- `{"error": "..."}` indicates a failure — diagnose whether it's an API issue, bad input, or expected (e.g., no games today)
- Team not found → suggest valid abbreviations
- Game not found → may be wrong ID format (ESPN uses numeric IDs like `401584793`)

## Example Invocations

```
/espn-api scoreboard              → Today's games
/espn-api scoreboard 20260228     → Games on Feb 28, 2026
/espn-api live                    → Currently live games
/espn-api game 401584793          → Detailed game state
/espn-api game-context 401584793  → Game + team stats
/espn-api team-stats LAL          → Lakers full stats
/espn-api team-stats lakers       → Also works
/espn-api roster BOS              → Celtics roster
/espn-api injuries LAL            → Lakers injuries
/espn-api injuries                → All team injuries
/espn-api standings               → Conference standings
/espn-api athlete 3032977         → Player stats by ESPN ID
/espn-api schedule LAL            → Lakers schedule
/espn-api schedule LAL 2026       → Lakers 2025-26 schedule
/espn-api head-to-head LAL BOS    → Lakers vs Celtics season series
/espn-api play-by-play 401584793  → Full play-by-play
```
