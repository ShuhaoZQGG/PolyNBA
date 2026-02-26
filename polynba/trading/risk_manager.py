"""Risk management and limits enforcement."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from ..data.models import TradeSide
from .executor import Order
from .position_tracker import Position, PositionTracker

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk limit configuration."""

    # Position limits
    max_position_size_usdc: Decimal = Decimal("100")
    max_total_exposure_usdc: Decimal = Decimal("500")
    max_concurrent_positions: int = 5
    max_position_per_market: int = 2

    # Loss limits
    max_loss_per_trade_usdc: Decimal = Decimal("25")
    max_daily_loss_usdc: Decimal = Decimal("100")
    stop_loss_percent: float = 10.0

    # Hard circuit breaker per position (absolute loss limit, safety net)
    hard_loss_limit_percent: float = 30.0

    # Profit taking
    take_profit_percent: float = 15.0

    # Order limits
    max_order_size_usdc: Decimal = Decimal("50")
    min_order_size_usdc: Decimal = Decimal("5")


@dataclass
class RiskCheckResult:
    """Result of a risk check."""

    allowed: bool
    reason: Optional[str] = None
    adjusted_size: Optional[Decimal] = None


@dataclass
class DailyStats:
    """Daily trading statistics."""

    date: datetime
    trades: int = 0
    wins: int = 0
    losses: int = 0
    realized_pnl: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    peak_pnl: Decimal = Decimal("0")


