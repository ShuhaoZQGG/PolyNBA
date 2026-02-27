"""Live price simulator that produces dynamically evolving prices during order delays.

Solves the realism gap where PaperTradingExecutor.get_market_data() returns the same
cached value every 100ms delay check. This simulator applies micro-ticks of random
noise so successive calls get fresh prices, enabling the auto-cancel mechanism.
"""

import logging
import random
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from ..polymarket.models import MarketPrices, PolymarketNBAMarket
from ..polymarket.price_fetcher import home_win_probability_from_game_state
from ..trading.executor import MarketData

if TYPE_CHECKING:
    from ..data.models import GameState

logger = logging.getLogger(__name__)


class LiveTestPriceSimulator:
    """Produces dynamically evolving prices for test-game mode.

    Each call to get_market_data_for_token() applies a micro-tick of random noise
    so that successive 100ms delay checks during the 3-second order delay see
    different prices. Scoring events trigger larger jumps.

    Over 30 ticks (3s / 100ms), total drift std ~1.6%, occasionally exceeding
    the 2% auto-cancel threshold (~20-30% of orders).
    """

    def __init__(
        self,
        market: PolymarketNBAMarket,
        spread: float = 0.02,
        micro_tick_std: float = 0.003,
        score_jump_std: float = 0.015,
        misprice_probability: float = 0.0,
        misprice_min_pct: float = 5.0,
        misprice_max_pct: float = 12.0,
    ):
        """Initialize the live price simulator.

        Args:
            market: The synthetic Polymarket market for the test game.
            spread: Bid-ask spread (e.g. 0.02 = 2 cents).
            micro_tick_std: Std dev of noise per delay-check tick (~0.3%).
                Over 30 ticks: sqrt(30)*0.003 ≈ 1.6% total drift std.
            score_jump_std: Std dev of price jump on scoring events.
            misprice_probability: Probability (0-1) of adding a deliberate misprice
                per main-loop tick so the market diverges from the model.
            misprice_min_pct: Min absolute misprice in percent (e.g. 5 = 5%).
            misprice_max_pct: Max absolute misprice in percent (e.g. 12 = 12%).
        """
        self._market = market
        self._spread = spread
        self._micro_tick_std = micro_tick_std
        self._score_jump_std = score_jump_std
        self._misprice_probability = misprice_probability
        self._misprice_min_pct = misprice_min_pct
        self._misprice_max_pct = misprice_max_pct

        # Current fair value for home win probability
        self._current_home_mid: float = 0.5
        # Track last game state to detect scoring events
        self._last_home_score: int = 0
        self._last_away_score: int = 0

    def get_current_prices(
        self,
        market: PolymarketNBAMarket,
        game_state: "GameState",
    ) -> MarketPrices:
        """Update fair value from game state and return prices.

        Called by the price fetcher each main-loop iteration (~30s).
        Detects scoring events and applies larger jumps accordingly.

        Args:
            market: The Polymarket market.
            game_state: Current game state with scores and clock.

        Returns:
            MarketPrices with updated fair value.
        """
        # Detect scoring events
        home_scored = game_state.home_team.score > self._last_home_score
        away_scored = game_state.away_team.score > self._last_away_score
        self._last_home_score = game_state.home_team.score
        self._last_away_score = game_state.away_team.score

        # Update fair value from game state
        self._current_home_mid = home_win_probability_from_game_state(
            game_state, noise_std=0.01
        )

        # Apply extra jump on scoring events
        if home_scored or away_scored:
            jump = random.gauss(0, self._score_jump_std)
            self._current_home_mid += jump
            self._current_home_mid = max(0.02, min(0.98, self._current_home_mid))
            logger.debug(
                f"Score change detected, applied jump {jump:+.4f} -> "
                f"home_mid={self._current_home_mid:.4f}"
            )

        # Apply deliberate misprice so market sometimes diverges from model
        # (produces tradeable edges for strategies in test mode)
        market_home_mid = self._current_home_mid
        if (
            self._misprice_probability > 0
            and random.random() < self._misprice_probability
        ):
            offset_pct = random.uniform(
                self._misprice_min_pct / 100.0,
                self._misprice_max_pct / 100.0,
            )
            market_home_mid += random.choice([-1.0, 1.0]) * offset_pct
            market_home_mid = max(0.02, min(0.98, market_home_mid))

        return self._build_market_prices(market, market_home_mid)

    def get_market_data_for_token(self, token_id: str) -> Optional[MarketData]:
        """Get fresh market data with micro-tick noise for a token.

        Called by the paper executor during each 100ms delay check.
        Applies a small random noise so successive calls return different prices.

        Args:
            token_id: The token ID to get data for.

        Returns:
            MarketData with micro-tick noise applied, or None if unknown token.
        """
        if token_id not in (
            self._market.home_token_id,
            self._market.away_token_id,
        ):
            return None

        # Apply micro-tick noise to fair value
        noise = random.gauss(0, self._micro_tick_std)
        noisy_home_mid = max(0.02, min(0.98, self._current_home_mid + noise))

        is_home = token_id == self._market.home_token_id
        mid = noisy_home_mid if is_home else (1.0 - noisy_home_mid)
        half = self._spread / 2

        bid = Decimal(str(round(mid - half, 4)))
        ask = Decimal(str(round(mid + half, 4)))
        mid_d = Decimal(str(round(mid, 4)))

        outcome = "Home" if is_home else "Away"

        return MarketData(
            market_id=token_id,
            condition_id=self._market.condition_id,
            token_id=token_id,
            question="",
            outcome=outcome,
            best_bid=bid,
            best_ask=ask,
            last_price=mid_d,
            volume_24h=Decimal("0"),
            liquidity=Decimal("1000"),
            timestamp=datetime.now(),
        )

    def _build_market_prices(
        self, market: PolymarketNBAMarket, home_mid: Optional[float] = None
    ) -> MarketPrices:
        """Build MarketPrices from the current (or overridden) fair value."""
        if home_mid is None:
            home_mid = self._current_home_mid
        away_mid = 1.0 - home_mid
        half = self._spread / 2
        depth = Decimal("1000")

        return MarketPrices(
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
