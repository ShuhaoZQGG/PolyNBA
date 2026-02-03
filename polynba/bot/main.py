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
    """Bootstrap game selection then run the bot."""
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
