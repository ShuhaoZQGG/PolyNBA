"""CLI entry point for pre-game betting advisor."""

import argparse
import asyncio
import logging
import sys

from .advisor import PreGameAdvisor
from .probability_model import PreGameModelConfig


def main():
    parser = argparse.ArgumentParser(
        description="Pre-game NBA betting advisor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--bankroll", type=float, default=500.0, help="Available bankroll in USDC")
    parser.add_argument("--min-edge", type=float, default=2.0, help="Minimum edge %% to recommend bet")
    parser.add_argument("--kelly-fraction", type=float, default=0.25, help="Kelly fraction (0.25 = quarter-Kelly)")
    parser.add_argument("--model-weight", type=float, default=0.30, help="Model weight in probability blend")
    parser.add_argument("--no-claude", action="store_true", help="Disable Claude AI analysis")
    parser.add_argument("--no-hold", action="store_true", help="Hide HOLD recommendations")
    parser.add_argument("--date", type=str, default=None, help="Date to scan (YYYYMMDD format, e.g. 20260228). Defaults to today.")
    parser.add_argument("--min-speculate-prob", type=float, default=0.72, help="Minimum model probability to trigger SPECULATE verdict")
    parser.add_argument("--speculate-kelly", type=float, default=0.15, help="Kelly fraction for SPECULATE bets (more conservative)")
    parser.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level")

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)-30s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    config = PreGameModelConfig(
        min_edge_percent=args.min_edge,
        kelly_fraction=args.kelly_fraction,
        model_weight=args.model_weight,
        market_weight=1.0 - args.model_weight,
        min_speculate_prob=args.min_speculate_prob,
        speculate_kelly_fraction=args.speculate_kelly,
    )

    advisor = PreGameAdvisor(
        model_config=config,
        bankroll=args.bankroll,
        use_claude=not args.no_claude,
        show_hold=not args.no_hold,
        log_level=args.log_level,
        scan_date=args.date,
    )

    try:
        advisories = asyncio.run(advisor.run())
        sys.exit(0 if advisories else 1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        logging.getLogger(__name__).exception("Pre-game advisor failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
