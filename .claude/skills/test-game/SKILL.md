---
name: test-game
description: Run a test game simulation with mock NBA data and simulated prices. Use when the user asks to test game, simulate, run test, mock game, test trading, or try a scenario.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: [scenario] [--strategies X] [--min-edge N] [...]
---

# Test Game Skill

Run a full trading simulation with mock NBA data and simulated prices — no real APIs needed.

## Understanding the Request

Parse `$ARGUMENTS` to determine:

### 1. Scenario

Extract the scenario name (first positional argument, or `random` if omitted):

| Scenario | Description |
|---|---|
| `home_blowout` | Home team dominates start to finish (+22 lead) |
| `away_blowout` | Away team dominates start to finish (-22 lead) |
| `close_game` | Tight throughout, home wins by ~2 |
| `home_comeback` | Home trails by 12 at half, rallies to win by 4 |
| `away_comeback` | Away trails by 12 at half, rallies to win by 4 |
| `failed_comeback` | Home trails big, closes gap but still loses by 4 |
| `overtime_thriller` | Tied at end of regulation, home wins in OT |
| `wire_to_wire` | Home leads wire-to-wire by ~6 |
| `late_collapse` | Home up 12 in Q3, collapses and loses by 3 |
| `back_and_forth` | Lead swaps multiple times, home wins by 5 |
| `random` | Pick a random scenario (default) |

If the user says just "blowout", infer `home_blowout`.

### 2. Strategy Overrides

`--strategies X Y` — one or more of:

**Base strategies:** `aggressive`, `conservative`, `contrarian`, `very_aggressive_fast`, `conviction`

**Recommended configs:** `rec1_aggressive_e2_sl15_pt2_k06`, `rec2_aggressive_e1_sl20_pt2_k06`, `rec3_aggressive_e2_sl12_pt5_k06`, `rec4_aggressive_e15_sl20_pt3_k06`, `rec5_aggressive_e2_sl20_pt2_k06`

### 3. CLI Flags

Pass through any of these flags as-is:

| Flag | Type | Description |
|---|---|---|
| `--min-edge PCT` | float | Minimum edge % to consider a bet |
| `--max-edge PCT` | float | Maximum edge % (filter suspiciously high) |
| `--min-confidence N` | int | Minimum confidence 1-10 |
| `--stop-loss-pct PCT` | float | Global stop-loss % |
| `--profit-target-pct PCT` | float | Global take-profit % |
| `--kelly-multiplier X` | float | Scale Kelly fraction (e.g. 0.5 = half) |
| `--bankroll N` | float | Initial bankroll in USDC (default: 500) |
| `--min-market-price P` | float | Minimum market price 0-1 |
| `--max-market-price P` | float | Maximum market price 0-1 |
| `--min-time-remaining SECS` | int | Min seconds remaining to allow buy |
| `--exit-before-seconds SECS` | int | Exit when time left <= SECS |
| `--max-portfolio-exposure PCT` | float | Max fraction of balance bettable 0-1 |
| `--conviction-min-probability P` | float | Min probability for conviction bets (0-1) |
| `--min-position-usdc USD` | float | Skip signal if position below USD |
| `--config PATH` | path | Path to configuration file |
| `--interval N` | int | Loop interval in seconds (default: 5 for test) |
| `--no-claude` | flag | Disable Claude AI analysis |
| `--once` | flag | Run only one iteration (quick check) |
| `--log-level LEVEL` | str | DEBUG, INFO, WARNING, or ERROR |

## Build and Run the Command

Construct the command:

```
cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba --test-game --test-game-scenario SCENARIO [flags...]
```

Rules:
- Always use `.venv/bin/python` (project virtualenv)
- Default `--test-game-scenario random` if no scenario given
- Pass through all recognized CLI flags exactly as the user provided them
- Use a **10-minute Bash timeout** (600000ms) since games can run long with default interval

Run the command with Bash.

## Present Results

After the run completes, summarize:

1. **Scenario & config** — which scenario ran, which strategies were active, any parameter overrides
2. **Trades made** — entries and exits with prices, edges, and sides
3. **P&L summary** — realized P&L, unrealized P&L, total return
4. **Key observations** — notable edge signals, conviction signals, stop-loss/profit-target triggers, game flow vs. trading activity

## Example Invocations

```
/test-game                                    → random scenario, default strategy
/test-game home_blowout                       → specific scenario
/test-game close_game --strategies aggressive  → scenario + strategy override
/test-game --strategies conviction --conviction-min-probability 0.65
/test-game overtime_thriller --min-edge 2.0 --bankroll 1000
/test-game --once                             → single iteration (quick check)
/test-game blowout --no-claude                → home_blowout without AI analysis
/test-game --strategies rec1_aggressive_e2_sl15_pt2_k06  → recommended config
```
