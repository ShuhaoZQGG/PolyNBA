"""Polymarket API validation script — tests market discovery and CLOB price fetching.

Run with: cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.tests.validate_polymarket
"""

import asyncio
import logging
import sys
import traceback
from typing import Any

from polynba.tests.validation_helpers import (
    ValidationResult,
    header,
    report,
    section,
    summary,
)

# ── Configure logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("validate_polymarket")
logger.setLevel(logging.INFO)


# ── Polymarket Validation ────────────────────────────────────────────
async def validate_polymarket_discovery() -> ValidationResult:
    """Validate Polymarket Gamma API market discovery."""
    from polynba.polymarket.market_discovery import MarketDiscovery

    vr = ValidationResult("Polymarket Market Discovery (Gamma API)")
    discovery = MarketDiscovery()

    try:
        markets = await discovery.discover_nba_markets(force_refresh=True)
        vr.ok(f"Discovered {len(markets)} NBA moneyline markets")

        if not markets:
            vr.warn("No NBA markets found (may be offseason or no upcoming games)")
            return vr

        # Validate market fields
        m = markets[0]
        if m.condition_id:
            vr.ok(f"condition_id present: {m.condition_id[:30]}...")
        else:
            vr.fail("condition_id is empty")

        if m.home_token_id and m.away_token_id:
            vr.ok(f"Token IDs present (home: {m.home_token_id[:20]}..., away: {m.away_token_id[:20]}...)")
        else:
            vr.fail("Token IDs missing")

        if m.home_team_name and m.away_team_name:
            home_abbr = discovery.get_team_abbreviation(m.home_team_name) or "???"
            away_abbr = discovery.get_team_abbreviation(m.away_team_name) or "???"
            vr.ok(f"Teams: {m.away_team_name} ({away_abbr}) @ {m.home_team_name} ({home_abbr})")
        else:
            vr.fail("Team names missing")

        if m.home_price is not None and m.away_price is not None:
            hp, ap = float(m.home_price), float(m.away_price)
            if 0 < hp < 1 and 0 < ap < 1:
                vr.ok(f"Prices sane: home=${hp:.2f}, away=${ap:.2f} (sum={hp + ap:.2f})")
            else:
                vr.fail(f"Prices out of range: home={hp}, away={ap}")
        else:
            vr.warn("Prices are None (Gamma API may not include them)")

        if m.end_date:
            vr.ok(f"End date: {m.end_date.isoformat()}")
        else:
            vr.warn("End date is None")

        vr.ok(f"Tradeable: {m.is_tradeable}, Volume: {m.volume}")

        # Store for price fetcher test
        vr._market = m

        # Also list all markets
        for i, mkt in enumerate(markets):
            home_abbr = discovery.get_team_abbreviation(mkt.home_team_name) or "???"
            away_abbr = discovery.get_team_abbreviation(mkt.away_team_name) or "???"
            hp_str = f"${float(mkt.home_price):.2f}" if mkt.home_price else "N/A"
            ap_str = f"${float(mkt.away_price):.2f}" if mkt.away_price else "N/A"
            date_str = mkt.end_date.strftime("%m/%d") if mkt.end_date else "?"
            print(f"    [{date_str}] {away_abbr} @ {home_abbr}: {home_abbr} {hp_str}, {away_abbr} {ap_str}")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await discovery.close()

    return vr


async def validate_polymarket_prices(market: Any) -> ValidationResult:
    """Validate Polymarket CLOB price fetching and order book parsing."""
    from polynba.polymarket.price_fetcher import PriceFetcher

    vr = ValidationResult(f"Polymarket CLOB Prices ({market.home_team_name} vs {market.away_team_name})")
    fetcher = PriceFetcher()

    try:
        prices = await fetcher.get_market_prices(market)

        if prices is None:
            vr.fail("get_market_prices returned None")
            return vr
        vr.ok("Fetched MarketPrices successfully")

        # Validate mid prices
        hm, am = float(prices.home_mid_price), float(prices.away_mid_price)
        if 0 < hm < 1 and 0 < am < 1:
            vr.ok(f"Mid prices: home={hm:.4f}, away={am:.4f}")
        else:
            vr.fail(f"Mid prices out of range: home={hm}, away={am}")

        price_sum = hm + am
        if 0.95 <= price_sum <= 1.05:
            vr.ok(f"Price sum ~1.0: {price_sum:.4f}")
        else:
            vr.warn(f"Price sum deviates from 1.0: {price_sum:.4f}")

        # Validate bid/ask
        if prices.home_best_bid is not None and prices.home_best_ask is not None:
            hb, ha = float(prices.home_best_bid), float(prices.home_best_ask)
            if hb < ha:
                vr.ok(f"Home bid/ask: {hb:.4f}/{ha:.4f} (spread={ha - hb:.4f})")
            else:
                vr.fail(f"Home bid >= ask: {hb} >= {ha}")
        else:
            vr.warn("Home bid/ask not available")

        if prices.away_best_bid is not None and prices.away_best_ask is not None:
            ab, aa = float(prices.away_best_bid), float(prices.away_best_ask)
            if ab < aa:
                vr.ok(f"Away bid/ask: {ab:.4f}/{aa:.4f} (spread={aa - ab:.4f})")
            else:
                vr.fail(f"Away bid >= ask: {ab} >= {aa}")
        else:
            vr.warn("Away bid/ask not available")

        # Validate depth
        hbd = float(prices.home_bid_depth)
        vr.ok(f"Home bid depth: ${hbd:,.0f}, Has liquidity: {prices.has_liquidity}")

        # Test get_token_sell_price
        sell_price = fetcher.get_token_sell_price(market.home_token_id)
        if sell_price is not None:
            vr.ok(f"Home token sell price (best bid): {float(sell_price):.4f}")
        else:
            vr.warn("get_token_sell_price returned None")

        # Test get_token_price_info
        mid, bid, spread_pct = fetcher.get_token_price_info(market.home_token_id)
        if mid is not None:
            vr.ok(f"Home token info: mid={float(mid):.4f}, bid={float(bid):.4f}, spread={spread_pct:.2f}%")
        else:
            vr.warn("get_token_price_info returned None for mid")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")

    return vr


# ── Main ─────────────────────────────────────────────────────────────
async def main() -> int:
    results: list[ValidationResult] = []

    header("1. Polymarket")

    section("1a. Market Discovery (Gamma API)")
    discovery_result = await validate_polymarket_discovery()
    results.append(discovery_result)
    report(discovery_result)

    market = getattr(discovery_result, "_market", None)
    if market:
        section("1b. CLOB Price Fetching")
        price_result = await validate_polymarket_prices(market)
        results.append(price_result)
        report(price_result)

    return summary(results)


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
