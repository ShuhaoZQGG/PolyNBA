#!/usr/bin/env python3
"""Fetch and display Polymarket trade history grouped by market."""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import TradeParams


HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


def create_client() -> ClobClient:
    """Create authenticated CLOB client using .env credentials."""
    load_dotenv()
    key = os.getenv("POLYMARKET_PRIVATE_KEY")
    funder = os.getenv("POLYMARKET_FUNDER_ADDRESS")
    if not key:
        print("Error: POLYMARKET_PRIVATE_KEY not set in .env")
        sys.exit(1)

    kwargs = {"host": HOST, "key": key, "chain_id": CHAIN_ID}
    if funder:
        kwargs["signature_type"] = 1
        kwargs["funder"] = funder

    client = ClobClient(**kwargs)
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client


def fetch_trades(client: ClobClient, after_ts: int | None = None) -> list[dict]:
    """Fetch all trades, optionally filtered by timestamp."""
    params = TradeParams(after=after_ts) if after_ts else None
    return client.get_trades(params)


def fetch_market_metadata(client: ClobClient, condition_ids: set[str]) -> dict[str, dict]:
    """Fetch market metadata for each unique condition_id."""
    cache = {}
    for cid in condition_ids:
        try:
            cache[cid] = client.get_market(cid)
        except Exception as e:
            cache[cid] = {"question": f"Unknown market ({cid[:12]}...)", "error": str(e)}
    return cache


def extract_user_trades(raw_trades: list[dict], user_address: str) -> list[dict]:
    """Extract trades from the user's perspective, handling MAKER/TAKER correctly.

    When trader_side=TAKER, top-level fields are the user's trade.
    When trader_side=MAKER, the user's fill is inside maker_orders.
    """
    user_addr = user_address.lower()
    extracted = []

    for t in raw_trades:
        match_time = t.get("match_time", "")
        market = t.get("market", "")

        if t.get("trader_side") == "MAKER":
            # User was a maker — find their fill(s) in maker_orders
            for mo in t.get("maker_orders", []):
                if mo.get("maker_address", "").lower() == user_addr:
                    extracted.append({
                        "market": market,
                        "asset_id": mo.get("asset_id", t.get("asset_id")),
                        "outcome": mo.get("outcome", t.get("outcome")),
                        "side": mo.get("side", ""),
                        "size": mo.get("matched_amount", "0"),
                        "price": mo.get("price", "0"),
                        "fee_rate_bps": mo.get("fee_rate_bps", "0"),
                        "match_time": match_time,
                        "trader_side": "MAKER",
                        "status": t.get("status", ""),
                    })
        else:
            # User was the taker — top-level fields are the user's trade
            extracted.append({
                "market": market,
                "asset_id": t.get("asset_id", ""),
                "outcome": t.get("outcome", ""),
                "side": t.get("side", ""),
                "size": t.get("size", "0"),
                "price": t.get("price", "0"),
                "fee_rate_bps": t.get("fee_rate_bps", "0"),
                "match_time": match_time,
                "trader_side": "TAKER",
                "status": t.get("status", ""),
            })

    return extracted


def get_market_name(market_meta: dict) -> str:
    return market_meta.get("question", market_meta.get("condition_id", "Unknown"))


def get_market_status(market_meta: dict) -> dict:
    """Get resolution status and winning outcome from market metadata."""
    closed = market_meta.get("closed", False)
    accepting = market_meta.get("accepting_orders", True)
    tokens = market_meta.get("tokens", [])

    winner = None
    token_outcomes = {}  # asset_id -> {outcome, winner}
    for tok in tokens:
        tid = tok.get("token_id", "")
        outcome = tok.get("outcome", "")
        is_winner = tok.get("winner", False)
        token_outcomes[tid] = {"outcome": outcome, "winner": is_winner}
        if is_winner:
            winner = outcome

    resolved = closed and not accepting and winner is not None

    return {
        "closed": closed,
        "resolved": resolved,
        "winner": winner,
        "token_outcomes": token_outcomes,
    }


