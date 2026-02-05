"""Main trading loop orchestration."""

import asyncio
import logging
import math
import os
import random
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..analysis import (
    ClaudeAnalyzer,
    ContextBuilder,
    EdgeDetector,
    EdgeFilter,
    ProbabilityCalculator,
)
from ..data import DataManager, GameState, TeamStats
from ..polymarket import (
    MarketDiscovery,
    MarketMapper,
    PriceFetcher,
    TimeSeriesPriceFetcher,
    generate_random_price_series,
)
from ..testing import TestDataManager, TestMarketMapper
from ..testing.mock_mapper import TEST_CONDITION_ID
from ..strategy import CapitalAllocation, StrategyManager, TradingSignal
from ..trading import (
    MarketData,
    OrderManager,
    PaperTradingExecutor,
    PositionTracker,
    RiskLimits,
    RiskManager,
    TradingExecutor,
)
from ..utils.logger import TradeLogger, setup_logging
from ..utils.performance import PerformanceTracker
from ..utils.portfolio_display import PortfolioDisplay

logger = logging.getLogger(__name__)


def _optional_float(v: Any) -> Optional[float]:
    """Return float or None if v is None."""
    if v is None:
        return None
    return float(v)


def _optional_int(v: Any) -> Optional[int]:
    """Return int or None if v is None."""
    if v is None:
        return None
    return int(v)


