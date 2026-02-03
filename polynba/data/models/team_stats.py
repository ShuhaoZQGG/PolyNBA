"""Team statistics models for NBA data."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TeamStats:
    """Season statistics for an NBA team."""

    team_id: str
    team_name: str
    team_abbreviation: str

    # Record
    wins: int = 0
    losses: int = 0
    win_percentage: float = 0.0
    conference_rank: int = 0
    division_rank: int = 0

    # Offensive stats
    points_per_game: float = 0.0
    offensive_rating: float = 0.0  # Points per 100 possessions
    field_goal_percentage: float = 0.0
    three_point_percentage: float = 0.0
    free_throw_percentage: float = 0.0
    assists_per_game: float = 0.0
    turnovers_per_game: float = 0.0

    # Defensive stats
    points_allowed_per_game: float = 0.0
    defensive_rating: float = 0.0  # Points allowed per 100 possessions
    steals_per_game: float = 0.0
    blocks_per_game: float = 0.0
    opponent_field_goal_percentage: float = 0.0

    # Advanced stats
    net_rating: float = 0.0  # Offensive rating - Defensive rating
    pace: float = 0.0  # Possessions per 48 minutes
    effective_field_goal_percentage: float = 0.0
    true_shooting_percentage: float = 0.0
    rebound_percentage: float = 0.0

    # Clutch stats (last 5 minutes, within 5 points)
    clutch_net_rating: float = 0.0
    clutch_wins: int = 0
    clutch_losses: int = 0

    # Rankings (1-30, lower is better)
    offensive_rating_rank: int = 0
    defensive_rating_rank: int = 0
    net_rating_rank: int = 0
    pace_rank: int = 0

    # Streaks
    current_streak: int = 0  # Positive = win streak, negative = loss streak
    last_10_wins: int = 0
    last_10_losses: int = 0

    # Home/Away splits
    home_wins: int = 0
    home_losses: int = 0
    away_wins: int = 0
    away_losses: int = 0

    # Metadata
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def games_played(self) -> int:
        """Total games played."""
        return self.wins + self.losses

    @property
    def home_win_percentage(self) -> float:
        """Home win percentage."""
        total = self.home_wins + self.home_losses
        return self.home_wins / total if total > 0 else 0.0

    @property
    def away_win_percentage(self) -> float:
        """Away win percentage."""
        total = self.away_wins + self.away_losses
        return self.away_wins / total if total > 0 else 0.0

    @property
    def is_elite_offense(self) -> bool:
        """Check if team has elite offense (top 5)."""
        return self.offensive_rating_rank <= 5

    @property
    def is_elite_defense(self) -> bool:
        """Check if team has elite defense (top 5)."""
        return self.defensive_rating_rank <= 5

    @property
    def is_bottom_offense(self) -> bool:
        """Check if team has bottom-tier offense (bottom 5)."""
        return self.offensive_rating_rank >= 26

    @property
    def is_bottom_defense(self) -> bool:
        """Check if team has bottom-tier defense (bottom 5)."""
        return self.defensive_rating_rank >= 26

    def strength_tier(self) -> str:
        """Get overall team strength tier."""
        if self.net_rating_rank <= 5:
            return "elite"
        elif self.net_rating_rank <= 10:
            return "contender"
        elif self.net_rating_rank <= 20:
            return "average"
        elif self.net_rating_rank <= 25:
            return "below_average"
        return "rebuilding"


@dataclass
class HeadToHead:
    """Head-to-head statistics between two teams for current season."""

    team1_id: str
    team2_id: str
    team1_wins: int = 0
    team2_wins: int = 0
    team1_avg_points: float = 0.0
    team2_avg_points: float = 0.0
    team1_avg_margin: float = 0.0
    games_played: int = 0
    last_meeting_date: Optional[datetime] = None
    last_meeting_winner: Optional[str] = None

    @property
    def team1_win_percentage(self) -> float:
        """Team 1 win percentage in head-to-head."""
        if self.games_played == 0:
            return 0.5
        return self.team1_wins / self.games_played

    @property
    def is_even(self) -> bool:
        """Check if head-to-head record is even."""
        return self.team1_wins == self.team2_wins


@dataclass
class PlayerInjury:
    """Player injury status."""

    player_id: str
    player_name: str
    team_id: str
    status: str  # "Out", "Doubtful", "Questionable", "Probable", "Available"
    injury_description: str
    return_date: Optional[datetime] = None

    @property
    def is_out(self) -> bool:
        """Check if player is out."""
        return self.status.lower() in ("out", "doubtful")

    @property
    def is_questionable(self) -> bool:
        """Check if player status is uncertain."""
        return self.status.lower() in ("questionable", "game-time decision")


@dataclass
class TeamContext:
    """Full context for a team including stats, injuries, and recent form."""

    stats: TeamStats
    injuries: list[PlayerInjury] = field(default_factory=list)
    head_to_head: Optional[HeadToHead] = None

    @property
    def key_players_out(self) -> list[PlayerInjury]:
        """Get list of key players who are out."""
        return [inj for inj in self.injuries if inj.is_out]

    @property
    def has_significant_injuries(self) -> bool:
        """Check if team has significant injury concerns."""
        return len(self.key_players_out) >= 2

    @property
    def is_hot(self) -> bool:
        """Check if team is on a hot streak."""
        return self.stats.current_streak >= 3

    @property
    def is_cold(self) -> bool:
        """Check if team is on a cold streak."""
        return self.stats.current_streak <= -3
