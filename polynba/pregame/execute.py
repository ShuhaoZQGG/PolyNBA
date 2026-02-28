"""CLI entry point for placing a single Polymarket order from pregame output.

Usage:
    python -m polynba.pregame.execute \
        --token-id <TOKEN_ID> \
        --market-id <CONDITION_ID> \
        --side buy \
        --size 6.8 \
        --price 0.305

Reads POLYMARKET_PRIVATE_KEY, POLYMARKET_FUNDER_ADDRESS, and CHAIN_ID from
environment variables (same as the trading bot).
"""

import argparse
import asyncio
import os
import sys
from decimal import Decimal


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Place a single Polymarket order",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--token-id", required=True, help="Outcome token ID")
    parser.add_argument("--market-id", required=True, help="Market condition ID")
    parser.add_argument(
        "--side",
        required=True,
        choices=["buy", "sell"],
        help="Order side",
    )
    parser.add_argument(
        "--size",
        required=True,
        type=float,
        help="Order size in USDC (converted to shares at --price)",
    )
    parser.add_argument(
        "--price",
        required=True,
        type=float,
        help="Limit price per share (0-1)",
    )
    return parser.parse_args()


async def _execute(args: argparse.Namespace) -> None:
    from ..data.models.enums import TradeSide
    from ..trading import LiveTradingExecutor

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    if not private_key:
        print("ERROR: POLYMARKET_PRIVATE_KEY not set in environment.", file=sys.stderr)
        sys.exit(1)

    executor = LiveTradingExecutor(
        private_key=private_key,
        rpc_url=os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com"),
        chain_id=int(os.environ.get("CHAIN_ID", "137")),
        funder=os.environ.get("POLYMARKET_FUNDER_ADDRESS"),
    )

    side = TradeSide.BUY if args.side == "buy" else TradeSide.SELL
    price = Decimal(str(args.price))
    usdc_size = Decimal(str(args.size))
    size_shares = usdc_size / price

    print(f"Placing {args.side.upper()} order:")
    print(f"  Token ID:  {args.token_id}")
    print(f"  Market ID: {args.market_id}")
    print(f"  Price:     {price}")
    print(f"  Size:      {size_shares:.2f} shares (${usdc_size} USDC)")
    print()

    result = await executor.place_order(
        market_id=args.market_id,
        token_id=args.token_id,
        side=side,
        size=size_shares,
        price=price,
    )

    if result.success:
        order_id = result.order.order_id if result.order else "N/A"
        print(f"SUCCESS — Order ID: {order_id}")
        if result.transaction_hash:
            print(f"  Tx hash: {result.transaction_hash}")
    else:
        print(f"FAILED — {result.error}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(_execute(args))
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