@dataclass
class BotConfig:
    """Bot configuration."""

    mode: str = "paper"
    bankroll: float = 500.0
    loop_interval: int = 30
    max_iterations: Optional[int] = None
    active_strategies: list[str] = None
    claude_enabled: bool = True
    log_level: str = "INFO"

    # Portfolio display settings
    portfolio_display_interval: int = 1  # Show every N iterations (0 to disable)
    portfolio_display_compact: bool = False  # Use compact one-line format

    # Command server settings
    command_server_enabled: bool = True
    command_server_host: str = "127.0.0.1"
    command_server_port: int = 8765

    # Run / instance
    allowed_game_ids: Optional[List[str]] = None
    instance_id: Optional[int] = None

    # Test game (mock time-series prices, no real API)
    test_game: bool = False
    test_game_ticks: Optional[int] = None  # Number of price ticks / game states (default 20)

    # Polymarket settings
    polymarket_gamma_api: str = "https://gamma-api.polymarket.com"
    polymarket_clob_host: str = "https://clob.polymarket.com"
    polymarket_discovery_cache_ttl: int = 300
    polymarket_fallback_to_simulated: bool = True

    # Edge detection (buy filters)
    min_edge_percent: float = 5.0
    max_edge_percent: float = 50.0
    min_confidence: int = 5
    min_market_price: float = 0.10
    max_market_price: float = 0.90
    min_time_remaining_seconds: int = 300
    exclude_overtime: bool = False

    # Exit overrides (sell; None = use strategy YAML)
    exit_stop_loss_percent: Optional[float] = None
    exit_before_seconds: Optional[int] = None
    exit_profit_target_percent: Optional[float] = None  # Global take-profit % override

    # Risk limits (wired to RiskManager)
    max_position_usdc: float = 100.0
    max_total_exposure_usdc: float = 500.0
    max_daily_loss_usdc: float = 100.0
    max_concurrent_positions: int = 5
    max_position_per_market: int = 2
    min_order_size_usdc: float = 5.0
    max_order_size_usdc: float = 50.0
    min_position_usdc: Optional[float] = None  # Global min; skip signal if size below (None = use strategy)

    # Allocation: % of balance bettable and split by risk level
    max_portfolio_exposure: float = 0.50  # Max fraction of bankroll in positions (bettable %)
    allocation_low_risk_percent: float = 0.50
    allocation_medium_risk_percent: float = 0.35
    allocation_high_risk_percent: float = 0.15

    # Strategy / conflict
    conflict_min_confidence: int = 7  # Take conflicting side only if confidence >= this
    kelly_multiplier_override: Optional[float] = None  # Scale strategy Kelly (e.g. 0.5 = half); None = use strategy
    min_edge_strategy_overrides: Dict[str, float] = field(default_factory=dict)  # Per-strategy min edge % (e.g. {"conservative": 3.0, "aggressive": 5.0})

    @classmethod
    def from_yaml(cls, path: Path) -> "BotConfig":
        """Load config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        polymarket_config = data.get("apis", {}).get("polymarket", {})
        discovery_config = polymarket_config.get("discovery", {})
        prices_config = polymarket_config.get("prices", {})

        display_config = data.get("portfolio_display", {})
        command_config = data.get("command_server", {})
        run_config = data.get("run", {})

        return cls(
            mode=data.get("mode", "paper"),
            bankroll=data.get("bankroll", 500.0),
            loop_interval=data.get("loop", {}).get("interval_seconds", 30),
            max_iterations=data.get("loop", {}).get("max_iterations"),
            active_strategies=data.get("active_strategies", ["conservative"]),
            claude_enabled=data.get("apis", {}).get("claude", {}).get("enabled", True),
            log_level=data.get("logging", {}).get("level", "INFO"),
            # Portfolio display settings
            portfolio_display_interval=display_config.get("interval", 1),
            portfolio_display_compact=display_config.get("compact", False),
            # Command server settings
            command_server_enabled=command_config.get("enabled", True),
            command_server_host=command_config.get("host", "127.0.0.1"),
            command_server_port=command_config.get("port", 8765),
            allowed_game_ids=run_config.get("allowed_game_ids"),
            instance_id=run_config.get("instance_id"),
            test_game=run_config.get("test_game", False),
            test_game_ticks=run_config.get("test_game_ticks"),
            # Polymarket settings
            polymarket_gamma_api=polymarket_config.get(
                "gamma_api", "https://gamma-api.polymarket.com"
            ),
            polymarket_clob_host=polymarket_config.get(
                "host", "https://clob.polymarket.com"
            ),
            polymarket_discovery_cache_ttl=discovery_config.get("cache_ttl_seconds", 300),
            polymarket_fallback_to_simulated=prices_config.get("fallback_to_simulated", True),
            # Edge detection
            min_edge_percent=data.get("edge", {}).get("min_edge_percent", 5.0),
            max_edge_percent=data.get("edge", {}).get("max_edge_percent", 50.0),
            min_confidence=data.get("edge", {}).get("min_confidence", 5),
            min_market_price=float(data.get("edge", {}).get("min_market_price", 0.10)),
            max_market_price=float(data.get("edge", {}).get("max_market_price", 0.90)),
            min_time_remaining_seconds=int(data.get("edge", {}).get("min_time_remaining_seconds", 300)),
            exclude_overtime=bool(data.get("edge", {}).get("exclude_overtime", False)),
            # Exit overrides (None = use strategy)
            exit_stop_loss_percent=_optional_float(data.get("exit", {}).get("stop_loss_percent")),
            exit_before_seconds=_optional_int(data.get("exit", {}).get("exit_before_seconds")),
            exit_profit_target_percent=_optional_float(data.get("exit", {}).get("profit_target_percent")),
            # Risk limits
            max_position_usdc=float(data.get("risk", {}).get("max_position_usdc", 100)),
            max_total_exposure_usdc=float(data.get("risk", {}).get("max_total_exposure_usdc", 500)),
            max_daily_loss_usdc=float(data.get("risk", {}).get("max_daily_loss_usdc", 100)),
            max_concurrent_positions=int(data.get("risk", {}).get("max_concurrent_positions", 5)),
            max_position_per_market=int(data.get("risk", {}).get("max_position_per_market", 2)),
            min_order_size_usdc=float(data.get("risk", {}).get("min_order_size_usdc", 5)),
            max_order_size_usdc=float(data.get("risk", {}).get("max_order_size_usdc", 50)),
            min_position_usdc=_optional_float(data.get("risk", {}).get("min_position_usdc")),
            # Allocation (bettable % of balance)
            max_portfolio_exposure=float(data.get("allocation", {}).get("max_portfolio_exposure", 0.50)),
            allocation_low_risk_percent=float(data.get("allocation", {}).get("low_risk_percent", 0.50)),
            allocation_medium_risk_percent=float(data.get("allocation", {}).get("medium_risk_percent", 0.35)),
            allocation_high_risk_percent=float(data.get("allocation", {}).get("high_risk_percent", 0.15)),
            # Strategy / conflict
            conflict_min_confidence=int(data.get("trading", {}).get("conflict_min_confidence", 7)),
            kelly_multiplier_override=_optional_float(data.get("position_sizing", {}).get("kelly_multiplier_override")),
            min_edge_strategy_overrides={
                str(k): float(v)
                for k, v in (data.get("edge", {}).get("min_edge_strategy_overrides") or {}).items()
            },
        )


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(
        self,
        config: BotConfig,
        executor: Optional[TradingExecutor] = None,
        data_manager: Optional[DataManager] = None,
    ):
        """Initialize trading bot.

        Args:
            config: Bot configuration
            executor: Trading executor (paper or live)
            data_manager: Data manager instance
        """
        self._config = config
        self._running = False

        # Core components (or test-game mocks)
        if config.test_game:
            n_ticks = config.test_game_ticks or 20
            self._data_manager = TestDataManager(n_game_states=n_ticks)
            self._market_mapper = TestMarketMapper()
            self._price_fetcher = TimeSeriesPriceFetcher(
                prices=generate_random_price_series(
                    n_ticks, condition_id=TEST_CONDITION_ID
                ),
                misprice_probability=0.15,
                misprice_min_pct=5.0,
                misprice_max_pct=12.0,
            )
            self._fallback_to_simulated = False
            logger.info("Test game mode: using mock game and time-series prices")
        else:
            self._data_manager = data_manager or DataManager()
            self._market_mapper = None
            self._price_fetcher = None
            self._fallback_to_simulated = config.polymarket_fallback_to_simulated

        if executor:
            self._executor = executor
        elif config.mode == "live":
            # Live trading requires private key from environment
            private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
            if not private_key:
                raise ValueError(
                    "POLYMARKET_PRIVATE_KEY environment variable required for live trading. "
                    "Set it in your .env file or environment."
                )
            from ..trading import LiveTradingExecutor
            self._executor = LiveTradingExecutor(
                private_key=private_key,
                rpc_url=os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com"),
                chain_id=int(os.environ.get("CHAIN_ID", "137")),
            )
            logger.info("Using LIVE trading executor")
        else:
            self._executor = PaperTradingExecutor(
                initial_balance=Decimal(str(config.bankroll))
            )
            logger.info("Using PAPER trading executor")

        # Trading components
        self._position_tracker = PositionTracker()
        risk_limits = RiskLimits(
            max_position_size_usdc=Decimal(str(config.max_position_usdc)),
            max_total_exposure_usdc=Decimal(str(config.max_total_exposure_usdc)),
            max_concurrent_positions=config.max_concurrent_positions,
            max_position_per_market=config.max_position_per_market,
            max_daily_loss_usdc=Decimal(str(config.max_daily_loss_usdc)),
            max_order_size_usdc=Decimal(str(config.max_order_size_usdc)),
            min_order_size_usdc=Decimal(str(config.min_order_size_usdc)),
        )
        self._risk_manager = RiskManager(
            limits=risk_limits,
            position_tracker=self._position_tracker,
        )
        self._order_manager = OrderManager(
            executor=self._executor,
            on_fill=self._on_order_fill,
            on_cancel=self._on_order_cancel,
        )

        # Strategy components (allocation = bettable % of balance by risk level)
        allocation = CapitalAllocation(
            low_risk_percent=config.allocation_low_risk_percent,
            medium_risk_percent=config.allocation_medium_risk_percent,
            high_risk_percent=config.allocation_high_risk_percent,
        )
        self._strategy_manager = StrategyManager(
            position_tracker=self._position_tracker,
            total_bankroll=Decimal(str(config.bankroll)),
            max_portfolio_exposure=config.max_portfolio_exposure,
            allocation=allocation,
            exit_stop_loss_pct_override=config.exit_stop_loss_percent,
            exit_time_stop_seconds_override=config.exit_before_seconds,
            exit_profit_target_percent_override=config.exit_profit_target_percent,
            conflict_min_confidence=config.conflict_min_confidence,
            kelly_multiplier_override=config.kelly_multiplier_override,
            min_position_usdc_override=config.min_position_usdc,
            min_edge_strategy_overrides=config.min_edge_strategy_overrides,
        )

        # Analysis components
        self._probability_calculator = ProbabilityCalculator()
        self._edge_detector = EdgeDetector(
            filter_config=EdgeFilter(
                min_edge_percent=config.min_edge_percent,
                max_edge_percent=config.max_edge_percent,
                min_confidence=config.min_confidence,
                min_market_price=Decimal(str(config.min_market_price)),
                max_market_price=Decimal(str(config.max_market_price)),
                min_time_remaining_seconds=config.min_time_remaining_seconds,
                exclude_overtime=config.exclude_overtime,
            )
        )
        self._context_builder = ContextBuilder()
        self._claude_analyzer = ClaudeAnalyzer() if config.claude_enabled else None

        # Performance tracking
        self._performance = PerformanceTracker(
            initial_equity=config.bankroll
        )
        self._trade_logger = TradeLogger()

        # Portfolio display
        self._portfolio_display = PortfolioDisplay(
            initial_balance=config.bankroll
        )

        # Polymarket integration for real market data (or test mocks already set)
        self._market_discovery = MarketDiscovery(
            gamma_api_url=config.polymarket_gamma_api,
            cache_ttl_seconds=config.polymarket_discovery_cache_ttl,
        )
        if not config.test_game:
            self._market_mapper = MarketMapper(
                discovery=self._market_discovery,
                mapping_ttl_seconds=config.polymarket_discovery_cache_ttl,
            )
            self._price_fetcher = PriceFetcher(
                clob_host=config.polymarket_clob_host,
            )
            self._fallback_to_simulated = config.polymarket_fallback_to_simulated

        # State
        self._iteration = 0
        self._active_games: dict[str, GameState] = {}
        self._token_id_to_game_id: dict[str, str] = {}
        self._command_server: Optional[asyncio.AbstractServer] = None

    async def start(self) -> None:
        """Start the trading bot."""
        logger.info(f"Starting PolyNBA bot in {self._config.mode} mode")
        logger.info(f"Bankroll: ${self._config.bankroll}")
        logger.info(f"Active strategies: {self._config.active_strategies}")

        # Load strategies
        self._strategy_manager.load_strategies(self._config.active_strategies)

        # Verify Polymarket API connection and log available markets
        await self._verify_polymarket_connection()

        # Start order manager
        await self._order_manager.start()
        await self._start_command_server()

        self._running = True

        try:
            await self._main_loop()
        except asyncio.CancelledError:
            logger.info("Bot cancelled")
        except Exception as e:
            logger.error(f"Bot error: {e}", exc_info=True)
        finally:
            await self.stop()

    async def _verify_polymarket_connection(self) -> None:
        """Verify Polymarket API connection and log available markets.

        This runs at startup to confirm we can fetch market data
        and to show what NBA markets are currently available.
        """
        if self._config.test_game:
            logger.info("Test game mode: skipping Polymarket API verification")
            return
        logger.info("")
        logger.info("Verifying Polymarket API connection...")

        try:
            # First, show all NBA-related markets (including futures)
            await self._market_discovery.log_all_nba_markets()

            # Then show game markets by date (today + next 2 days)
            markets_by_date = await self._market_discovery.log_market_summary(
                days_ahead=2,
                force_refresh=True,
            )

            total = sum(len(m) for m in markets_by_date.values())
            if total > 0:
                logger.info("Polymarket API connection verified - game markets found!")
            else:
                logger.warning(
                    "No individual NBA GAME markets found on Polymarket. "
                    "This is expected - Polymarket may only have futures/championship markets."
                )
                if self._fallback_to_simulated:
                    logger.info(
                        "Will use SIMULATED prices for live game trading. "
                        "This is normal for paper trading when no real game markets exist."
                    )

        except Exception as e:
            logger.error(f"Failed to verify Polymarket connection: {e}")
            if self._fallback_to_simulated:
                logger.info("Will proceed with simulated prices as fallback")
            else:
                logger.warning(
                    "Fallback to simulated prices is disabled. "
                    "Bot may not be able to trade without real market data."
                )

    async def stop(self) -> None:
        """Stop the trading bot."""
        logger.info("Stopping PolyNBA bot")
        self._running = False

        await self._stop_command_server()
        await self._order_manager.stop()
        await self._data_manager.close()
        await self._market_discovery.close()

        # Save performance data
        self._performance.save()

        logger.info("Bot stopped")

    async def _start_command_server(self) -> None:
        """Start the command server for interactive commands."""
        if not self._config.command_server_enabled:
            return

        port = (
            8765 + self._config.instance_id
            if self._config.instance_id is not None
            else self._config.command_server_port
        )
        try:
            self._command_server = await asyncio.start_server(
                self._handle_command_client,
                host=self._config.command_server_host,
                port=port,
            )
            logger.debug(
                "Command server listening on %s:%s",
                self._config.command_server_host,
                port,
            )
        except OSError as exc:
            self._command_server = None
            logger.warning("Command server failed to start: %s", exc)

    async def _stop_command_server(self) -> None:
        """Stop the command server if running."""
        if not self._command_server:
            return

        self._command_server.close()
        await self._command_server.wait_closed()
        self._command_server = None

    async def _main_loop(self) -> None:
        """Main trading loop."""
        while self._running:
            self._iteration += 1

            # Check iteration limit
            if (
                self._config.max_iterations
                and self._iteration > self._config.max_iterations
            ):
                logger.info(f"Reached max iterations ({self._config.max_iterations})")
                break

            try:
                await self._loop_iteration()
            except Exception as e:
                logger.error(f"Error in loop iteration: {e}", exc_info=True)

            # Sleep until next iteration
            await asyncio.sleep(self._config.loop_interval)

    async def _loop_iteration(self) -> None:
        """Single iteration of the main loop."""
        logger.info(f"Loop iteration {self._iteration}")

        self._token_id_to_game_id.clear()

        # 1. Get active games
        live_games = await self._data_manager.get_live_games()

        if not live_games:
            logger.info("No live games")
            return

        if self._config.allowed_game_ids is not None:
            live_games = [
                g for g in live_games if g.game_id in self._config.allowed_game_ids
            ]
            if not live_games:
                logger.info("No live games in selected set")
                return

        logger.info(f"Found {len(live_games)} live games")

        # 2. Process each game
        for game_summary in live_games:
            try:
                await self._process_game(game_summary.game_id)
            except Exception as e:
                logger.error(f"Error processing game {game_summary.game_id}: {e}")

        # 3. Manage existing positions
        await self._manage_positions()

        # 4. Take performance snapshot
        balance = await self._executor.get_balance()
        positions = self._position_tracker.get_all_positions()
        orders = self._order_manager.get_all_open_orders()

        self._performance.take_snapshot(
            deployed_capital=float(self._position_tracker.total_exposure()),
            unrealized_pnl=0.0,  # Would need price updates
            open_positions=len(positions),
            pending_orders=len(orders),
        )

        # 5. Display portfolio summary
        await self._print_portfolio_summary()

    async def _process_game(self, game_id: str) -> None:
        """Process a single game for trading opportunities."""
        # Get detailed game state
        game_state = await self._data_manager.get_game_state(game_id)
        if not game_state:
            logger.warning(f"Could not get game state for {game_id}")
            return

        # Skip if game is not tradeable
        if not game_state.is_live:
            logger.info(f"Game {game_id} is not live, skipping")
            return

        self._active_games[game_id] = game_state

        # Log game info
        logger.info(
            f"Processing: {game_state.away_team.team_abbreviation} @ "
            f"{game_state.home_team.team_abbreviation} | "
            f"{game_state.away_team.score}-{game_state.home_team.score} | "
            f"{game_state.period.display_name} {game_state.clock}"
        )

        # Get team stats
        home_stats = await self._data_manager.get_team_stats(
            game_state.home_team.team_id
        )
        away_stats = await self._data_manager.get_team_stats(
            game_state.away_team.team_id
        )

        if not home_stats or not away_stats:
            logger.warning(f"Missing team stats for game {game_id}")
            return

        logger.info(
            f"  Records: {game_state.home_team.team_abbreviation} "
            f"({home_stats.wins}-{home_stats.losses}) vs "
            f"{game_state.away_team.team_abbreviation} "
            f"({away_stats.wins}-{away_stats.losses})"
        )

        # Get market data (in real impl, would fetch from Polymarket)
        market_data = await self._get_market_data(game_id, game_state)
        if not market_data:
            return

        self._token_id_to_game_id[market_data["home_token_id"]] = game_id
        self._token_id_to_game_id[market_data["away_token_id"]] = game_id

        home_market_price = market_data["home_price"]
        away_market_price = market_data["away_price"]

        # Calculate probability estimate (buy prices = best ask per outcome)
        estimate = self._probability_calculator.calculate(
            game_state=game_state,
            home_market_price=home_market_price,
            home_stats=home_stats,
            away_stats=away_stats,
            away_market_price=away_market_price,
        )

        away_estimated = Decimal("1") - estimate.estimated_probability
        away_edge_pct = float((away_estimated - away_market_price) * 100)

        logger.info(
            f"  Market: {game_state.home_team.team_abbreviation} "
            f"{float(home_market_price):.1%} | "
            f"Edge: {estimate.edge_percentage:+.2f}% | "
            f"Confidence: {estimate.confidence}/10"
        )
        logger.info(
            f"  Market: {game_state.away_team.team_abbreviation} "
            f"{float(away_market_price):.1%} | "
            f"Edge: {away_edge_pct:+.2f}% | "
            f"Confidence: {estimate.confidence}/10"
        )

        # Optionally enhance with Claude analysis
        if self._claude_analyzer and abs(estimate.edge_percentage) >= 5:
            await self._enhance_with_claude(
                game_state, home_market_price, estimate, home_stats, away_stats
            )

        # Detect edge opportunities
        opportunities = self._edge_detector.detect(
            game_state=game_state,
            home_market_id=market_data["home_market_id"],
            home_token_id=market_data["home_token_id"],
            away_market_id=market_data["away_market_id"],
            away_token_id=market_data["away_token_id"],
            estimate=estimate,
        )

        filt = self._edge_detector.filter_config
        if not opportunities:
            if game_state.total_seconds_remaining < filt.min_time_remaining_seconds:
                logger.info(
                    f"  Filtered: not enough time remaining "
                    f"({game_state.total_seconds_remaining}s < {filt.min_time_remaining_seconds}s)"
                )
            elif filt.exclude_overtime and game_state.period.is_overtime:
                logger.info("  Filtered: overtime excluded")
            else:
                logger.info(
                    f"  No edge opportunity (need >= {filt.min_edge_percent}% edge)"
                )
        else:
            for opportunity in opportunities:
                logger.info(
                    f"  >>> EDGE FOUND: {opportunity.side.upper()} "
                    f"{opportunity.team_abbreviation} | "
                    f"Edge: {opportunity.edge_percentage:+.2f}% | "
                    f"EV: {opportunity.expected_value:.2%}"
                )

        # Evaluate against strategies
        for opportunity in opportunities:
            signals = self._strategy_manager.evaluate_opportunity(
                game_state, opportunity
            )

            if not signals:
                logger.info(
                    f"  No strategy signals for {opportunity.side} opportunity"
                )

            for signal in signals:
                logger.info(
                    f"  >>> SIGNAL: {signal.strategy_id} | "
                    f"{signal.action.upper()} {signal.side} | "
                    f"Size: ${float(signal.size):.2f} @ {float(signal.price):.4f}"
                )
                await self._execute_signal(signal)

    async def _get_market_data(
        self, game_id: str, game_state: GameState
    ) -> Optional[dict[str, Any]]:
        """Get market data for a game.

        Attempts to fetch real Polymarket prices first, falling back
        to simulated prices if no market is found or fetch fails.

        Args:
            game_id: ESPN game ID
            game_state: Current game state

        Returns:
            Market data dict with prices and token IDs
        """
        # Try to find real Polymarket market
        try:
            mapping = await self._market_mapper.get_market_for_game(game_state)

            if mapping is not None:
                # Fetch real prices (test game: prices from game state; live: from API)
                prices = await self._price_fetcher.get_market_prices(
                    mapping.polymarket_market,
                    game_state=game_state if self._config.test_game else None,
                )

                if prices is not None:
                    # Buy price = best ask (probability in cents: 73 cents = 73%)
                    home_buy_price = prices.home_best_ask or prices.home_mid_price
                    away_buy_price = prices.away_best_ask or prices.away_mid_price
                    logger.info(
                        f"  [Real Polymarket prices] "
                        f"home={float(home_buy_price):.1%}, away={float(away_buy_price):.1%} (buy)"
                    )
                    self._update_paper_market_data(
                        market_id=mapping.polymarket_market.condition_id,
                        token_id=mapping.polymarket_market.home_token_id,
                        mid_price=home_buy_price,
                        best_bid=prices.home_best_bid,
                        best_ask=prices.home_best_ask,
                        outcome="home",
                    )
                    self._update_paper_market_data(
                        market_id=mapping.polymarket_market.condition_id,
                        token_id=mapping.polymarket_market.away_token_id,
                        mid_price=away_buy_price,
                        best_bid=prices.away_best_bid,
                        best_ask=prices.away_best_ask,
                        outcome="away",
                    )
                    return {
                        "home_market_id": mapping.polymarket_market.condition_id,
                        "home_token_id": mapping.polymarket_market.home_token_id,
                        "away_market_id": mapping.polymarket_market.condition_id,
                        "away_token_id": mapping.polymarket_market.away_token_id,
                        "home_price": home_buy_price,
                        "away_price": away_buy_price,
                        "source": "polymarket",
                        "liquidity": mapping.polymarket_market.liquidity,
                    }
                else:
                    logger.warning(
                        f"Could not fetch prices for mapped market "
                        f"(condition_id={mapping.polymarket_market.condition_id})"
                    )
            else:
                logger.debug(f"No Polymarket market found for game {game_id}")

        except Exception as e:
            logger.error(f"Error fetching Polymarket data: {e}")

        # Fallback to simulated prices
        if not self._fallback_to_simulated:
            logger.warning(f"No real market data and fallback disabled for {game_id}")
            return None

        simulated = self._get_simulated_market_data(game_id, game_state)
        self._update_paper_market_data(
            market_id=simulated["home_market_id"],
            token_id=simulated["home_token_id"],
            mid_price=simulated["home_price"],
            outcome="home",
        )
        self._update_paper_market_data(
            market_id=simulated["away_market_id"],
            token_id=simulated["away_token_id"],
            mid_price=simulated["away_price"],
            outcome="away",
        )
        return simulated

    def _get_simulated_market_data(
        self, game_id: str, game_state: GameState
    ) -> dict[str, Any]:
        """Get simulated market data based on game state.

        Used as fallback when no Polymarket market is found.

        Args:
            game_id: ESPN game ID
            game_state: Current game state

        Returns:
            Simulated market data dict
        """
        home_prob = self._estimate_naive_probability(game_state)

        logger.info(
            f"  [Simulated prices] "
            f"home={home_prob:.1%}, away={1-home_prob:.1%}"
        )

        return {
            "home_market_id": f"{game_id}_home",
            "home_token_id": f"{game_id}_home_token",
            "away_market_id": f"{game_id}_away",
            "away_token_id": f"{game_id}_away_token",
            "home_price": Decimal(str(round(home_prob, 4))),
            "away_price": Decimal(str(round(1 - home_prob, 4))),
            "source": "simulated",
            "liquidity": Decimal("0"),
        }

    def _update_paper_market_data(
        self,
        market_id: str,
        token_id: str,
        mid_price: Decimal,
        best_bid: Optional[Decimal] = None,
        best_ask: Optional[Decimal] = None,
        outcome: str = "",
    ) -> None:
        """Update paper executor market data cache for fills."""
        if not isinstance(self._executor, PaperTradingExecutor):
            return

        bid = best_bid if best_bid is not None else mid_price
        ask = best_ask if best_ask is not None else mid_price

        market_data = MarketData(
            market_id=market_id,
            condition_id=market_id,
            token_id=token_id,
            question="",
            outcome=outcome,
            best_bid=bid,
            best_ask=ask,
            last_price=mid_price,
            volume_24h=Decimal("0"),
            liquidity=Decimal("0"),
        )
        self._executor.set_market_data(token_id, market_data)

    def _estimate_naive_probability(self, game: GameState) -> float:
        """Estimate naive win probability from game state.

        Uses a simple logistic model based on score differential
        and time remaining.

        Args:
            game: Current game state

        Returns:
            Estimated home team win probability (0.0 to 1.0)
        """
        diff = game.score_differential
        minutes = game.total_seconds_remaining / 60

        # Simple logistic model
        # Each point lead = ~2% more likely to win
        # Effect increases as time decreases
        time_factor = max(0.1, minutes / 48)
        point_factor = diff * 0.02 / time_factor

        # Sigmoid transformation
        prob = 1 / (1 + math.exp(-point_factor))

        # Add some noise for realism in paper trading
        noise = random.uniform(-0.03, 0.03)

        return max(0.05, min(0.95, prob + noise))

    async def _enhance_with_claude(
        self,
        game_state: GameState,
        home_market_price: Decimal,
        estimate,
        home_stats: TeamStats,
        away_stats: TeamStats,
    ) -> None:
        """Enhance analysis with Claude."""
        if not self._claude_analyzer:
            return

        context = self._context_builder.build(
            game_state=game_state,
            home_market_price=home_market_price,
            estimate=estimate,
            home_stats=home_stats,
            away_stats=away_stats,
        )

        analysis = await self._claude_analyzer.analyze(
            game_context=context.game_context,
            market_context=context.market_context,
            quant_analysis=context.quant_analysis,
            game_id=game_state.game_id,
        )

        if analysis:
            logger.info(
                f"Claude analysis for {game_state.game_id}: "
                f"{analysis.market_assessment} (conf: {analysis.confidence})"
            )

    async def _execute_signal(self, signal: TradingSignal) -> None:
        """Execute a trading signal."""
        # Check risk
        risk_check = self._risk_manager.check_order(
            market_id=signal.market_id,
            token_id=signal.token_id,
            side=signal.action,
            size=signal.size,
            price=signal.price,
        )

        if not risk_check.allowed:
            logger.warning(f"Signal rejected by risk manager: {risk_check.reason}")
            return

        # Adjust size if needed
        size = risk_check.adjusted_size or signal.size

        # Log signal
        self._trade_logger.log_signal(
            strategy_id=signal.strategy_id,
            game_id=signal.game_id,
            side=signal.side,
            edge=signal.edge_percentage,
            confidence=signal.confidence,
            size=float(size),
        )

        # Submit order
        from ..data.models import TradeSide
        side = TradeSide.BUY if signal.action == "buy" else TradeSide.SELL

        result = await self._order_manager.submit_order(
            market_id=signal.market_id,
            token_id=signal.token_id,
            side=side,
            size=size,
            price=signal.price,
            strategy_id=signal.strategy_id,
        )

        if result.success:
            self._trade_logger.log_order(
                order_id=result.order.order_id,
                action="submit",
                market_id=signal.market_id,
                side=signal.action,
                size=float(size),
                price=float(signal.price),
            )

    async def _manage_positions(self) -> None:
        """Manage existing positions."""
        positions = self._position_tracker.get_all_positions()
        if not positions:
            return
        logger.info(f"  [Exit check] Evaluating {len(positions)} position(s)")
        # Get current prices for all positions (best bid = sell price)
        price_map = {}
        for position in positions:
            sell_price = await asyncio.to_thread(
                self._price_fetcher.get_token_sell_price, position.token_id
            )
            price_map[position.token_id] = (
                sell_price if sell_price is not None else position.avg_entry_price
            )

        for position in positions:
            game_id = self._token_id_to_game_id.get(position.token_id)
            if game_id is None:
                continue
            game_state = self._active_games.get(game_id)
            if game_state is None:
                continue
            exit_signal = self._strategy_manager.evaluate_position(
                position, game_state, price_map
            )
            if exit_signal is not None:
                await self._execute_exit(exit_signal)

    async def _execute_exit(self, exit_signal) -> None:
        """Execute a position exit."""
        position = exit_signal.position

        # Submit sell order
        from ..data.models import TradeSide

        result = await self._order_manager.submit_order(
            market_id=position.market_id,
            token_id=position.token_id,
            side=TradeSide.SELL,
            size=position.size,
            price=position.avg_entry_price,  # Market order in real impl
            strategy_id=position.strategy_id,
        )

        if result.success:
            logger.info(
                f"Exit order submitted for {position.token_id}: {exit_signal.reason}"
            )

    def _on_order_fill(self, order) -> None:
        """Callback when order fills."""
        trade = self._position_tracker.record_fill(order)

        if trade:
            self._trade_logger.log_fill(
                order_id=order.order_id,
                fill_price=float(order.avg_fill_price),
                fill_size=float(order.filled_size),
            )

    def _on_order_cancel(self, order) -> None:
        """Callback when order cancels."""
        logger.info(f"Order cancelled: {order.order_id}")

    async def _handle_command_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single command connection."""
        try:
            data = await reader.readline()
            if not data:
                return

            command = data.decode(errors="ignore").strip()
            response = await self._handle_command(command)

            if not response.endswith("\n"):
                response += "\n"
            writer.write(response.encode())
            await writer.drain()
        except Exception as exc:
            try:
                writer.write(f"Command error: {exc}\n".encode())
                await writer.drain()
            except Exception:
                pass
            logger.debug("Command handler error: %s", exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_command(self, command: str) -> str:
        """Dispatch an interactive command."""
        if not command:
            return (
                "Empty command. Use: show portfolio | show trades [N] | show positions"
            )

        parts = command.split()
        if len(parts) >= 2 and parts[0].lower() == "show":
            subcommand = parts[1].lower()

            if subcommand == "portfolio":
                snapshot = await self._build_portfolio_snapshot()
                if self._config.portfolio_display_compact:
                    return self._portfolio_display.format_compact_summary(snapshot)
                return self._portfolio_display.format_summary(snapshot)

            if subcommand == "trades":
                limit = 20
                if len(parts) >= 3:
                    try:
                        limit = int(parts[2])
                    except ValueError:
                        return "Invalid trade limit. Use: show trades [N]"
                    if limit <= 0:
                        return "Trade limit must be a positive integer."
                trades = self._position_tracker.get_trades(limit=limit)
                return self._portfolio_display.format_trades(trades)

            if subcommand == "positions":
                positions = self._position_tracker.get_all_positions()
                return self._portfolio_display.format_positions(positions)

        return "Unknown command. Valid: show portfolio | show trades [N] | show positions"

    async def _build_portfolio_snapshot(self) -> "PortfolioSnapshot":
        """Build a portfolio snapshot for display or command output."""
        from datetime import datetime

        from ..utils.portfolio_display import PortfolioSnapshot

        balance = await self._executor.get_balance()
        performance_summary = self._performance.get_summary()
        risk_stats = self._risk_manager.stats
        position_stats = self._position_tracker.stats

        # Fetch current prices for unrealized P&L
        price_map = {}
        for position in self._position_tracker.get_all_positions():
            sell_price = await asyncio.to_thread(
                self._price_fetcher.get_token_sell_price, position.token_id
            )
            price_map[position.token_id] = (
                sell_price if sell_price is not None else position.avg_entry_price
            )
        unrealized_pnl = self._position_tracker.total_unrealized_pnl(price_map)
        # Realized P&L from position tracker (updated on every closing fill); performance
        # tracker total_pnl is only updated when record_trade() is called (not wired for fills).
        realized_pnl = Decimal(str(position_stats.get("total_realized_pnl", 0)))

        return PortfolioSnapshot(
            session_start=self._portfolio_display.session_start,
            current_time=datetime.now(),
            iteration=self._iteration,
            initial_balance=self._portfolio_display.initial_balance,
            current_balance=balance.usdc,
            available_balance=balance.available_usdc,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_trades=performance_summary.get("total_trades", 0),
            winning_trades=performance_summary.get("winning_trades", 0),
            losing_trades=performance_summary.get("losing_trades", 0),
            open_positions=position_stats.get("open_positions", 0),
            pending_orders=self._order_manager.stats.get("pending_count", 0),
            total_exposure=Decimal(str(position_stats.get("total_exposure", 0))),
            max_drawdown_pct=performance_summary.get("max_drawdown_percent", 0),
            circuit_breaker_active=risk_stats.get("circuit_breaker_active", False),
        )

    async def _print_portfolio_summary(self) -> None:
        """Print a portfolio summary to the console."""
        # Check if display is enabled
        if self._config.portfolio_display_interval <= 0:
            return

        # Check if it's time to display
        if self._iteration % self._config.portfolio_display_interval != 0:
            return

        snapshot = await self._build_portfolio_snapshot()

        # Format and print
        if self._config.portfolio_display_compact:
            output = self._portfolio_display.format_compact_summary(snapshot)
        else:
            output = self._portfolio_display.format_summary(snapshot)

        # Print directly (bypasses logging to stand out)
        print(output)


async def run_bot(config_path: Optional[Path] = None) -> None:
    """Run the trading bot.

    Args:
        config_path: Path to config file
    """
    # Load config
    if config_path and config_path.exists():
        config = BotConfig.from_yaml(config_path)
    else:
        config = BotConfig()

    # Setup logging
    setup_logging(level=config.log_level)

    # Create and run bot
    bot = TradingBot(config)

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        await bot.stop()
