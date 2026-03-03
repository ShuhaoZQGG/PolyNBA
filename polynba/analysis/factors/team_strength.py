"""Team strength factor - rankings, efficiency, and matchups."""

import logging
from dataclasses import dataclass
from typing import Optional

from ...data.models import PlayerInjury, PlayerSeasonStats, TeamContext, TeamStats

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
class AdvancedStatsComparison:
    """Four Factors + advanced stat diffs between home and away teams.

    All diffs are home - away; positive = home advantage.
    """

    efg_diff: float           # eFG% diff (percentage points, e.g. 2.1)
    tov_diff: float           # TOV% diff (negative = home turns over less = good)
    oreb_diff: float          # OREB% diff
    ft_rate_diff: float       # FT rate proxy diff (FT% * FTA-ratio estimate)
    pie_diff: float           # PIE diff
    ast_to_diff: float        # AST/TO ratio diff
    four_factors_score: float # Composite Dean Oliver score (-15 to +15)

    @property
    def has_data(self) -> bool:
        return self.four_factors_score != 0.0


@dataclass
class RotationComparison:
    """Rotation EIR comparison between home and away teams."""

    home_starter_avg_eir: float
    away_starter_avg_eir: float
    home_top8_avg_eir: float
    away_top8_avg_eir: float
    home_bench_avg_eir: float
    away_bench_avg_eir: float
    rotation_score: float  # Composite score (-10 to +10)

    @property
    def has_data(self) -> bool:
        return self.home_top8_avg_eir > 0 or self.away_top8_avg_eir > 0


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
    advanced_stats: Optional[AdvancedStatsComparison] = None
    rotation: Optional[RotationComparison] = None


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

        # Score new factors (guarded: return 0 when data missing)
        four_factors_score, advanced_stats = self._score_four_factors(home, away)
        rotation_score, rotation_comp = self._score_rotation_strength(
            input_data.home_context, input_data.away_context
        )

        has_advanced = advanced_stats is not None and advanced_stats.has_data
        has_rotation = rotation_comp is not None and rotation_comp.has_data

        # Combine with weights — scale existing down when advanced data available
        nr_w, rec_w, ha_w, str_w = self._get_effective_weights(home, away)

        if has_advanced or has_rotation:
            # Scale existing weights by 0.85 to make room for new factors
            scale = 0.85
            nr_w *= scale
            rec_w *= scale
            ha_w *= scale
            str_w *= scale

        raw_score = (
            net_rating_score * nr_w
            + record_score * rec_w
            + home_away_score * ha_w
            + streak_score * str_w
        )

        # Add Four Factors (10% weight) and Rotation (5% weight)
        if has_advanced:
            raw_score += four_factors_score * 0.10
        if has_rotation:
            raw_score += rotation_score * 0.05

        # Analyze injury impact if context available
        injury_impact = 0
        if input_data.home_context and input_data.away_context:
            injury_impact = self._analyze_injuries(
                input_data.home_context, input_data.away_context
            )
            raw_score += injury_impact * 0.5

        # Bonus advantages from advanced data
        if advanced_stats and advanced_stats.has_data:
            if advanced_stats.efg_diff > 2.0:
                raw_score += 2.0
            elif advanced_stats.efg_diff < -2.0:
                raw_score -= 2.0
            if advanced_stats.tov_diff < -1.5:
                raw_score += 1.5  # Home turns over less
            elif advanced_stats.tov_diff > 1.5:
                raw_score -= 1.5
        if rotation_comp and rotation_comp.has_data and abs(rotation_comp.rotation_score) > 3:
            raw_score += rotation_comp.rotation_score * 0.3

        score = int(max(-100, min(100, raw_score)))

        # Identify advantages
        home_advantages, away_advantages = self._identify_advantages(
            home, away, efficiency, tiers,
            advanced_stats=advanced_stats,
            rotation=rotation_comp,
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
            advanced_stats=advanced_stats,
            rotation=rotation_comp,
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

    def _score_four_factors(
        self, home: TeamStats, away: TeamStats
    ) -> tuple[float, Optional[AdvancedStatsComparison]]:
        """Score based on Dean Oliver's Four Factors.

        Weights: eFG% (40%), TOV% (25%), OREB% (20%), FT rate (15%).
        Returns score in [-15, +15] range and the comparison data.
        Returns (0.0, None) when eFG% data is missing.
        """
        # Guard: need eFG% for both teams
        if home.effective_field_goal_percentage == 0.0 or away.effective_field_goal_percentage == 0.0:
            return 0.0, None

        # eFG% diff (percentage points, e.g. home 52% - away 50% = +2.0)
        efg_diff = (home.effective_field_goal_percentage - away.effective_field_goal_percentage) * 100

        # TOV% diff (lower is better, so negate: home 12% - away 14% = -2, good for home)
        # turnover_pct is a fraction (0.125 = 12.5%)
        tov_diff = (home.turnover_pct - away.turnover_pct) * 100

        # OREB% diff (higher is better)
        oreb_diff = (home.offensive_rebound_pct - away.offensive_rebound_pct) * 100

        # FT rate proxy: FT% is available; approximate FT rate with FT%
        # (not ideal but best available without FTA/FGA ratio)
        ft_home = home.free_throw_percentage if home.free_throw_percentage > 0 else 75.0
        ft_away = away.free_throw_percentage if away.free_throw_percentage > 0 else 75.0
        ft_rate_diff = ft_home - ft_away

        # Composite: Dean Oliver weights, scale each factor to contribute proportionally
        # eFG diff of 3 pct points is huge → scale so 3 → ~4.5 contribution (40% weight)
        # TOV diff of 2 pct points → scale so 2 → ~2.5 contribution (25% weight, inverted)
        # OREB diff of 2 pct points → scale so 2 → ~2.0 contribution (20% weight)
        # FT rate diff of 5 pct points → scale so 5 → ~1.5 contribution (15% weight)
        composite = (
            efg_diff * 1.5 * 0.40          # eFG: 40% weight
            + (-tov_diff) * 1.25 * 0.25    # TOV: 25% weight (inverted: less is better)
            + oreb_diff * 1.0 * 0.20       # OREB: 20% weight
            + ft_rate_diff * 0.06 * 0.15   # FT: 15% weight (smaller scale)
        )

        # Clamp to [-15, +15]
        composite = max(-15.0, min(15.0, composite))

        # PIE and AST/TO diffs (informational, not in composite)
        pie_diff = (home.team_pie - away.team_pie) * 100
        ast_to_diff = home.assist_to_turnover - away.assist_to_turnover

        comparison = AdvancedStatsComparison(
            efg_diff=efg_diff,
            tov_diff=tov_diff,
            oreb_diff=oreb_diff,
            ft_rate_diff=ft_rate_diff,
            pie_diff=pie_diff,
            ast_to_diff=ast_to_diff,
            four_factors_score=composite,
        )

        logger.info(
            f"  Four Factors: eFG% diff={efg_diff:+.1f}, TOV% diff={tov_diff:+.1f}, "
            f"OREB% diff={oreb_diff:+.1f} → composite={composite:+.1f}"
        )

        # Scale composite to the raw_score space (Four Factors weight applied in calculate())
        # composite is [-15, +15]; scale to [-100, +100] for consistent weighting
        return composite * (100 / 15), comparison

    def _score_rotation_strength(
        self,
        home_ctx: Optional[TeamContext],
        away_ctx: Optional[TeamContext],
    ) -> tuple[float, Optional[RotationComparison]]:
        """Score based on rotation EIR comparison.

        Weights: top-8 avg EIR (50%), starter avg EIR (30%), bench avg EIR (20%).
        Returns score in [-10, +10] range and the comparison data.
        Returns (0.0, None) when context or player data is unavailable.
        """
        if not home_ctx or not away_ctx:
            return 0.0, None

        home_players = list(home_ctx.player_stats_map.values())
        away_players = list(away_ctx.player_stats_map.values())

        if not home_players or not away_players:
            return 0.0, None

        def _rotation_eirs(players: list[PlayerSeasonStats]) -> tuple[float, float, float]:
            """Return (starter_avg, top8_avg, bench_avg) EIR."""
            # Sort by minutes descending to identify starters vs bench
            by_mins = sorted(players, key=lambda p: p.minutes_per_game, reverse=True)
            starters = [p for p in by_mins if p.minutes_per_game >= 24][:5]
            top8 = by_mins[:8]
            bench = [p for p in by_mins if p.is_bench and p.estimated_impact_rating > 0]

            starter_avg = (
                sum(p.estimated_impact_rating for p in starters) / len(starters)
                if starters else 0.0
            )
            top8_avg = (
                sum(p.estimated_impact_rating for p in top8) / len(top8)
                if top8 else 0.0
            )
            bench_avg = (
                sum(p.estimated_impact_rating for p in bench) / len(bench)
                if bench else 0.0
            )
            return starter_avg, top8_avg, bench_avg

        h_starter, h_top8, h_bench = _rotation_eirs(home_players)
        a_starter, a_top8, a_bench = _rotation_eirs(away_players)

        if h_top8 == 0.0 and a_top8 == 0.0:
            return 0.0, None

        # Composite: top-8 (50%), starters (30%), bench (20%)
        top8_diff = h_top8 - a_top8
        starter_diff = h_starter - a_starter
        bench_diff = h_bench - a_bench

        composite = (
            top8_diff * 0.50
            + starter_diff * 0.30
            + bench_diff * 0.20
        )

        # Clamp to [-10, +10]
        composite = max(-10.0, min(10.0, composite))

        comparison = RotationComparison(
            home_starter_avg_eir=h_starter,
            away_starter_avg_eir=a_starter,
            home_top8_avg_eir=h_top8,
            away_top8_avg_eir=a_top8,
            home_bench_avg_eir=h_bench,
            away_bench_avg_eir=a_bench,
            rotation_score=composite,
        )

        logger.info(
            f"  Rotation: top-8 EIR {h_top8:.1f} vs {a_top8:.1f}, "
            f"starters {h_starter:.1f} vs {a_starter:.1f} → score={composite:+.1f}"
        )

        # Scale composite to raw_score space (Rotation weight applied in calculate())
        # composite is [-10, +10]; scale to [-100, +100]
        return composite * (100 / 10), comparison

    def _player_injury_impact(self, injury: PlayerInjury) -> float:
        """Estimate net rating impact of losing one player using EIR + NET_RATING.

        When both EIR and per-player net_rating are available, blends them
        (65% EIR, 35% NET_RATING) for a more accurate estimate. Positive
        net_rating means full penalty when lost; negative net_rating reduces
        the penalty. Falls back to EIR-only or basic stats when data is missing.
        """
        if not injury.player_stats:
            return -(3.0 + 0.5 * 2.5) * 0.05  # ~-0.2 fallback

        s = injury.player_stats
        eir = s.estimated_impact_rating

        if eir > 0:
            # EIR-based impact: scale EIR by replacement difficulty
            if eir >= 25:
                replacement_difficulty = 0.35
            elif eir >= 18:
                replacement_difficulty = 0.28
            elif eir >= 12:
                replacement_difficulty = 0.20
            elif eir >= 8:
                replacement_difficulty = 0.12
            else:
                replacement_difficulty = 0.05

            eir_impact = -(eir * replacement_difficulty)

            # Blend with per-player NET_RATING when available
            if s.net_rating != 0.0:
                # net_rating is pts per 100 possessions — scale to comparable range
                # Positive NR = good player, full penalty when lost
                # Negative NR = bad player, reduced penalty
                nr_impact = -(s.net_rating * 0.3)
                return 0.65 * eir_impact + 0.35 * nr_impact

            return eir_impact

        # Fallback: basic stats when no extended data
        scoring_value = s.points_per_game + s.assists_per_game * 2.5
        total_value = scoring_value + s.rebounds_per_game * 0.5

        if total_value >= 25:
            replacement_pct = 0.35
        elif total_value >= 15:
            replacement_pct = 0.25
        elif total_value >= 8:
            replacement_pct = 0.15
        else:
            replacement_pct = 0.05

        return -(total_value * replacement_pct)

    # Position compatibility groups for replacement matching
    _POSITION_COMPAT: dict[str, set[str]] = {
        "G": {"G", "G-F", "PG", "SG"},
        "F": {"F", "G-F", "F-C", "SF", "PF"},
        "C": {"C", "F-C", "PF"},
        "PG": {"PG", "G", "SG", "G-F"},
        "SG": {"SG", "G", "PG", "G-F"},
        "SF": {"SF", "F", "G-F", "PF"},
        "PF": {"PF", "F", "F-C", "C", "SF"},
        "G-F": {"G-F", "G", "F", "SG", "SF"},
        "F-C": {"F-C", "F", "C", "PF"},
    }

    def _analyze_replacement_quality(self, ctx: TeamContext) -> float:
        """Analyze how well bench players can replace injured starters.

        For each injured starter, find the best available bench player at a
        compatible position and compare their EIR.

        Returns:
            Positive offset (0-15) that reduces injury damage when bench depth
            is strong.
        """
        injured_starters = [
            inj for inj in ctx.key_players_out
            if inj.player_stats and inj.player_stats.minutes_per_game >= 28
        ]
        if not injured_starters:
            return 0.0

        # Build set of injured player names for exclusion
        injured_names = {inj.player_name for inj in ctx.injuries}

        # Collect available bench players with EIR data
        bench_players: list[PlayerSeasonStats] = []
        for name, ps in ctx.player_stats_map.items():
            if name not in injured_names and ps.is_bench and ps.estimated_impact_rating > 0:
                bench_players.append(ps)

        if not bench_players:
            return 0.0

        total_ratio = 0.0
        matched = 0

        for inj in injured_starters:
            starter = inj.player_stats
            if not starter or starter.estimated_impact_rating <= 0:
                continue

            # Find best bench replacement at compatible position
            compat = self._POSITION_COMPAT.get(starter.position, {starter.position})
            candidates = [bp for bp in bench_players if bp.position in compat]
            if not candidates:
                candidates = bench_players  # any position as fallback

            best = max(candidates, key=lambda p: p.estimated_impact_rating)
            ratio = best.estimated_impact_rating / starter.estimated_impact_rating
            total_ratio += min(ratio, 1.0)  # cap at 1.0
            matched += 1

            logger.debug(
                f"  Replacement: {inj.player_name} (EIR {starter.estimated_impact_rating:.1f}) "
                f"-> {best.player_name} (EIR {best.estimated_impact_rating:.1f}, ratio {ratio:.2f})"
            )

        if matched == 0:
            return 0.0

        avg_ratio = total_ratio / matched

        # Score: high ratio (>0.7) = good depth, low ratio (<0.4) = thin bench
        # Map ratio 0.0-1.0 -> offset 0-15
        offset = avg_ratio * 15.0
        return offset

    def _analyze_injuries(
        self, home_ctx: TeamContext, away_ctx: TeamContext
    ) -> int:
        """Analyze injury impact on team strength using EIR + replacement quality."""
        home_impact = sum(
            self._player_injury_impact(inj) for inj in home_ctx.key_players_out
        )
        away_impact = sum(
            self._player_injury_impact(inj) for inj in away_ctx.key_players_out
        )

        # Scale to match NET_RATING_FACTOR (×3 converts lost-points to score scale)
        home_score = home_impact * 3
        away_score = away_impact * 3

        # Replacement quality offsets: good bench depth reduces injury damage
        home_repl_quality = self._analyze_replacement_quality(home_ctx)
        away_repl_quality = self._analyze_replacement_quality(away_ctx)

        # Net impact on home team's advantage (positive = home benefits)
        injury_net = home_score - away_score
        replacement_net = home_repl_quality - away_repl_quality
        return int(injury_net + replacement_net)

    def _identify_advantages(
        self,
        home: TeamStats,
        away: TeamStats,
        efficiency: EfficiencyComparison,
        tiers: StrengthTierComparison,
        advanced_stats: Optional[AdvancedStatsComparison] = None,
        rotation: Optional[RotationComparison] = None,
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

        # Shooting efficiency (Four Factors)
        if advanced_stats and advanced_stats.has_data:
            if advanced_stats.efg_diff > 2.0:
                home_adv.append(f"Better shooting efficiency (eFG% +{advanced_stats.efg_diff:.1f})")
            elif advanced_stats.efg_diff < -2.0:
                away_adv.append(f"Better shooting efficiency (eFG% +{-advanced_stats.efg_diff:.1f})")

            if advanced_stats.tov_diff < -1.5:
                home_adv.append("Better ball security")
            elif advanced_stats.tov_diff > 1.5:
                away_adv.append("Better ball security")

        # Rotation depth
        if rotation and rotation.has_data:
            if rotation.rotation_score > 3:
                home_adv.append(f"Deeper rotation (top-8 EIR {rotation.home_top8_avg_eir:.1f} vs {rotation.away_top8_avg_eir:.1f})")
            elif rotation.rotation_score < -3:
                away_adv.append(f"Deeper rotation (top-8 EIR {rotation.away_top8_avg_eir:.1f} vs {rotation.home_top8_avg_eir:.1f})")

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
