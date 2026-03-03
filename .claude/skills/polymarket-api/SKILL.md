---
name: polymarket-api
description: Query Polymarket NBA betting markets — discover markets, get live prices, check spreads, and fetch token order book data. Use when the user asks about Polymarket odds, NBA betting markets, market prices, or trading data.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: <subcommand> [args...]
---

# Polymarket API Skill

Call Polymarket Gamma API (market discovery) and CLOB API (live prices) for NBA game markets.

## Subcommands

| Subcommand | Args | Description |
|------------|------|-------------|
| `markets` | `[--days N]` | All active NBA game markets with indices |
| `upcoming` | `[--days N]` | Markets grouped by date (today/tomorrow/future) |
| `prices` | `INDEX_OR_ID` | Live order book prices for a single market |
| `prices-all` | | All markets with live prices (market data + order books) |
| `token-price` | `TOKEN_ID` | Mid price, best bid, and spread for a specific token |

**INDEX_OR_ID**: Either a numeric index from `markets` output (e.g., `0`, `1`, `2`) or a condition_id substring.

**TOKEN_ID**: A CLOB token ID (long hex string from market data).

**--days N**: How many days ahead to look for markets (default: 3).

## Understanding the Request

Parse `$ARGUMENTS` for the subcommand and its arguments. If no subcommand is given, show available subcommands.

## Build and Run the Command

```bash
cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.tools.polymarket_api $SUBCOMMAND $ARGS
```

Run with **120000ms Bash timeout** (2 minutes). Market discovery fetches event details for each active game.

## Present Results

All output is JSON. Summarize the key information:

- **markets**: Number of markets found, each game with teams, initial prices (implied probability), volume, liquidity, and index for use with `prices`
- **upcoming**: Games grouped by date — highlight today's games with odds
- **prices**: Home/away mid prices (implied win probability), best bid/ask, bid-ask spread, order book depth
- **prices-all**: All games with live order book prices — good for scanning all odds at once
- **token-price**: Single token's mid price, best bid, and spread percentage

### Interpreting prices

- Mid price ≈ implied win probability (e.g., 0.65 = 65% chance)
- Best bid = what you'd get selling (exit price)
- Best ask = what you'd pay buying (entry price)
- Spread = (ask - bid) / mid — tighter is better liquidity
- Depth = total USDC available at all price levels

### Error handling

- `{"error": "No markets found"}` — no active NBA game markets (offseason or between game days)
- `null` prices — order book empty or CLOB API issue
- Condition ID not matching — use `markets` first to get valid indices

## Example Invocations

```
/polymarket-api markets             → All NBA game markets with indices
/polymarket-api markets --days 5    → Markets up to 5 days ahead
/polymarket-api upcoming            → Markets grouped by date
/polymarket-api upcoming --days 1   → Just today's markets
/polymarket-api prices 0            → Prices for first market (by index)
/polymarket-api prices 0x3f2a...    → Prices by condition_id substring
/polymarket-api prices-all          → All markets with live prices
/polymarket-api token-price 12345...→ Single token order book info
```
