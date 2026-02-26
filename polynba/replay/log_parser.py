"""Parse bot log files into MarketSnapshot sequences."""

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .models import MarketSnapshot

# Strip ANSI escape codes
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Log line timestamp + message extraction
LOG_LINE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+-\s+\S+\s+-\s+\S+\s+-\s+(.*)"
)

# Patterns for data extraction
ITERATION_RE = re.compile(r"Loop iteration (\d+)")
PROCESSING_RE = re.compile(
    r"Processing:\s+(\w+)\s+@\s+(\w+)\s+\|\s+(\d+)-(\d+)\s+\|\s+(Q[1-4]|OT\d*)\s+([\d:.]+)"
)
PRICES_RE = re.compile(
    r"\[Real Polymarket prices\]\s+home=([\d.]+)%,\s+away=([\d.]+)%"
)
MARKET_RE = re.compile(
    r"Market:\s+(\w+)\s+([\d.]+)%\s+\|\s+Edge:\s+([+-]?[\d.]+)%\s+\|\s+Confidence:\s+(\d+)/10"
)
NO_EDGE_RE = re.compile(r"No edge opportunity \(need >= ([\d.]+)% edge\)")
SIGNAL_RE = re.compile(r">>> SIGNAL:")
EDGE_FOUND_RE = re.compile(r">>> EDGE FOUND:")
BANKROLL_RE = re.compile(r"Bankroll:\s+\$([\d.]+)")
STRATEGIES_RE = re.compile(r"Active strategies:\s+\[(.+)\]")


def _parse_clock(clock_str: str) -> int:
    """Parse clock string to seconds remaining in period.

    Handles formats: "6:22" (min:sec), "35.6" (seconds), "0.0", "0:00"
    """
    if not clock_str or clock_str in ("0:00", "0.0", "0"):
        return 0

    if ":" in clock_str:
        parts = clock_str.split(":")
        try:
            minutes = int(parts[0])
            seconds = int(parts[1])
            return minutes * 60 + seconds
        except (ValueError, IndexError):
            return 0
    else:
        # Seconds-only format like "35.6"
        try:
            return int(float(clock_str))
        except ValueError:
            return 0


def _period_to_quarter_number(period_str: str) -> int:
    """Convert period string to numeric quarter (1-8).

    Q1->1, Q2->2, Q3->3, Q4->4, OT1->5, OT->5, OT2->6, etc.
    """
    if period_str.startswith("Q"):
        return int(period_str[1])
    if period_str.startswith("OT"):
        ot_num = period_str[2:] if len(period_str) > 2 else "1"
        return 4 + int(ot_num or 1)
    return 1


def _total_seconds_remaining(quarter: int, clock_seconds: int) -> int:
    """Calculate total seconds remaining in game.

    Same logic as GameState.total_seconds_remaining:
    - Regular time: remaining quarters * 720 + clock_seconds
    - Overtime: just clock_seconds
    """
    if quarter <= 4:
        remaining_quarters = 4 - quarter
        return remaining_quarters * 12 * 60 + clock_seconds
    else:
        return clock_seconds


