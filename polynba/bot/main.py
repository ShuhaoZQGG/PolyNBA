"""Main entry point for PolyNBA trading bot."""

import argparse
import asyncio
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from .trading_loop import BotConfig, TradingBot, run_bot


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="PolyNBA - NBA Live Trading Bot for Polymarket",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in paper trading mode
  python -m polynba --mode paper

  # Run with specific strategies
  python -m polynba --mode paper --strategies conservative aggressive

  # Run with custom config
  python -m polynba --config myconfig.yaml

  # Run for specific number of iterations
  python -m polynba --mode paper --max-iterations 100

  # Run with mock test game (no real NBA/Polymarket)
  python -m polynba --test-game --test-game-ticks 20
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode (default: paper)",
    )

    parser.add_argument(
        "--config",
        type=Path,
        help="Path to configuration file",
    )

    parser.add_argument(
        "--strategies",
        nargs="+",
        default=None,
        help="Active strategies (e.g., conservative aggressive)",
    )

    parser.add_argument(
        "--bankroll",
        type=float,
        default=500.0,
        help="Initial bankroll in USDC (default: 500)",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Loop interval in seconds (default: 30)",
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum loop iterations (default: unlimited)",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run only one iteration then exit (useful for testing)",
    )

    parser.add_argument(
        "--no-claude",
        action="store_true",
        help="Disable Claude AI analysis",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Show performance analysis and exit",
    )

    parser.add_argument(
        "--send-command",
        type=str,
        default=None,
        help="Send a command to a running bot instance and exit",
    )
    parser.add_argument(
        "--command-host",
        type=str,
        default="127.0.0.1",
        help="Command server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--command-port",
        type=int,
        default=8765,
        help="Command server port (default: 8765)",
    )
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=5.0,
        help="Command server timeout seconds (default: 5)",
    )
    parser.add_argument(
        "--instance-id",
        type=int,
        default=None,
        help="Instance ID; command server port = 8765 + id. Use when running multiple instances (default: use --command-port)",
    )
    parser.add_argument(
        "--games",
        type=str,
        default=None,
        help="Game selection: comma-separated 1-based indices (e.g. 1,3) or 'all'. Skips interactive prompt when set.",
    )
    parser.add_argument(
        "--test-game",
        action="store_true",
        help="Use mock test game with time-series prices (no real NBA or Polymarket API).",
    )
    parser.add_argument(
        "--test-game-ticks",
        type=int,
        default=None,
        help="Number of price ticks / game states for --test-game (default: 20).",
    )
    # Edge (buy) filters
    parser.add_argument(
        "--min-edge",
        type=float,
        default=None,
        metavar="PCT",
        help="Minimum edge %% to consider a bet (overrides config).",
    )
    parser.add_argument(
        "--min-edge-strategy-conservative",
        type=float,
        default=None,
        metavar="PCT",
        help="Override minimum edge %% for conservative strategy entry rule (e.g. 3.0).",
    )
    parser.add_argument(
        "--min-edge-strategy-aggressive",
        type=float,
        default=None,
        metavar="PCT",
        help="Override minimum edge %% for aggressive strategy entry rule (e.g. 5.0).",
    )
    parser.add_argument(
        "--max-edge",
        type=float,
        default=None,
        metavar="PCT",
        help="Maximum edge %% (filter suspiciously high; overrides config).",
    )
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=None,
        metavar="N",
        help="Minimum confidence 1-10 (overrides config).",
    )
    parser.add_argument(
        "--min-market-price",
        type=float,
        default=None,
        metavar="P",
        help="Minimum market price 0-1 (overrides config).",
    )
    parser.add_argument(
        "--max-market-price",
        type=float,
        default=None,
        metavar="P",
        help="Maximum market price 0-1 (overrides config).",
    )
    parser.add_argument(
        "--min-time-remaining",
        type=int,
        default=None,
        metavar="SECS",
        help="Minimum seconds remaining in game to allow buy (overrides config).",
    )
    parser.add_argument(
        "--exclude-overtime",
        action="store_true",
        default=None,
        help="Do not allow buys in overtime (overrides config).",
    )
    parser.add_argument(
        "--no-exclude-overtime",
        action="store_true",
        help="Allow buys in overtime (overrides config).",
    )
    # Exit (sell) overrides
    parser.add_argument(
        "--stop-loss-pct",
        type=float,
        default=None,
        metavar="PCT",
        help="Global stop-loss %% (overrides strategy; e.g. 10).",
    )
    parser.add_argument(
        "--exit-before-seconds",
        type=int,
        default=None,
        metavar="SECS",
        help="Exit when time left <= SECS (overrides strategy; e.g. 60).",
    )
    parser.add_argument(
        "--profit-target-pct",
        type=float,
        default=None,
        metavar="PCT",
        help="Global take-profit %% (overrides strategy; e.g. 15).",
    )
    # Risk / allocation
    parser.add_argument(
        "--max-portfolio-exposure",
        type=float,
        default=None,
        metavar="PCT",
        help="Max fraction of balance bettable 0-1 (e.g. 0.5 = 50%%).",
    )
    parser.add_argument(
        "--conflict-min-confidence",
        type=int,
        default=None,
        metavar="N",
        help="Take conflicting side only if confidence >= N (default 7).",
    )
    parser.add_argument(
        "--kelly-multiplier",
        type=float,
        default=None,
        metavar="X",
        help="Scale strategy Kelly by X (e.g. 0.5 = half); overrides config.",
    )
    parser.add_argument(
        "--min-position-usdc",
        type=float,
        default=None,
        metavar="USD",
        help="Skip signal if position size below USD (global min).",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    if args.send_command:
        port = (
            8765 + args.instance_id
            if args.instance_id is not None
            else args.command_port
        )
        return send_command(
            command=args.send_command,
            host=args.command_host,
            port=port,
            timeout=args.command_timeout,
        )

    # Handle analyze mode
    if args.analyze:
        return run_analysis()

    # Build config
    if args.config and args.config.exists():
        config = BotConfig.from_yaml(args.config)
    else:
        config = BotConfig()

    # Override with command line args
    config.mode = args.mode
    config.bankroll = args.bankroll
    config.loop_interval = args.interval
    config.max_iterations = 1 if args.once else args.max_iterations
    config.claude_enabled = not args.no_claude
    config.log_level = args.log_level

    if args.strategies:
        config.active_strategies = args.strategies

    if args.instance_id is not None:
        config.command_server_port = 8765 + args.instance_id
        config.instance_id = args.instance_id

    if args.test_game:
        config.test_game = True
        config.test_game_ticks = args.test_game_ticks
        if config.loop_interval == 30:
            config.loop_interval = 5
        # Leave max_iterations unchanged (None = unlimited), like a real game

    # Edge (buy) overrides
    if args.min_edge is not None:
        config.min_edge_percent = args.min_edge
    overrides = dict(getattr(config, "min_edge_strategy_overrides", None) or {})
    if args.min_edge_strategy_conservative is not None:
        overrides["conservative"] = args.min_edge_strategy_conservative
    if args.min_edge_strategy_aggressive is not None:
        overrides["aggressive"] = args.min_edge_strategy_aggressive
    if overrides:
        config.min_edge_strategy_overrides = overrides
    if args.max_edge is not None:
        config.max_edge_percent = args.max_edge
    if args.min_confidence is not None:
        config.min_confidence = args.min_confidence
    if args.min_market_price is not None:
        config.min_market_price = args.min_market_price
    if args.max_market_price is not None:
        config.max_market_price = args.max_market_price
    if args.min_time_remaining is not None:
        config.min_time_remaining_seconds = args.min_time_remaining
    if args.exclude_overtime is True:
        config.exclude_overtime = True
    if args.no_exclude_overtime is True:
        config.exclude_overtime = False
    # Exit (sell) overrides
    if args.stop_loss_pct is not None:
        config.exit_stop_loss_percent = args.stop_loss_pct
    if args.exit_before_seconds is not None:
        config.exit_before_seconds = args.exit_before_seconds
    if args.profit_target_pct is not None:
        config.exit_profit_target_percent = args.profit_target_pct
    # Risk / allocation
    if args.max_portfolio_exposure is not None:
        config.max_portfolio_exposure = args.max_portfolio_exposure
    if args.conflict_min_confidence is not None:
        config.conflict_min_confidence = args.conflict_min_confidence
    if args.kelly_multiplier is not None:
        config.kelly_multiplier_override = args.kelly_multiplier
    if args.min_position_usdc is not None:
        config.min_position_usdc = args.min_position_usdc

    # Print startup banner
    print_banner(config)

    # Run the bot
    try:
        asyncio.run(async_main(args, config))
        return 0
    except KeyboardInterrupt:
        print("\nShutdown requested")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def send_command(command: str, host: str, port: int, timeout: float) -> int:
    """Send a command to the running bot and print the response."""
    if not command.strip():
        print("Command is empty.")
        return 1

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(f"{command.strip()}\n".encode())
            sock.shutdown(socket.SHUT_WR)

            chunks: list[bytes] = []
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)

        response = b"".join(chunks).decode(errors="ignore")
        if response:
            print(response, end="" if response.endswith("\n") else "\n")
        return 0
    except Exception as exc:
        print(f"Command failed: {exc}")
        return 1