def parse_timestamp(ts_str: str) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            return datetime.fromtimestamp(int(ts_str))
        except (ValueError, TypeError):
            return None


def analyze_position(trades: list[dict], is_winner: bool | None = None) -> dict:
    """Analyze a single position (one outcome within one market)."""
    buys = [t for t in trades if t["side"] == "BUY"]
    sells = [t for t in trades if t["side"] == "SELL"]

    buy_sizes = [float(t["size"]) for t in buys]
    sell_sizes = [float(t["size"]) for t in sells]
    buy_prices = [float(t["price"]) for t in buys]
    sell_prices = [float(t["price"]) for t in sells]

    total_bought = sum(buy_sizes)
    total_sold = sum(sell_sizes)

    cost = sum(s * p for s, p in zip(buy_sizes, buy_prices))
    revenue = sum(s * p for s, p in zip(sell_sizes, sell_prices))

    avg_buy = cost / total_bought if total_bought > 0 else 0.0
    avg_sell = revenue / total_sold if total_sold > 0 else 0.0

    net_shares = total_bought - total_sold

    # Fees
    total_fees = 0.0
    for t in trades:
        fee_bps = float(t.get("fee_rate_bps", 0))
        total_fees += float(t["size"]) * float(t["price"]) * fee_bps / 10000

    # Resolution value
    resolution_value = 0.0
    if is_winner is True and net_shares > 0:
        resolution_value = net_shares * 1.0
    elif is_winner is False and net_shares > 0:
        resolution_value = 0.0

    # P&L
    if is_winner is not None:
        # Market resolved
        total_pnl = revenue + resolution_value - cost
    else:
        # Market still active — use last trade price for unrealized
        last_price = float(trades[-1]["price"]) if trades else 0.0
        unrealized_value = net_shares * last_price if net_shares > 0 else 0.0
        total_pnl = revenue + unrealized_value - cost

    # Timestamps
    timestamps = [parse_timestamp(t.get("match_time", "")) for t in trades]
    timestamps = [ts for ts in timestamps if ts]

    return {
        "total_trades": len(trades),
        "buys": len(buys),
        "sells": len(sells),
        "total_bought": total_bought,
        "total_sold": total_sold,
        "cost": cost,
        "revenue": revenue,
        "avg_buy": avg_buy,
        "avg_sell": avg_sell,
        "net_shares": net_shares,
        "resolution_value": resolution_value,
        "is_winner": is_winner,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "first_trade": min(timestamps) if timestamps else None,
        "last_trade": max(timestamps) if timestamps else None,
    }


def format_pnl(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}${value:.2f}"


def format_date(dt: datetime | None) -> str:
    return dt.strftime("%b %d, %Y") if dt else "N/A"


def format_date_short(dt: datetime | None) -> str:
    return dt.strftime("%b %d") if dt else "N/A"


