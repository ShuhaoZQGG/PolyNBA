"""Price fetching from Polymarket CLOB API."""

import logging
import math
import random
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderBookSummary

from .models import MarketPrices, PolymarketNBAMarket

if TYPE_CHECKING:
    from ..data.models import GameState

logger = logging.getLogger(__name__)


def home_win_probability_from_game_state(
    game_state: "GameState",
    noise_std: float = 0.015,
) -> float:
    """In-game home win probability from score and time (basketball-aware).

    Uses score differential and time remaining: a 20-pt lead with 2 min left
    is near-certain; the same lead with 20 min left is less so. Small noise
    is added so prices are not perfectly mechanical.

    Args:
        game_state: Current game state (scores, period, clock).
        noise_std: Std dev of Gaussian noise added to probability (e.g. 0.015).

    Returns:
        P(home wins) in [0, 1].
    """
    diff = game_state.score_differential  # positive = home leading
    sec_left = max(1, game_state.total_seconds_remaining)
    # Time factor: each point matters more as time runs out (e.g. 2 min left -> big impact)
    minutes_left = sec_left / 60.0
    time_factor = 10.0 / math.sqrt(minutes_left)
    # Logistic: effective_diff in "points worth" -> home_prob
    effective = diff * time_factor * 0.05
    home_prob = 1.0 / (1.0 + math.exp(-effective))
    home_prob += random.gauss(0, noise_std)
    return max(0.02, min(0.98, home_prob))


