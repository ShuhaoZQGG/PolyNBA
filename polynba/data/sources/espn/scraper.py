"""ESPN data scraper coordinator."""

import logging
from typing import Optional

from ...models import GameState, GameSummary, TeamStats
from .client import ESPNClient, ESPNClientError
from .parser import ESPNParser

logger = logging.getLogger(__name__)


class ESPNScraper:
    """Coordinator for fetching and parsing ESPN NBA data."""

    def __init__(self, client: Optional[ESPNClient] = None):
        """Initialize the scraper.

        Args:
            client: Optional ESPNClient instance. Creates one if not provided.
        """
        self._client = client or ESPNClient()
        self._parser = ESPNParser()

    @property
    def client(self) -> ESPNClient:
        """Get the underlying client."""
        return self._client

    @property
    def is_healthy(self) -> bool:
        """Check if the scraper/client is healthy."""
        return self._client.is_healthy

    async def close(self) -> None:
        """Close the scraper and underlying client."""
        await self._client.close()

    async def get_live_games(self, date: Optional[str] = None) -> list[GameSummary]:
        """Get all games for a date, filtering to live games.

        Args:
            date: Optional date in YYYYMMDD format

        Returns:
            List of live GameSummary objects
        """
        try:
            scoreboard = await self._client.get_scoreboard(date)
            games = self._parser.parse_scoreboard(scoreboard)
            return [g for g in games if g.is_live]
        except ESPNClientError as e:
            logger.error(f"Failed to get live games: {e}")
            return []

    async def get_all_games(self, date: Optional[str] = None) -> list[GameSummary]:
        """Get all games for a date.

        Args:
            date: Optional date in YYYYMMDD format

        Returns:
            List of all GameSummary objects
        """
        try:
            scoreboard = await self._client.get_scoreboard(date)
            return self._parser.parse_scoreboard(scoreboard)
        except ESPNClientError as e:
            logger.error(f"Failed to get all games: {e}")
            return []

    async def get_game_state(self, game_id: str) -> Optional[GameState]:
        """Get detailed game state.

        Args:
            game_id: ESPN game ID

        Returns:
            GameState object or None if unavailable
        """
        try:
            summary = await self._client.get_game_summary(game_id)
            return self._parser.parse_game_summary(summary)
        except ESPNClientError as e:
            logger.error(f"Failed to get game state for {game_id}: {e}")
            return None

    async def get_team_stats(self, team_id: str) -> Optional[TeamStats]:
        """Get team statistics.

        Args:
            team_id: ESPN team ID

        Returns:
            TeamStats object or None if unavailable
        """
        try:
            stats = await self._client.get_team_stats(team_id)
            return self._parser.parse_team_stats(stats, team_id)
        except ESPNClientError as e:
            logger.error(f"Failed to get team stats for {team_id}: {e}")
            return None

    async def get_team_rankings(self) -> dict[str, dict[str, int]]:
        """Get team rankings from standings.

        Returns:
            Dictionary mapping team_id to rank info
        """
        try:
            standings = await self._client.get_standings()
            return self._parser.parse_standings(standings)
        except ESPNClientError as e:
            logger.error(f"Failed to get team rankings: {e}")
            return {}

    async def get_game_with_context(
        self, game_id: str
    ) -> tuple[Optional[GameState], dict[str, Optional[TeamStats]]]:
        """Get game state with team statistics.

        Args:
            game_id: ESPN game ID

        Returns:
            Tuple of (GameState, {team_id: TeamStats})
        """
        game_state = await self.get_game_state(game_id)

        if not game_state:
            return None, {}

        team_stats = {}

        # Fetch stats for both teams
        for team in [game_state.home_team, game_state.away_team]:
            stats = await self.get_team_stats(team.team_id)
            team_stats[team.team_id] = stats

        return game_state, team_stats
