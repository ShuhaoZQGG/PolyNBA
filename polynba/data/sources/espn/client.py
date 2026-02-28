"""ESPN API HTTP client for NBA data."""

import asyncio
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


class ESPNClientError(Exception):
    """Base exception for ESPN client errors."""

    pass


class ESPNRateLimitError(ESPNClientError):
    """Rate limit exceeded."""

    pass


class ESPNNotFoundError(ESPNClientError):
    """Resource not found."""

    pass


class ESPNClient:
    """Async HTTP client for ESPN NBA API."""

    BASE_URL = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba"
    SUMMARY_URL = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba"
    COMMON_V3_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"

    def __init__(
        self,
        requests_per_second: float = 2.0,
        timeout: float = 10.0,
    ):
        """Initialize ESPN client.

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
                    "User-Agent": "Mozilla/5.0 (compatible; PolyNBA/1.0)",
                    "Accept": "application/json",
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
    async def _request(self, url: str, params: Optional[dict] = None) -> dict[str, Any]:
        """Make an HTTP request with rate limiting and retries.

        Args:
            url: Request URL
            params: Query parameters

        Returns:
            JSON response as dictionary

        Raises:
            ESPNClientError: On request failure
        """
        async with self._rate_limiter:
            session = await self._get_session()

            try:
                async with session.get(url, params=params) as response:
                    if response.status == 429:
                        self._consecutive_failures += 1
                        raise ESPNRateLimitError("Rate limit exceeded")

                    if response.status == 404:
                        raise ESPNNotFoundError(f"Resource not found: {url}")

                    if response.status >= 400:
                        self._consecutive_failures += 1
                        raise ESPNClientError(
                            f"HTTP {response.status}: {await response.text()}"
                        )

                    self._consecutive_failures = 0
                    return await response.json()

            except aiohttp.ClientError as e:
                self._consecutive_failures += 1
                logger.error(f"ESPN API request failed: {e}")
                raise

    @property
    def is_healthy(self) -> bool:
        """Check if the client is healthy (not too many consecutive failures)."""
        return self._consecutive_failures < self._max_consecutive_failures

    def reset_failure_count(self) -> None:
        """Reset the consecutive failure counter."""
        self._consecutive_failures = 0

    async def get_scoreboard(self, date: Optional[str] = None) -> dict[str, Any]:
        """Get NBA scoreboard data.

        Args:
            date: Optional date in YYYYMMDD format. Defaults to today.

        Returns:
            Scoreboard JSON data
        """
        url = f"{self.BASE_URL}/scoreboard"
        params = {}
        if date:
            params["dates"] = date

        logger.debug(f"Fetching scoreboard for date: {date or 'today'}")
        return await self._request(url, params)

    async def get_game_summary(self, game_id: str) -> dict[str, Any]:
        """Get detailed game summary.

        Args:
            game_id: ESPN game ID

        Returns:
            Game summary JSON data
        """
        url = f"{self.SUMMARY_URL}/summary"
        params = {"event": game_id}

        logger.debug(f"Fetching game summary for game_id: {game_id}")
        return await self._request(url, params)

    async def get_team_stats(self, team_id: str) -> dict[str, Any]:
        """Get team statistics.

        Args:
            team_id: ESPN team ID

        Returns:
            Team stats JSON data
        """
        url = f"{self.BASE_URL}/teams/{team_id}/statistics"

        logger.debug(f"Fetching team stats for team_id: {team_id}")
        return await self._request(url)

    async def get_team_info(self, team_id: str) -> dict[str, Any]:
        """Get team info including record, point differential, and home/away splits.

        Args:
            team_id: ESPN team ID

        Returns:
            Team info JSON data (includes record.items with avgPointsFor/Against)
        """
        url = f"{self.BASE_URL}/teams/{team_id}"

        logger.debug(f"Fetching team info for team_id: {team_id}")
        return await self._request(url)

    async def get_team_roster(self, team_id: str) -> dict[str, Any]:
        """Get team roster.

        Args:
            team_id: ESPN team ID

        Returns:
            Team roster JSON data
        """
        url = f"{self.BASE_URL}/teams/{team_id}/roster"

        logger.debug(f"Fetching team roster for team_id: {team_id}")
        return await self._request(url)

    async def get_injuries(self) -> dict[str, Any]:
        """Get NBA injury data for all teams.

        Returns:
            Injuries JSON data
        """
        url = f"{self.BASE_URL}/injuries"

        logger.debug("Fetching NBA injuries")
        return await self._request(url)

    async def get_athlete_overview(self, athlete_id: str) -> dict[str, Any]:
        """Get athlete overview with season stats.

        Args:
            athlete_id: ESPN athlete ID

        Returns:
            Athlete overview JSON data
        """
        url = f"{self.COMMON_V3_URL}/athletes/{athlete_id}/overview"

        logger.debug(f"Fetching athlete overview for athlete_id: {athlete_id}")
        return await self._request(url)

    STANDINGS_URL = "http://site.api.espn.com/apis/v2/sports/basketball/nba"

    async def get_standings(self) -> dict[str, Any]:
        """Get NBA standings.

        Returns:
            Standings JSON data
        """
        url = f"{self.STANDINGS_URL}/standings"

        logger.debug("Fetching NBA standings")
        return await self._request(url)

    async def get_team_schedule(self, team_id: str, season: Optional[int] = None) -> dict[str, Any]:
        """Get team schedule (for head-to-head data).

        Args:
            team_id: ESPN team ID
            season: Optional season year (e.g., 2026). Defaults to current season.

        Returns:
            Team schedule JSON data
        """
        url = f"{self.BASE_URL}/teams/{team_id}/schedule"
        params = {"seasontype": "2"}  # Regular season
        if season:
            params["season"] = str(season)

        logger.debug(f"Fetching team schedule for team_id: {team_id}")
        return await self._request(url, params)

    async def get_play_by_play(self, game_id: str) -> dict[str, Any]:
        """Get play-by-play data for a game.

        Args:
            game_id: ESPN game ID

        Returns:
            Play-by-play JSON data
        """
        url = f"{self.SUMMARY_URL}/playbyplay"
        params = {"event": game_id}

        logger.debug(f"Fetching play-by-play for game_id: {game_id}")
        return await self._request(url, params)


async def main():
    """Test the ESPN client."""
    client = ESPNClient()

    try:
        scoreboard = await client.get_scoreboard()
        print(f"Found {len(scoreboard.get('events', []))} games")

        events = scoreboard.get("events", [])
        if events:
            game_id = events[0]["id"]
            summary = await client.get_game_summary(game_id)
            print(f"Game summary: {summary.get('header', {}).get('competitions', [{}])[0].get('headlines', [{}])[0].get('shortLinkText', 'N/A')}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
