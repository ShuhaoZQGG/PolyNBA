"""Trade history service - fetches and enriches trade data from the executor."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

import asyncio

from polynba.trading.executor import TradingExecutor, TradeHistoryEntry

from ..schemas import TradeHistoryEntrySchema, TradeHistoryResponse

logger = logging.getLogger(__name__)


def _parse_timestamp(ts_str: str) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            return datetime.fromtimestamp(int(ts_str))
        except (ValueError, TypeError):
            return None


def _get_market_status(market_meta: dict) -> dict:
    """Get resolution status and winning outcome from market metadata."""
    closed = market_meta.get("closed", False)
    accepting = market_meta.get("accepting_orders", True)
    tokens = market_meta.get("tokens", [])

    winner = None
    token_outcomes: dict[str, dict] = {}
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


def _determine_activity(
    side: str,
    is_resolved: bool,
    is_winner: bool | None,
    net_shares: float,
) -> str:
    """Determine the activity label for a trade entry."""
    if is_resolved and is_winner is False and net_shares > 0:
        return "Lost"
    if is_resolved and is_winner is True and net_shares > 0:
        return "Won"
    if side == "BUY":
        return "Bought"
    return "Sold"


async def get_trade_history(
    executor: TradingExecutor,
    after_ts: int | None = None,
) -> TradeHistoryResponse:
    """Fetch trade history, enrich with market metadata, and return response."""
    raw_entries = await executor.get_trade_history(after_ts)

    if not raw_entries:
        return TradeHistoryResponse(entries=[], total_pnl=0.0, total_fees=0.0)

    # Group by market (condition_id) then by outcome
    market_positions: dict[str, dict[str, list[TradeHistoryEntry]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for t in raw_entries:
        market_positions[t.market][t.outcome].append(t)

    # Fetch market metadata for enrichment (parallel + cached)
    from .cache import market_info_cache

    async def _fetch_meta(cid: str):
        meta = await market_info_cache.get_or_fetch(
            cid, lambda c=cid: executor.get_market_info(c)
        )
        return cid, meta

    meta_results = await asyncio.gather(*[_fetch_meta(c) for c in market_positions])
    market_meta_cache: dict[str, dict] = {
        cid: meta for cid, meta in meta_results if meta
    }

    result_entries: list[TradeHistoryEntrySchema] = []
    total_pnl = 0.0
    total_fees = 0.0

    for cid, positions in market_positions.items():
        meta = market_meta_cache.get(cid, {})
        market_name = meta.get("question", f"Market {cid[:12]}...")
        status = _get_market_status(meta)

        for outcome, trades in positions.items():
            # Compute position stats for this outcome
            buy_cost = 0.0
            sell_revenue = 0.0
            total_bought = 0.0
            total_sold = 0.0

            for t in trades:
                if t.side == "BUY":
                    buy_cost += t.size * t.price
                    total_bought += t.size
                else:
                    sell_revenue += t.size * t.price
                    total_sold += t.size

            net_shares = total_bought - total_sold
            is_winner = None
            if status["resolved"]:
                is_winner = outcome == status["winner"]

            # Resolution value
            resolution_value = 0.0
            if is_winner is True and net_shares > 0:
                resolution_value = net_shares
            elif is_winner is False and net_shares > 0:
                resolution_value = 0.0

            # P&L for this position
            if is_winner is not None:
                pos_pnl = sell_revenue + resolution_value - buy_cost
            else:
                last_price = trades[-1].price if trades else 0.0
                unrealized = net_shares * last_price if net_shares > 0 else 0.0
                pos_pnl = sell_revenue + unrealized - buy_cost

            # Fees
            pos_fees = 0.0
            for t in trades:
                pos_fees += t.size * t.price * t.fee_rate_bps / 10000

            total_pnl += pos_pnl
            total_fees += pos_fees

            # Always emit per-trade Bought/Sold entries
            for t in trades:
                value = t.size * t.price
                if t.side == "BUY":
                    value = -value  # spent

                activity = "Bought" if t.side == "BUY" else "Sold"
                ts = _parse_timestamp(t.match_time)

                result_entries.append(TradeHistoryEntrySchema(
                    activity=activity,
                    market_name=market_name,
                    outcome=outcome,
                    price=t.price,
                    shares=t.size,
                    value=round(value, 2),
                    timestamp=ts.isoformat() if ts else t.match_time,
                    condition_id=cid,
                    asset_id=t.asset_id,
                    side=t.side,
                    trader_side=t.trader_side,
                ))

            # Add resolution entry for resolved positions with held shares
            if status["resolved"] and is_winner is not None and net_shares > 0:
                if is_winner:
                    res_activity = "Won"
                    res_value = round(net_shares * 1.0, 2)
                else:
                    res_activity = "Lost"
                    res_value = 0.0

                avg_price = buy_cost / total_bought if total_bought > 0 else 0.0
                last_ts = max(trades, key=lambda t: t.match_time).match_time
                ts = _parse_timestamp(last_ts)

                result_entries.append(TradeHistoryEntrySchema(
                    activity=res_activity,
                    market_name=market_name,
                    outcome=outcome,
                    price=round(avg_price, 4),
                    shares=round(net_shares, 1),
                    value=res_value,
                    timestamp=ts.isoformat() if ts else last_ts,
                    condition_id=cid,
                    asset_id=trades[0].asset_id,
                    side="BUY",
                    trader_side=trades[0].trader_side,
                ))

    # Sort newest first
    result_entries.sort(key=lambda e: e.timestamp, reverse=True)

    return TradeHistoryResponse(
        entries=result_entries,
        total_pnl=round(total_pnl, 2),
        total_fees=round(total_fees, 4),
    )
