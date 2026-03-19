"""Data router.

GET  /api/data/injuries      ->  list[TeamInjuriesSchema]
GET  /api/data/team-strength ->  list[TeamStatsSchema]
GET  /api/data/player-stats  ->  list[PlayerStatsEntry]
POST /api/data/refresh       ->  RefreshResponse
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from polynba.data.manager import DataManager
from polynba.data.espn_teams import ESPN_IDS

from ..dependencies import get_data_manager
from ..schemas import (
    PlayerInjurySchema,
    TeamStatsSchema,
    # New schemas defined in schemas.py
    TeamInjuriesSchema,
    PlayerStatsEntry,
    RefreshRequest,
    RefreshResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data", tags=["data"])


# ---------------------------------------------------------------------------
# GET /api/data/injuries
# ---------------------------------------------------------------------------


@router.get(
    "/injuries",
    response_model=list[TeamInjuriesSchema],
    summary="Get all team injuries grouped by team",
)
async def get_injuries(
    data_manager: DataManager = Depends(get_data_manager),
) -> list[TeamInjuriesSchema]:
    """Return all NBA team injuries grouped by team.

    Each entry includes the raw injury list for the team plus a count of
    players who are definitively OUT (status "Out" or "Doubtful").
    """
    try:
        all_injuries: dict[str, list] = await data_manager.get_all_injuries()
    except Exception as exc:
        logger.error("Failed to fetch injuries: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch injury data from upstream source.",
        ) from exc

    result: list[TeamInjuriesSchema] = []
    for team_id, injuries in all_injuries.items():
        team_abbreviation = ESPN_IDS.get(team_id, team_id)
        injury_schemas = [PlayerInjurySchema.from_dataclass(inj) for inj in injuries]
        key_players_out = sum(1 for inj in injuries if inj.is_out)
        result.append(
            TeamInjuriesSchema(
                team_id=team_id,
                team_abbreviation=team_abbreviation,
                injuries=injury_schemas,
                key_players_out=key_players_out,
            )
        )

    # Sort by team_abbreviation for stable ordering
    result.sort(key=lambda t: t.team_abbreviation)
    return result


# ---------------------------------------------------------------------------
# GET /api/data/team-strength
# ---------------------------------------------------------------------------


@router.get(
    "/team-strength",
    response_model=list[TeamStatsSchema],
    summary="Get all 30 teams' season stats sorted by win percentage",
)
async def get_team_strength(
    data_manager: DataManager = Depends(get_data_manager),
) -> list[TeamStatsSchema]:
    """Return season stats for all 30 NBA teams sorted by win percentage descending.

    Includes offensive/defensive ratings, net rating, pace, home/away splits,
    current streak, clutch net rating, and last-10 record.
    """
    try:
        all_stats: dict[str, object] = await data_manager.get_all_team_stats()
    except Exception as exc:
        logger.error("Failed to fetch team stats: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch team stats from upstream source.",
        ) from exc

    schemas = [TeamStatsSchema.from_dataclass(ts) for ts in all_stats.values()]
    schemas.sort(key=lambda s: s.win_percentage, reverse=True)
    return schemas


# ---------------------------------------------------------------------------
# GET /api/data/player-stats
# ---------------------------------------------------------------------------


@router.get(
    "/player-stats",
    response_model=list[PlayerStatsEntry],
    summary="Get player season stats for all teams",
)
async def get_player_stats(
    data_manager: DataManager = Depends(get_data_manager),
) -> list[PlayerStatsEntry]:
    """Return per-player season averages for all NBA teams.

    Players are returned sorted by points per game descending.  Advanced
    stats (true_shooting_pct, usage_rate, net_rating) are included when
    available and are ``null`` otherwise.
    """
    try:
        player_index: dict[str, list] = await data_manager.get_player_index()
    except Exception as exc:
        logger.error("Failed to fetch player index: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch player stats from upstream source.",
        ) from exc

    entries: list[PlayerStatsEntry] = []
    for team_abbreviation, players in player_index.items():
        for p in players:
            entries.append(
                PlayerStatsEntry(
                    player_name=p.player_name,
                    team_abbreviation=team_abbreviation,
                    games_played=p.games_played,
                    minutes_per_game=p.minutes_per_game,
                    points_per_game=p.points_per_game,
                    rebounds_per_game=p.rebounds_per_game,
                    assists_per_game=p.assists_per_game,
                    steals_per_game=p.steals_per_game,
                    blocks_per_game=p.blocks_per_game,
                    field_goal_pct=p.field_goal_pct,
                    three_point_pct=p.three_point_pct,
                    free_throw_pct=p.free_throw_pct,
                    true_shooting_pct=p.true_shooting_pct if p.true_shooting_pct else None,
                    usage_rate=p.usage_pct if p.usage_pct else None,
                    net_rating=p.net_rating if p.net_rating != 0.0 else None,
                )
            )

    entries.sort(key=lambda e: e.points_per_game, reverse=True)
    return entries


# ---------------------------------------------------------------------------
# POST /api/data/refresh
# ---------------------------------------------------------------------------

# Maps from the public API target names to the DataCache cache_type keys
_TARGET_TO_CACHE_TYPES: dict[str, list[str]] = {
    "injuries": ["injuries", "team_context"],
    "team_stats": ["team_stats", "team_context"],
    "player_stats": ["player_index"],
    "all": ["injuries", "team_stats", "team_context", "player_index"],
}


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    summary="Force-refresh specific NBA data caches",
)
async def refresh_data(
    request: RefreshRequest,
    data_manager: DataManager = Depends(get_data_manager),
) -> RefreshResponse:
    """Invalidate and re-fetch specified data caches.

    Accepted ``targets`` values: ``"injuries"``, ``"team_stats"``,
    ``"player_stats"``, ``"all"``.  Duplicate targets are de-duplicated.
    The endpoint invalidates the matching caches, then eagerly re-fetches
    the data so subsequent reads are served from a warm cache.
    """
    if not request.targets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one refresh target must be specified.",
        )

    # De-duplicate targets; if "all" present, short-circuit
    unique_targets: list[str] = list(dict.fromkeys(request.targets))
    if "all" in unique_targets:
        unique_targets = ["all"]

    # Collect cache types to invalidate (de-duplicated)
    cache_types_to_clear: list[str] = []
    for target in unique_targets:
        for ct in _TARGET_TO_CACHE_TYPES.get(target, []):
            if ct not in cache_types_to_clear:
                cache_types_to_clear.append(ct)

    for cache_type in cache_types_to_clear:
        data_manager._cache.invalidate_all(cache_type)
        logger.info("Invalidated cache: %s", cache_type)

    # Re-fetch eagerly — gather all independent fetches in parallel
    fetch_tasks = []
    refreshed_labels: list[str] = []

    # Build a set of logical operations needed based on targets
    needs_injuries = any(t in ("injuries", "all") for t in unique_targets)
    needs_team_stats = any(t in ("team_stats", "all") for t in unique_targets)
    needs_player_stats = any(t in ("player_stats", "all") for t in unique_targets)

    if needs_injuries:
        fetch_tasks.append(data_manager.get_all_injuries())
        refreshed_labels.append("injuries")

    if needs_team_stats:
        fetch_tasks.append(data_manager.get_all_team_stats())
        refreshed_labels.append("team_stats")

    if needs_player_stats:
        fetch_tasks.append(data_manager.get_player_index())
        refreshed_labels.append("player_stats")

    if fetch_tasks:
        try:
            await asyncio.gather(*fetch_tasks)
        except Exception as exc:
            logger.error("Error during cache refresh: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Cache invalidated but re-fetch failed: {exc}",
            ) from exc

    logger.info("Data refresh complete for targets: %s", refreshed_labels)
    return RefreshResponse(
        refreshed=refreshed_labels,
        message=f"Successfully refreshed: {', '.join(refreshed_labels)}.",
    )
