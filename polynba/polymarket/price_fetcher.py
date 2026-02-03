"""Price fetching from Polymarket CLOB API."""

import logging
from decimal import Decimal
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderBookSummary

from .models import MarketPrices, PolymarketNBAMarket

logger = logging.getLogger(__name__)

# Default CLOB host
DEFAULT_CLOB_HOST = "https://clob.polymarket.com"


class PriceFetcher:
    """Fetches real-time prices from Polymarket CLOB API.

    Uses py-clob-client in Level 0 mode (no authentication required)
    for read-only market data access.
    """

    def __init__(
        self,
        clob_host: str = DEFAULT_CLOB_HOST,
        chain_id: int = 137,  # Polygon mainnet
    ):
        """Initialize price fetcher.

        Args:
            clob_host: CLOB API host URL
            chain_id: Blockchain chain ID (137 for Polygon)
        """
        self._clob_host = clob_host
        self._chain_id = chain_id
        self._client: Optional[ClobClient] = None

    def _get_client(self) -> ClobClient:
        """Get or create CLOB client.

        Level 0 mode requires no private key - just host and chain_id.
        """
        if self._client is None:
            # Initialize in Level 0 (read-only) mode
            # No private key needed for market data
            self._client = ClobClient(
                host=self._clob_host,
                chain_id=self._chain_id,
            )
        return self._client

    async def get_market_prices(
        self,
        market: PolymarketNBAMarket,
    ) -> Optional[MarketPrices]:
        """Fetch current prices for a market.

        Args:
            market: The Polymarket NBA market to fetch prices for

        Returns:
            MarketPrices or None if fetch fails
        """
        try:
            client = self._get_client()

            # Fetch order books for both outcomes
            # Note: py-clob-client methods are synchronous
            home_book = client.get_order_book(market.home_token_id)
            away_book = client.get_order_book(market.away_token_id)

            # Parse order books into prices
            prices = self._parse_order_books(
                condition_id=market.condition_id,
                home_book=home_book,
                away_book=away_book,
            )

            if prices:
                logger.debug(
                    f"Fetched prices for {market.condition_id}: "
                    f"home={prices.home_mid_price:.4f}, away={prices.away_mid_price:.4f}"
                )

            return prices

        except Exception as e:
            logger.error(f"Error fetching prices for {market.condition_id}: {e}")
            return None

    def get_token_sell_price(self, token_id: str) -> Optional[Decimal]:
        """Get current sell price (best bid) for a token. Use for unrealized P&L / exit evaluation.

        Args:
            token_id: CLOB token ID for the outcome

        Returns:
            Best bid price (0-1), or None if fetch fails or no bids
        """
        try:
            client = self._get_client()
            book = client.get_order_book(token_id)
            if not book:
                return None
            return self._get_best_bid(book)
        except Exception as e:
            logger.debug(f"Error fetching sell price for token {token_id[:20]}...: {e}")
            return None

    def _parse_order_books(
        self,
        condition_id: str,
        home_book: OrderBookSummary,
        away_book: OrderBookSummary,
    ) -> Optional[MarketPrices]:
        """Parse order book summaries into MarketPrices.

        Args:
            condition_id: Market condition ID
            home_book: Order book for home outcome
            away_book: Order book for away outcome

        Returns:
            MarketPrices or None if invalid
        """
        try:
            # Extract best bid/ask for home
            home_best_bid = self._get_best_bid(home_book)
            home_best_ask = self._get_best_ask(home_book)

            # Extract best bid/ask for away
            away_best_bid = self._get_best_bid(away_book)
            away_best_ask = self._get_best_ask(away_book)

            # Calculate mid prices
            home_mid = self._calculate_mid_price(home_best_bid, home_best_ask)
            away_mid = self._calculate_mid_price(away_best_bid, away_best_ask)

            # If we can't get mid prices, try using last trade or default
            if home_mid is None or away_mid is None:
                logger.warning(f"Could not calculate mid prices for {condition_id}")
                return None

            # Calculate depth at best prices
            home_bid_depth = self._calculate_depth(home_book.bids)
            home_ask_depth = self._calculate_depth(home_book.asks)
            away_bid_depth = self._calculate_depth(away_book.bids)
            away_ask_depth = self._calculate_depth(away_book.asks)

            return MarketPrices(
                condition_id=condition_id,
                home_mid_price=home_mid,
                away_mid_price=away_mid,
                home_best_bid=home_best_bid,
                home_best_ask=home_best_ask,
                away_best_bid=away_best_bid,
                away_best_ask=away_best_ask,
                home_bid_depth=home_bid_depth,
                home_ask_depth=home_ask_depth,
                away_bid_depth=away_bid_depth,
                away_ask_depth=away_ask_depth,
            )

        except Exception as e:
            logger.error(f"Error parsing order books: {e}")
            return None

    def _get_best_bid(self, book: OrderBookSummary) -> Optional[Decimal]:
        """Get best (highest) bid price from order book. Sell price for this outcome."""
        if not book.bids:
            return None
        try:
            prices = [Decimal(str(b.price)) for b in book.bids]
            return max(prices)
        except (KeyError, ValueError, TypeError):
            return None

    def _get_best_ask(self, book: OrderBookSummary) -> Optional[Decimal]:
        """Get best (lowest) ask price from order book. Buy price for this outcome."""
        if not book.asks:
            return None
        try:
            prices = [Decimal(str(a.price)) for a in book.asks]
            return min(prices)
        except (KeyError, ValueError, TypeError):
            return None

    def _calculate_mid_price(
        self,
        bid: Optional[Decimal],
        ask: Optional[Decimal],
    ) -> Optional[Decimal]:
        """Calculate mid price from bid and ask.

        Args:
            bid: Best bid price
            ask: Best ask price

        Returns:
            Mid price or None
        """
        if bid is not None and ask is not None:
            return (bid + ask) / 2

        # Fallback: if only one side exists, use it
        if bid is not None:
            return bid
        if ask is not None:
            return ask

        return None

    def _calculate_depth(self, orders: list) -> Decimal:
        """Calculate total depth (size) at all price levels.

        Args:
            orders: List of orders from order book

        Returns:
            Total size in USDC
        """
        total = Decimal("0")
        for order in orders:
            try:
                size = Decimal(str(order.size))
                total += size
            except (ValueError, AttributeError):
                continue
        return total

    async def get_prices_batch(
        self,
        markets: list[PolymarketNBAMarket],
    ) -> dict[str, MarketPrices]:
        """Fetch prices for multiple markets.

        Args:
            markets: List of markets to fetch prices for

        Returns:
            Dict mapping condition_id to MarketPrices
        """
        results = {}

        for market in markets:
            prices = await self.get_market_prices(market)
            if prices:
                results[market.condition_id] = prices

        return results


class SimulatedPriceFetcher:
    """Simulated price fetcher for testing and fallback."""

    async def get_market_prices(
        self,
        market: PolymarketNBAMarket,
    ) -> MarketPrices:
        """Return simulated prices for testing.

        Args:
            market: Market to generate prices for

        Returns:
            Simulated MarketPrices
        """
        # Default to 50/50 with some spread
        home_mid = Decimal("0.50")
        away_mid = Decimal("0.50")

        return MarketPrices(
            condition_id=market.condition_id,
            home_mid_price=home_mid,
            away_mid_price=away_mid,
            home_best_bid=home_mid - Decimal("0.01"),
            home_best_ask=home_mid + Decimal("0.01"),
            away_best_bid=away_mid - Decimal("0.01"),
            away_best_ask=away_mid + Decimal("0.01"),
            home_bid_depth=Decimal("1000"),
            home_ask_depth=Decimal("1000"),
            away_bid_depth=Decimal("1000"),
            away_ask_depth=Decimal("1000"),
        )
