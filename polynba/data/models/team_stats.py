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

    # Team advanced stats (from NBA.com leaguedashteamstats)
    assist_pct: float = 0.0               # AST_PCT (fraction, 0.62 = 62%)
    assist_to_turnover: float = 0.0       # AST_TO (ratio, e.g. 1.85)
    assist_ratio: float = 0.0             # AST_RATIO (per 100 poss)
    offensive_rebound_pct: float = 0.0    # OREB_PCT (fraction)
    defensive_rebound_pct: float = 0.0    # DREB_PCT (fraction)
    turnover_pct: float = 0.0             # TM_TOV_PCT (fraction, 0.125 = 12.5%)
    team_pie: float = 0.0                 # PIE (fraction)
    estimated_offensive_rating: float = 0.0
    estimated_defensive_rating: float = 0.0
    estimated_net_rating: float = 0.0
    possessions: float = 0.0              # POSS per game
    minutes: float = 0.0                  # MIN per game

    # Additional rankings (from NBA.com)
    effective_fg_pct_rank: int = 0
    true_shooting_pct_rank: int = 0
    assist_pct_rank: int = 0
    assist_to_turnover_rank: int = 0
    rebound_pct_rank: int = 0
    turnover_pct_rank: int = 0
    pie_rank: int = 0

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
    def pythagorean_win_pct(self) -> float:
        """Pythagorean expected win% based on points scored/allowed.

        Uses Morey's exponent (13.91) for NBA.
        """
        if self.points_per_game <= 0 or self.points_allowed_per_game <= 0:
            return self.win_percentage  # fall back to actual
        exp = 13.91
        ppg_exp = self.points_per_game ** exp
        pa_exp = self.points_allowed_per_game ** exp
        return ppg_exp / (ppg_exp + pa_exp)

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
class PlayerSeasonStats:
    """Per-player season average stats from NBA.com player index."""

    player_name: str
    team_abbreviation: str
    position: str  # "G", "F", "C", "G-F", "F-C", etc.
    points_per_game: float
    rebounds_per_game: float
    assists_per_game: float
    # Extended stats (from ESPN overview, 0 = not yet fetched)
    games_played: int = 0
    minutes_per_game: float = 0.0
    field_goal_pct: float = 0.0
    three_point_pct: float = 0.0
    free_throw_pct: float = 0.0
    blocks_per_game: float = 0.0
    steals_per_game: float = 0.0
    fouls_per_game: float = 0.0
    turnovers_per_game: float = 0.0
    # Advanced stats (from NBA.com leaguedashplayerstats, 0 = not yet fetched)
    age: float = 0.0
    player_wins: int = 0
    player_losses: int = 0
    player_win_pct: float = 0.0            # fraction (0.6 = 60%)
    offensive_rating: float = 0.0          # pts per 100 possessions
    defensive_rating: float = 0.0          # pts allowed per 100 possessions
    net_rating: float = 0.0                # off - def
    assist_pct: float = 0.0                # fraction (0.184 = 18.4%)
    assist_to_turnover: float = 0.0        # ratio (e.g. 3.61)
    assist_ratio: float = 0.0              # per 100 possessions (e.g. 19.3)
    offensive_rebound_pct: float = 0.0     # fraction
    defensive_rebound_pct: float = 0.0     # fraction
    rebound_pct: float = 0.0              # fraction
    turnover_pct: float = 0.0             # WHOLE percentage (e.g., 11.2 = 11.2%)
    effective_fg_pct: float = 0.0         # fraction
    true_shooting_pct: float = 0.0        # fraction (0.575 = 57.5%)
    usage_pct: float = 0.0                # fraction (0.20 = 20%)
    pace: float = 0.0                     # absolute (e.g. 101.4)
    player_impact_estimate: float = 0.0   # PIE (fraction)
    possessions: int = 0                  # total possessions

    @property
    def per36_points(self) -> float:
        """Points per 36 minutes."""
        if self.minutes_per_game > 0:
            return self.points_per_game * 36.0 / self.minutes_per_game
        return self.points_per_game

    @property
    def per36_rebounds(self) -> float:
        """Rebounds per 36 minutes."""
        if self.minutes_per_game > 0:
            return self.rebounds_per_game * 36.0 / self.minutes_per_game
        return self.rebounds_per_game

    @property
    def per36_assists(self) -> float:
        """Assists per 36 minutes."""
        if self.minutes_per_game > 0:
            return self.assists_per_game * 36.0 / self.minutes_per_game
        return self.assists_per_game

    @property
    def per36_steals(self) -> float:
        """Steals per 36 minutes."""
        if self.minutes_per_game > 0:
            return self.steals_per_game * 36.0 / self.minutes_per_game
        return self.steals_per_game

    @property
    def per36_blocks(self) -> float:
        """Blocks per 36 minutes."""
        if self.minutes_per_game > 0:
            return self.blocks_per_game * 36.0 / self.minutes_per_game
        return self.blocks_per_game

    @property
    def is_bench(self) -> bool:
        """Whether player is a bench player (plays but under starter minutes)."""
        return 0 < self.minutes_per_game < 24

    @property
    def estimated_impact_rating(self) -> float:
        """Estimated Impact Rating — three-component composite score.

        EIR = box_component + impact_component + defense_component

        Box (~55%): Game Score formula with rate-stat upgrades (TOV%, REB%,
        AST%) when available, TS% efficiency, USG% factor. Rate-stat
        multipliers calibrated so league-average rate ≈ league-average raw
        stat (no inflation). Falls back to raw per-game independently.

        Impact (~25%): NET_RATING-dominated (Tier 1 stat, best raw signal
        for on-court impact). PIE used only as minor validation (Tier 4,
        simplistic). NR * 0.40 (80%) + PIE-relative * 30 (20%).
        Range: roughly -3 to +4 EIR points.

        Defense (~10%): (112.0 - DEFRTG) * 0.12. Modest credit for good
        defenders. Low weight because individual DEFRTG is noisy and
        lineup-dependent (Tier 4 reliability). Range: ~-1.4 to +1.4.

        Anti-double-counting: box scales by 0.94 when additive components
        are active. When advanced stats are zero, output is identical to
        the original formula.

        Scaled so ~15.0 = league average starter.
        """
        if self.minutes_per_game <= 0:
            return 0.0

        mpg = self.minutes_per_game

        # --- Rate-stat upgrades (fall back to raw per-game independently) ---
        # Multipliers calibrated: league-avg rate * multiplier ≈ league-avg raw stat

        # TOV: prefer TOV% (whole pct, e.g. 11.2) scaled to per-game-like impact
        if self.turnover_pct > 0:
            tov_term = self.turnover_pct / 100.0 * self.points_per_game
        else:
            tov_term = self.turnovers_per_game

        # REB: prefer REB% (fraction, e.g. 0.10) → ~4.5 for avg player
        if self.rebound_pct > 0:
            reb_term = self.rebound_pct * 45.0
        else:
            reb_term = self.rebounds_per_game

        # AST: prefer AST% (fraction, e.g. 0.13) → ~3.2 for avg player
        if self.assist_pct > 0:
            ast_term = self.assist_pct * 25.0
        else:
            ast_term = self.assists_per_game

        # Per-minute raw production (Game Score weights, rate-stat upgraded)
        raw = (
            self.points_per_game
            + 0.7 * ast_term
            + 0.3 * reb_term
            + 1.5 * self.steals_per_game
            + 1.2 * self.blocks_per_game
            - tov_term
            - 0.4 * self.fouls_per_game
        ) / mpg

        # Efficiency: prefer TS% over FG% (Tier 1 — gold standard)
        if self.true_shooting_pct > 0:
            eff = 1.0 + (self.true_shooting_pct - 0.575) / 0.575
        else:
            fg_pct = self.field_goal_pct if self.field_goal_pct > 0 else 46.5
            eff = 1.0 + (fg_pct - 46.5) / 100.0

        # Usage factor: 1.0 at league avg, ~1.19 at 25% USG (Tier 3 — context)
        if self.usage_pct > 0:
            usg_factor = 0.85 + 0.15 * (self.usage_pct / 0.20)
        else:
            usg_factor = 1.0

        # Scale to 36 minutes, normalize to ~15.0 = league average
        box_component = raw * 36.0 * eff * usg_factor * (15.0 / 13.0)

        # --- Impact component: NR-dominated (Tier 1), PIE as minor validation ---
        impact_component = 0.0
        has_nr = self.net_rating != 0.0
        has_pie = self.player_impact_estimate > 0.0

        if has_nr and has_pie:
            nr_part = self.net_rating * 0.40
            pie_part = (self.player_impact_estimate - 0.10) * 30.0
            impact_component = 0.80 * nr_part + 0.20 * pie_part
        elif has_nr:
            impact_component = self.net_rating * 0.40
        elif has_pie:
            impact_component = (self.player_impact_estimate - 0.10) * 30.0

        # --- Defense component: modest weight, DEFRTG is noisy (Tier 4) ---
        defense_component = 0.0
        if self.defensive_rating > 0:
            defense_component = (112.0 - self.defensive_rating) * 0.12

        # --- Anti-double-counting: scale box down when additive components active ---
        has_additive = impact_component != 0.0 or defense_component != 0.0
        if has_additive:
            box_component *= 0.94

        eir = box_component + impact_component + defense_component

        # Confidence discount for <15 MPG (garbage time / small sample risk)
        if mpg < 15:
            eir *= 0.5 + 0.5 * mpg / 15.0

        return max(eir, 0.0)


@dataclass
class PlayerInjury:
    """Player injury status."""

    player_id: str
    player_name: str
    team_id: str
    status: str  # "Out", "Doubtful", "Questionable", "Probable", "Available"
    injury_description: str
    return_date: Optional[datetime] = None
    player_stats: Optional[PlayerSeasonStats] = None

    @property
    def is_out(self) -> bool:
        """Check if player is out."""
        return self.status.lower() in ("out", "doubtful")

    @property
    def is_questionable(self) -> bool:
        """Check if player status is uncertain."""
        return self.status.lower() in ("questionable", "game-time decision", "day-to-day")


@dataclass
class TeamContext:
    """Full context for a team including stats, injuries, and recent form."""

    stats: TeamStats
    injuries: list[PlayerInjury] = field(default_factory=list)
    head_to_head: Optional[HeadToHead] = None
    player_stats_map: dict[str, PlayerSeasonStats] = field(default_factory=dict)

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
