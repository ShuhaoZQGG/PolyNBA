"""Tests for strategy rule engine."""

import pytest
from decimal import Decimal

from polynba.analysis.edge_detector import EdgeOpportunity
from polynba.analysis.probability_calculator import (
    ProbabilityEstimate,
    FactorScores,
)
from polynba.analysis.factors import (
    MarketSentimentOutput,
    GameContextOutput,
    TeamStrengthOutput,
    MomentumAnalysis,
    ClutchAnalysis,
    EfficiencyComparison,
    StrengthTierComparison,
)
from polynba.data.models import (
    GameState,
    GameStatus,
    Period,
    TeamGameState,
)
from polynba.strategy.loader import (
    StrategyConfig,
    StrategyMetadata,
    FactorWeights,
    EntryRules,
    ExitRules,
    PositionSizing,
    StrategyRiskLimits,
    RuleCondition,
    ProfitTarget,
)
from polynba.strategy.rule_engine import (
    RuleEngine,
    RuleContext,
    RuleFactory,
    ThresholdRule,
    ListEmptyRule,
)
from polynba.trading.position_tracker import Position
from polynba.data.models import TradeSide


@pytest.fixture
def sample_game_state():
    """Create sample game state."""
    return GameState(
        game_id="test123",
        status=GameStatus.IN_PROGRESS,
        period=Period.THIRD_QUARTER,
        clock="8:30",
        home_team=TeamGameState(
            team_id="home1",
            team_name="Home Team",
            team_abbreviation="HOM",
            score=72,
            timeouts_remaining=4,
        ),
        away_team=TeamGameState(
            team_id="away1",
            team_name="Away Team",
            team_abbreviation="AWY",
            score=65,
            timeouts_remaining=3,
        ),
    )


@pytest.fixture
def sample_factor_scores():
    """Create sample factor scores."""
    return FactorScores(
        market_sentiment=MarketSentimentOutput(
            score=30,
            home_implied_prob=0.55,
            away_implied_prob=0.45,
            fair_home_prob=0.65,
            fair_away_prob=0.35,
            mispricing_magnitude=10.0,
            reasoning="Test reasoning",
        ),
        game_context=GameContextOutput(
            score=20,
            momentum=MomentumAnalysis(
                recent_scoring_diff=5,
                scoring_run=5,
                momentum_team=None,
                momentum_strength=30,
            ),
            clutch=ClutchAnalysis(
                is_clutch=False,
                pressure_level=0,
                clutch_description="Not clutch",
            ),
            home_timeouts=4,
            away_timeouts=3,
            timeout_advantage=1,
            foul_situation="Neutral",
            reasoning="Test reasoning",
        ),
        team_strength=TeamStrengthOutput(
            score=25,
            efficiency=EfficiencyComparison(
                home_net_rating=5.5,
                away_net_rating=1.2,
                net_rating_diff=4.3,
                home_pace=100,
                away_pace=98,
                expected_pace=99,
            ),
            tiers=StrengthTierComparison(
                home_tier="contender",
                away_tier="average",
                tier_advantage="home",
                mismatch_level=1,
            ),
            home_advantages=["Better net rating"],
            away_advantages=[],
            injury_impact=0,
            reasoning="Test reasoning",
        ),
    )


@pytest.fixture
def sample_probability_estimate(sample_factor_scores):
    """Create sample probability estimate."""
    return ProbabilityEstimate(
        market_price=Decimal("0.55"),
        estimated_probability=Decimal("0.65"),
        edge=Decimal("0.10"),
        edge_percentage=10.0,
        combined_score=25,
        factor_scores=sample_factor_scores,
        confidence=7,
        reasoning="Test reasoning",
    )


@pytest.fixture
def sample_opportunity(sample_game_state, sample_probability_estimate):
    """Create sample edge opportunity."""
    return EdgeOpportunity(
        game_id=sample_game_state.game_id,
        market_id="market1",
        token_id="token1",
        side="home",
        team_name="Home Team",
        team_abbreviation="HOM",
        market_price=Decimal("0.55"),
        estimated_probability=Decimal("0.65"),
        edge=Decimal("0.10"),
        edge_percentage=10.0,
        confidence=7,
        estimate=sample_probability_estimate,
    )


