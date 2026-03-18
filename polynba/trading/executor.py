"""Trading executor interface and implementations."""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Optional

from ..data.models import OrderStatus, TradeSide

logger = logging.getLogger(__name__)


@dataclass
class TradeHistoryEntry:
    """A single trade fill from the user's perspective."""

    market: str  # condition_id
    asset_id: str
    outcome: str
    side: str  # "BUY" or "SELL"
    size: float
    price: float
    fee_rate_bps: float
    match_time: str
    trader_side: str  # "MAKER" or "TAKER"
    status: str


@dataclass
class Order:
    """Represents a trading order."""

    order_id: str
    market_id: str
    token_id: str
    side: TradeSide
    size: Decimal  # Size in shares
    price: Decimal  # Price per share (0-1)
    status: OrderStatus = OrderStatus.PENDING
    filled_size: Decimal = Decimal("0")
    avg_fill_price: Decimal = Decimal("0")
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    strategy_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining_size(self) -> Decimal:
        """Get unfilled size."""
        return self.size - self.filled_size

    @property
    def is_complete(self) -> bool:
        """Check if order is in a terminal state."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )

    @property
    def notional_value(self) -> Decimal:
        """Get notional value of the order."""
        return self.size * self.price


@dataclass
class OrderResult:
    """Result of an order operation."""

    success: bool
    order: Optional[Order] = None
    error: Optional[str] = None
    transaction_hash: Optional[str] = None


@dataclass
class Balance:
    """Account balance information."""

    usdc: Decimal
    locked_usdc: Decimal  # USDC in open orders

    @property
    def available_usdc(self) -> Decimal:
        """Get available balance for trading."""
        return self.usdc - self.locked_usdc


@dataclass
class MarketData:
    """Market data for a Polymarket market."""

    market_id: str
    condition_id: str
    token_id: str
    question: str
    outcome: str  # "Yes" or "No"
    best_bid: Decimal
    best_ask: Decimal
    last_price: Decimal
    volume_24h: Decimal
    liquidity: Decimal
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def mid_price(self) -> Decimal:
        """Get mid price."""
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> Decimal:
        """Get bid-ask spread."""
        return self.best_ask - self.best_bid

    @property
    def spread_percentage(self) -> float:
        """Get spread as percentage of mid price."""
        mid = self.mid_price
        if mid == 0:
            return 0.0
        return float(self.spread / mid * 100)


class TradingExecutor(ABC):
    """Abstract interface for trading execution."""

    @abstractmethod
    async def place_order(
        self,
        market_id: str,
        token_id: str,
        side: TradeSide,
        size: Decimal,
        price: Decimal,
        strategy_id: Optional[str] = None,
    ) -> OrderResult:
        """Place a new order.

        Args:
            market_id: Polymarket market ID
            token_id: Token ID for the outcome
            side: Buy or sell
            size: Number of shares
            price: Price per share (0-1)
            strategy_id: Optional strategy identifier

        Returns:
            OrderResult with success status and order details
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an open order.

        Args:
            order_id: Order ID to cancel

        Returns:
            OrderResult with success status
        """
        pass

    @abstractmethod
    async def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID.

        Args:
            order_id: Order ID

        Returns:
            Order object or None if not found
        """
        pass

    @abstractmethod
    async def get_open_orders(
        self, market_id: Optional[str] = None
    ) -> list[Order]:
        """Get all open orders.

        Args:
            market_id: Optional filter by market

        Returns:
            List of open orders
        """
        pass

    @abstractmethod
    async def get_balance(self) -> Balance:
        """Get account balance.

        Returns:
            Balance object
        """
        pass

    @abstractmethod
    async def get_market_data(self, market_id: str) -> Optional[MarketData]:
        """Get current market data.

        Args:
            market_id: Market ID

        Returns:
            MarketData object or None
        """
        pass

    @abstractmethod
    async def get_positions(self) -> dict[str, Decimal]:
        """Get current positions.

        Returns:
            Dict mapping token_id to position size
        """
        pass

    async def get_trade_history(self, after_ts: Optional[int] = None) -> list[TradeHistoryEntry]:
        """Get trade history from the CLOB API.

        Returns list of user fills. Base implementation returns empty list.
        """
        return []

    async def get_market_info(self, condition_id: str) -> Optional[dict]:
        """Fetch market metadata (question, resolution status, winner).

        Returns raw market dict or None. Base implementation returns None.
        """
        return None


