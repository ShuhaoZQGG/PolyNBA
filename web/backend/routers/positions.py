"""Positions router.

GET /api/positions  ->  PositionsResponse
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from polynba.polymarket.price_fetcher import PriceFetcher
from polynba.trading.executor import TradingExecutor

from ..dependencies import get_executor, get_price_fetcher
from ..schemas import PositionsResponse
from ..services.positions_service import get_enriched_positions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("", response_model=PositionsResponse, summary="Get enriched positions with P&L")
async def positions(
    executor: TradingExecutor = Depends(get_executor),
    price_fetcher: PriceFetcher = Depends(get_price_fetcher),
) -> PositionsResponse:
    return await get_enriched_positions(executor, price_fetcher)
