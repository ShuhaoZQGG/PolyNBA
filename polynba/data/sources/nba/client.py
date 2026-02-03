"""NBA.com CDN client as fallback data source."""

import logging
from typing import Any, Optional

import aiohttp
from aiolimiter import AsyncLimiter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class NBAClientError(Exception):
    """Base exception for NBA client errors."""

    pass


class NBAClient:
    """Async HTTP client for NBA.com CDN endpoints."""

    # NBA CDN endpoints
    BASE_URL = "https://cdn.nba.com/static/json"
    LIVE_DATA_URL = "https://cdn.nba.com/static/json/liveData"

    def __init__(
        self,
        requests_per_second: float = 1.0,
        timeout: float = 15.0,
    ):
        """Initialize NBA client.

        Args:
            requests_per_second: Rate limit for API requests
            timeout: Request timeout in seconds
        """
        self._rate_limiter = AsyncLimiter(requests_per_second, 1.0)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Origin": "https://www.nba.com",
                    "Referer": "https://www.nba.com/",
                },
            )
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @retry(
        retry=retry_if_exception_type(aiohttp.ClientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _request(self, url: str) -> dict[str, Any]:
        """Make an HTTP request with rate limiting and retries.

        Args:
            url: Request URL

        Returns:
            JSON response as dictionary

        Raises:
            NBAClientError: On request failure
        """
        async with self._rate_limiter:
            session = await self._get_session()

            try:
                async with session.get(url) as response:
                    if response.status >= 400:
                        self._consecutive_failures += 1
                        raise NBAClientError(
                            f"HTTP {response.status}: {await response.text()}"
                        )

                    self._consecutive_failures = 0
                    return await response.json(content_type=None)

            except aiohttp.ClientError as e:
                self._consecutive_failures += 1
                logger.error(f"NBA.com API request failed: {e}")
                raise

    @property
    def is_healthy(self) -> bool:
        """Check if the client is healthy."""
        return self._consecutive_failures < self._max_consecutive_failures

    def reset_failure_count(self) -> None:
        """Reset the consecutive failure counter."""
        self._consecutive_failures = 0

    async def get_scoreboard(self) -> dict[str, Any]:
        """Get today's scoreboard.

        Returns:
            Scoreboard JSON data
        """
        url = f"{self.LIVE_DATA_URL}/scoreboard/todaysScoreboard_00.json"
        logger.debug("Fetching NBA.com scoreboard")
        return await self._request(url)

    async def get_boxscore(self, game_id: str) -> dict[str, Any]:
        """Get boxscore for a game.

        Args:
            game_id: NBA game ID (format: 00XXXXXXXX)

        Returns:
            Boxscore JSON data
        """
        url = f"{self.LIVE_DATA_URL}/boxscore/boxscore_{game_id}.json"
        logger.debug(f"Fetching NBA.com boxscore for game: {game_id}")
        return await self._request(url)

    async def get_playbyplay(self, game_id: str) -> dict[str, Any]:
        """Get play-by-play for a game.

        Args:
            game_id: NBA game ID

        Returns:
            Play-by-play JSON data
        """
        url = f"{self.LIVE_DATA_URL}/playbyplay/playbyplay_{game_id}.json"
        logger.debug(f"Fetching NBA.com play-by-play for game: {game_id}")
        return await self._request(url)
