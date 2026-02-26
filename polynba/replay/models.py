"""Data models for strategy replay."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class MarketSnapshot:
    """One iteration's worth of parsed log data."""

    timestamp: datetime
    iteration: int
    away_team: str
    home_team: str
    away_score: int
    home_score: int
    period: str  # "Q1", "Q2", "Q3", "Q4", "OT1", etc.
    clock: str  # Original clock string e.g. "6:22"
    clock_seconds: int  # Clock converted to seconds remaining in period
    total_seconds_remaining: int
    home_market_price: Decimal  # 0-1
    away_market_price: Decimal  # 0-1
    home_edge_pct: float
    away_edge_pct: float
    confidence: int
    original_edge_threshold: Optional[float] = None
    has_signal: bool = False
    signal_details: Optional[str] = None


@dataclass
class ReplayTrade:
    """A trade generated during replay."""

    iteration: int
    timestamp: datetime
    side: str  # "home" or "away"
    team: str
    action: str  # "buy" or "sell"
    shares: Decimal
    price: Decimal
    size_usdc: Decimal
    edge_pct: float
    confidence: int
    reason: str
    strategy_id: str


@dataclass
class ClosedPosition:
    """A position that was opened and closed during replay."""

    entry_trade: ReplayTrade
    exit_trade: ReplayTrade
    pnl_usdc: Decimal
    pnl_percent: float
    hold_iterations: int


@dataclass
class OpenPosition:
    """A position still open at end of replay."""

    entry_trade: ReplayTrade
    current_price: Decimal
    unrealized_pnl_usdc: Decimal
    unrealized_pnl_percent: float


@dataclass
class ReplayResult:
    """Complete result of a strategy replay."""

    log_path: str
    away_team: str
    home_team: str
    game_date: str
    strategy_id: str
    overrides: dict
    total_snapshots: int
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    bankroll: Decimal = Decimal("500")

    trades: list[ReplayTrade] = field(default_factory=list)
    closed_positions: list[ClosedPosition] = field(default_factory=list)
    open_positions: list[OpenPosition] = field(default_factory=list)

    original_signal_count: int = 0

    @property
    def total_pnl(self) -> Decimal:
        realized = sum((p.pnl_usdc for p in self.closed_positions), Decimal("0"))
        unrealized = sum((p.unrealized_pnl_usdc for p in self.open_positions), Decimal("0"))
        return realized + unrealized

    @property
    def realized_pnl(self) -> Decimal:
        return sum((p.pnl_usdc for p in self.closed_positions), Decimal("0"))

    @property
    def unrealized_pnl(self) -> Decimal:
        return sum((p.unrealized_pnl_usdc for p in self.open_positions), Decimal("0"))

    @property
    def win_rate(self) -> Optional[float]:
        if not self.closed_positions:
            return None
        wins = sum(1 for p in self.closed_positions if p.pnl_usdc > 0)
        return wins / len(self.closed_positions)

    @property
    def max_drawdown(self) -> Decimal:
        """Calculate max drawdown from equity curve."""
        if not self.closed_positions:
            return Decimal("0")
        equity = Decimal("0")
        peak = Decimal("0")
        max_dd = Decimal("0")
        for pos in self.closed_positions:
            equity += pos.pnl_usdc
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        return max_dd
