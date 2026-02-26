"""Caching layer for NBA data."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Generic, Optional, TypeVar

from cachetools import TTLCache

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CacheConfig:
    """Configuration for cache TTLs."""

    # Live data (frequently updated)
    live_game_state_ttl: int = 15  # seconds
    scoreboard_ttl: int = 30  # seconds

    # Semi-static data
    team_stats_ttl: int = 3600  # 1 hour
    standings_ttl: int = 3600  # 1 hour
    team_context_ttl: int = 300  # 5 minutes (matches injuries TTL)
    injuries_ttl: int = 300  # 5 minutes

    # Static data
    team_info_ttl: int = 86400  # 24 hours

    # Polymarket data
    polymarket_markets_ttl: int = 300  # 5 minutes - discovered markets list
    polymarket_prices_ttl: int = 15  # 15 seconds - real-time prices
    polymarket_mappings_ttl: int = 300  # 5 minutes - game-to-market mappings


class CacheEntry(Generic[T]):
    """A cache entry with value and timestamp."""

    def __init__(self, value: T, ttl: int):
        self.value = value
        self.created_at = datetime.now()
        self.ttl = ttl

    @property
    def is_expired(self) -> bool:
        """Check if entry is expired."""
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed > self.ttl


class DataCache:
    """Multi-layer cache for NBA data with configurable TTLs."""

    def __init__(self, config: Optional[CacheConfig] = None):
        """Initialize the cache.

        Args:
            config: Optional cache configuration
        """
        self._config = config or CacheConfig()

        # Separate caches for different data types
        self._game_state_cache: TTLCache = TTLCache(
            maxsize=50, ttl=self._config.live_game_state_ttl
        )
        self._scoreboard_cache: TTLCache = TTLCache(
            maxsize=10, ttl=self._config.scoreboard_ttl
        )
        self._team_stats_cache: TTLCache = TTLCache(
            maxsize=50, ttl=self._config.team_stats_ttl
        )
        self._standings_cache: TTLCache = TTLCache(
            maxsize=5, ttl=self._config.standings_ttl
        )
        self._team_context_cache: TTLCache = TTLCache(
            maxsize=50, ttl=self._config.team_context_ttl
        )
        self._injuries_cache: TTLCache = TTLCache(
            maxsize=5, ttl=self._config.injuries_ttl
        )

        # Polymarket caches
        self._polymarket_markets_cache: TTLCache = TTLCache(
            maxsize=100, ttl=self._config.polymarket_markets_ttl
        )
        self._polymarket_prices_cache: TTLCache = TTLCache(
            maxsize=50, ttl=self._config.polymarket_prices_ttl
        )
        self._polymarket_mappings_cache: TTLCache = TTLCache(
            maxsize=50, ttl=self._config.polymarket_mappings_ttl
        )

        # Stats tracking
        self._hits = 0
        self._misses = 0

    def _get_cache_for_type(self, cache_type: str) -> TTLCache:
        """Get the appropriate cache for a data type."""
        caches = {
            "game_state": self._game_state_cache,
            "scoreboard": self._scoreboard_cache,
            "team_stats": self._team_stats_cache,
            "standings": self._standings_cache,
            "team_context": self._team_context_cache,
            "injuries": self._injuries_cache,
            "polymarket_markets": self._polymarket_markets_cache,
            "polymarket_prices": self._polymarket_prices_cache,
            "polymarket_mappings": self._polymarket_mappings_cache,
        }
        return caches.get(cache_type, self._scoreboard_cache)

    def get(self, cache_type: str, key: str) -> Optional[Any]:
        """Get a value from cache.

        Args:
            cache_type: Type of cache (game_state, scoreboard, etc.)
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        cache = self._get_cache_for_type(cache_type)
        value = cache.get(key)

        if value is not None:
            self._hits += 1
            logger.debug(f"Cache hit: {cache_type}/{key}")
            return value

        self._misses += 1
        logger.debug(f"Cache miss: {cache_type}/{key}")
        return None

    def set(self, cache_type: str, key: str, value: Any) -> None:
        """Set a value in cache.

        Args:
            cache_type: Type of cache
            key: Cache key
            value: Value to cache
        """
        cache = self._get_cache_for_type(cache_type)
        cache[key] = value
        logger.debug(f"Cache set: {cache_type}/{key}")

    def invalidate(self, cache_type: str, key: str) -> None:
        """Invalidate a specific cache entry.

        Args:
            cache_type: Type of cache
            key: Cache key
        """
        cache = self._get_cache_for_type(cache_type)
        if key in cache:
            del cache[key]
            logger.debug(f"Cache invalidated: {cache_type}/{key}")

    def invalidate_all(self, cache_type: Optional[str] = None) -> None:
        """Invalidate all entries in a cache or all caches.

        Args:
            cache_type: Optional specific cache to clear
        """
        if cache_type:
            cache = self._get_cache_for_type(cache_type)
            cache.clear()
            logger.debug(f"Cache cleared: {cache_type}")
        else:
            self._game_state_cache.clear()
            self._scoreboard_cache.clear()
            self._team_stats_cache.clear()
            self._standings_cache.clear()
            self._team_context_cache.clear()
            self._injuries_cache.clear()
            self._polymarket_markets_cache.clear()
            self._polymarket_prices_cache.clear()
            self._polymarket_mappings_cache.clear()
            logger.debug("All caches cleared")

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self.hit_rate,
            "game_state_size": len(self._game_state_cache),
            "scoreboard_size": len(self._scoreboard_cache),
            "team_stats_size": len(self._team_stats_cache),
            "polymarket_markets_size": len(self._polymarket_markets_cache),
            "polymarket_prices_size": len(self._polymarket_prices_cache),
            "polymarket_mappings_size": len(self._polymarket_mappings_cache),
        }

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self._hits = 0
        self._misses = 0


async def cached(
    cache: DataCache,
    cache_type: str,
    key: str,
    fetch_func: Callable[[], Any],
) -> Any:
    """Helper to get cached data or fetch if missing.

    Args:
        cache: DataCache instance
        cache_type: Type of cache
        key: Cache key
        fetch_func: Async function to fetch data if not cached

    Returns:
        Cached or freshly fetched data
    """
    # Try cache first
    cached_value = cache.get(cache_type, key)
    if cached_value is not None:
        return cached_value

    # Fetch fresh data
    value = await fetch_func()

    # Cache the result if valid
    if value is not None:
        cache.set(cache_type, key, value)

    return value
