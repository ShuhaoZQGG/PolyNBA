"""Polygon gas estimation and management."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class GasPrice:
    """Gas price information."""

    safe_low: Decimal  # Gwei
    standard: Decimal
    fast: Decimal
    fastest: Decimal
    base_fee: Optional[Decimal] = None
    timestamp: Optional[float] = None


@dataclass
class GasEstimate:
    """Gas cost estimate for a transaction."""

    gas_limit: int
    gas_price_gwei: Decimal
    total_cost_matic: Decimal
    total_cost_usd: Optional[Decimal] = None


class GasManager:
    """Manages Polygon gas estimation and pricing."""

    # Polygon gas station API
    GAS_STATION_URL = "https://gasstation.polygon.technology/v2"

    # Typical gas limits for Polymarket operations
    GAS_LIMITS = {
        "approve": 50_000,
        "place_order": 150_000,
        "cancel_order": 100_000,
        "fill_order": 200_000,
    }

    def __init__(
        self,
        rpc_url: str = "https://polygon-rpc.com",
        max_gas_price_gwei: Decimal = Decimal("500"),
    ):
        """Initialize gas manager.

        Args:
            rpc_url: Polygon RPC endpoint
            max_gas_price_gwei: Maximum gas price to use
        """
        self._rpc_url = rpc_url
        self._max_gas_price = max_gas_price_gwei
        self._session: Optional[aiohttp.ClientSession] = None
        self._cached_price: Optional[GasPrice] = None
        self._matic_price_usd: Decimal = Decimal("0.50")  # Default, should be updated

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_gas_price(self, force_refresh: bool = False) -> GasPrice:
        """Get current gas prices from Polygon gas station.

        Args:
            force_refresh: Force refresh from API

        Returns:
            GasPrice with current rates
        """
        if self._cached_price and not force_refresh:
            return self._cached_price

        try:
            session = await self._get_session()

            async with session.get(self.GAS_STATION_URL) as response:
                if response.status != 200:
                    raise Exception(f"Gas station API error: {response.status}")

                data = await response.json()

                gas_price = GasPrice(
                    safe_low=Decimal(str(data.get("safeLow", {}).get("maxFee", 30))),
                    standard=Decimal(str(data.get("standard", {}).get("maxFee", 50))),
                    fast=Decimal(str(data.get("fast", {}).get("maxFee", 100))),
                    fastest=Decimal(str(data.get("fast", {}).get("maxFee", 200))),
                    base_fee=Decimal(str(data.get("estimatedBaseFee", 30))),
                )

                self._cached_price = gas_price
                return gas_price

        except Exception as e:
            logger.warning(f"Failed to get gas price: {e}, using defaults")
            return GasPrice(
                safe_low=Decimal("30"),
                standard=Decimal("50"),
                fast=Decimal("100"),
                fastest=Decimal("200"),
            )

    async def estimate_gas_cost(
        self,
        operation: str,
        priority: str = "standard",
    ) -> GasEstimate:
        """Estimate gas cost for an operation.

        Args:
            operation: Operation type (approve, place_order, etc.)
            priority: Gas priority (safe_low, standard, fast, fastest)

        Returns:
            GasEstimate with cost breakdown
        """
        gas_limit = self.GAS_LIMITS.get(operation, 150_000)
        gas_price = await self.get_gas_price()

        price_map = {
            "safe_low": gas_price.safe_low,
            "standard": gas_price.standard,
            "fast": gas_price.fast,
            "fastest": gas_price.fastest,
        }

        gas_price_gwei = price_map.get(priority, gas_price.standard)

        # Cap at max
        if gas_price_gwei > self._max_gas_price:
            gas_price_gwei = self._max_gas_price

        # Calculate cost in MATIC
        # Cost = gas_limit * gas_price_gwei * 1e-9 (convert gwei to MATIC)
        cost_matic = Decimal(gas_limit) * gas_price_gwei / Decimal("1000000000")

        # Convert to USD
        cost_usd = cost_matic * self._matic_price_usd

        return GasEstimate(
            gas_limit=gas_limit,
            gas_price_gwei=gas_price_gwei,
            total_cost_matic=cost_matic,
            total_cost_usd=cost_usd,
        )

    async def update_matic_price(self, price_usd: Decimal) -> None:
        """Update MATIC price for USD conversions.

        Args:
            price_usd: Current MATIC price in USD
        """
        self._matic_price_usd = price_usd

    def is_gas_acceptable(
        self,
        gas_price_gwei: Decimal,
        trade_value_usd: Decimal,
        max_gas_percent: float = 5.0,
    ) -> bool:
        """Check if gas cost is acceptable relative to trade value.

        Args:
            gas_price_gwei: Current gas price
            trade_value_usd: Value of the trade in USD
            max_gas_percent: Maximum acceptable gas as % of trade

        Returns:
            True if gas is acceptable
        """
        # Estimate cost for a typical order
        gas_limit = self.GAS_LIMITS["place_order"]
        cost_matic = Decimal(gas_limit) * gas_price_gwei / Decimal("1000000000")
        cost_usd = cost_matic * self._matic_price_usd

        if trade_value_usd == 0:
            return False

        gas_percent = float(cost_usd / trade_value_usd * 100)
        return gas_percent <= max_gas_percent

    async def wait_for_lower_gas(
        self,
        target_gwei: Decimal,
        timeout_seconds: int = 300,
        check_interval: int = 30,
    ) -> bool:
        """Wait for gas price to drop below target.

        Args:
            target_gwei: Target gas price
            timeout_seconds: Maximum wait time
            check_interval: Seconds between checks

        Returns:
            True if target reached, False if timeout
        """
        import asyncio

        elapsed = 0
        while elapsed < timeout_seconds:
            gas_price = await self.get_gas_price(force_refresh=True)

            if gas_price.standard <= target_gwei:
                return True

            logger.info(
                f"Gas price {gas_price.standard} > target {target_gwei}, "
                f"waiting... ({elapsed}/{timeout_seconds}s)"
            )

            await asyncio.sleep(check_interval)
            elapsed += check_interval

        return False

    @property
    def stats(self) -> dict:
        """Get gas manager statistics."""
        return {
            "cached_standard_gwei": float(self._cached_price.standard) if self._cached_price else None,
            "matic_price_usd": float(self._matic_price_usd),
            "max_gas_gwei": float(self._max_gas_price),
        }
