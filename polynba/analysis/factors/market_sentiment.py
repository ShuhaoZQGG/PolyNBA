"""Market sentiment factor - identifies mispricing based on score vs odds."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ...data.models import GameState, TeamSide

logger = logging.getLogger(__name__)


@dataclass
class MarketSentimentInput:
    """Input data for market sentiment analysis."""

    game_state: GameState
    home_market_price: Decimal  # Current market price for home win (0-1)
    away_market_price: Decimal  # Current market price for away win (0-1)


@dataclass
class MarketSentimentOutput:
    """Output from market sentiment factor."""

    score: int  # -100 to +100 (positive = home undervalued)
    home_implied_prob: float
    away_implied_prob: float
    fair_home_prob: float
    fair_away_prob: float
    mispricing_magnitude: float  # Percentage points
    reasoning: str


class MarketSentimentFactor:
    """Factor 1: Market mispricing detection.

    Compares current market odds to what the score/time would suggest.
    Identifies when markets haven't adjusted properly to game flow.
    """

    # Win probability lookup by lead and time remaining
    # Based on historical NBA data
    WIN_PROB_TABLE = {
        # (lead, minutes_remaining) -> home_win_probability_if_leading
        # This is a simplified model; production would use more granular data
        (0, 48): 0.50,
        (0, 24): 0.50,
        (0, 12): 0.50,
        (0, 6): 0.50,
        (0, 3): 0.50,
        (0, 1): 0.50,
        # Small lead (1-5 points)
        (3, 48): 0.55,
        (3, 24): 0.58,
        (3, 12): 0.65,
        (3, 6): 0.72,
        (3, 3): 0.80,
        (3, 1): 0.88,
        # Medium lead (6-10 points)
        (8, 48): 0.62,
        (8, 24): 0.70,
        (8, 12): 0.82,
        (8, 6): 0.90,
        (8, 3): 0.95,
        (8, 1): 0.98,
        # Large lead (11-15 points)
        (13, 48): 0.70,
        (13, 24): 0.80,
        (13, 12): 0.92,
        (13, 6): 0.97,
        (13, 3): 0.99,
        (13, 1): 0.995,
        # Very large lead (16+ points)
        (18, 48): 0.78,
        (18, 24): 0.88,
        (18, 12): 0.96,
        (18, 6): 0.99,
        (18, 3): 0.998,
        (18, 1): 0.999,
    }

    def __init__(self, sensitivity: float = 1.0):
        """Initialize market sentiment factor.

        Args:
            sensitivity: Multiplier for score output (default 1.0)
        """
        self._sensitivity = sensitivity

    def calculate(self, input_data: MarketSentimentInput) -> MarketSentimentOutput:
        """Calculate market sentiment score.

        Args:
            input_data: Market and game state data

        Returns:
            MarketSentimentOutput with score and analysis
        """
        game = input_data.game_state

        # Calculate implied probabilities from market
        home_implied = float(input_data.home_market_price)
        away_implied = float(input_data.away_market_price)

        # Normalize if they don't sum to 1
        total = home_implied + away_implied
        if total > 0:
            home_implied /= total
            away_implied /= total

        # Calculate fair probability based on game state
        fair_home = self._calculate_fair_probability(game)
        fair_away = 1.0 - fair_home

        # Calculate mispricing
        home_mispricing = fair_home - home_implied  # Positive = home undervalued
        mispricing_magnitude = abs(home_mispricing) * 100

        # Convert to score (-100 to +100)
        # +100 = home heavily undervalued
        # -100 = away heavily undervalued (home overvalued)
        raw_score = home_mispricing * 200  # Scale to -100 to +100 range
        score = int(max(-100, min(100, raw_score * self._sensitivity)))

        # Generate reasoning
        reasoning = self._generate_reasoning(
            game, home_implied, fair_home, score
        )

        return MarketSentimentOutput(
            score=score,
            home_implied_prob=home_implied,
            away_implied_prob=away_implied,
            fair_home_prob=fair_home,
            fair_away_prob=fair_away,
            mispricing_magnitude=mispricing_magnitude,
            reasoning=reasoning,
        )

    def _calculate_fair_probability(self, game: GameState) -> float:
        """Calculate fair win probability based on game state."""
        lead = game.score_differential  # Positive = home leading
        minutes_remaining = game.total_seconds_remaining / 60

        # Find closest entries in lookup table
        abs_lead = abs(lead)

        # Bucket the lead
        if abs_lead == 0:
            lead_bucket = 0
        elif abs_lead <= 5:
            lead_bucket = 3
        elif abs_lead <= 10:
            lead_bucket = 8
        elif abs_lead <= 15:
            lead_bucket = 13
        else:
            lead_bucket = 18

        # Bucket the time
        time_buckets = [48, 24, 12, 6, 3, 1]
        time_bucket = time_buckets[-1]
        for t in time_buckets:
            if minutes_remaining >= t:
                time_bucket = t
                break

        # Look up base probability (for leading team)
        key = (lead_bucket, time_bucket)
        leading_team_prob = self.WIN_PROB_TABLE.get(key, 0.50)

        # Interpolate for more precision
        leading_team_prob = self._interpolate_probability(
            abs_lead, minutes_remaining, leading_team_prob
        )

        # Convert to home team probability
        if lead > 0:
            # Home is leading
            return leading_team_prob
        elif lead < 0:
            # Away is leading, home probability is 1 - leading_prob
            return 1.0 - leading_team_prob
        else:
            # Tied
            return 0.50

    def _interpolate_probability(
        self,
        lead: int,
        minutes: float,
        base_prob: float,
    ) -> float:
        """Interpolate probability for more precision."""
        # Adjust for exact lead (each point ~1-2% depending on time)
        if minutes > 24:
            point_value = 0.01
        elif minutes > 12:
            point_value = 0.015
        elif minutes > 6:
            point_value = 0.02
        elif minutes > 3:
            point_value = 0.03
        else:
            point_value = 0.05

        # Slight adjustment based on exact values
        adjustment = 0

        # More time = closer to 0.5
        if minutes > 36:
            adjustment -= (base_prob - 0.5) * 0.1

        return max(0.01, min(0.99, base_prob + adjustment))

    def _generate_reasoning(
        self,
        game: GameState,
        market_prob: float,
        fair_prob: float,
        score: int,
    ) -> str:
        """Generate human-readable reasoning."""
        lead = game.score_differential
        minutes = game.total_seconds_remaining / 60

        if abs(score) < 10:
            assessment = "Market is fairly priced"
        elif abs(score) < 25:
            assessment = "Slight mispricing detected"
        elif abs(score) < 50:
            assessment = "Moderate mispricing detected"
        else:
            assessment = "Significant mispricing detected"

        leader = "Home" if lead > 0 else "Away" if lead < 0 else "Tied"
        lead_str = f"{leader} by {abs(lead)}" if lead != 0 else "Tied game"

        return (
            f"{assessment}. {lead_str} with {minutes:.1f} min remaining. "
            f"Market implies {market_prob:.1%} home win, "
            f"fair value estimate is {fair_prob:.1%}."
        )
