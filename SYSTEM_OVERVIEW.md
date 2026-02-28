# PolyNBA System Overview

A real-time NBA in-game trading bot for Polymarket prediction markets.

---

## Table of Contents

1. [Game Analysis Pipeline](#1-game-analysis-pipeline)
2. [Data Sources](#2-data-sources)
3. [Polymarket API Integration](#3-polymarket-api-integration)
4. [Probability Estimation Model](#4-probability-estimation-model)
5. [Trading Strategies](#5-trading-strategies)
6. [Strategy Combination & Conflict Resolution](#6-strategy-combination--conflict-resolution)
7. [Risk Management](#7-risk-management)
8. [Test Game vs Real Live Game](#8-test-game-vs-real-live-game)
9. [Replay / Backtesting System](#9-replay--backtesting-system)
10. [End-to-End Trade Example](#10-end-to-end-trade-example)

---

## 1. Game Analysis Pipeline

The system follows a multi-stage pipeline from live data ingestion to trade execution:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│  NBA Data    │───▶│  GameState   │───▶│  Probability     │───▶│  Edge        │
│  (ESPN/NBA)  │    │  Builder     │    │  Estimation      │    │  Detection   │
└──────────────┘    └──────────────┘    └──────────────────┘    └──────┬───────┘
                                                                       │
┌──────────────┐    ┌──────────────┐    ┌──────────────────┐           │
│  Order       │◀───│  Trading     │◀───│  Strategy        │◀──────────┘
│  Execution   │    │  Signals     │    │  Rule Engine     │
└──────────────┘    └──────────────┘    └──────────────────┘
        │
        ▼
┌──────────────┐    ┌──────────────┐
│  Position    │───▶│  Exit Rules  │ (profit targets, stop-loss, time stop)
│  Monitoring  │    │  Evaluation  │
└──────────────┘    └──────────────┘
```

**Steps:**

1. **Data Ingestion** — Fetch live NBA game state from ESPN API (primary) / NBA.com CDN (fallback)
2. **State Building** — Construct a `GameState` model: scores, period, clock, play events, team stats
3. **Market Discovery** — Find the matching Polymarket moneyline market for the game
4. **Price Fetching** — Get real-time order book prices from Polymarket CLOB
5. **Probability Estimation** — Three-factor model produces `ProbabilityEstimate` (estimated win prob, edge, confidence)
6. **Edge Detection** — Compare model estimate to market price, filter by minimum edge/confidence thresholds
7. **Strategy Evaluation** — Rule engine evaluates entry conditions for each enabled strategy
8. **Signal Generation** — Produce `TradingSignal` objects (BUY/SELL, size, strategy ID)
9. **Conflict Resolution** — If multiple strategies signal opposite sides on the same game, resolve by confidence
10. **Trade Execution** — Submit orders via Polymarket CLOB (live) or paper executor (paper mode)
11. **Position Monitoring** — Continuously evaluate exit conditions (profit targets, stop-losses, time stops)
12. **Reporting** — Log trades, update P&L, display portfolio summary

---

## 2. Data Sources

### ESPN API (Primary)

| Component | File | Purpose |
|-----------|------|---------|
| Client | `polynba/data/sources/espn/client.py` | Async HTTP client with rate limiting |
| Parser | `polynba/data/sources/espn/parser.py` | Extract game state, scores, play-by-play |
| Scraper | `polynba/data/sources/espn/scraper.py` | Fetch and aggregate game data |

Provides: Live scores, period/clock, play events, team stats (FG%, 3P%, rebounds, etc.)

### NBA.com CDN (Fallback)

| Component | File | Purpose |
|-----------|------|---------|
| Client | `polynba/data/sources/nba/client.py` | Async with exponential backoff retries |

- Base URL: `https://cdn.nba.com/static/json/liveData`
- Rate limit: 1 request/second (configurable)
- Timeout: 15 seconds default

### Data Models

| Model | Key Fields |
|-------|------------|
| `GameState` | period, clock (M:SS), home/away scores, differential, total seconds remaining |
| `TeamGameState` | score, timeouts remaining, fouls, period scores, shooting percentages |
| `PlayEvent` | event type, description, points scored, running score |
| `TeamStats` | FG%, 3P%, FT%, rebounds, assists, turnovers, steals, blocks |

The `DataManager` (`polynba/data/manager.py`) coordinates multiple sources with caching.

---

## 3. Polymarket API Integration

### Market Discovery

**File:** `polynba/polymarket/market_discovery.py`

1. **Fetch NBA series** from `https://gamma-api.polymarket.com/series/10345` (NBA Series ID)
2. **Filter events** by date (today ± 3 days)
3. **Fetch full event details** → extract market data
4. **Identify moneyline markets** — question pattern: "Team A vs Team B"
5. **Extract** `condition_id`, `token_ids` (home/away), team abbreviations, prices
6. **Cache** results with 300-second TTL

### Price Fetching (CLOB)

**File:** `polynba/polymarket/price_fetcher.py`

Uses `py_clob_client.ClobClient` in **Level 0 (read-only)** mode — no authentication required.

| Setting | Value |
|---------|-------|
| CLOB Host | `https://clob.polymarket.com` |
| Chain | Polygon mainnet (chain_id = 137) |

**Methods:**

| Method | Returns |
|--------|---------|
| `get_market_prices()` | `MarketPrices` — home/away mid, bid, ask, depth |
| `get_token_sell_price()` | Best bid price (for exit evaluation) |
| `get_token_price_info()` | (mid_price, best_bid, spread_pct) |

**Spread Calculation:**
```
spread_pct = (ask - bid) / mid_price × 100%
```

### Fallback Modes

When no live Polymarket market exists:

- **TimeSeriesPriceFetcher** — Pre-generated price sequences or game-state-based pricing
- **SimulatedPriceFetcher** — Stub 50/50 prices for basic testing
- **LiveTestPriceSimulator** — Game-state-aware pricing with realistic delays

---

## 4. Probability Estimation Model

**File:** `polynba/analysis/probability_calculator.py`

A three-factor model with configurable weights (normalized to 1.0):

### Factor 1: Market Sentiment (default 40%)

- Compares market odds to a score-derived win probability
- Score-based prob uses a **logistic function** of `(score_diff × time_factor)`
- Detects **overreaction** (market moved too far) or **stale odds** (market hasn't caught up)
- Output: home implied prob, fair prob, mispricing magnitude

### Factor 2: Game Context (default 35%)

- **Momentum**: Recent scoring run, which team has momentum
- **Clutch**: Is it late-game? Is it tight? Pressure level
- **Fouls**: In the bonus? Star player foul trouble?
- **Timeouts**: More timeouts = more clock control advantage

### Factor 3: Team Strength (default 25%)

- Team tier comparison (Elite / Good / Medium / Weak)
- Offensive & defensive efficiency (ORtg vs DRtg)
- Head-to-head history
- Output: home advantage score

### Output

```
ProbabilityEstimate:
  market_price      → current Polymarket price
  estimated_prob    → model's estimated probability
  edge              → estimated_prob - market_price
  edge_pct          → edge as a percentage
  confidence        → 1–10 score (factor agreement + magnitude + freshness)
  factor_scores     → individual factor contributions
```

Edge is capped at ±25% of market odds (`MAX_ADJUSTMENT = 0.25`).

### Optional: Claude AI Analysis

**File:** `polynba/analysis/claude_analyzer.py`

- Triggered on high-probability situations or unusual game states
- Receives formatted game state, market prices, quant scores
- Returns structured risk flags and qualitative insights
- Per-game deduplication to avoid redundant API calls
- Separate budget tracking

---

## 5. Trading Strategies

All strategies are defined as YAML files in `polynba/config/strategies/`.

### Strategy Comparison

| Strategy | Risk | Min Edge | Min Confidence | Key Characteristic |
|----------|------|----------|----------------|--------------------|
| **conservative** | Low | 8% | 6 | Wide spread requirement (≤4%), minimum 5 minutes remaining |
| **aggressive** | High | 3% | 5 | Aggressive Kelly sizing (×0.40), wide stop-losses (25%) |
| **contrarian** | Medium | varies | 6 | Targets underdogs (<40¢), requires ≥10% mispricing |
| **conviction** | High | 1% | 7 | High prob (≥65%), hold-to-resolution, max 2 concurrent |
| **very_aggressive_fast** | High | 2% | 5 | Quick exits (30s time stop), small sizes but frequent |

### Strategy YAML Structure

```yaml
metadata:
  name: strategy_name
  description: "..."
  risk_level: low | medium | high
  enabled: true

factor_weights:
  market_sentiment: 0.40
  game_context: 0.35
  team_strength: 0.25

entry_rules:
  conditions:
    - name: "min_edge"
      type: threshold          # threshold | comparison | list_empty
      field: edge_percentage
      operator: ">="
      value: 5.0
    - name: "min_confidence"
      type: threshold
      field: confidence
      operator: ">="
      value: 6
    - name: "max_spread"
      type: threshold
      field: spread_percentage
      operator: "<="
      value: 4.0

exit_rules:
  profit_targets:              # Time-tiered profit taking
    - time_remaining_min: 1200
      target_percentage: 18.0
    - time_remaining_min: 600
      target_percentage: 12.0
    - time_remaining_min: 300
      target_percentage: 6.0

  stop_loss:
    value: 15.0                # Base stop-loss %
    exit_max_spread_percent: 15.0   # Suppress SL if spread > this
    patience_before_seconds: 600    # Suppress SL if > this time left
    max_averagedown_count: 2
    max_averagedown_multiplier: 3.0
    late_game_widening:
      - time_remaining_max: 600
        multiplier: 1.3
      - time_remaining_max: 300
        multiplier: 1.5

  time_stop:
    exit_before_seconds: 60

position_sizing:
  method: kelly_fraction       # kelly_fraction | fixed | percentage
  kelly_multiplier: 0.25
  max_position_usdc: 50.0
  min_position_usdc: 5.0
  late_game_multiplier: 1.5

risk_limits:
  max_concurrent_positions: 3
  max_daily_loss_usdc: 50.0
  max_position_per_game: 1
  max_stop_losses_per_game: 2
  max_loss_per_game_usdc: 30.0
```

### Rule Engine

**File:** `polynba/strategy/rule_engine.py`

Evaluates rules from the YAML configs:

| Rule Type | Description | Example |
|-----------|-------------|---------|
| `ThresholdRule` | Single field vs value | `edge_percentage >= 5.0` |
| `ComparisonRule` | Two fields compared | `field_a >= field_b` |
| `ListEmptyRule` | Check if a list field is empty | `risk_flags is empty` |

**Entry evaluation:** All conditions must pass (AND logic).

**Exit evaluation:** Evaluates profit targets, dynamic stop-loss, and time stops.

---

## 6. Strategy Combination & Conflict Resolution

### Strategy Manager

**File:** `polynba/strategy/strategy_manager.py`

### Capital Allocation by Risk Level

| Risk Level | Strategies | Bankroll Allocation |
|------------|------------|---------------------|
| Low | conservative | 50% |
| Medium | contrarian | 35% |
| High | aggressive, conviction, very_aggressive_fast | 15% |

### Multi-Strategy Orchestration

1. Each edge opportunity is evaluated against **all enabled strategies**
2. Each strategy that passes all entry rules generates a `TradingSignal`
3. Signals are collected across all strategies

### Conflict Resolution

When two strategies signal **opposite sides** on the same game:

- If either signal has confidence ≥ 7 (configurable), take the higher-confidence signal
- If neither meets the threshold, **skip the trade entirely**
- Same-side signals from multiple strategies are allowed (each trades independently with its own allocation)

### Recommendation Profiles

**Directory:** `polynba/config/recommends/`

Pre-configured strategy + parameter override combinations for quick deployment:

```
rec1_aggressive_e2_sl15_pt2_k06.yaml  → aggressive + edge 2%, stop-loss 15%, profit target 2%, kelly ×0.6
rec2_aggressive_e1_sl20_pt2_k06.yaml  → aggressive + edge 1%, stop-loss 20%
rec3_aggressive_e2_sl12_pt5_k06.yaml  → aggressive + edge 2%, stop-loss 12%, profit target 5%
rec4_aggressive_e15_sl20_pt3_k06.yaml → aggressive + edge 1.5%, stop-loss 20%, profit target 3%
rec5_aggressive_e2_sl20_pt2_k06.yaml  → aggressive + edge 2%, stop-loss 20%
```

---

## 7. Risk Management

### Position Monitoring

**File:** `polynba/trading/position_tracker.py`

Tracks each position:
- Entry price, size, side (BUY/SELL), strategy ID
- `unrealized_pnl = size × (current_price - entry_price)`
- `unrealized_pnl_percent = pnl / total_cost × 100`

### Risk Manager

**File:** `polynba/trading/risk_manager.py`

| Guard | Default | Purpose |
|-------|---------|---------|
| Max position size | 100 USDC | Cap single trade |
| Max total exposure | 500 USDC | Cap portfolio |
| Max concurrent positions | 5 | Limit open trades |
| Max position per market | 2 | Diversification |
| Max loss per trade | 25 USDC | Single-trade circuit breaker |
| Max daily loss | 100 USDC | Daily circuit breaker |
| Hard loss limit | 30% | Emergency stop |

### Dynamic Stop-Loss Logic

1. **Base %** — Strategy-defined (e.g., 15–25%)
2. **Spread Guard** — Suppress stop-loss if bid-ask spread > threshold (prices unreliable in thin books)
3. **Patience Guard** — Suppress stop-loss if > N seconds remain (early-game variance is expected)
4. **Price-Based Widening** — Low-price positions (entry < $0.35) get wider stops:
   ```
   multiplier = min(2.0, max(1.0, 2.0 - entry_price / 0.35))
   ```
5. **Late-Game Widening** — Stop-loss widens as clock ticks down (accounts for increased volatility):
   - ≤10 min left: 1.3× base
   - ≤5 min left: 1.5× base
6. **Average Down** — Limited to N attempts, capped at M× initial cost

### Time-Tiered Profit Targets

```
≥20 min remaining → take profit at 18%
≥10 min remaining → take profit at 12%
≥5 min remaining  → take profit at 6%
```

### Time Stop

Force exit when ≤ N seconds remain (30–60s default), preventing resolution-time illiquidity.

---

## 8. Test Game vs Real Live Game

### Real Live Game

| Aspect | How It Works |
|--------|-------------|
| **NBA Data** | Live from ESPN API (real scores, clock, plays) |
| **Market Discovery** | Real Polymarket markets via Gamma API |
| **Prices** | Real order book from CLOB (`clob.polymarket.com`) |
| **Execution** | Paper (simulated fills) or Live (real orders on Polygon) |
| **Duration** | Runs until game ends or manually stopped |
| **Loop** | Continuous, configurable interval (default 30s) |

### Test Game (Simulated)

| Aspect | How It Works |
|--------|-------------|
| **NBA Data** | Synthetic game "Test Home vs Test Away" with scripted scenarios |
| **Market Discovery** | Skipped — mock market provided |
| **Prices** | Generated via random walk with configurable volatility/spread |
| **Execution** | Always paper mode |
| **Duration** | Auto-stops when Q4 clock reaches 0:00 |
| **Loop** | Same trading loop, same strategies, same rule engine |

**Activation:** `--test-game` flag or config `run.test_game: true`

### Test Game Scenarios

| Scenario | Description |
|----------|-------------|
| `home_blowout` | Home team dominates from start |
| `away_blowout` | Away team dominates from start |
| `close_game` | Tight throughout, decided late |
| `home_comeback` | Home trails big, comes back to win |
| `away_comeback` | Away trails big, comes back to win |
| `failed_comeback` | Team rallies but falls short |
| `overtime_thriller` | Goes to OT |
| `wire_to_wire` | Leading team never trails |
| `late_collapse` | Leading team chokes in Q4 |
| `back_and_forth` | Multiple lead changes |
| `random` | Procedurally generated |

### Test Game Price Generation

- **Random walk** with configurable spread and volatility
- **Misprice injection**: 5–12% random offset to simulate market overreaction
- **Game-state awareness**: `LiveTestPriceSimulator` derives prices from score + time using a basketball-aware logistic function

### Key Difference Summary

```
                    Real Game              Test Game
─────────────────────────────────────────────────────────
Data Source         ESPN API (live)        Synthetic scenarios
Markets             Polymarket (real)      Mock market
Prices              CLOB order book        Random walk / game-state model
Execution           Paper or Live          Paper only
Game Duration       Real-time              Accelerated (configurable)
Strategy Engine     ✓ Same                 ✓ Same
Rule Engine         ✓ Same                 ✓ Same
Risk Management     ✓ Same                 ✓ Same
```

The test game uses **the exact same trading logic** — strategies, rule engine, risk management, position monitoring, and exit rules. The only difference is the data source and price feed. This makes it an accurate sandbox for validating strategy behavior.

---

## 9. Replay / Backtesting System

**File:** `polynba/replay/replay_engine.py`

Replays historical game logs through the strategy engine to evaluate performance.

### How It Works

1. **Parse** saved market snapshots (condition_id, scores, clock, prices)
2. **Reconstruct** `GameState` from each snapshot
3. **Build** `EdgeOpportunity` from snapshot prices + model estimates
4. **Evaluate** entry/exit rules for each strategy at each tick
5. **Track** position lifecycle: open → hold → close
6. **Calculate** P&L and performance metrics

### Output

| Metric | Description |
|--------|-------------|
| Total P&L | Net profit/loss across all trades |
| Win Rate | Percentage of profitable trades |
| Avg Win | Average profit on winning trades |
| Avg Loss | Average loss on losing trades |
| Trade Count | Total trades taken |

Results are written per-strategy, per-game as JSON (`polynba/replay/output.py`).

### Usage

Backtest any strategy YAML against any historical game log to compare parameter variations without risking capital.

---

## 10. End-to-End Trade Example

Here's a complete lifecycle of a single trade:

```
1. FETCH GAME STATE
   DataManager → ESPN API
   → GameState: BOS 45–40 LAL, Q2 3:45 remaining

2. DISCOVER MARKET
   MarketDiscovery → Gamma API
   → Found moneyline market: BOS vs LAL

3. GET PRICES
   PriceFetcher → CLOB order book
   → BOS mid = $0.62, bid = $0.61, ask = $0.63, spread = 3.2%

4. ESTIMATE PROBABILITY
   ProbabilityCalculator (3-factor model)
   → estimated_prob = 0.72 (72% BOS wins)

5. DETECT EDGE
   EdgeDetector
   → edge = 0.72 − 0.62 = 0.10 (10%), confidence = 8

6. EVALUATE STRATEGIES
   RuleEngine checks "aggressive" strategy:
   ├── edge ≥ 3%?       ✓ (10%)
   ├── confidence ≥ 5?  ✓ (8)
   ├── time ≥ 180s?     ✓ (Q2, ~1600s left)
   ├── price ∈ [0.15, 0.75]? ✓ (0.62)
   └── spread ≤ 8%?     ✓ (3.2%)
   → All pass → Signal: BUY BOS

7. SIZE POSITION
   Kelly fraction = edge × prob = 0.10 × 0.72 ≈ 0.072
   Size = bankroll × kelly × multiplier = 500 × 0.072 × 0.40 = $14.40
   → Buy 23 tokens @ $0.62

8. EXECUTE ORDER
   → Order submitted (paper mode: instant fill)

9. MONITOR POSITION (every 5s)
   Price → $0.68: unrealized P&L = +$1.38 (+9.7%)
   Profit target (≥10 min left): 18% → Hold
   ...
   Clock → 0:30: Time stop triggered
   → SELL 23 tokens @ $0.67 (best bid)

10. RESULT
    Realized P&L = 23 × ($0.67 − $0.62) = +$1.15 (+8.1%)
    Logged to trade history, strategy stats updated
```

---

## Architecture Summary

```
polynba/
├── analysis/                  # Probability estimation & edge detection
│   ├── probability_calculator.py   # 3-factor model
│   ├── edge_detector.py            # Edge filtering & opportunity creation
│   └── claude_analyzer.py          # Optional AI analysis
├── bot/
│   └── trading_loop.py        # Main orchestration loop
├── config/
│   ├── config.yaml            # Main configuration
│   ├── strategies/            # Strategy YAML definitions
│   ├── recommends/            # Pre-configured parameter overrides
│   └── profiles/              # Deployment profiles
├── data/
│   ├── manager.py             # Data source coordinator
│   └── sources/
│       ├── espn/              # ESPN API client, parser, scraper
│       └── nba/               # NBA.com CDN client
├── polymarket/
│   ├── market_discovery.py    # Gamma API market finder
│   └── price_fetcher.py       # CLOB order book reader
├── strategy/
│   ├── loader.py              # YAML config loader
│   ├── rule_engine.py         # Entry/exit rule evaluator
│   └── strategy_manager.py    # Multi-strategy orchestration
├── trading/
│   ├── position_tracker.py    # Position lifecycle tracking
│   └── risk_manager.py        # Risk limits & circuit breakers
├── testing/
│   └── test_game_provider.py  # Test game scenarios & price simulation
└── replay/
    ├── replay_engine.py       # Historical backtesting
    └── output.py              # Results formatting
```
