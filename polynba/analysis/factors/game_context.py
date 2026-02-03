"""Game context factor - momentum, fouls, timeouts, clutch situations."""

import logging
from dataclasses import dataclass
from typing import Optional

from ...data.models import EventType, GameState, Period, TeamSide

logger = logging.getLogger(__name__)


@dataclass
class GameContextInput:
    """Input data for game context analysis."""

    game_state: GameState


@dataclass
class MomentumAnalysis:
    """Analysis of game momentum."""

    recent_scoring_diff: int  # Points differential in last N plays
    scoring_run: int  # Current scoring run
    momentum_team: Optional[TeamSide]
    momentum_strength: int  # 0-100


@dataclass
class ClutchAnalysis:
    """Analysis of clutch situation."""

    is_clutch: bool  # Within 5 points, last 5 minutes
    pressure_level: int  # 0-100
    clutch_description: str


@dataclass
class GameContextOutput:
    """Output from game context factor."""

    score: int  # -100 to +100 (positive = favors home)
    momentum: MomentumAnalysis
    clutch: ClutchAnalysis
    home_timeouts: int
    away_timeouts: int
    timeout_advantage: int  # Positive = home has more
    foul_situation: str
    reasoning: str


class GameContextFactor:
    """Factor 2: Game context and momentum analysis.

    Analyzes momentum shifts, foul trouble, timeout situations,
    and clutch game scenarios.
    """

    def __init__(
        self,
        momentum_weight: float = 0.4,
        timeout_weight: float = 0.2,
        clutch_weight: float = 0.3,
        foul_weight: float = 0.1,
    ):
        """Initialize game context factor.

        Args:
            momentum_weight: Weight for momentum in score
            timeout_weight: Weight for timeout advantage
            clutch_weight: Weight for clutch situations
            foul_weight: Weight for foul situations
        """
        self._momentum_weight = momentum_weight
        self._timeout_weight = timeout_weight
        self._clutch_weight = clutch_weight
        self._foul_weight = foul_weight

    def calculate(self, input_data: GameContextInput) -> GameContextOutput:
        """Calculate game context score.

        Args:
            input_data: Game state data

        Returns:
            GameContextOutput with score and analysis
        """
        game = input_data.game_state

        # Analyze each component
        momentum = self._analyze_momentum(game)
        clutch = self._analyze_clutch(game)
        timeout_score = self._analyze_timeouts(game)
        foul_score, foul_situation = self._analyze_fouls(game)

        # Calculate component scores
        momentum_contribution = (
            momentum.momentum_strength
            * (1 if momentum.momentum_team == TeamSide.HOME else -1 if momentum.momentum_team else 0)
            * self._momentum_weight
        )

        clutch_contribution = 0
        if clutch.is_clutch:
            # In clutch, momentum matters more
            clutch_contribution = (
                clutch.pressure_level * 0.3
                * (1 if momentum.momentum_team == TeamSide.HOME else -1 if momentum.momentum_team else 0)
            )

        timeout_contribution = timeout_score * self._timeout_weight
        foul_contribution = foul_score * self._foul_weight

        # Combine scores
        raw_score = (
            momentum_contribution
            + clutch_contribution
            + timeout_contribution
            + foul_contribution
        )

        score = int(max(-100, min(100, raw_score)))

        reasoning = self._generate_reasoning(
            game, momentum, clutch, score
        )

        return GameContextOutput(
            score=score,
            momentum=momentum,
            clutch=clutch,
            home_timeouts=game.home_team.timeouts_remaining,
            away_timeouts=game.away_team.timeouts_remaining,
            timeout_advantage=game.home_team.timeouts_remaining - game.away_team.timeouts_remaining,
            foul_situation=foul_situation,
            reasoning=reasoning,
        )

    def _analyze_momentum(self, game: GameState) -> MomentumAnalysis:
        """Analyze game momentum based on recent plays."""
        recent_plays = game.recent_plays[:10]  # Last 10 plays

        home_points = 0
        away_points = 0

        for play in recent_plays:
            if play.is_scoring_play:
                if play.team_id == game.home_team.team_id:
                    home_points += play.score_value
                elif play.team_id == game.away_team.team_id:
                    away_points += play.score_value

        scoring_diff = home_points - away_points

        # Calculate scoring run (consecutive scoring by one team)
        scoring_run = 0
        run_team = None

        for play in recent_plays:
            if play.is_scoring_play:
                if run_team is None:
                    run_team = play.team_id
                    scoring_run = play.score_value
                elif play.team_id == run_team:
                    scoring_run += play.score_value
                else:
                    break

        # Determine momentum team and strength
        if abs(scoring_diff) < 3:
            momentum_team = None
            momentum_strength = 0
        else:
            momentum_team = TeamSide.HOME if scoring_diff > 0 else TeamSide.AWAY
            # Scale: 3-6 pts = 20-40, 7-12 pts = 40-70, 13+ = 70-100
            if abs(scoring_diff) <= 6:
                momentum_strength = 20 + (abs(scoring_diff) - 3) * 7
            elif abs(scoring_diff) <= 12:
                momentum_strength = 40 + (abs(scoring_diff) - 7) * 5
            else:
                momentum_strength = min(100, 70 + (abs(scoring_diff) - 13) * 3)

        # Boost for long scoring runs
        if scoring_run >= 8:
            momentum_strength = min(100, momentum_strength + 15)

        return MomentumAnalysis(
            recent_scoring_diff=scoring_diff,
            scoring_run=scoring_run,
            momentum_team=momentum_team,
            momentum_strength=momentum_strength,
        )

    def _analyze_clutch(self, game: GameState) -> ClutchAnalysis:
        """Analyze if game is in clutch situation."""
        minutes_remaining = game.total_seconds_remaining / 60
        point_diff = abs(game.score_differential)

        # Clutch: last 5 minutes, within 5 points
        is_clutch = minutes_remaining <= 5 and point_diff <= 5

        # Extended clutch check
        is_extended_clutch = minutes_remaining <= 3 and point_diff <= 8

        if not is_clutch and not is_extended_clutch:
            return ClutchAnalysis(
                is_clutch=False,
                pressure_level=0,
                clutch_description="Not a clutch situation",
            )

        # Calculate pressure level
        # Higher pressure = less time, closer score
        time_pressure = max(0, (5 - minutes_remaining) / 5 * 50)
        score_pressure = max(0, (5 - point_diff) / 5 * 50)
        pressure_level = int(time_pressure + score_pressure)

        # Overtime is always max pressure
        if game.period.is_overtime:
            pressure_level = 100

        # Generate description
        if minutes_remaining <= 1:
            desc = "Final minute"
        elif minutes_remaining <= 2:
            desc = "Final 2 minutes"
        else:
            desc = "Clutch time"

        if point_diff == 0:
            desc += ", tied game"
        elif point_diff <= 2:
            desc += f", {point_diff} point game"
        else:
            desc += f", {point_diff} point margin"

        return ClutchAnalysis(
            is_clutch=True,
            pressure_level=pressure_level,
            clutch_description=desc,
        )

    def _analyze_timeouts(self, game: GameState) -> int:
        """Analyze timeout situation.

        Returns score from -100 to +100 based on timeout advantage.
        """
        home_to = game.home_team.timeouts_remaining
        away_to = game.away_team.timeouts_remaining
        diff = home_to - away_to

        minutes = game.total_seconds_remaining / 60

        # Timeouts matter more late in game
        if minutes > 12:
            multiplier = 5
        elif minutes > 6:
            multiplier = 10
        elif minutes > 3:
            multiplier = 15
        else:
            multiplier = 20

        return int(max(-100, min(100, diff * multiplier)))

    def _analyze_fouls(self, game: GameState) -> tuple[int, str]:
        """Analyze foul situation.

        Returns (score, description).
        """
        home_fouls = game.home_team.team_fouls
        away_fouls = game.away_team.team_fouls
        diff = away_fouls - home_fouls  # Positive = opponent in foul trouble

        # Check bonus situations
        home_in_bonus = game.home_team.in_bonus or home_fouls >= 4
        away_in_bonus = game.away_team.in_bonus or away_fouls >= 4

        situation_parts = []

        if away_in_bonus:
            situation_parts.append("Home in bonus")

        if home_in_bonus:
            situation_parts.append("Away in bonus")

        if not situation_parts:
            if away_fouls > home_fouls + 2:
                situation_parts.append("Away in foul trouble")
            elif home_fouls > away_fouls + 2:
                situation_parts.append("Home in foul trouble")
            else:
                situation_parts.append("Neutral foul situation")

        situation = "; ".join(situation_parts)

        # Score based on foul differential and bonus
        score = diff * 5  # Base from foul diff

        if away_in_bonus and not home_in_bonus:
            score += 15
        elif home_in_bonus and not away_in_bonus:
            score -= 15

        return int(max(-100, min(100, score))), situation

    def _generate_reasoning(
        self,
        game: GameState,
        momentum: MomentumAnalysis,
        clutch: ClutchAnalysis,
        score: int,
    ) -> str:
        """Generate human-readable reasoning."""
        parts = []

        # Momentum
        if momentum.momentum_team:
            team_name = (
                game.home_team.team_abbreviation
                if momentum.momentum_team == TeamSide.HOME
                else game.away_team.team_abbreviation
            )
            parts.append(
                f"{team_name} has momentum ({momentum.momentum_strength}% strength)"
            )
            if momentum.scoring_run >= 6:
                parts.append(f"on a {momentum.scoring_run}-0 run")
        else:
            parts.append("No clear momentum")

        # Clutch
        if clutch.is_clutch:
            parts.append(f"{clutch.clutch_description}")

        # Overall assessment
        if abs(score) < 15:
            assessment = "Neutral game context"
        elif score > 0:
            assessment = "Context favors home"
        else:
            assessment = "Context favors away"

        return f"{assessment}. {'. '.join(parts)}."
