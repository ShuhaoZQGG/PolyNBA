"""Parser for ESPN API responses to data models."""

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
    TeamStats,
)

logger = logging.getLogger(__name__)


class ESPNParser:
    """Parser for ESPN API JSON responses."""

    @staticmethod
    def parse_scoreboard(data: dict[str, Any]) -> list[GameSummary]:
        """Parse scoreboard response to list of GameSummary.

        Args:
            data: ESPN scoreboard JSON response

        Returns:
            List of GameSummary objects
        """
        games = []

        for event in data.get("events", []):
            try:
                game = ESPNParser._parse_event_to_summary(event)
                if game:
                    games.append(game)
            except Exception as e:
                logger.warning(f"Failed to parse event {event.get('id', 'unknown')}: {e}")

        return games

    @staticmethod
    def _parse_event_to_summary(event: dict[str, Any]) -> Optional[GameSummary]:
        """Parse a single event to GameSummary."""
        competition = event.get("competitions", [{}])[0]
        competitors = competition.get("competitors", [])

        if len(competitors) < 2:
            return None

        # ESPN returns home team with homeAway == "home"
        home_team = None
        away_team = None

        for comp in competitors:
            if comp.get("homeAway") == "home":
                home_team = comp
            else:
                away_team = comp

        if not home_team or not away_team:
            return None

        status_data = competition.get("status", {})
        status_type = status_data.get("type", {})

        # Parse status
        status = GameStatus.from_espn_status(
            status_type.get("id", 1),
            status_type.get("state", "pre"),
        )

        # Parse period
        period_value = status_data.get("period", 1)
        period = Period.from_int(period_value)

        # Parse clock
        clock = status_data.get("displayClock", "0:00")

        # Parse game date
        game_date = None
        date_str = event.get("date")
        if date_str:
            try:
                game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Get broadcast info
        broadcast = None
        broadcasts = competition.get("broadcasts", [])
        if broadcasts:
            names = broadcasts[0].get("names", [])
            if names:
                broadcast = names[0]

        return GameSummary(
            game_id=event.get("id", ""),
            status=status,
            period=period,
            clock=clock,
            home_team_id=home_team.get("team", {}).get("id", ""),
            home_team_name=home_team.get("team", {}).get("displayName", ""),
            home_team_abbreviation=home_team.get("team", {}).get("abbreviation", ""),
            home_score=int(home_team.get("score", 0)),
            away_team_id=away_team.get("team", {}).get("id", ""),
            away_team_name=away_team.get("team", {}).get("displayName", ""),
            away_team_abbreviation=away_team.get("team", {}).get("abbreviation", ""),
            away_score=int(away_team.get("score", 0)),
            game_date=game_date,
            broadcast=broadcast,
        )

    @staticmethod
    def parse_game_summary(data: dict[str, Any]) -> Optional[GameState]:
        """Parse game summary response to GameState.

        Args:
            data: ESPN game summary JSON response

        Returns:
            GameState object or None if parsing fails
        """
        try:
            header = data.get("header", {})
            competitions = header.get("competitions", [{}])

            if not competitions:
                return None

            competition = competitions[0]
            competitors = competition.get("competitors", [])

            if len(competitors) < 2:
                return None

            # Get home and away teams
            home_data = None
            away_data = None

            for comp in competitors:
                if comp.get("homeAway") == "home":
                    home_data = comp
                else:
                    away_data = comp

            if not home_data or not away_data:
                return None

            # Parse status
            status_data = competition.get("status", {})
            status_type = status_data.get("type", {})
            status = GameStatus.from_espn_status(
                status_type.get("id", 1),
                status_type.get("state", "pre"),
            )

            # Parse period and clock
            period_value = status_data.get("period", 1)
            period = Period.from_int(period_value)
            clock = status_data.get("displayClock", "0:00")

            # Parse team states
            home_team = ESPNParser._parse_team_game_state(home_data, data)
            away_team = ESPNParser._parse_team_game_state(away_data, data)

            # Parse recent plays
            recent_plays = ESPNParser._parse_recent_plays(data, home_team.team_id)

            # Parse game metadata
            game_date = None
            date_str = header.get("gameDate")
            if date_str:
                try:
                    game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            venue = None
            game_info = data.get("gameInfo", {})
            venue_data = game_info.get("venue", {})
            if venue_data:
                venue = venue_data.get("fullName")

            return GameState(
                game_id=header.get("id", ""),
                status=status,
                period=period,
                clock=clock,
                home_team=home_team,
                away_team=away_team,
                recent_plays=recent_plays,
                game_date=game_date,
                venue=venue,
            )

        except Exception as e:
            logger.error(f"Failed to parse game summary: {e}")
            return None

    @staticmethod
    def _parse_team_game_state(
        team_data: dict[str, Any], full_data: dict[str, Any]
    ) -> TeamGameState:
        """Parse team competitor data to TeamGameState."""
        team_info = team_data.get("team", {})

        # Get linescores for period scores
        linescores = team_data.get("linescores", [])
        period_scores = [int(ls.get("value", 0)) for ls in linescores]

        # Get statistics from boxscore if available
        boxscore = full_data.get("boxscore", {})
        team_stats = {}

        for team_box in boxscore.get("teams", []):
            if team_box.get("team", {}).get("id") == team_info.get("id"):
                stats_list = team_box.get("statistics", [])
                for stat in stats_list:
                    team_stats[stat.get("name", "")] = stat.get("displayValue", "0")
                break

        # Parse stats with defaults
        def parse_stat(name: str, default: int = 0) -> int:
            val = team_stats.get(name, str(default))
            try:
                return int(val.split("-")[0]) if "-" in val else int(float(val))
            except (ValueError, IndexError):
                return default

        def parse_made_attempted(name: str) -> tuple[int, int]:
            val = team_stats.get(name, "0-0")
            try:
                parts = val.split("-")
                return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            except (ValueError, IndexError):
                return 0, 0

        fg_made, fg_att = parse_made_attempted("fieldGoalsMade-fieldGoalsAttempted")
        three_made, three_att = parse_made_attempted(
            "threePointFieldGoalsMade-threePointFieldGoalsAttempted"
        )
        ft_made, ft_att = parse_made_attempted(
            "freeThrowsMade-freeThrowsAttempted"
        )

        return TeamGameState(
            team_id=team_info.get("id", ""),
            team_name=team_info.get("displayName", ""),
            team_abbreviation=team_info.get("abbreviation", ""),
            score=int(team_data.get("score", 0)),
            timeouts_remaining=int(team_data.get("timeoutsRemaining", 7)),
            period_scores=period_scores,
            field_goals_made=fg_made,
            field_goals_attempted=fg_att,
            three_pointers_made=three_made,
            three_pointers_attempted=three_att,
            free_throws_made=ft_made,
            free_throws_attempted=ft_att,
            rebounds=parse_stat("totalRebounds"),
            assists=parse_stat("assists"),
            turnovers=parse_stat("turnovers"),
            steals=parse_stat("steals"),
            blocks=parse_stat("blocks"),
        )

    @staticmethod
    def _parse_recent_plays(
        data: dict[str, Any], home_team_id: str
    ) -> list[PlayEvent]:
        """Parse recent plays from game data."""
        plays = []

        # Get plays from drives data
        drives = data.get("drives", {})
        previous_plays = drives.get("previous", [])

        # Flatten all plays from drives
        all_plays = []
        for drive in previous_plays:
            drive_plays = drive.get("plays", [])
            all_plays.extend(drive_plays)

        # Sort by sequence and take last 20
        all_plays.sort(key=lambda p: p.get("sequenceNumber", 0), reverse=True)
        recent = all_plays[:20]

        for play_data in recent:
            try:
                play = ESPNParser._parse_play_event(play_data, home_team_id)
                if play:
                    plays.append(play)
            except Exception as e:
                logger.debug(f"Failed to parse play: {e}")

        return plays

    @staticmethod
    def _parse_play_event(
        play_data: dict[str, Any], home_team_id: str
    ) -> Optional[PlayEvent]:
        """Parse a single play event."""
        play_type = play_data.get("type", {})
        type_text = play_type.get("text", "")

        # Parse event type
        event_type = EventType.from_espn_type(
            play_type.get("id", 0),
            play_data.get("text", "") or type_text,
        )

        # Parse period
        period_value = play_data.get("period", {}).get("number", 1)
        period = Period.from_int(period_value)

        # Get score value
        score_value = 0
        if play_data.get("scoringPlay"):
            score_value = int(play_data.get("scoreValue", 0))

        # Get team info
        team_id = play_data.get("team", {}).get("id")

        # Get scores after this play
        home_score = play_data.get("homeScore", 0)
        away_score = play_data.get("awayScore", 0)

        return PlayEvent(
            event_id=str(play_data.get("id", "")),
            period=period,
            clock=play_data.get("clock", {}).get("displayValue", "0:00"),
            event_type=event_type,
            description=play_data.get("text", ""),
            team_id=team_id,
            score_value=score_value,
            home_score=home_score,
            away_score=away_score,
        )

    @staticmethod
    def parse_team_stats(data: dict[str, Any], team_id: str) -> Optional[TeamStats]:
        """Parse team statistics response.

        Args:
            data: ESPN team stats JSON response
            team_id: Team ID

        Returns:
            TeamStats object or None if parsing fails
        """
        try:
            team_info = data.get("team", {})

            # ESPN API returns stats in results.stats.categories
            results = data.get("results", {})
            stats_data = results.get("stats", {}) if results else data.get("statistics", {})

            # Build stats mapping
            stats = {}
            # Try new structure: results.stats.categories
            categories = stats_data.get("categories", [])
            # Fallback to old structure: statistics.splits.categories
            if not categories:
                categories = stats_data.get("splits", {}).get("categories", [])

            for category in categories:
                for stat in category.get("stats", []):
                    stats[stat.get("name", "")] = stat.get("value", 0)

            def get_stat(name: str, default: float = 0.0) -> float:
                return float(stats.get(name, default))

            # Parse wins/losses from recordSummary (e.g., "30-18")
            wins, losses = 0, 0
            record_summary = team_info.get("recordSummary", "")
            if record_summary and "-" in record_summary:
                try:
                    parts = record_summary.split("-")
                    wins = int(parts[0])
                    losses = int(parts[1])
                except (ValueError, IndexError):
                    pass

            return TeamStats(
                team_id=team_id,
                team_name=team_info.get("displayName", ""),
                team_abbreviation=team_info.get("abbreviation", ""),
                wins=wins,
                losses=losses,
                win_percentage=get_stat("winPercent"),
                points_per_game=get_stat("avgPoints"),
                offensive_rating=get_stat("offensiveRating", 110.0),
                defensive_rating=get_stat("defensiveRating", 110.0),
                field_goal_percentage=get_stat("fieldGoalPct"),
                three_point_percentage=get_stat("threePointFieldGoalPct"),
                free_throw_percentage=get_stat("freeThrowPct"),
                assists_per_game=get_stat("avgAssists"),
                turnovers_per_game=get_stat("avgTurnovers"),
                points_allowed_per_game=get_stat("avgPointsAllowed"),
                steals_per_game=get_stat("avgSteals"),
                blocks_per_game=get_stat("avgBlocks"),
                net_rating=get_stat("offensiveRating", 110) - get_stat("defensiveRating", 110),
                pace=get_stat("pace", 100.0),
            )

        except Exception as e:
            logger.error(f"Failed to parse team stats: {e}")
            return None

    @staticmethod
    def parse_standings(data: dict[str, Any]) -> dict[str, dict[str, int]]:
        """Parse standings to get team rankings.

        Args:
            data: ESPN standings JSON response

        Returns:
            Dictionary mapping team_id to rank info
        """
        rankings = {}

        for group in data.get("children", []):
            for standing in group.get("standings", {}).get("entries", []):
                team_id = standing.get("team", {}).get("id")
                if not team_id:
                    continue

                stats = {}
                for stat in standing.get("stats", []):
                    stats[stat.get("name", "")] = stat.get("value", 0)

                rankings[team_id] = {
                    "conference_rank": int(stats.get("playoffSeed", 0)),
                    "wins": int(stats.get("wins", 0)),
                    "losses": int(stats.get("losses", 0)),
                    "win_percentage": float(stats.get("winPercent", 0)),
                    "streak": int(stats.get("streak", 0)),
                }

        return rankings
