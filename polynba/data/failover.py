"""Failover logic for data sources."""

import logging
from enum import Enum, auto
from typing import Optional

from .models import GameState, GameSummary, PlayerInjury, TeamStats
from .sources.espn import ESPNScraper
from .sources.nba import NBAScraper

logger = logging.getLogger(__name__)


class DataSource(Enum):
    """Available data sources."""

    ESPN = auto()
    NBA = auto()


class FailoverManager:
    """Manages failover between data sources."""

    def __init__(
        self,
        espn_scraper: Optional[ESPNScraper] = None,
        nba_scraper: Optional[NBAScraper] = None,
        failure_threshold: int = 3,
    ):
        """Initialize failover manager.

        Args:
            espn_scraper: ESPN scraper instance
            nba_scraper: NBA scraper instance
            failure_threshold: Consecutive failures before switching sources
        """
        self._espn = espn_scraper or ESPNScraper()
        self._nba = nba_scraper or NBAScraper()
        self._failure_threshold = failure_threshold

        # Track which source is primary
        self._primary_source = DataSource.ESPN
        self._espn_failures = 0
        self._nba_failures = 0

    @property
    def primary_source(self) -> DataSource:
        """Get the current primary data source."""
        return self._primary_source

    @property
    def espn_healthy(self) -> bool:
        """Check if ESPN source is healthy."""
        return self._espn.is_healthy and self._espn_failures < self._failure_threshold

    @property
    def nba_healthy(self) -> bool:
        """Check if NBA source is healthy."""
        return self._nba.is_healthy and self._nba_failures < self._failure_threshold

    def _record_success(self, source: DataSource) -> None:
        """Record a successful request."""
        if source == DataSource.ESPN:
            self._espn_failures = 0
        else:
            self._nba_failures = 0

    def _record_failure(self, source: DataSource) -> None:
        """Record a failed request and potentially switch sources."""
        if source == DataSource.ESPN:
            self._espn_failures += 1
            if self._espn_failures >= self._failure_threshold:
                logger.warning(
                    f"ESPN failures ({self._espn_failures}) reached threshold, "
                    "switching to NBA.com"
                )
                self._primary_source = DataSource.NBA
        else:
            self._nba_failures += 1
            if self._nba_failures >= self._failure_threshold:
                logger.warning(
                    f"NBA.com failures ({self._nba_failures}) reached threshold, "
                    "switching to ESPN"
                )
                self._primary_source = DataSource.ESPN

    def reset_source(self, source: DataSource) -> None:
        """Reset failure count for a source."""
        if source == DataSource.ESPN:
            self._espn_failures = 0
            self._espn.client.reset_failure_count()
        else:
            self._nba_failures = 0
            self._nba.client.reset_failure_count()

    def set_primary(self, source: DataSource) -> None:
        """Manually set the primary source."""
        self._primary_source = source
        logger.info(f"Primary source set to {source.name}")

    async def close(self) -> None:
        """Close all scrapers."""
        await self._espn.close()
        await self._nba.close()

    async def get_live_games(self, date: Optional[str] = None) -> list[GameSummary]:
        """Get live games with failover.

        Args:
            date: Optional date (YYYYMMDD format, ESPN only)

        Returns:
            List of live GameSummary objects
        """
        # Try primary source first
        if self._primary_source == DataSource.ESPN:
            try:
                games = await self._espn.get_live_games(date)
                # Empty list is valid (no live games), not a failure
                self._record_success(DataSource.ESPN)
                return games
            except Exception as e:
                logger.warning(f"ESPN get_live_games failed: {e}")
                self._record_failure(DataSource.ESPN)

            # Try fallback
            try:
                games = await self._nba.get_live_games()
                self._record_success(DataSource.NBA)
                return games
            except Exception as e:
                logger.warning(f"NBA get_live_games failed: {e}")
                self._record_failure(DataSource.NBA)
        else:
            try:
                games = await self._nba.get_live_games()
                self._record_success(DataSource.NBA)
                return games
            except Exception as e:
                logger.warning(f"NBA get_live_games failed: {e}")
                self._record_failure(DataSource.NBA)

            # Try fallback
            try:
                games = await self._espn.get_live_games(date)
                self._record_success(DataSource.ESPN)
                return games
            except Exception as e:
                logger.warning(f"ESPN get_live_games failed: {e}")
                self._record_failure(DataSource.ESPN)

        return []

    async def get_all_games(self, date: Optional[str] = None) -> list[GameSummary]:
        """Get all games with failover.

        Args:
            date: Optional date (YYYYMMDD format, ESPN only)

        Returns:
            List of all GameSummary objects
        """
        if self._primary_source == DataSource.ESPN:
            games = await self._espn.get_all_games(date)
            if games:
                self._record_success(DataSource.ESPN)
                return games

            self._record_failure(DataSource.ESPN)
            games = await self._nba.get_all_games()
            if games:
                self._record_success(DataSource.NBA)
            else:
                self._record_failure(DataSource.NBA)
            return games
        else:
            games = await self._nba.get_all_games()
            if games:
                self._record_success(DataSource.NBA)
                return games

            self._record_failure(DataSource.NBA)
            games = await self._espn.get_all_games(date)
            if games:
                self._record_success(DataSource.ESPN)
            else:
                self._record_failure(DataSource.ESPN)
            return games

    async def get_game_state(self, game_id: str) -> Optional[GameState]:
        """Get game state with failover.

        Note: game_id formats differ between ESPN and NBA.com,
        so failover may not work for game state queries.

        Args:
            game_id: Game ID (format depends on source)

        Returns:
            GameState object or None
        """
        if self._primary_source == DataSource.ESPN:
            state = await self._espn.get_game_state(game_id)
            if state:
                self._record_success(DataSource.ESPN)
                return state

            self._record_failure(DataSource.ESPN)
            # Note: Can't easily failover since IDs differ
            return None
        else:
            state = await self._nba.get_game_state(game_id)
            if state:
                self._record_success(DataSource.NBA)
                return state

            self._record_failure(DataSource.NBA)
            return None

    async def get_team_stats(self, team_id: str) -> Optional[TeamStats]:
        """Get team stats (ESPN only).

        Args:
            team_id: ESPN team ID

        Returns:
            TeamStats object or None
        """
        # Team stats only available from ESPN
        stats = await self._espn.get_team_stats(team_id)
        if stats:
            self._record_success(DataSource.ESPN)
            return stats

        self._record_failure(DataSource.ESPN)
        return None

    async def get_all_injuries(self) -> dict[str, list[PlayerInjury]]:
        """Get injury data for all NBA teams (ESPN only).

        Returns:
            Dictionary mapping team_id to list of PlayerInjury objects
        """
        try:
            result = await self._espn.get_all_injuries()
            if result is not None:
                self._record_success(DataSource.ESPN)
                return result
        except Exception as e:
            logger.warning(f"ESPN get_all_injuries failed: {e}")
            self._record_failure(DataSource.ESPN)
        return {}

    @property
    def health_status(self) -> dict[str, bool]:
        """Get health status of all sources."""
        return {
            "espn_healthy": self.espn_healthy,
            "nba_healthy": self.nba_healthy,
            "primary_source": self._primary_source.name,
            "espn_failures": self._espn_failures,
            "nba_failures": self._nba_failures,
        }
