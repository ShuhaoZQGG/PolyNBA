"""Maps ESPN games to Polymarket markets."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from ..data.models import GameState
from .market_discovery import MarketDiscovery, NBA_TEAMS
from .models import MarketMapping, PolymarketNBAMarket

logger = logging.getLogger(__name__)


# Team name variations mapping to abbreviations
# Handles common variations in how teams are named
TEAM_NAME_VARIATIONS = {
    # Los Angeles teams (commonly confused)
    "la lakers": "LAL",
    "los angeles lakers": "LAL",
    "l.a. lakers": "LAL",
    "lakers": "LAL",
    "la clippers": "LAC",
    "los angeles clippers": "LAC",
    "l.a. clippers": "LAC",
    "clippers": "LAC",
    # Other common variations
    "brooklyn": "BKN",
    "brooklyn nets": "BKN",
    "new york": "NYK",
    "ny knicks": "NYK",
    "new york knicks": "NYK",
    "golden state": "GSW",
    "gsw": "GSW",
    "oklahoma city": "OKC",
    "okc": "OKC",
    "san antonio": "SAS",
    "portland": "POR",
    "new orleans": "NOP",
    "minnesota": "MIN",
    "sacramento": "SAC",
    "philadelphia": "PHI",
    "philly": "PHI",
    "washington": "WAS",
    "charlotte": "CHA",
    "cleveland": "CLE",
    "milwaukee": "MIL",
    "atlanta": "ATL",
    "boston": "BOS",
    "chicago": "CHI",
    "dallas": "DAL",
    "denver": "DEN",
    "detroit": "DET",
    "houston": "HOU",
    "indiana": "IND",
    "memphis": "MEM",
    "miami": "MIA",
    "orlando": "ORL",
    "phoenix": "PHX",
    "toronto": "TOR",
    "utah": "UTA",
}


class MarketMapper:
    """Maps ESPN game data to Polymarket markets."""

    def __init__(
        self,
        discovery: MarketDiscovery,
        mapping_ttl_seconds: int = 300,
    ):
        """Initialize market mapper.

        Args:
            discovery: MarketDiscovery instance for finding markets
            mapping_ttl_seconds: How long to cache mappings
        """
        self._discovery = discovery
        self._mapping_ttl = mapping_ttl_seconds

        # Cache of mappings by ESPN game ID
        self._mappings: dict[str, MarketMapping] = {}
        self._mapping_times: dict[str, datetime] = {}

    async def get_market_for_game(
        self,
        game_state: GameState,
    ) -> Optional[MarketMapping]:
        """Find Polymarket market for an ESPN game.

        Args:
            game_state: Current game state from ESPN

        Returns:
            MarketMapping if found, None otherwise
        """
        game_id = game_state.game_id

        # Check cache
        cached = self._get_cached_mapping(game_id)
        if cached is not None:
            return cached

        # Discover markets
        markets = await self._discovery.discover_nba_markets()
        if not markets:
            logger.warning("No NBA markets found on Polymarket")
            return None

        # Find best matching market
        mapping = self._find_best_match(game_state, markets)

        if mapping:
            self._cache_mapping(game_id, mapping)
            logger.info(
                f"Mapped {game_state.away_team.team_abbreviation} @ "
                f"{game_state.home_team.team_abbreviation} to Polymarket market "
                f"(confidence={mapping.confidence:.2f})"
            )
        else:
            logger.debug(
                f"No Polymarket market found for {game_state.away_team.team_abbreviation} @ "
                f"{game_state.home_team.team_abbreviation}"
            )
            # Cache negative result briefly
            self._cache_mapping(game_id, None)

        return mapping

    def _get_cached_mapping(self, game_id: str) -> Optional[MarketMapping]:
        """Get cached mapping if still valid.

        Args:
            game_id: ESPN game ID

        Returns:
            Cached mapping, or None if not cached/expired
        """
        if game_id not in self._mappings:
            return None

        cached_time = self._mapping_times.get(game_id)
        if not cached_time:
            return None

        # Check if expired
        if datetime.now() - cached_time > timedelta(seconds=self._mapping_ttl):
            del self._mappings[game_id]
            del self._mapping_times[game_id]
            return None

        return self._mappings.get(game_id)

    def _cache_mapping(
        self,
        game_id: str,
        mapping: Optional[MarketMapping],
    ) -> None:
        """Cache a mapping result.

        Args:
            game_id: ESPN game ID
            mapping: Mapping to cache (or None for negative result)
        """
        self._mappings[game_id] = mapping
        self._mapping_times[game_id] = datetime.now()

    def _find_best_match(
        self,
        game_state: GameState,
        markets: list[PolymarketNBAMarket],
    ) -> Optional[MarketMapping]:
        """Find the best matching market for a game.

        Args:
            game_state: Game to match
            markets: Available Polymarket markets

        Returns:
            Best matching MarketMapping or None
        """
        home_abbr = game_state.home_team.team_abbreviation.upper()
        away_abbr = game_state.away_team.team_abbreviation.upper()
        home_name = game_state.home_team.team_name.lower()
        away_name = game_state.away_team.team_name.lower()

        best_match: Optional[MarketMapping] = None
        best_confidence = 0.0

        for market in markets:
            confidence, match_details = self._calculate_match_confidence(
                home_abbr=home_abbr,
                away_abbr=away_abbr,
                home_name=home_name,
                away_name=away_name,
                market=market,
            )

            if confidence > best_confidence:
                best_confidence = confidence
                best_match = MarketMapping(
                    espn_game_id=game_state.game_id,
                    espn_home_team_id=game_state.home_team.team_id,
                    espn_away_team_id=game_state.away_team.team_id,
                    polymarket_market=market,
                    confidence=confidence,
                    matched_home_team=match_details.get("home", ""),
                    matched_away_team=match_details.get("away", ""),
                    match_method=match_details.get("method", "unknown"),
                    expires_at=datetime.now() + timedelta(seconds=self._mapping_ttl),
                )

        # Only return if confidence is above threshold
        if best_match and best_confidence >= 0.7:
            return best_match

        return None

    def _calculate_match_confidence(
        self,
        home_abbr: str,
        away_abbr: str,
        home_name: str,
        away_name: str,
        market: PolymarketNBAMarket,
    ) -> tuple[float, dict]:
        """Calculate confidence score for a market match.

        Args:
            home_abbr: Home team abbreviation (e.g., "LAL")
            away_abbr: Away team abbreviation (e.g., "BOS")
            home_name: Home team full name
            away_name: Away team full name
            market: Polymarket market to check

        Returns:
            Tuple of (confidence 0-1, match details dict)
        """
        market_home = market.home_team_name.lower()
        market_away = market.away_team_name.lower()

        # Get abbreviations for market teams
        market_home_abbr = self._name_to_abbreviation(market_home)
        market_away_abbr = self._name_to_abbreviation(market_away)

        # Strategy 1: Exact abbreviation match
        if market_home_abbr == home_abbr and market_away_abbr == away_abbr:
            return 1.0, {
                "home": market_home,
                "away": market_away,
                "method": "exact_abbreviation",
            }

        # Strategy 2: Abbreviation match but teams swapped
        # (Polymarket may have different home/away convention)
        if market_home_abbr == away_abbr and market_away_abbr == home_abbr:
            return 0.9, {
                "home": market_away,  # swapped
                "away": market_home,
                "method": "swapped_abbreviation",
            }

        # Strategy 3: Fuzzy name match
        home_match = self._fuzzy_match_team(home_name, market_home) or \
                     self._fuzzy_match_team(home_name, market_away)
        away_match = self._fuzzy_match_team(away_name, market_away) or \
                     self._fuzzy_match_team(away_name, market_home)

        if home_match and away_match:
            return 0.85, {
                "home": market_home if self._fuzzy_match_team(home_name, market_home) else market_away,
                "away": market_away if self._fuzzy_match_team(away_name, market_away) else market_home,
                "method": "fuzzy_name",
            }

        # Strategy 4: Partial match (one team matches)
        if home_match or away_match:
            return 0.5, {
                "home": market_home,
                "away": market_away,
                "method": "partial",
            }

        return 0.0, {}

    def _name_to_abbreviation(self, name: str) -> Optional[str]:
        """Convert team name to abbreviation.

        Args:
            name: Team name (any format)

        Returns:
            3-letter abbreviation or None
        """
        name = name.lower().strip()

        # Check variations first
        if name in TEAM_NAME_VARIATIONS:
            return TEAM_NAME_VARIATIONS[name]

        # Check NBA_TEAMS mapping
        if name in NBA_TEAMS:
            return NBA_TEAMS[name]

        # Try partial match
        for team_name, abbr in TEAM_NAME_VARIATIONS.items():
            if team_name in name or name in team_name:
                return abbr

        for team_name, abbr in NBA_TEAMS.items():
            if team_name in name or name in team_name:
                return abbr

        return None

    def _fuzzy_match_team(self, espn_name: str, market_name: str) -> bool:
        """Check if two team names match (fuzzy).

        Args:
            espn_name: Team name from ESPN
            market_name: Team name from market

        Returns:
            True if they likely refer to the same team
        """
        # Normalize both names
        espn_abbr = self._name_to_abbreviation(espn_name)
        market_abbr = self._name_to_abbreviation(market_name)

        # If we can get abbreviations, compare them
        if espn_abbr and market_abbr:
            return espn_abbr == market_abbr

        # Fallback: check for common substrings
        espn_words = set(espn_name.lower().split())
        market_words = set(market_name.lower().split())

        # Remove common words
        common_words = {"the", "a", "an", "team", "basketball"}
        espn_words -= common_words
        market_words -= common_words

        # Check for overlap
        if espn_words & market_words:
            return True

        return False

    def invalidate_mapping(self, game_id: str) -> None:
        """Invalidate cached mapping for a game.

        Args:
            game_id: ESPN game ID
        """
        if game_id in self._mappings:
            del self._mappings[game_id]
        if game_id in self._mapping_times:
            del self._mapping_times[game_id]

    def clear_cache(self) -> None:
        """Clear all cached mappings."""
        self._mappings.clear()
        self._mapping_times.clear()
