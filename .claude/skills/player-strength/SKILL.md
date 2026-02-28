---
name: player-strength
description: Look up NBA player strength ratings (EIR, advanced stats like TS%, USG%, NR, bench/starter role) for a team rotation or individual player search.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: --team LAL | --player "LeBron" [--top 8] [--log-level WARNING]
---

# Player Strength Lookup

Show NBA player Estimated Impact Ratings (EIR), advanced stats (TS%, USG%, NR, OFFRTG, DEFRTG, PIE, etc.), and bench/starter classification for a team's rotation or a specific player.

## Understanding the Request

Parse `$ARGUMENTS` for flags:

| Flag | Default | Purpose |
|------|---------|---------|
| `--team ABBR` | — | Show full rotation for a team (e.g. LAL, BOS) |
| `--player "Name"` | — | Search for a player by name substring |
| `--top N` | 8 | How many players to show |
| `--log-level LEVEL` | WARNING | Logging verbosity |

One of `--team` or `--player` is required.

## Build and Run the Command

Construct the command from parsed arguments:

```bash
cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.tools.player_strength $FLAGS
```

Run with **120000ms Bash timeout** (2 minutes).

## Present Results

Summarize the output tables showing:
1. **Compact table** — players ranked by PPG with columns: PPG, RPG, APG, MIN, TS%, USG%, NR, EIR, Role
2. **Advanced detail section** — OFFRTG, DEFRTG, AST%, AST/TO, OREB%, DREB%, REB%, PIE
3. **Roles** — Starter vs Bench classification
4. **Summary** — average EIR for starters/bench, top EIR player, best bench player

## Example Invocations

```
/player-strength --team LAL           -> Lakers top 8 rotation
/player-strength --team BOS --top 10  -> Celtics top 10
/player-strength --player "LeBron"    -> Search for LeBron across all teams
/player-strength --player "Davis"     -> Search for all players named Davis
```
