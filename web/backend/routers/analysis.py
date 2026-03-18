"""Analysis router.

POST /api/analysis/run-all              ->  list[GameAdvisoryResponse]
POST /api/analysis/{game_id}/run        ->  GameAdvisoryResponse
GET  /api/analysis/{game_id}            ->  GameAdvisoryResponse  (cached)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from polynba.data.manager import DataManager
from polynba.polymarket.market_discovery import MarketDiscovery
from polynba.polymarket.price_fetcher import PriceFetcher
from polynba.pregame.advisor import GameAdvisory

from ..config import DEFAULT_BANKROLL, DEFAULT_SCAN_DATE
from ..dependencies import (
    get_data_manager,
    get_market_discovery,
    get_price_fetcher,
)
from ..schemas import GameAdvisoryResponse
from ..services.advisor_service import run_all_analysis, run_single_game_analysis
from ..services.market_service import get_market_for_game

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# ---------------------------------------------------------------------------
# In-memory advisory cache with TTL: game_id -> (timestamp, GameAdvisory)
# Serves as the primary cache — run-all returns from here when hot.
# ---------------------------------------------------------------------------
ANALYSIS_CACHE_TTL = timedelta(hours=4)

_advisory_cache: dict[str, tuple[datetime, GameAdvisory]] = {}

# Track which dates have been fully analysed so run-all can short-circuit.
_analysed_dates: dict[str, datetime] = {}


def _cache_advisories(advisories: list[GameAdvisory], date_key: str) -> None:
    """Store or overwrite the cache entries for a list of advisories."""
    now = datetime.now()
    for adv in advisories:
        _advisory_cache[adv.game.game_id] = (now, adv)
    _analysed_dates[date_key] = now


def _get_cached(game_id: str) -> GameAdvisory | None:
    """Return a cached advisory if it exists and hasn't expired."""
    entry = _advisory_cache.get(game_id)
    if entry is None:
        return None
    ts, adv = entry
    if datetime.now() - ts > ANALYSIS_CACHE_TTL:
        del _advisory_cache[game_id]
        return None
    return adv


def _get_cached_timestamp(game_id: str) -> datetime | None:
    """Return the timestamp when the cached advisory was stored."""
    entry = _advisory_cache.get(game_id)
    if entry is None:
        return None
    return entry[0]


def _get_all_cached_for_date(date_key: str) -> list[tuple[GameAdvisory, datetime]] | None:
    """Return all cached advisories for a date if the full run is still fresh."""
    ts = _analysed_dates.get(date_key)
    if ts is None or datetime.now() - ts > ANALYSIS_CACHE_TTL:
        _analysed_dates.pop(date_key, None)
        return None
    # Collect all entries that were cached at or after the date-run timestamp
    results = []
    for game_id, (entry_ts, adv) in list(_advisory_cache.items()):
        if entry_ts >= ts:
            results.append((adv, entry_ts))
    return results if results else None


def _invalidate_date(date_key: str) -> None:
    """Bust the date-level cache so the next run-all re-runs the pipeline."""
    _analysed_dates.pop(date_key, None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/run-all",
    response_model=list[GameAdvisoryResponse],
    summary="Run full pre-game analysis for all matched games today",
)
async def run_all(
    date: Optional[str] = Query(
        default=None,
        description="Date in YYYYMMDD format.  Defaults to today (US/Eastern).",
        pattern=r"^\d{8}$",
    ),
    bankroll: float = Query(
        default=DEFAULT_BANKROLL,
        gt=0,
        description="Bankroll in USDC for Kelly sizing.",
    ),
    with_ai: bool = Query(
        default=True,
        description="Whether to run AI (Claude) analysis on actionable games.",
    ),
    force: bool = Query(
        default=False,
        description="Force fresh analysis, busting all caches.",
    ),
    data_manager: DataManager = Depends(get_data_manager),
    market_discovery: MarketDiscovery = Depends(get_market_discovery),
    price_fetcher: PriceFetcher = Depends(get_price_fetcher),
) -> list[GameAdvisoryResponse]:
    """Run the full pre-game analysis pipeline for all games that have a
    matching Polymarket market.

    When ``force=False`` (the default), returns cached results immediately if
    a previous run for this date is still fresh (4-hour TTL).  This makes
    repeated clicks of "Run All Analysis" instant.

    Pass ``force=True`` to bust the cache and re-run everything from scratch,
    including fresh AI analysis.

    Results are cached in memory by ``game_id`` so subsequent ``GET
    /api/analysis/{game_id}`` calls also return instantly.
    """
    date_key = date or DEFAULT_SCAN_DATE or "today"

    # --- Fast path: return from cache if the full date-run is still fresh ---
    if not force:
        cached_all = _get_all_cached_for_date(date_key)
        if cached_all:
            logger.info("Returning %d cached advisories for date=%s", len(cached_all), date_key)
            return [
                GameAdvisoryResponse.from_advisory(adv, analyzed_at=ts)
                for adv, ts in cached_all
            ]

    # --- Slow path: run the pipeline ---
    if force:
        _invalidate_date(date_key)

    # When not forcing, selectively reuse cached AI
    skip_ai = False
    if with_ai and not force:
        skip_ai = True

    advisories = await run_all_analysis(
        data_manager=data_manager,
        market_discovery=market_discovery,
        price_fetcher=price_fetcher,
        bankroll=bankroll,
        scan_date=date or DEFAULT_SCAN_DATE,
        with_ai=with_ai if not skip_ai else False,
        force=force,
    )

    if skip_ai and advisories:
        # Reuse cached AI for games that have it; run fresh AI for the rest
        needs_ai: list[GameAdvisory] = []
        for adv in advisories:
            cached = _get_cached(adv.game.game_id)
            if cached and cached.ai_detail:
                adv.ai_analysis = cached.ai_analysis
                adv.ai_detail = cached.ai_detail
            else:
                needs_ai.append(adv)

        if needs_ai:
            from polynba.pregame.ai_analyzer import PregameAIAnalyzer
            from ..config import AI_ANALYSIS_ENABLED, AI_MODEL
            actionable = [
                a for a in needs_ai
                if a.estimate.verdict.startswith("BET") or a.estimate.verdict.startswith("SPECULATE")
            ]
            if actionable and AI_ANALYSIS_ENABLED:
                logger.info("Running AI analysis for %d games (cache miss)...", len(actionable))
                ai_analyzer = PregameAIAnalyzer(model=AI_MODEL)
                await ai_analyzer.analyze_games(actionable)

    _cache_advisories(advisories, date_key)

    return [
        GameAdvisoryResponse.from_advisory(adv, analyzed_at=_get_cached_timestamp(adv.game.game_id))
        for adv in advisories
    ]


