---
name: nba-api
description: Query any NBA.com API endpoint — scoreboard, boxscores, player stats (basic + advanced), team advanced stats, and play-by-play. Use when the user asks for NBA.com data, advanced stats, player indexes, or real-time game data.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: <subcommand> [args...]
---

# NBA.com API Skill

Call any NBA.com endpoint (CDN + stats.nba.com) and get structured JSON output.

## Subcommands

| Subcommand | Args | Description |
|------------|------|-------------|
| `scoreboard` | | Today's games from NBA.com (no date param — always today) |
| `live` | | Live games only |
| `boxscore` | `GAME_ID` | Game boxscore (may 403 pre-game) |
| `game` | `GAME_ID` | Full game state with boxscore + play-by-play |
| `players` | `[TEAM]` | Player index with basic + advanced stats (filter by team abbr) |
| `players-full` | `[TEAM]` | Full player stats from 3 NBA.com calls (base + advanced merged) |
| `player-stats-base` | `[SEASON]` | Per-game base stats for all players (default: 2025-26) |
| `player-stats-advanced` | `[SEASON]` | Advanced stats for all players (NR, TS%, USG%, PIE) |
| `team-stats-advanced` | `[SEASON]` | Advanced stats for all 30 teams (ORtg, DRtg, eFG%, TS%, PIE + ranks) |
| `playbyplay` | `GAME_ID` | Play-by-play events (may 403 pre-game) |

**TEAM** is a 3-letter abbreviation (LAL, BOS, GSW, etc.).

**SEASON** format: `2025-26` (default if omitted).

**GAME_ID** format: NBA.com uses IDs like `0022500785`.

## Understanding the Request

Parse `$ARGUMENTS` for the subcommand and its arguments. If no subcommand is given, show available subcommands.

## Build and Run the Command

```bash
cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.tools.nba_api $SUBCOMMAND $ARGS
```

Run with **120000ms Bash timeout** (2 minutes). stats.nba.com calls (player-stats-*, team-stats-advanced) can be slow (30+ seconds).

## Present Results

All output is JSON. Summarize the key information:

- **scoreboard/live**: Number of games, teams, scores, game status, tip times
- **boxscore**: Score, period, boxscore stats (FG/3PT/FT, rebounds, assists, turnovers)
- **game**: Full game state including boxscore + recent play-by-play events
- **players**: Player count per team, top scorers, key stats (PPG, RPG, APG)
- **players-full**: Complete stats including FG%, 3P%, FT%, STL, BLK, advanced (NR, TS%, USG%, PIE)
- **player-stats-base**: League-wide per-game stats (FG%, 3P%, FT%, STL, BLK, TOV, MIN)
- **player-stats-advanced**: League-wide advanced stats (ORtg, DRtg, NR, TS%, USG%, PIE)
- **team-stats-advanced**: All 30 teams' advanced metrics with league rankings
- **playbyplay**: Key plays, scoring events, game flow

### Error handling

- `{"error": "403 Forbidden..."}` — boxscore/playbyplay not available for pre-game or old games
- stats.nba.com endpoints may be slow or blocked without curl_cffi (TLS fingerprinting)
- If `players` or `players-full` returns empty for a team, verify the abbreviation is correct

## Example Invocations

```
/nba-api scoreboard                 → Today's games
/nba-api live                       → Currently live games
/nba-api boxscore 0022500785        → Game boxscore
/nba-api game 0022500785            → Full game state + plays
/nba-api players LAL                → Lakers player stats
/nba-api players                    → All ~500 players
/nba-api players-full LAL           → Lakers full stats (3 API calls)
/nba-api player-stats-base          → All players base stats (current season)
/nba-api player-stats-base 2024-25  → Last season's base stats
/nba-api player-stats-advanced      → All players advanced stats
/nba-api team-stats-advanced        → All 30 teams advanced stats + rankings
/nba-api team-stats-advanced 2024-25 → Last season's team advanced stats
/nba-api playbyplay 0022500785      → Play-by-play events
```
