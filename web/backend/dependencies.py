"""Singleton service holders and FastAPI dependency callables.

Services are initialised once at application startup via ``init_services()``
and torn down via ``shutdown_services()``.  Individual routers obtain
references through the ``Depends()`` callables at the bottom of this module.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

from polynba.data.manager import DataManager
from polynba.polymarket.market_discovery import MarketDiscovery
from polynba.polymarket.price_fetcher import PriceFetcher
from polynba.trading.executor import PaperTradingExecutor, TradingExecutor

from .config import IS_LIVE_MODE, POLYMARKET_PRIVATE_KEY

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Module-level state dict — populated during lifespan startup.
_state: dict = {}


async def init_services() -> None:
    """Initialise all long-lived service singletons.

    Called once from the FastAPI lifespan context manager before the app
    starts accepting requests.
    """
    logger.info("Initialising PolyNBA backend services...")

    _state["data_manager"] = DataManager()
    _state["market_discovery"] = MarketDiscovery()
    _state["price_fetcher"] = PriceFetcher()

    if IS_LIVE_MODE:
        from polynba.trading.executor import LiveTradingExecutor

        funder = __import__("os").environ.get("POLYMARKET_FUNDER_ADDRESS")
        _state["executor"] = LiveTradingExecutor(
            private_key=POLYMARKET_PRIVATE_KEY,  # type: ignore[arg-type]
            funder=funder,
        )
        logger.info("Trading executor: LIVE mode (Polygon mainnet)")
    else:
        _state["executor"] = PaperTradingExecutor(initial_balance=Decimal("1000"))
        logger.info("Trading executor: PAPER mode (simulated)")

    logger.info("All services initialised.")


async def shutdown_services() -> None:
    """Gracefully close all service resources.

    Called from the FastAPI lifespan context manager on shutdown.
    """
    logger.info("Shutting down PolyNBA backend services...")

    if "data_manager" in _state:
        await _state["data_manager"].close()

    if "market_discovery" in _state:
        await _state["market_discovery"].close()

    _state.clear()
    logger.info("All services shut down.")


# ---------------------------------------------------------------------------
# FastAPI dependency callables
# ---------------------------------------------------------------------------


def _require(key: str, label: str):
    """Raise HTTP 503 if the requested service has not been initialised."""
    svc = _state.get(key)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{label} service is not available.",
        )
    return svc


def get_data_manager() -> DataManager:
    """FastAPI dependency: returns the shared DataManager instance."""
    return _require("data_manager", "DataManager")


def get_market_discovery() -> MarketDiscovery:
    """FastAPI dependency: returns the shared MarketDiscovery instance."""
    return _require("market_discovery", "MarketDiscovery")


def get_price_fetcher() -> PriceFetcher:
    """FastAPI dependency: returns the shared PriceFetcher instance."""
    return _require("price_fetcher", "PriceFetcher")


def get_executor() -> TradingExecutor:
    """FastAPI dependency: returns the shared TradingExecutor instance."""
    return _require("executor", "TradingExecutor")
