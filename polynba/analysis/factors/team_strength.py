"""Team strength factor - rankings, efficiency, and matchups."""

import logging
from dataclasses import dataclass
from typing import Optional

from ...data.models import TeamContext, TeamStats

logger = logging.getLogger(__name__)


@dataclass
class TeamStrengthInput:
    """Input data for team strength analysis."""

    home_stats: TeamStats
    away_stats: TeamStats
    home_context: Optional[TeamContext] = None
    away_context: Optional[TeamContext] = None


@dataclass
class EfficiencyComparison:
    """Comparison of team efficiencies."""

    home_net_rating: float
    away_net_rating: float
    net_rating_diff: float  # Home - Away
    home_pace: float
    away_pace: float
    expected_pace: float


@dataclass
class StrengthTierComparison:
    """Comparison of team strength tiers.

    Tiers (by net_rating): elite > 5, contender > 2, average > -2,
    below_average > -5, else rebuilding.
    mismatch_level: number of tier steps between teams (0 = same tier,
    1 = adjacent, 2 = two apart, etc.), from abs(home_tier_idx - away_tier_idx).
    """

    home_tier: str
    away_tier: str
    tier_advantage: str  # "home", "away", or "even"
    mismatch_level: int  # 0-4: number of tier steps between teams


@dataclass
class TeamStrengthOutput:
    """Output from team strength factor."""

    score: int  # -100 to +100 (positive = home stronger)
    efficiency: EfficiencyComparison
    tiers: StrengthTierComparison
    home_advantages: list[str]
    away_advantages: list[str]
    injury_impact: int  # -50 to +50
    reasoning: str


