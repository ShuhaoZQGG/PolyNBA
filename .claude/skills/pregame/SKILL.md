---
name: pregame
description: Run the pre-game NBA betting advisor to scan today's games, compute win probabilities, compare to Polymarket odds, and output bet suggestions with Kelly sizing. Use when the user asks for pre-game analysis, daily picks, or betting recommendations.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: [--bankroll 500] [--min-edge 2.0] [--kelly-fraction 0.25] [--model-weight 0.30] [--no-claude] [--no-hold] [--date YYYYMMDD] [--min-speculate-prob 0.72] [--speculate-kelly 0.15] [--log-level WARNING]
---

# Pre-Game Betting Advisor

Scan today's NBA games with Polymarket markets, compute independent win probabilities using team strength/injuries/H2H, and output bet recommendations with Kelly-optimal sizing.

## Understanding the Request

Parse `$ARGUMENTS` for optional flags:

| Flag | Default | Purpose |
|------|---------|---------|
| `--bankroll N` | 500 | Available bankroll in USDC |
| `--min-edge N` | 2.0 | Minimum edge % to recommend a bet |
| `--kelly-fraction N` | 0.25 | Kelly conservatism (0.25 = quarter-Kelly) |
| `--model-weight N` | 0.30 | Model weight in probability blend (market gets 1-N) |
| `--no-claude` | off | Disable Claude AI qualitative analysis |
| `--no-hold` | off | Hide HOLD recommendations, show only actionable bets |
| `--date YYYYMMDD` | today | Date to scan (e.g. 20260228) |
| `--min-speculate-prob N` | 0.72 | Minimum model probability to trigger SPECULATE verdict |
| `--speculate-kelly N` | 0.15 | Kelly fraction for SPECULATE bets (more conservative) |
| `--log-level LEVEL` | WARNING | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |

## Build and Run the Command

Construct the command from parsed arguments:

```bash
cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.pregame $FLAGS
```

Run with **120000ms Bash timeout** (2 minutes).

## Present Results

After the run completes, summarize:

1. **Games scanned** — How many pre-game NBA games were found today
2. **Markets matched** — How many games had active Polymarket markets
3. **Recommendations** — List each BET and SPECULATE recommendation with:
   - Game (Away @ Home)
   - Model probability vs market probability
   - Edge percentage
   - Suggested bet amount
   - Confidence rating
   - Key factors driving the recommendation
   - Claude AI analysis (for SPECULATE verdicts when --no-claude is not set)
4. **HOLD games** — Brief mention of games where no edge was found (if --no-hold was not set)
5. **Overall assessment** — Any notable patterns (e.g., "heavy favorites across the board", "multiple edges found")

## Execute Bets

After presenting results, for each BET or SPECULATE recommendation that includes an `Execute:` command:

1. Ask the user for confirmation: **"Place $X on TEAM at Y price? (y/n)"**
2. Only on explicit confirmation (`y`, `yes`, `confirm`), run the execute command:
   ```bash
   cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.pregame.execute --token-id ... --market-id ... --side buy --size ... --price ...
   ```
3. Report the result (order ID on success, error message on failure).
4. Move to the next BET recommendation and repeat.

**Never execute without explicit user confirmation for each bet.**

## Example Invocations

```
/pregame                              -> Default: $500 bankroll, 2% min edge
/pregame --bankroll 1000              -> Higher bankroll
/pregame --min-edge 3.0 --no-hold    -> Only show strong edges
/pregame --log-level INFO             -> Verbose output for debugging
/pregame --model-weight 0.50          -> Trust model more vs market
/pregame --date 20260228              -> Scan a specific date
/pregame --min-speculate-prob 0.80    -> Only speculate on very strong convictions
/pregame --no-claude                  -> SPECULATE based on model threshold only
```
