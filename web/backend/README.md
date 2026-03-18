# PolyNBA Web Backend

FastAPI backend for the PolyNBA pre-game betting advisor web application. Provides NBA game data, Polymarket market discovery, probability analysis (with optional Claude AI), and trading execution.

## Routers

| Router | Prefix | Description |
|--------|--------|-------------|
| `markets` | `/markets` | Polymarket NBA market discovery and prices |
| `games` | `/games` | NBA game schedule and live data |
| `analysis` | `/analysis` | Pre-game probability analysis with factor breakdown |
| `portfolio` | `/portfolio` | Bankroll balance and P&L tracking |
| `positions` | `/positions` | Open position management |
| `trading` | `/trading` | Order placement and trade history |
| `pregame_orders` | `/pregame-orders` | Standing pre-game order management |

## Services

Backend services live in `services/` and encapsulate business logic:

- **`market_service`** — Market discovery and price fetching via Polymarket APIs
- **`advisor_service`** — Pre-game probability model and bet suggestions
- **`portfolio_service`** — Bankroll and balance management
- **`positions_service`** — Position tracking (paper and live)
- **`trading_service`** — Order execution via CLOB client
- **`trade_history_service`** — Trade history retrieval
- **`pregame_orders_service`** — Standing order CRUD
- **`cache`** — In-memory TTL cache for API responses

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `POLYMARKET_PRIVATE_KEY` | _(none)_ | Wallet private key; enables live trading mode |
| `POLYNBA_BANKROLL` | `500` | Default bankroll in USDC |
| `POLYNBA_SCAN_DATE` | _(today)_ | Override scan date (YYYYMMDD) |
| `POLYNBA_AI_ANALYSIS` | `true` | Enable/disable AI analysis |
| `POLYNBA_AI_MODEL` | `claude-haiku-4-5-20251001` | Claude model for AI analysis |
| `ANTHROPIC_API_KEY` | _(none)_ | Required for AI analysis |

## Running

```bash
# Install web dependencies
pip install -e ".[web]"

# Start the dev server
uvicorn web.backend.app:app --reload --port 8000
```

API docs available at http://localhost:8000/docs once running.
