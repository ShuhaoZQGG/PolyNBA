#!/usr/bin/env python3
"""Replay historical bot logs with different strategy parameters.

Usage:
    python scripts/replay_strategy.py <log_path> [options]

Examples:
    python scripts/replay_strategy.py logs/live/20260223215750_UTAH_vs_HOU --min-edge 1.0
    python scripts/replay_strategy.py logs/live/20260221201447_MEM_vs_MIA --min-edge 5.0
    python scripts/replay_strategy.py logs/live/20260223215750_UTAH_vs_HOU --min-edge 1.0 --verbose
"""

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import yaml

from polynba.replay.log_parser import LogParser
from polynba.replay.output import format_result, format_result_json
from polynba.replay.replay_engine import ReplayEngine, VolatilityConfig


def main():
    parser = argparse.ArgumentParser(
        description="Replay bot logs with different strategy parameters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "log_path",
        help="Path to log directory or full.txt file",
    )
    parser.add_argument(
        "--strategy",
        dest="strategy_id",
        help="Base strategy ID (default: auto-detect from log)",
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        help="Override minimum edge %% (e.g., 1.0)",
    )
    parser.add_argument(
        "--min-confidence",
        type=int,
        help="Override minimum confidence (1-10)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        help="Override stop loss %%",
    )
    parser.add_argument(
        "--profit-target",
        type=float,
        help="Override profit target %% (uniform across all time buckets)",
    )
    parser.add_argument(
        "--kelly-mult",
        type=float,
        help="Override Kelly multiplier",
    )
    parser.add_argument(
        "--max-position",
        type=float,
        help="Override max position USDC",
    )
    parser.add_argument(
        "--bankroll",
        type=float,
        help="Override bankroll (default: from log)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show per-iteration details",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Profile YAML to load edge/volatility settings from",
    )

    args = parser.parse_args()

    # Set up logging
    level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
    )

    # Parse log
    try:
        log_parser = LogParser(args.log_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    snapshots = log_parser.parse()
    if not snapshots:
        print("Error: No valid snapshots found in log file", file=sys.stderr)
        sys.exit(1)

    print(f"Parsed {len(snapshots)} snapshots from log", file=sys.stderr)

    # Determine strategy
    strategy_id = args.strategy_id
    if not strategy_id:
        if log_parser.active_strategies:
            strategy_id = log_parser.active_strategies[0]
            print(f"Auto-detected strategy: {strategy_id}", file=sys.stderr)
        else:
            print("Error: Could not detect strategy from log. Use --strategy.", file=sys.stderr)
            sys.exit(1)

    # Build overrides
    overrides = {}
    if args.min_edge is not None:
        overrides["min_edge"] = args.min_edge
    if args.min_confidence is not None:
        overrides["min_confidence"] = args.min_confidence
    if args.stop_loss is not None:
        overrides["stop_loss"] = args.stop_loss
    if args.profit_target is not None:
        overrides["profit_target"] = args.profit_target
    if args.kelly_mult is not None:
        overrides["kelly_multiplier"] = args.kelly_mult
    if args.max_position is not None:
        overrides["max_position"] = args.max_position

    # Determine bankroll
    bankroll = Decimal(str(args.bankroll)) if args.bankroll else log_parser.bankroll

    if overrides:
        print(f"Overrides: {overrides}", file=sys.stderr)

    # Load volatility config from profile YAML if provided
    volatility_config = None
    if args.config and args.config.exists():
        with open(args.config) as f:
            profile_data = yaml.safe_load(f)
        edge_cfg = profile_data.get("edge", {})
        vol_cfg = edge_cfg.get("volatility", {})
        volatility_config = VolatilityConfig(
            min_edge_percent=float(edge_cfg.get("min_edge_percent", 5.0)),
            score_threshold=int(vol_cfg.get("score_threshold", 5)),
            period_threshold=int(vol_cfg.get("period_threshold", 3)),
            edge_multiplier=float(vol_cfg.get("edge_multiplier", 1.5)),
        )
        # Use strategy from profile if not specified
        if not args.strategy_id and profile_data.get("active_strategies"):
            strategy_id = profile_data["active_strategies"][0]
            print(f"Strategy from config: {strategy_id}", file=sys.stderr)
        # Use bankroll from profile if not overridden
        if not args.bankroll and profile_data.get("bankroll"):
            bankroll = Decimal(str(profile_data["bankroll"]))
        print(
            f"Volatility filter: min_edge={volatility_config.min_edge_percent}%, "
            f"score<{volatility_config.score_threshold}, period>={volatility_config.period_threshold}, "
            f"multiplier={volatility_config.edge_multiplier}x",
            file=sys.stderr,
        )

    # Run replay
    engine = ReplayEngine(
        strategy_id=strategy_id,
        overrides=overrides,
        bankroll=bankroll,
        volatility_config=volatility_config,
    )

    result = engine.run(
        snapshots=snapshots,
        original_signal_count=log_parser.original_signal_count,
        log_path=args.log_path,
        verbose=args.verbose,
    )

    # Output
    if args.json:
        print(format_result_json(result))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()
