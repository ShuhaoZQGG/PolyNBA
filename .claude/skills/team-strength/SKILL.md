---
name: team-strength
description: Show NBA team strength profile (record, ratings, tier, injuries, rotation) or compare two teams in a matchup with strength score and injury analysis.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: TEAM | TEAM1 TEAM2 [--log-level WARNING]
---

# Team Strength Lookup

Show a team's full strength profile or compare two teams in a matchup with strength scoring, tier comparison, and injury impact analysis.

## Understanding the Request

Parse `$ARGUMENTS` for:

| Argument | Purpose |
|----------|---------|
| `TEAM` | Single team view — record, ratings, tier, injuries, rotation |
| `TEAM1 TEAM2` | Matchup view — side-by-side comparison with strength score. First team is treated as home. |
| `--log-level LEVEL` | Logging verbosity (default: WARNING) |

Teams can be specified as abbreviations (LAL, SAC, BOS, etc.).

## Build and Run the Command

Construct the command from parsed arguments:

```bash
cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.tools.team_strength $FLAGS
```

Run with **120000ms Bash timeout** (2 minutes).

## Present Results

### Single Team Mode
Summarize:
1. **Season record** — W-L, win%, net rating, tier
2. **Ratings** — ORtg, DRtg, pace with rankings
3. **Home/Away splits** and current streak
4. **Injuries** — key players OUT/Doubtful with EIR
5. **Rotation** — top 8 players with PPG, minutes, EIR, role
6. **Bench depth** assessment

### Matchup Mode
Summarize:
1. **Side-by-side comparison** — record, net rating, tier, ratings, home/away, streak
2. **Strength score** — -100 to +100 with advantage direction
3. **Tier mismatch** if applicable
4. **Injuries** for both teams with EIR
5. **Injury impact** score, replacement offset, and net effect
6. **Reasoning** — plain-English assessment of the matchup

## Example Invocations

```
/team-strength LAL              -> Lakers full profile
/team-strength BOS              -> Celtics full profile
/team-strength LAL SAC          -> Lakers (home) vs Kings (away) matchup
/team-strength OKC DEN          -> Thunder (home) vs Nuggets (away) matchup
/team-strength --log-level INFO LAL  -> Verbose output for debugging
```
