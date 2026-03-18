"""Trading router.

POST   /api/trading/order           ->  OrderResponse
DELETE /api/trading/order/{order_id}->  OrderResponse
GET    /api/trading/orders          ->  list[OrderSchema]
GET    /api/trading/history         ->  TradeHistoryResponse
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from polynba.trading.executor import TradingExecutor

from ..dependencies import get_executor
from ..schemas import OrderRequest, OrderResponse, OrderSchema, TradeHistoryResponse
from ..services.trading_service import cancel_order, place_order
from ..services.trade_history_service import get_trade_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trading", tags=["trading"])


@router.post(
    "/order",
    response_model=OrderResponse,
    summary="Place a new limit order",
)
async def create_order(
    req: OrderRequest,
    executor: TradingExecutor = Depends(get_executor),
) -> OrderResponse:
    """Place a buy or sell limit order.

    ``size_usdc`` is the USDC amount to spend.  The service layer converts
    this to the equivalent number of shares at the given limit price.

    In paper mode the order is simulated against the stored market data
    cache and may be filled immediately if the price crosses the current
    best bid/ask.
    """
    result = await place_order(
        executor=executor,
        market_id=req.market_id,
        token_id=req.token_id,
        side=req.side,
        size_usdc=req.size_usdc,
        price=req.price,
        strategy_id=req.strategy_id,
    )
    return OrderResponse.from_result(result)


@router.delete(
    "/order/{order_id}",
    response_model=OrderResponse,
    summary="Cancel an open order",
)
async def delete_order(
    order_id: str,
    executor: TradingExecutor = Depends(get_executor),
) -> OrderResponse:
    """Cancel the open order with the given ID.

    Returns a successful response with the updated order even when the
    order was already filled or cancelled.
    """
    result = await cancel_order(executor=executor, order_id=order_id)
    return OrderResponse.from_result(result)


@router.get(
    "/orders",
    response_model=list[OrderSchema],
    summary="List all open orders",
)
async def list_orders(
    market_id: Optional[str] = Query(
        default=None,
        description="Optional Polymarket condition ID to filter orders by market.",
    ),
    executor: TradingExecutor = Depends(get_executor),
) -> list[OrderSchema]:
    """Return all currently open orders, optionally filtered by market."""
    orders = await executor.get_open_orders(market_id=market_id)
    return [OrderSchema.from_dataclass(o) for o in orders]


@router.get(
    "/history",
    response_model=TradeHistoryResponse,
    summary="Get trade history from Polymarket CLOB",
)
async def trade_history(
    after: Optional[str] = Query(
        default=None,
        description="Filter trades after this ISO date (YYYY-MM-DD).",
    ),
    executor: TradingExecutor = Depends(get_executor),
) -> TradeHistoryResponse:
    """Return trade history entries enriched with market metadata.

    Fetches fills from the CLOB API (or paper order book), groups by
    market/outcome, and returns activity entries sorted newest-first.
    """
    after_ts: int | None = None
    if after:
        try:
            dt = datetime.strptime(after, "%Y-%m-%d")
            after_ts = int(dt.timestamp())
        except ValueError:
            pass

    from ..services.cache import trade_history_cache

    cache_key = f"history:{after_ts or 'all'}"
    return await trade_history_cache.get_or_fetch(
        cache_key, lambda: get_trade_history(executor=executor, after_ts=after_ts)
    )
