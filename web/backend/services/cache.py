"""Simple async TTL cache for cross-request caching of external API results."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class TTLCache:
    """Async-safe in-memory cache with per-key TTL expiry.

    Usage::

        cache = TTLCache(ttl_seconds=300)
        result = await cache.get_or_fetch("key", lambda: some_async_fn())
    """

    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def get_or_fetch(
        self, key: str, fetch_fn: Callable[[], Awaitable[Any]]
    ) -> Any:
        """Return cached value if fresh, otherwise call *fetch_fn* and cache."""
        # Fast path: check without lock
        entry = self._store.get(key)
        if entry is not None:
            ts, value = entry
            if time.monotonic() - ts < self._ttl:
                return value

        # Get per-key lock to avoid thundering herd
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            lock = self._locks[key]

        async with lock:
            # Re-check after acquiring lock (another coroutine may have populated)
            entry = self._store.get(key)
            if entry is not None:
                ts, value = entry
                if time.monotonic() - ts < self._ttl:
                    return value

            value = await fetch_fn()
            self._store[key] = (time.monotonic(), value)
            return value

    def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()


# ---------------------------------------------------------------------------
# Shared cache instances (initialised at import time)
# ---------------------------------------------------------------------------

market_info_cache = TTLCache(ttl_seconds=300)        # 5 minutes
matched_markets_cache = TTLCache(ttl_seconds=30)     # 30 seconds — matches frontend refetchInterval
trade_history_cache = TTLCache(ttl_seconds=30)       # 30 seconds
balance_cache = TTLCache(ttl_seconds=15)             # 15 seconds
