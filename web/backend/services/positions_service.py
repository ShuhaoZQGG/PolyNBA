"""Positions service - derives enriched open-position data from trade history.

For each (condition_id, outcome) group with net_shares > 0 the service:
  1. Skips markets that are already resolved (closed + no accepting_orders + winner set).
  2. Fetches the current mid-price from the live order book in parallel.
  3. Computes avg_price, cost, to_win, current_value, pnl, and pnl_percent.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from polynba.polymarket.price_fetcher import PriceFetcher
from polynba.trading.executor import TradingExecutor, TradeHistoryEntry

from ..schemas import PositionSchema, PositionsResponse
from .trade_history_service import _get_market_status

logger = logging.getLogger(__name__)


async def get_enriched_positions(executor: TradingExecutor, price_fetcher: PriceFetcher) -> PositionsResponse:
    """Return all open positions enriched with live prices and P&L metrics."""

    raw_entries = await executor.get_trade_history()

    if not raw_entries:
        return PositionsResponse(
            positions=[],
            total_value=0.0,
            total_cost=0.0,
            total_pnl=0.0,
            total_pnl_percent=0.0,
        )

    # Group fills by (condition_id, outcome) ---------------------------------
    # Structure: {condition_id: {outcome: [TradeHistoryEntry, ...]}}
    market_positions: dict[str, dict[str, list[TradeHistoryEntry]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for entry in raw_entries:
        market_positions[entry.market][entry.outcome].append(entry)

    # Fetch market metadata for all condition IDs (parallel + cached) --------
    from .cache import market_info_cache

    async def _fetch_meta(cid: str):
        meta = await market_info_cache.get_or_fetch(
            cid, lambda c=cid: executor.get_market_info(c)
        )
        return cid, meta

    meta_results = await asyncio.gather(*[_fetch_meta(c) for c in market_positions])
    market_meta_cache_local: dict[str, dict] = {
        cid: meta for cid, meta in meta_results if meta
    }

    # Identify open positions and which token_id each outcome maps to ---------
    # An open position: net_shares > 0 AND the market is NOT fully resolved.
    open_positions: list[dict] = []

    for cid, outcomes in market_positions.items():
        meta = market_meta_cache_local.get(cid, {})
        market_name = meta.get("question", f"Market {cid[:12]}...")
        status = _get_market_status(meta)

        # Skip markets that have already settled
        if status["resolved"]:
            logger.debug("Skipping resolved market %s", cid)
            continue

        # Build a lookup from outcome label -> token_id using market metadata
        token_outcomes: dict[str, str] = {}  # outcome -> token_id
        for tok in meta.get("tokens", []):
            tok_outcome = tok.get("outcome", "")
            tok_id = tok.get("token_id", "")
            if tok_outcome and tok_id:
                token_outcomes[tok_outcome] = tok_id

        for outcome, trades in outcomes.items():
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

            if net_shares <= 0:
                continue

            # Resolve token_id: prefer metadata lookup, fall back to asset_id
            token_id = token_outcomes.get(outcome, trades[0].asset_id)

            open_positions.append(
                {
                    "token_id": token_id,
                    "condition_id": cid,
                    "market_name": market_name,
                    "outcome": outcome,
                    "net_shares": net_shares,
                    "buy_cost": buy_cost,
                    "sell_revenue": sell_revenue,
                    "total_bought": total_bought,
                }
            )

    if not open_positions:
        return PositionsResponse(
            positions=[],
            total_value=0.0,
            total_cost=0.0,
            total_pnl=0.0,
            total_pnl_percent=0.0,
        )

    # Fetch live market data for all open positions in parallel ---------------
    def _fetch_price(token_id: str):
        try:
            mid, bid, _ = price_fetcher.get_token_price_info(token_id)
            return (mid, bid)
        except Exception:
            logger.exception("Failed to fetch price for token %s", token_id)
            return (None, None)

    price_results = await asyncio.gather(
        *[asyncio.to_thread(_fetch_price, pos["token_id"]) for pos in open_positions]
    )

    # Build enriched PositionSchema objects -----------------------------------
    position_schemas: list[PositionSchema] = []

    for pos, (mid, bid) in zip(open_positions, price_results):
        net_shares = pos["net_shares"]
        buy_cost = pos["buy_cost"]
        sell_revenue = pos["sell_revenue"]
        total_bought = pos["total_bought"]

        avg_price = buy_cost / total_bought if total_bought > 0 else 0.0

        if mid is not None:
            current_price = float(mid)
        elif bid is not None:
            current_price = float(bid)
        else:
            logger.warning(
                "No live price for token %s; falling back to avg_price", pos["token_id"]
            )
            current_price = avg_price

        cost = buy_cost
        to_win = net_shares * 1.0
        current_value = net_shares * current_price
        pnl = current_value - buy_cost + sell_revenue
        pnl_percent = (pnl / buy_cost * 100) if buy_cost > 0 else 0.0

        position_schemas.append(
            PositionSchema(
                token_id=pos["token_id"],
                condition_id=pos["condition_id"],
                market_name=pos["market_name"],
                outcome=pos["outcome"],
                shares=round(net_shares, 4),
                avg_price=round(avg_price, 4),
                current_price=round(current_price, 4),
                cost=round(cost, 2),
                to_win=round(to_win, 4),
                current_value=round(current_value, 2),
                pnl=round(pnl, 2),
                pnl_percent=round(pnl_percent, 2),
            )
        )

    # Aggregate portfolio-level totals ----------------------------------------
    total_value = sum(p.current_value for p in position_schemas)
    total_cost = sum(p.cost for p in position_schemas)
    total_pnl = sum(p.pnl for p in position_schemas)
    total_pnl_percent = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

    return PositionsResponse(
        positions=position_schemas,
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_percent=round(total_pnl_percent, 2),
    )
