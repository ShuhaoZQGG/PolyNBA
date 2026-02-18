"""Order manager with sports market delay handling."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Callable, Optional

from ..data.models import TradeSide
from .executor import MarketData, Order, OrderResult, OrderStatus, TradingExecutor

logger = logging.getLogger(__name__)


@dataclass
class DelayConfig:
    """Configuration for order delay handling."""

    delay_seconds: float = 3.0  # Sports market delay
    price_check_interval: float = 0.1  # Check price every 100ms
    max_price_deviation_percent: float = 2.0  # Auto-cancel threshold
    enable_auto_cancel: bool = True


@dataclass
class PendingOrder:
    """Order pending during delay period."""

    order: Order
    submitted_at: datetime
    initial_market_price: Decimal
    cancel_requested: bool = False
    price_checks: list[Decimal] = field(default_factory=list)


class OrderManager:
    """Manages order lifecycle with sports market delay handling.

    Sports markets on Polymarket have a 3-second delay before orders
    become active. This manager monitors price during the delay and
    can auto-cancel if price moves unfavorably.
    """

    def __init__(
        self,
        executor: TradingExecutor,
        config: Optional[DelayConfig] = None,
        on_fill: Optional[Callable[[Order], None]] = None,
        on_cancel: Optional[Callable[[Order], None]] = None,
    ):
        """Initialize order manager.

        Args:
            executor: Trading executor instance
            config: Delay handling configuration
            on_fill: Callback when order fills
            on_cancel: Callback when order cancels
        """
        self._executor = executor
        self._config = config or DelayConfig()
        self._on_fill = on_fill
        self._on_cancel = on_cancel

        self._pending_orders: dict[str, PendingOrder] = {}
        self._active_orders: dict[str, Order] = {}
        self._completed_orders: dict[str, Order] = {}

        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the order manager."""
        if self._running:
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Order manager started")

    async def stop(self) -> None:
        """Stop the order manager."""
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("Order manager stopped")

    async def submit_order(
        self,
        market_id: str,
        token_id: str,
        side: TradeSide,
        size: Decimal,
        price: Decimal,
        strategy_id: Optional[str] = None,
    ) -> OrderResult:
        """Submit a new order with delay monitoring.

        Args:
            market_id: Market ID
            token_id: Token ID
            side: Buy or sell
            size: Order size
            price: Order price
            strategy_id: Optional strategy identifier

        Returns:
            OrderResult with order details
        """
        # Get current market price (use token_id as key for CLOB orderbook lookup)
        market_data = await self._executor.get_market_data(token_id)
        initial_price = Decimal("0.5")  # Default mid

        if market_data:
            initial_price = market_data.mid_price

        # Place order through executor
        result = await self._executor.place_order(
            market_id=market_id,
            token_id=token_id,
            side=side,
            size=size,
            price=price,
            strategy_id=strategy_id,
        )

        if not result.success or not result.order:
            return result

        # Track pending order
        pending = PendingOrder(
            order=result.order,
            submitted_at=datetime.now(),
            initial_market_price=initial_price,
        )
        self._pending_orders[result.order.order_id] = pending

        logger.info(
            f"Order submitted: {result.order.order_id}, "
            f"monitoring during {self._config.delay_seconds}s delay"
        )

        return result

    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel

        Returns:
            OrderResult with status
        """
        # Check if pending
        if order_id in self._pending_orders:
            pending = self._pending_orders[order_id]
            pending.cancel_requested = True
            logger.info(f"Cancel requested for pending order: {order_id}")
            # Will be cancelled in monitor loop

        # Cancel through executor
        result = await self._executor.cancel_order(order_id)

        if result.success:
            self._move_to_completed(order_id, OrderStatus.CANCELLED)
            if self._on_cancel and result.order:
                self._on_cancel(result.order)

        return result

    async def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID.

        Args:
            order_id: Order ID

        Returns:
            Order object or None
        """
        # Check all tracking dicts
        if order_id in self._pending_orders:
            return self._pending_orders[order_id].order
        if order_id in self._active_orders:
            return self._active_orders[order_id]
        if order_id in self._completed_orders:
            return self._completed_orders[order_id]

        return await self._executor.get_order(order_id)

    def get_pending_orders(self) -> list[Order]:
        """Get all pending orders (in delay period)."""
        return [p.order for p in self._pending_orders.values()]

    def get_active_orders(self) -> list[Order]:
        """Get all active orders (past delay period)."""
        return list(self._active_orders.values())

    def get_all_open_orders(self) -> list[Order]:
        """Get all open orders (pending + active)."""
        return self.get_pending_orders() + self.get_active_orders()

    async def _monitor_loop(self) -> None:
        """Main monitoring loop for pending orders."""
        while self._running:
            try:
                await self._check_pending_orders()
                await self._check_active_orders()
                await asyncio.sleep(self._config.price_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in order monitor loop: {e}")
                await asyncio.sleep(1.0)

    async def _check_pending_orders(self) -> None:
        """Check pending orders during delay period."""
        now = datetime.now()
        completed = []

        for order_id, pending in self._pending_orders.items():
            elapsed = (now - pending.submitted_at).total_seconds()

            # Check for cancel request
            if pending.cancel_requested:
                await self._cancel_pending_order(order_id, "User requested")
                completed.append(order_id)
                continue

            # Check price during delay
            if self._config.enable_auto_cancel:
                try:
                    should_cancel = await self._check_price_deviation(pending)
                    if should_cancel:
                        await self._cancel_pending_order(order_id, "Price deviation")
                        completed.append(order_id)
                        continue
                except Exception as e:
                    logger.debug(f"Price deviation check failed for {order_id}: {e}")

            # Check if delay period complete
            if elapsed >= self._config.delay_seconds:
                self._promote_to_active(order_id)
                completed.append(order_id)

        # Remove from pending
        for order_id in completed:
            self._pending_orders.pop(order_id, None)

    async def _check_price_deviation(self, pending: PendingOrder) -> bool:
        """Check if price has moved too much during delay.

        Returns:
            True if order should be cancelled
        """
        market_data = await self._executor.get_market_data(
            pending.order.token_id
        )

        if not market_data:
            return False

        current_price = market_data.mid_price
        pending.price_checks.append(current_price)

        initial = pending.initial_market_price
        if initial == 0:
            return False

        deviation = abs(current_price - initial) / initial * 100

        if deviation > self._config.max_price_deviation_percent:
            logger.warning(
                f"Price deviation {deviation:.2f}% exceeds threshold "
                f"for order {pending.order.order_id}"
            )
            return True

        return False

    async def _cancel_pending_order(self, order_id: str, reason: str) -> None:
        """Cancel a pending order."""
        logger.info(f"Cancelling pending order {order_id}: {reason}")

        result = await self._executor.cancel_order(order_id)

        if result.success:
            self._move_to_completed(order_id, OrderStatus.CANCELLED)
            if self._on_cancel and result.order:
                self._on_cancel(result.order)

    def _promote_to_active(self, order_id: str) -> None:
        """Promote order from pending to active."""
        pending = self._pending_orders.get(order_id)
        if not pending:
            return

        logger.info(f"Order {order_id} now active (past delay period)")
        self._active_orders[order_id] = pending.order

    async def _check_active_orders(self) -> None:
        """Check status of active orders."""
        completed = []

        for order_id, order in self._active_orders.items():
            # Get updated status from executor
            updated = await self._executor.get_order(order_id)

            if not updated:
                continue

            # Check for fill
            if updated.status == OrderStatus.FILLED:
                logger.info(f"Order filled: {order_id}")
                completed.append(order_id)
                self._completed_orders[order_id] = updated
                if self._on_fill:
                    self._on_fill(updated)

            # Check for cancel
            elif updated.status in (
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            ):
                logger.info(f"Order {order_id} status: {updated.status.value}")
                completed.append(order_id)
                self._completed_orders[order_id] = updated
                if self._on_cancel:
                    self._on_cancel(updated)

            # Update local copy
            else:
                self._active_orders[order_id] = updated

        # Remove completed from active
        for order_id in completed:
            self._active_orders.pop(order_id, None)

    def _move_to_completed(self, order_id: str, status: OrderStatus) -> None:
        """Move order to completed tracking."""
        order = None

        if order_id in self._pending_orders:
            order = self._pending_orders.pop(order_id).order
        elif order_id in self._active_orders:
            order = self._active_orders.pop(order_id)

        if order:
            order.status = status
            order.updated_at = datetime.now()
            self._completed_orders[order_id] = order

    @property
    def stats(self) -> dict:
        """Get order manager statistics."""
        return {
            "pending_count": len(self._pending_orders),
            "active_count": len(self._active_orders),
            "completed_count": len(self._completed_orders),
        }
