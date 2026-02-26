---
name: replay
description: Replay historical NBA bot game logs with different strategy parameters to analyze trading performance. Use when the user asks to replay a game, backtest a strategy, or analyze past trading sessions.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: <game or log path> [--min-edge N] [--strategy ID] [...]
---

# Replay Strategy Skill

You are replaying historical bot logs to analyze how different strategy parameters would have performed.

## Understanding the Request

The user wants to replay a game log. Parse `$ARGUMENTS` to determine:

1. **Which game(s)** - could be:
   - A team name (e.g., "MEM vs MIA", "UTAH", "PHX")
   - A specific log path (e.g., `logs/live/20260221201447_MEM_vs_MIA`)
   - "latest", "last game", "today's games", "all live games"
   - A date (e.g., "Feb 23", "yesterday")

2. **Strategy overrides** - any of:
   - `--min-edge N` (minimum edge %)
   - `--min-confidence N` (1-10)
   - `--stop-loss N` (stop loss %)
   - `--profit-target N` (profit target %)
   - `--kelly-mult N` (Kelly multiplier)
   - `--max-position N` (max position USDC)
   - `--bankroll N` (override bankroll)
   - `--strategy ID` (strategy ID: aggressive, conservative, contrarian, very_aggressive_fast)

## Steps

### Step 1: Find the log file(s)

If the user gave a specific path, use it directly.

Otherwise, search for matching logs:
- List logs with: `ls logs/live/` and `ls logs/paper/`
- Log directories follow pattern: `YYYYMMDDHHMMSS_AWAY_vs_HOME/`
- Match by team abbreviation, date, or recency
- Prefer `logs/live/` over `logs/paper/` unless specified

If multiple matches, show them and ask the user to pick, or replay all if they said "all".

### Step 2: Run the replay

Execute the replay script:

```bash
cd /Users/shuhaozhang/Project/PolyNBA && python scripts/replay_strategy.py <log_path> [options] --verbose
```

Always include `--verbose` to get per-iteration details.

Pass through any strategy override flags the user specified.

### Step 3: Present the results

After running the replay, present a clean summary to the user:

- Game info (teams, date)
- Strategy used and any overrides applied
- Key trades made (entry/exit with prices and edges)
- P&L summary (realized, unrealized, total)
- Win rate and max drawdown
- Comparison to original session

If the user asked to compare multiple parameter sets, run replays sequentially and present a comparison table.

## Available Strategies

- `aggressive` - Main aggressive strategy
- `conservative` - Conservative parameters
- `contrarian` - Contrarian approach
- `very_aggressive_fast` - Very aggressive with fast execution

## Example Invocations

- `/replay UTAH vs HOU --min-edge 1.0` - Replay UTAH/HOU game with 1% min edge
- `/replay MEM vs MIA --min-edge 5.0` - Replay MEM/MIA with 5% min edge
- `/replay latest` - Replay the most recent live game with default strategy
- `/replay all today --min-edge 2.0` - Replay all of today's games
- `/replay logs/live/20260223215750_UTAH_vs_HOU --min-edge 1.0 --strategy conservative`
