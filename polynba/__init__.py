"""PolyNBA - NBA Live In-Game Trading Bot for Polymarket.

An automated trading bot that identifies mispriced odds during live NBA games
and executes profitable mean-reversion trades using AI-powered analysis.
"""

__version__ = "0.1.0"
__author__ = "PolyNBA Team"

from .bot import BotConfig, TradingBot, run_bot

__all__ = [
    "__version__",
    "BotConfig",
    "TradingBot",
    "run_bot",
]
