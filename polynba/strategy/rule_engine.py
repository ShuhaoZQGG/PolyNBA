"""Rule engine for evaluating entry and exit conditions."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from ..analysis.edge_detector import EdgeOpportunity
from ..data.models import GameState
from ..trading.position_tracker import Position
from .loader import ExitRules, RuleCondition, StrategyConfig

logger = logging.getLogger(__name__)


@dataclass
class RuleContext:
    """Context for rule evaluation."""

    game_state: GameState
    opportunity: EdgeOpportunity
    current_position: Optional[Position] = None
    current_price: Optional[Decimal] = None

    @property
    def edge_percentage(self) -> float:
        """Get edge percentage."""
        return self.opportunity.edge_percentage

    @property
    def confidence(self) -> int:
        """Get confidence level."""
        return self.opportunity.confidence

    @property
    def market_price(self) -> float:
        """Get market price."""
        return float(self.opportunity.market_price)

    @property
    def total_seconds_remaining(self) -> int:
        """Get total seconds remaining."""
        return self.game_state.total_seconds_remaining

    @property
    def mispricing_magnitude(self) -> float:
        """Get mispricing magnitude from estimate."""
        return self.opportunity.estimate.factor_scores.market_sentiment.mispricing_magnitude

    @property
    def score_differential_abs(self) -> int:
        """Get absolute score differential."""
        return abs(self.game_state.score_differential)

    @property
    def estimated_probability(self) -> float:
        """Get estimated probability for this side."""
        return float(self.opportunity.estimated_probability)

    @property
    def spread_percentage(self) -> float:
        """Get bid-ask spread as percentage of mid price (0 if unavailable)."""
        if self.opportunity.spread_percentage is not None:
            return self.opportunity.spread_percentage
        return 0.0

    @property
    def risk_flags(self) -> list[str]:
        """Get risk flags if available."""
        # This would come from Claude analysis if available
        return []


class Rule(ABC):
    """Abstract base class for rules."""

    def __init__(self, condition: RuleCondition):
        """Initialize rule.

        Args:
            condition: Rule condition configuration
        """
        self.condition = condition
        self.name = condition.name

    @abstractmethod
    def evaluate(self, context: RuleContext) -> bool:
        """Evaluate the rule against context.

        Args:
            context: Rule evaluation context

        Returns:
            True if rule passes, False otherwise
        """
        pass


class ThresholdRule(Rule):
    """Rule that compares a field to a threshold value."""

    OPERATORS = {
        ">=": lambda a, b: a >= b,
        ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }

    def evaluate(self, context: RuleContext) -> bool:
        """Evaluate threshold rule."""
        field_value = self._get_field_value(context)
        if field_value is None:
            logger.debug(f"Rule {self.name}: field '{self.condition.field}' not found")
            return False

        operator_fn = self.OPERATORS.get(self.condition.operator)
        if operator_fn is None:
            logger.error(f"Unknown operator: {self.condition.operator}")
            return False

        result = operator_fn(field_value, self.condition.value)
        logger.debug(
            f"Rule {self.name}: {field_value} {self.condition.operator} "
            f"{self.condition.value} = {result}"
        )
        return result

    def _get_field_value(self, context: RuleContext) -> Any:
        """Get field value from context."""
        field = self.condition.field

        # Try context attributes first
        if hasattr(context, field):
            return getattr(context, field)

        # Try nested access with dots
        if "." in field:
            parts = field.split(".")
            value = context
            for part in parts:
                if hasattr(value, part):
                    value = getattr(value, part)
                else:
                    return None
            return value

        return None


class ListEmptyRule(Rule):
    """Rule that checks if a list field is empty."""

    def evaluate(self, context: RuleContext) -> bool:
        """Evaluate list empty rule."""
        field_value = self._get_field_value(context)

        if field_value is None:
            # Treat None as empty
            return True

        if not isinstance(field_value, (list, tuple)):
            logger.debug(f"Rule {self.name}: field is not a list")
            return False

        result = len(field_value) == 0
        logger.debug(f"Rule {self.name}: list empty = {result}")
        return result

    def _get_field_value(self, context: RuleContext) -> Any:
        """Get field value from context."""
        field = self.condition.field
        if hasattr(context, field):
            return getattr(context, field)
        return None


class ComparisonRule(Rule):
    """Rule that compares two fields."""

    OPERATORS = {
        ">=": lambda a, b: a >= b,
        ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }

    def evaluate(self, context: RuleContext) -> bool:
        """Evaluate comparison rule."""
        field_value = self._get_field_value(context, self.condition.field)
        compare_value = self._get_field_value(
            context, self.condition.compare_field or ""
        )

        if field_value is None or compare_value is None:
            return False

        operator_fn = self.OPERATORS.get(self.condition.operator)
        if operator_fn is None:
            return False

        result = operator_fn(field_value, compare_value)
        logger.debug(
            f"Rule {self.name}: {field_value} {self.condition.operator} "
            f"{compare_value} = {result}"
        )
        return result

    def _get_field_value(self, context: RuleContext, field: str) -> Any:
        """Get field value from context."""
        if hasattr(context, field):
            return getattr(context, field)
        return None


class RuleFactory:
    """Factory for creating rules from conditions."""

    @staticmethod
    def create(condition: RuleCondition) -> Rule:
        """Create a rule from a condition.

        Args:
            condition: Rule condition configuration

        Returns:
            Rule instance
        """
        rule_types = {
            "threshold": ThresholdRule,
            "list_empty": ListEmptyRule,
            "comparison": ComparisonRule,
        }

        rule_class = rule_types.get(condition.type, ThresholdRule)
        return rule_class(condition)


@dataclass
class RuleEvaluationResult:
    """Result of rule evaluation."""

    passed: bool
    passed_rules: list[str]
    failed_rules: list[str]
    details: dict[str, bool]


class RuleEngine:
    """Evaluates entry and exit rules for strategies."""

    def __init__(self):
        """Initialize rule engine."""
        self._rule_cache: dict[str, list[Rule]] = {}

    def evaluate_entry(
        self,
        strategy: StrategyConfig,
        context: RuleContext,
    ) -> RuleEvaluationResult:
        """Evaluate entry rules for a strategy.

        All entry conditions must pass (AND logic).

        Args:
            strategy: Strategy configuration
            context: Rule evaluation context

        Returns:
            RuleEvaluationResult
        """
        rules = self._get_rules(strategy.id, strategy.entry_rules.conditions)

        passed_rules = []
        failed_rules = []
        details = {}

        for rule in rules:
            try:
                result = rule.evaluate(context)
                details[rule.name] = result

                if result:
                    passed_rules.append(rule.name)
                else:
                    failed_rules.append(rule.name)
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.name}: {e}")
                failed_rules.append(rule.name)
                details[rule.name] = False

        all_passed = len(failed_rules) == 0

        return RuleEvaluationResult(
            passed=all_passed,
            passed_rules=passed_rules,
            failed_rules=failed_rules,
            details=details,
        )

    def evaluate_exit(
        self,
        strategy: StrategyConfig,
        position: Position,
        current_price: Decimal,
        time_remaining_seconds: int,
        *,
        stop_loss_pct_override: Optional[float] = None,
        time_stop_seconds_override: Optional[int] = None,
        profit_target_percent_override: Optional[float] = None,
        spread_pct: float = 0.0,
    ) -> tuple[bool, str, Optional[Decimal]]:
        """Evaluate exit conditions for a position.

        Args:
            strategy: Strategy configuration
            position: Current position
            current_price: Current market price
            time_remaining_seconds: Seconds remaining in game
            stop_loss_pct_override: If set, use instead of strategy exit_rules.stop_loss_percent
            time_stop_seconds_override: If set, use instead of strategy exit_rules.time_stop_seconds

        Returns:
            Tuple of (should_exit, reason, limit_price) where limit_price is the
            target sell price for the exit order (None for urgent exits like time stop).
        """
        exit_rules = strategy.exit_rules
        stop_loss_pct = (
            stop_loss_pct_override
            if stop_loss_pct_override is not None
            else exit_rules.stop_loss_percent
        )
        time_stop_seconds = (
            time_stop_seconds_override
            if time_stop_seconds_override is not None
            else exit_rules.time_stop_seconds
        )

        # Calculate P&L
        pnl_percent = position.unrealized_pnl_percent(current_price)
        token_short = position.token_id[:16] + "..." if len(position.token_id) > 16 else position.token_id

        logger.info(
            f"  [Exit eval] {strategy.id} | token {token_short} | "
            f"entry={float(position.avg_entry_price):.2f} now={float(current_price):.2f} | "
            f"PnL={pnl_percent:+.1f}% | time_left={time_remaining_seconds}s"
        )

        # Global profit target override (take profit at X%)
        if profit_target_percent_override is not None:
            if pnl_percent >= profit_target_percent_override:
                limit_price = position.avg_entry_price * (1 + Decimal(str(profit_target_percent_override)) / 100)
                logger.info(
                    f"    -> Profit target (override): PnL {pnl_percent:.1f}% >= "
                    f"{profit_target_percent_override:.1f}% -> SELL (limit={float(limit_price):.4f})"
                )
                return True, f"Profit target hit ({pnl_percent:.1f}%)", limit_price
            logger.info(
                f"    -> Profit target (override): PnL {pnl_percent:.1f}% < "
                f"{profit_target_percent_override:.1f}% -> no"
            )

        # Spread guard: suppress stop loss evaluation when spread is abnormally wide
        spread_guard_active = False
        max_spread = exit_rules.exit_max_spread_percent
        if max_spread > 0 and spread_pct > max_spread:
            spread_guard_active = True
            logger.warning(
                f"    -> Spread guard: spread {spread_pct:.1f}% > threshold {max_spread:.1f}% — "
                f"suppressing stop loss evaluation (prices unreliable)"
            )

        if not spread_guard_active:
            # Dynamic stop loss: widen for low-price positions where normal volatility exceeds %
            entry_price = float(position.avg_entry_price)
            effective_stop_loss = stop_loss_pct
            if entry_price < 0.35:
                # Scale: multiplier from 1.0 (at 0.35) to 2.0 (at 0.0)
                multiplier = min(2.0, max(1.0, 2.0 - (entry_price / 0.35)))
                effective_stop_loss = stop_loss_pct * multiplier

            # Time-based widening for late-game volatility (stacks with price-based)
            for bucket in exit_rules.late_game_widening:
                if time_remaining_seconds <= bucket.time_remaining_max:
                    effective_stop_loss *= bucket.multiplier
                    break  # First matching bucket wins (sorted descending by time)

            stop_threshold = -effective_stop_loss
            if pnl_percent <= stop_threshold:
                limit_price = position.avg_entry_price * (1 - Decimal(str(effective_stop_loss)) / 100)
                logger.info(
                    f"    -> Stop loss: PnL {pnl_percent:.1f}% <= {stop_threshold:.1f}% "
                    f"(base={stop_loss_pct:.0f}%, effective={effective_stop_loss:.1f}%, entry@{entry_price:.2f}) -> SELL (limit={float(limit_price):.4f})"
                )
                return True, f"Stop loss triggered ({pnl_percent:.1f}%, threshold {stop_threshold:.1f}%)", limit_price
            logger.info(
                f"    -> Stop loss: PnL {pnl_percent:.1f}% > {stop_threshold:.1f}% "
                f"(base={stop_loss_pct:.0f}%, effective={effective_stop_loss:.1f}%, entry@{entry_price:.2f}) -> no"
            )

        # Check profit targets (time-based)
        matched_target = None
        for target in exit_rules.profit_targets:
            if time_remaining_seconds >= target.time_remaining_min:
                matched_target = target
                break
        if matched_target is not None:
            if pnl_percent >= matched_target.target_percentage:
                limit_price = position.avg_entry_price * (1 + Decimal(str(matched_target.target_percentage)) / 100)
                logger.info(
                    f"    -> Profit target: PnL {pnl_percent:.1f}% >= {matched_target.target_percentage:.1f}% "
                    f"(bucket time_left>={matched_target.time_remaining_min}s) -> SELL (limit={float(limit_price):.4f})"
                )
                return True, f"Profit target hit ({pnl_percent:.1f}%)", limit_price
            logger.info(
                f"    -> Profit target: PnL {pnl_percent:.1f}% < {matched_target.target_percentage:.1f}% "
                f"(bucket time_left>={matched_target.time_remaining_min}s) -> no"
            )
        else:
            logger.info(
                f"    -> Profit target: no time bucket (time_left={time_remaining_seconds}s) -> no"
            )

        # Check time stop
        if time_remaining_seconds <= time_stop_seconds:
            logger.info(
                f"    -> Time stop: time_left {time_remaining_seconds}s <= {time_stop_seconds}s -> SELL"
            )
            return True, "Time stop triggered", None
        logger.info(
            f"    -> Time stop: time_left {time_remaining_seconds}s > {time_stop_seconds}s -> no"
        )

        logger.info(f"    -> HOLD (no exit condition met)")
        return False, "", None

    def calculate_position_size(
        self,
        strategy: StrategyConfig,
        opportunity: EdgeOpportunity,
        bankroll: Decimal,
        *,
        kelly_multiplier_override: Optional[float] = None,
        time_remaining_seconds: Optional[int] = None,
    ) -> Decimal:
        """Calculate position size based on strategy rules.

        Args:
            strategy: Strategy configuration
            opportunity: Edge opportunity
            bankroll: Available bankroll
            kelly_multiplier_override: If set, scale strategy kelly_multiplier by this (e.g. 0.5 = half)
            time_remaining_seconds: Seconds remaining in game (for late-game scaling)

        Returns:
            Position size in USDC
        """
        sizing = strategy.position_sizing

        if sizing.method == "kelly_fraction":
            # Kelly criterion
            kelly = opportunity.kelly_fraction
            mult = sizing.kelly_multiplier
            if kelly_multiplier_override is not None:
                mult = mult * kelly_multiplier_override
            size = float(bankroll) * kelly * mult
        elif sizing.method == "fixed":
            size = sizing.fixed_size_usdc
        elif sizing.method == "percentage":
            size = float(bankroll) * sizing.percentage_of_bankroll
        else:
            size = sizing.min_position_usdc

        # Late-game position size scaling
        if (
            time_remaining_seconds is not None
            and sizing.late_game_multiplier < 1.0
            and time_remaining_seconds <= sizing.late_game_seconds
        ):
            size *= sizing.late_game_multiplier
            logger.info(
                f"    Late-game sizing: {time_remaining_seconds}s remaining "
                f"(<= {sizing.late_game_seconds}s), size scaled by {sizing.late_game_multiplier:.1%}"
            )

        # Apply limits
        size = max(sizing.min_position_usdc, size)
        size = min(sizing.max_position_usdc, size)
        size = min(float(bankroll), size)

        return Decimal(str(round(size, 2)))

    def _get_rules(
        self, strategy_id: str, conditions: list[RuleCondition]
    ) -> list[Rule]:
        """Get or create rules for a strategy."""
        cache_key = strategy_id

        if cache_key not in self._rule_cache:
            self._rule_cache[cache_key] = [
                RuleFactory.create(cond) for cond in conditions
            ]

        return self._rule_cache[cache_key]

    def clear_cache(self) -> None:
        """Clear rule cache."""
        self._rule_cache.clear()
