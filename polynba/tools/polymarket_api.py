"""Polymarket API CLI — query NBA market data.

Usage:
    python -m polynba.tools.polymarket_api markets [--days N]
    python -m polynba.tools.polymarket_api upcoming [--days N]
    python -m polynba.tools.polymarket_api prices INDEX_OR_ID
    python -m polynba.tools.polymarket_api prices-all
    python -m polynba.tools.polymarket_api token-price TOKEN_ID
"""

import asyncio
import dataclasses
import json
import sys
from datetime import datetime
from decimal import Decimal
from enum import Enum

from polynba.polymarket.market_discovery import MarketDiscovery
from polynba.polymarket.price_fetcher import PriceFetcher


def _json_default(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Enum):
        return obj.name
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dump(data):
    print(json.dumps(data, indent=2, default=_json_default))


def _parse_days(args):
    """Parse --days N from args, return (days, remaining_args)."""
    days = 3
    remaining = []
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        else:
            remaining.append(args[i])
            i += 1
    return days, remaining


async def cmd_markets(args):
    _days, _ = _parse_days(args)
    discovery = MarketDiscovery()
    try:
        markets = await discovery.discover_nba_markets(force_refresh=True)
        result = []
        for i, m in enumerate(markets):
            d = dataclasses.asdict(m)
            d["_index"] = i
            result.append(d)
        _dump(result)
    finally:
        await discovery.close()


async def cmd_upcoming(args):
    days, _ = _parse_days(args)
    discovery = MarketDiscovery()
    try:
        grouped = await discovery.discover_upcoming_nba_markets(
            days_ahead=days, force_refresh=True,
        )
        _dump({
            k: [dataclasses.asdict(m) for m in ms]
            for k, ms in grouped.items()
        })
    finally:
        await discovery.close()


async def cmd_prices(args):
    if not args:
        _dump({"error": "Usage: prices INDEX_OR_ID"})
        sys.exit(1)
    selector = args[0]
    discovery = MarketDiscovery()
    fetcher = PriceFetcher()
    try:
        markets = await discovery.discover_nba_markets(force_refresh=True)
        if not markets:
            _dump({"error": "No markets found"})
            sys.exit(1)

        # Try numeric index first
        market = None
        try:
            idx = int(selector)
            if 0 <= idx < len(markets):
                market = markets[idx]
        except ValueError:
            pass

        # Fall back to condition_id substring match
        if market is None:
            for m in markets:
                if selector in m.condition_id:
                    market = m
                    break

        if market is None:
            _dump({"error": f"No market matching '{selector}'. Use 'markets' to see available indices."})
            sys.exit(1)

        prices = await fetcher.get_market_prices(market)
        _dump(dataclasses.asdict(prices) if prices else None)
    finally:
        await discovery.close()


async def cmd_prices_all(args):
    discovery = MarketDiscovery()
    fetcher = PriceFetcher()
    try:
        markets = await discovery.discover_nba_markets(force_refresh=True)
        prices_map = await fetcher.get_prices_batch(markets)
        result = []
        for m in markets:
            entry = dataclasses.asdict(m)
            p = prices_map.get(m.condition_id)
            entry["prices"] = dataclasses.asdict(p) if p else None
            result.append(entry)
        _dump(result)
    finally:
        await discovery.close()


async def cmd_token_price(args):
    if not args:
        _dump({"error": "Usage: token-price TOKEN_ID"})
        sys.exit(1)
    fetcher = PriceFetcher()
    mid, bid, spread = fetcher.get_token_price_info(args[0])
    _dump({
        "token_id": args[0],
        "mid_price": float(mid) if mid else None,
        "best_bid": float(bid) if bid else None,
        "spread_pct": spread,
    })


COMMANDS = {
    "markets": cmd_markets,
    "upcoming": cmd_upcoming,
    "prices": cmd_prices,
    "prices-all": cmd_prices_all,
    "token-price": cmd_token_price,
}


async def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        _dump({"error": f"Usage: polymarket_api <subcommand> [args...]\nSubcommands: {', '.join(COMMANDS)}"})
        sys.exit(1)
    try:
        await COMMANDS[sys.argv[1]](sys.argv[2:])
    except Exception as e:
        _dump({"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