class PaperTradingExecutor(TradingExecutor):
    """Paper trading executor for simulation.

    Simulates trading against real orderbook data without
    executing actual trades.
    """

    def __init__(
        self,
        initial_balance: Decimal = Decimal("1000"),
        slippage_bps: int = 10,  # 0.1% slippage simulation
        live_price_source: Optional["Callable[[str], Optional[MarketData]]"] = None,
    ):
        """Initialize paper trading executor.

        Args:
            initial_balance: Starting USDC balance
            slippage_bps: Simulated slippage in basis points
            live_price_source: Optional callable that returns fresh MarketData
                for a given token_id. When set, get_market_data() calls this
                instead of returning static cache, enabling price evolution
                during order delay checks.
        """
        self._balance = initial_balance
        self._locked_balance = Decimal("0")
        self._slippage_bps = slippage_bps
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Decimal] = {}
        self._order_counter = 0
        self._market_data_cache: dict[str, MarketData] = {}
        self._live_price_source = live_price_source

    def set_market_data(self, market_id: str, data: MarketData) -> None:
        """Set market data for simulation.

        Args:
            market_id: Market ID
            data: Market data to use
        """
        self._market_data_cache[market_id] = data

    async def place_order(
        self,
        market_id: str,
        token_id: str,
        side: TradeSide,
        size: Decimal,
        price: Decimal,
        strategy_id: Optional[str] = None,
    ) -> OrderResult:
        """Place a simulated order."""
        self._order_counter += 1
        order_id = f"paper_{self._order_counter}"

        # Check balance
        required = size * price
        if side == TradeSide.BUY and required > (self._balance - self._locked_balance):
            return OrderResult(
                success=False,
                error="Insufficient balance",
            )

        # Check position for sells
        if side == TradeSide.SELL:
            position = self._positions.get(token_id, Decimal("0"))
            if size > position:
                return OrderResult(
                    success=False,
                    error="Insufficient position",
                )

        # Create order
        order = Order(
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            size=size,
            price=price,
            status=OrderStatus.OPEN,
            strategy_id=strategy_id,
        )

        self._orders[order_id] = order

        # Lock funds
        if side == TradeSide.BUY:
            self._locked_balance += required

        # Simulate immediate fill for market-crossing orders
        market_data = self._market_data_cache.get(market_id)
        if not market_data:
            market_data = self._market_data_cache.get(token_id)
        if market_data:
            fill_price = self._simulate_fill(order, market_data)
            if fill_price:
                await self._execute_fill(order, fill_price)

        logger.info(
            f"Paper order placed: {order_id} {side.value} {size} @ {price}"
        )

        return OrderResult(success=True, order=order)

    def _simulate_fill(
        self, order: Order, market_data: MarketData
    ) -> Optional[Decimal]:
        """Simulate order fill based on market data."""
        slippage = Decimal(self._slippage_bps) / Decimal("10000")

        if order.side == TradeSide.BUY:
            # Buy at or above ask
            if order.price >= market_data.best_ask:
                return market_data.best_ask * (1 + slippage)
        else:
            # Sell at or below bid
            if order.price <= market_data.best_bid:
                return market_data.best_bid * (1 - slippage)

        return None

    def _simulate_fill_at_mid(
        self, order: Order, market_data: MarketData
    ) -> Optional[Decimal]:
        """Simulate a fill at mid price (paper mode fallback)."""
        mid = market_data.mid_price
        if mid == 0:
            return None

        slippage = Decimal(self._slippage_bps) / Decimal("10000")

        if order.side == TradeSide.BUY:
            if order.price >= mid:
                return mid * (1 + slippage)
        else:
            if order.price <= mid:
                return mid * (1 - slippage)

        return None

    async def _execute_fill(self, order: Order, fill_price: Decimal) -> None:
        """Execute a simulated fill."""
        order.updated_at = datetime.now()

        if order.side == TradeSide.BUY:
            order.filled_size = order.size
            order.avg_fill_price = fill_price
            order.status = OrderStatus.FILLED
            cost = order.size * fill_price
            self._balance -= cost
            self._locked_balance -= order.size * order.price
            current = self._positions.get(order.token_id, Decimal("0"))
            self._positions[order.token_id] = current + order.size
        else:
            current = self._positions.get(order.token_id, Decimal("0"))
            fill_size = min(order.size, current)
            if fill_size <= 0:
                order.filled_size = Decimal("0")
                order.status = OrderStatus.FILLED
                logger.info(
                    f"Paper order filled: {order.order_id} @ {fill_price} "
                    f"(capped to 0, position was {current})"
                )
                return
            order.filled_size = fill_size
            order.avg_fill_price = fill_price
            order.status = OrderStatus.FILLED
            proceeds = fill_size * fill_price
            self._balance += proceeds
            self._positions[order.token_id] = current - fill_size

        logger.info(
            f"Paper order filled: {order.order_id} @ {fill_price}"
        )

    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a paper order."""
        order = self._orders.get(order_id)

        if not order:
            return OrderResult(success=False, error="Order not found")

        if order.is_complete:
            return OrderResult(success=False, error="Order already complete")

        # Unlock funds
        if order.side == TradeSide.BUY:
            self._locked_balance -= order.remaining_size * order.price

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now()

        logger.info(f"Paper order cancelled: {order_id}")

        return OrderResult(success=True, order=order)

    async def get_order(self, order_id: str) -> Optional[Order]:
        """Get paper order."""
        order = self._orders.get(order_id)
        if not order:
            return None

        if order.status == OrderStatus.OPEN:
            market_data = self._market_data_cache.get(order.market_id)
            if not market_data:
                market_data = self._market_data_cache.get(order.token_id)

            if market_data:
                fill_price = self._simulate_fill(order, market_data)
                if fill_price is None:
                    fill_price = self._simulate_fill_at_mid(order, market_data)

                if fill_price is not None:
                    await self._execute_fill(order, fill_price)

        return order

    async def get_open_orders(
        self, market_id: Optional[str] = None
    ) -> list[Order]:
        """Get open paper orders."""
        orders = [
            o for o in self._orders.values()
            if o.status == OrderStatus.OPEN
        ]

        if market_id:
            orders = [o for o in orders if o.market_id == market_id]

        return orders

    async def get_balance(self) -> Balance:
        """Get paper balance."""
        return Balance(
            usdc=self._balance,
            locked_usdc=self._locked_balance,
        )

    async def get_market_data(self, market_id: str) -> Optional[MarketData]:
        """Get market data, using live price source if available."""
        if self._live_price_source is not None:
            fresh = self._live_price_source(market_id)
            if fresh is not None:
                self._market_data_cache[market_id] = fresh
                return fresh
        return self._market_data_cache.get(market_id)

    async def get_positions(self) -> dict[str, Decimal]:
        """Get paper positions."""
        return dict(self._positions)

    async def get_trade_history(self, after_ts: Optional[int] = None) -> list[TradeHistoryEntry]:
        """Return fills from internal paper orders."""
        entries = []
        for order in self._orders.values():
            if order.status != OrderStatus.FILLED:
                continue
            entries.append(TradeHistoryEntry(
                market=order.market_id,
                asset_id=order.token_id,
                outcome="",
                side=order.side.value if hasattr(order.side, "value") else str(order.side),
                size=float(order.filled_size),
                price=float(order.avg_fill_price),
                fee_rate_bps=0,
                match_time=order.updated_at.isoformat(),
                trader_side="TAKER",
                status="MATCHED",
            ))
        entries.sort(key=lambda e: e.match_time, reverse=True)
        return entries


class LiveTradingExecutor(TradingExecutor):
    """Live trading executor using py-clob-client.

    Executes real trades on Polymarket via the CLOB API.
    """

    def __init__(
        self,
        private_key: str,
        rpc_url: str = "https://polygon-rpc.com",
        chain_id: int = 137,
        funder: Optional[str] = None,
    ):
        """Initialize live trading executor.

        Args:
            private_key: Ethereum private key for signing
            rpc_url: Polygon RPC endpoint
            chain_id: Chain ID (137 for Polygon mainnet)
            funder: Proxy wallet address that holds funds (for proxy wallets).
                   If set, uses signature_type=2 (POLY_PROXY).
        """
        self._private_key = private_key
        self._rpc_url = rpc_url
        self._chain_id = chain_id
        self._funder = funder
        self._client = None
        self._orders: dict[str, Order] = {}

    async def _get_client(self):
        """Get or create CLOB client."""
        if self._client is None:
            try:
                from py_clob_client.client import ClobClient

                client_kwargs = {
                    "host": "https://clob.polymarket.com",
                    "key": self._private_key,
                    "chain_id": self._chain_id,
                }
                if self._funder:
                    client_kwargs["signature_type"] = 1
                    client_kwargs["funder"] = self._funder
                self._client = ClobClient(**client_kwargs)
                # Derive and set API credentials for authenticated endpoints
                creds = self._client.create_or_derive_api_creds()
                self._client.set_api_creds(creds)
            except ImportError:
                raise ImportError(
                    "py-clob-client is required for live trading. "
                    "Install with: pip install py-clob-client"
                )
        return self._client

    async def place_order(
        self,
        market_id: str,
        token_id: str,
        side: TradeSide,
        size: Decimal,
        price: Decimal,
        strategy_id: Optional[str] = None,
    ) -> OrderResult:
        """Place a live order on Polymarket."""
        try:
            client = await self._get_client()

            # Convert to CLOB API format
            from py_clob_client.clob_types import OrderArgs
            from py_clob_client.order_builder.constants import BUY, SELL

            order_args = OrderArgs(
                token_id=token_id,
                price=float(price),
                size=float(size),
                side=BUY if side == TradeSide.BUY else SELL,
            )

            # Create and sign order
            signed_order = client.create_order(order_args)
            response = client.post_order(signed_order)

            order_id = response.get("orderID", "")

            order = Order(
                order_id=order_id,
                market_id=market_id,
                token_id=token_id,
                side=side,
                size=size,
                price=price,
                status=OrderStatus.OPEN,
                strategy_id=strategy_id,
            )

            self._orders[order_id] = order

            logger.info(f"Live order placed: {order_id}")

            return OrderResult(success=True, order=order)

        except Exception as e:
            logger.error(f"Failed to place live order: {e}")
            return OrderResult(success=False, error=str(e))

    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a live order."""
        try:
            client = await self._get_client()
            client.cancel(order_id)

            order = self._orders.get(order_id)
            if order:
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.now()

            logger.info(f"Live order cancelled: {order_id}")

            return OrderResult(success=True, order=order)

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return OrderResult(success=False, error=str(e))

    async def get_order(self, order_id: str) -> Optional[Order]:
        """Get order status from CLOB."""
        try:
            client = await self._get_client()
            response = client.get_order(order_id)

            if not response:
                return None

            order = self._orders.get(order_id)
            if order:
                # Update from response
                status_map = {
                    "OPEN": OrderStatus.OPEN,
                    "MATCHED": OrderStatus.FILLED,
                    "FILLED": OrderStatus.FILLED,
                    "CANCELED": OrderStatus.CANCELLED,
                    "CANCELLED": OrderStatus.CANCELLED,
                }
                order.status = status_map.get(
                    response.get("status", "OPEN"),
                    OrderStatus.OPEN
                )
                order.filled_size = Decimal(str(response.get("size_matched", 0)))
                order.avg_fill_price = Decimal(str(response.get("price", 0)))
                order.updated_at = datetime.now()

            return order

        except Exception as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            return self._orders.get(order_id)

    async def get_open_orders(
        self, market_id: Optional[str] = None
    ) -> list[Order]:
        """Get open orders from CLOB."""
        try:
            client = await self._get_client()
            response = client.get_orders()

            orders = []
            for order_data in response:
                order = Order(
                    order_id=order_data.get("id", ""),
                    market_id=order_data.get("market", ""),
                    token_id=order_data.get("asset_id", ""),
                    side=TradeSide.BUY if order_data.get("side") == "BUY" else TradeSide.SELL,
                    size=Decimal(str(order_data.get("original_size", 0))),
                    price=Decimal(str(order_data.get("price", 0))),
                    status=OrderStatus.OPEN,
                    filled_size=Decimal(str(order_data.get("size_matched", 0))),
                )
                orders.append(order)

            if market_id:
                orders = [o for o in orders if o.market_id == market_id]

            return orders

        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return []

    async def get_balance(self) -> Balance:
        """Get balance from CLOB."""
        try:
            client = await self._get_client()
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

            result = client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            # Balance is in USDC raw units (6 decimals)
            raw_balance = Decimal(result.get("balance", "0"))
            usdc_balance = raw_balance / Decimal("1000000")

            # Estimate locked balance from open orders
            open_orders = await self.get_open_orders()
            locked = sum(
                o.remaining_size * o.price
                for o in open_orders
                if o.side == TradeSide.BUY
            )

            return Balance(
                usdc=usdc_balance,
                locked_usdc=locked,
            )

        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return Balance(usdc=Decimal("0"), locked_usdc=Decimal("0"))

    async def get_market_data(self, market_id: str) -> Optional[MarketData]:
        """Get market data from CLOB.

        Note: market_id should be a token_id, as the CLOB API's
        get_order_book operates on token IDs, not condition IDs.
        """
        try:
            client = await self._get_client()
            book = client.get_order_book(market_id)

            if not book:
                return None

            bids = book.bids or []
            asks = book.asks or []

            best_bid = Decimal(bids[0].price) if bids else Decimal("0")
            best_ask = Decimal(asks[0].price) if asks else Decimal("1")

            return MarketData(
                market_id=market_id,
                condition_id="",
                token_id="",
                question="",
                outcome="",
                best_bid=best_bid,
                best_ask=best_ask,
                last_price=(best_bid + best_ask) / 2,
                volume_24h=Decimal("0"),
                liquidity=Decimal("0"),
            )

        except Exception as e:
            logger.error(f"Failed to get market data: {e}")
            return None

    async def get_positions(self) -> dict[str, Decimal]:
        """Get positions from CLOB."""
        # Would need integration with wallet/subgraph
        return {}

    async def get_trade_history(self, after_ts: Optional[int] = None) -> list[TradeHistoryEntry]:
        """Fetch trade history from CLOB API, extracting user fills."""
        try:
            client = await self._get_client()
            from py_clob_client.clob_types import TradeParams

            params = TradeParams(after=after_ts) if after_ts else None
            raw_trades = client.get_trades(params)

            if not raw_trades:
                return []

            # Determine user address from funder or derive from key
            user_address = (self._funder or "").lower()
            entries = []

            for t in raw_trades:
                match_time = t.get("match_time", "")
                market = t.get("market", "")

                if t.get("trader_side") == "MAKER":
                    for mo in t.get("maker_orders", []):
                        if not user_address or mo.get("maker_address", "").lower() == user_address:
                            entries.append(TradeHistoryEntry(
                                market=market,
                                asset_id=mo.get("asset_id", t.get("asset_id", "")),
                                outcome=mo.get("outcome", t.get("outcome", "")),
                                side=mo.get("side", ""),
                                size=float(mo.get("matched_amount", 0)),
                                price=float(mo.get("price", 0)),
                                fee_rate_bps=float(mo.get("fee_rate_bps", 0)),
                                match_time=match_time,
                                trader_side="MAKER",
                                status=t.get("status", ""),
                            ))
                else:
                    entries.append(TradeHistoryEntry(
                        market=market,
                        asset_id=t.get("asset_id", ""),
                        outcome=t.get("outcome", ""),
                        side=t.get("side", ""),
                        size=float(t.get("size", 0)),
                        price=float(t.get("price", 0)),
                        fee_rate_bps=float(t.get("fee_rate_bps", 0)),
                        match_time=match_time,
                        trader_side="TAKER",
                        status=t.get("status", ""),
                    ))

            entries.sort(key=lambda e: e.match_time, reverse=True)
            return entries

        except Exception as e:
            logger.error(f"Failed to fetch trade history: {e}")
            return []

    async def get_market_info(self, condition_id: str) -> Optional[dict]:
        """Fetch market metadata from CLOB API."""
        try:
            client = await self._get_client()
            return client.get_market(condition_id)
        except Exception as e:
            logger.error(f"Failed to fetch market info for {condition_id}: {e}")
            return None
