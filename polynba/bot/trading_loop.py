"""Main trading loop orchestration."""

import asyncio
import hashlib
import logging
import math
import os
import random
import time
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
from ..data.models import GameStatus, Period, TeamContext, TradeSide
from ..polymarket import (
    MarketDiscovery,
    MarketMapper,
    PriceFetcher,
    TimeSeriesPriceFetcher,
    generate_random_price_series,
)
from ..testing import LiveTestPriceSimulator, TestDataManager, TestMarketMapper
from ..testing.mock_mapper import TEST_CONDITION_ID
from ..strategy import CapitalAllocation, ExitSignal, StrategyManager, TradingSignal
from ..trading import (
    DelayConfig,
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
    position_check_interval: int = 5  # seconds between background position checks
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
    test_game_scenario: Optional[str] = None  # Scenario name (e.g. "home_blowout", "random")

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

    # Volatility filter: raise min_edge when game is tight + late
    volatility_score_threshold: int = 5
    volatility_period_threshold: int = 3
    volatility_edge_multiplier: float = 1.5

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

    # Conviction bets
    conviction_min_probability: float = 0.0  # 0 = disabled; e.g. 0.65 = 65% threshold

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
            position_check_interval=data.get("loop", {}).get("position_check_interval", 5),
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
            # Volatility filter
            volatility_score_threshold=int(data.get("edge", {}).get("volatility", {}).get("score_threshold", 5)),
            volatility_period_threshold=int(data.get("edge", {}).get("volatility", {}).get("period_threshold", 3)),
            volatility_edge_multiplier=float(data.get("edge", {}).get("volatility", {}).get("edge_multiplier", 1.5)),
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
            # Conviction
            conviction_min_probability=float(data.get("conviction", {}).get("min_probability", 0.0)),
        )


