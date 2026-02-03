"""Strategy layer for trading rule management."""

from .loader import (
    EntryRules,
    ExitRules,
    FactorWeights,
    PositionSizing,
    ProfitTarget,
    RuleCondition,
    StrategyConfig,
    StrategyLoader,
    StrategyMetadata,
    StrategyRiskLimits,
)
from .rule_engine import (
    Rule,
    RuleContext,
    RuleEngine,
    RuleEvaluationResult,
    RuleFactory,
)
from .strategy_manager import (
    CapitalAllocation,
    ExitSignal,
    StrategyManager,
    TradingSignal,
)

__all__ = [
    # Loader
    "StrategyLoader",
    "StrategyConfig",
    "StrategyMetadata",
    "FactorWeights",
    "RuleCondition",
    "EntryRules",
    "ExitRules",
    "ProfitTarget",
    "PositionSizing",
    "StrategyRiskLimits",
    # Rule Engine
    "Rule",
    "RuleContext",
    "RuleEngine",
    "RuleEvaluationResult",
    "RuleFactory",
    # Strategy Manager
    "StrategyManager",
    "TradingSignal",
    "ExitSignal",
    "CapitalAllocation",
]
