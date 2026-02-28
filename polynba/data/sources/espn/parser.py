"""Parser for ESPN API responses to data models."""

import logging
import re
from datetime import datetime
from typing import Any, Optional

from ...models import (
    EventType,
    GameState,
    GameStatus,
    GameSummary,
    HeadToHead,
    Period,
    PlayEvent,
    PlayerInjury,
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
    def _parse_team_info_record(
        team_info_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract record stats from /teams/{id} response.

        The /teams/{id} endpoint returns record.items[] with stats arrays
        containing avgPointsFor, avgPointsAgainst, differential, streak,
        and home/away splits.

        Returns dict with keys: ppg, pa, differential, streak,
        home_wins, home_losses, away_wins, away_losses, wins, losses, win_pct.
        """
        result: dict[str, Any] = {}
        team = team_info_data.get("team", {})
        record = team.get("record", {})
        items = record.get("items", [])

        for item in items:
            item_type = item.get("type", "")
            stats_list = item.get("stats", [])
            stats_map = {s["name"]: s["value"] for s in stats_list if "name" in s}

            if item_type == "total":
                result["ppg"] = float(stats_map.get("avgPointsFor", 0.0))
                result["pa"] = float(stats_map.get("avgPointsAgainst", 0.0))
                result["differential"] = float(stats_map.get("differential", 0.0))
                result["streak"] = int(stats_map.get("streak", 0))
                result["wins"] = int(stats_map.get("wins", 0))
                result["losses"] = int(stats_map.get("losses", 0))
                result["win_pct"] = float(stats_map.get("winPercent", 0.0))
            elif item_type == "home":
                result["home_wins"] = int(stats_map.get("wins", 0))
                result["home_losses"] = int(stats_map.get("losses", 0))
            elif item_type == "road":
                result["away_wins"] = int(stats_map.get("wins", 0))
                result["away_losses"] = int(stats_map.get("losses", 0))

        return result

    @staticmethod
    def parse_team_stats(
        data: dict[str, Any],
        team_id: str,
        team_info_data: dict[str, Any] | None = None,
    ) -> Optional[TeamStats]:
        """Parse team statistics response.

        Args:
            data: ESPN team stats JSON response (/teams/{id}/statistics)
            team_id: Team ID
            team_info_data: Optional ESPN team info response (/teams/{id})
                containing record, point differential, and home/away splits.

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

            # Use 0.0 default to detect when ESPN doesn't provide ratings
            off_rating = get_stat("offensiveRating", 0.0)
            def_rating = get_stat("defensiveRating", 0.0)
            ppg = get_stat("avgPoints", 0.0)
            pa = get_stat("avgPointsAllowed", 0.0)

            # Merge data from /teams/{id} endpoint if available
            record_data: dict[str, Any] = {}
            if team_info_data:
                record_data = ESPNParser._parse_team_info_record(team_info_data)
                # Fill in points allowed from team info if not in statistics
                if pa <= 0 and record_data.get("pa", 0) > 0:
                    pa = record_data["pa"]
                # Fill in PPG from team info if not in statistics
                if ppg <= 0 and record_data.get("ppg", 0) > 0:
                    ppg = record_data["ppg"]
                # Use record from team info if not parsed from recordSummary
                if wins == 0 and losses == 0:
                    wins = record_data.get("wins", 0)
                    losses = record_data.get("losses", 0)

            # Derive net_rating: prefer per-100-possession ratings, fall back to point differential
            if off_rating > 0 and def_rating > 0:
                net_rating = off_rating - def_rating
            elif record_data.get("differential") is not None and record_data.get("differential") != 0:
                # Use pre-computed differential from team info endpoint
                net_rating = record_data["differential"]
            elif ppg > 0 and pa > 0:
                net_rating = ppg - pa
            else:
                net_rating = 0.0  # Truly no data available

            # Home/away splits from team info
            home_wins = record_data.get("home_wins", 0)
            home_losses = record_data.get("home_losses", 0)
            away_wins = record_data.get("away_wins", 0)
            away_losses = record_data.get("away_losses", 0)

            # Streak from team info
            current_streak = record_data.get("streak", 0)

            # Win percentage: prefer team info (more reliable), fall back to stats
            win_pct = record_data.get("win_pct", 0.0)
            if win_pct <= 0:
                win_pct = get_stat("winPercent")
            if win_pct <= 0 and (wins + losses) > 0:
                win_pct = wins / (wins + losses)

            return TeamStats(
                team_id=team_id,
                team_name=team_info.get("displayName", ""),
                team_abbreviation=team_info.get("abbreviation", ""),
                wins=wins,
                losses=losses,
                win_percentage=win_pct,
                points_per_game=ppg,
                offensive_rating=off_rating if off_rating > 0 else ppg if ppg > 0 else 110.0,
                defensive_rating=def_rating if def_rating > 0 else pa if pa > 0 else 110.0,
                field_goal_percentage=get_stat("fieldGoalPct"),
                three_point_percentage=get_stat("threePointFieldGoalPct"),
                free_throw_percentage=get_stat("freeThrowPct"),
                assists_per_game=get_stat("avgAssists"),
                turnovers_per_game=get_stat("avgTurnovers"),
                points_allowed_per_game=pa,
                steals_per_game=get_stat("avgSteals"),
                blocks_per_game=get_stat("avgBlocks"),
                net_rating=net_rating,
                pace=get_stat("pace", 100.0),
                home_wins=home_wins,
                home_losses=home_losses,
                away_wins=away_wins,
                away_losses=away_losses,
                current_streak=current_streak,
            )

        except Exception as e:
            logger.error(f"Failed to parse team stats: {e}")
            return None

    # ESPN status normalization map
    _STATUS_MAP: dict[str, str] = {
        "out": "out",
        "injury_status_out": "out",
        "o": "out",
        "doubtful": "doubtful",
        "d": "doubtful",
        "questionable": "questionable",
        "q": "questionable",
        "day-to-day": "day-to-day",
        "day to day": "day-to-day",
        "dd": "day-to-day",
        "injury_status_daytoday": "day-to-day",
        "probable": "probable",
        "p": "probable",
        "suspension": "out",
        "injury_status_suspension": "out",
        "susp": "out",
    }

    # Fantasy status abbreviation map (separate from main statuses)
    _FANTASY_STATUS_MAP: dict[str, str] = {
        "OUT": "out",
        "OFS": "out",
        "GTD": "game-time decision",
    }

    @staticmethod
    def parse_injuries(data: dict[str, Any]) -> dict[str, list[PlayerInjury]]:
        """Parse injuries response to dict of team_id -> list of PlayerInjury.

        Args:
            data: ESPN injuries JSON response

        Returns:
            Dictionary mapping team_id to list of PlayerInjury objects
        """
        result: dict[str, list[PlayerInjury]] = {}

        for team_entry in data.get("injuries", []):
            # ESPN returns team data either nested under "team" or at the top level
            team_info = team_entry.get("team", {})
            team_id = team_info.get("id", "") or str(team_entry.get("id", ""))
            if not team_id:
                continue

            injuries_list = team_entry.get("injuries", [])
            for injury_data in injuries_list:
                try:
                    injury = ESPNParser._parse_single_injury(injury_data, team_id)
                    if injury:
                        result.setdefault(team_id, []).append(injury)
                except Exception as e:
                    logger.debug(f"Failed to parse injury entry: {e}")

        return result

    @staticmethod
    def _parse_single_injury(
        injury_data: dict[str, Any], team_id: str
    ) -> Optional[PlayerInjury]:
        """Parse a single injury entry.

        Args:
            injury_data: Single injury entry from ESPN API
            team_id: Team ID this injury belongs to

        Returns:
            PlayerInjury object or None if status can't be determined
        """
        athlete = injury_data.get("athlete", {})
        player_name = athlete.get("displayName", "")
        player_id = athlete.get("id", "")

        # Fallback: extract ID from player link URL (/id/XXXXX/name)
        if not player_id:
            for link in athlete.get("links", []):
                href = link.get("href", "")
                m = re.search(r"/id/(\d+)/", href)
                if m:
                    player_id = m.group(1)
                    break

        if not player_name:
            return None

        # Multi-layer status extraction with fallbacks
        raw_status = None

        # Try direct status field
        raw_status = injury_data.get("status")

        # Fallback: type.name
        if not raw_status:
            raw_status = injury_data.get("type", {}).get("name")

        # Fallback: type.abbreviation
        if not raw_status:
            raw_status = injury_data.get("type", {}).get("abbreviation")

        # Normalize status
        status = None
        if raw_status:
            status = ESPNParser._STATUS_MAP.get(raw_status.lower())

        # Fallback: fantasy status abbreviation
        if not status:
            fantasy_abbr = (
                injury_data.get("fantasyStatus", {}).get("abbreviation", "")
            )
            if fantasy_abbr:
                status = ESPNParser._FANTASY_STATUS_MAP.get(fantasy_abbr)

        if not status:
            return None

        # Extract injury description
        description = (
            injury_data.get("shortComment", "")
            or injury_data.get("details", {}).get("detail", "")
            or ""
        )

        return PlayerInjury(
            player_id=player_id,
            player_name=player_name,
            team_id=team_id,
            status=status,
            injury_description=description,
        )

    # Mapping from ESPN overview stat names to our field names
    _OVERVIEW_STAT_MAP: dict[str, str] = {
        "gamesPlayed": "games_played",
        "avgMinutes": "minutes_per_game",
        "fieldGoalPct": "field_goal_pct",
        "threePointPct": "three_point_pct",
        "threePointFieldGoalPct": "three_point_pct",  # alternate key
        "freeThrowPct": "free_throw_pct",
        "avgRebounds": "rebounds_per_game",
        "avgAssists": "assists_per_game",
        "avgBlocks": "blocks_per_game",
        "avgSteals": "steals_per_game",
        "avgFouls": "fouls_per_game",
        "avgTurnovers": "turnovers_per_game",
        "avgPoints": "points_per_game",
    }

    @staticmethod
    def parse_athlete_overview(data: dict[str, Any]) -> Optional[dict[str, float]]:
        """Parse ESPN athlete overview to extract season stats.

        The names array lives at statistics.names (shared across all splits),
        while each split has its own stats array. We find the Regular Season
        split and zip its stats with the top-level names.

        Args:
            data: ESPN athlete overview JSON response

        Returns:
            Dict of stat_name -> value, or None if parsing fails
        """
        try:
            statistics = data.get("statistics", {})
            splits = statistics.get("splits", [])

            # Names are at the statistics level, shared across splits
            names = statistics.get("names", [])

            # Find the Regular Season split
            season_split = None
            for split in splits:
                if split.get("displayName") == "Regular Season":
                    season_split = split
                    break

            # Fall back to first split if "Regular Season" not found
            if season_split is None and splits:
                season_split = splits[0]

            if season_split is None:
                return None

            stats = season_split.get("stats", [])

            # Fall back to split-level names if top-level names are empty
            if not names:
                names = season_split.get("names", [])

            if not names or not stats or len(names) != len(stats):
                return None

            raw_map = dict(zip(names, stats))
            result: dict[str, float] = {}

            for espn_name, our_name in ESPNParser._OVERVIEW_STAT_MAP.items():
                val = raw_map.get(espn_name)
                if val is not None:
                    try:
                        result[our_name] = float(val)
                    except (ValueError, TypeError):
                        pass

            return result if result else None

        except Exception as e:
            logger.warning(f"Failed to parse athlete overview: {e}")
            return None

    @staticmethod
    def parse_team_roster(data: dict[str, Any]) -> list[dict[str, str]]:
        """Parse ESPN team roster response to extract player info.

        Args:
            data: ESPN team roster JSON response (/teams/{id}/roster)

        Returns:
            List of dicts with athlete_id, player_name, position
        """
        players: list[dict[str, str]] = []

        for entry in data.get("athletes", []):
            # Handle both grouped format (items list) and flat format (direct athlete)
            if "items" in entry:
                athletes = entry["items"]
            else:
                athletes = [entry]

            for athlete in athletes:
                athlete_id = str(athlete.get("id", ""))
                name = athlete.get("displayName", "") or athlete.get("fullName", "")
                position = athlete.get("position", {}).get("abbreviation", "")
                if athlete_id and name:
                    players.append({
                        "athlete_id": athlete_id,
                        "player_name": name,
                        "position": position,
                    })

        return players

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

    @staticmethod
    def parse_head_to_head(
        schedule_data: dict[str, Any],
        team_id: str,
        opponent_id: str,
    ) -> Optional[HeadToHead]:
        """Parse team schedule to extract head-to-head record vs an opponent.

        Args:
            schedule_data: ESPN team schedule JSON response
            team_id: The team whose schedule was fetched
            opponent_id: The opponent team ID to filter for

        Returns:
            HeadToHead object or None if no completed games found
        """
        events = schedule_data.get("events", [])
        if not events:
            return None

        team1_wins = 0
        team2_wins = 0
        team1_total_points = 0
        team2_total_points = 0
        games_played = 0
        last_meeting_date: Optional[datetime] = None
        last_meeting_winner: Optional[str] = None

        for event in events:
            # Only look at completed games
            status = event.get("competitions", [{}])[0].get("status", {})
            status_type = status.get("type", {})
            if status_type.get("state", "") != "post":
                continue

            # Check if this game involves the opponent
            competitors = event.get("competitions", [{}])[0].get("competitors", [])
            if len(competitors) < 2:
                continue

            opponent_found = False
            team_data = None
            opp_data = None

            for comp in competitors:
                comp_id = comp.get("team", {}).get("id", "")
                if comp_id == opponent_id:
                    opponent_found = True
                    opp_data = comp
                elif comp_id == team_id:
                    team_data = comp

            if not opponent_found or not team_data or not opp_data:
                continue

            # This is a completed H2H game
            games_played += 1
            team_score = int(team_data.get("score", {}).get("value", 0) if isinstance(team_data.get("score"), dict) else team_data.get("score", 0))
            opp_score = int(opp_data.get("score", {}).get("value", 0) if isinstance(opp_data.get("score"), dict) else opp_data.get("score", 0))

            team1_total_points += team_score
            team2_total_points += opp_score

            if team_data.get("winner", False):
                team1_wins += 1
            else:
                team2_wins += 1

            # Track last meeting
            date_str = event.get("date")
            if date_str:
                try:
                    game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if last_meeting_date is None or game_date > last_meeting_date:
                        last_meeting_date = game_date
                        last_meeting_winner = team_id if team_data.get("winner", False) else opponent_id
                except ValueError:
                    pass

        if games_played == 0:
            return None

        return HeadToHead(
            team1_id=team_id,
            team2_id=opponent_id,
            team1_wins=team1_wins,
            team2_wins=team2_wins,
            team1_avg_points=team1_total_points / games_played,
            team2_avg_points=team2_total_points / games_played,
            team1_avg_margin=(team1_total_points - team2_total_points) / games_played,
            games_played=games_played,
            last_meeting_date=last_meeting_date,
            last_meeting_winner=last_meeting_winner,
        )
