"""FastAPI application factory for the PolyNBA web backend.

Run with:
    uvicorn web.backend.app:app --reload --port 8000

Or from the project root:
    python -m uvicorn web.backend.app:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS, IS_LIVE_MODE
from .dependencies import init_services, shutdown_services
from .routers import analysis, data, games, markets, portfolio, positions, pregame_orders, trading

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise shared services on startup and clean them up on shutdown."""
    await init_services()
    yield
    await shutdown_services()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


app = FastAPI(
    title="PolyNBA API",
    description=(
        "Backend API for the PolyNBA pre-game betting advisor web application.\n\n"
        "Provides NBA game data, Polymarket market discovery, pre-game probability "
        "analysis (with optional Claude AI), and trading execution (paper or live)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(portfolio.router)
app.include_router(positions.router)
app.include_router(markets.router)
app.include_router(analysis.router)
app.include_router(trading.router)
app.include_router(games.router)
app.include_router(pregame_orders.router)
app.include_router(data.router)


# ---------------------------------------------------------------------------
# Health / info endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict:
    """Return service health status."""
    return {"status": "ok", "live_mode": IS_LIVE_MODE}


@app.get("/", tags=["system"], summary="API root")
async def root() -> dict:
    """Return basic API information."""
    return {
        "name": "PolyNBA API",
        "version": "1.0.0",
        "docs": "/docs",
        "live_mode": IS_LIVE_MODE,
    }