class RiskManager:
    """Enforces risk limits and manages position sizing."""

    def __init__(
        self,
        limits: Optional[RiskLimits] = None,
        position_tracker: Optional[PositionTracker] = None,
    ):
        """Initialize risk manager.

        Args:
            limits: Risk limit configuration
            position_tracker: Position tracker instance
        """
        self._limits = limits or RiskLimits()
        self._position_tracker = position_tracker or PositionTracker()

        # Daily tracking
        self._daily_stats: dict[str, DailyStats] = {}
        self._daily_pnl = Decimal("0")

        # Circuit breaker
        self._circuit_breaker_active = False
        self._circuit_breaker_until: Optional[datetime] = None

    @property
    def limits(self) -> RiskLimits:
        """Get current risk limits."""
        return self._limits

    def update_limits(self, limits: RiskLimits) -> None:
        """Update risk limits.

        Args:
            limits: New risk limits
        """
        self._limits = limits
        logger.info("Risk limits updated")

    def check_order(
        self,
        market_id: str,
        token_id: str,
        side: TradeSide,
        size: Decimal,
        price: Decimal,
    ) -> RiskCheckResult:
        """Check if an order is allowed by risk limits.

        Args:
            market_id: Market ID
            token_id: Token ID
            side: Order side
            size: Order size
            price: Order price

        Returns:
            RiskCheckResult with allowed status
        """
        # Check circuit breaker
        if self._circuit_breaker_active:
            if self._circuit_breaker_until and datetime.now() < self._circuit_breaker_until:
                return RiskCheckResult(
                    allowed=False,
                    reason="Circuit breaker active",
                )
            else:
                self._reset_circuit_breaker()

        notional = size * price

        # Check minimum size
        if notional < self._limits.min_order_size_usdc:
            return RiskCheckResult(
                allowed=False,
                reason=f"Order size ${notional} below minimum ${self._limits.min_order_size_usdc}",
            )

        # Check maximum order size
        if notional > self._limits.max_order_size_usdc:
            adjusted = self._limits.max_order_size_usdc / price
            return RiskCheckResult(
                allowed=True,
                reason=f"Order size reduced from ${notional} to ${self._limits.max_order_size_usdc}",
                adjusted_size=adjusted,
            )

        # Check position size limit
        existing_position = self._position_tracker.get_position(token_id)
        if existing_position and side == existing_position.side:
            new_total = existing_position.notional_value + notional
            if new_total > self._limits.max_position_size_usdc:
                remaining = self._limits.max_position_size_usdc - existing_position.notional_value
                if remaining <= 0:
                    return RiskCheckResult(
                        allowed=False,
                        reason="Maximum position size reached",
                    )
                adjusted = remaining / price
                return RiskCheckResult(
                    allowed=True,
                    reason=f"Size adjusted to stay within position limit",
                    adjusted_size=adjusted,
                )

        # Check total exposure
        total_exposure = self._position_tracker.total_exposure()
        if total_exposure + notional > self._limits.max_total_exposure_usdc:
            remaining = self._limits.max_total_exposure_usdc - total_exposure
            if remaining <= 0:
                return RiskCheckResult(
                    allowed=False,
                    reason="Maximum total exposure reached",
                )
            adjusted = remaining / price
            return RiskCheckResult(
                allowed=True,
                reason="Size adjusted to stay within exposure limit",
                adjusted_size=adjusted,
            )

        # Check concurrent positions
        positions = self._position_tracker.get_all_positions()
        if side == TradeSide.BUY and not existing_position:
            if len(positions) >= self._limits.max_concurrent_positions:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Maximum concurrent positions ({self._limits.max_concurrent_positions}) reached",
                )

        # Check positions per market
        market_positions = self._position_tracker.get_positions_by_market(market_id)
        if len(market_positions) >= self._limits.max_position_per_market:
            if not any(p.token_id == token_id for p in market_positions):
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Maximum positions per market ({self._limits.max_position_per_market}) reached",
                )

        # Check daily loss limit
        if self._daily_pnl < -self._limits.max_daily_loss_usdc:
            return RiskCheckResult(
                allowed=False,
                reason="Daily loss limit reached",
            )

        return RiskCheckResult(allowed=True)

    def check_position_risk(
        self,
        position: Position,
        current_price: Decimal,
    ) -> tuple[bool, Optional[str]]:
        """Check if position needs risk action.

        Args:
            position: Position to check
            current_price: Current market price

        Returns:
            Tuple of (needs_action, action_type)
            action_type is "stop_loss" or "take_profit"
        """
        pnl_percent = position.unrealized_pnl_percent(current_price)

        # Check stop loss
        if pnl_percent <= -self._limits.stop_loss_percent:
            logger.warning(
                f"Stop loss triggered for {position.token_id}: {pnl_percent:.2f}%"
            )
            return True, "stop_loss"

        # Check take profit
        if pnl_percent >= self._limits.take_profit_percent:
            logger.info(
                f"Take profit triggered for {position.token_id}: {pnl_percent:.2f}%"
            )
            return True, "take_profit"

        return False, None

    def check_hard_loss_limit(
        self,
        position: Position,
        current_price: Decimal,
    ) -> bool:
        """Check if position has hit the hard loss limit (circuit breaker).

        This is a safety net that forces an exit regardless of strategy
        stop-loss settings, in case the normal stop-loss mechanism fails.

        Args:
            position: Position to check
            current_price: Current market price

        Returns:
            True if position must be force-exited
        """
        pnl_percent = position.unrealized_pnl_percent(current_price)

        if pnl_percent <= -self._limits.hard_loss_limit_percent:
            logger.warning(
                f"HARD CIRCUIT BREAKER: position {position.token_id} at "
                f"{pnl_percent:.1f}% loss (limit: -{self._limits.hard_loss_limit_percent}%)"
            )
            return True

        return False

    def record_trade_result(
        self,
        pnl: Decimal,
        is_win: bool,
    ) -> None:
        """Record a trade result for daily tracking.

        Args:
            pnl: Trade P&L
            is_win: Whether trade was profitable
        """
        today = datetime.now().strftime("%Y-%m-%d")

        if today not in self._daily_stats:
            self._daily_stats[today] = DailyStats(date=datetime.now())

        stats = self._daily_stats[today]
        stats.trades += 1
        stats.realized_pnl += pnl
        self._daily_pnl += pnl

        if is_win:
            stats.wins += 1
        else:
            stats.losses += 1

        # Update peak and drawdown
        if stats.realized_pnl > stats.peak_pnl:
            stats.peak_pnl = stats.realized_pnl
        else:
            drawdown = stats.peak_pnl - stats.realized_pnl
            if drawdown > stats.max_drawdown:
                stats.max_drawdown = drawdown

        # Check for circuit breaker
        if self._daily_pnl <= -self._limits.max_daily_loss_usdc:
            self._activate_circuit_breaker()

    def _activate_circuit_breaker(self, duration_hours: int = 1) -> None:
        """Activate circuit breaker to stop trading.

        Args:
            duration_hours: Hours to remain active
        """
        self._circuit_breaker_active = True
        self._circuit_breaker_until = datetime.now() + timedelta(hours=duration_hours)
        logger.warning(
            f"Circuit breaker activated until {self._circuit_breaker_until}"
        )

    def _reset_circuit_breaker(self) -> None:
        """Reset circuit breaker."""
        self._circuit_breaker_active = False
        self._circuit_breaker_until = None
        logger.info("Circuit breaker reset")

    def reset_daily_stats(self) -> None:
        """Reset daily statistics (for new trading day)."""
        self._daily_pnl = Decimal("0")
        self._circuit_breaker_active = False
        self._circuit_breaker_until = None
        logger.info("Daily stats reset")

    def calculate_kelly_size(
        self,
        win_probability: float,
        win_amount: float,
        loss_amount: float,
        fraction: float = 0.25,
    ) -> Decimal:
        """Calculate position size using Kelly Criterion.

        Args:
            win_probability: Probability of winning (0-1)
            win_amount: Expected win amount per unit
            loss_amount: Expected loss amount per unit
            fraction: Kelly fraction (default 0.25 for quarter-Kelly)

        Returns:
            Recommended position size as fraction of bankroll
        """
        if loss_amount == 0:
            return Decimal("0")

        # Kelly formula: (bp - q) / b
        # where b = win/loss ratio, p = win prob, q = 1-p
        b = win_amount / loss_amount
        p = win_probability
        q = 1 - p

        kelly = (b * p - q) / b

        # Apply fraction and cap
        kelly = max(0, kelly) * fraction
        kelly = min(kelly, 0.25)  # Never bet more than 25%

        return Decimal(str(kelly))

    @property
    def stats(self) -> dict:
        """Get risk manager statistics."""
        today = datetime.now().strftime("%Y-%m-%d")
        daily = self._daily_stats.get(today, DailyStats(date=datetime.now()))

        return {
            "daily_pnl": float(self._daily_pnl),
            "daily_trades": daily.trades,
            "daily_wins": daily.wins,
            "daily_losses": daily.losses,
            "daily_win_rate": daily.wins / daily.trades if daily.trades > 0 else 0,
            "max_drawdown": float(daily.max_drawdown),
            "circuit_breaker_active": self._circuit_breaker_active,
        }

    @property
    def is_trading_allowed(self) -> bool:
        """Check if trading is currently allowed."""
        if self._circuit_breaker_active:
            if self._circuit_breaker_until and datetime.now() < self._circuit_breaker_until:
                return False
            self._reset_circuit_breaker()

        if self._daily_pnl <= -self._limits.max_daily_loss_usdc:
            return False

        return True
