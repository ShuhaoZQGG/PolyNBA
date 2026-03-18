"""Backend configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

load_dotenv()  # Load from .env in project root

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
]

# Paper vs Live mode
POLYMARKET_PRIVATE_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY")
IS_LIVE_MODE = bool(POLYMARKET_PRIVATE_KEY)

# Default bankroll
DEFAULT_BANKROLL = float(os.environ.get("POLYNBA_BANKROLL", "500"))

# Default scan date (YYYYMMDD); None means "today in US/Eastern"
DEFAULT_SCAN_DATE: str | None = os.environ.get("POLYNBA_SCAN_DATE")

# AI analysis settings
AI_ANALYSIS_ENABLED = os.environ.get("POLYNBA_AI_ANALYSIS", "true").lower() == "true"
AI_MODEL = os.environ.get("POLYNBA_AI_MODEL", "claude-haiku-4-5-20251001")
