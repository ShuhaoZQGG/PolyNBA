"""Parser for NBA.com CDN responses."""

import logging
from datetime import datetime
from typing import Any, Optional

from ...models import (
    EventType,
    GameState,
    GameStatus,
    GameSummary,
    Period,
    PlayEvent,
    TeamGameState,
)

logger = logging.getLogger(__name__)


class NBAParser:
    """Parser for NBA.com CDN JSON responses."""

    @staticmethod
    def parse_scoreboard(data: dict[str, Any]) -> list[GameSummary]:
        """Parse scoreboard response to list of GameSummary.

        Args:
            data: NBA.com scoreboard JSON response

        Returns:
            List of GameSummary objects
        """
        games = []

        scoreboard = data.get("scoreboard", {})

        for game in scoreboard.get("games", []):
            try:
                summary = NBAParser._parse_game_to_summary(game)
                if summary:
                    games.append(summary)
            except Exception as e:
                logger.warning(f"Failed to parse game: {e}")

        return games

    @staticmethod
    def _parse_game_to_summary(game: dict[str, Any]) -> Optional[GameSummary]:
        """Parse a single game to GameSummary."""
        home_team = game.get("homeTeam", {})
        away_team = game.get("awayTeam", {})

        # Parse status
        game_status = game.get("gameStatus", 1)
        game_status_text = game.get("gameStatusText", "")

        if game_status == 1:
            status = GameStatus.SCHEDULED
        elif game_status == 2:
            if "halftime" in game_status_text.lower():
                status = GameStatus.HALFTIME
            else:
                status = GameStatus.IN_PROGRESS
        elif game_status == 3:
            status = GameStatus.FINAL
        else:
            status = GameStatus.SCHEDULED

        # Parse period
        period_value = game.get("period", 1)
        period = Period.from_int(period_value)

        # Parse clock
        clock = game.get("gameClock", "0:00")
        # NBA format might be "PT05M32.00S", convert to "5:32"
        if clock.startswith("PT"):
            clock = NBAParser._parse_iso_duration(clock)

        # Parse date
        game_date = None
        date_str = game.get("gameTimeUTC")
        if date_str:
            try:
                game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        return GameSummary(
            game_id=game.get("gameId", ""),
            status=status,
            period=period,
            clock=clock,
            home_team_id=str(home_team.get("teamId", "")),
            home_team_name=home_team.get("teamName", ""),
            home_team_abbreviation=home_team.get("teamTricode", ""),
            home_score=home_team.get("score", 0),
            away_team_id=str(away_team.get("teamId", "")),
            away_team_name=away_team.get("teamName", ""),
            away_team_abbreviation=away_team.get("teamTricode", ""),
            away_score=away_team.get("score", 0),
            game_date=game_date,
        )

    @staticmethod
    def _parse_iso_duration(duration: str) -> str:
        """Parse ISO 8601 duration to clock format.

        Args:
            duration: ISO duration like "PT05M32.00S"

        Returns:
            Clock string like "5:32"
        """
        try:
            # Remove PT prefix
            duration = duration.replace("PT", "")

            minutes = 0
            seconds = 0

            if "M" in duration:
                mins, duration = duration.split("M")
                minutes = int(mins)

            if "S" in duration:
                secs = duration.replace("S", "")
                seconds = int(float(secs))

            return f"{minutes}:{seconds:02d}"
        except (ValueError, IndexError):
            return "0:00"

    @staticmethod
    def parse_boxscore(data: dict[str, Any]) -> Optional[GameState]:
        """Parse boxscore response to GameState.

        Args:
            data: NBA.com boxscore JSON response

        Returns:
            GameState object or None if parsing fails
        """
        try:
            game = data.get("game", {})

            home_team_data = game.get("homeTeam", {})
            away_team_data = game.get("awayTeam", {})

            # Parse status
            game_status = game.get("gameStatus", 1)
            game_status_text = game.get("gameStatusText", "")

            if game_status == 1:
                status = GameStatus.SCHEDULED
            elif game_status == 2:
                if "halftime" in game_status_text.lower():
                    status = GameStatus.HALFTIME
                else:
                    status = GameStatus.IN_PROGRESS
            elif game_status == 3:
                status = GameStatus.FINAL
            else:
                status = GameStatus.SCHEDULED

            # Parse period and clock
            period_value = game.get("period", 1)
            period = Period.from_int(period_value)

            clock = game.get("gameClock", "0:00")
            if clock.startswith("PT"):
                clock = NBAParser._parse_iso_duration(clock)

            # Parse team states
            home_team = NBAParser._parse_team_boxscore(home_team_data)
            away_team = NBAParser._parse_team_boxscore(away_team_data)

            return GameState(
                game_id=game.get("gameId", ""),
                status=status,
                period=period,
                clock=clock,
                home_team=home_team,
                away_team=away_team,
                recent_plays=[],  # Would need separate play-by-play call
            )

        except Exception as e:
            logger.error(f"Failed to parse boxscore: {e}")
            return None

    @staticmethod
    def _parse_team_boxscore(team_data: dict[str, Any]) -> TeamGameState:
        """Parse team boxscore data to TeamGameState."""
        statistics = team_data.get("statistics", {})

        # Get period scores
        periods = team_data.get("periods", [])
        period_scores = [int(p.get("score", 0)) for p in periods]

        return TeamGameState(
            team_id=str(team_data.get("teamId", "")),
            team_name=team_data.get("teamName", ""),
            team_abbreviation=team_data.get("teamTricode", ""),
            score=team_data.get("score", 0),
            timeouts_remaining=team_data.get("timeoutsRemaining", 7),
            period_scores=period_scores,
            field_goals_made=statistics.get("fieldGoalsMade", 0),
            field_goals_attempted=statistics.get("fieldGoalsAttempted", 0),
            three_pointers_made=statistics.get("threePointersMade", 0),
            three_pointers_attempted=statistics.get("threePointersAttempted", 0),
            free_throws_made=statistics.get("freeThrowsMade", 0),
            free_throws_attempted=statistics.get("freeThrowsAttempted", 0),
            rebounds=statistics.get("reboundsTotal", 0),
            assists=statistics.get("assists", 0),
            turnovers=statistics.get("turnovers", 0),
            steals=statistics.get("steals", 0),
            blocks=statistics.get("blocks", 0),
        )

    @staticmethod
    def parse_playbyplay(data: dict[str, Any], home_team_id: str) -> list[PlayEvent]:
        """Parse play-by-play data.

        Args:
            data: NBA.com play-by-play JSON response
            home_team_id: Home team ID for context

        Returns:
            List of PlayEvent objects
        """
        plays = []

        game = data.get("game", {})
        actions = game.get("actions", [])

        # Get last 20 actions
        recent_actions = actions[-20:] if len(actions) > 20 else actions

        for action in reversed(recent_actions):
            try:
                play = NBAParser._parse_action(action)
                if play:
                    plays.append(play)
            except Exception as e:
                logger.debug(f"Failed to parse action: {e}")

        return plays

    @staticmethod
    def _parse_action(action: dict[str, Any]) -> Optional[PlayEvent]:
        """Parse a single action to PlayEvent."""
        action_type = action.get("actionType", "")
        description = action.get("description", "")

        # Determine event type from action type
        event_type = EventType.from_espn_type(0, description or action_type)

        # Parse period
        period_value = action.get("period", 1)
        period = Period.from_int(period_value)

        # Parse clock
        clock = action.get("clock", "0:00")
        if clock.startswith("PT"):
            clock = NBAParser._parse_iso_duration(clock)

        # Get score value
        score_value = 0
        if action.get("shotResult") == "Made":
            if "3pt" in action_type.lower() or "three" in description.lower():
                score_value = 3
            elif "free throw" in action_type.lower():
                score_value = 1
            else:
                score_value = 2

        return PlayEvent(
            event_id=str(action.get("actionNumber", "")),
            period=period,
            clock=clock,
            event_type=event_type,
            description=description,
            team_id=str(action.get("teamId", "")),
            player_id=str(action.get("personId", "")),
            player_name=action.get("playerNameI", ""),
            score_value=score_value,
            home_score=action.get("scoreHome", 0),
            away_score=action.get("scoreAway", 0),
        )