def print_summary(
    market_positions: dict[str, dict],
    market_meta: dict[str, dict],
    show_details: bool = False,
):
    """Print the full trade history summary.

    market_positions: {condition_id: {outcome: [trades]}}
    """
    funder = os.getenv("POLYMARKET_FUNDER_ADDRESS", "unknown")
    short_addr = f"{funder[:6]}...{funder[-4:]}" if len(funder) > 10 else funder

    total_trades = sum(
        len(trades)
        for positions in market_positions.values()
        for trades in positions.values()
    )

    print()
    print("=" * 66)
    print("                  POLYMARKET TRADE HISTORY")
    print("=" * 66)
    print()
    print(f"  Account: {short_addr}")
    print(f"  Total Markets Traded: {len(market_positions)}")
    print(f"  Total Trades: {total_trades}")
    print("-" * 66)

    portfolio_pnl = 0.0
    portfolio_fees = 0.0

    for idx, (cid, positions) in enumerate(market_positions.items(), 1):
        meta = market_meta.get(cid, {})
        name = get_market_name(meta)
        status = get_market_status(meta)

        # Status label
        if status["resolved"]:
            status_label = f"RESOLVED - {status['winner']} won"
        elif status["closed"]:
            status_label = "CLOSED"
        else:
            status_label = "ACTIVE"

        print()
        print(f"  [{idx}] {name}")
        print(f"      Status: {status_label}")

        market_pnl = 0.0
        market_fees = 0.0
        all_timestamps = []

        for outcome, trades in positions.items():
            # Determine if this outcome won
            is_winner = None
            if status["resolved"]:
                is_winner = (outcome == status["winner"])

            stats = analyze_position(trades, is_winner)
            market_pnl += stats["total_pnl"]
            market_fees += stats["total_fees"]
            if stats["first_trade"]:
                all_timestamps.append(stats["first_trade"])
            if stats["last_trade"]:
                all_timestamps.append(stats["last_trade"])

            # Position header
            winner_tag = ""
            if is_winner is True:
                winner_tag = " (winner)"
            elif is_winner is False:
                winner_tag = " (loser)"

            print(f"      [{outcome}{winner_tag}]")
            print(f"        Trades: {stats['total_trades']} ({stats['buys']} buys, {stats['sells']} sells)")

            if stats["total_bought"] > 0:
                print(f"        Bought: {stats['total_bought']:.2f} shares @ ${stats['avg_buy']:.4f} avg (${stats['cost']:.2f})")
            if stats["total_sold"] > 0:
                print(f"        Sold:   {stats['total_sold']:.2f} shares @ ${stats['avg_sell']:.4f} avg (${stats['revenue']:.2f})")

            if stats["net_shares"] > 0:
                if is_winner is True:
                    print(f"        Remaining: {stats['net_shares']:.2f} shares -> Payout: ${stats['resolution_value']:.2f}")
                elif is_winner is False:
                    print(f"        Remaining: {stats['net_shares']:.2f} shares -> Expired worthless")
                else:
                    last_price = float(trades[-1]["price"]) if trades else 0.0
                    print(f"        Remaining: {stats['net_shares']:.2f} shares (last price ${last_price:.4f})")
            elif stats["net_shares"] < 0:
                print(f"        Net short: {abs(stats['net_shares']):.2f} shares")

            print(f"        P&L: {format_pnl(stats['total_pnl'])}")

            if show_details:
                print()
                print(f"        {'Side':<6} {'Size':>10} {'Price':>10} {'Value':>10} {'Role':<8} {'Time'}")
                print(f"        {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*20}")
                for t in trades:
                    size = float(t["size"])
                    price = float(t["price"])
                    value = size * price
                    ts = parse_timestamp(t.get("match_time", ""))
                    time_str = ts.strftime("%Y-%m-%d %H:%M") if ts else str(t.get("match_time", ""))[:20]
                    print(f"        {t['side']:<6} {size:>10.2f} {price:>10.4f} ${value:>9.2f} {t['trader_side']:<8} {time_str}")

        # Market totals
        period_start = format_date_short(min(all_timestamps)) if all_timestamps else "N/A"
        period_end = format_date(max(all_timestamps)) if all_timestamps else "N/A"
        if market_fees > 0:
            print(f"      Fees: ${market_fees:.4f}")
        print(f"      Market P&L: {format_pnl(market_pnl)}")
        print(f"      Period: {period_start} -> {period_end}")

        portfolio_pnl += market_pnl
        portfolio_fees += market_fees

    print()
    print("-" * 66)
    print("  PORTFOLIO SUMMARY")
    print(f"    Total P&L:   {format_pnl(portfolio_pnl)}")
    if portfolio_fees > 0:
        print(f"    Total Fees:  ${portfolio_fees:.4f}")
        print(f"    Net P&L:     {format_pnl(portfolio_pnl - portfolio_fees)}")
    print("=" * 66)
    print()


