"""Portfolio service: aggregates balance, positions, and open orders."""

from __future__ import annotations

import logging

from polynba.trading.executor import TradingExecutor

logger = logging.getLogger(__name__)


async def get_portfolio(executor: TradingExecutor) -> dict:
    """Fetch and aggregate all portfolio data from the executor.

    Returns a plain dict with keys:
        - balance: Balance dataclass
        - positions: dict[str, Decimal]
        - open_orders: list[Order]

    Any individual fetch failure is logged and a safe default is used so
    the endpoint always returns a partial response rather than a 500.
    """
    import asyncio

    balance_task = executor.get_balance()
    positions_task = executor.get_positions()
    orders_task = executor.get_open_orders()

    balance, positions, open_orders = await asyncio.gather(
        balance_task,
        positions_task,
        orders_task,
        return_exceptions=True,
    )

    if isinstance(balance, Exception):
        logger.warning("Failed to fetch balance: %s", balance)
        from decimal import Decimal
        from polynba.trading.executor import Balance
        balance = Balance(usdc=Decimal("0"), locked_usdc=Decimal("0"))

    if isinstance(positions, Exception):
        logger.warning("Failed to fetch positions: %s", positions)
        positions = {}

    if isinstance(open_orders, Exception):
        logger.warning("Failed to fetch open orders: %s", open_orders)
        open_orders = []

    return {
        "balance": balance,
        "positions": positions,
        "open_orders": open_orders,
    }
