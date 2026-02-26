"""Position and trade state tracking."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..data.models import TradeSide
from .executor import Order, OrderStatus

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents a position in a market."""

    market_id: str
    token_id: str
    side: TradeSide  # Whether we're long (BUY) or short (SELL)
    size: Decimal  # Number of shares
    avg_entry_price: Decimal  # Average entry price
    strategy_id: Optional[str] = None
    opened_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    realized_pnl: Decimal = Decimal("0")

    # Cost basis tracking
    total_cost: Decimal = Decimal("0")

    @property
    def notional_value(self) -> Decimal:
        """Get notional value at entry."""
        return self.size * self.avg_entry_price

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Calculate unrealized P&L at current price.

        Args:
            current_price: Current market price

        Returns:
            Unrealized profit/loss
        """
        if self.size == 0:
            return Decimal("0")

        if self.side == TradeSide.BUY:
            # Long position: profit when price goes up
            return self.size * (current_price - self.avg_entry_price)
        else:
            # Short position: profit when price goes down
            return self.size * (self.avg_entry_price - current_price)

    def unrealized_pnl_percent(self, current_price: Decimal) -> float:
        """Calculate unrealized P&L as percentage.

        Args:
            current_price: Current market price

        Returns:
            Unrealized P&L percentage
        """
        if self.total_cost == 0:
            return 0.0

        pnl = self.unrealized_pnl(current_price)
        return float(pnl / self.total_cost * 100)

    @property
    def is_closed(self) -> bool:
        """Check if position is closed."""
        return self.size == 0


@dataclass
class Trade:
    """Record of a completed trade."""

    trade_id: str
    market_id: str
    token_id: str
    side: TradeSide
    size: Decimal
    price: Decimal
    timestamp: datetime
    order_id: str
    strategy_id: Optional[str] = None
    fees: Decimal = Decimal("0")

    @property
    def notional_value(self) -> Decimal:
        """Get notional value of trade."""
        return self.size * self.price

    @property
    def net_value(self) -> Decimal:
        """Get net value after fees."""
        if self.side == TradeSide.BUY:
            return self.notional_value + self.fees
        return self.notional_value - self.fees


class PositionTracker:
    """Tracks positions and trade history."""

    def __init__(self):
        """Initialize position tracker."""
        self._positions: dict[str, Position] = {}  # token_id -> Position
        self._closed_realized_pnl: Decimal = Decimal("0")  # PnL from removed positions
        self._trades: list[Trade] = []
        self._trade_counter = 0
        self._completed_trades = 0
        self._winning_trades = 0
        self._losing_trades = 0

    def record_fill(self, order: Order) -> Optional[Trade]:
        """Record an order fill and update position.

        Args:
            order: Filled order

        Returns:
            Trade record
        """
        if order.status != OrderStatus.FILLED:
            return None

        # Create trade record
        self._trade_counter += 1
        trade = Trade(
            trade_id=f"trade_{self._trade_counter}",
            market_id=order.market_id,
            token_id=order.token_id,
            side=order.side,
            size=order.filled_size,
            price=order.avg_fill_price,
            timestamp=datetime.now(),
            order_id=order.order_id,
            strategy_id=order.strategy_id,
        )
        self._trades.append(trade)

        # Update position
        self._update_position(trade)

        logger.info(
            f"Trade recorded: {trade.trade_id} {trade.side.value} "
            f"{trade.size} @ {trade.price}"
        )

        return trade

    def _update_position(self, trade: Trade) -> None:
        """Update position based on trade."""
        position = self._positions.get(trade.token_id)

        if position is None:
            # New position
            position = Position(
                market_id=trade.market_id,
                token_id=trade.token_id,
                side=trade.side,
                size=trade.size,
                avg_entry_price=trade.price,
                strategy_id=trade.strategy_id,
                total_cost=trade.notional_value,
            )
            self._positions[trade.token_id] = position
            return

        if trade.side == position.side:
            # Adding to position
            new_size = position.size + trade.size
            new_cost = position.total_cost + trade.notional_value
            position.avg_entry_price = new_cost / new_size
            position.size = new_size
            position.total_cost = new_cost
        else:
            # Reducing or closing position
            if trade.size >= position.size:
                # Close position and realize P&L
                close_size = position.size
                remaining = trade.size - close_size

                # Calculate realized P&L
                if position.side == TradeSide.BUY:
                    realized = close_size * (trade.price - position.avg_entry_price)
                else:
                    realized = close_size * (position.avg_entry_price - trade.price)

                position.realized_pnl += realized

                if remaining > 0:
                    # Flip position
                    position.side = trade.side
                    position.size = remaining
                    position.avg_entry_price = trade.price
                    position.total_cost = remaining * trade.price
                else:
                    # Position closed — accumulate realized PnL and remove
                    self._closed_realized_pnl += position.realized_pnl
                    self._completed_trades += 1
                    if position.realized_pnl > 0:
                        self._winning_trades += 1
                    elif position.realized_pnl < 0:
                        self._losing_trades += 1
                    del self._positions[trade.token_id]
                    return
            else:
                # Partial close
                close_size = trade.size
                remaining_size = position.size - close_size

                # Calculate realized P&L
                if position.side == TradeSide.BUY:
                    realized = close_size * (trade.price - position.avg_entry_price)
                else:
                    realized = close_size * (position.avg_entry_price - trade.price)

                position.realized_pnl += realized
                position.size = remaining_size
                position.total_cost = remaining_size * position.avg_entry_price

        position.updated_at = datetime.now()

    def get_position(self, token_id: str) -> Optional[Position]:
        """Get position by token ID.

        Args:
            token_id: Token ID

        Returns:
            Position or None
        """
        position = self._positions.get(token_id)
        if position and position.is_closed:
            return None
        return position

    def get_all_positions(self) -> list[Position]:
        """Get all open positions."""
        return [p for p in self._positions.values() if not p.is_closed]

    def get_positions_by_market(self, market_id: str) -> list[Position]:
        """Get positions for a specific market.

        Args:
            market_id: Market ID

        Returns:
            List of positions in market
        """
        return [
            p for p in self._positions.values()
            if p.market_id == market_id and not p.is_closed
        ]

    def get_positions_by_strategy(self, strategy_id: str) -> list[Position]:
        """Get positions for a specific strategy.

        Args:
            strategy_id: Strategy ID

        Returns:
            List of positions from strategy
        """
        return [
            p for p in self._positions.values()
            if p.strategy_id == strategy_id and not p.is_closed
        ]

    def get_trades(
        self,
        limit: int = 100,
        strategy_id: Optional[str] = None,
    ) -> list[Trade]:
        """Get recent trades.

        Args:
            limit: Maximum trades to return
            strategy_id: Optional filter by strategy

        Returns:
            List of trades
        """
        trades = self._trades

        if strategy_id:
            trades = [t for t in trades if t.strategy_id == strategy_id]

        return trades[-limit:]

    def total_unrealized_pnl(
        self, price_map: dict[str, Decimal]
    ) -> Decimal:
        """Calculate total unrealized P&L across all positions.

        Args:
            price_map: Dict mapping token_id to current price

        Returns:
            Total unrealized P&L
        """
        total = Decimal("0")

        for position in self.get_all_positions():
            current_price = price_map.get(position.token_id)
            if current_price:
                total += position.unrealized_pnl(current_price)

        return total

    def total_realized_pnl(self) -> Decimal:
        """Get total realized P&L across all positions (open + closed)."""
        return self._closed_realized_pnl + sum(
            p.realized_pnl for p in self._positions.values()
        )

    def total_exposure(self) -> Decimal:
        """Get total notional exposure."""
        return sum(p.notional_value for p in self.get_all_positions())

    @property
    def stats(self) -> dict:
        """Get tracker statistics."""
        positions = self.get_all_positions()
        return {
            "open_positions": len(positions),
            "total_trades": len(self._trades),
            "completed_trades": self._completed_trades,
            "winning_trades": self._winning_trades,
            "losing_trades": self._losing_trades,
            "total_realized_pnl": float(self.total_realized_pnl()),
            "total_exposure": float(self.total_exposure()),
        }

    def write_off_dust(self, token_id: str) -> None:
        """Write off a dust position that's too small to sell.

        Removes the position and accumulates any realized PnL.
        """
        position = self._positions.get(token_id)
        if position:
            self._closed_realized_pnl += position.realized_pnl
            del self._positions[token_id]
            logger.info(f"Dust position written off: {token_id}")

    def reset(self) -> None:
        """Reset all positions and trades."""
        self._positions.clear()
        self._closed_realized_pnl = Decimal("0")
        self._trades.clear()
        self._trade_counter = 0
        self._completed_trades = 0
        self._winning_trades = 0
        self._losing_trades = 0
        logger.info("Position tracker reset")
