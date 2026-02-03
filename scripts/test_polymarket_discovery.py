#!/usr/bin/env python3
"""Test script to verify Polymarket market discovery.

This script tests the Gamma API integration by:
1. Fetching all NBA markets from Polymarket
2. Showing markets grouped by date (today, tomorrow, +2 days)
3. Optionally fetching prices for discovered markets

Usage:
    python scripts/test_polymarket_discovery.py
    python scripts/test_polymarket_discovery.py --fetch-prices
    python scripts/test_polymarket_discovery.py --raw-sample
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Create a fake polynba package to allow importing polymarket without loading the full package
import types
polynba_pkg = types.ModuleType("polynba")
polynba_pkg.__path__ = [str(project_root / "polynba")]
sys.modules["polynba"] = polynba_pkg

# Now import the polymarket modules
from polynba.polymarket.models import (
    PolymarketNBAMarket,
    MarketPrices,
    GammaMarketResponse,
)
from polynba.polymarket.market_discovery import MarketDiscovery
from polynba.polymarket.price_fetcher import PriceFetcher


async def test_market_discovery(fetch_prices: bool = False, raw_sample: bool = False):
    """Test the market discovery functionality."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger = logging.getLogger(__name__)

    discovery = MarketDiscovery()
    price_fetcher = PriceFetcher() if fetch_prices else None

    try:
        # Option 1: Show raw API response sample
        if raw_sample:
            logger.info("Fetching raw market data sample from Gamma API...")
            raw_markets = await discovery.fetch_raw_markets_sample(limit=5)

            print("\n" + "=" * 60)
            print("RAW GAMMA API RESPONSE SAMPLE (first 5 NBA markets)")
            print("=" * 60)

            for i, market in enumerate(raw_markets, 1):
                print(f"\n--- Market {i} ---")
                # Pretty print relevant fields
                relevant_fields = [
                    "id", "question", "conditionId", "slug",
                    "endDate", "active", "closed", "liquidity",
                    "volume", "outcomes", "outcomePrices", "clobTokenIds"
                ]
                for field in relevant_fields:
                    if field in market:
                        value = market[field]
                        if isinstance(value, str) and len(value) > 80:
                            value = value[:80] + "..."
                        print(f"  {field}: {value}")

            print("\n" + "=" * 60)
            return

        # Option 2: Run full market summary with logging
        logger.info("Running Polymarket market discovery verification...")
        markets_by_date = await discovery.log_market_summary(
            days_ahead=2,
            force_refresh=True,
        )

        # Option 3: Fetch prices for today's markets
        if fetch_prices and markets_by_date.get("today"):
            print("\n" + "=" * 60)
            print("FETCHING REAL PRICES FOR TODAY'S MARKETS")
            print("=" * 60)

            for market in markets_by_date["today"]:
                prices = await price_fetcher.get_market_prices(market)
                if prices:
                    home_abbr = discovery.get_team_abbreviation(market.home_team_name) or "???"
                    away_abbr = discovery.get_team_abbreviation(market.away_team_name) or "???"
                    print(
                        f"\n{away_abbr} @ {home_abbr}:"
                    )
                    print(f"  Home: {float(prices.home_mid_price):.1%} "
                          f"(bid: {float(prices.home_best_bid or 0):.2f}, "
                          f"ask: {float(prices.home_best_ask or 0):.2f})")
                    print(f"  Away: {float(prices.away_mid_price):.1%} "
                          f"(bid: {float(prices.away_best_bid or 0):.2f}, "
                          f"ask: {float(prices.away_best_ask or 0):.2f})")
                    print(f"  Liquidity: home_bid=${float(prices.home_bid_depth):,.0f}, "
                          f"home_ask=${float(prices.home_ask_depth):,.0f}")
                else:
                    print(f"\n{market.question[:50]}... - FAILED TO FETCH PRICES")

            print("\n" + "=" * 60)

        # Summary
        total = sum(len(m) for m in markets_by_date.values())
        print(f"\nTotal NBA markets found: {total}")
        print(f"  Today: {len(markets_by_date.get('today', []))}")
        print(f"  Tomorrow: {len(markets_by_date.get('tomorrow', []))}")
        print(f"  Future (+2 days): {len(markets_by_date.get('future', []))}")
        print(f"  Unknown date: {len(markets_by_date.get('unknown', []))}")

    finally:
        await discovery.close()


def main():
    parser = argparse.ArgumentParser(
        description="Test Polymarket NBA market discovery"
    )
    parser.add_argument(
        "--fetch-prices",
        action="store_true",
        help="Also fetch prices for today's markets",
    )
    parser.add_argument(
        "--raw-sample",
        action="store_true",
        help="Show raw API response sample instead of parsed markets",
    )

    args = parser.parse_args()

    asyncio.run(test_market_discovery(
        fetch_prices=args.fetch_prices,
        raw_sample=args.raw_sample,
    ))


if __name__ == "__main__":
    main()