async def bootstrap_game_selection(args: argparse.Namespace, config: BotConfig) -> None:
    """Fetch live games and set config.allowed_game_ids (prompt or --games)."""
    from ..data import DataManager

    dm = DataManager()
    try:
        live_games = await dm.get_live_games()
    finally:
        await dm.close()

    if len(live_games) <= 1:
        config.allowed_game_ids = None
        return

    if args.games is not None:
        s = args.games.strip().lower()
        if s == "all":
            config.allowed_game_ids = None
        else:
            try:
                indices = [int(x.strip()) for x in s.split(",")]
                game_ids = [
                    live_games[i - 1].game_id
                    for i in indices
                    if 1 <= i <= len(live_games)
                ]
                config.allowed_game_ids = game_ids if game_ids else None
            except ValueError:
                config.allowed_game_ids = None
        return

    print("\nLive games:")
    for i, g in enumerate(live_games, 1):
        print(
            f"  {i}. {g.away_team_abbreviation} @ {g.home_team_abbreviation} "
            f"{g.away_score}-{g.home_score}"
        )
    print("Select game(s) to trade (comma-separated numbers, or 'all'): ", end="")
    try:
        raw = input().strip()
    except (EOFError, KeyboardInterrupt):
        config.allowed_game_ids = None
        return
    if raw.lower() == "all":
        config.allowed_game_ids = None
        return
    try:
        indices = [int(x.strip()) for x in raw.split(",")]
        game_ids = [
            live_games[i - 1].game_id
            for i in indices
            if 1 <= i <= len(live_games)
        ]
        config.allowed_game_ids = game_ids if game_ids else None
    except ValueError:
        config.allowed_game_ids = None


