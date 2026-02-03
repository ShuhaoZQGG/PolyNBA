"""Market discovery via Polymarket Gamma API."""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import aiohttp

from .models import GammaMarketResponse, PolymarketNBAMarket

logger = logging.getLogger(__name__)

# NBA Series ID on Polymarket
NBA_SERIES_ID = "10345"

# Common NBA team name patterns for extraction
NBA_TEAMS = {
    # Full names
    "atlanta hawks": "ATL",
    "boston celtics": "BOS",
    "brooklyn nets": "BKN",
    "charlotte hornets": "CHA",
    "chicago bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",
    "denver nuggets": "DEN",
    "detroit pistons": "DET",
    "golden state warriors": "GSW",
    "houston rockets": "HOU",
    "indiana pacers": "IND",
    "los angeles clippers": "LAC",
    "los angeles lakers": "LAL",
    "la clippers": "LAC",
    "la lakers": "LAL",
    "memphis grizzlies": "MEM",
    "miami heat": "MIA",
    "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "new orleans pelicans": "NOP",
    "new york knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX",
    "portland trail blazers": "POR",
    "sacramento kings": "SAC",
    "san antonio spurs": "SAS",
    "toronto raptors": "TOR",
    "utah jazz": "UTA",
    "washington wizards": "WAS",
    # Short names (used in Polymarket)
    "hawks": "ATL",
    "celtics": "BOS",
    "nets": "BKN",
    "hornets": "CHA",
    "bulls": "CHI",
    "cavaliers": "CLE",
    "cavs": "CLE",
    "mavericks": "DAL",
    "mavs": "DAL",
    "nuggets": "DEN",
    "pistons": "DET",
    "warriors": "GSW",
    "rockets": "HOU",
    "pacers": "IND",
    "clippers": "LAC",
    "lakers": "LAL",
    "grizzlies": "MEM",
    "heat": "MIA",
    "bucks": "MIL",
    "timberwolves": "MIN",
    "wolves": "MIN",
    "pelicans": "NOP",
    "knicks": "NYK",
    "thunder": "OKC",
    "magic": "ORL",
    "76ers": "PHI",
    "sixers": "PHI",
    "suns": "PHX",
    "trail blazers": "POR",
    "blazers": "POR",
    "kings": "SAC",
    "spurs": "SAS",
    "raptors": "TOR",
    "jazz": "UTA",
    "wizards": "WAS",
}