class LogParser:
    """Parses bot log files into MarketSnapshot sequences."""

    def __init__(self, log_path: str | Path):
        """Initialize parser.

        Args:
            log_path: Path to log directory or full.txt file
        """
        path = Path(log_path)
        if path.is_dir():
            self._log_file = path / "full.txt"
        else:
            self._log_file = path

        if not self._log_file.exists():
            raise FileNotFoundError(f"Log file not found: {self._log_file}")

        self.bankroll: Optional[Decimal] = None
        self.active_strategies: list[str] = []

    @property
    def log_dir(self) -> Path:
        return self._log_file.parent

    def parse(self) -> list[MarketSnapshot]:
        """Parse log file into list of MarketSnapshots.

        Returns:
            List of snapshots, one per iteration that has complete data
        """
        raw = self._log_file.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()

        snapshots: list[MarketSnapshot] = []
        signal_count = 0

        # Current iteration state
        cur_iter: Optional[int] = None
        cur_ts: Optional[datetime] = None
        cur_away: Optional[str] = None
        cur_home: Optional[str] = None
        cur_away_score: int = 0
        cur_home_score: int = 0
        cur_period: str = "Q1"
        cur_clock: str = "0:00"
        cur_home_price: Optional[Decimal] = None
        cur_away_price: Optional[Decimal] = None
        cur_home_edge: Optional[float] = None
        cur_away_edge: Optional[float] = None
        cur_confidence: int = 0
        cur_edge_threshold: Optional[float] = None
        cur_has_signal: bool = False
        cur_signal_details: Optional[str] = None

        def _flush():
            """Save current iteration as a snapshot if we have enough data."""
            nonlocal cur_iter
            if (
                cur_iter is not None
                and cur_ts is not None
                and cur_home is not None
                and cur_home_price is not None
            ):
                clock_secs = _parse_clock(cur_clock)
                quarter = _period_to_quarter_number(cur_period)
                total_secs = _total_seconds_remaining(quarter, clock_secs)

                snapshots.append(
                    MarketSnapshot(
                        timestamp=cur_ts,
                        iteration=cur_iter,
                        away_team=cur_away or "",
                        home_team=cur_home or "",
                        away_score=cur_away_score,
                        home_score=cur_home_score,
                        period=cur_period,
                        clock=cur_clock,
                        clock_seconds=clock_secs,
                        total_seconds_remaining=total_secs,
                        home_market_price=cur_home_price,
                        away_market_price=cur_away_price or (Decimal("1") - cur_home_price),
                        home_edge_pct=cur_home_edge or 0.0,
                        away_edge_pct=cur_away_edge or 0.0,
                        confidence=cur_confidence,
                        original_edge_threshold=cur_edge_threshold,
                        has_signal=cur_has_signal,
                        signal_details=cur_signal_details,
                    )
                )

        for line in lines:
            # Strip ANSI codes
            clean = ANSI_RE.sub("", line)

            # Extract timestamp and message
            m = LOG_LINE_RE.match(clean)
            if not m:
                continue
            ts_str, msg = m.group(1), m.group(2)

            # Parse header info (once)
            if self.bankroll is None:
                bm = BANKROLL_RE.search(msg)
                if bm:
                    self.bankroll = Decimal(bm.group(1))

            if not self.active_strategies:
                sm = STRATEGIES_RE.search(msg)
                if sm:
                    raw_list = sm.group(1)
                    self.active_strategies = [
                        s.strip().strip("'\"")
                        for s in raw_list.split(",")
                    ]

            # New iteration
            im = ITERATION_RE.search(msg)
            if im:
                # Flush previous iteration
                _flush()
                cur_iter = int(im.group(1))
                try:
                    cur_ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f")
                except ValueError:
                    cur_ts = None
                # Reset per-iteration state
                cur_home_price = None
                cur_away_price = None
                cur_home_edge = None
                cur_away_edge = None
                cur_confidence = 0
                cur_edge_threshold = None
                cur_has_signal = False
                cur_signal_details = None
                continue

            # Processing line (game info)
            pm = PROCESSING_RE.search(msg)
            if pm:
                cur_away = pm.group(1)
                cur_home = pm.group(2)
                cur_away_score = int(pm.group(3))
                cur_home_score = int(pm.group(4))
                cur_period = pm.group(5)
                cur_clock = pm.group(6)
                continue

            # Market prices
            prm = PRICES_RE.search(msg)
            if prm:
                cur_home_price = Decimal(prm.group(1)) / 100
                cur_away_price = Decimal(prm.group(2)) / 100
                continue

            # Edge per side
            mm = MARKET_RE.search(msg)
            if mm:
                team = mm.group(1)
                edge = float(mm.group(3))
                conf = int(mm.group(4))
                cur_confidence = conf
                if cur_home and team == cur_home:
                    cur_home_edge = edge
                elif cur_away and team == cur_away:
                    cur_away_edge = edge
                continue

            # No edge (captures threshold)
            nem = NO_EDGE_RE.search(msg)
            if nem:
                cur_edge_threshold = float(nem.group(1))
                continue

            # Signal
            if SIGNAL_RE.search(msg):
                cur_has_signal = True
                cur_signal_details = msg.strip()
                signal_count += 1
                continue

            # Edge found (also counts)
            if EDGE_FOUND_RE.search(msg):
                continue

        # Flush last iteration
        _flush()

        self._original_signal_count = signal_count
        return snapshots

    @property
    def original_signal_count(self) -> int:
        """Number of SIGNAL lines found in the original log."""
        return getattr(self, "_original_signal_count", 0)
