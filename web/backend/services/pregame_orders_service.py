"""Service layer for reading / updating pregame order ledger files."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException

from polynba.pregame.check_orders import LEDGER_DIR, _get_token_balance

logger = logging.getLogger(__name__)


def _ledger_path(date_str: str) -> Path:
    return LEDGER_DIR / f"{date_str}.json"


def _save_ledger(date_str: str, ledger: dict) -> None:
    path = _ledger_path(date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w") as f:
        json.dump(ledger, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_dates() -> list[str]:
    """Return date strings (YYYYMMDD) for all ledger files, newest first."""
    if not LEDGER_DIR.exists():
        return []
    dates = sorted(
        (p.stem for p in LEDGER_DIR.glob("*.json")),
        reverse=True,
    )
    return dates


def get_orders(date_str: str) -> dict:
    """Read a ledger file and return the raw dict. Raises 404 if missing."""
    path = _ledger_path(date_str)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No ledger for date {date_str}")
    with open(path) as f:
        return json.load(f)


def record_order(req) -> dict:
    """Append a new order entry to the ledger for the given date. Returns the entry dict."""
    date_str = req.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    path = _ledger_path(date_str)

    if path.exists():
        with open(path) as f:
            ledger = json.load(f)
    else:
        ledger = {
            "date": date_str,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "orders": [],
        }

    entry = {
        "order_id": req.order_id,
        "game": req.game,
        "team": req.team,
        "token_id": req.token_id,
        "market_id": req.market_id,
        "side": req.side,
        "shares": int(req.shares),
        "entry_price": req.entry_price,
        "strategy": req.strategy,
        "exit_price": req.exit_price,
        "status": "OPEN",
        "filled_shares": 0,
        "sell_order_id": None,
    }

    ledger.setdefault("orders", []).append(entry)
    _save_ledger(date_str, ledger)
    return entry


async def check_fills(date_str: str, executor) -> dict:
    """Refresh fill status for each order via the CLOB API, save ledger."""
    ledger = get_orders(date_str)
    orders = ledger.get("orders", [])
    if not orders:
        return ledger

    open_orders = await executor.get_open_orders()
    open_ids = {o.order_id for o in open_orders}

    for entry in orders:
        oid = entry["order_id"]
        order = await executor.get_order(oid)

        if order:
            filled = int(order.filled_size)
            status = order.status.value.upper()
        elif oid in open_ids:
            filled = entry.get("filled_shares", 0)
            status = "OPEN"
        else:
            filled = entry.get("shares", 0)
            status = "MATCHED"

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

    _save_ledger(date_str, ledger)
    return ledger


def update_exit_price(date_str: str, order_id: str, exit_price: float | None) -> dict:
    """Update the exit_price for an order. Rejects if sell already placed."""
    ledger = get_orders(date_str)
    orders = ledger.get("orders", [])

    entry = next((e for e in orders if e["order_id"] == order_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    if entry.get("status") == "SELL_PLACED":
        raise HTTPException(status_code=400, detail="Cannot edit exit price after sell is placed")

    entry["exit_price"] = exit_price
    _save_ledger(date_str, ledger)
    return entry


async def place_sell(date_str: str, order_id: str, executor) -> dict:
    """Place an exit sell order for a filled TRADE entry. Returns updated entry."""
    from polynba.data.models.enums import TradeSide

    ledger = get_orders(date_str)
    orders = ledger.get("orders", [])

    entry = next((e for e in orders if e["order_id"] == order_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    if entry.get("status") != "MATCHED":
        raise HTTPException(status_code=400, detail="Order is not MATCHED")
    if entry.get("strategy") != "TRADE":
        raise HTTPException(status_code=400, detail="Order strategy is not TRADE")
    if not entry.get("exit_price"):
        raise HTTPException(status_code=400, detail="Order has no exit_price")
    if entry.get("sell_order_id"):
        raise HTTPException(status_code=400, detail="Sell already placed")

    sell_price = Decimal(str(entry["exit_price"]))

    # Get on-chain token balance
    client = await executor._get_client()
    actual_shares = await _get_token_balance(client, entry["token_id"])
    if actual_shares <= 0:
        raise HTTPException(status_code=400, detail="No tokens on-chain for this order")

    result = await executor.place_order(
        market_id=entry["market_id"],
        token_id=entry["token_id"],
        side=TradeSide.SELL,
        size=Decimal(actual_shares),
        price=sell_price,
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Sell order failed: {result.error}")

    sell_id = result.order.order_id if result.order else "N/A"
    entry["sell_order_id"] = sell_id
    entry["status"] = "SELL_PLACED"

    _save_ledger(date_str, ledger)
    return entry
