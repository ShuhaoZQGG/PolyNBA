"""NBA.com data scraper coordinator."""

import logging
from typing import Optional

from ...models import GameState, GameSummary
from .client import NBAClient, NBAClientError
from .parser import NBAParser

logger = logging.getLogger(__name__)


class NBAScraper:
    """Coordinator for fetching and parsing NBA.com data."""

    def __init__(self, client: Optional[NBAClient] = None):
        """Initialize the scraper.

        Args:
            client: Optional NBAClient instance. Creates one if not provided.
        """
        self._client = client or NBAClient()
        self._parser = NBAParser()

    @property
    def client(self) -> NBAClient:
        """Get the underlying client."""
        return self._client

    @property
    def is_healthy(self) -> bool:
        """Check if the scraper/client is healthy."""
        return self._client.is_healthy

    async def close(self) -> None:
        """Close the scraper and underlying client."""
        await self._client.close()

    async def get_live_games(self) -> list[GameSummary]:
        """Get all live games.

        Returns:
            List of live GameSummary objects
        """
        try:
            scoreboard = await self._client.get_scoreboard()
            games = self._parser.parse_scoreboard(scoreboard)
            return [g for g in games if g.is_live]
        except NBAClientError as e:
            logger.error(f"Failed to get live games from NBA.com: {e}")
            return []

    async def get_all_games(self) -> list[GameSummary]:
        """Get all games for today.

        Returns:
            List of all GameSummary objects
        """
        try:
            scoreboard = await self._client.get_scoreboard()
            return self._parser.parse_scoreboard(scoreboard)
        except NBAClientError as e:
            logger.error(f"Failed to get all games from NBA.com: {e}")
            return []

    async def get_game_state(self, game_id: str) -> Optional[GameState]:
        """Get detailed game state.

        Args:
            game_id: NBA game ID

        Returns:
            GameState object or None if unavailable
        """
        try:
            boxscore = await self._client.get_boxscore(game_id)
            game_state = self._parser.parse_boxscore(boxscore)

            if game_state:
                # Try to get recent plays
                try:
                    pbp = await self._client.get_playbyplay(game_id)
                    plays = self._parser.parse_playbyplay(
                        pbp, game_state.home_team.team_id
                    )
                    game_state.recent_plays = plays
                except NBAClientError:
                    # Play-by-play is optional
                    pass

            return game_state
        except NBAClientError as e:
            logger.error(f"Failed to get game state from NBA.com for {game_id}: {e}")
            return None
