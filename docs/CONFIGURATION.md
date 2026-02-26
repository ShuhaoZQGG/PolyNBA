# PolyNBA Configuration Reference

This document covers every configurable setting in PolyNBA, how they interact, and common combinations for different trading styles.

---

## Table of Contents

1. [Configuration Hierarchy](#configuration-hierarchy)
2. [Environment Variables](#environment-variables)
3. [Main Config (config.yaml)](#main-config)
4. [Strategy Files](#strategy-files)
5. [Profiles](#profiles)
6. [Command-Line Arguments](#command-line-arguments)
7. [Common Setting Combinations](#common-setting-combinations)
8. [Strategy Replay Tool](#strategy-replay-tool)

---

## Configuration Hierarchy

Settings are resolved in this order (later overrides earlier):

```
config.yaml  <  profile YAML (--config)  <  CLI arguments (--min-edge, etc.)
```

Strategy-level settings (entry rules, exit rules, position sizing) come from strategy YAML files and can be partially overridden by global config or CLI flags.

---

## Environment Variables

Defined in `.env` at the project root.

| Variable | Required | Description |
|----------|----------|-------------|
| `POLYMARKET_PRIVATE_KEY` | Live mode | Ethereum private key for on-chain trading |
| `POLYMARKET_BUILDER_API_KEY` | Optional | Polymarket builder API key |
| `POLYMARKET_BUILDER_SECRET_KEY` | Optional | Polymarket builder secret |
| `POLYMARKET_BUILDER_PASSPHRASE` | Optional | Polymarket builder passphrase |
| `POLYMARKET_FUNDER_ADDRESS` | Optional | Funding wallet address (0x...) |
| `ANTHROPIC_API_KEY` | For Claude | Claude AI API key (sk-ant-...) |
| `POLYGON_RPC_URL` | Optional | Custom RPC endpoint (default: `https://polygon-rpc.com`) |
| `CHAIN_ID` | Optional | Blockchain chain ID (default: `137` for Polygon) |

---

## Main Config

**File:** `polynba/config/config.yaml`

### Mode & Bankroll

| Setting | Default | Description |
|---------|---------|-------------|
| `mode` | `paper` | `paper` (simulated) or `live` (real money) |
| `bankroll` | `500.0` | Starting capital in USDC |
| `active_strategies` | `["conservative"]` | List of strategy YAML filenames (without `.yaml`) |

### Main Loop

| Setting | Default | Description |
|---------|---------|-------------|
| `loop.interval_seconds` | `30` | Seconds between each bot iteration |
| `loop.max_iterations` | `null` | Max iterations before stopping (`null` = unlimited) |

### Data Sources

| Setting | Default | Description |
|---------|---------|-------------|
| `data.primary_source` | `espn` | NBA data provider (`espn` or `nba`) |
| `data.cache.live_game_ttl` | `15` | Live game data cache in seconds |
| `data.cache.scoreboard_ttl` | `30` | Scoreboard cache in seconds |
| `data.cache.team_stats_ttl` | `3600` | Team stats cache in seconds (1 hour) |

### Claude AI

| Setting | Default | Description |
|---------|---------|-------------|
| `apis.claude.model` | `claude-haiku-4-5-20251001` | Model ID for analysis |
| `apis.claude.daily_budget_usd` | `10.0` | Max daily API spend |
| `apis.claude.min_interval_seconds` | `120` | Minimum seconds between Claude calls |
| `apis.claude.enabled` | `true` | Enable/disable Claude analysis |

### Polymarket API

| Setting | Default | Description |
|---------|---------|-------------|
| `apis.polymarket.host` | `https://clob.polymarket.com` | CLOB API endpoint |
| `apis.polymarket.gamma_api` | `https://gamma-api.polymarket.com` | Market discovery endpoint |
| `apis.polymarket.rpc_url` | `https://polygon-rpc.com` | Polygon RPC |
| `apis.polymarket.chain_id` | `137` | Polygon mainnet |
| `apis.polymarket.websocket_url` | `wss://ws-subscriptions-clob...` | Real-time price feed |
| `apis.polymarket.discovery.cache_ttl_seconds` | `300` | Market discovery cache (5 min) |
| `apis.polymarket.prices.poll_interval_seconds` | `15` | Price refresh frequency |
| `apis.polymarket.prices.fallback_to_simulated` | `true` | Use simulated prices when no real market found |
| `apis.polymarket.prices.min_liquidity_usdc` | `100` | Minimum market liquidity to trade |

### Edge Detection (Buy Filters)

These control when the bot opens a position.

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `edge.min_edge_percent` | `5.0` | 0-100 | Minimum edge % to enter a trade |
| `edge.max_edge_percent` | `50.0` | 0-100 | Maximum edge % (filters stale/suspicious data) |
| `edge.min_confidence` | `5` | 1-10 | Minimum analysis confidence score |
| `edge.min_market_price` | `0.10` | 0-1 | Don't trade extreme underdogs below this price |
| `edge.max_market_price` | `0.90` | 0-1 | Don't trade extreme favorites above this price |
| `edge.min_time_remaining_seconds` | `300` | seconds | Minimum game time remaining (default 5 min) |
| `edge.exclude_overtime` | `false` | bool | Block trading during overtime |

### Exit Rules (Sell Overrides)

Global overrides applied on top of strategy-specific exit rules. Set to `null` to defer to the strategy YAML.

| Setting | Default | Description |
|---------|---------|-------------|
| `exit.stop_loss_percent` | `null` | Global stop loss % (overrides strategy) |
| `exit.exit_before_seconds` | `null` | Exit when game has <= N seconds left |
| `exit.profit_target_percent` | `null` | Global take-profit % (overrides strategy buckets) |

### Risk Management

Hard limits enforced by the RiskManager regardless of strategy.

| Setting | Default | Description |
|---------|---------|-------------|
| `risk.max_position_usdc` | `100` | Max size of a single position |
| `risk.max_total_exposure_usdc` | `500` | Max total capital across all open positions |
| `risk.max_daily_loss_usdc` | `100` | Daily loss circuit breaker |
| `risk.max_concurrent_positions` | `5` | Max number of simultaneous positions |
| `risk.max_position_per_market` | `2` | Max positions per game/market |
| `risk.min_order_size_usdc` | `5` | Skip orders below this size |
| `risk.max_order_size_usdc` | `50` | Cap individual order size |
| `risk.min_position_usdc` | `null` | Global min position size (`null` = use strategy) |

### Capital Allocation

| Setting | Default | Description |
|---------|---------|-------------|
| `allocation.max_portfolio_exposure` | `0.50` | Max fraction of bankroll deployable (50%) |
| `allocation.low_risk_percent` | `0.50` | % of bettable capital for low-risk signals |
| `allocation.medium_risk_percent` | `0.35` | % of bettable capital for medium-risk signals |
| `allocation.high_risk_percent` | `0.15` | % of bettable capital for high-risk signals |

### Position Sizing

| Setting | Default | Description |
|---------|---------|-------------|
| `position_sizing.kelly_multiplier_override` | `null` | Global Kelly multiplier (`null` = use strategy value) |

### Conflict Resolution

| Setting | Default | Description |
|---------|---------|-------------|
| `trading.conflict_min_confidence` | `7` | When strategies disagree, only take side with confidence >= this |

### Logging

| Setting | Default | Description |
|---------|---------|-------------|
| `logging.level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `logging.file` | `polynba.log` | Log output file |
| `logging.format` | standard | Python logging format string |

### Performance Tracking

| Setting | Default | Description |
|---------|---------|-------------|
| `performance.track_trades` | `true` | Record all trades for analysis |
| `performance.save_interval_minutes` | `15` | How often to write performance data |
| `performance.report_file` | `performance.json` | Output file for P&L metrics |

### Portfolio Display

| Setting | Default | Description |
|---------|---------|-------------|
| `portfolio_display.interval` | `1` | Show summary every N iterations (0 to disable) |
| `portfolio_display.compact` | `false` | Use compact one-line format |

### Command Server

| Setting | Default | Description |
|---------|---------|-------------|
| `command_server.enabled` | `true` | Enable interactive command socket |
| `command_server.host` | `127.0.0.1` | Listen address |
| `command_server.port` | `8765` | Listen port |

---

## Strategy Files

**Directory:** `polynba/config/strategies/`

Each strategy YAML defines its own entry rules, exit rules, position sizing, and risk limits. The bot loads whichever strategies are listed in `active_strategies`.

### Conservative (`conservative.yaml`)

Low-risk mean reversion. High conviction, small positions.

| Category | Setting | Value |
|----------|---------|-------|
| **Entry** | min edge | 8.0% |
| | min confidence | 6 |
| | min time remaining | 300s (5 min) |
| | price range | 0.15 - 0.85 |
| | risk flags | must be empty |
| **Exit** | profit target (>12 min) | 15% |
| | profit target (6-12 min) | 10% |
| | profit target (<6 min) | 5% |
| | stop loss | 10% |
| | time exit | 60s before end |
| **Sizing** | Kelly multiplier | 0.25 (quarter Kelly) |
| | max position | $100 |
| | min position | $10 |
| **Risk** | max concurrent | 3 |
| | max daily loss | $150 |
| | max per game | 1 |
| **Weights** | market sentiment | 0.40 |
| | game context | 0.35 |
| | team strength | 0.25 |

### Aggressive (`aggressive.yaml`)

High-risk, wider entry criteria, larger positions.

| Category | Setting | Value |
|----------|---------|-------|
| **Entry** | min edge | 3.0% |
| | min confidence | 5 |
| | min time remaining | 180s (3 min) |
| | price range | 0.10 - 0.90 |
| **Exit** | profit target (>12 min) | 20% |
| | profit target (6-12 min) | 12% |
| | profit target (<6 min) | 6% |
| | stop loss | 15% |
| | time exit | 30s before end |
| **Sizing** | Kelly multiplier | 0.40 |
| | max position | $250 |
| | min position | $25 |
| **Risk** | max concurrent | 5 |
| | max daily loss | $300 |
| | max per game | 2 |
| **Weights** | market sentiment | 0.45 |
| | game context | 0.35 |
| | team strength | 0.20 |

### Contrarian (`contrarian.yaml`)

Medium-risk, targets extreme market overreactions on underdogs.

| Category | Setting | Value |
|----------|---------|-------|
| **Entry** | min mispricing | 10.0% |
| | min confidence | 6 |
| | min time remaining | 600s (10 min) |
| | underdog price | <= 0.40 |
| | max score diff | 20 (not a blowout) |
| **Exit** | profit target (>12 min) | 25% |
| | profit target (6-12 min) | 15% |
| | profit target (<6 min) | 8% |
| | stop loss | 12% |
| | time exit | 120s before end |
| **Sizing** | Kelly multiplier | 0.30 |
| | max position | $150 |
| | min position | $15 |
| **Risk** | max concurrent | 4 |
| | max daily loss | $200 |
| | max per game | 1 |
| **Weights** | market sentiment | 0.50 |
| | game context | 0.30 |
| | team strength | 0.20 |

---

## Profiles

**Directory:** `polynba/config/profiles/`

Pre-built YAML files that set mode + strategy + risk as a single unit. Load with `--config`.

| Profile | Mode | Bankroll | Strategies | Min Edge | Exposure | Max Position | Max Daily Loss | Concurrent |
|---------|------|----------|------------|----------|----------|--------------|----------------|------------|
| `paper_conservative_low` | paper | $150 | conservative | 6.0% | 35% | $40 | $50 | 2 |
| `paper_conservative_medium` | paper | $500 | conservative | 5.0% | 50% | $100 | $100 | 4 |
| `paper_balanced_medium` | paper | $500 | conservative + aggressive | 5.0% | 50% | $100 | $100 | 5 |
| `paper_aggressive_high` | paper | $1000 | aggressive | 5.0% | 55% | $200 | $150 | 5 |
| `live_minimal` | live | $50 | conservative | 8.0% | 25% | $20 | $25 | 1 |
| `live_conservative_low` | live | $150 | conservative | 6.0% | 35% | $40 | $50 | 2 |
| `live_balanced_medium` | live | $500 | conservative + aggressive | 5.0% | 50% | $100 | $100 | 5 |
| `live_aggressive_high` | live | $1000 | aggressive | 3.0% | 55% | $200 | $150 | 5 |

**Key difference between paper and live profiles:** Live profiles set `fallback_to_simulated: false` so the bot only trades on real Polymarket data.

---

## Command-Line Arguments

CLI flags override config YAML values.

### Mode & Execution

```
--mode {paper,live}             Trading mode
--config PATH                   Path to a profile/config YAML
--strategies NAME [NAME ...]    Active strategies by name
--bankroll FLOAT                Starting capital (USDC)
--interval INT                  Loop interval (seconds)
--max-iterations INT            Max iterations (default: unlimited)
--once                          Run one iteration and exit
--test-game                     Use mock test game data
--test-game-scenario NAME       Game scenario (home_blowout, close_game, etc., or random)
--test-game-ticks INT           Number of simulated price ticks (default: 20)
--no-claude                     Disable Claude AI analysis
--log-level {DEBUG,INFO,...}    Logging verbosity
--analyze                       Print performance analysis and exit
```

### Edge Overrides

```
--min-edge PCT                  Override edge.min_edge_percent
--max-edge PCT                  Override edge.max_edge_percent
--min-confidence N              Override edge.min_confidence
--min-market-price P            Override edge.min_market_price
--max-market-price P            Override edge.max_market_price
--min-time-remaining SECS       Override edge.min_time_remaining_seconds
--exclude-overtime              Block overtime trading
--no-exclude-overtime           Allow overtime trading
```

### Exit Overrides

```
--stop-loss-pct PCT             Global stop loss %
--exit-before-seconds SECS      Exit when game time <= SECS
--profit-target-pct PCT         Global take-profit %
```

### Risk & Sizing Overrides

```
--max-portfolio-exposure PCT    Override allocation.max_portfolio_exposure
--conflict-min-confidence N     Override trading.conflict_min_confidence
--kelly-multiplier X            Override position_sizing.kelly_multiplier_override
--min-position-usdc USD         Override risk.min_position_usdc
```

### Game Selection

```
--games "1,3"                   Trade specific games (1-based index)
--games "all"                   Trade all live games
```

### Command Server

```
--send-command STR              Send command to a running bot instance
--command-host HOST             Override command_server.host
--command-port INT              Override command_server.port
--command-timeout FLOAT         Command timeout in seconds (default: 5.0)
--instance-id INT               Instance ID (port = 8765 + id)
```

---

## Common Setting Combinations

### 1. First-Time Paper Testing

The safest starting point. High edge requirement, small positions, low exposure.

```bash
python -m polynba --config polynba/config/profiles/paper_conservative_low.yaml
```

Key settings:
- Strategy: **conservative** only
- Min edge: **6%** (only trades strong signals)
- Kelly: **0.25** (quarter Kelly)
- Max exposure: **35%** of $150 bankroll
- Max position: **$40**
- Max concurrent: **2**
- Simulated prices: **enabled** (works without live Polymarket data)

### 2. Balanced Paper Trading

Good middle-ground for evaluating both strategies side by side.

```bash
python -m polynba --config polynba/config/profiles/paper_balanced_medium.yaml
```

Key settings:
- Strategies: **conservative + aggressive**
- Min edge: **5%**
- Kelly: **0.25** (conservative) / **0.40** (aggressive)
- Max exposure: **50%** of $500 bankroll
- Max position: **$100**
- Max concurrent: **5**
- Conflict resolution: confidence >= **7**

### 3. First Live Deployment

Minimal capital at risk. Use this to validate the full pipeline before scaling up.

```bash
python -m polynba --config polynba/config/profiles/live_minimal.yaml --max-iterations 20
```

Key settings:
- Strategy: **conservative** only
- Min edge: **8%** (very selective)
- Bankroll: **$50**
- Max exposure: **25%** ($12.50 max in play)
- Max position: **$20**, max order: **$10**
- Max concurrent: **1** position at a time
- Daily loss limit: **$25**
- Simulated prices: **disabled**
- Iteration cap: **20** (short test run)

### 4. Conservative Live Trading

Steady approach for daily operation with real capital.

```bash
python -m polynba --config polynba/config/profiles/live_conservative_low.yaml
```

Key settings:
- Strategy: **conservative**
- Min edge: **6%**
- Bankroll: **$150**
- Max exposure: **35%** (~$52 max in play)
- Max position: **$40**, max order: **$20**
- Max concurrent: **2**
- Daily loss limit: **$50**

### 5. Aggressive Live Trading

Higher risk/reward. More trades, larger positions, lower edge threshold.

```bash
python -m polynba --config polynba/config/profiles/live_aggressive_high.yaml
```

Key settings:
- Strategy: **aggressive**
- Min edge: **3%** (takes more marginal trades)
- Kelly: **0.40**
- Bankroll: **$1000**
- Max exposure: **55%** ($550 max in play)
- Max position: **$200**, max order: **$75**
- Max concurrent: **5**
- Daily loss limit: **$150**
- Stop loss: **15%** (wider than conservative's 10%)

### 6. High-Selectivity Sniper

Only trade when the edge is very large. Few trades, high conviction.

```bash
python -m polynba --mode paper --strategies conservative \
  --min-edge 12 --min-confidence 8 --bankroll 500 \
  --kelly-multiplier 0.15 --max-portfolio-exposure 0.25
```

Key settings:
- Min edge: **12%** (very selective)
- Min confidence: **8** (high conviction only)
- Kelly: **0.15** (very small positions)
- Max exposure: **25%**
- Result: few trades per night, small positions, low drawdown

### 7. Contrarian Underdog Hunter

Bet on market overreactions to runs/momentum shifts.

```bash
python -m polynba --mode paper --strategies contrarian \
  --bankroll 500 --min-edge 10 --min-confidence 6
```

Key settings:
- Strategy: **contrarian** (requires 10%+ mispricing, underdog price <= 0.40)
- Min time: **600s** (10 min, needs time for reversal)
- Kelly: **0.30**
- Stop loss: **12%**
- Profit targets: **25%/15%/8%** (higher than other strategies)
- Max per game: **1** (concentrated bets)

### 8. Multi-Strategy with Tight Risk

Run multiple strategies but cap total risk aggressively.

```bash
python -m polynba --mode paper --strategies conservative aggressive contrarian \
  --bankroll 1000 --max-portfolio-exposure 0.30 --kelly-multiplier 0.20 \
  --stop-loss-pct 8 --min-edge 6
```

Key settings:
- All three strategies active
- Global Kelly override: **0.20** (conservative sizing across all strategies)
- Global stop loss: **8%** (tighter than any individual strategy default)
- Max exposure: **30%** ($300 max in play)
- Min edge: **6%** (filters out aggressive strategy's low-edge trades)

### 9. Quick Test Run

Validate everything works with a mock game.

```bash
python -m polynba --test-game --test-game-scenario home_blowout --once --log-level DEBUG
```

Key settings:
- Uses simulated game data (no ESPN/NBA API needed)
- Scenario-driven game simulation (10 scenarios available: `home_blowout`, `away_blowout`, `close_game`, `home_comeback`, `away_comeback`, `failed_comeback`, `overtime_thriller`, `wire_to_wire`, `late_collapse`, `back_and_forth`)
- Game ends naturally; bot stops automatically after the game finishes
- Runs one iteration and exits (remove `--once` to let the full game play out)
- Debug logging for full visibility

### 10. Running Multiple Instances

Different strategies on different ports.

```bash
# Terminal 1: conservative on port 8766
python -m polynba --instance-id 1 \
  --config polynba/config/profiles/live_conservative_low.yaml

# Terminal 2: aggressive on port 8767
python -m polynba --instance-id 2 \
  --config polynba/config/profiles/live_aggressive_high.yaml

# Check status of instance 1
python -m polynba --send-command "show portfolio" --command-port 8766
```

---

## Strategy Replay Tool

Replay historical bot logs with different strategy parameters to answer "what if" questions — what trades would have been placed, and what would the P&L have been?

### Usage

```bash
python scripts/replay_strategy.py <log_path> [options]
```

The `log_path` can be a log directory (e.g., `logs/live/20260221201447_MEM_vs_MIA`) or a direct path to `full.txt`.

### Options

| Flag | Description |
|------|-------------|
| `--strategy ID` | Base strategy ID (default: auto-detected from log) |
| `--min-edge FLOAT` | Override minimum edge % |
| `--min-confidence INT` | Override minimum confidence (1-10) |
| `--stop-loss FLOAT` | Override stop loss % |
| `--profit-target FLOAT` | Override profit target % (applied uniformly to all time buckets) |
| `--kelly-mult FLOAT` | Override Kelly multiplier |
| `--max-position FLOAT` | Override max position USDC |
| `--bankroll FLOAT` | Override bankroll (default: read from log) |
| `--verbose` / `-v` | Show per-iteration entry/exit evaluation details |
| `--json` | Output as JSON instead of text table |

### Examples

```bash
# Replay with lower edge threshold
python scripts/replay_strategy.py logs/live/20260223215750_UTAH_vs_HOU --min-edge 1.0

# Replay with higher edge threshold (fewer trades)
python scripts/replay_strategy.py logs/live/20260221201447_MEM_vs_MIA --min-edge 5.0

# Replay with multiple overrides
python scripts/replay_strategy.py logs/live/20260221201447_MEM_vs_MIA \
  --min-edge 2.0 --stop-loss 10 --profit-target 5.0

# Verbose output to see every entry/exit evaluation
python scripts/replay_strategy.py logs/live/20260221201447_MEM_vs_MIA --verbose

# JSON output for programmatic consumption
python scripts/replay_strategy.py logs/live/20260221201447_MEM_vs_MIA --json 2>/dev/null
```

### How It Works

1. **Parses** the `full.txt` log into per-iteration snapshots (scores, market prices, edges, confidence)
2. **Loads** the base strategy YAML and applies your overrides (e.g., `--min-edge` patches the `minimum_edge` entry rule)
3. **Replays** each snapshot through the existing `RuleEngine`:
   - Checks exit conditions on open positions (`evaluate_exit()`)
   - Checks entry conditions for home/away sides (`evaluate_entry()`)
   - Calculates position size via `calculate_position_size()`
4. **Outputs** a report with trade log, closed/open positions, P&L summary, and comparison to the original session

### Output

The text report includes:
- **Trade log** — every entry/exit with iteration, price, USDC size, edge, and reason
- **Closed positions** — entry/exit prices, P&L in dollars and percent, hold duration
- **Open positions** — marked to market at session-end prices
- **P&L summary** — realized, unrealized, total, win rate, max drawdown
- **Comparison** — original session signal count vs replay trade count and P&L

### Limitations

- Fill prices use the logged market prices (best bid/ask snapshots), not actual order book depth
- The replay does not simulate slippage, fees, or partial fills
- Strategy rules that depend on data not in the logs (e.g., Claude AI analysis) use stub values

---

## Setting Interaction Notes

- **`edge.min_edge_percent`** is the global floor. Each strategy also has its own `minimum_edge` in entry rules. The bot applies whichever is higher.
- **`risk.*` limits** are hard caps enforced by RiskManager. They override strategy-level limits if the strategy allows more.
- **`exit.*` overrides** replace strategy exit rules when set to non-null. For example, `--stop-loss-pct 8` overrides every strategy's stop loss.
- **`kelly_multiplier_override`** scales all strategies uniformly. If conservative uses 0.25 and you set override to 0.5, effective Kelly becomes 0.125.
- **`allocation.max_portfolio_exposure`** limits total deployed capital as a fraction of current balance, not initial bankroll.
- **`fallback_to_simulated`** should be `true` for paper testing (lets you run without live markets) and `false` for live (ensures you only trade real markets).
- When **multiple strategies** are active and produce conflicting signals for the same game, `trading.conflict_min_confidence` determines the threshold for taking the trade.
