"""Games router.

GET /api/games                    ->  list[GameSummarySchema]   (fast, no Polymarket)
GET /api/games/{game_id}/context  ->  GameContextResponse
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from polynba.data.manager import DataManager
from polynba.data.models import GameStatus

from ..dependencies import get_data_manager
from ..schemas import (
    GameContextResponse,
    GameSummarySchema,
    HeadToHeadSchema,
    TeamContextSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/games", tags=["games"])


@router.get(
    "",
    response_model=list[GameSummarySchema],
    summary="List games for a date (fast, no Polymarket data)",
)
async def list_games(
    date: Optional[str] = Query(
        default=None,
        description="Date in YYYYMMDD format. Defaults to today (US/Eastern).",
        pattern=r"^\d{8}$",
    ),
    data_manager: DataManager = Depends(get_data_manager),
) -> list[GameSummarySchema]:
    """Return ESPN game summaries for the given date.

    This is a fast endpoint (<500ms) that returns only game metadata
    (teams, time, status, scores) without any Polymarket market or price data.
    Use ``/api/markets`` for enriched data with prices and verdicts.
    """
    all_games = await data_manager.get_all_games(date=date)
    return [GameSummarySchema.from_dataclass(g) for g in all_games]


@router.get(
    "/{game_id}/context",
    response_model=GameContextResponse,
    summary="Get team contexts and head-to-head for a specific game",
)
async def game_context(
    game_id: str,
    data_manager: DataManager = Depends(get_data_manager),
) -> GameContextResponse:
    """Return enriched team contexts (stats, injuries, rotation) and H2H data
    for both teams in the specified game.

    The response includes:
    - ``home_context``: Full TeamContext for the home team, including
      TeamStats, injury list with player stats, and rotation depth.
    - ``away_context``: Full TeamContext for the away team.
    - ``head_to_head``: Current-season H2H record between the two teams
      (may be None when no games have been played between them yet).

    This endpoint is useful for displaying pre-game team cards without
    running the full analysis pipeline.
    """
    # Find the game across all statuses (not just pre-game) so we can
    # serve context for games that are in-progress or already final too.
    all_games = await data_manager.get_all_games(date=None)
    game = next((g for g in all_games if g.game_id == game_id), None)

    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game '{game_id}' not found.",
        )

    # Fetch both team contexts in parallel
    home_ctx, away_ctx = await asyncio.gather(
        data_manager.get_team_context(game.home_team_id, game.away_team_id),
        data_manager.get_team_context(game.away_team_id, game.home_team_id),
    )

    # Fetch H2H independently (may fail gracefully)
    h2h = None
    try:
        h2h = await data_manager.get_head_to_head(game.home_team_id, game.away_team_id)
    except Exception as exc:
        logger.debug("H2H fetch failed for game %s: %s", game_id, exc)

    return GameContextResponse(
        game_id=game_id,
        home_context=TeamContextSchema.from_dataclass(home_ctx) if home_ctx else None,
        away_context=TeamContextSchema.from_dataclass(away_ctx) if away_ctx else None,
        head_to_head=HeadToHeadSchema.from_dataclass(h2h) if h2h else None,
    )