def generate_random_price_series(
    n_ticks: int,
    condition_id: str = "test_market",
    spread: float = 0.02,
    volatility: float = 0.03,
    initial_home_mid: float = 0.5,
    depth: float = 1000.0,
    seed: Optional[int] = None,
) -> list[MarketPrices]:
    """Generate a random walk time series of MarketPrices for testing.

    home_mid follows a bounded random walk; away_mid = 1 - home_mid.
    Bid/ask are mid +/- spread/2. When series is exhausted, callers hold last value.

    Args:
        n_ticks: Number of price ticks to generate
        condition_id: Market condition_id for each MarketPrices
        spread: Bid-ask spread (e.g. 0.02 = 2 cents)
        volatility: Std dev of random step for home_mid
        initial_home_mid: Starting home mid price (0-1)
        depth: Fixed depth for all sides
        seed: Optional RNG seed for reproducibility

    Returns:
        List of MarketPrices of length n_ticks
    """
    if seed is not None:
        random.seed(seed)
    depth_d = Decimal(str(depth))
    half = spread / 2
    out: list[MarketPrices] = []
    home_mid = max(0.2, min(0.8, initial_home_mid))
    for _ in range(n_ticks):
        home_mid = max(0.2, min(0.8, home_mid + random.gauss(0, volatility)))
        away_mid = 1.0 - home_mid
        home_bid = Decimal(str(round(home_mid - half, 4)))
        home_ask = Decimal(str(round(home_mid + half, 4)))
        away_bid = Decimal(str(round(away_mid - half, 4)))
        away_ask = Decimal(str(round(away_mid + half, 4)))
        out.append(
            MarketPrices(
                condition_id=condition_id,
                home_mid_price=Decimal(str(round(home_mid, 4))),
                away_mid_price=Decimal(str(round(away_mid, 4))),
                home_best_bid=home_bid,
                home_best_ask=home_ask,
                away_best_bid=away_bid,
                away_best_ask=away_ask,
                home_bid_depth=depth_d,
                home_ask_depth=depth_d,
                away_bid_depth=depth_d,
                away_ask_depth=depth_d,
            )
        )
    return out

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
        **kwargs: object,
    ) -> Optional[MarketPrices]:
        """Fetch current prices for a market.

        Args:
            market: The Polymarket NBA market to fetch prices for
            **kwargs: Ignored (e.g. game_state for test-mode compatibility).

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

    def get_token_price_info(self, token_id: str) -> tuple[Optional[Decimal], Optional[Decimal], float]:
        """Get mid-price, best-bid, and spread % in one order book fetch.

        Returns:
            (mid_price, best_bid, spread_pct) — any element may be None/0.0 on failure.
        """
        try:
            client = self._get_client()
            book = client.get_order_book(token_id)
            if not book:
                return None, None, 0.0
            best_bid = self._get_best_bid(book)
            best_ask = self._get_best_ask(book)
            mid_price = self._calculate_mid_price(best_bid, best_ask)
            if mid_price and mid_price > 0 and best_bid is not None and best_ask is not None:
                spread_pct = float((best_ask - best_bid) / mid_price) * 100.0
            else:
                spread_pct = 0.0
            return mid_price, best_bid, spread_pct
        except Exception as e:
            logger.debug(f"Error fetching price info for token {token_id[:20]}...: {e}")
            return None, None, 0.0

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
        """Fetch prices for multiple markets concurrently.

        Uses asyncio.gather with bounded concurrency for parallel fetching.

        Args:
            markets: List of markets to fetch prices for

        Returns:
            Dict mapping condition_id to MarketPrices
        """
        import asyncio

        semaphore = asyncio.Semaphore(5)

        async def _fetch_with_limit(market: PolymarketNBAMarket) -> tuple[str, Optional[MarketPrices]]:
            async with semaphore:
                prices = await self.get_market_prices(market)
                return market.condition_id, prices

        pairs = await asyncio.gather(
            *[_fetch_with_limit(m) for m in markets]
        )

        return {cid: prices for cid, prices in pairs if prices is not None}


class TimeSeriesPriceFetcher:
    """Price fetcher that returns a pre-generated or scripted time series of prices.

    Each call to get_market_prices returns the next tick. When the series is
    exhausted, continues with a random walk from the last price so odds keep changing.
    """

    def __init__(
        self,
        prices: list[MarketPrices],
        wrap: bool = False,
        continue_random_walk: bool = True,
        volatility: float = 0.03,
        spread: float = 0.02,
        *,
        misprice_probability: float = 0.0,
        misprice_min_pct: float = 5.0,
        misprice_max_pct: float = 12.0,
        live_simulator: Optional[object] = None,
    ):
        """Initialize with a list of MarketPrices (e.g. from generate_random_price_series).

        Args:
            prices: List of MarketPrices; each get_market_prices returns the next.
            wrap: If True, after last tick wrap to first (ignored if continue_random_walk).
            continue_random_walk: If True, after series exhausted generate new prices by random walk.
            volatility: Std dev for random walk step when continue_random_walk is True.
            spread: Bid-ask spread (e.g. 0.02) when generating from random walk.
            misprice_probability: When using game_state prices, probability (0-1) of adding a
                deliberate misprice so market diverges from model (e.g. 0.25 = 25% of ticks).
            misprice_min_pct: Min absolute misprice in percent (e.g. 5 = 5%).
            misprice_max_pct: Max absolute misprice in percent (e.g. 12 = 12%).
            live_simulator: Optional LiveTestPriceSimulator. When set with game_state,
                delegates to simulator.get_current_prices() for coordinated live pricing.
        """
        self._prices = prices
        self._wrap = wrap
        self._continue_random_walk = continue_random_walk
        self._volatility = volatility
        self._spread = spread
        self._misprice_probability = misprice_probability
        self._misprice_min_pct = misprice_min_pct
        self._misprice_max_pct = misprice_max_pct
        self._live_simulator = live_simulator
        self._index = 0
        self._last_market: Optional[PolymarketNBAMarket] = None
        self._last_prices: Optional[MarketPrices] = None

    def _prices_from_game_state(
        self, market: PolymarketNBAMarket, game_state: "GameState"
    ) -> MarketPrices:
        """Build MarketPrices from game state (score + time -> win prob, then bid/ask)."""
        home_prob = home_win_probability_from_game_state(game_state, noise_std=0.015)
        # Optionally add a deliberate misprice so the "market" sometimes disagrees with the model
        # (simulates overreaction / stale odds and produces edges >= min_edge in test mode).
        if (
            self._misprice_probability > 0
            and random.random() < self._misprice_probability
        ):
            offset_pct = random.uniform(
                self._misprice_min_pct / 100.0,
                self._misprice_max_pct / 100.0,
            )
            home_prob += random.choice([-1.0, 1.0]) * offset_pct
            home_prob = max(0.02, min(0.98, home_prob))
        away_prob = 1.0 - home_prob
        half = self._spread / 2
        depth = (
            self._prices[0].home_bid_depth
            if self._prices
            else Decimal("1000")
        )
        prices = MarketPrices(
            condition_id=market.condition_id,
            home_mid_price=Decimal(str(round(home_prob, 4))),
            away_mid_price=Decimal(str(round(away_prob, 4))),
            home_best_bid=Decimal(str(round(home_prob - half, 4))),
            home_best_ask=Decimal(str(round(home_prob + half, 4))),
            away_best_bid=Decimal(str(round(away_prob - half, 4))),
            away_best_ask=Decimal(str(round(away_prob + half, 4))),
            home_bid_depth=depth,
            home_ask_depth=depth,
            away_bid_depth=depth,
            away_ask_depth=depth,
        )
        self._last_market = market
        self._last_prices = prices
        return prices

    def _next_from_random_walk(self, market: PolymarketNBAMarket) -> Optional[MarketPrices]:
        """Generate next MarketPrices from last price using a random step."""
        if self._last_prices is None:
            return None
        half = self._spread / 2
        home_mid = float(self._last_prices.home_mid_price) + random.gauss(0, self._volatility)
        home_mid = max(0.2, min(0.8, home_mid))
        away_mid = 1.0 - home_mid
        depth = self._last_prices.home_bid_depth
        prices = MarketPrices(
            condition_id=market.condition_id,
            home_mid_price=Decimal(str(round(home_mid, 4))),
            away_mid_price=Decimal(str(round(away_mid, 4))),
            home_best_bid=Decimal(str(round(home_mid - half, 4))),
            home_best_ask=Decimal(str(round(home_mid + half, 4))),
            away_best_bid=Decimal(str(round(away_mid - half, 4))),
            away_best_ask=Decimal(str(round(away_mid + half, 4))),
            home_bid_depth=depth,
            home_ask_depth=depth,
            away_bid_depth=depth,
            away_ask_depth=depth,
        )
        self._last_market = market
        self._last_prices = prices
        return prices

    async def get_market_prices(
        self,
        market: PolymarketNBAMarket,
        *,
        game_state: Optional["GameState"] = None,
    ) -> Optional[MarketPrices]:
        """Return prices. If game_state given, use score+time win prob; else series/random walk."""
        if game_state is not None and self._live_simulator is not None:
            prices = self._live_simulator.get_current_prices(market, game_state)
            self._last_market = market
            self._last_prices = prices
            return prices
        if game_state is not None:
            return self._prices_from_game_state(market, game_state)
        if not self._prices:
            return None
        if self._index >= len(self._prices):
            if self._continue_random_walk and self._last_prices is not None:
                return self._next_from_random_walk(market)
            if self._wrap:
                self._index = 0
            else:
                idx = len(self._prices) - 1
                tick = self._prices[idx]
                prices = MarketPrices(
                    condition_id=market.condition_id,
                    home_mid_price=tick.home_mid_price,
                    away_mid_price=tick.away_mid_price,
                    home_best_bid=tick.home_best_bid,
                    home_best_ask=tick.home_best_ask,
                    away_best_bid=tick.away_best_bid,
                    away_best_ask=tick.away_best_ask,
                    home_bid_depth=tick.home_bid_depth,
                    home_ask_depth=tick.home_ask_depth,
                    away_bid_depth=tick.away_bid_depth,
                    away_ask_depth=tick.away_ask_depth,
                )
                self._last_market = market
                self._last_prices = prices
                return prices
        idx = self._index
        tick = self._prices[idx]
        self._index += 1
        prices = MarketPrices(
            condition_id=market.condition_id,
            home_mid_price=tick.home_mid_price,
            away_mid_price=tick.away_mid_price,
            home_best_bid=tick.home_best_bid,
            home_best_ask=tick.home_best_ask,
            away_best_bid=tick.away_best_bid,
            away_best_ask=tick.away_best_ask,
            home_bid_depth=tick.home_bid_depth,
            home_ask_depth=tick.home_ask_depth,
            away_bid_depth=tick.away_bid_depth,
            away_ask_depth=tick.away_ask_depth,
        )
        self._last_market = market
        self._last_prices = prices
        return prices

    def get_token_sell_price(self, token_id: str) -> Optional[Decimal]:
        """Return current best bid for the token (from last get_market_prices result)."""
        if self._last_market is None or self._last_prices is None:
            return None
        if token_id == self._last_market.home_token_id:
            return self._last_prices.home_best_bid
        if token_id == self._last_market.away_token_id:
            return self._last_prices.away_best_bid
        return None

    def get_token_price_info(self, token_id: str) -> tuple[Optional[Decimal], Optional[Decimal], float]:
        """Get mid-price, best-bid, and spread % from cached last prices.

        Returns:
            (mid_price, best_bid, spread_pct) — any element may be None/0.0.
        """
        if self._last_market is None or self._last_prices is None:
            return None, None, 0.0
        p = self._last_prices
        if token_id == self._last_market.home_token_id:
            mid, bid, ask = p.home_mid_price, p.home_best_bid, p.home_best_ask
        elif token_id == self._last_market.away_token_id:
            mid, bid, ask = p.away_mid_price, p.away_best_bid, p.away_best_ask
        else:
            return None, None, 0.0
        if mid and mid > 0 and bid is not None and ask is not None:
            spread_pct = float((ask - bid) / mid) * 100.0
        else:
            spread_pct = 0.0
        return mid, bid, spread_pct


class SimulatedPriceFetcher:
    """Simulated price fetcher for testing and fallback."""

    async def get_market_prices(
        self,
        market: PolymarketNBAMarket,
        **kwargs: object,
    ) -> MarketPrices:
        """Return simulated prices for testing.

        Args:
            market: Market to generate prices for
            **kwargs: Ignored (e.g. game_state for test-mode compatibility).

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
