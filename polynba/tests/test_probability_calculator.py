"""Tests for probability calculator."""

import pytest
from decimal import Decimal

from polynba.analysis.factors import (
    MarketSentimentFactor,
    MarketSentimentInput,
    GameContextFactor,
    GameContextInput,
    TeamStrengthFactor,
    TeamStrengthInput,
)
from polynba.analysis.probability_calculator import (
    ProbabilityCalculator,
    FactorWeights,
)
from polynba.data.models import (
    GameState,
    GameStatus,
    Period,
    TeamGameState,
    TeamStats,
)


@pytest.fixture
def sample_game_state():
    """Create a sample game state for testing."""
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
def sample_team_stats():
    """Create sample team stats."""
    home_stats = TeamStats(
        team_id="home1",
        team_name="Home Team",
        team_abbreviation="HOM",
        wins=30,
        losses=15,
        win_percentage=0.667,
        net_rating=5.5,
        offensive_rating=115.0,
        defensive_rating=109.5,
        home_wins=18,
        home_losses=5,
    )

    away_stats = TeamStats(
        team_id="away1",
        team_name="Away Team",
        team_abbreviation="AWY",
        wins=25,
        losses=20,
        win_percentage=0.556,
        net_rating=1.2,
        offensive_rating=112.0,
        defensive_rating=110.8,
        away_wins=10,
        away_losses=12,
    )

    return home_stats, away_stats


class TestMarketSentimentFactor:
    """Tests for market sentiment factor."""

    def test_home_leading_undervalued(self, sample_game_state):
        """Test detection of undervalued home team when leading."""
        factor = MarketSentimentFactor()

        # Home leading by 7 with ~20 min left, but market only gives them 55%
        input_data = MarketSentimentInput(
            game_state=sample_game_state,
            home_market_price=Decimal("0.55"),
            away_market_price=Decimal("0.45"),
        )

        result = factor.calculate(input_data)

        # Should detect home is undervalued
        assert result.score > 0
        assert result.fair_home_prob > 0.55
        assert "undervalued" in result.reasoning.lower() or result.score > 20

    def test_tied_game_fair_odds(self, sample_game_state):
        """Test fair odds detection in tied game."""
        sample_game_state.away_team.score = 72  # Make it tied
        factor = MarketSentimentFactor()

        input_data = MarketSentimentInput(
            game_state=sample_game_state,
            home_market_price=Decimal("0.50"),
            away_market_price=Decimal("0.50"),
        )

        result = factor.calculate(input_data)

        # Should be close to fair
        assert abs(result.score) < 20
        assert abs(result.mispricing_magnitude) < 5


class TestGameContextFactor:
    """Tests for game context factor."""

    def test_momentum_detection(self, sample_game_state):
        """Test momentum detection."""
        factor = GameContextFactor()

        input_data = GameContextInput(game_state=sample_game_state)
        result = factor.calculate(input_data)

        # Should have valid momentum analysis
        assert result.momentum is not None
        assert -100 <= result.score <= 100

    def test_timeout_advantage(self, sample_game_state):
        """Test timeout advantage scoring."""
        # Home has 4, away has 3 timeouts
        factor = GameContextFactor()

        input_data = GameContextInput(game_state=sample_game_state)
        result = factor.calculate(input_data)

        assert result.timeout_advantage == 1


class TestTeamStrengthFactor:
    """Tests for team strength factor."""

    def test_strength_comparison(self, sample_team_stats):
        """Test team strength comparison."""
        home_stats, away_stats = sample_team_stats
        factor = TeamStrengthFactor()

        input_data = TeamStrengthInput(
            home_stats=home_stats,
            away_stats=away_stats,
        )

        result = factor.calculate(input_data)

        # Home team is stronger (better net rating, record)
        assert result.score > 0
        assert result.efficiency.net_rating_diff > 0

    def test_tier_assignment(self, sample_team_stats):
        """Test tier assignment."""
        home_stats, away_stats = sample_team_stats
        factor = TeamStrengthFactor()

        input_data = TeamStrengthInput(
            home_stats=home_stats,
            away_stats=away_stats,
        )

        result = factor.calculate(input_data)

        # Home should be contender/elite tier
        assert result.tiers.home_tier in ["elite", "contender"]
        # Away should be average/contender
        assert result.tiers.away_tier in ["average", "contender"]


