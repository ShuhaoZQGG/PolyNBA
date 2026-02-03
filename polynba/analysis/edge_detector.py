"""Edge detection comparing estimates to market prices."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..data.models import GameState, TeamSide
from .probability_calculator import ProbabilityEstimate

logger = logging.getLogger(__name__)


@dataclass
class EdgeOpportunity:
    """An identified edge opportunity."""

    game_id: str
    market_id: str
    token_id: str
    side: str  # "home" or "away"
    team_name: str
    team_abbreviation: str
    market_price: Decimal
    estimated_probability: Decimal
    edge: Decimal
    edge_percentage: float
    confidence: int
    estimate: ProbabilityEstimate
    detected_at: datetime = field(default_factory=datetime.now)

    @property
    def expected_value(self) -> float:
        """Calculate expected value per dollar bet."""
        # EV = (probability * payout) - cost
        # For binary markets: EV = probability * (1/price) - 1
        if self.market_price == 0:
            return 0.0
        payout = 1 / float(self.market_price)
        prob = float(self.estimated_probability)
        return prob * payout - 1

    @property
    def kelly_fraction(self) -> float:
        """Calculate Kelly criterion fraction."""
        if self.market_price == 0 or self.market_price == 1:
            return 0.0

        p = float(self.estimated_probability)
        q = 1 - p
        b = (1 / float(self.market_price)) - 1  # Odds received

        if b <= 0:
            return 0.0

        kelly = (b * p - q) / b
        return max(0, kelly)


@dataclass
class EdgeFilter:
    """Filter criteria for edge opportunities."""

    min_edge_percent: float = 5.0
    max_edge_percent: float = 50.0  # Suspiciously high edges
    min_confidence: int = 5
    min_market_price: Decimal = Decimal("0.10")
    max_market_price: Decimal = Decimal("0.90")
    min_time_remaining_seconds: int = 300  # 5 minutes
    exclude_overtime: bool = False


class EdgeDetector:
    """Detects and filters edge opportunities."""

    def __init__(self, filter_config: Optional[EdgeFilter] = None):
        """Initialize edge detector.

        Args:
            filter_config: Edge filtering configuration
        """
        self._filter = filter_config or EdgeFilter()

    @property
    def filter_config(self) -> EdgeFilter:
        """Get current filter configuration."""
        return self._filter

    def update_filter(self, config: EdgeFilter) -> None:
        """Update filter configuration."""
        self._filter = config

    def detect(
        self,
        game_state: GameState,
        home_market_id: str,
        home_token_id: str,
        away_market_id: str,
        away_token_id: str,
        estimate: ProbabilityEstimate,
    ) -> list[EdgeOpportunity]:
        """Detect edge opportunities from a probability estimate.

        Args:
            game_state: Current game state
            home_market_id: Market ID for home win
            home_token_id: Token ID for home win
            away_market_id: Market ID for away win
            away_token_id: Token ID for away win
            estimate: Probability estimate

        Returns:
            List of filtered edge opportunities
        """
        opportunities = []

        # Apply basic filters
        if not self._passes_basic_filters(game_state, estimate):
            return opportunities

        # Check home team edge
        if self._is_valid_edge(
            estimate.edge_percentage,
            estimate.confidence,
            estimate.market_price,
        ):
            opportunities.append(
                EdgeOpportunity(
                    game_id=game_state.game_id,
                    market_id=home_market_id,
                    token_id=home_token_id,
                    side="home",
                    team_name=game_state.home_team.team_name,
                    team_abbreviation=game_state.home_team.team_abbreviation,
                    market_price=estimate.market_price,
                    estimated_probability=estimate.estimated_probability,
                    edge=estimate.edge,
                    edge_percentage=estimate.edge_percentage,
                    confidence=estimate.confidence,
                    estimate=estimate,
                )
            )

        # Check away team edge: use away buy price (best ask) when available
        away_buy_price = (
            estimate.away_market_price
            if estimate.away_market_price is not None
            else Decimal("1") - estimate.market_price
        )
        away_estimated = Decimal("1") - estimate.estimated_probability
        away_edge = away_estimated - away_buy_price
        away_edge_percent = float(away_edge * 100)

        if self._is_valid_edge(
            away_edge_percent,
            estimate.confidence,
            away_buy_price,
        ):
            opportunities.append(
                EdgeOpportunity(
                    game_id=game_state.game_id,
                    market_id=away_market_id,
                    token_id=away_token_id,
                    side="away",
                    team_name=game_state.away_team.team_name,
                    team_abbreviation=game_state.away_team.team_abbreviation,
                    market_price=away_buy_price,
                    estimated_probability=away_estimated,
                    edge=away_edge,
                    edge_percentage=away_edge_percent,
                    confidence=estimate.confidence,
                    estimate=estimate,
                )
            )

        return opportunities

    def _passes_basic_filters(
        self, game_state: GameState, estimate: ProbabilityEstimate
    ) -> bool:
        """Check if game/estimate passes basic filters."""
        # Time remaining filter
        if game_state.total_seconds_remaining < self._filter.min_time_remaining_seconds:
            logger.debug(
                f"Filtered: Not enough time remaining "
                f"({game_state.total_seconds_remaining}s)"
            )
            return False

        # Overtime filter
        if self._filter.exclude_overtime and game_state.period.is_overtime:
            logger.debug("Filtered: Overtime excluded")
            return False

        return True

    def _is_valid_edge(
        self,
        edge_percent: float,
        confidence: int,
        market_price: Decimal,
    ) -> bool:
        """Check if an edge opportunity is valid."""
        # Edge size
        if edge_percent < self._filter.min_edge_percent:
            return False

        if edge_percent > self._filter.max_edge_percent:
            logger.debug(f"Filtered: Edge too high ({edge_percent}%), might be stale")
            return False

        # Confidence
        if confidence < self._filter.min_confidence:
            return False

        # Market price range
        if market_price < self._filter.min_market_price:
            return False

        if market_price > self._filter.max_market_price:
            return False

        return True

    def rank_opportunities(
        self,
        opportunities: list[EdgeOpportunity],
        sort_by: str = "expected_value",
    ) -> list[EdgeOpportunity]:
        """Rank opportunities by specified criteria.

        Args:
            opportunities: List of edge opportunities
            sort_by: Ranking criteria ("expected_value", "edge", "confidence", "kelly")

        Returns:
            Sorted list of opportunities
        """
        if sort_by == "expected_value":
            return sorted(opportunities, key=lambda x: x.expected_value, reverse=True)
        elif sort_by == "edge":
            return sorted(opportunities, key=lambda x: x.edge_percentage, reverse=True)
        elif sort_by == "confidence":
            return sorted(opportunities, key=lambda x: x.confidence, reverse=True)
        elif sort_by == "kelly":
            return sorted(opportunities, key=lambda x: x.kelly_fraction, reverse=True)
        else:
            return opportunities

    def filter_conflicting(
        self,
        opportunities: list[EdgeOpportunity],
    ) -> list[EdgeOpportunity]:
        """Remove conflicting opportunities (both sides of same game).

        Keeps the opportunity with higher expected value.

        Args:
            opportunities: List of edge opportunities

        Returns:
            Filtered list without conflicts
        """
        by_game: dict[str, list[EdgeOpportunity]] = {}

        for opp in opportunities:
            if opp.game_id not in by_game:
                by_game[opp.game_id] = []
            by_game[opp.game_id].append(opp)

        result = []
        for game_id, game_opps in by_game.items():
            if len(game_opps) == 1:
                result.append(game_opps[0])
            else:
                # Conflicting signals - take highest EV or skip
                best = max(game_opps, key=lambda x: x.expected_value)
                if best.expected_value > 0.05:  # Only keep if EV > 5%
                    result.append(best)
                    logger.debug(
                        f"Conflicting signals for game {game_id}, "
                        f"keeping {best.side} with EV {best.expected_value:.2%}"
                    )
                else:
                    logger.debug(
                        f"Conflicting signals for game {game_id}, skipping both"
                    )

        return result