@pytest.fixture
def sample_strategy():
    """Create sample strategy config."""
    return StrategyConfig(
        id="test_strategy",
        metadata=StrategyMetadata(
            name="Test Strategy",
            risk_level="medium",
            enabled=True,
        ),
        factor_weights=FactorWeights(
            market_sentiment=0.4,
            game_context=0.35,
            team_strength=0.25,
        ),
        entry_rules=EntryRules(
            conditions=[
                RuleCondition(
                    name="minimum_edge",
                    type="threshold",
                    field="edge_percentage",
                    operator=">=",
                    value=5.0,
                ),
                RuleCondition(
                    name="minimum_confidence",
                    type="threshold",
                    field="confidence",
                    operator=">=",
                    value=5,
                ),
                RuleCondition(
                    name="time_remaining",
                    type="threshold",
                    field="total_seconds_remaining",
                    operator=">=",
                    value=300,
                ),
            ]
        ),
        exit_rules=ExitRules(
            profit_targets=[
                ProfitTarget(time_remaining_min=720, target_percentage=15.0),
                ProfitTarget(time_remaining_min=0, target_percentage=5.0),
            ],
            stop_loss_percent=10.0,
            time_stop_seconds=60,
        ),
        position_sizing=PositionSizing(
            method="kelly_fraction",
            kelly_multiplier=0.25,
            max_position_usdc=100.0,
            min_position_usdc=10.0,
        ),
        risk_limits=StrategyRiskLimits(
            max_concurrent_positions=5,
            max_daily_loss_usdc=200.0,
            max_position_per_game=1,
        ),
    )


class TestRuleFactory:
    """Tests for rule factory."""

    def test_create_threshold_rule(self):
        """Test creating threshold rule."""
        condition = RuleCondition(
            name="test",
            type="threshold",
            field="edge_percentage",
            operator=">=",
            value=5.0,
        )

        rule = RuleFactory.create(condition)
        assert isinstance(rule, ThresholdRule)

    def test_create_list_empty_rule(self):
        """Test creating list empty rule."""
        condition = RuleCondition(
            name="test",
            type="list_empty",
            field="risk_flags",
        )

        rule = RuleFactory.create(condition)
        assert isinstance(rule, ListEmptyRule)


class TestThresholdRule:
    """Tests for threshold rules."""

    def test_gte_operator(self, sample_game_state, sample_opportunity):
        """Test >= operator."""
        condition = RuleCondition(
            name="edge_check",
            type="threshold",
            field="edge_percentage",
            operator=">=",
            value=5.0,
        )

        rule = ThresholdRule(condition)
        context = RuleContext(
            game_state=sample_game_state,
            opportunity=sample_opportunity,
        )

        # Edge is 10%, should pass >= 5%
        assert rule.evaluate(context) is True

    def test_lt_operator(self, sample_game_state, sample_opportunity):
        """Test < operator."""
        condition = RuleCondition(
            name="price_check",
            type="threshold",
            field="market_price",
            operator="<",
            value=0.60,
        )

        rule = ThresholdRule(condition)
        context = RuleContext(
            game_state=sample_game_state,
            opportunity=sample_opportunity,
        )

        # Market price is 0.55, should pass < 0.60
        assert rule.evaluate(context) is True