class TradingBot:
    """Main trading bot orchestrator."""

    AI_ANALYSIS_MIN_INTERVAL = 180  # Minimum seconds between AI analyses per game

    def __init__(
        self,
        config: BotConfig,
        executor: Optional[TradingExecutor] = None,
        data_manager: Optional[DataManager] = None,
        log_dir: Optional[Path] = None,
        start_ts: str = "",
    ):
        """Initialize trading bot.

        Args:
            config: Bot configuration
            executor: Trading executor (paper or live)
            data_manager: Data manager instance
            log_dir: Log directory path for this session
            start_ts: Timestamp string used in the log directory name
        """
        self._config = config
        self._running = False
        self._log_dir = log_dir
        self._start_ts = start_ts
        self._game_identity: Optional[tuple[str, str]] = None

        # Core components (or test-game mocks)
        self._live_simulator = None
        if config.test_game:
            n_ticks = config.test_game_ticks or 20
            self._data_manager = TestDataManager(
                n_game_states=n_ticks, scenario=config.test_game_scenario
            )
            self._market_mapper = TestMarketMapper()
            self._live_simulator = LiveTestPriceSimulator(
                market=self._market_mapper._market,
                misprice_probability=0.40,
                misprice_min_pct=6.0,
                misprice_max_pct=15.0,
            )
            self._price_fetcher = TimeSeriesPriceFetcher(
                prices=generate_random_price_series(
                    n_ticks, condition_id=TEST_CONDITION_ID
                ),
                live_simulator=self._live_simulator,
            )
            self._fallback_to_simulated = False
            logger.info("Test game mode: using mock game with live price simulator")
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
                funder=os.environ.get("POLYMARKET_FUNDER_ADDRESS"),
            )
            logger.info("Using LIVE trading executor")
        else:
            self._executor = PaperTradingExecutor(
                initial_balance=Decimal(str(config.bankroll)),
                live_price_source=(
                    self._live_simulator.get_market_data_for_token
                    if self._live_simulator
                    else None
                ),
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
        # In test-game mode, enable auto-cancel with the live price simulator
        # providing micro-tick noise during the 3s delay so prices evolve
        # realistically between delay checks.
        delay_cfg = (
            DelayConfig(enable_auto_cancel=True)
            if config.test_game
            else None
        )
        self._order_manager = OrderManager(
            executor=self._executor,
            config=delay_cfg,
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
                volatility_score_threshold=config.volatility_score_threshold,
                volatility_period_threshold=config.volatility_period_threshold,
                volatility_edge_multiplier=config.volatility_edge_multiplier,
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
        self._ai_analysis_log: list[dict] = []
        self._last_live_balance: Optional[Decimal] = None

        # Per-game risk tracking (mirrors replay_engine logic)
        self._last_stop_loss_iteration: dict[str, int] = {}   # token_id -> iteration
        self._game_stop_loss_count: dict[str, int] = {}        # game_id -> count
        self._game_cumulative_pnl: dict[str, Decimal] = {}     # game_id -> PnL

        # AI analysis deduplication and rate limiting
        self._last_analyzed_state: dict[str, str] = {}  # game_id -> state hash
        self._last_ai_call_time: dict[str, float] = {}  # game_id -> timestamp
        self._last_analyzed_score: dict[str, tuple[int, int]] = {}  # game_id -> (home, away)

        # Conviction: store latest Claude analysis per game for conviction entry checks
        self._last_claude_analysis: dict = {}  # game_id -> ClaudeAnalysisResponse

    async def start(self) -> None:
        """Start the trading bot."""
        logger.info(f"Starting PolyNBA bot in {self._config.mode} mode")
        logger.info(f"Bankroll: ${self._config.bankroll}")
        logger.info(f"Active strategies: {self._config.active_strategies}")

        # Load strategies
        self._strategy_manager.load_strategies(self._config.active_strategies)

        # In live mode, fetch real balance and update initial balance
        if self._config.mode == "live":
            try:
                balance = await self._executor.get_balance()
                if balance.usdc > 0:
                    self._config.bankroll = float(balance.usdc)
                    self._portfolio_display._initial_balance = balance.usdc
                    self._performance._initial_equity = float(balance.usdc)
                    self._performance._current_equity = float(balance.usdc)
                    self._performance._peak_equity = float(balance.usdc)
                    self._last_live_balance = balance.usdc
                    self._strategy_manager.update_bankroll(balance.usdc)
                    logger.info(f"Live balance: ${balance.usdc:.2f} USDC")
                    print(f"\n  Live bankroll: ${balance.usdc:.2f} USDC (from wallet)\n")
            except Exception as e:
                logger.warning(f"Could not fetch live balance: {e}")

        # Verify Polymarket API connection and log available markets
        await self._verify_polymarket_connection()

        # Start order manager
        await self._order_manager.start()
        await self._start_command_server()

        self._running = True
        position_monitor = asyncio.create_task(self._position_monitor_loop())

        try:
            await self._main_loop()
        except asyncio.CancelledError:
            logger.info("Bot cancelled")
        except Exception as e:
            logger.error(f"Bot error: {e}", exc_info=True)
        finally:
            position_monitor.cancel()
            try:
                await position_monitor
            except asyncio.CancelledError:
                pass
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

        # Close all open positions while order manager is still active
        try:
            await self._close_all_positions()
        except Exception as e:
            logger.error(f"Error closing positions during shutdown: {e}")

        # Generate summary after closing positions so it reflects final PnL
        self._write_summary()

        self._running = False

        await self._stop_command_server()
        await self._order_manager.stop()
        await self._data_manager.close()
        await self._market_discovery.close()

        # Save performance data
        self._performance.save()

        logger.info("Bot stopped")

    def _generate_session_summary(self) -> str:
        """Generate a text summary of the trading session."""
        from datetime import datetime

        lines: list[str] = []
        now = datetime.now()
        session_start = self._portfolio_display.session_start
        duration = now - session_start

        hours, remainder = divmod(int(duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        # --- Session Info ---
        lines.append("=" * 60)
        lines.append("  PolyNBA Session Summary")
        lines.append("=" * 60)
        lines.append("")
        lines.append("SESSION INFO")
        lines.append(f"  Mode:           {self._config.mode}")
        lines.append(f"  Start:          {session_start.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  End:            {now.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  Duration:       {hours}h {minutes}m {seconds}s")
        lines.append(f"  Iterations:     {self._iteration}")
        lines.append(f"  Bankroll:       ${self._config.bankroll:.2f}")
        lines.append("")

        # --- Game ---
        lines.append("GAME")
        if self._game_identity:
            away, home = self._game_identity
            lines.append(f"  Matchup:        {away} @ {home}")
        else:
            lines.append("  No game was processed during this session.")

        # Last known score from active games
        for gid, gs in self._active_games.items():
            away_abbr = gs.away_team.team_abbreviation
            home_abbr = gs.home_team.team_abbreviation
            lines.append(
                f"  Last score:     {away_abbr} {gs.away_team.score} - "
                f"{home_abbr} {gs.home_team.score}  "
                f"({gs.period.display_name} {gs.clock})"
            )
        lines.append("")

        # --- Strategies ---
        lines.append("STRATEGIES")
        for sid in self._strategy_manager.active_strategies:
            strategy = self._strategy_manager.get_strategy(sid)
            stats = self._strategy_manager.get_strategy_stats(sid)

            desc = ""
            if strategy and strategy.metadata:
                desc = f" - {strategy.metadata.description}" if strategy.metadata.description else ""

            lines.append(f"  [{sid}]{desc}")
            lines.append(
                f"    Signals: {stats.get('signals_generated', 0)}  "
                f"Trades: {stats.get('trades_executed', 0)}  "
                f"W/L: {stats.get('wins', 0)}/{stats.get('losses', 0)}  "
                f"PnL: ${float(stats.get('total_pnl', 0)):.2f}"
            )
        lines.append("")

        # --- Trade Log ---
        trades = self._position_tracker.get_trades(limit=9999)
        lines.append("TRADE LOG")
        if trades:
            lines.append(f"  {'Time':<20} {'Side':<5} {'Size':>10} {'Price':>8} {'Strategy':<16}")
            lines.append(f"  {'-'*20} {'-'*5} {'-'*10} {'-'*8} {'-'*16}")
            for t in trades:
                ts = t.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                side_str = t.side.value if hasattr(t.side, 'value') else str(t.side)
                lines.append(
                    f"  {ts:<20} {side_str:<5} "
                    f"${float(t.size * t.price):>9.2f} "
                    f"{float(t.price):>7.4f} "
                    f"{t.strategy_id or 'N/A':<16}"
                )
        else:
            lines.append("  No trades executed.")
        lines.append("")

        # --- Open Positions at Shutdown ---
        positions = self._position_tracker.get_all_positions()
        lines.append("OPEN POSITIONS AT SHUTDOWN")
        if positions:
            for p in positions:
                side_str = p.side.value if hasattr(p.side, 'value') else str(p.side)
                lines.append(
                    f"  {side_str} {float(p.size):.4f} @ {float(p.avg_entry_price):.4f}  "
                    f"cost=${float(p.total_cost):.2f}  strategy={p.strategy_id or 'N/A'}"
                )
        else:
            lines.append("  No open positions.")
        lines.append("")

        # --- Performance ---
        lines.append("PERFORMANCE")
        perf = self._performance.get_summary()
        pos_stats = self._position_tracker.stats
        realized_pnl = float(self._position_tracker.total_realized_pnl())
        completed = pos_stats.get("completed_trades", 0)
        wins = pos_stats.get("winning_trades", 0)
        losses = pos_stats.get("losing_trades", 0)
        win_rate = wins / completed if completed > 0 else 0.0

        lines.append(f"  Initial equity:   ${perf.get('initial_equity', 0):.2f}")
        lines.append(f"  Current equity:   ${perf.get('current_equity', 0):.2f}")
        lines.append(f"  Total PnL:        ${perf.get('total_pnl', 0):.2f}")
        lines.append(f"  Return:           {perf.get('total_return_percent', 0):.2f}%")
        lines.append(f"  Realized PnL:     ${realized_pnl:.2f}")
        lines.append(f"  Total trades:     {completed}")
        lines.append(f"  Win rate:         {win_rate:.1%}")
        lines.append(f"  Max drawdown:     {perf.get('max_drawdown_percent', 0):.2f}%")
        lines.append("")

        # --- AI Analysis Log ---
        if self._claude_analyzer:
            if self._ai_analysis_log:
                n = len(self._ai_analysis_log)
                lines.append(f"AI ANALYSIS LOG ({n} {'analysis' if n == 1 else 'analyses'})")
                for idx, entry in enumerate(self._ai_analysis_log, 1):
                    ts = entry["timestamp"].strftime("%H:%M:%S")
                    edge_str = f"{entry['edge_pct']:+.1f}%"
                    lines.append(
                        f"  #{idx} [Iter {entry['iteration']}] {ts} | "
                        f"{entry['score']} ({entry['period']}) | Edge: {edge_str}"
                    )
                    lines.append(
                        f"     Assessment: {entry['assessment']} "
                        f"(conf {entry['ai_confidence']}/10) | "
                        f"Adj: sent={entry['sentiment_adj']:+d} ctx={entry['context_adj']:+d}"
                    )
                    factors = ", ".join(entry["key_factors"]) if entry["key_factors"] else "none"
                    lines.append(f"     Factors: {factors}")
                    lines.append(f"     Reasoning: {entry['reasoning']}")
                    # Outcome line
                    opps = entry.get("opportunities", 0)
                    sigs = entry.get("signals", 0)
                    if sigs > 0:
                        outcome = f"{opps} edge found, {sigs} signal(s) executed"
                    elif opps > 0:
                        outcome = f"{opps} edge found, 0 signals"
                    else:
                        outcome = "no edge found"
                    lines.append(f"     Outcome: {outcome}")
                    lines.append("")
            else:
                lines.append("AI ANALYSIS LOG")
                lines.append("  Claude AI was enabled but no analyses were triggered.")
                lines.append("")

            usage = self._claude_analyzer.usage_stats
            lines.append(f"  Claude Usage: {usage.get('total_requests', 0)} requests, "
                         f"${usage.get('total_cost_usd', 0):.4f} total cost")
        else:
            lines.append("AI ANALYSIS LOG")
            lines.append("  Claude AI was not used this session.")
        lines.append("")

        # --- Final Portfolio Snapshot (ASCII box) ---
        try:
            from ..utils.portfolio_display import PortfolioSnapshot

            # Build snapshot from data already available (no async calls)
            pos_stats_snap = self._position_tracker.stats
            realized = self._position_tracker.total_realized_pnl()
            exposure = Decimal(str(pos_stats_snap.get("total_exposure", 0)))

            # Best-effort balance: use cached live balance if available,
            # otherwise fall back to paper executor's _balance or config bankroll
            if hasattr(self, '_last_live_balance') and self._last_live_balance is not None:
                balance_usdc = self._last_live_balance
                available_usdc = balance_usdc - exposure
            elif hasattr(self._executor, '_balance'):
                balance_usdc = self._executor._balance
                available_usdc = balance_usdc - exposure
            else:
                balance_usdc = Decimal(str(self._config.bankroll))
                available_usdc = balance_usdc

            snapshot = PortfolioSnapshot(
                session_start=self._portfolio_display.session_start,
                current_time=now,
                iteration=self._iteration,
                initial_balance=self._portfolio_display.initial_balance,
                current_balance=balance_usdc,
                available_balance=available_usdc,
                realized_pnl=realized,
                unrealized_pnl=Decimal("0"),
                total_trades=pos_stats_snap.get("completed_trades", 0),
                winning_trades=pos_stats_snap.get("winning_trades", 0),
                losing_trades=pos_stats_snap.get("losing_trades", 0),
                open_positions=pos_stats_snap.get("open_positions", 0),
                pending_orders=self._order_manager.stats.get("pending_count", 0),
                total_exposure=exposure,
                max_drawdown_pct=perf.get("max_drawdown_percent", 0),
                circuit_breaker_active=self._risk_manager.stats.get(
                    "circuit_breaker_active", False
                ),
            )
            lines.append(self._portfolio_display.format_summary(snapshot))
        except Exception as e:
            logger.debug(f"Could not build final portfolio snapshot: {e}")

        lines.append("=" * 60)

        return "\n".join(lines)

    def _write_summary(self) -> None:
        """Write session summary to file and print to console."""
        try:
            summary = self._generate_session_summary()
        except Exception as e:
            logger.warning(f"Failed to generate session summary: {e}")
            return

        # Print to console
        print("\n" + summary)

        # Write to file
        if self._log_dir:
            try:
                self._log_dir.mkdir(parents=True, exist_ok=True)
                summary_path = self._log_dir / "summary.txt"
                summary_path.write_text(summary)
                logger.info(f"Session summary written to {summary_path}")
            except Exception as e:
                logger.warning(f"Failed to write summary file: {e}")

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
            self._no_game_count = getattr(self, '_no_game_count', 0) + 1
            if self._config.test_game and self._no_game_count >= 3:
                logger.info("Test game ended. Stopping bot.")
                self._running = False
                return
            logger.info("No live games")
            return
        self._no_game_count = 0

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
        self._last_live_balance = balance.usdc
        # Sync performance tracker equity with real wallet balance in live mode
        if self._config.mode == "live":
            self._performance._current_equity = float(balance.usdc)
            if float(balance.usdc) > self._performance._peak_equity:
                self._performance._peak_equity = float(balance.usdc)
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

    def _should_run_ai_analysis(self, game_id: str, game_state: GameState) -> bool:
        """Check whether AI analysis should run for the given game state.

        Returns False (skip) when:
        - The game is at halftime or end-of-period
        - The game state (score/period/clock) is unchanged since last analysis
        - Not enough time has elapsed AND the score hasn't jumped by >= 3 points
        """
        # Check 1: Skip during halftime or end-of-period breaks
        if game_state.status in {GameStatus.HALFTIME, GameStatus.END_OF_PERIOD}:
            logger.debug(f"  AI analysis skipped for {game_id}: {game_state.status.value}")
            return False

        # Check 2: Has game state changed since last analysis?
        state_hash = hashlib.md5(
            f"{game_state.home_team.score}:{game_state.away_team.score}"
            f":{game_state.period.value}:{game_state.clock}".encode()
        ).hexdigest()
        if self._last_analyzed_state.get(game_id) == state_hash:
            logger.debug(f"  AI analysis skipped for {game_id}: game state unchanged")
            return False

        # Check 3: Rate limiting — require minimum interval, unless score jumped >= 3
        last_call = self._last_ai_call_time.get(game_id, 0.0)
        elapsed = time.time() - last_call
        if elapsed < self.AI_ANALYSIS_MIN_INTERVAL:
            last_score = self._last_analyzed_score.get(game_id, (0, 0))
            score_delta = abs(game_state.home_team.score - last_score[0]) + abs(
                game_state.away_team.score - last_score[1]
            )
            if score_delta < 3:
                logger.debug(
                    f"  AI analysis skipped for {game_id}: rate limited "
                    f"({elapsed:.0f}s < {self.AI_ANALYSIS_MIN_INTERVAL}s, "
                    f"score delta={score_delta})"
                )
                return False

        # All checks passed — update tracking state
        self._last_analyzed_state[game_id] = state_hash
        self._last_ai_call_time[game_id] = time.time()
        self._last_analyzed_score[game_id] = (
            game_state.home_team.score,
            game_state.away_team.score,
        )
        return True

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

        # One-time game identity capture for log directory naming
        if self._game_identity is None:
            away_abbr = game_state.away_team.team_abbreviation
            home_abbr = game_state.home_team.team_abbreviation
            self._game_identity = (away_abbr, home_abbr)
            self._rename_log_dir(away_abbr, home_abbr)

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

        # Fetch team contexts (includes injuries)
        home_context = await self._data_manager.get_team_context(
            game_state.home_team.team_id, game_state.away_team.team_id
        )
        away_context = await self._data_manager.get_team_context(
            game_state.away_team.team_id, game_state.home_team.team_id
        )

        home_abbr = game_state.home_team.team_abbreviation
        away_abbr = game_state.away_team.team_abbreviation

        logger.info(
            f"  Records: {home_abbr} "
            f"({home_stats.wins}-{home_stats.losses}) vs "
            f"{away_abbr} "
            f"({away_stats.wins}-{away_stats.losses})"
        )

        if home_context and home_context.key_players_out:
            logger.info(f"  {home_abbr} injuries: {', '.join(i.player_name for i in home_context.key_players_out)}")
        if away_context and away_context.key_players_out:
            logger.info(f"  {away_abbr} injuries: {', '.join(i.player_name for i in away_context.key_players_out)}")

        # Skip new analysis and entries during halftime/breaks
        if game_state.status in (GameStatus.HALFTIME, GameStatus.END_OF_PERIOD):
            logger.info(f"  Game is at {game_state.status.value}, skipping analysis and entries")
            return

        # Block entries near halftime to avoid volatility spike
        if game_state.period == Period.SECOND_QUARTER and game_state.clock_seconds <= 120:
            logger.info(f"  Near halftime ({game_state.clock_seconds}s left in Q2), skipping entries")
            return

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
            home_context=home_context,
            away_context=away_context,
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
        conviction_thresh = self._config.conviction_min_probability
        high_prob_for_ai = conviction_thresh > 0 and (
            float(estimate.estimated_probability) >= conviction_thresh
            or float(Decimal("1") - estimate.estimated_probability) >= conviction_thresh
        )
        if self._claude_analyzer and (
            abs(estimate.edge_percentage) >= self._config.min_edge_percent
            or high_prob_for_ai
        ):
            if self._should_run_ai_analysis(game_id, game_state):
                await self._enhance_with_claude(
                    game_state, home_market_price, estimate, home_stats, away_stats,
                    home_context=home_context, away_context=away_context,
                )
            else:
                logger.debug(f"  AI analysis skipped for {game_id}")

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
                effective = self._edge_detector._effective_min_edge(game_state)
                if effective > filt.min_edge_percent:
                    logger.info(
                        f"  No edge opportunity (need >= {effective:.2f}% edge, "
                        f"raised from {filt.min_edge_percent}% by volatility filter)"
                    )
                else:
                    logger.info(
                        f"  No edge opportunity (need >= {filt.min_edge_percent}% edge)"
                    )
        else:
            # Annotate opportunities with bid-ask spread data
            for opportunity in opportunities:
                spread_key = f"{opportunity.side}_spread_pct"
                spread_pct = market_data.get(spread_key)
                opportunity.spread_percentage = spread_pct

                spread_str = f"{spread_pct:.1f}%" if spread_pct is not None else "N/A"
                logger.info(
                    f"  >>> EDGE FOUND: {opportunity.side.upper()} "
                    f"{opportunity.team_abbreviation} | "
                    f"Edge: {opportunity.edge_percentage:+.2f}% | "
                    f"EV: {opportunity.expected_value:.2%} | "
                    f"Spread: {spread_str}"
                )

        # Generate conviction opportunities for high-probability side (AI-confirmed, no risk flags)
        if conviction_thresh > 0:
            ai_analysis = self._last_claude_analysis.get(game_id)
            ai_clear = ai_analysis is not None and not ai_analysis.risk_flags
            if ai_clear:
                existing_sides = {o.side for o in opportunities}
                home_prob = float(estimate.estimated_probability)
                away_prob = 1.0 - home_prob

                if home_prob >= conviction_thresh and "home" not in existing_sides:
                    home_spread = market_data.get("home_spread_pct")
                    opportunities.append(EdgeOpportunity(
                        game_id=game_state.game_id,
                        market_id=market_data["home_market_id"],
                        token_id=market_data["home_token_id"],
                        side="home",
                        team_name=game_state.home_team.team_name,
                        team_abbreviation=game_state.home_team.team_abbreviation,
                        market_price=estimate.market_price,
                        estimated_probability=estimate.estimated_probability,
                        edge=estimate.edge,
                        edge_percentage=estimate.edge_percentage,
                        confidence=estimate.confidence,
                        estimate=estimate,
                        spread_percentage=home_spread,
                    ))
                    logger.info(
                        f"  >>> CONVICTION: {game_state.home_team.team_abbreviation} "
                        f"prob={home_prob:.1%} (AI-enhanced, no risk flags)"
                    )

                if away_prob >= conviction_thresh and "away" not in existing_sides:
                    away_buy = estimate.away_market_price or (Decimal("1") - estimate.market_price)
                    away_est = Decimal("1") - estimate.estimated_probability
                    away_edge = away_est - away_buy
                    away_spread = market_data.get("away_spread_pct")
                    opportunities.append(EdgeOpportunity(
                        game_id=game_state.game_id,
                        market_id=market_data["away_market_id"],
                        token_id=market_data["away_token_id"],
                        side="away",
                        team_name=game_state.away_team.team_name,
                        team_abbreviation=game_state.away_team.team_abbreviation,
                        market_price=away_buy,
                        estimated_probability=away_est,
                        edge=away_edge,
                        edge_percentage=float(away_edge * 100),
                        confidence=estimate.confidence,
                        estimate=estimate,
                        spread_percentage=away_spread,
                    ))
                    logger.info(
                        f"  >>> CONVICTION: {game_state.away_team.team_abbreviation} "
                        f"prob={away_prob:.1%} (AI-enhanced, no risk flags)"
                    )

        # Evaluate against strategies
        signals_count = 0
        for opportunity in opportunities:
            signals = self._strategy_manager.evaluate_opportunity(
                game_state, opportunity
            )

            if not signals:
                logger.info(
                    f"  No strategy signals for {opportunity.side} opportunity"
                )

            for signal in signals:
                # Enforce position accumulation limit: skip buy if we
                # already hold a position on this token.
                if signal.action == "buy":
                    existing = self._position_tracker.get_position(signal.token_id)
                    if existing and existing.size > 0:
                        logger.info(
                            f"  Skipping buy: already have open position on "
                            f"{signal.token_id[:16]}... "
                            f"(size={float(existing.size):.4f}, "
                            f"cost=${float(existing.total_cost):.2f})"
                        )
                        continue

                    # --- Risk guards (mirrors replay_engine) ---
                    strategy = self._strategy_manager.get_strategy(signal.strategy_id)
                    if strategy:
                        rl = strategy.risk_limits

                        # 1. Per-game loss cap
                        if rl.max_loss_per_game_usdc > 0:
                            cum_pnl = self._game_cumulative_pnl.get(game_id, Decimal("0"))
                            cap = Decimal(str(rl.max_loss_per_game_usdc))
                            if cum_pnl <= -cap:
                                logger.info(
                                    f"  Skipping buy: game loss cap reached "
                                    f"(PnL ${float(cum_pnl):+.2f} <= -${float(cap):.2f})"
                                )
                                continue

                        # 2. Max stop losses per game
                        if rl.max_stop_losses_per_game > 0:
                            sl_count = self._game_stop_loss_count.get(game_id, 0)
                            if sl_count >= rl.max_stop_losses_per_game:
                                logger.info(
                                    f"  Skipping buy: max stop losses reached "
                                    f"({sl_count}/{rl.max_stop_losses_per_game})"
                                )
                                continue

                        # 3. Cooldown after stop-loss
                        if rl.cooldown_iterations > 0:
                            last_sl_iter = self._last_stop_loss_iteration.get(signal.token_id)
                            if last_sl_iter is not None:
                                iters_since = self._iteration - last_sl_iter
                                if iters_since < rl.cooldown_iterations:
                                    logger.info(
                                        f"  Skipping buy: cooldown active "
                                        f"({iters_since}/{rl.cooldown_iterations} iters since stop loss)"
                                    )
                                    continue

                signals_count += 1
                logger.info(
                    f"  >>> SIGNAL: {signal.strategy_id} | "
                    f"{signal.action.upper()} {signal.side} | "
                    f"Size: ${float(signal.size):.2f} @ {float(signal.price):.4f}"
                )
                await self._execute_signal(signal)

        # Attach outcome to the AI analysis log entry for this iteration
        if (self._ai_analysis_log
                and self._ai_analysis_log[-1]["iteration"] == self._iteration):
            self._ai_analysis_log[-1]["opportunities"] = len(opportunities)
            self._ai_analysis_log[-1]["signals"] = signals_count

    def _rename_log_dir(self, away_abbr: str, home_abbr: str) -> None:
        """Rename the log directory to include team abbreviations.

        Renames from ``{timestamp}/`` to ``{timestamp}_{away}_vs_{home}/``
        and updates the logging FileHandler to point to the new path.
        """
        if not self._log_dir or not self._log_dir.exists():
            return

        new_name = f"{self._start_ts}_{away_abbr}_vs_{home_abbr}"
        new_dir = self._log_dir.parent / new_name

        try:
            self._log_dir.rename(new_dir)
            self._log_dir = new_dir

            # Update any FileHandler so logging continues at the new path
            root_logger = logging.getLogger()
            for handler in root_logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    new_log_path = str(new_dir / "full.txt")
                    handler.close()
                    handler.baseFilename = new_log_path
                    handler.stream = handler._open()
                    break

            logger.info(f"Log directory renamed to {new_dir}")
        except Exception as e:
            logger.warning(f"Could not rename log directory: {e}")

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
                    # Compute spread % for each outcome (relative to mid price)
                    home_spread_pct = None
                    away_spread_pct = None
                    if prices.home_best_bid and prices.home_best_ask:
                        home_mid = (prices.home_best_bid + prices.home_best_ask) / 2
                        if home_mid > 0:
                            home_spread_pct = float(
                                (prices.home_best_ask - prices.home_best_bid) / home_mid * 100
                            )
                    if prices.away_best_bid and prices.away_best_ask:
                        away_mid = (prices.away_best_bid + prices.away_best_ask) / 2
                        if away_mid > 0:
                            away_spread_pct = float(
                                (prices.away_best_ask - prices.away_best_bid) / away_mid * 100
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
                        "home_spread_pct": home_spread_pct,
                        "away_spread_pct": away_spread_pct,
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
        home_context: Optional[TeamContext] = None,
        away_context: Optional[TeamContext] = None,
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
            home_context=home_context,
            away_context=away_context,
        )

        analysis = await self._claude_analyzer.analyze(
            game_context=context.game_context,
            market_context=context.market_context,
            quant_analysis=context.quant_analysis,
            game_id=game_state.game_id,
        )

        if analysis:
            # Apply AI probability adjustment to estimate (previously only logged, not applied)
            adjusted_prob = self._claude_analyzer.apply_to_probability(
                estimate.estimated_probability, analysis
            )
            old_prob = float(estimate.estimated_probability)
            estimate.estimated_probability = adjusted_prob
            estimate.edge = adjusted_prob - estimate.market_price
            estimate.edge_percentage = float(estimate.edge * 100)

            # Store analysis for conviction entry checks
            self._last_claude_analysis[game_state.game_id] = analysis

            logger.info(
                f"Claude analysis for {game_state.game_id}: "
                f"assessment={analysis.market_assessment} conf={analysis.confidence} "
                f"sentiment_adj={analysis.sentiment_adjustment} "
                f"context_adj={analysis.context_adjustment}"
            )
            logger.info(
                f"  AI adjustment: prob {old_prob:.1%} -> {float(adjusted_prob):.1%} | "
                f"edge now {estimate.edge_percentage:+.2f}%"
            )
            logger.info(
                f"  Key factors: {', '.join(analysis.key_factors)}"
            )
            logger.info(
                f"  Risk flags: "
                f"{', '.join(analysis.risk_flags) if analysis.risk_flags else 'none'}"
            )
            logger.info(f"  Reasoning: {analysis.reasoning}")

            from datetime import datetime as _dt
            self._ai_analysis_log.append({
                "iteration": self._iteration,
                "timestamp": _dt.now(),
                "game_id": game_state.game_id,
                "score": f"{game_state.away_team.team_abbreviation} {game_state.away_team.score} - "
                         f"{game_state.home_team.team_abbreviation} {game_state.home_team.score}",
                "period": f"{game_state.period.display_name} {game_state.clock}",
                "home_market_price": float(home_market_price),
                "edge_pct": estimate.edge_percentage,
                "quant_confidence": estimate.confidence,
                "assessment": analysis.market_assessment,
                "ai_confidence": analysis.confidence,
                "sentiment_adj": analysis.sentiment_adjustment,
                "context_adj": analysis.context_adjustment,
                "key_factors": analysis.key_factors,
                "reasoning": analysis.reasoning,
            })

    async def _execute_signal(self, signal: TradingSignal) -> None:
        """Execute a trading signal."""
        # Convert USDC size to shares (Kelly sizing outputs USDC,
        # but the executor and position tracker expect share counts).
        size_in_shares = signal.size / signal.price

        # Check risk (risk manager computes notional = shares * price = USDC)
        risk_check = self._risk_manager.check_order(
            market_id=signal.market_id,
            token_id=signal.token_id,
            side=signal.action,
            size=size_in_shares,
            price=signal.price,
        )

        if not risk_check.allowed:
            logger.warning(f"Signal rejected by risk manager: {risk_check.reason}")
            return

        # Adjust size if needed (risk manager adjusted_size is already in shares)
        order_size = risk_check.adjusted_size or size_in_shares

        # Log signal (convert back to USDC for readability)
        self._trade_logger.log_signal(
            strategy_id=signal.strategy_id,
            game_id=signal.game_id,
            side=signal.side,
            edge=signal.edge_percentage,
            confidence=signal.confidence,
            size=float(order_size * signal.price),
        )

        # Submit order (size is in shares)
        side = TradeSide.BUY if signal.action == "buy" else TradeSide.SELL

        result = await self._order_manager.submit_order(
            market_id=signal.market_id,
            token_id=signal.token_id,
            side=side,
            size=order_size,
            price=signal.price,
            strategy_id=signal.strategy_id,
        )

        if result.success:
            self._trade_logger.log_order(
                order_id=result.order.order_id,
                action="submit",
                market_id=signal.market_id,
                side=signal.action,
                size=float(order_size),
                price=float(signal.price),
            )

    async def _position_monitor_loop(self) -> None:
        """Background loop that checks positions more frequently than the main loop."""
        interval = self._config.position_check_interval
        logger.info(f"Position monitor started (every {interval}s)")
        while self._running:
            try:
                if self._position_tracker.get_all_positions():
                    await self._manage_positions()
            except Exception as e:
                logger.error(f"Position monitor error: {e}", exc_info=True)
            await asyncio.sleep(interval)

    async def _manage_positions(self) -> None:
        """Manage existing positions."""
        positions = self._position_tracker.get_all_positions()
        if not positions:
            return
        logger.info(f"  [Exit check] Evaluating {len(positions)} position(s)")
        # Get mid-price (for P&L / exit evaluation), best-bid (for execution),
        # and spread % (for spread guard) in one API call per token.
        mid_price_map: dict[str, Decimal] = {}
        bid_price_map: dict[str, Decimal] = {}
        spread_pct_map: dict[str, float] = {}
        for position in positions:
            if hasattr(self._price_fetcher, "get_token_price_info"):
                mid, bid, spread_pct = await asyncio.to_thread(
                    self._price_fetcher.get_token_price_info, position.token_id
                )
            else:
                # Fallback for fetchers without get_token_price_info
                bid = await asyncio.to_thread(
                    self._price_fetcher.get_token_sell_price, position.token_id
                )
                mid, spread_pct = bid, 0.0
            fallback = position.avg_entry_price
            mid_price_map[position.token_id] = mid if mid is not None else fallback
            bid_price_map[position.token_id] = bid if bid is not None else fallback
            spread_pct_map[position.token_id] = spread_pct if spread_pct else 0.0
            # Log divergence when mid vs bid differs >5%
            mid_val = mid_price_map[position.token_id]
            bid_val = bid_price_map[position.token_id]
            if mid_val > 0 and bid_val > 0:
                divergence_pct = float((mid_val - bid_val) / mid_val) * 100
                if abs(divergence_pct) > 5.0:
                    logger.warning(
                        f"  Mid/bid divergence for {position.token_id[:20]}...: "
                        f"mid={float(mid_val):.4f} bid={float(bid_val):.4f} "
                        f"({divergence_pct:+.1f}%) spread={spread_pct_map[position.token_id]:.1f}%"
                    )
        # Use mid_price_map for strategy evaluation, bid_price_map for execution
        price_map = mid_price_map

        # Collect token_ids that already have pending/active sell orders
        open_sell_tokens = {
            o.token_id
            for o in self._order_manager.get_all_open_orders()
            if o.side == TradeSide.SELL
        }

        for position in positions:
            # Skip if there's already a pending/active sell order for this token
            if position.token_id in open_sell_tokens:
                logger.debug(
                    f"  Skipping exit eval for {position.token_id}: "
                    f"sell order already pending/active"
                )
                continue

            current_price = mid_price_map.get(position.token_id)

            # Hard circuit breaker: force exit if position loss exceeds
            # absolute limit, regardless of strategy stop-loss settings.
            # Uses mid-price for evaluation (fair value).
            if current_price is not None and self._risk_manager.check_hard_loss_limit(
                position, current_price
            ):
                hard_exit = ExitSignal(
                    strategy_id=position.strategy_id or "risk_manager",
                    position=position,
                    reason=f"Hard circuit breaker (-{self._risk_manager.limits.hard_loss_limit_percent}%)",
                )
                await self._execute_exit(hard_exit, bid_price_map)
                continue

            game_id = self._token_id_to_game_id.get(position.token_id)
            if game_id is None:
                continue
            game_state = self._active_games.get(game_id)
            if game_state is None:
                continue
            exit_signal = self._strategy_manager.evaluate_position(
                position, game_state, mid_price_map, spread_pct_map
            )
            if exit_signal is not None:
                await self._execute_exit(exit_signal, bid_price_map)

    async def _execute_exit(
        self, exit_signal, price_map: Optional[dict[str, Decimal]] = None,
    ) -> None:
        """Execute a position exit."""
        position = exit_signal.position

        # Guard: skip if position is already closed (size<=0) to avoid
        # submitting orders with zero amounts after a fill.
        if position.size <= 0:
            logger.warning(
                f"Skipping exit for {position.token_id}: position size is "
                f"{position.size} (already closed)"
            )
            return

        # Use limit price from exit signal when available (profit target / stop loss),
        # fall back to current market price, then entry price as last resort.
        if exit_signal.limit_price is not None:
            sell_price = exit_signal.limit_price
        elif price_map and position.token_id in price_map:
            sell_price = price_map[position.token_id]
        else:
            sell_price = position.avg_entry_price

        # Clamp sell_price to current market if limit is above market (gap past SL)
        if price_map and position.token_id in price_map:
            current_market = price_map[position.token_id]
            if current_market > 0 and sell_price > current_market:
                logger.warning(
                    f"Exit limit {float(sell_price):.4f} above market "
                    f"{float(current_market):.4f} - using market price"
                )
                sell_price = current_market

        # Guard: write off dust positions below Polymarket minimum notional
        MIN_SELL_NOTIONAL = Decimal("0.50")
        notional = position.size * sell_price
        if notional < MIN_SELL_NOTIONAL:
            logger.warning(
                f"Writing off dust position {position.token_id}: "
                f"{position.size} shares worth ${notional:.4f}"
            )
            self._position_tracker.write_off_dust(position.token_id)
            return

        # Submit sell order
        result = await self._order_manager.submit_order(
            market_id=position.market_id,
            token_id=position.token_id,
            side=TradeSide.SELL,
            size=position.size,
            price=sell_price,
            strategy_id=position.strategy_id,
        )

        if result.success:
            logger.info(
                f"Exit order submitted for {position.token_id}: {exit_signal.reason}"
            )

            # Track cumulative PnL per game
            game_id = self._token_id_to_game_id.get(position.token_id, "")
            if game_id:
                pnl = position.unrealized_pnl(sell_price)
                self._game_cumulative_pnl[game_id] = (
                    self._game_cumulative_pnl.get(game_id, Decimal("0")) + pnl
                )

            # Track stop losses for cooldown / per-game limits
            reason_lower = exit_signal.reason.lower()
            if "stop loss" in reason_lower or "circuit breaker" in reason_lower:
                self._last_stop_loss_iteration[position.token_id] = self._iteration
                if game_id:
                    self._game_stop_loss_count[game_id] = (
                        self._game_stop_loss_count.get(game_id, 0) + 1
                    )
                    logger.info(
                        f"  Stop loss #{self._game_stop_loss_count[game_id]} for game {game_id} "
                        f"| Game PnL: ${float(self._game_cumulative_pnl.get(game_id, 0)):+.2f}"
                    )

    async def _close_all_positions(self) -> None:
        """Close all open positions at market price during shutdown."""
        positions = self._position_tracker.get_all_positions()
        if not positions:
            logger.info("SHUTDOWN: No open positions to close")
            return

        logger.warning(f"SHUTDOWN: Force-closing {len(positions)} open position(s)")
        for position in positions:
            try:
                sell_price = await asyncio.to_thread(
                    self._price_fetcher.get_token_sell_price, position.token_id
                )
                if sell_price is None:
                    sell_price = position.avg_entry_price

                # Skip dust positions
                notional = position.size * sell_price
                if notional < Decimal("0.50"):
                    logger.info(
                        f"SHUTDOWN: Skipping dust position {position.token_id} "
                        f"(${float(notional):.4f})"
                    )
                    continue

                result = await self._order_manager.submit_order(
                    market_id=position.market_id,
                    token_id=position.token_id,
                    side=TradeSide.SELL,
                    size=position.size,
                    price=sell_price,
                    strategy_id=position.strategy_id,
                )
                if result.success:
                    logger.info(
                        f"SHUTDOWN: Sell order submitted for {position.token_id} "
                        f"@ {float(sell_price):.4f}"
                    )
                else:
                    logger.error(
                        f"SHUTDOWN: Failed to close {position.token_id}: {result}"
                    )
            except Exception as e:
                logger.error(
                    f"SHUTDOWN: Error closing position {position.token_id}: {e}"
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
            total_trades=position_stats.get("completed_trades", 0),
            winning_trades=position_stats.get("winning_trades", 0),
            losing_trades=position_stats.get("losing_trades", 0),
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
