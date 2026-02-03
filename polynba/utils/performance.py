"""Performance tracking and metrics."""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Record of a single trade."""

    trade_id: str
    strategy_id: str
    game_id: str
    market_id: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_percent: float
    entry_time: str
    exit_time: str
    exit_reason: str
    edge_at_entry: float
    confidence_at_entry: int


@dataclass
class DailyMetrics:
    """Daily performance metrics."""

    date: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_pnl: float = 0.0
    fees: float = 0.0
    net_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_equity: float = 0.0
    average_edge: float = 0.0
    average_confidence: float = 0.0

    @property
    def win_rate(self) -> float:
        """Calculate win rate."""
        if self.trades == 0:
            return 0.0
        return self.wins / self.trades

    @property
    def profit_factor(self) -> float:
        """Calculate profit factor (gross wins / gross losses)."""
        # This would need separate win/loss tracking
        return 0.0


@dataclass
class StrategyMetrics:
    """Performance metrics for a strategy."""

    strategy_id: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0

    @property
    def win_rate(self) -> float:
        """Calculate win rate."""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def expectancy(self) -> float:
        """Calculate trade expectancy."""
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl / self.total_trades


@dataclass
class PerformanceSnapshot:
    """Point-in-time performance snapshot."""

    timestamp: str
    total_equity: float
    deployed_capital: float
    unrealized_pnl: float
    realized_pnl: float
    daily_pnl: float
    open_positions: int
    pending_orders: int


class PerformanceTracker:
    """Tracks trading performance and metrics."""

    def __init__(
        self,
        initial_equity: float = 1000.0,
        save_path: Optional[Path] = None,
    ):
        """Initialize performance tracker.

        Args:
            initial_equity: Starting equity
            save_path: Path to save performance data
        """
        self._initial_equity = initial_equity
        self._current_equity = initial_equity
        self._save_path = save_path

        # Trade records
        self._trades: list[TradeRecord] = []

        # Daily metrics
        self._daily_metrics: dict[str, DailyMetrics] = {}
        self._current_date = datetime.now().strftime("%Y-%m-%d")

        # Strategy metrics
        self._strategy_metrics: dict[str, StrategyMetrics] = {}

        # Snapshots
        self._snapshots: list[PerformanceSnapshot] = []

        # Running calculations
        self._peak_equity = initial_equity
        self._max_drawdown = 0.0
        self._wins_streak = 0
        self._losses_streak = 0

    def record_trade(
        self,
        trade_id: str,
        strategy_id: str,
        game_id: str,
        market_id: str,
        side: str,
        entry_price: float,
        exit_price: float,
        size: float,
        exit_reason: str,
        edge_at_entry: float,
        confidence_at_entry: int,
        entry_time: Optional[datetime] = None,
        exit_time: Optional[datetime] = None,
    ) -> TradeRecord:
        """Record a completed trade.

        Args:
            trade_id: Unique trade identifier
            strategy_id: Strategy that made the trade
            ... other params ...

        Returns:
            TradeRecord
        """
        # Calculate P&L
        if side == "buy":
            pnl = (exit_price - entry_price) * size
        else:
            pnl = (entry_price - exit_price) * size

        pnl_percent = (pnl / (entry_price * size)) * 100 if entry_price > 0 else 0

        record = TradeRecord(
            trade_id=trade_id,
            strategy_id=strategy_id,
            game_id=game_id,
            market_id=market_id,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
            pnl=pnl,
            pnl_percent=pnl_percent,
            entry_time=(entry_time or datetime.now()).isoformat(),
            exit_time=(exit_time or datetime.now()).isoformat(),
            exit_reason=exit_reason,
            edge_at_entry=edge_at_entry,
            confidence_at_entry=confidence_at_entry,
        )

        self._trades.append(record)

        # Update metrics
        self._update_metrics(record)

        logger.info(
            f"Trade recorded: {trade_id} | PnL: ${pnl:.2f} ({pnl_percent:.1f}%)"
        )

        return record

    def _update_metrics(self, trade: TradeRecord) -> None:
        """Update all metrics based on a trade."""
        # Update equity
        self._current_equity += trade.pnl

        # Update peak and drawdown
        if self._current_equity > self._peak_equity:
            self._peak_equity = self._current_equity

        current_drawdown = (self._peak_equity - self._current_equity) / self._peak_equity
        if current_drawdown > self._max_drawdown:
            self._max_drawdown = current_drawdown

        # Update streaks
        is_win = trade.pnl > 0
        if is_win:
            self._wins_streak += 1
            self._losses_streak = 0
        else:
            self._losses_streak += 1
            self._wins_streak = 0

        # Update daily metrics
        self._update_daily_metrics(trade)

        # Update strategy metrics
        self._update_strategy_metrics(trade)

    def _update_daily_metrics(self, trade: TradeRecord) -> None:
        """Update daily metrics."""
        today = datetime.now().strftime("%Y-%m-%d")

        if today not in self._daily_metrics:
            self._daily_metrics[today] = DailyMetrics(date=today)

        metrics = self._daily_metrics[today]
        metrics.trades += 1
        metrics.gross_pnl += trade.pnl
        metrics.net_pnl += trade.pnl  # Fees would be subtracted here

        if trade.pnl > 0:
            metrics.wins += 1
        else:
            metrics.losses += 1

        # Update running averages
        metrics.average_edge = (
            (metrics.average_edge * (metrics.trades - 1) + trade.edge_at_entry)
            / metrics.trades
        )
        metrics.average_confidence = (
            (metrics.average_confidence * (metrics.trades - 1) + trade.confidence_at_entry)
            / metrics.trades
        )

    def _update_strategy_metrics(self, trade: TradeRecord) -> None:
        """Update strategy-specific metrics."""
        if trade.strategy_id not in self._strategy_metrics:
            self._strategy_metrics[trade.strategy_id] = StrategyMetrics(
                strategy_id=trade.strategy_id
            )

        metrics = self._strategy_metrics[trade.strategy_id]
        metrics.total_trades += 1
        metrics.total_pnl += trade.pnl

        is_win = trade.pnl > 0

        if is_win:
            metrics.winning_trades += 1
            if trade.pnl > metrics.largest_win:
                metrics.largest_win = trade.pnl
        else:
            metrics.losing_trades += 1
            if trade.pnl < metrics.largest_loss:
                metrics.largest_loss = trade.pnl

        # Update averages
        if metrics.winning_trades > 0:
            metrics.average_win = sum(
                t.pnl for t in self._trades
                if t.strategy_id == trade.strategy_id and t.pnl > 0
            ) / metrics.winning_trades

        if metrics.losing_trades > 0:
            metrics.average_loss = sum(
                t.pnl for t in self._trades
                if t.strategy_id == trade.strategy_id and t.pnl < 0
            ) / metrics.losing_trades

    def take_snapshot(
        self,
        deployed_capital: float,
        unrealized_pnl: float,
        open_positions: int,
        pending_orders: int,
    ) -> PerformanceSnapshot:
        """Take a performance snapshot.

        Args:
            deployed_capital: Currently deployed capital
            unrealized_pnl: Unrealized P&L
            open_positions: Number of open positions
            pending_orders: Number of pending orders

        Returns:
            PerformanceSnapshot
        """
        realized_pnl = self._current_equity - self._initial_equity

        # Calculate daily P&L
        today = datetime.now().strftime("%Y-%m-%d")
        daily_metrics = self._daily_metrics.get(today)
        daily_pnl = daily_metrics.net_pnl if daily_metrics else 0.0

        snapshot = PerformanceSnapshot(
            timestamp=datetime.now().isoformat(),
            total_equity=self._current_equity,
            deployed_capital=deployed_capital,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            daily_pnl=daily_pnl,
            open_positions=open_positions,
            pending_orders=pending_orders,
        )

        self._snapshots.append(snapshot)
        return snapshot

    def get_summary(self) -> dict[str, Any]:
        """Get performance summary."""
        total_trades = len(self._trades)
        winning_trades = sum(1 for t in self._trades if t.pnl > 0)

        return {
            "initial_equity": self._initial_equity,
            "current_equity": self._current_equity,
            "total_pnl": self._current_equity - self._initial_equity,
            "total_return_percent": (self._current_equity / self._initial_equity - 1) * 100,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": total_trades - winning_trades,
            "win_rate": winning_trades / total_trades if total_trades > 0 else 0,
            "max_drawdown_percent": self._max_drawdown * 100,
            "peak_equity": self._peak_equity,
            "current_win_streak": self._wins_streak,
            "current_loss_streak": self._losses_streak,
        }

    def get_strategy_summary(self, strategy_id: str) -> dict[str, Any]:
        """Get summary for a specific strategy."""
        metrics = self._strategy_metrics.get(strategy_id)
        if not metrics:
            return {}

        return {
            "strategy_id": strategy_id,
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "win_rate": metrics.win_rate,
            "total_pnl": metrics.total_pnl,
            "expectancy": metrics.expectancy,
            "average_win": metrics.average_win,
            "average_loss": metrics.average_loss,
            "largest_win": metrics.largest_win,
            "largest_loss": metrics.largest_loss,
        }

    def save(self, path: Optional[Path] = None) -> None:
        """Save performance data to file.

        Args:
            path: Optional override path
        """
        save_path = path or self._save_path
        if not save_path:
            return

        data = {
            "summary": self.get_summary(),
            "trades": [asdict(t) for t in self._trades],
            "daily_metrics": {k: asdict(v) for k, v in self._daily_metrics.items()},
            "strategy_metrics": {k: asdict(v) for k, v in self._strategy_metrics.items()},
            "snapshots": [asdict(s) for s in self._snapshots[-100:]],  # Last 100
        }

        with open(save_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Performance data saved to {save_path}")

    def load(self, path: Optional[Path] = None) -> None:
        """Load performance data from file.

        Args:
            path: Optional override path
        """
        load_path = path or self._save_path
        if not load_path or not load_path.exists():
            return

        with open(load_path) as f:
            data = json.load(f)

        # Restore trades
        self._trades = [TradeRecord(**t) for t in data.get("trades", [])]

        # Restore daily metrics
        for date, metrics in data.get("daily_metrics", {}).items():
            self._daily_metrics[date] = DailyMetrics(**metrics)

        # Restore strategy metrics
        for sid, metrics in data.get("strategy_metrics", {}).items():
            self._strategy_metrics[sid] = StrategyMetrics(**metrics)

        logger.info(f"Performance data loaded from {load_path}")
