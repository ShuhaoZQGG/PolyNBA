"""Data models for Polymarket NBA market integration."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class PolymarketNBAMarket:
    """Represents a Polymarket NBA game market."""

    # Core identifiers
    condition_id: str  # Unique market identifier
    question_id: str  # Question/market ID
    slug: str  # URL slug for the market

    # Market question/title
    question: str  # e.g., "Will the Lakers beat the Celtics?"

    # Token IDs for outcomes
    home_token_id: str  # Token ID for home team win
    away_token_id: str  # Token ID for away team win

    # Team information extracted from question
    home_team_name: str
    away_team_name: str

    # Market state
    active: bool = True
    closed: bool = False
    end_date: Optional[datetime] = None

    # Liquidity info
    liquidity: Decimal = Decimal("0")
    volume: Decimal = Decimal("0")

    # Last known prices from API (for display/logging)
    home_price: Optional[Decimal] = None  # Price per share for home team win (0-1)
    away_price: Optional[Decimal] = None  # Price per share for away team win (0-1)

    # Timestamps
    created_at: Optional[datetime] = None
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def is_tradeable(self) -> bool:
        """Check if market is open for trading."""
        return self.active and not self.closed


@dataclass
class MarketPrices:
    """Current prices for a Polymarket NBA market."""

    condition_id: str

    # Mid prices (between best bid and ask)
    home_mid_price: Decimal
    away_mid_price: Decimal

    # Best bid/ask for home outcome
    home_best_bid: Optional[Decimal] = None
    home_best_ask: Optional[Decimal] = None

    # Best bid/ask for away outcome
    away_best_bid: Optional[Decimal] = None
    away_best_ask: Optional[Decimal] = None

    # Order book depth
    home_bid_depth: Decimal = Decimal("0")
    home_ask_depth: Decimal = Decimal("0")
    away_bid_depth: Decimal = Decimal("0")
    away_ask_depth: Decimal = Decimal("0")

    # Timestamp
    fetched_at: datetime = field(default_factory=datetime.now)

    @property
    def home_spread(self) -> Optional[Decimal]:
        """Calculate bid-ask spread for home outcome."""
        if self.home_best_bid and self.home_best_ask:
            return self.home_best_ask - self.home_best_bid
        return None

    @property
    def away_spread(self) -> Optional[Decimal]:
        """Calculate bid-ask spread for away outcome."""
        if self.away_best_bid and self.away_best_ask:
            return self.away_best_ask - self.away_best_bid
        return None

    @property
    def has_liquidity(self) -> bool:
        """Check if market has reasonable liquidity."""
        min_depth = Decimal("100")  # $100 minimum
        return (
            self.home_bid_depth >= min_depth
            and self.home_ask_depth >= min_depth
        )


@dataclass
class MarketMapping:
    """Maps an ESPN game to a Polymarket market."""

    # ESPN identifiers
    espn_game_id: str
    espn_home_team_id: str
    espn_away_team_id: str

    # Polymarket market
    polymarket_market: PolymarketNBAMarket

    # Mapping confidence (0.0 to 1.0)
    confidence: float = 1.0

    # Match details
    matched_home_team: str = ""  # The team name that was matched
    matched_away_team: str = ""
    match_method: str = "exact"  # "exact", "fuzzy", "abbreviation"

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None

    @property
    def is_high_confidence(self) -> bool:
        """Check if mapping has high confidence."""
        return self.confidence >= 0.9

    @property
    def is_expired(self) -> bool:
        """Check if mapping has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


@dataclass
class GammaMarketResponse:
    """Raw response structure from Gamma API for a market."""

    id: str
    question: str
    condition_id: str
    slug: str
    end_date_iso: Optional[str] = None
    active: bool = True
    closed: bool = False
    liquidity: str = "0"
    volume: str = "0"
    outcomes: list[str] = field(default_factory=list)
    outcome_prices: list[str] = field(default_factory=list)
    clob_token_ids: list[str] = field(default_factory=list)
    created_at: Optional[str] = None

    def to_polymarket_market(
        self,
        home_team: str,
        away_team: str,
    ) -> Optional[PolymarketNBAMarket]:
        """Convert to PolymarketNBAMarket if valid NBA game market.

        Args:
            home_team: Extracted home team name
            away_team: Extracted away team name

        Returns:
            PolymarketNBAMarket or None if invalid
        """
        # Need exactly 2 outcomes (home win, away win)
        if len(self.clob_token_ids) != 2:
            return None

        # Parse timestamps
        end_date = None
        if self.end_date_iso:
            try:
                end_date = datetime.fromisoformat(
                    self.end_date_iso.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        created_at = None
        if self.created_at:
            try:
                created_at = datetime.fromisoformat(
                    self.created_at.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        # Determine which token is home vs away based on outcomes
        # Typically outcomes are ordered as they appear in the question
        # We'll assign based on the order - first token is typically "Yes"
        # for home team winning
        home_token_id = self.clob_token_ids[0]
        away_token_id = self.clob_token_ids[1]

        return PolymarketNBAMarket(
            condition_id=self.condition_id,
            question_id=self.id,
            slug=self.slug,
            question=self.question,
            home_token_id=home_token_id,
            away_token_id=away_token_id,
            home_team_name=home_team,
            away_team_name=away_team,
            active=self.active,
            closed=self.closed,
            end_date=end_date,
            liquidity=Decimal(self.liquidity) if self.liquidity else Decimal("0"),
            volume=Decimal(self.volume) if self.volume else Decimal("0"),
            created_at=created_at,
        )
