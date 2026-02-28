"""Strategy YAML configuration loader."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class StrategyMetadata:
    """Strategy metadata."""

    name: str
    description: str = ""
    risk_level: str = "medium"  # low, medium, high
    enabled: bool = True


@dataclass
class FactorWeights:
    """Factor weights for strategy."""

    market_sentiment: float = 0.40
    game_context: float = 0.35
    team_strength: float = 0.25

    def __post_init__(self):
        """Normalize weights to sum to 1."""
        total = self.market_sentiment + self.game_context + self.team_strength
        if total > 0 and abs(total - 1.0) > 0.001:
            self.market_sentiment /= total
            self.game_context /= total
            self.team_strength /= total


@dataclass
class RuleCondition:
    """A single rule condition."""

    name: str
    type: str  # threshold, list_empty, comparison
    field: str
    operator: str = ">="
    value: Any = None
    compare_field: Optional[str] = None


@dataclass
class EntryRules:
    """Entry rules configuration."""

    conditions: list[RuleCondition] = field(default_factory=list)


@dataclass
class ProfitTarget:
    """Profit target at specific time."""

    time_remaining_min: int  # Minimum seconds remaining
    target_percentage: float


@dataclass
class StopLossWideningBucket:
    """Time-based stop loss widening bucket."""

    time_remaining_max: int  # Seconds remaining threshold (<=)
    multiplier: float  # Multiply base stop loss by this


@dataclass
class ExitRules:
    """Exit rules configuration."""

    profit_targets: list[ProfitTarget] = field(default_factory=list)
    stop_loss_percent: float = 10.0
    time_stop_seconds: int = 60
    late_game_widening: list[StopLossWideningBucket] = field(default_factory=list)
    exit_max_spread_percent: float = 0.0  # Spread guard: suppress stop loss when spread > this (0 = disabled)
    patience_before_seconds: int = 0      # Suppress SL when game has > N seconds left (0 = disabled)
    max_averagedown_count: int = 0        # Max times to average down per position (0 = disabled)
    max_averagedown_multiplier: float = 3.0  # Max total position cost = mult * initial entry cost


@dataclass
class PositionSizing:
    """Position sizing configuration."""

    method: str = "kelly_fraction"  # kelly_fraction, fixed, percentage
    kelly_multiplier: float = 0.25
    max_position_usdc: float = 100.0
    min_position_usdc: float = 10.0
    fixed_size_usdc: float = 50.0  # For fixed method
    percentage_of_bankroll: float = 0.05  # For percentage method
    late_game_seconds: int = 720  # Threshold for late-game scaling (default 12 min = start of Q4)
    late_game_multiplier: float = 1.0  # Scale factor for late-game sizing (1.0 = no change)


@dataclass
class StrategyRiskLimits:
    """Strategy-specific risk limits."""

    max_concurrent_positions: int = 5
    max_daily_loss_usdc: float = 200.0
    max_position_per_game: int = 1
    cooldown_iterations: int = 0  # Iterations to wait after stop loss before re-entry
    max_stop_losses_per_game: int = 0  # Max stop losses per game (0 = unlimited)
    max_loss_per_game_usdc: float = 0.0  # Per-game loss cap in USDC (0 = unlimited)
    profit_cooldown_iterations: int = 0  # Cooldown after profit taking (0 = disabled)


@dataclass
class StrategyConfig:
    """Complete strategy configuration."""

    id: str
    metadata: StrategyMetadata
    factor_weights: FactorWeights
    entry_rules: EntryRules
    exit_rules: ExitRules
    position_sizing: PositionSizing
    risk_limits: StrategyRiskLimits


class StrategyLoader:
    """Loads strategy configurations from YAML files."""

    def __init__(self, strategies_dir: Optional[Path] = None):
        """Initialize strategy loader.

        Args:
            strategies_dir: Directory containing strategy YAML files
        """
        if strategies_dir is None:
            # Default to config/strategies relative to this file
            strategies_dir = Path(__file__).parent.parent / "config" / "strategies"

        self._strategies_dir = strategies_dir
        self._strategies: dict[str, StrategyConfig] = {}

    def load_all(self) -> dict[str, StrategyConfig]:
        """Load all strategy configurations.

        Returns:
            Dict mapping strategy ID to config
        """
        # Search directories: strategies/ and recommends/
        search_dirs = [self._strategies_dir]
        recommends_dir = self._strategies_dir.parent / "recommends"
        if recommends_dir.exists():
            search_dirs.append(recommends_dir)

        for search_dir in search_dirs:
            if not search_dir.exists():
                logger.warning(f"Strategies directory not found: {search_dir}")
                continue

            for yaml_file in search_dir.glob("*.yaml"):
                try:
                    strategy = self.load_file(yaml_file)
                    if strategy:
                        self._strategies[strategy.id] = strategy
                        logger.info(f"Loaded strategy: {strategy.metadata.name}")
                except Exception as e:
                    logger.error(f"Failed to load strategy {yaml_file}: {e}")

        return self._strategies

    def load_file(self, path: Path) -> Optional[StrategyConfig]:
        """Load a single strategy file.

        Args:
            path: Path to YAML file

        Returns:
            StrategyConfig or None if loading fails
        """
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data:
            return None

        strategy_id = path.stem  # Filename without extension

        return self._parse_config(strategy_id, data)

    def load_by_id(self, strategy_id: str) -> Optional[StrategyConfig]:
        """Load a strategy by ID.

        Args:
            strategy_id: Strategy identifier (filename without extension)

        Returns:
            StrategyConfig or None if not found
        """
        if strategy_id in self._strategies:
            return self._strategies[strategy_id]

        # Search in strategies/ and recommends/
        search_dirs = [
            self._strategies_dir,
            self._strategies_dir.parent / "recommends",
        ]
        for search_dir in search_dirs:
            path = search_dir / f"{strategy_id}.yaml"
            if path.exists():
                return self.load_file(path)

        logger.warning(f"Strategy file not found: {strategy_id}")
        return None

    def _parse_config(self, strategy_id: str, data: dict) -> StrategyConfig:
        """Parse YAML data into StrategyConfig."""
        # Parse metadata
        meta_data = data.get("metadata", {})
        metadata = StrategyMetadata(
            name=meta_data.get("name", strategy_id),
            description=meta_data.get("description", ""),
            risk_level=meta_data.get("risk_level", "medium"),
            enabled=meta_data.get("enabled", True),
        )

        # Parse factor weights
        weights_data = data.get("factor_weights", {})
        factor_weights = FactorWeights(
            market_sentiment=weights_data.get("market_sentiment", 0.40),
            game_context=weights_data.get("game_context", 0.35),
            team_strength=weights_data.get("team_strength", 0.25),
        )

        # Parse entry rules
        entry_data = data.get("entry_rules", {})
        entry_conditions = []
        for cond in entry_data.get("conditions", []):
            entry_conditions.append(
                RuleCondition(
                    name=cond.get("name", ""),
                    type=cond.get("type", "threshold"),
                    field=cond.get("field", ""),
                    operator=cond.get("operator", ">="),
                    value=cond.get("value"),
                    compare_field=cond.get("compare_field"),
                )
            )
        entry_rules = EntryRules(conditions=entry_conditions)

        # Parse exit rules
        exit_data = data.get("exit_rules", {})
        profit_targets = []
        for target in exit_data.get("profit_targets", []):
            profit_targets.append(
                ProfitTarget(
                    time_remaining_min=target.get("time_remaining_min", 0),
                    target_percentage=target.get("target_percentage", 10.0),
                )
            )
        # Parse late-game stop loss widening buckets
        stop_loss_data = exit_data.get("stop_loss", {})
        late_game_widening = []
        for bucket in stop_loss_data.get("late_game_widening", []):
            late_game_widening.append(
                StopLossWideningBucket(
                    time_remaining_max=bucket.get("time_remaining_max", 0),
                    multiplier=bucket.get("multiplier", 1.0),
                )
            )
        # Sort descending by time so first match = widest applicable bucket
        late_game_widening.sort(key=lambda b: b.time_remaining_max, reverse=True)

        exit_rules = ExitRules(
            profit_targets=profit_targets,
            stop_loss_percent=stop_loss_data.get("value", 10.0),
            time_stop_seconds=exit_data.get("time_stop", {}).get("exit_before_seconds", 60),
            late_game_widening=late_game_widening,
            exit_max_spread_percent=stop_loss_data.get("exit_max_spread_percent", 0.0),
            patience_before_seconds=int(stop_loss_data.get("patience_before_seconds", 0)),
            max_averagedown_count=int(stop_loss_data.get("max_averagedown_count", 0)),
            max_averagedown_multiplier=float(stop_loss_data.get("max_averagedown_multiplier", 3.0)),
        )

        # Parse position sizing
        sizing_data = data.get("position_sizing", {})
        position_sizing = PositionSizing(
            method=sizing_data.get("method", "kelly_fraction"),
            kelly_multiplier=sizing_data.get("kelly_multiplier", 0.25),
            max_position_usdc=sizing_data.get("max_position_usdc", 100.0),
            min_position_usdc=sizing_data.get("min_position_usdc", 10.0),
            fixed_size_usdc=sizing_data.get("fixed_size_usdc", 50.0),
            percentage_of_bankroll=sizing_data.get("percentage_of_bankroll", 0.05),
            late_game_seconds=sizing_data.get("late_game_seconds", 720),
            late_game_multiplier=sizing_data.get("late_game_multiplier", 1.0),
        )

        # Parse risk limits
        risk_data = data.get("risk_limits", {})
        risk_limits = StrategyRiskLimits(
            max_concurrent_positions=risk_data.get("max_concurrent_positions", 5),
            max_daily_loss_usdc=risk_data.get("max_daily_loss_usdc", 200.0),
            max_position_per_game=risk_data.get("max_position_per_game", 1),
            cooldown_iterations=risk_data.get("cooldown_iterations", 0),
            max_stop_losses_per_game=risk_data.get("max_stop_losses_per_game", 0),
            max_loss_per_game_usdc=risk_data.get("max_loss_per_game_usdc", 0.0),
            profit_cooldown_iterations=int(risk_data.get("profit_cooldown_iterations", 0)),
        )

        return StrategyConfig(
            id=strategy_id,
            metadata=metadata,
            factor_weights=factor_weights,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            position_sizing=position_sizing,
            risk_limits=risk_limits,
        )

    def get_enabled_strategies(self) -> list[StrategyConfig]:
        """Get all enabled strategies."""
        if not self._strategies:
            self.load_all()
        return [s for s in self._strategies.values() if s.metadata.enabled]

    def get_by_risk_level(self, risk_level: str) -> list[StrategyConfig]:
        """Get strategies by risk level."""
        if not self._strategies:
            self.load_all()
        return [
            s for s in self._strategies.values()
            if s.metadata.risk_level == risk_level and s.metadata.enabled
        ]
