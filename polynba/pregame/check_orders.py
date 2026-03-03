"""CLI to check buy order fills and place exit sells using a pregame ledger file.

Usage:
    # Check all orders from a date's ledger
    python -m polynba.pregame.check_orders --date 20260301

    # Check and auto-place sells for filled TRADE orders
    python -m polynba.pregame.check_orders --date 20260301 --place-sells
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

LEDGER_DIR = Path(__file__).resolve().parent.parent / "data" / "pregame_orders"


def _ledger_path(date_str: str) -> Path:
    return LEDGER_DIR / f"{date_str}.json"


def load_ledger(date_str: str) -> dict:
    path = _ledger_path(date_str)
    if not path.exists():
        print(f"ERROR: No ledger file found at {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def save_ledger(date_str: str, ledger: dict) -> None:
    path = _ledger_path(date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w") as f:
        json.dump(ledger, f, indent=2)
        f.write("\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check buy order fills and place exit sell orders using pregame ledger",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Ledger date YYYYMMDD (loads polynba/data/pregame_orders/YYYYMMDD.json)",
    )
    parser.add_argument(
        "--place-sells",
        action="store_true",
        help="Auto-place sell orders for filled TRADE buys at ledger exit prices",
    )
    return parser.parse_args()


async def _get_token_balance(client, token_id: str) -> int:
    """Get on-chain token balance (floor to whole shares)."""
    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

    result = client.get_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
    )
    raw = int(result.get("balance", "0"))
    return raw // 1_000_000  # 6 decimals → whole shares


async def _run(args: argparse.Namespace) -> None:
    from ..data.models.enums import TradeSide
    from ..trading import LiveTradingExecutor

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    if not private_key:
        print("ERROR: POLYMARKET_PRIVATE_KEY not set.", file=sys.stderr)
        sys.exit(1)

    executor = LiveTradingExecutor(
        private_key=private_key,
        rpc_url=os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com"),
        chain_id=int(os.environ.get("CHAIN_ID", "137")),
        funder=os.environ.get("POLYMARKET_FUNDER_ADDRESS"),
    )

    ledger = load_ledger(args.date)
    orders = ledger.get("orders", [])

    if not orders:
        print("No orders in ledger.")
        return

    # Fetch open orders once for fallback check
    open_orders = await executor.get_open_orders()
    open_ids = {o.order_id for o in open_orders}

    # --- Status check ---
    header = f"{'GAME':<14} {'TEAM':<5} {'SHARES':>6} {'ENTRY':>6} {'STRAT':<10} {'EXIT':>6} {'FILLED':>6} {'STATUS'}"
    print(header)
    print("-" * len(header))

    newly_filled = []

    for entry in orders:
        oid = entry["order_id"]
        order = await executor.get_order(oid)

        if order:
            filled = int(order.filled_size)
            status = order.status.value
        elif oid in open_ids:
            filled = entry.get("filled_shares", 0)
            status = "OPEN"
        else:
            # Not in get_order and not in open orders → presumed fully matched
            filled = entry.get("shares", 0)
            status = "MATCHED"

        # Update ledger entry
        old_status = entry.get("status", "OPEN")
        entry["filled_shares"] = filled
        if status == "MATCHED" and old_status in ("OPEN", "MATCHED"):
            entry["status"] = "MATCHED"
        elif status in ("FILLED", "MATCHED") and old_status == "OPEN":
            entry["status"] = "MATCHED"
        elif old_status == "SELL_PLACED":
            pass  # don't regress
        else:
            entry["status"] = status

        exit_str = f"${entry['exit_price']:.2f}" if entry.get("exit_price") else "HOLD"

        print(
            f"{entry['game']:<14} {entry['team']:<5} "
            f"{entry['shares']:>6} ${entry['entry_price']:>5.2f} "
            f"{entry['strategy']:<10} {exit_str:>6} "
            f"{filled:>6} {entry['status']}"
        )

        # Track newly filled TRADE orders for sell placement
        if (
            entry["status"] == "MATCHED"
            and entry["strategy"] == "TRADE"
            and entry.get("exit_price")
            and not entry.get("sell_order_id")
            and filled > 0
        ):
            newly_filled.append(entry)

    # Save updated statuses
    save_ledger(args.date, ledger)

    # --- Balance ---
    balance = await executor.get_balance()
    print()
    print(f"Balance: ${balance.usdc:.2f} USDC  (${balance.available_usdc:.2f} available)")

    # --- Place sells ---
    if not args.place_sells:
        if newly_filled:
            print(f"\n{len(newly_filled)} filled TRADE order(s) ready for exit sells. "
                  f"Re-run with --place-sells to place them.")
        return

    if not newly_filled:
        print("\nNo newly filled TRADE orders to place sells for.")
        return

    print()
    print("=== Placing exit sell orders ===")

    client = await executor._get_client()

    for entry in newly_filled:
        sell_price = Decimal(str(entry["exit_price"]))

        # Use on-chain token balance instead of ledger filled_shares
        # to avoid "not enough balance" errors from fractional fills
        actual_shares = await _get_token_balance(client, entry["token_id"])
        if actual_shares <= 0:
            print(f"  {entry['game']} {entry['team']}: SKIP — 0 tokens on-chain")
            continue

        print(
            f"  {entry['game']} {entry['team']}: "
            f"SELL {actual_shares} shares @ ${sell_price} "
            f"(on-chain balance, ledger said {entry['filled_shares']})"
        )

        result = await executor.place_order(
            market_id=entry["market_id"],
            token_id=entry["token_id"],
            side=TradeSide.SELL,
            size=Decimal(actual_shares),
            price=sell_price,
        )

        if result.success:
            sell_id = result.order.order_id if result.order else "N/A"
            entry["sell_order_id"] = sell_id
            entry["status"] = "SELL_PLACED"
            print(f"    SUCCESS — Sell Order ID: {sell_id}")
        else:
            print(f"    FAILED — {result.error}", file=sys.stderr)

    # Save sell order IDs to ledger
    save_ledger(args.date, ledger)


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
