"""Format replay results as text tables or JSON."""

import json
from decimal import Decimal
from typing import Any

from .models import ReplayResult


def _dec(v: Decimal) -> str:
    """Format Decimal for display."""
    return f"{float(v):.2f}"


def format_result(result: ReplayResult) -> str:
    """Format a ReplayResult as a human-readable text report."""
    lines: list[str] = []
    sep = "=" * 70

    # --- Header ---
    lines.append(sep)
    lines.append("STRATEGY REPLAY REPORT")
    lines.append(sep)
    lines.append(f"Game:       {result.away_team} @ {result.home_team}")
    lines.append(f"Date:       {result.game_date}")
    if result.first_timestamp and result.last_timestamp:
        duration = result.last_timestamp - result.first_timestamp
        mins = int(duration.total_seconds() / 60)
        lines.append(f"Duration:   {mins} min ({result.total_snapshots} iterations)")
    lines.append(f"Bankroll:   ${_dec(result.bankroll)}")
    lines.append("")

    # --- Strategy ---
    lines.append(f"Strategy:   {result.strategy_id}")
    if result.overrides:
        lines.append("Overrides:")
        for k, v in result.overrides.items():
            lines.append(f"  {k}: {v}")
    lines.append("")

    # --- Trade Log ---
    lines.append("-" * 70)
    lines.append("TRADE LOG")
    lines.append("-" * 70)

    if result.trades:
        lines.append(
            f"{'#':>3}  {'Iter':>4}  {'Time':>8}  {'Action':>6}  {'Side':>5}  "
            f"{'Team':>5}  {'Price':>6}  {'USDC':>8}  {'Edge':>6}  Reason"
        )
        lines.append("-" * 70)
        for i, t in enumerate(result.trades, 1):
            time_str = t.timestamp.strftime("%H:%M:%S")
            lines.append(
                f"{i:>3}  {t.iteration:>4}  {time_str:>8}  {t.action.upper():>6}  "
                f"{t.side:>5}  {t.team:>5}  {float(t.price):>6.3f}  "
                f"${float(t.size_usdc):>7.2f}  {t.edge_pct:>+5.1f}%  {t.reason}"
            )
    else:
        lines.append("  (no trades)")
    lines.append("")

    # --- Closed Positions ---
    if result.closed_positions:
        lines.append("-" * 70)
        lines.append("CLOSED POSITIONS")
        lines.append("-" * 70)
        for i, cp in enumerate(result.closed_positions, 1):
            lines.append(
                f"  #{i}: {cp.entry_trade.side} {cp.entry_trade.team} | "
                f"Entry @ {float(cp.entry_trade.price):.3f} -> Exit @ {float(cp.exit_trade.price):.3f} | "
                f"PnL: ${float(cp.pnl_usdc):+.2f} ({cp.pnl_percent:+.1f}%) | "
                f"Hold: {cp.hold_iterations} iters"
            )
        lines.append("")

    # --- Open Positions ---
    if result.open_positions:
        lines.append("-" * 70)
        lines.append("OPEN POSITIONS (marked to market at session end)")
        lines.append("-" * 70)
        for op in result.open_positions:
            lines.append(
                f"  {op.entry_trade.side} {op.entry_trade.team} | "
                f"Entry @ {float(op.entry_trade.price):.3f} -> Current @ {float(op.current_price):.3f} | "
                f"Unrealized: ${float(op.unrealized_pnl_usdc):+.2f} ({op.unrealized_pnl_percent:+.1f}%)"
            )
        lines.append("")

    # --- P&L Summary ---
    lines.append(sep)
    lines.append("P&L SUMMARY")
    lines.append(sep)
    lines.append(f"Realized P&L:   ${_dec(result.realized_pnl)}")
    lines.append(f"Unrealized P&L: ${_dec(result.unrealized_pnl)}")
    lines.append(f"Total P&L:      ${_dec(result.total_pnl)}")
    lines.append(f"Total Trades:   {len(result.trades)}")

    if result.win_rate is not None:
        lines.append(f"Win Rate:       {result.win_rate:.0%} ({len(result.closed_positions)} closed)")
    if result.max_drawdown > 0:
        lines.append(f"Max Drawdown:   ${_dec(result.max_drawdown)}")
    lines.append("")

    # --- Comparison ---
    lines.append("-" * 70)
    lines.append("COMPARISON TO ORIGINAL SESSION")
    lines.append("-" * 70)
    original_trades = result.original_signal_count
    replay_trades = len(result.trades)
    lines.append(
        f"Original: {original_trades} signals, $0.00 P&L | "
        f"Replay: {replay_trades} trades, ${_dec(result.total_pnl)} P&L"
    )
    lines.append("")
    lines.append("Note: Fill prices use logged market prices (approximation).")
    lines.append(sep)

    return "\n".join(lines)


def format_result_json(result: ReplayResult) -> str:
    """Format a ReplayResult as JSON."""

    def _to_dict(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, "__dict__"):
            return {k: _to_dict(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
        if isinstance(obj, list):
            return [_to_dict(item) for item in obj]
        if isinstance(obj, dict):
            return {k: _to_dict(v) for k, v in obj.items()}
        return obj

    data = {
        "log_path": result.log_path,
        "game": f"{result.away_team} @ {result.home_team}",
        "game_date": result.game_date,
        "strategy_id": result.strategy_id,
        "overrides": result.overrides,
        "bankroll": float(result.bankroll),
        "total_snapshots": result.total_snapshots,
        "trades": [_to_dict(t) for t in result.trades],
        "closed_positions": [_to_dict(p) for p in result.closed_positions],
        "open_positions": [_to_dict(p) for p in result.open_positions],
        "summary": {
            "total_pnl": float(result.total_pnl),
            "realized_pnl": float(result.realized_pnl),
            "unrealized_pnl": float(result.unrealized_pnl),
            "total_trades": len(result.trades),
            "win_rate": result.win_rate,
            "max_drawdown": float(result.max_drawdown),
        },
        "original_signal_count": result.original_signal_count,
    }

    return json.dumps(data, indent=2, default=str)
