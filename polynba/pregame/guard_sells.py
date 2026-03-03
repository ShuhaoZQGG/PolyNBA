"""Sell Order Guardian — polls SELL_PLACED orders and re-places them when cancelled.

Polymarket clears all limit orders at tipoff. This guardian detects cancelled
sells and automatically re-places them at exit_price so positions are not left
unhedged.

Usage:
    python -m polynba.pregame.guard_sells --date 20260301
    python -m polynba.pregame.guard_sells --date 20260301 --interval 15 --dry-run
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .check_orders import load_ledger, save_ledger, _get_token_balance


class SellGuardian:
    def __init__(self, date_str: str, interval: int = 30, dry_run: bool = False):
        self.date_str = date_str
        self.interval = interval
        self.dry_run = dry_run
        self._executor = None
        self._client = None
        self._cancel_seen: dict[str, datetime] = {}  # sell_id → first-seen-cancelled time

    async def _init_executor(self):
        from ..trading import LiveTradingExecutor

        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
        if not private_key:
            print("ERROR: POLYMARKET_PRIVATE_KEY not set.", file=sys.stderr)
            sys.exit(1)

        self._executor = LiveTradingExecutor(
            private_key=private_key,
            rpc_url=os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com"),
            chain_id=int(os.environ.get("CHAIN_ID", "137")),
            funder=os.environ.get("POLYMARKET_FUNDER_ADDRESS"),
        )
        self._client = await self._executor._get_client()

    async def run(self) -> None:
        """Main poll loop until all SOLD or interrupted."""
        await self._init_executor()
        print(f"Sell Guardian started — date={self.date_str} interval={self.interval}s "
              f"dry_run={self.dry_run}")

        first = True
        while True:
            ledger = load_ledger(self.date_str)
            entries = [e for e in ledger.get("orders", [])
                       if e.get("status") == "SELL_PLACED" and e.get("sell_order_id")]

            if not entries:
                print("No SELL_PLACED entries remaining. Done.")
                break

            if first:
                first = False
                print(f"Tracking {len(entries)} sell order(s):")
                for e in entries:
                    oid = e["sell_order_id"]
                    short_id = oid[:12] if len(oid) > 12 else oid
                    shares = e.get("filled_shares", e.get("shares", "?"))
                    price = f"${e['exit_price']:.2f}" if e.get("exit_price") else "?"
                    print(f"  {e['game']:<14} {e['team']:<5} {shares:>5} shares @ {price}  id={short_id}…")
                await self._check_game_times(entries)

            results = {"alive": 0, "sold": 0, "replaced": 0, "pending": 0}
            changed = False

            for entry in entries:
                result = await self._check_entry(entry)
                results[result] += 1
                if result in ("sold", "replaced"):
                    changed = True

            if changed:
                save_ledger(self.date_str, ledger)

            summary = " | ".join(f"{k}={v}" for k, v in results.items() if v)
            print(f"[{_now()}] {summary}")

            # Only exit when every sell has reached terminal SOLD state
            if results["sold"] == len(entries) and not results["replaced"]:
                print("All sells filled (SOLD). Exiting.")
                break

            await asyncio.sleep(self.interval)

    async def _check_game_times(self, entries: list[dict]) -> None:
        """Fetch ESPN scoreboard and warn if earliest tracked game is >1hr away."""
        try:
            from ..data.sources.espn.client import ESPNClient
            from ..data.sources.espn.parser import ESPNParser

            client = ESPNClient()
            try:
                raw = await client.get_scoreboard(self.date_str)
                games = ESPNParser().parse_scoreboard(raw)
            finally:
                await client.close()

            # Build lookup: "AWAY @ HOME" → game_date
            tipoffs: dict[str, datetime] = {}
            for g in games:
                key = f"{g.away_team_abbreviation} @ {g.home_team_abbreviation}"
                if g.game_date:
                    tipoffs[key] = g.game_date

            # Find the earliest tipoff among tracked entries
            tracked_games = {e["game"] for e in entries}
            matched = [(g, tipoffs[g]) for g in tracked_games if g in tipoffs]

            if not matched:
                return

            now = datetime.now(timezone.utc)
            far_games = []

            for game, tip in sorted(matched, key=lambda x: x[1]):
                local = tip.astimezone().strftime("%H:%M %Z")
                delta = tip - now
                total_sec = delta.total_seconds()
                if total_sec <= 0:
                    tag = "already started"
                elif total_sec < 60:
                    tag = "in <1min"
                elif total_sec < 3600:
                    tag = f"in {int(total_sec // 60)}min"
                else:
                    h, m = divmod(int(total_sec // 60), 60)
                    tag = f"in {h}h{m:02d}m" if m else f"in {h}h"
                    far_games.append(game)
                print(f"  {game:<14} tips off {local} ({tag})")

            if far_games:
                print(f"\n  ⏳ {len(far_games)} game(s) start >1hr from now.")
                print(f"     Consider re-running closer to tipoff to avoid idle polling.\n")
        except Exception as e:
            print(f"  (Could not fetch game times: {e})")

    async def _check_entry(self, entry: dict) -> str:
        """Check one sell. Returns: 'alive' | 'replaced' | 'sold' | 'pending'."""
        sell_id = entry["sell_order_id"]
        label = f"{entry['game']} {entry['team']}"
        order = await self._executor.get_order(sell_id)

        if order:
            status = order.status.value.upper()
        else:
            status = "NOT_FOUND"

        if status == "OPEN":
            return "alive"

        if status == "FILLED":
            balance = await _get_token_balance(self._client, entry["token_id"])
            if balance <= 0:
                entry["status"] = "SOLD"
                print(f"  {label}: FILLED → SOLD (0 tokens)")
                return "sold"
            # Partially filled but still has tokens — keep alive
            return "alive"

        # CANCELLED, NOT_FOUND, EXPIRED, etc → wait one cycle before replacing
        # so Polymarket has time to free the token allowance
        now = datetime.now(timezone.utc)
        if sell_id not in self._cancel_seen:
            self._cancel_seen[sell_id] = now
            print(f"  {label}: {status} (first sight — waiting for allowance to clear)")
            return "pending"

        waited = (now - self._cancel_seen[sell_id]).total_seconds()
        if waited < 180:
            print(f"  {label}: {status} (waiting {int(waited)}s/180s)")
            return "pending"

        balance = await _get_token_balance(self._client, entry["token_id"])
        if balance <= 0:
            entry["status"] = "SOLD"
            print(f"  {label}: {status} but 0 tokens → SOLD")
            return "sold"

        # Re-place at exit_price for on-chain balance
        return await self._replace_sell(entry, balance, label)

    async def _replace_sell(self, entry: dict, shares: int, label: str) -> str:
        """Place new sell at exit_price, update ledger entry."""
        price = Decimal(str(entry["exit_price"]))
        tag = "[DRY-RUN] " if self.dry_run else ""
        print(f"  {tag}{label}: SELL {shares} @ ${price} (was {entry['sell_order_id'][:10]}…)")

        if self.dry_run:
            return "replaced"

        from ..data.models.enums import TradeSide

        result = await self._executor.place_order(
            market_id=entry["market_id"],
            token_id=entry["token_id"],
            side=TradeSide.SELL,
            size=Decimal(shares),
            price=price,
        )

        if result.success:
            new_id = result.order.order_id if result.order else "N/A"
            entry["sell_order_id"] = new_id
            entry["sell_replaced_at"] = _now()
            entry["sell_replace_count"] = entry.get("sell_replace_count", 0) + 1
            print(f"    → new sell_order_id: {new_id}")
            return "replaced"
        else:
            print(f"    → FAILED: {result.error} (will retry next cycle)", file=sys.stderr)
            return "pending"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sell Order Guardian — re-places cancelled sells after game start",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--date", required=True, help="Ledger date YYYYMMDD")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without placing orders")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    guardian = SellGuardian(
        date_str=args.date,
        interval=args.interval,
        dry_run=args.dry_run,
    )
    try:
        asyncio.run(guardian.run())
    except KeyboardInterrupt:
        print("\nGuardian stopped.")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
