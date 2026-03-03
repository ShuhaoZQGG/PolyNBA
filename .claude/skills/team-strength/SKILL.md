---
name: team-strength
description: Show NBA team strength profile (record, ratings, tier, injuries, rotation), compare two teams in a matchup, rank all 30 teams by any metric, or save/load team snapshots.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: TEAM | TEAM1 TEAM2 | --snapshot | --rankings [METRIC] [--from-snapshot PATH] [--log-level WARNING]
---

# Team Strength Lookup

Show a team's full strength profile, compare two teams in a matchup, rank all 30 teams by any metric, or save/load team snapshots for offline use.

## Understanding the Request

Parse `$ARGUMENTS` for:

| Argument | Purpose |
|----------|---------|
| `TEAM` | Single team view — record, ratings, tier, injuries, rotation |
| `TEAM1 TEAM2` | Matchup view — side-by-side comparison with strength score. First team is treated as home. |
| `--snapshot [PATH]` | Fetch all 30 teams and save to snapshot JSON (default: `polynba/data/snapshots/teams_YYYYMMDD.json`) |
| `--rankings [METRIC]` | Rank all 30 teams by metric (default: `net_rating`). Metrics: `net_rating`, `offensive_rating`, `defensive_rating`, `effective_field_goal_percentage`, `true_shooting_percentage`, `pace`, `team_pie`, `assist_to_turnover`, `turnover_pct`, `rebound_percentage`, `win_percentage` |
| `--from-snapshot PATH` | Load team data from a snapshot file instead of API (works with all modes) |
| `--top N` | Number of teams to show in rankings (default: 30) |
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
4. **Advanced stats** — eFG%, TS%, AST%, AST/TO, OREB%, DREB%, REB%, TOV%, PIE with league rankings (from NBA.com)
5. **Four Factors** — shooting (eFG%), turnovers (TOV%), rebounding (OREB%), free throws (FT%)
6. **Injuries** — key players OUT/Doubtful with EIR
7. **Rotation** — top 8 players with PPG, minutes, EIR, role
8. **Bench depth** assessment

### Matchup Mode
Summarize:
1. **Side-by-side comparison** — record, net rating, tier, ratings, home/away, streak, plus advanced stats (eFG%, TS%, AST/TO, TOV%, REB%, PIE)
2. **Strength score** — -100 to +100 with advantage direction
3. **Tier mismatch** if applicable
4. **Injuries** for both teams with EIR
5. **Injury impact** score, replacement offset, and net effect
6. **Reasoning** — plain-English assessment of the matchup

### Rankings Mode
Summarize:
1. **Ranked table** — all 30 teams sorted by the chosen metric
2. **Context columns** — record plus 4 related metrics (net rating, ORtg, DRtg, pace, win%)
3. **Sort direction** — higher is better for most metrics; DRtg and TOV% sort ascending

### Snapshot Mode
Summarize:
1. **File saved** — path and team count
2. **Summary table** — all 30 teams sorted by net rating with record, ORtg, DRtg, tier

Note: When using `--from-snapshot`, injuries and rotation data are not available (only team stats).

## Example Invocations

```
/team-strength LAL              -> Lakers full profile
/team-strength BOS              -> Celtics full profile
/team-strength LAL SAC          -> Lakers (home) vs Kings (away) matchup
/team-strength --snapshot       -> Save all 30 teams to default path
/team-strength --rankings       -> All 30 teams by net rating (live API)
/team-strength --rankings offensive_rating  -> All 30 teams by ORtg
/team-strength --rankings defensive_rating --top 10  -> Top 10 defenses
/team-strength --rankings win_percentage --from-snapshot polynba/data/snapshots/teams_20260228.json  -> Offline rankings
/team-strength LAL --from-snapshot polynba/data/snapshots/teams_20260228.json  -> Single team from snapshot
/team-strength LAL BOS --from-snapshot polynba/data/snapshots/teams_20260228.json  -> Matchup from snapshot
/team-strength --log-level INFO LAL  -> Verbose output for debugging
```