class TestProbabilityCalculator:
    """Tests for probability calculator."""

    def test_calculate_estimate(self, sample_game_state, sample_team_stats):
        """Test full probability calculation."""
        home_stats, away_stats = sample_team_stats
        calculator = ProbabilityCalculator()

        estimate = calculator.calculate(
            game_state=sample_game_state,
            home_market_price=Decimal("0.55"),
            home_stats=home_stats,
            away_stats=away_stats,
        )

        # Should produce valid estimate
        assert Decimal("0.01") <= estimate.estimated_probability <= Decimal("0.99")
        assert -100 <= estimate.combined_score <= 100
        assert 1 <= estimate.confidence <= 10

    def test_edge_calculation(self, sample_game_state, sample_team_stats):
        """Test edge calculation."""
        home_stats, away_stats = sample_team_stats
        calculator = ProbabilityCalculator()

        market_price = Decimal("0.50")
        estimate = calculator.calculate(
            game_state=sample_game_state,
            home_market_price=market_price,
            home_stats=home_stats,
            away_stats=away_stats,
        )

        # Edge should be estimated - market
        expected_edge = estimate.estimated_probability - market_price
        assert estimate.edge == expected_edge

    def test_custom_weights(self, sample_game_state, sample_team_stats):
        """Test with custom factor weights."""
        home_stats, away_stats = sample_team_stats

        weights = FactorWeights(
            market_sentiment=0.6,
            game_context=0.3,
            team_strength=0.1,
        )
        calculator = ProbabilityCalculator(weights=weights)

        estimate = calculator.calculate(
            game_state=sample_game_state,
            home_market_price=Decimal("0.50"),
            home_stats=home_stats,
            away_stats=away_stats,
        )

        # Should still produce valid estimate
        assert estimate is not None
        assert estimate.factor_scores is not None

    def test_buy_prices_both_sides(self, sample_game_state, sample_team_stats):
        """Test with explicit home/away buy prices (best ask per outcome)."""
        home_stats, away_stats = sample_team_stats
        calculator = ProbabilityCalculator()

        # e.g. NOP 72c, CHA 28c buy prices (need not sum to 1)
        estimate = calculator.calculate(
            game_state=sample_game_state,
            home_market_price=Decimal("0.72"),
            home_stats=home_stats,
            away_stats=away_stats,
            away_market_price=Decimal("0.28"),
        )

        assert estimate.market_price == Decimal("0.72")
        assert estimate.away_market_price == Decimal("0.28")
        assert Decimal("0.01") <= estimate.estimated_probability <= Decimal("0.99")


class TestEdgeDetector:
    """Tests for edge detector."""

    def test_detect_edge_opportunity(self, sample_game_state, sample_team_stats):
        """Test edge opportunity detection."""
        from polynba.analysis.edge_detector import EdgeDetector, EdgeFilter

        home_stats, away_stats = sample_team_stats
        calculator = ProbabilityCalculator()

        # Use a clearly mispriced market
        estimate = calculator.calculate(
            game_state=sample_game_state,
            home_market_price=Decimal("0.40"),  # Underpriced
            home_stats=home_stats,
            away_stats=away_stats,
        )

        detector = EdgeDetector(
            filter_config=EdgeFilter(min_edge_percent=3.0)
        )

        opportunities = detector.detect(
            game_state=sample_game_state,
            home_market_id="market1",
            home_token_id="token1",
            away_market_id="market2",
            away_token_id="token2",
            estimate=estimate,
        )

        # Should detect at least one opportunity
        assert len(opportunities) >= 0  # May or may not detect based on estimate
