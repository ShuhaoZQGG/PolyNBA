"""Portfolio display utility for clean session summaries."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from ..trading.position_tracker import Position, Trade


@dataclass
class PortfolioSnapshot:
    """Snapshot of portfolio state for display."""

    # Timing
    session_start: datetime
    current_time: datetime
    iteration: int = 0

    # Balance
    initial_balance: Decimal = Decimal("0")
    current_balance: Decimal = Decimal("0")
    available_balance: Decimal = Decimal("0")

    # P&L
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")

    # Trades
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    # Positions
    open_positions: int = 0
    pending_orders: int = 0
    total_exposure: Decimal = Decimal("0")

    # Risk
    max_drawdown_pct: float = 0.0
    circuit_breaker_active: bool = False
    daily_loss_limit_remaining: Optional[Decimal] = None


class PortfolioDisplay:
    """Displays portfolio summaries in a clean, readable format."""

    def __init__(self, initial_balance: float):
        """Initialize portfolio display.

        Args:
            initial_balance: Starting balance for the session
        """
        self._session_start = datetime.now()
        self._initial_balance = Decimal(str(initial_balance))
        self._last_display_time: Optional[datetime] = None

    def format_summary(self, snapshot: PortfolioSnapshot) -> str:
        """Format portfolio snapshot as a display string.

        Args:
            snapshot: Current portfolio state

        Returns:
            Formatted string for display
        """
        # Calculate derived values
        session_duration = snapshot.current_time - snapshot.session_start
        total_pnl = snapshot.realized_pnl + snapshot.unrealized_pnl
        total_return_pct = (
            float(total_pnl / snapshot.initial_balance * 100)
            if snapshot.initial_balance > 0
            else 0.0
        )
        win_rate = (
            snapshot.winning_trades / snapshot.total_trades * 100
            if snapshot.total_trades > 0
            else 0.0
        )

        # Format duration
        hours, remainder = divmod(int(session_duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # Build the display
        width = 58
        line = "═" * width

        # P&L color indicator (for terminal that supports it)
        pnl_indicator = "▲" if total_pnl >= 0 else "▼"
        pnl_sign = "+" if total_pnl >= 0 else ""

        lines = [
            "",
            f"╔{line}╗",
            f"║{'PORTFOLIO SUMMARY':^{width}}║",
            f"╠{line}╣",
            f"║  Session: {duration_str:<15} {'Iteration':>15}: {snapshot.iteration:<10}  ║",
            f"╠{line}╣",
            f"║  {'BALANCE':<20} {'P&L':>33}  ║",
            f"║  Initial:  ${float(snapshot.initial_balance):>10,.2f}    "
            f"Realized:  {pnl_sign}${float(snapshot.realized_pnl):>10,.2f}  ║",
            f"║  Current:  ${float(snapshot.current_balance):>10,.2f}    "
            f"Unrealized: {pnl_sign}${float(snapshot.unrealized_pnl):>9,.2f}  ║",
            f"║  Available: ${float(snapshot.available_balance):>9,.2f}    "
            f"Total: {pnl_indicator} {pnl_sign}${float(total_pnl):>10,.2f}  ║",
            f"╠{line}╣",
            f"║  {'TRADES':<20} {'POSITIONS':>33}  ║",
            f"║  Total:     {snapshot.total_trades:>10}         "
            f"Open:       {snapshot.open_positions:>10}  ║",
            f"║  Wins:      {snapshot.winning_trades:>10}         "
            f"Pending:    {snapshot.pending_orders:>10}  ║",
            f"║  Losses:    {snapshot.losing_trades:>10}         "
            f"Exposure: ${float(snapshot.total_exposure):>10,.2f}  ║",
            f"║  Win Rate:  {win_rate:>9.1f}%         "
            f"Return:   {total_return_pct:>+10.2f}%  ║",
            f"╠{line}╣",
            f"║  {'RISK':<54}  ║",
            f"║  Max Drawdown: {snapshot.max_drawdown_pct:>6.2f}%    "
            f"Circuit Breaker: {'ACTIVE' if snapshot.circuit_breaker_active else 'OK':>10}  ║",
            f"╚{line}╝",
            "",
        ]

        return "\n".join(lines)

    def format_compact_summary(self, snapshot: PortfolioSnapshot) -> str:
        """Format a compact one-line summary.

        Args:
            snapshot: Current portfolio state

        Returns:
            Compact summary string
        """
        total_pnl = snapshot.realized_pnl + snapshot.unrealized_pnl
        pnl_sign = "+" if total_pnl >= 0 else ""
        win_rate = (
            snapshot.winning_trades / snapshot.total_trades * 100
            if snapshot.total_trades > 0
            else 0.0
        )

        return (
            f"[PORTFOLIO] "
            f"Balance: ${float(snapshot.current_balance):,.2f} | "
            f"P&L: {pnl_sign}${float(total_pnl):,.2f} | "
            f"Trades: {snapshot.total_trades} ({win_rate:.0f}% win) | "
            f"Positions: {snapshot.open_positions}"
        )

    def format_trades(self, trades: list[Trade]) -> str:
        """Format recent trades as a display string."""
        width = 90

        if not trades:
            return self._format_box("RECENT TRADES", ["No trades recorded."], width)

        rows = [
            (
                f"  {'Time':<19} {'Side':<4} {'Size':>10} {'Price':>9} "
                f"{'Token':<12} {'Market':<10} {'Strategy':<12}"
            )
        ]
        rows.append(f"  {'-' * (width - 2)}")

        for trade in trades:
            time_str = trade.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            side_str = trade.side.value.upper()
            strategy = trade.strategy_id or "-"
            row = (
                f"  {self._fit(time_str, 19):<19} "
                f"{self._fit(side_str, 4):<4} "
                f"{float(trade.size):>10,.2f} "
                f"{float(trade.price):>9,.4f} "
                f"{self._fit(trade.token_id, 12):<12} "
                f"{self._fit(trade.market_id, 10):<10} "
                f"{self._fit(strategy, 12):<12}"
            )
            rows.append(row)

        return self._format_box("RECENT TRADES", rows, width)

    def format_positions(self, positions: list[Position]) -> str:
        """Format open positions as a display string."""
        width = 90

        if not positions:
            return self._format_box("OPEN POSITIONS", ["No open positions."], width)

        rows = [
            (
                f"  {'Token':<12} {'Side':<4} {'Size':>10} {'AvgPx':>10} "
                f"{'Notional':>12} {'Realized':>12} {'Strategy':<12}"
            )
        ]
        rows.append(f"  {'-' * (width - 2)}")

        for position in positions:
            side_str = position.side.value.upper()
            strategy = position.strategy_id or "-"
            row = (
                f"  {self._fit(position.token_id, 12):<12} "
                f"{self._fit(side_str, 4):<4} "
                f"{float(position.size):>10,.2f} "
                f"{float(position.avg_entry_price):>10,.4f} "
                f"{float(position.notional_value):>12,.2f} "
                f"{float(position.realized_pnl):>12,.2f} "
                f"{self._fit(strategy, 12):<12}"
            )
            rows.append(row)

        return self._format_box("OPEN POSITIONS", rows, width)

    def _format_box(self, title: str, rows: list[str], width: int) -> str:
        """Wrap rows in a boxed layout."""
        line = "═" * width
        lines = [
            "",
            f"╔{line}╗",
            f"║{title:^{width}}║",
            f"╠{line}╣",
        ]

        for row in rows:
            if len(row) > width:
                row = self._fit(row, width)
            lines.append(f"║{row:<{width}}║")

        lines.extend([f"╚{line}╝", ""])
        return "\n".join(lines)

    def _fit(self, text: str, width: int) -> str:
        """Trim text to fit within width."""
        if len(text) <= width:
            return text
        if width <= 3:
            return text[:width]
        return f"{text[:width - 3]}..."

    def should_display(self, interval_seconds: int = 60) -> bool:
        """Check if enough time has passed to display again.

        Args:
            interval_seconds: Minimum seconds between displays

        Returns:
            True if should display
        """
        if self._last_display_time is None:
            return True

        elapsed = datetime.now() - self._last_display_time
        return elapsed >= timedelta(seconds=interval_seconds)

    def mark_displayed(self) -> None:
        """Mark that a display was shown."""
        self._last_display_time = datetime.now()

    @property
    def session_start(self) -> datetime:
        """Get session start time."""
        return self._session_start

    @property
    def initial_balance(self) -> Decimal:
        """Get initial balance."""
        return self._initial_balance
