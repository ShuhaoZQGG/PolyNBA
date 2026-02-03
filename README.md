# PolyNBA

NBA live in-game trading bot for Polymarket. It ingests live game data, estimates win probabilities, detects pricing edges, and executes trades via a strategy and risk framework. Claude-assisted analysis can be enabled to add qualitative signals to the quantitative model.

## Features
- Live game ingestion via data sources (ESPN/NBA).
- Quant probability model with edge detection and filters.
- Pluggable strategy rules and capital allocation.
- Paper trading executor with position, order, and risk management.
- Optional Claude analysis with caching and budget controls.
- Performance tracking and summary reporting.

## Project layout
- `polynba/bot/`: CLI entrypoint and trading loop orchestration.
- `polynba/analysis/`: probability model, edge detection, Claude integration.
- `polynba/data/`: live data sources, caching, models.
- `polynba/strategy/`: strategy loader and rule engine.
- `polynba/trading/`: executors, order/position/risk management.
- `polynba/config/`: default config and risk limits.

## Requirements
- Python 3.11+
- Dependencies from `pyproject.toml` or `requirements.txt`
- Optional: `ANTHROPIC_API_KEY` for Claude analysis

## Install
```bash
pip install -r requirements.txt
```

## Quick start (paper trading)
```bash
python -m polynba --mode paper
```

You can also use the console script after installing as a package:
```bash
polynba --mode paper
```

## CLI options
```text
--mode paper|live           Trading mode (default: paper)
--config PATH               Config file path
--strategies NAME ...       Active strategies by name
--bankroll FLOAT            Initial bankroll in USDC
--interval INT              Loop interval in seconds
--max-iterations INT        Stop after N iterations
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

## Tests
```bash
pytest
```
