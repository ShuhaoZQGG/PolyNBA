"""Game state models for NBA live data."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .enums import EventType, GameStatus, Period, TeamSide


@dataclass
class PlayEvent:
    """A single play event in an NBA game."""

    event_id: str
    period: Period
    clock: str  # e.g., "5:32"
    event_type: EventType
    description: str
    team_id: Optional[str] = None
    player_id: Optional[str] = None
    player_name: Optional[str] = None
    score_value: int = 0  # Points scored (0, 1, 2, or 3)
    home_score: int = 0
    away_score: int = 0
    timestamp: Optional[datetime] = None

    @property
    def clock_seconds(self) -> int:
        """Convert clock string to seconds remaining in period."""
        if not self.clock or self.clock == "0:00":
            return 0
        try:
            parts = self.clock.split(":")
            if len(parts) == 2:
                minutes, seconds = int(parts[0]), int(parts[1])
                return minutes * 60 + seconds
        except (ValueError, IndexError):
            return 0
        return 0

    @property
    def is_scoring_play(self) -> bool:
        """Check if this event resulted in points."""
        return self.score_value > 0


@dataclass
class TeamGameState:
    """State of a team during a game."""

    team_id: str
    team_name: str
    team_abbreviation: str
    score: int = 0
    timeouts_remaining: int = 7
    team_fouls: int = 0
    period_scores: list[int] = field(default_factory=list)
    in_bonus: bool = False

    # Optional detailed stats
    field_goals_made: int = 0
    field_goals_attempted: int = 0
    three_pointers_made: int = 0
    three_pointers_attempted: int = 0
    free_throws_made: int = 0
    free_throws_attempted: int = 0
    rebounds: int = 0
    assists: int = 0
    turnovers: int = 0
    steals: int = 0
    blocks: int = 0

    @property
    def field_goal_percentage(self) -> float:
        """Calculate field goal percentage."""
        if self.field_goals_attempted == 0:
            return 0.0
        return self.field_goals_made / self.field_goals_attempted

    @property
    def three_point_percentage(self) -> float:
        """Calculate three point percentage."""
        if self.three_pointers_attempted == 0:
            return 0.0
        return self.three_pointers_made / self.three_pointers_attempted

    @property
    def free_throw_percentage(self) -> float:
        """Calculate free throw percentage."""
        if self.free_throws_attempted == 0:
            return 0.0
        return self.free_throws_made / self.free_throws_attempted


@dataclass
class GameState:
    """Complete state of an NBA game."""

    game_id: str
    status: GameStatus
    period: Period
    clock: str  # e.g., "5:32"
    home_team: TeamGameState
    away_team: TeamGameState
    recent_plays: list[PlayEvent] = field(default_factory=list)

    # Game metadata
    game_date: Optional[datetime] = None
    venue: Optional[str] = None
    attendance: Optional[int] = None

    # Broadcast info
    broadcast: Optional[str] = None

    # Timing
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def is_live(self) -> bool:
        """Check if the game is currently in progress."""
        if self.status in (
            GameStatus.IN_PROGRESS,
            GameStatus.HALFTIME,
            GameStatus.END_OF_PERIOD,
        ):
            return True

        # Heuristic: some feeds mark halftime as scheduled
        if self.status == GameStatus.SCHEDULED:
            if self.period.value > 0:
                if self.clock and self.clock != "0:00":
                    return True
                if (self.home_team.score + self.away_team.score) > 0:
                    return True

        return False

    @property
    def is_final(self) -> bool:
        """Check if the game has ended."""
        return self.status == GameStatus.FINAL

    @property
    def clock_seconds(self) -> int:
        """Convert clock string to seconds remaining in period."""
        if not self.clock or self.clock == "0:00":
            return 0
        try:
            parts = self.clock.split(":")
            if len(parts) == 2:
                minutes, seconds = int(parts[0]), int(parts[1])
                return minutes * 60 + seconds
        except (ValueError, IndexError):
            return 0
        return 0

    @property
    def total_seconds_remaining(self) -> int:
        """Calculate total seconds remaining in the game.

        Assumes 12-minute quarters and 5-minute overtimes.
        """
        period_value = self.period.value
        clock_seconds = self.clock_seconds

        if period_value <= 4:
            # Regular time: remaining quarters + current quarter time
            remaining_quarters = 4 - period_value
            return remaining_quarters * 12 * 60 + clock_seconds
        else:
            # Overtime: just current period time (can't predict more OTs)
            return clock_seconds

    @property
    def score_differential(self) -> int:
        """Get score differential (positive = home leading)."""
        return self.home_team.score - self.away_team.score

    @property
    def total_score(self) -> int:
        """Get total combined score."""
        return self.home_team.score + self.away_team.score

    @property
    def leading_team(self) -> Optional[TeamSide]:
        """Get which team is leading, or None if tied."""
        diff = self.score_differential
        if diff > 0:
            return TeamSide.HOME
        elif diff < 0:
            return TeamSide.AWAY
        return None

    def get_team(self, side: TeamSide) -> TeamGameState:
        """Get team by side."""
        return self.home_team if side == TeamSide.HOME else self.away_team

    def get_recent_scoring_plays(self, count: int = 10) -> list[PlayEvent]:
        """Get recent scoring plays."""
        scoring_plays = [p for p in self.recent_plays if p.is_scoring_play]
        return scoring_plays[:count]

    def get_momentum_indicator(self, plays: int = 5) -> tuple[int, TeamSide | None]:
        """Calculate momentum based on recent scoring.

        Returns (point_differential, leading_team) for last N scoring plays.
        Positive differential means home team has momentum.
        """
        recent_scoring = self.get_recent_scoring_plays(plays)
        if not recent_scoring:
            return 0, None

        home_points = 0
        away_points = 0

        for play in recent_scoring:
            if play.team_id == self.home_team.team_id:
                home_points += play.score_value
            elif play.team_id == self.away_team.team_id:
                away_points += play.score_value

        diff = home_points - away_points
        if diff > 0:
            return diff, TeamSide.HOME
        elif diff < 0:
            return abs(diff), TeamSide.AWAY
        return 0, None


@dataclass
class GameSummary:
    """Lightweight game summary for scoreboard views."""

    game_id: str
    status: GameStatus
    period: Period
    clock: str
    home_team_id: str
    home_team_name: str
    home_team_abbreviation: str
    home_score: int
    away_team_id: str
    away_team_name: str
    away_team_abbreviation: str
    away_score: int
    game_date: Optional[datetime] = None
    broadcast: Optional[str] = None

    @property
    def is_live(self) -> bool:
        """Check if the game is currently in progress."""
        if self.status in (
            GameStatus.IN_PROGRESS,
            GameStatus.HALFTIME,
            GameStatus.END_OF_PERIOD,
        ):
            return True

        # Heuristic: some feeds mark halftime as scheduled
        if self.status == GameStatus.SCHEDULED:
            if self.period.value > 0:
                if self.clock and self.clock != "0:00":
                    return True
                if (self.home_score + self.away_score) > 0:
                    return True

        return False