async def async_main(args: argparse.Namespace, config: BotConfig) -> None:
    """Bootstrap game selection then run the bot (skip selection in test-game mode)."""
    if not config.test_game:
        await bootstrap_game_selection(args, config)
    await run_bot_with_config(config)


async def run_bot_with_config(config: BotConfig) -> None:
    """Run bot with given config."""
    from ..utils.logger import setup_logging

    start_ts = datetime.now().strftime("%Y%m%d%H%M%S")
    setup_logging(
        level=config.log_level,
        log_file=f"{start_ts}.txt",
        log_dir=Path("logs"),
    )

    bot = TradingBot(config)
    await bot.start()


def print_banner(config: BotConfig) -> None:
    """Print startup banner."""
    banner = """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   ██████╗  ██████╗ ██╗  ██╗   ██╗███╗   ██╗██████╗  █████╗║
║   ██╔══██╗██╔═══██╗██║  ╚██╗ ██╔╝████╗  ██║██╔══██╗██╔══██║
║   ██████╔╝██║   ██║██║   ╚████╔╝ ██╔██╗ ██║██████╔╝███████║
║   ██╔═══╝ ██║   ██║██║    ╚██╔╝  ██║╚██╗██║██╔══██╗██╔══██║
║   ██║     ╚██████╔╝███████╗██║   ██║ ╚████║██████╔╝██║  ██║
║   ╚═╝      ╚═════╝ ╚══════╝╚═╝   ╚═╝  ╚═══╝╚═════╝ ╚═╝  ╚═╝║
║                                                           ║
║   NBA Live In-Game Trading Bot for Polymarket             ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)
    print(f"  Mode: {config.mode.upper()}")
    print(f"  Bankroll: ${config.bankroll}")
    print(f"  Strategies: {', '.join(config.active_strategies or ['default'])}")
    print(f"  Loop interval: {config.loop_interval}s")
    print(f"  Claude AI: {'enabled' if config.claude_enabled else 'disabled'}")
    if config.test_game:
        print(f"  Test game: enabled ({config.test_game_ticks or 20} ticks)")
    print(
        f"  Edge: min={config.min_edge_percent}% max={config.max_edge_percent}% "
        f"conf>={config.min_confidence} time>={config.min_time_remaining_seconds}s "
        f"OT={'excl' if config.exclude_overtime else 'ok'}"
    )
    print(
        f"  Bettable: {config.max_portfolio_exposure:.0%} of balance | "
        f"Conflict conf>={config.conflict_min_confidence}"
    )
    if (
        config.exit_stop_loss_percent is not None
        or config.exit_before_seconds is not None
        or config.exit_profit_target_percent is not None
    ):
        parts = []
        if config.exit_stop_loss_percent is not None:
            parts.append(f"stop={config.exit_stop_loss_percent}%")
        if config.exit_before_seconds is not None:
            parts.append(f"exit_before={config.exit_before_seconds}s")
        if config.exit_profit_target_percent is not None:
            parts.append(f"profit={config.exit_profit_target_percent}%")
        print(f"  Exit overrides: {', '.join(parts)}")
    if config.kelly_multiplier_override is not None:
        print(f"  Kelly override: {config.kelly_multiplier_override}x")
    if getattr(config, "min_edge_strategy_overrides", None):
        parts = [f"{k}={v}%" for k, v in (config.min_edge_strategy_overrides or {}).items()]
        if parts:
            print(f"  Strategy min edge overrides: {', '.join(parts)}")
    if config.min_position_usdc is not None:
        print(f"  Min position: ${config.min_position_usdc}")
    if config.instance_id is not None:
        print(f"  Instance: {config.instance_id} (port {8765 + config.instance_id})")
    if config.allowed_game_ids:
        print(f"  Focus games: {len(config.allowed_game_ids)} game(s)")
    print()


def run_analysis() -> int:
    """Run performance analysis."""
    from ..utils.performance import PerformanceTracker

    # Load performance data
    perf_path = Path("performance.json")
    if not perf_path.exists():
        print("No performance data found. Run some trades first.")
        return 1

    tracker = PerformanceTracker()
    tracker.load(perf_path)

    summary = tracker.get_summary()

    print("\n=== Performance Summary ===\n")
    print(f"Initial Equity:     ${summary['initial_equity']:.2f}")
    print(f"Current Equity:     ${summary['current_equity']:.2f}")
    print(f"Total P&L:          ${summary['total_pnl']:.2f}")
    print(f"Total Return:       {summary['total_return_percent']:.2f}%")
    print()
    print(f"Total Trades:       {summary['total_trades']}")
    print(f"Win Rate:           {summary['win_rate']:.1%}")
    print(f"Max Drawdown:       {summary['max_drawdown_percent']:.2f}%")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
