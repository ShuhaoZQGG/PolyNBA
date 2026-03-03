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

try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession

    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

logger = logging.getLogger(__name__)


class NBAClientError(Exception):
    """Base exception for NBA client errors."""

    pass


class NBAClient:
    """Async HTTP client for NBA.com CDN endpoints."""

    # NBA CDN endpoints
    BASE_URL = "https://cdn.nba.com/static/json"
    LIVE_DATA_URL = "https://cdn.nba.com/static/json/liveData"
    STATIC_DATA_URL = "https://cdn.nba.com/static/json/staticData"
    STATS_URL = "https://stats.nba.com/stats"

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
        self._curl_session: Optional[Any] = None
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

    async def _get_curl_session(self) -> "CurlAsyncSession":
        """Get or create a curl_cffi session with Chrome TLS fingerprint."""
        if self._curl_session is None:
            self._curl_session = CurlAsyncSession(
                impersonate="chrome",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": "https://www.nba.com",
                    "Referer": "https://www.nba.com/",
                    "Host": "stats.nba.com",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-site",
                },
                timeout=45,
            )
        return self._curl_session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
        if self._curl_session is not None:
            await self._curl_session.close()
            self._curl_session = None

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

    async def get_player_index(self) -> dict[str, Any]:
        """Get the NBA player index with season stats for all active players.

        Returns:
            Player index JSON data
        """
        url = f"{self.STATIC_DATA_URL}/playerIndex.json"
        logger.debug("Fetching NBA.com player index")
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

    async def get_base_player_stats(self, season: str = "2025-26") -> dict[str, Any]:
        """Get base per-game player stats from stats.nba.com for all active players.

        Returns FG%, 3P%, FT%, STL, BLK, TOV, PF, MIN, GP — the same stats
        that previously required ~270 ESPN calls (roster + 8 overview per team).

        Args:
            season: NBA season string (e.g. "2025-26")

        Returns:
            Base player stats JSON data (resultSets format)
        """
        url = (
            f"{self.STATS_URL}/leaguedashplayerstats"
            f"?College=&Conference=&Country=&DateFrom=&DateTo=&Division="
            f"&DraftPick=&DraftYear=&GameScope=&GameSegment=&Height="
            f"&ISTRound=&LastNGames=0&LeagueID=00&Location="
            f"&MeasureType=Base&Month=0&OpponentTeamID=0&Outcome="
            f"&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0"
            f"&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N"
            f"&Season={season}&SeasonSegment=&SeasonType=Regular%20Season"
            f"&ShotClockRange=&StarterBench=&TeamID=0&VsConference="
            f"&VsDivision=&Weight="
        )
        logger.debug(f"Fetching NBA.com base player stats for {season}")

        if HAS_CURL_CFFI:
            return await self._request_stats_impersonated(url)

        logger.warning(
            "curl_cffi not installed — falling back to aiohttp for stats.nba.com "
            "(likely to be blocked by TLS fingerprinting)"
        )
        return await self._request_stats(url)

    async def get_advanced_player_stats(self, season: str = "2025-26") -> dict[str, Any]:
        """Get advanced player stats from stats.nba.com for all active players.

        Uses a longer timeout than CDN endpoints since stats.nba.com returns
        a large dataset (~500+ players) and can be slow to respond.

        Args:
            season: NBA season string (e.g. "2025-26")

        Returns:
            Advanced player stats JSON data (resultSets format)
        """
        url = (
            f"{self.STATS_URL}/leaguedashplayerstats"
            f"?College=&Conference=&Country=&DateFrom=&DateTo=&Division="
            f"&DraftPick=&DraftYear=&GameScope=&GameSegment=&Height="
            f"&ISTRound=&LastNGames=0&LeagueID=00&Location="
            f"&MeasureType=Advanced&Month=0&OpponentTeamID=0&Outcome="
            f"&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0"
            f"&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N"
            f"&Season={season}&SeasonSegment=&SeasonType=Regular%20Season"
            f"&ShotClockRange=&StarterBench=&TeamID=0&VsConference="
            f"&VsDivision=&Weight="
        )
        logger.debug(f"Fetching NBA.com advanced player stats for {season}")

        if HAS_CURL_CFFI:
            return await self._request_stats_impersonated(url)

        logger.warning(
            "curl_cffi not installed — falling back to aiohttp for stats.nba.com "
            "(likely to be blocked by TLS fingerprinting)"
        )
        return await self._request_stats(url)

    async def get_advanced_team_stats(self, season: str = "2025-26") -> dict[str, Any]:
        """Get advanced team stats from stats.nba.com for all 30 teams.

        Args:
            season: NBA season string (e.g. "2025-26")

        Returns:
            Advanced team stats JSON data (resultSets format)
        """
        url = (
            f"{self.STATS_URL}/leaguedashteamstats"
            f"?Conference=&DateFrom=&DateTo=&Division="
            f"&GameScope=&GameSegment=&Height="
            f"&ISTRound=&LastNGames=0&LeagueID=00&Location="
            f"&MeasureType=Advanced&Month=0&OpponentTeamID=0&Outcome="
            f"&PORound=0&PaceAdjust=N&PerMode=PerGame&Period=0"
            f"&PlayerExperience=&PlayerPosition=&PlusMinus=N&Rank=N"
            f"&Season={season}&SeasonSegment=&SeasonType=Regular%20Season"
            f"&ShotClockRange=&StarterBench=&TeamID=0&VsConference="
            f"&VsDivision="
        )
        logger.debug(f"Fetching NBA.com advanced team stats for {season}")

        if HAS_CURL_CFFI:
            return await self._request_stats_impersonated(url)

        logger.warning(
            "curl_cffi not installed — falling back to aiohttp for stats.nba.com "
            "(likely to be blocked by TLS fingerprinting)"
        )
        return await self._request_stats(url)

    @retry(
        retry=retry_if_exception_type(aiohttp.ClientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
    )
    async def _request_stats(self, url: str) -> dict[str, Any]:
        """Make a request to stats.nba.com with extended timeout and headers.

        stats.nba.com requires specific headers and returns large payloads
        that may take 30+ seconds.
        """
        async with self._rate_limiter:
            timeout = aiohttp.ClientTimeout(total=45)
            session = await self._get_session()

            try:
                async with session.get(url, timeout=timeout) as response:
                    if response.status >= 400:
                        self._consecutive_failures += 1
                        raise NBAClientError(
                            f"HTTP {response.status}: {await response.text()}"
                        )

                    self._consecutive_failures = 0
                    return await response.json(content_type=None)

            except aiohttp.ClientError as e:
                self._consecutive_failures += 1
                logger.error(f"stats.nba.com request failed: {e}")
                raise

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
    )
    async def _request_stats_impersonated(self, url: str) -> dict[str, Any]:
        """Make a TLS-impersonated request to stats.nba.com via curl_cffi.

        Bypasses Akamai bot detection by reproducing Chrome's TLS fingerprint.
        Same retry/rate-limit/error-tracking pattern as _request_stats().
        """
        async with self._rate_limiter:
            session = await self._get_curl_session()

            try:
                response = await session.get(url)

                if response.status_code >= 400:
                    self._consecutive_failures += 1
                    raise NBAClientError(
                        f"HTTP {response.status_code}: {response.text}"
                    )

                self._consecutive_failures = 0
                return response.json()

            except (ConnectionError, TimeoutError, OSError) as e:
                self._consecutive_failures += 1
                logger.error(f"stats.nba.com curl_cffi request failed: {e}")
                raise