def output_json(
    market_positions: dict[str, dict],
    market_meta: dict[str, dict],
):
    """Output trade history as JSON."""
    result = {
        "account": os.getenv("POLYMARKET_FUNDER_ADDRESS", "unknown"),
        "total_markets": len(market_positions),
        "markets": [],
    }

    portfolio_pnl = 0.0
    portfolio_fees = 0.0

    for cid, positions in market_positions.items():
        meta = market_meta.get(cid, {})
        status = get_market_status(meta)

        market_entry = {
            "condition_id": cid,
            "name": get_market_name(meta),
            "status": "resolved" if status["resolved"] else ("closed" if status["closed"] else "active"),
            "winner": status["winner"],
            "positions": [],
        }

        for outcome, trades in positions.items():
            is_winner = None
            if status["resolved"]:
                is_winner = (outcome == status["winner"])

            stats = analyze_position(trades, is_winner)
            portfolio_pnl += stats["total_pnl"]
            portfolio_fees += stats["total_fees"]

            pos_entry = {
                "outcome": outcome,
                "is_winner": is_winner,
                "stats": {
                    k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in stats.items()
                },
                "trades": trades,
            }
            market_entry["positions"].append(pos_entry)

        result["markets"].append(market_entry)

    result["portfolio"] = {
        "total_pnl": portfolio_pnl,
        "total_fees": portfolio_fees,
        "net_pnl": portfolio_pnl - portfolio_fees,
    }

    print(json.dumps(result, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Polymarket trade history viewer")
    parser.add_argument("--market", type=str, help="Filter by market name (fuzzy search)")
    parser.add_argument("--details", action="store_true", help="Show individual trades")
    parser.add_argument("--after", type=str, help="Filter trades after date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
    args = parser.parse_args()

    load_dotenv()
    user_address = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")

    # Parse --after into a unix timestamp
    after_ts = None
    if args.after:
        try:
            dt = datetime.strptime(args.after, "%Y-%m-%d")
            after_ts = int(dt.timestamp())
        except ValueError:
            print(f"Error: invalid date format '{args.after}', expected YYYY-MM-DD")
            sys.exit(1)

    print("Authenticating with Polymarket CLOB API...", file=sys.stderr)
    client = create_client()

    print("Fetching trades...", file=sys.stderr)
    raw_trades = fetch_trades(client, after_ts)

    if not raw_trades:
        print("No trades found.")
        return

    print(f"Found {len(raw_trades)} raw trades.", file=sys.stderr)

    # Extract user's actual trades (handle MAKER/TAKER)
    trades = extract_user_trades(raw_trades, user_address)
    print(f"Extracted {len(trades)} user fills.", file=sys.stderr)

    # Group by market (condition_id) then by outcome
    market_positions: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for t in trades:
        cid = t["market"]
        outcome = t.get("outcome", "Unknown")
        market_positions[cid][outcome].append(t)

    # Sort trades within each position by match_time
    for cid in market_positions:
        for outcome in market_positions[cid]:
            market_positions[cid][outcome].sort(key=lambda t: t.get("match_time", ""))

    # Fetch market metadata
    condition_ids = set(market_positions.keys())
    print(f"Fetching metadata for {len(condition_ids)} markets...", file=sys.stderr)
    market_meta = fetch_market_metadata(client, condition_ids)

    # Filter by market name if requested
    if args.market:
        query = args.market.lower()
        filtered = {}
        for cid, positions in market_positions.items():
            meta = market_meta.get(cid, {})
            name = get_market_name(meta).lower()
            if query in name:
                filtered[cid] = positions
        if not filtered:
            print(f"No markets matching '{args.market}' found.")
            return
        market_positions = filtered

    # Output
    if args.json_output:
        output_json(market_positions, market_meta)
    else:
        print_summary(market_positions, market_meta, show_details=args.details)


if __name__ == "__main__":
    main()