class TeamStrengthFactor:
    """Factor 3: Team strength and matchup analysis.

    Analyzes team rankings, efficiency metrics, and head-to-head factors.
    """

    # Net rating to win probability conversion
    # Each point of net rating difference ≈ 2.5% win probability
    NET_RATING_FACTOR = 2.5

    # Home court advantage in NBA ≈ 3 points
    HOME_COURT_ADVANTAGE = 3.0

    # Tier definitions
    TIER_THRESHOLDS = {
        "elite": 5.0,       # Net rating > 5
        "contender": 2.0,   # Net rating > 2
        "average": -2.0,    # Net rating > -2
        "below_average": -5.0,  # Net rating > -5
        # Everything else is "rebuilding"
    }

    def __init__(
        self,
        net_rating_weight: float = 0.5,
        record_weight: float = 0.2,
        home_away_weight: float = 0.15,
        streak_weight: float = 0.15,
    ):
        """Initialize team strength factor.

        Args:
            net_rating_weight: Weight for net rating comparison
            record_weight: Weight for win-loss records
            home_away_weight: Weight for home/away splits
            streak_weight: Weight for current streaks
        """
        self._net_rating_weight = net_rating_weight
        self._record_weight = record_weight
        self._home_away_weight = home_away_weight
        self._streak_weight = streak_weight

    def calculate(self, input_data: TeamStrengthInput) -> TeamStrengthOutput:
        """Calculate team strength score.

        Args:
            input_data: Team statistics data

        Returns:
            TeamStrengthOutput with score and analysis
        """
        home = input_data.home_stats
        away = input_data.away_stats

        # Log net rating data source
        if home.net_rating != 0.0 or away.net_rating != 0.0:
            logger.info(
                f"  Team strength: {home.team_abbreviation} net_rating={home.net_rating:+.1f}, "
                f"{away.team_abbreviation} net_rating={away.net_rating:+.1f}"
            )

        # Calculate efficiency comparison
        efficiency = self._analyze_efficiency(home, away)

        # Calculate tier comparison
        tiers = self._analyze_tiers(home, away)

        # Calculate component scores
        net_rating_score = self._score_net_rating(efficiency)
        record_score = self._score_records(home, away)
        home_away_score = self._score_home_away_splits(home, away)
        streak_score = self._score_streaks(home, away)

        # Log warning and adjust weights when net_rating data is unreliable
        if home.net_rating == 0.0 and away.net_rating == 0.0:
            logger.warning(
                f"Net ratings are 0.0 for both teams ({home.team_abbreviation} vs {away.team_abbreviation}). "
                f"Using records as primary quality signal."
            )

        # Combine with weights (adjusted when net_rating data is unavailable)
        nr_w, rec_w, ha_w, str_w = self._get_effective_weights(home, away)
        raw_score = (
            net_rating_score * nr_w
            + record_score * rec_w
            + home_away_score * ha_w
            + streak_score * str_w
        )

        # Analyze injury impact if context available
        injury_impact = 0
        if input_data.home_context and input_data.away_context:
            injury_impact = self._analyze_injuries(
                input_data.home_context, input_data.away_context
            )
            raw_score += injury_impact * 0.5

        score = int(max(-100, min(100, raw_score)))

        # Identify advantages
        home_advantages, away_advantages = self._identify_advantages(
            home, away, efficiency, tiers
        )

        reasoning = self._generate_reasoning(
            home, away, efficiency, tiers, score
        )

        return TeamStrengthOutput(
            score=score,
            efficiency=efficiency,
            tiers=tiers,
            home_advantages=home_advantages,
            away_advantages=away_advantages,
            injury_impact=injury_impact,
            reasoning=reasoning,
        )

    def _get_effective_weights(self, home: TeamStats, away: TeamStats) -> tuple[float, float, float, float]:
        """Get effective weights, adjusting when net_rating data is unavailable."""
        if home.net_rating == 0.0 and away.net_rating == 0.0:
            # Net rating unavailable — upweight records
            return (0.10, 0.45, 0.25, 0.20)  # net_rating, record, home_away, streak
        return (self._net_rating_weight, self._record_weight, self._home_away_weight, self._streak_weight)

    def _analyze_efficiency(
        self, home: TeamStats, away: TeamStats
    ) -> EfficiencyComparison:
        """Analyze efficiency metrics."""
        return EfficiencyComparison(
            home_net_rating=home.net_rating,
            away_net_rating=away.net_rating,
            net_rating_diff=home.net_rating - away.net_rating,
            home_pace=home.pace,
            away_pace=away.pace,
            expected_pace=(home.pace + away.pace) / 2,
        )

    def _analyze_tiers(
        self, home: TeamStats, away: TeamStats
    ) -> StrengthTierComparison:
        """Analyze team strength tiers."""
        home_tier = self._get_tier(home.net_rating)
        away_tier = self._get_tier(away.net_rating)

        tier_order = ["elite", "contender", "average", "below_average", "rebuilding"]
        home_idx = tier_order.index(home_tier)
        away_idx = tier_order.index(away_tier)

        mismatch = abs(home_idx - away_idx)

        if home_idx < away_idx:
            advantage = "home"
        elif away_idx < home_idx:
            advantage = "away"
        else:
            advantage = "even"

        return StrengthTierComparison(
            home_tier=home_tier,
            away_tier=away_tier,
            tier_advantage=advantage,
            mismatch_level=mismatch,
        )

    def _get_tier(self, net_rating: float) -> str:
        """Get team tier from net rating."""
        if net_rating > self.TIER_THRESHOLDS["elite"]:
            return "elite"
        elif net_rating > self.TIER_THRESHOLDS["contender"]:
            return "contender"
        elif net_rating > self.TIER_THRESHOLDS["average"]:
            return "average"
        elif net_rating > self.TIER_THRESHOLDS["below_average"]:
            return "below_average"
        return "rebuilding"

    def _score_net_rating(self, efficiency: EfficiencyComparison) -> float:
        """Score based on net rating difference."""
        diff = efficiency.net_rating_diff
        # Each point of net rating ≈ 2.5% win prob ≈ 5 points in our -100 to 100 scale
        return diff * 5

    def _score_records(self, home: TeamStats, away: TeamStats) -> float:
        """Score based on win-loss records (Pythagorean expected win%)."""
        home_wp = home.pythagorean_win_pct
        away_wp = away.pythagorean_win_pct
        diff = home_wp - away_wp  # -1 to +1

        return diff * 100  # Scale to -100 to +100

    def _score_home_away_splits(self, home: TeamStats, away: TeamStats) -> float:
        """Score based on home/away performance splits."""
        home_at_home = home.home_win_percentage
        away_on_road = away.away_win_percentage

        # Compare home team's home record vs away team's road record
        diff = home_at_home - away_on_road

        return diff * 80

    def _score_streaks(self, home: TeamStats, away: TeamStats) -> float:
        """Score based on current streaks."""
        home_streak = home.current_streak
        away_streak = away.current_streak

        # Cap streaks at 10 for scoring
        home_streak = max(-10, min(10, home_streak))
        away_streak = max(-10, min(10, away_streak))

        diff = home_streak - away_streak
        return diff * 5

    def _analyze_injuries(
        self, home_ctx: TeamContext, away_ctx: TeamContext
    ) -> int:
        """Analyze injury impact on team strength."""
        home_out = len(home_ctx.key_players_out)
        away_out = len(away_ctx.key_players_out)

        # Each key player out ≈ -15 impact
        home_impact = -home_out * 15
        away_impact = -away_out * 15

        # Net impact on home team's advantage
        return home_impact - away_impact

    def _identify_advantages(
        self,
        home: TeamStats,
        away: TeamStats,
        efficiency: EfficiencyComparison,
        tiers: StrengthTierComparison,
    ) -> tuple[list[str], list[str]]:
        """Identify specific advantages for each team."""
        home_adv = []
        away_adv = []

        # Net rating
        if efficiency.net_rating_diff > 3:
            home_adv.append(f"Better net rating (+{efficiency.net_rating_diff:.1f})")
        elif efficiency.net_rating_diff < -3:
            away_adv.append(f"Better net rating (+{-efficiency.net_rating_diff:.1f})")

        # Offensive/Defensive ratings
        if home.offensive_rating > away.offensive_rating + 2:
            home_adv.append("Superior offense")
        elif away.offensive_rating > home.offensive_rating + 2:
            away_adv.append("Superior offense")

        if home.defensive_rating < away.defensive_rating - 2:
            home_adv.append("Superior defense")
        elif away.defensive_rating < home.defensive_rating - 2:
            away_adv.append("Superior defense")

        # Streaks
        if home.current_streak >= 3:
            home_adv.append(f"{home.current_streak} game win streak")
        elif home.current_streak <= -3:
            away_adv.append(f"Opponent on {-home.current_streak} game losing streak")

        if away.current_streak >= 3:
            away_adv.append(f"{away.current_streak} game win streak")
        elif away.current_streak <= -3:
            home_adv.append(f"Opponent on {-away.current_streak} game losing streak")

        return home_adv, away_adv

    def _generate_reasoning(
        self,
        home: TeamStats,
        away: TeamStats,
        efficiency: EfficiencyComparison,
        tiers: StrengthTierComparison,
        score: int,
    ) -> str:
        """Generate human-readable reasoning."""
        parts = []

        # Tier comparison
        if tiers.home_tier != tiers.away_tier:
            parts.append(
                f"{home.team_abbreviation} ({tiers.home_tier}) vs "
                f"{away.team_abbreviation} ({tiers.away_tier})"
            )
        else:
            parts.append(f"Both teams are {tiers.home_tier} tier")

        # Net rating
        if abs(efficiency.net_rating_diff) > 2:
            better = home.team_abbreviation if efficiency.net_rating_diff > 0 else away.team_abbreviation
            parts.append(
                f"{better} has {abs(efficiency.net_rating_diff):.1f} better net rating"
            )

        # Overall assessment
        if abs(score) < 15:
            assessment = "Evenly matched teams"
        elif score > 0:
            assessment = f"{home.team_abbreviation} has strength advantage"
        else:
            assessment = f"{away.team_abbreviation} has strength advantage"

        # Note data quality issues
        if home.net_rating == 0.0 and away.net_rating == 0.0:
            parts.append("Note: team net rating data unavailable, using records as primary quality signal.")

        return f"{assessment}. {'. '.join(parts)}."