@router.post(
    "/{game_id}/run",
    response_model=GameAdvisoryResponse,
    summary="Run pre-game analysis for a specific game",
)
async def run_single(
    game_id: str,
    date: Optional[str] = Query(
        default=None,
        description="Date in YYYYMMDD format.  Defaults to today (US/Eastern).",
        pattern=r"^\d{8}$",
    ),
    bankroll: float = Query(
        default=DEFAULT_BANKROLL,
        gt=0,
        description="Bankroll in USDC for Kelly sizing.",
    ),
    with_ai: bool = Query(
        default=True,
        description="Whether to run AI (Claude) analysis.",
    ),
    force: bool = Query(
        default=False,
        description="Force fresh AI analysis, ignoring cached results.",
    ),
    data_manager: DataManager = Depends(get_data_manager),
    market_discovery: MarketDiscovery = Depends(get_market_discovery),
    price_fetcher: PriceFetcher = Depends(get_price_fetcher),
) -> GameAdvisoryResponse:
    """Run full pre-game analysis for a single game.

    The game must be in a pre-game / scheduled state and must have a
    corresponding Polymarket market.  The primary advisory (highest |edge|)
    is returned; the optional conviction RESOLUTION advisory for the
    opposite side is discarded (it can be retrieved via ``/run-all``).

    When ``force=False`` and a non-expired cached AI analysis exists, the
    cached ``ai_detail`` is reused on the fresh quant result.
    """
    triple = await get_market_for_game(
        game_id=game_id,
        data_manager=data_manager,
        market_discovery=market_discovery,
        price_fetcher=price_fetcher,
        date=date or DEFAULT_SCAN_DATE,
    )

    if triple is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found or has no matching Polymarket market.",
        )

    game, market, _prices = triple

    # Check if we can reuse cached AI analysis
    skip_ai = False
    if with_ai and not force:
        cached = _get_cached(game_id)
        if cached and cached.ai_detail:
            skip_ai = True

    advisories = await run_single_game_analysis(
        game=game,
        market=market,
        data_manager=data_manager,
        price_fetcher=price_fetcher,
        bankroll=bankroll,
        scan_date=date or DEFAULT_SCAN_DATE,
        with_ai=with_ai if not skip_ai else False,
    )

    if not advisories:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Analysis pipeline produced no results for game '{game_id}'.",
        )

    # Reuse cached AI if we skipped the fresh call
    if skip_ai:
        cached = _get_cached(game_id)
        if cached and cached.ai_detail:
            for adv in advisories:
                adv.ai_analysis = cached.ai_analysis
                adv.ai_detail = cached.ai_detail

    # Cache all returned advisories (primary + optional conviction advisory).
    # Use a per-game key so single-game runs don't interfere with date-level cache.
    now = datetime.now()
    for adv in advisories:
        _advisory_cache[adv.game.game_id] = (now, adv)

    # Return the primary advisory (first in list, highest |edge|)
    primary = advisories[0]
    return GameAdvisoryResponse.from_advisory(primary, analyzed_at=_get_cached_timestamp(primary.game.game_id))


@router.get(
    "/{game_id}",
    response_model=GameAdvisoryResponse,
    summary="Get cached analysis for a specific game",
)
async def get_cached(game_id: str) -> GameAdvisoryResponse:
    """Return the most recently computed analysis for the given game.

    Returns HTTP 404 if analysis has not been run yet or has expired.
    Call ``POST /api/analysis/{game_id}/run`` first to populate the cache.
    """
    advisory = _get_cached(game_id)
    if advisory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No cached analysis found for game '{game_id}'. "
                "Run POST /api/analysis/{game_id}/run first."
            ),
        )
    return GameAdvisoryResponse.from_advisory(advisory, analyzed_at=_get_cached_timestamp(game_id))
