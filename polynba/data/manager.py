"""Data manager coordinating all data sources and caching."""

import logging
from typing import Optional

from .cache import CacheConfig, DataCache, cached
from .failover import DataSource, FailoverManager
from .models import GameState, GameSummary, TeamContext, TeamStats

logger = logging.getLogger(__name__)


class DataManager:
    """Central coordinator for all NBA data access.

    Provides a unified interface for fetching game data with:
    - Automatic caching with configurable TTLs
    - Automatic failover between ESPN and NBA.com
    - Team context aggregation
    """

    def __init__(
        self,
        failover_manager: Optional[FailoverManager] = None,
        cache_config: Optional[CacheConfig] = None,
    ):
        """Initialize the data manager.

        Args:
            failover_manager: Optional FailoverManager instance
            cache_config: Optional cache configuration
        """
        self._failover = failover_manager or FailoverManager()
        self._cache = DataCache(cache_config)

    @property
    def cache(self) -> DataCache:
        """Get the cache instance."""
        return self._cache

    @property
    def failover(self) -> FailoverManager:
        """Get the failover manager."""
        return self._failover

    async def close(self) -> None:
        """Close the data manager and all resources."""
        await self._failover.close()

    async def get_live_games(self, date: Optional[str] = None) -> list[GameSummary]:
        """Get all currently live games.

        Args:
            date: Optional date in YYYYMMDD format

        Returns:
            List of live GameSummary objects
        """
        cache_key = f"live_games_{date or 'today'}"

        return await cached(
            self._cache,
            "scoreboard",
            cache_key,
            lambda: self._failover.get_live_games(date),
        )

    async def get_all_games(self, date: Optional[str] = None) -> list[GameSummary]:
        """Get all games for a date.

        Args:
            date: Optional date in YYYYMMDD format

        Returns:
            List of all GameSummary objects
        """
        cache_key = f"all_games_{date or 'today'}"

        return await cached(
            self._cache,
            "scoreboard",
            cache_key,
            lambda: self._failover.get_all_games(date),
        )

    async def get_game_state(
        self, game_id: str, force_refresh: bool = False
    ) -> Optional[GameState]:
        """Get detailed game state.

        Args:
            game_id: Game ID
            force_refresh: If True, bypass cache

        Returns:
            GameState object or None
        """
        cache_key = f"game_state_{game_id}"

        if force_refresh:
            self._cache.invalidate("game_state", cache_key)

        return await cached(
            self._cache,
            "game_state",
            cache_key,
            lambda: self._failover.get_game_state(game_id),
        )

    async def get_team_stats(
        self, team_id: str, force_refresh: bool = False
    ) -> Optional[TeamStats]:
        """Get team statistics.

        Args:
            team_id: Team ID
            force_refresh: If True, bypass cache

        Returns:
            TeamStats object or None
        """
        cache_key = f"team_stats_{team_id}"

        if force_refresh:
            self._cache.invalidate("team_stats", cache_key)

        return await cached(
            self._cache,
            "team_stats",
            cache_key,
            lambda: self._failover.get_team_stats(team_id),
        )

    async def get_team_context(
        self, team_id: str, opponent_id: Optional[str] = None
    ) -> Optional[TeamContext]:
        """Get full team context including stats and injuries.

        Args:
            team_id: Team ID
            opponent_id: Optional opponent ID for head-to-head data

        Returns:
            TeamContext object or None
        """
        cache_key = f"team_context_{team_id}_{opponent_id or 'none'}"

        cached_value = self._cache.get("team_context", cache_key)
        if cached_value:
            return cached_value

        # Fetch team stats
        stats = await self.get_team_stats(team_id)
        if not stats:
            return None

        # Build context (injuries and head-to-head would need additional data sources)
        context = TeamContext(
            stats=stats,
            injuries=[],  # Would need injury data source
            head_to_head=None,  # Would need head-to-head data source
        )

        self._cache.set("team_context", cache_key, context)
        return context

    async def get_game_with_context(
        self, game_id: str
    ) -> tuple[Optional[GameState], dict[str, Optional[TeamContext]]]:
        """Get game state with full context for both teams.

        Args:
            game_id: Game ID

        Returns:
            Tuple of (GameState, {team_id: TeamContext})
        """
        game_state = await self.get_game_state(game_id)

        if not game_state:
            return None, {}

        # Get context for both teams
        home_context = await self.get_team_context(
            game_state.home_team.team_id,
            game_state.away_team.team_id,
        )

        away_context = await self.get_team_context(
            game_state.away_team.team_id,
            game_state.home_team.team_id,
        )

        contexts = {
            game_state.home_team.team_id: home_context,
            game_state.away_team.team_id: away_context,
        }

        return game_state, contexts

    def invalidate_game_cache(self, game_id: str) -> None:
        """Invalidate cached data for a specific game.

        Args:
            game_id: Game ID
        """
        self._cache.invalidate("game_state", f"game_state_{game_id}")
        logger.debug(f"Invalidated game cache for {game_id}")

    def invalidate_all_live_data(self) -> None:
        """Invalidate all live data caches."""
        self._cache.invalidate_all("game_state")
        self._cache.invalidate_all("scoreboard")
        logger.debug("Invalidated all live data caches")

    def set_primary_source(self, source: DataSource) -> None:
        """Manually set the primary data source.

        Args:
            source: DataSource to use as primary
        """
        self._failover.set_primary(source)

    @property
    def health_status(self) -> dict:
        """Get overall health status."""
        return {
            "failover": self._failover.health_status,
            "cache": self._cache.stats,
        }
