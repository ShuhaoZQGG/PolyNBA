"""Portfolio router.

GET /api/portfolio  ->  PortfolioResponse
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from polynba.trading.executor import TradingExecutor

from ..config import IS_LIVE_MODE
from ..dependencies import get_executor
from ..schemas import BalanceSchema, OrderSchema, PortfolioResponse
from ..services.portfolio_service import get_portfolio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioResponse, summary="Get portfolio balance, positions, and open orders")
async def portfolio(
    executor: TradingExecutor = Depends(get_executor),
) -> PortfolioResponse:
    """Return current balance, positions, and open orders.

    Works for both paper and live trading modes.  In paper mode the balance
    starts at the configured initial balance and tracks simulated fills.
    """
    from ..services.cache import balance_cache

    data = await balance_cache.get_or_fetch(
        "portfolio", lambda: get_portfolio(executor)
    )

    balance = BalanceSchema.from_dataclass(data["balance"])
    positions = {token_id: float(size) for token_id, size in data["positions"].items()}
    open_orders = [OrderSchema.from_dataclass(o) for o in data["open_orders"]]

    return PortfolioResponse(
        balance=balance,
        positions=positions,
        open_orders=open_orders,
        is_live_mode=IS_LIVE_MODE,
    )
