"""Trading service: wraps TradingExecutor with USDC-to-shares conversion.

The web frontend works in USDC amounts.  This service converts the USDC size
into the number of shares needed before delegating to the executor.
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from polynba.data.models import TradeSide
from polynba.trading.executor import OrderResult, TradingExecutor

logger = logging.getLogger(__name__)

# Minimum order size on Polymarket CLOB (0.01 USDC worth of shares)
_MIN_ORDER_USDC = Decimal("0.01")
# Tick size: prices are rounded to this precision
_PRICE_TICK = Decimal("0.01")
# Share size precision (integer shares — Polymarket cannot sell fractional at limit)
_SIZE_TICK = Decimal("1")


async def place_order(
    executor: TradingExecutor,
    market_id: str,
    token_id: str,
    side: str,
    size_usdc: float,
    price: float,
    strategy_id: Optional[str] = None,
) -> OrderResult:
    """Place an order, converting USDC size to shares.

    Args:
        executor: The active TradingExecutor (paper or live).
        market_id: Polymarket condition ID.
        token_id: Token ID for the outcome.
        side: "buy" or "sell".
        size_usdc: Order size in USDC.
        price: Limit price per share (0 < price < 1).
        strategy_id: Optional strategy tag.

    Returns:
        OrderResult from the executor.

    Raises:
        ValueError: If size or price are out of range.
    """
    price_dec = Decimal(str(price)).quantize(_PRICE_TICK, rounding=ROUND_DOWN)

    if price_dec <= 0 or price_dec >= 1:
        return OrderResult(success=False, error=f"Price {price} is out of range (0, 1).")

    usdc_dec = Decimal(str(size_usdc))
    if usdc_dec < _MIN_ORDER_USDC:
        return OrderResult(
            success=False,
            error=f"Order size ${size_usdc:.4f} is below minimum ${_MIN_ORDER_USDC}.",
        )

    # Convert USDC → shares: shares = usdc / price_per_share
    # Floor to 2 decimal places to avoid over-spending
    raw_shares = usdc_dec / price_dec
    shares = raw_shares.quantize(_SIZE_TICK, rounding=ROUND_DOWN)

    if shares <= 0:
        return OrderResult(success=False, error="Computed share size is zero after rounding.")

    trade_side = TradeSide.BUY if side.lower() == "buy" else TradeSide.SELL

    logger.info(
        "Placing %s order: market=%s token=%s size=%.2f shares @ %.4f (%.2f USDC)",
        side.upper(),
        market_id[:20],
        token_id[:20],
        float(shares),
        float(price_dec),
        float(shares * price_dec),
    )

    return await executor.place_order(
        market_id=market_id,
        token_id=token_id,
        side=trade_side,
        size=shares,
        price=price_dec,
        strategy_id=strategy_id,
    )


async def cancel_order(executor: TradingExecutor, order_id: str) -> OrderResult:
    """Cancel an open order by ID."""
    logger.info("Cancelling order %s", order_id)
    return await executor.cancel_order(order_id)