class TestRuleEngine:
    """Tests for rule engine."""

    def test_evaluate_entry_all_pass(
        self, sample_strategy, sample_game_state, sample_opportunity
    ):
        """Test entry evaluation when all rules pass."""
        engine = RuleEngine()

        context = RuleContext(
            game_state=sample_game_state,
            opportunity=sample_opportunity,
        )

        result = engine.evaluate_entry(sample_strategy, context)

        assert result.passed is True
        assert len(result.failed_rules) == 0

    def test_evaluate_entry_with_failure(
        self, sample_strategy, sample_game_state, sample_opportunity
    ):
        """Test entry evaluation with rule failure."""
        # Modify opportunity to fail edge check
        sample_opportunity.edge_percentage = 3.0

        engine = RuleEngine()

        context = RuleContext(
            game_state=sample_game_state,
            opportunity=sample_opportunity,
        )

        result = engine.evaluate_entry(sample_strategy, context)

        assert result.passed is False
        assert "minimum_edge" in result.failed_rules

    def test_evaluate_exit_stop_loss(self, sample_strategy):
        """Test exit evaluation for stop loss."""
        engine = RuleEngine()

        position = Position(
            market_id="market1",
            token_id="token1",
            side=TradeSide.BUY,
            size=Decimal("10"),
            avg_entry_price=Decimal("0.60"),
            total_cost=Decimal("6"),
        )

        # Price dropped 15% - should trigger stop loss at 10%
        current_price = Decimal("0.51")  # ~15% loss

        should_exit, reason, limit_price = engine.evaluate_exit(
            sample_strategy,
            position,
            current_price,
            time_remaining_seconds=600,
        )

        assert should_exit is True
        assert "stop loss" in reason.lower()
        # limit_price = entry * (1 - effective_stop_loss/100) = 0.60 * (1 - 10/100) = 0.54
        assert limit_price == Decimal("0.60") * (1 - Decimal("10") / 100)

    def test_evaluate_exit_profit_target(self, sample_strategy):
        """Test exit evaluation for profit target."""
        engine = RuleEngine()

        position = Position(
            market_id="market1",
            token_id="token1",
            side=TradeSide.BUY,
            size=Decimal("10"),
            avg_entry_price=Decimal("0.50"),
            total_cost=Decimal("5"),
        )

        # Price increased 20% - should trigger 15% profit target
        current_price = Decimal("0.60")  # 20% profit

        should_exit, reason, limit_price = engine.evaluate_exit(
            sample_strategy,
            position,
            current_price,
            time_remaining_seconds=900,  # > 720 seconds
        )

        assert should_exit is True
        assert "profit target" in reason.lower()
        # limit_price = entry * (1 + target/100) = 0.50 * (1 + 15/100) = 0.575
        assert limit_price == Decimal("0.50") * (1 + Decimal("15") / 100)

    def test_evaluate_exit_time_stop_limit_price_is_none(self, sample_strategy):
        """Test that time stop exit returns None for limit_price (urgent exit)."""
        engine = RuleEngine()

        position = Position(
            market_id="market1",
            token_id="token1",
            side=TradeSide.BUY,
            size=Decimal("10"),
            avg_entry_price=Decimal("0.50"),
            total_cost=Decimal("5"),
        )

        # Price near entry (no profit target or stop loss triggered)
        current_price = Decimal("0.51")

        should_exit, reason, limit_price = engine.evaluate_exit(
            sample_strategy,
            position,
            current_price,
            time_remaining_seconds=30,  # < 60s time stop
        )

        assert should_exit is True
        assert "time stop" in reason.lower()
        assert limit_price is None

    def test_evaluate_entry_spread_gate_passes(
        self, sample_game_state, sample_opportunity
    ):
        """Test entry passes when spread is within threshold."""
        # Create strategy with max_spread rule
        strategy = StrategyConfig(
            id="spread_test",
            metadata=StrategyMetadata(name="Spread Test", enabled=True),
            factor_weights=FactorWeights(),
            entry_rules=EntryRules(
                conditions=[
                    RuleCondition(
                        name="minimum_edge",
                        type="threshold",
                        field="edge_percentage",
                        operator=">=",
                        value=5.0,
                    ),
                    RuleCondition(
                        name="max_spread",
                        type="threshold",
                        field="spread_percentage",
                        operator="<=",
                        value=8.0,
                    ),
                ]
            ),
            exit_rules=ExitRules(),
            position_sizing=PositionSizing(),
            risk_limits=StrategyRiskLimits(),
        )

        # Set spread below threshold
        sample_opportunity.spread_percentage = 5.0

        engine = RuleEngine()
        context = RuleContext(
            game_state=sample_game_state,
            opportunity=sample_opportunity,
        )

        result = engine.evaluate_entry(strategy, context)
        assert result.passed is True

    def test_evaluate_entry_spread_gate_blocks(
        self, sample_game_state, sample_opportunity
    ):
        """Test entry blocked when spread exceeds threshold."""
        strategy = StrategyConfig(
            id="spread_test",
            metadata=StrategyMetadata(name="Spread Test", enabled=True),
            factor_weights=FactorWeights(),
            entry_rules=EntryRules(
                conditions=[
                    RuleCondition(
                        name="minimum_edge",
                        type="threshold",
                        field="edge_percentage",
                        operator=">=",
                        value=5.0,
                    ),
                    RuleCondition(
                        name="max_spread",
                        type="threshold",
                        field="spread_percentage",
                        operator="<=",
                        value=4.0,
                    ),
                ]
            ),
            exit_rules=ExitRules(),
            position_sizing=PositionSizing(),
            risk_limits=StrategyRiskLimits(),
        )

        # Set spread above threshold
        sample_opportunity.spread_percentage = 7.5

        engine = RuleEngine()
        context = RuleContext(
            game_state=sample_game_state,
            opportunity=sample_opportunity,
        )

        result = engine.evaluate_entry(strategy, context)
        assert result.passed is False
        assert "max_spread" in result.failed_rules

    def test_spread_percentage_defaults_to_zero(
        self, sample_game_state, sample_opportunity
    ):
        """Test that spread_percentage returns 0 when not set on opportunity."""
        # Don't set spread_percentage on the opportunity (defaults to None)
        sample_opportunity.spread_percentage = None

        context = RuleContext(
            game_state=sample_game_state,
            opportunity=sample_opportunity,
        )

        assert context.spread_percentage == 0.0

    def test_calculate_position_size_kelly(
        self, sample_strategy, sample_opportunity
    ):
        """Test Kelly position sizing."""
        engine = RuleEngine()
        bankroll = Decimal("1000")

        size = engine.calculate_position_size(
            sample_strategy,
            sample_opportunity,
            bankroll,
        )

        # Should be within limits
        assert size >= Decimal("10")  # min_position
        assert size <= Decimal("100")  # max_position

    def test_spread_guard_suppresses_stop_loss(self, sample_strategy):
        """Test that stop loss is suppressed when spread exceeds threshold."""
        # Configure spread guard
        sample_strategy.exit_rules.exit_max_spread_percent = 15.0

        engine = RuleEngine()
        position = Position(
            market_id="market1",
            token_id="token1",
            side=TradeSide.BUY,
            size=Decimal("10"),
            avg_entry_price=Decimal("0.60"),
            total_cost=Decimal("6"),
        )

        # Price dropped 15% — would normally trigger 10% stop loss
        current_price = Decimal("0.51")

        should_exit, reason, limit_price = engine.evaluate_exit(
            sample_strategy,
            position,
            current_price,
            time_remaining_seconds=600,
            spread_pct=20.0,  # Spread 20% > threshold 15%
        )

        # Stop loss should be suppressed
        assert should_exit is False

    def test_spread_guard_allows_profit_target(self, sample_strategy):
        """Test that profit target still fires despite wide spread."""
        sample_strategy.exit_rules.exit_max_spread_percent = 15.0

        engine = RuleEngine()
        position = Position(
            market_id="market1",
            token_id="token1",
            side=TradeSide.BUY,
            size=Decimal("10"),
            avg_entry_price=Decimal("0.50"),
            total_cost=Decimal("5"),
        )

        # Price increased 20% — should trigger 15% profit target
        current_price = Decimal("0.60")

        should_exit, reason, limit_price = engine.evaluate_exit(
            sample_strategy,
            position,
            current_price,
            time_remaining_seconds=900,
            spread_pct=20.0,  # Wide spread — but profit targets are not affected
        )

        assert should_exit is True
        assert "profit target" in reason.lower()

    def test_spread_guard_allows_time_stop(self, sample_strategy):
        """Test that time stop still fires despite wide spread."""
        sample_strategy.exit_rules.exit_max_spread_percent = 15.0

        engine = RuleEngine()
        position = Position(
            market_id="market1",
            token_id="token1",
            side=TradeSide.BUY,
            size=Decimal("10"),
            avg_entry_price=Decimal("0.50"),
            total_cost=Decimal("5"),
        )

        current_price = Decimal("0.51")

        should_exit, reason, limit_price = engine.evaluate_exit(
            sample_strategy,
            position,
            current_price,
            time_remaining_seconds=30,  # Below time stop
            spread_pct=20.0,  # Wide spread — time stop not affected
        )

        assert should_exit is True
        assert "time stop" in reason.lower()

    def test_spread_guard_disabled_allows_stop_loss(self, sample_strategy):
        """Test that stop loss fires normally when spread guard is disabled (threshold=0)."""
        sample_strategy.exit_rules.exit_max_spread_percent = 0.0  # Disabled

        engine = RuleEngine()
        position = Position(
            market_id="market1",
            token_id="token1",
            side=TradeSide.BUY,
            size=Decimal("10"),
            avg_entry_price=Decimal("0.60"),
            total_cost=Decimal("6"),
        )

        current_price = Decimal("0.51")

        should_exit, reason, limit_price = engine.evaluate_exit(
            sample_strategy,
            position,
            current_price,
            time_remaining_seconds=600,
            spread_pct=20.0,  # Wide spread but guard is disabled
        )

        assert should_exit is True
        assert "stop loss" in reason.lower()

    def test_spread_below_threshold_allows_stop_loss(self, sample_strategy):
        """Test that stop loss fires normally when spread is below threshold."""
        sample_strategy.exit_rules.exit_max_spread_percent = 15.0

        engine = RuleEngine()
        position = Position(
            market_id="market1",
            token_id="token1",
            side=TradeSide.BUY,
            size=Decimal("10"),
            avg_entry_price=Decimal("0.60"),
            total_cost=Decimal("6"),
        )

        current_price = Decimal("0.51")

        should_exit, reason, limit_price = engine.evaluate_exit(
            sample_strategy,
            position,
            current_price,
            time_remaining_seconds=600,
            spread_pct=10.0,  # Spread 10% < threshold 15% — guard inactive
        )

        assert should_exit is True
        assert "stop loss" in reason.lower()
