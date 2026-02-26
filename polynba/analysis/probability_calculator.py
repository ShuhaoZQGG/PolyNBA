"""Three-factor probability calculator for edge detection."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from ..data.models import GameState, TeamContext, TeamStats
from .factors import (
    GameContextFactor,
    GameContextInput,
    GameContextOutput,
    MarketSentimentFactor,
    MarketSentimentInput,
    MarketSentimentOutput,
    TeamStrengthFactor,
    TeamStrengthInput,
    TeamStrengthOutput,
)

logger = logging.getLogger(__name__)


@dataclass
class FactorWeights:
    """Weights for combining factor scores."""

    market_sentiment: float = 0.40
    game_context: float = 0.35
    team_strength: float = 0.25

    def __post_init__(self):
        """Validate weights sum to 1."""
        total = self.market_sentiment + self.game_context + self.team_strength
        if abs(total - 1.0) > 0.001:
            # Normalize
            self.market_sentiment /= total
            self.game_context /= total
            self.team_strength /= total


@dataclass
class FactorScores:
    """Individual factor scores."""

    market_sentiment: MarketSentimentOutput
    game_context: GameContextOutput
    team_strength: TeamStrengthOutput


@dataclass
class ProbabilityEstimate:
    """Estimated probability with factor breakdown."""

    market_price: Decimal  # Home buy price (best ask) = probability to pay for home win
    estimated_probability: Decimal  # Our estimate for home win
    edge: Decimal  # estimated - market
    edge_percentage: float  # Edge as percentage
    combined_score: int  # Combined factor score (-100 to +100)
    factor_scores: FactorScores
    confidence: int  # 1-10 confidence level
    reasoning: str
    away_market_price: Optional[Decimal] = None  # Away buy price (best ask); set when both sides from order book


class ProbabilityCalculator:
    """Calculates probability estimates using three-factor model.

    Factors:
    1. Market Sentiment: How unjustified are current odds vs score/time?
    2. Game Context: Momentum, fouls, timeouts, clutch situations
    3. Team Strength: Rankings, efficiency, head-to-head

    Each factor outputs -100 to +100, combined with weights.
    Final adjustment capped at ±25% of market odds.
    """

    # Maximum adjustment to market probability
    MAX_ADJUSTMENT = 0.25

    # Score to adjustment conversion factor
    SCORE_TO_ADJUSTMENT = 0.0025  # 100 score = 25% adjustment

    def __init__(
        self,
        weights: Optional[FactorWeights] = None,
        market_sentiment_factor: Optional[MarketSentimentFactor] = None,
        game_context_factor: Optional[GameContextFactor] = None,
        team_strength_factor: Optional[TeamStrengthFactor] = None,
    ):
        """Initialize probability calculator.

        Args:
            weights: Factor weights configuration
            market_sentiment_factor: Custom market sentiment factor
            game_context_factor: Custom game context factor
            team_strength_factor: Custom team strength factor
        """
        self._weights = weights or FactorWeights()
        self._market_sentiment = market_sentiment_factor or MarketSentimentFactor()
        self._game_context = game_context_factor or GameContextFactor()
        self._team_strength = team_strength_factor or TeamStrengthFactor()

    @property
    def weights(self) -> FactorWeights:
        """Get current factor weights."""
        return self._weights

    def update_weights(self, weights: FactorWeights) -> None:
        """Update factor weights.

        Args:
            weights: New factor weights
        """
        self._weights = weights

    def calculate(
        self,
        game_state: GameState,
        home_market_price: Decimal,
        home_stats: TeamStats,
        away_stats: TeamStats,
        home_context: Optional[TeamContext] = None,
        away_context: Optional[TeamContext] = None,
        away_market_price: Optional[Decimal] = None,
    ) -> ProbabilityEstimate:
        """Calculate probability estimate for home team win.

        Args:
            game_state: Current game state
            home_market_price: Buy price for home win (best ask, 0-1)
            home_stats: Home team statistics
            away_stats: Away team statistics
            home_context: Optional home team context
            away_context: Optional away team context
            away_market_price: Buy price for away win (best ask); if None, derived as 1 - home

        Returns:
            ProbabilityEstimate with edge calculation
        """
        if away_market_price is None:
            away_market_price = Decimal("1") - home_market_price

        # Calculate each factor
        sentiment_result = self._market_sentiment.calculate(
            MarketSentimentInput(
                game_state=game_state,
                home_market_price=home_market_price,
                away_market_price=away_market_price,
            )
        )

        context_result = self._game_context.calculate(
            GameContextInput(game_state=game_state)
        )

        strength_result = self._team_strength.calculate(
            TeamStrengthInput(
                home_stats=home_stats,
                away_stats=away_stats,
                home_context=home_context,
                away_context=away_context,
            )
        )

        # Combine scores with weights
        combined_score = int(
            sentiment_result.score * self._weights.market_sentiment
            + context_result.score * self._weights.game_context
            + strength_result.score * self._weights.team_strength
        )

        # Convert combined score to probability adjustment
        # Score of 100 = +25% adjustment, Score of -100 = -25% adjustment
        adjustment = Decimal(str(combined_score * self.SCORE_TO_ADJUSTMENT))

        # Cap adjustment
        adjustment = max(
            Decimal(str(-self.MAX_ADJUSTMENT)),
            min(Decimal(str(self.MAX_ADJUSTMENT)), adjustment)
        )

        # Calculate estimated probability
        estimated_prob = home_market_price + adjustment

        # Ensure within valid range
        estimated_prob = max(Decimal("0.01"), min(Decimal("0.99"), estimated_prob))

        # Calculate edge
        edge = estimated_prob - home_market_price
        edge_percentage = float(edge * 100)

        # Determine confidence (1-10)
        confidence = self._calculate_confidence(
            sentiment_result, context_result, strength_result, combined_score
        )

        # Generate reasoning
        reasoning = self._generate_reasoning(
            sentiment_result, context_result, strength_result,
            combined_score, edge_percentage
        )

        factor_scores = FactorScores(
            market_sentiment=sentiment_result,
            game_context=context_result,
            team_strength=strength_result,
        )

        return ProbabilityEstimate(
            market_price=home_market_price,
            estimated_probability=estimated_prob,
            edge=edge,
            edge_percentage=edge_percentage,
            combined_score=combined_score,
            factor_scores=factor_scores,
            confidence=confidence,
            reasoning=reasoning,
            away_market_price=away_market_price,
        )

    def _calculate_confidence(
        self,
        sentiment: MarketSentimentOutput,
        context: GameContextOutput,
        strength: TeamStrengthOutput,
        combined_score: int,
    ) -> int:
        """Calculate confidence level (1-10)."""
        confidence = 5  # Base confidence

        # Higher confidence when factors agree
        scores = [sentiment.score, context.score, strength.score]
        all_positive = all(s > 0 for s in scores)
        all_negative = all(s < 0 for s in scores)

        if all_positive or all_negative:
            confidence += 2  # Factors agree

        # Higher confidence with stronger signals
        if abs(combined_score) > 50:
            confidence += 1
        if abs(combined_score) > 75:
            confidence += 1

        # Reduce confidence when net_rating data is unavailable
        if strength.efficiency.home_net_rating == 0.0 and strength.efficiency.away_net_rating == 0.0:
            confidence -= 1

        # Lower confidence in very close games
        if context.clutch.is_clutch and context.clutch.pressure_level > 80:
            confidence -= 1

        # Higher confidence with clear tier mismatch
        if strength.tiers.mismatch_level >= 2:
            confidence += 1

        return max(1, min(10, confidence))

    def _generate_reasoning(
        self,
        sentiment: MarketSentimentOutput,
        context: GameContextOutput,
        strength: TeamStrengthOutput,
        combined_score: int,
        edge_percentage: float,
    ) -> str:
        """Generate comprehensive reasoning."""
        parts = []

        # Overall assessment
        if abs(edge_percentage) < 3:
            parts.append("Market appears fairly priced.")
        elif edge_percentage > 0:
            parts.append(f"Home team appears undervalued by {edge_percentage:.1f}%.")
        else:
            parts.append(f"Away team appears undervalued by {-edge_percentage:.1f}%.")

        # Key factors
        key_factors = []

        if abs(sentiment.score) >= 30:
            direction = "undervalued" if sentiment.score > 0 else "overvalued"
            key_factors.append(f"market shows home {direction}")

        if abs(context.score) >= 30:
            favor = "home" if context.score > 0 else "away"
            key_factors.append(f"game context favors {favor}")

        if abs(strength.score) >= 30:
            stronger = "home" if strength.score > 0 else "away"
            key_factors.append(f"{stronger} is stronger team")

        if key_factors:
            parts.append(f"Key factors: {', '.join(key_factors)}.")

        # Note data quality issues
        if strength.efficiency.home_net_rating == 0.0 and strength.efficiency.away_net_rating == 0.0:
            parts.append("Note: team net rating data unavailable, using records as primary quality signal.")

        return " ".join(parts)


@dataclass
class EdgeOpportunity:
    """An identified edge opportunity."""

    game_id: str
    market_id: str
    token_id: str
    side: str  # "home" or "away"
    market_price: Decimal
    estimated_probability: Decimal
    edge: Decimal
    edge_percentage: float
    confidence: int
    estimate: ProbabilityEstimate


class EdgeDetector:
    """Detects edge opportunities from probability estimates."""

    def __init__(
        self,
        min_edge_percent: float = 5.0,
        min_confidence: int = 5,
    ):
        """Initialize edge detector.

        Args:
            min_edge_percent: Minimum edge percentage to consider
            min_confidence: Minimum confidence level to consider
        """
        self._min_edge = min_edge_percent
        self._min_confidence = min_confidence

    def detect(
        self,
        game_id: str,
        home_market_id: str,
        home_token_id: str,
        away_market_id: str,
        away_token_id: str,
        estimate: ProbabilityEstimate,
    ) -> list[EdgeOpportunity]:
        """Detect edge opportunities from a probability estimate.

        Args:
            game_id: Game identifier
            home_market_id: Market ID for home win
            home_token_id: Token ID for home win
            away_market_id: Market ID for away win
            away_token_id: Token ID for away win
            estimate: Probability estimate

        Returns:
            List of edge opportunities (0, 1, or 2)
        """
        opportunities = []

        # Check home edge
        if (
            estimate.edge_percentage >= self._min_edge
            and estimate.confidence >= self._min_confidence
        ):
            opportunities.append(
                EdgeOpportunity(
                    game_id=game_id,
                    market_id=home_market_id,
                    token_id=home_token_id,
                    side="home",
                    market_price=estimate.market_price,
                    estimated_probability=estimate.estimated_probability,
                    edge=estimate.edge,
                    edge_percentage=estimate.edge_percentage,
                    confidence=estimate.confidence,
                    estimate=estimate,
                )
            )

        # Check away edge (inverted)
        away_edge = -estimate.edge_percentage

        if (
            away_edge >= self._min_edge
            and estimate.confidence >= self._min_confidence
        ):
            away_market_price = Decimal("1") - estimate.market_price
            away_estimated = Decimal("1") - estimate.estimated_probability

            opportunities.append(
                EdgeOpportunity(
                    game_id=game_id,
                    market_id=away_market_id,
                    token_id=away_token_id,
                    side="away",
                    market_price=away_market_price,
                    estimated_probability=away_estimated,
                    edge=-estimate.edge,
                    edge_percentage=away_edge,
                    confidence=estimate.confidence,
                    estimate=estimate,
                )
            )

        return opportunities
