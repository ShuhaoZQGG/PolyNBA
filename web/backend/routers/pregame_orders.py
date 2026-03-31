"""Pregame orders router.

GET    /api/pregame-orders/dates              -> PregameDatesResponse
GET    /api/pregame-orders?date=YYYYMMDD      -> PregameOrdersResponse
POST   /api/pregame-orders/check-fills        -> PregameOrdersResponse
PATCH  /api/pregame-orders/{order_id}/exit-price -> PregameOrderSchema
POST   /api/pregame-orders/{order_id}/place-sell -> PregameOrderSchema
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from polynba.trading.executor import TradingExecutor

from ..dependencies import get_executor
from ..schemas import (
    PregameDatesResponse,
    PregameOrderSchema,
    PregameOrdersResponse,
    PregameOrdersSummary,
    RecordPregameOrderRequest,
    UpdateExitPriceRequest,
)
from ..services.pregame_orders_service import (
    check_fills,
    get_orders,
    list_dates,
    place_sell,
    record_order,
    update_exit_price,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pregame-orders", tags=["pregame-orders"])


def _build_response(ledger: dict) -> PregameOrdersResponse:
    """Convert a raw ledger dict into a PregameOrdersResponse."""
    orders = [PregameOrderSchema.from_ledger_entry(e) for e in ledger.get("orders", [])]
    summary = PregameOrdersSummary(
        total=len(orders),
        open=sum(1 for o in orders if o.status == "OPEN"),
        matched=sum(1 for o in orders if o.status == "MATCHED"),
        sell_placed=sum(1 for o in orders if o.status == "SELL_PLACED"),
        needs_sell=sum(1 for o in orders if o.needs_sell),
        total_cost=sum(o.shares * o.entry_price for o in orders),
    )
    return PregameOrdersResponse(
        date=ledger.get("date", ""),
        created_at=ledger.get("created_at"),
        updated_at=ledger.get("updated_at"),
        orders=orders,
        summary=summary,
    )


@router.get("/dates", response_model=PregameDatesResponse, summary="List ledger dates")
async def dates() -> PregameDatesResponse:
    return PregameDatesResponse(dates=list_dates())


@router.get("", response_model=PregameOrdersResponse, summary="Get orders for a date")
async def get_pregame_orders(
    date: str = Query(description="Ledger date YYYYMMDD"),
) -> PregameOrdersResponse:
    ledger = get_orders(date)
    return _build_response(ledger)


@router.post("/record", response_model=PregameOrderSchema, summary="Record a new pregame order")
async def record_pregame_order(req: RecordPregameOrderRequest) -> PregameOrderSchema:
    entry = record_order(req)
    return PregameOrderSchema.from_ledger_entry(entry)


@router.post("/check-fills", response_model=PregameOrdersResponse, summary="Check fills via CLOB API")
async def check_pregame_fills(
    date: str = Query(description="Ledger date YYYYMMDD"),
    executor: TradingExecutor = Depends(get_executor),
) -> PregameOrdersResponse:
    ledger = await check_fills(date, executor)
    return _build_response(ledger)


@router.patch("/{order_id}/exit-price", response_model=PregameOrderSchema, summary="Update exit price")
async def update_order_exit_price(
    order_id: str,
    req: UpdateExitPriceRequest,
    date: str = Query(description="Ledger date YYYYMMDD"),
) -> PregameOrderSchema:
    entry = update_exit_price(date, order_id, req.exit_price)
    return PregameOrderSchema.from_ledger_entry(entry)


@router.post("/{order_id}/place-sell", response_model=PregameOrderSchema, summary="Place exit sell order")
async def place_sell_order(
    order_id: str,
    date: str = Query(description="Ledger date YYYYMMDD"),
    executor: TradingExecutor = Depends(get_executor),
) -> PregameOrderSchema:
    entry = await place_sell(date, order_id, executor)
    return PregameOrderSchema.from_ledger_entry(entry)
