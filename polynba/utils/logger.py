"""Structured logging configuration."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message",
            ):
                log_data[key] = value

        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """Colored console formatter."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format with colors."""
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    structured: bool = False,
    log_dir: Optional[Path] = None,
) -> logging.Logger:
    """Set up logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file name
        structured: Use JSON-structured logging
        log_dir: Directory for log files

    Returns:
        Root logger
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    if structured:
        console_formatter = StructuredFormatter()
    else:
        console_formatter = ColoredFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%H:%M:%S",
        )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler
    if log_file:
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / log_file
        else:
            log_path = Path(log_file)

        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)

        if structured:
            file_formatter = StructuredFormatter()
        else:
            file_formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Set levels for noisy libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    return root_logger


class TradeLogger:
    """Specialized logger for trade events."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize trade logger.

        Args:
            logger: Optional logger instance
        """
        self._logger = logger or logging.getLogger("polynba.trades")

    def log_signal(
        self,
        strategy_id: str,
        game_id: str,
        side: str,
        edge: float,
        confidence: int,
        size: float,
    ) -> None:
        """Log a trading signal."""
        self._logger.info(
            f"SIGNAL: {strategy_id} | {game_id} | {side} | "
            f"edge={edge:.1f}% | conf={confidence} | size=${size:.2f}",
            extra={
                "event": "signal",
                "strategy_id": strategy_id,
                "game_id": game_id,
                "side": side,
                "edge": edge,
                "confidence": confidence,
                "size": size,
            },
        )

    def log_order(
        self,
        order_id: str,
        action: str,
        market_id: str,
        side: str,
        size: float,
        price: float,
    ) -> None:
        """Log an order event."""
        self._logger.info(
            f"ORDER: {action} | {order_id} | {side} {size} @ {price:.4f}",
            extra={
                "event": "order",
                "order_id": order_id,
                "action": action,
                "market_id": market_id,
                "side": side,
                "size": size,
                "price": price,
            },
        )

    def log_fill(
        self,
        order_id: str,
        fill_price: float,
        fill_size: float,
    ) -> None:
        """Log an order fill."""
        self._logger.info(
            f"FILL: {order_id} | {fill_size} @ {fill_price:.4f}",
            extra={
                "event": "fill",
                "order_id": order_id,
                "fill_price": fill_price,
                "fill_size": fill_size,
            },
        )

    def log_exit(
        self,
        position_id: str,
        reason: str,
        pnl: float,
        pnl_percent: float,
    ) -> None:
        """Log a position exit."""
        self._logger.info(
            f"EXIT: {position_id} | {reason} | PnL=${pnl:.2f} ({pnl_percent:.1f}%)",
            extra={
                "event": "exit",
                "position_id": position_id,
                "reason": reason,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
            },
        )

    def log_error(self, message: str, **kwargs: Any) -> None:
        """Log an error with context."""
        self._logger.error(message, extra={"event": "error", **kwargs})
