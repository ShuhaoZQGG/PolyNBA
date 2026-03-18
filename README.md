# PolyNBA

NBA live in-game trading bot for Polymarket. It ingests live game data, estimates win probabilities, detects pricing edges, and executes trades via a strategy and risk framework. Claude-assisted analysis can be enabled to add qualitative signals to the quantitative model.

## Features
- Live game ingestion via data sources (ESPN/NBA).
- Quant probability model with edge detection and filters.
- Pluggable strategy rules and capital allocation.
- Paper trading executor with position, order, and risk management.
- Optional Claude analysis with caching and budget controls.
- Performance tracking and summary reporting.
- **Pre-game advisor** with AI-powered analysis (`--ai-analysis`, `--ai-model`).
- **Web dashboard** — React frontend + FastAPI backend for visual game browsing, analysis, and trading.

## Project layout
- `polynba/bot/`: CLI entrypoint and trading loop orchestration.
- `polynba/analysis/`: probability model, edge detection, Claude integration.
- `polynba/data/`: live data sources, caching, models.
- `polynba/strategy/`: strategy loader and rule engine.
- `polynba/trading/`: executors, order/position/risk management.
- `polynba/config/`: default config and risk limits.
- `polynba/pregame/`: pre-game betting advisor with AI analysis.
- `web/backend/`: FastAPI backend — markets, games, analysis, portfolio, trading APIs.
- `web/frontend/`: React + TypeScript SPA — dashboard, game detail, activity pages.

## Requirements
- Python 3.11+
- Dependencies from `pyproject.toml` or `requirements.txt`
- Optional: `ANTHROPIC_API_KEY` for Claude analysis
- Optional: Node.js 18+ for the web frontend

## Install
```bash
pip install -r requirements.txt

# For the web dashboard (backend + frontend):
pip install -e ".[web]"
cd web/frontend && npm install
```

## Quick start (paper trading)
```bash
python -m polynba --mode paper
```

You can also use the console script after installing as a package:
```bash
polynba --mode paper
```

## Test game (simulation)
To test the bot without a real NBA game or Polymarket API, use **test game mode**. It runs a scenario-driven mock game with time-series prices so you can exercise the full loop (edge detection, strategies, paper orders) locally. The game ends naturally and the bot stops automatically.

```bash
python -m polynba --test-game
```

Optional flags:

- **`--test-game-scenario NAME`** – Choose a game scenario. Available: `home_blowout`, `away_blowout`, `close_game`, `home_comeback`, `away_comeback`, `failed_comeback`, `overtime_thriller`, `wire_to_wire`, `late_collapse`, `back_and_forth`, or `random` (default).
- **`--test-game-ticks N`** – Number of price ticks for the simulated market.
- **`--max-iterations N`** – Override how many iterations to run.

Examples:

```bash
# Run a home blowout scenario
python -m polynba --test-game --test-game-scenario home_blowout

# Run a random scenario with no Claude
python -m polynba --test-game --no-claude

# Short run with 3 ticks
python -m polynba --test-game --test-game-ticks 3 --max-iterations 3 --no-claude
```

In test game mode the bot skips Polymarket verification and game selection; it uses a synthetic “Test Home vs Test Away” game and a pre-generated random price series.

## CLI options
```text
--mode paper|live           Trading mode (default: paper)
--config PATH               Config file path
--strategies NAME ...       Active strategies by name
--bankroll FLOAT            Initial bankroll in USDC
--interval INT              Loop interval in seconds
--max-iterations INT        Stop after N iterations
--test-game                 Mock game + time-series prices (no real API)
--test-game-scenario NAME   Game scenario (e.g. home_blowout, random)
--test-game-ticks N         Number of price ticks for --test-game (default: 20)
--no-claude                 Disable Claude analysis
--log-level LEVEL           DEBUG|INFO|WARNING|ERROR
--analyze                   Show performance summary and exit
```

## Configuration
Default config lives at `polynba/config/config.yaml`. You can pass a custom file via `--config`. Key sections:
- `mode`, `bankroll`, `loop`: trading loop settings
- `data`: data source and cache TTLs
- `apis`: Claude + Polymarket endpoints
- `risk`: high-level risk settings
- `allocation`: portfolio allocation by risk level
- `logging`: log output settings
- `performance`: snapshot and report settings

Risk limits are defined in `polynba/config/risk_limits.yaml`.

## Strategies
Strategies are defined in `polynba/config/strategies/*.yaml` and loaded by name, for example:
```bash
python -m polynba --strategies conservative aggressive
```

## Claude analysis (optional)
Claude analysis is enabled by default and uses the `ANTHROPIC_API_KEY` environment variable. To disable:
```bash
python -m polynba --no-claude
```

## Performance summary
The bot writes snapshots to `performance.json`. View a summary:
```bash
python -m polynba --analyze
```

## Live trading note
The current trading loop instantiates `PaperTradingExecutor` by default. Live trading requires wiring a `LiveTradingExecutor` with a private key and Polymarket CLOB access in your own integration.

## Web dashboard

The web dashboard provides a visual interface for browsing today's games, viewing probability analysis, and placing trades.

```bash
# Start the FastAPI backend (port 8000)
uvicorn web.backend.app:app --reload --port 8000

# In another terminal, start the React dev server (port 5173)
cd web/frontend && npm run dev
```

Open http://localhost:5173 to use the dashboard. API docs at http://localhost:8000/docs.

See [web/backend/README.md](web/backend/README.md) and [web/frontend/README.md](web/frontend/README.md) for details.

## Tests
```bash
pytest
```
