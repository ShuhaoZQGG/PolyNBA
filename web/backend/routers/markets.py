"""Markets router.

GET /api/markets?date=YYYYMMDD  ->  list[GameMarketSummary]

Fetches games, discovers Polymarket markets, matches them by team
abbreviation, fetches prices, and returns the combined data.  Analysis
results are pulled from the in-memory cache when available.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from polynba.data.manager import DataManager
from polynba.polymarket.market_discovery import MarketDiscovery
from polynba.polymarket.price_fetcher import PriceFetcher

from ..dependencies import get_data_manager, get_market_discovery, get_price_fetcher
from ..routers.analysis import _get_cached
from ..schemas import (
    GameMarketSummary,
    GameSummarySchema,
    PolymarketMarketSchema,
    MarketPricesSchema,
    PreGameEstimateSchema,
)
from ..services.cache import matched_markets_cache
from ..services.market_service import get_matched_markets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets", tags=["markets"])


@router.get(
    "",
    response_model=list[GameMarketSummary],
    summary="List today's (or a given date's) NBA game markets with prices",
)
async def list_markets(
    date: Optional[str] = Query(
        default=None,
        description="Date in YYYYMMDD format.  Defaults to today (US/Eastern).",
        pattern=r"^\d{8}$",
    ),
    data_manager: DataManager = Depends(get_data_manager),
    market_discovery: MarketDiscovery = Depends(get_market_discovery),
    price_fetcher: PriceFetcher = Depends(get_price_fetcher),
) -> list[GameMarketSummary]:
    """Return matched game-market pairs with current order book prices.

    Each entry includes:
    - ``game``: ESPN game metadata (teams, status, score, schedule time).
    - ``market``: Polymarket market metadata (condition ID, token IDs, liquidity).
    - ``prices``: Live CLOB order book prices (mid, best bid/ask, depth).
    - ``cached_verdict`` / ``cached_estimate``: Present when ``/api/analysis``
      has already been run for this game, avoiding a second round-trip.
    """
    matched = await matched_markets_cache.get_or_fetch(
        f"markets:{date or 'today'}",
        lambda: get_matched_markets(
            data_manager=data_manager,
            market_discovery=market_discovery,
            price_fetcher=price_fetcher,
            date=date,
        ),
    )

    results: list[GameMarketSummary] = []
    for game, market, prices in matched:
        game_schema = GameSummarySchema.from_dataclass(game)
        market_schema = PolymarketMarketSchema.from_dataclass(market)
        prices_schema = MarketPricesSchema.from_dataclass(prices) if prices else None

        # Surface cached analysis verdict if available
        cached_advisory = _get_cached(game.game_id)
        cached_verdict: Optional[str] = None
        cached_estimate: Optional[PreGameEstimateSchema] = None
        if cached_advisory is not None:
            cached_verdict = cached_advisory.estimate.verdict
            cached_estimate = PreGameEstimateSchema.from_dataclass(cached_advisory.estimate)

        results.append(
            GameMarketSummary(
                game=game_schema,
                market=market_schema,
                prices=prices_schema,
                cached_verdict=cached_verdict,
                cached_estimate=cached_estimate,
            )
        )

    return results