class MarketDiscovery:
    """Discovers NBA markets from Polymarket Gamma API."""

    def __init__(
        self,
        gamma_api_url: str = "https://gamma-api.polymarket.com",
        cache_ttl_seconds: int = 300,
    ):
        """Initialize market discovery.

        Args:
            gamma_api_url: Base URL for Gamma API
            cache_ttl_seconds: How long to cache market list
        """
        self._gamma_api_url = gamma_api_url
        self._cache_ttl = cache_ttl_seconds
        self._cached_markets: list[PolymarketNBAMarket] = []
        self._cache_expires: Optional[datetime] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def discover_nba_markets(
        self,
        force_refresh: bool = False,
    ) -> list[PolymarketNBAMarket]:
        """Discover active NBA game markets from the NBA series.

        Args:
            force_refresh: Force refresh even if cache is valid

        Returns:
            List of NBA game markets (moneyline only)
        """
        # Check cache
        if not force_refresh and self._is_cache_valid():
            logger.debug(f"Using cached markets ({len(self._cached_markets)} markets)")
            return self._cached_markets

        logger.info("Fetching NBA markets from Gamma API (series endpoint)")

        try:
            # Fetch NBA series data
            series_data = await self._fetch_nba_series()
            if not series_data:
                logger.warning("Could not fetch NBA series data")
                return self._cached_markets if self._cached_markets else []

            events = series_data.get("events", [])
            logger.info(f"NBA series has {len(events)} events")

            # Filter for active games and fetch full details
            nba_markets = await self._process_nba_events(events)

            # Update cache
            self._cached_markets = nba_markets
            self._cache_expires = datetime.now() + timedelta(seconds=self._cache_ttl)

            logger.info(f"Discovered {len(nba_markets)} NBA game markets")
            return nba_markets

        except Exception as e:
            logger.error(f"Error discovering markets: {e}")
            # Return cached data if available
            if self._cached_markets:
                logger.warning("Returning stale cached markets")
                return self._cached_markets
            return []

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self._cached_markets or not self._cache_expires:
            return False
        return datetime.now() < self._cache_expires

    async def _fetch_nba_series(self) -> Optional[dict]:
        """Fetch NBA series data from Gamma API."""
        session = await self._get_session()

        url = f"{self._gamma_api_url}/series/{NBA_SERIES_ID}"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Gamma API series endpoint returned status {response.status}")
                    return None
                return await response.json()
        except Exception as e:
            logger.error(f"Error fetching NBA series: {e}")
            return None

    async def _fetch_event_details(self, event_id: str) -> Optional[dict]:
        """Fetch full event details including markets.

        Args:
            event_id: The event ID to fetch

        Returns:
            Full event data with markets, or None on error
        """
        session = await self._get_session()

        url = f"{self._gamma_api_url}/events/{event_id}"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.debug(f"Could not fetch event {event_id}: status {response.status}")
                    return None
                return await response.json()
        except Exception as e:
            logger.debug(f"Error fetching event {event_id}: {e}")
            return None

    async def _process_nba_events(
        self,
        events: list[dict],
    ) -> list[PolymarketNBAMarket]:
        """Process NBA events and extract moneyline markets.

        Args:
            events: List of events from series data

        Returns:
            List of PolymarketNBAMarket objects
        """
        nba_markets = []
        today = datetime.now().date()
        cutoff = today + timedelta(days=3)  # Look 3 days ahead

        for event in events:
            # Skip closed events
            if event.get("closed", True):
                continue

            # Check event date
            end_date_str = event.get("endDate", "")
            if not end_date_str:
                continue

            try:
                game_date = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                ).date()
                if game_date < today or game_date > cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            # Fetch full event details to get markets
            event_id = event.get("id")
            if not event_id:
                continue

            full_event = await self._fetch_event_details(str(event_id))
            if not full_event:
                continue

            # Find the moneyline market
            market = self._find_moneyline_market(full_event)
            if market:
                nba_markets.append(market)
                logger.debug(
                    f"Found game market: {market.home_team_name} vs {market.away_team_name} "
                    f"(condition_id={market.condition_id[:20]}...)"
                )

        return nba_markets

    def _find_moneyline_market(
        self,
        event: dict,
    ) -> Optional[PolymarketNBAMarket]:
        """Find the moneyline (game winner) market in an event.

        The moneyline market has a question like "Rockets vs. Pacers"
        without spread/points/props.

        Args:
            event: Full event data

        Returns:
            PolymarketNBAMarket or None
        """
        title = event.get("title", "")
        markets = event.get("markets", [])

        if not markets:
            return None

        # Parse event title to get team names
        # Format: "Rockets vs. Pacers" or "Team A vs. Team B"
        teams = self._extract_teams_from_title(title)
        if not teams:
            return None

        away_team, home_team = teams  # In Polymarket, format is "Away vs. Home"

        # Find the moneyline market
        # It's the one where question matches title exactly or closely
        for m in markets:
            question = m.get("question", "")

            # Moneyline market question is exactly "{Team A} vs. {Team B}"
            # without spread, points, or player names
            if not self._is_moneyline_market(question, title):
                continue

            # Parse market data
            outcomes_raw = m.get("outcomes", "")
            prices_raw = m.get("outcomePrices", "")
            clob_tokens_raw = m.get("clobTokenIds", "")
            condition_id = m.get("conditionId", "")

            if not condition_id:
                continue

            # Parse JSON arrays
            outcomes = self._parse_json_array(outcomes_raw)
            prices = self._parse_json_array(prices_raw)
            tokens = self._parse_json_array(clob_tokens_raw)

            if len(outcomes) != 2 or len(tokens) != 2:
                continue

            # Determine which token is home vs away
            # Outcomes are in order [Away, Home] based on title "Away vs. Home"
            away_token_id = tokens[0]
            home_token_id = tokens[1]

            # Parse end date
            end_date = None
            end_date_str = event.get("endDate")
            if end_date_str:
                try:
                    end_date = datetime.fromisoformat(
                        end_date_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            # Parse prices (price per share, 0-1 range)
            from decimal import Decimal
            try:
                away_price = Decimal(str(prices[0])) if prices else None
                home_price = Decimal(str(prices[1])) if len(prices) > 1 else None
            except (ValueError, TypeError, IndexError):
                away_price, home_price = None, None

            return PolymarketNBAMarket(
                condition_id=condition_id,
                question_id=m.get("id", ""),
                slug=m.get("slug", ""),
                question=question,
                home_token_id=home_token_id,
                away_token_id=away_token_id,
                home_team_name=home_team,
                away_team_name=away_team,
                active=not event.get("closed", False),
                closed=event.get("closed", False),
                end_date=end_date,
                liquidity=event.get("liquidity", 0),
                volume=event.get("volume", 0),
                home_price=home_price,
                away_price=away_price,
            )

        return None

    def _is_moneyline_market(self, question: str, title: str) -> bool:
        """Check if a market question is the moneyline market.

        Args:
            question: Market question text
            title: Event title

        Returns:
            True if this is the moneyline market
        """
        # Clean up for comparison
        q = question.lower().strip()
        t = title.lower().strip()

        # Exact match
        if q == t:
            return True

        # Check it's not a spread/prop market
        exclude_keywords = [
            "spread", "o/u", "over", "under", "points",
            "rebounds", "assists", "3-pointers", "3pt",
            "1h", "1q", "2h", "2q", "3q", "4q",
            "moneyline",  # "1H Moneyline" is not full game
        ]

        for kw in exclude_keywords:
            if kw in q:
                return False

        # Check it has "vs" or "vs."
        if "vs" not in q:
            return False

        # Check it has team names from title
        title_words = set(t.replace("vs.", "vs").replace(".", "").split())
        question_words = set(q.replace("vs.", "vs").replace(".", "").split())

        # Should have significant overlap
        common = title_words & question_words
        return len(common) >= 2

    def _extract_teams_from_title(
        self,
        title: str,
    ) -> Optional[tuple[str, str]]:
        """Extract team names from event title.

        Format: "Rockets vs. Pacers" -> ("Rockets", "Pacers")
        Returns (away_team, home_team) - Polymarket uses "Away vs. Home"

        Args:
            title: Event title

        Returns:
            Tuple of (away_team, home_team) or None
        """
        # Pattern: "Team A vs. Team B"
        match = re.match(
            r"(.+?)\s+vs\.?\s+(.+)",
            title.strip(),
            re.IGNORECASE,
        )
        if match:
            away = match.group(1).strip()
            home = match.group(2).strip()
            return (away, home)

        return None

    def _parse_json_array(self, value) -> list:
        """Parse a value that might be JSON string or already a list."""
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    def get_team_abbreviation(self, team_name: str) -> Optional[str]:
        """Get NBA team abbreviation from name.

        Args:
            team_name: Team name (any format)

        Returns:
            3-letter abbreviation or None
        """
        name_lower = team_name.lower().strip()

        # Direct match
        if name_lower in NBA_TEAMS:
            return NBA_TEAMS[name_lower]

        # Partial match
        for full_name, abbr in NBA_TEAMS.items():
            if full_name in name_lower or name_lower in full_name:
                return abbr

        return None

    async def discover_upcoming_nba_markets(
        self,
        days_ahead: int = 2,
        force_refresh: bool = False,
    ) -> dict[str, list[PolymarketNBAMarket]]:
        """Discover NBA markets for upcoming games within specified days.

        Groups markets by date (today, tomorrow, future).

        Args:
            days_ahead: How many days ahead to look (default 2)
            force_refresh: Force refresh even if cache is valid

        Returns:
            Dict with keys 'today', 'tomorrow', 'future' mapping to market lists
        """
        all_markets = await self.discover_nba_markets(force_refresh=force_refresh)

        now = datetime.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)
        cutoff = today + timedelta(days=days_ahead)

        result = {
            "today": [],
            "tomorrow": [],
            "future": [],
            "unknown": [],
        }

        for market in all_markets:
            if market.end_date is None:
                result["unknown"].append(market)
                continue

            market_date = market.end_date.date()

            if market_date < today:
                continue
            elif market_date == today:
                result["today"].append(market)
            elif market_date == tomorrow:
                result["tomorrow"].append(market)
            elif market_date <= cutoff:
                result["future"].append(market)

        return result

    async def log_market_summary(
        self,
        days_ahead: int = 2,
        force_refresh: bool = True,
    ) -> dict[str, list[PolymarketNBAMarket]]:
        """Discover and log summary of NBA markets for verification.

        Args:
            days_ahead: How many days ahead to look
            force_refresh: Force refresh from API

        Returns:
            Dict of markets grouped by date
        """
        logger.info("=" * 60)
        logger.info("POLYMARKET NBA GAME MARKETS - VERIFICATION")
        logger.info("=" * 60)

        try:
            markets_by_date = await self.discover_upcoming_nba_markets(
                days_ahead=days_ahead,
                force_refresh=force_refresh,
            )

            total_markets = sum(len(m) for m in markets_by_date.values())
            logger.info(f"Total NBA game markets found: {total_markets}")
            logger.info("")

            # Log today's markets
            today_markets = markets_by_date.get("today", [])
            logger.info(f"TODAY's GAMES ({len(today_markets)} markets):")
            if today_markets:
                for market in today_markets:
                    home_abbr = self.get_team_abbreviation(market.home_team_name) or "???"
                    away_abbr = self.get_team_abbreviation(market.away_team_name) or "???"
                    home_price_str = f"${float(market.home_price):.2f}" if market.home_price else "N/A"
                    away_price_str = f"${float(market.away_price):.2f}" if market.away_price else "N/A"
                    logger.info(
                        f"  {away_abbr} @ {home_abbr} | "
                        f"{home_abbr}: {home_price_str}/share, {away_abbr}: {away_price_str}/share | "
                        f"Vol: ${float(market.volume):,.0f}"
                    )
            else:
                logger.info("  (no markets)")
            logger.info("")

            # Log tomorrow's markets
            tomorrow_markets = markets_by_date.get("tomorrow", [])
            logger.info(f"TOMORROW's GAMES ({len(tomorrow_markets)} markets):")
            if tomorrow_markets:
                for market in tomorrow_markets:
                    home_abbr = self.get_team_abbreviation(market.home_team_name) or "???"
                    away_abbr = self.get_team_abbreviation(market.away_team_name) or "???"
                    home_price_str = f"${float(market.home_price):.2f}" if market.home_price else "N/A"
                    away_price_str = f"${float(market.away_price):.2f}" if market.away_price else "N/A"
                    logger.info(
                        f"  {away_abbr} @ {home_abbr} | "
                        f"{home_abbr}: {home_price_str}/share, {away_abbr}: {away_price_str}/share | "
                        f"Vol: ${float(market.volume):,.0f}"
                    )
            else:
                logger.info("  (no markets)")
            logger.info("")

            # Log future markets
            future_markets = markets_by_date.get("future", [])
            logger.info(f"FUTURE GAMES (+2 days, {len(future_markets)} markets):")
            if future_markets:
                for market in future_markets[:5]:
                    home_abbr = self.get_team_abbreviation(market.home_team_name) or "???"
                    away_abbr = self.get_team_abbreviation(market.away_team_name) or "???"
                    end_date = market.end_date.strftime("%Y-%m-%d") if market.end_date else "N/A"
                    home_price_str = f"${float(market.home_price):.2f}" if market.home_price else "N/A"
                    away_price_str = f"${float(market.away_price):.2f}" if market.away_price else "N/A"
                    logger.info(
                        f"  [{end_date}] {away_abbr} @ {home_abbr} | "
                        f"{home_abbr}: {home_price_str}, {away_abbr}: {away_price_str}"
                    )
                if len(future_markets) > 5:
                    logger.info(f"  ... and {len(future_markets) - 5} more")
            else:
                logger.info("  (no markets)")
            logger.info("")
            logger.info("=" * 60)

            return markets_by_date

        except Exception as e:
            logger.error(f"Error during market discovery verification: {e}")
            logger.info("=" * 60)
            return {"today": [], "tomorrow": [], "future": [], "unknown": []}

    async def log_all_nba_markets(self) -> None:
        """Log all NBA markets including prices for debugging."""
        logger.info("=" * 60)
        logger.info("ALL NBA GAME MARKETS WITH PRICES")
        logger.info("=" * 60)

        markets = await self.discover_nba_markets(force_refresh=True)

        if not markets:
            logger.info("No NBA game markets found")
            logger.info("=" * 60)
            return

        logger.info(f"Found {len(markets)} NBA game markets")
        logger.info("")

        for market in markets:
            home_abbr = self.get_team_abbreviation(market.home_team_name) or "???"
            away_abbr = self.get_team_abbreviation(market.away_team_name) or "???"
            end_date = market.end_date.strftime("%Y-%m-%d %H:%M") if market.end_date else "N/A"

            home_price_str = f"${float(market.home_price):.2f}/share" if market.home_price else "N/A"
            away_price_str = f"${float(market.away_price):.2f}/share" if market.away_price else "N/A"

            logger.info(f"{away_abbr} @ {home_abbr}")
            logger.info(f"  Date: {end_date}")
            logger.info(f"  Prices: {home_abbr} {home_price_str}, {away_abbr} {away_price_str}")
            logger.info(f"  Volume: ${float(market.volume):,.2f}")
            logger.info(f"  Liquidity: ${float(market.liquidity):,.2f}")
            logger.info(f"  Condition ID: {market.condition_id[:40]}...")
            logger.info(f"  Home Token: {market.home_token_id[:40]}...")
            logger.info(f"  Away Token: {market.away_token_id[:40]}...")
            logger.info("")

        logger.info("=" * 60)
