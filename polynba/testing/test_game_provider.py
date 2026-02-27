"""Test game data provider: scenario-driven GameSummary, evolving GameState, and TestDataManager."""

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..data.models import (
    EventType,
    GameState,
    GameStatus,
    GameSummary,
    Period,
    PlayEvent,
    TeamContext,
    TeamGameState,
    TeamStats,
)

logger = logging.getLogger(__name__)

TEST_GAME_ID = "test_game_001"
TEST_HOME_TEAM_ID = "test_home"
TEST_AWAY_TEAM_ID = "test_away"
TEST_HOME_NAME = "Test Home"
TEST_AWAY_NAME = "Test Away"
TEST_HOME_ABBR = "THM"
TEST_AWAY_ABBR = "TAY"


def _make_team_game_state(
    team_id: str,
    name: str,
    abbr: str,
    score: int,
) -> TeamGameState:
    return TeamGameState(
        team_id=team_id,
        team_name=name,
        team_abbreviation=abbr,
        score=score,
    )


def _make_game_state(
    period: Period,
    clock: str,
    home_score: int,
    away_score: int,
    status: GameStatus = GameStatus.IN_PROGRESS,
    recent_plays: list[PlayEvent] | None = None,
) -> GameState:
    return GameState(
        game_id=TEST_GAME_ID,
        status=status,
        period=period,
        clock=clock,
        home_team=_make_team_game_state(
            TEST_HOME_TEAM_ID, TEST_HOME_NAME, TEST_HOME_ABBR, home_score
        ),
        away_team=_make_team_game_state(
            TEST_AWAY_TEAM_ID, TEST_AWAY_NAME, TEST_AWAY_ABBR, away_score
        ),
        recent_plays=recent_plays or [],
    )


def _clock_to_seconds(clock: str) -> int:
    """Parse M:SS to seconds remaining in period."""
    if not clock or clock == "0:00":
        return 0
    parts = clock.split(":")
    if len(parts) != 2:
        return 0
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return 0


def _seconds_to_clock(sec: int) -> str:
    """Format seconds to M:SS."""
    sec = max(0, sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _next_period(period: Period) -> Period:
    """Next period (Q2->Q3, Q4->OT1, etc.)."""
    if period.value >= 8:
        return Period.OVERTIME_4
    return Period(period.value + 1)


# One possession ~24–30 sec; points per possession: 0 (miss), 1 (FT), 2, or 3 (and-1 rare)
POSSESSION_SECONDS = 28
# Weights: no score, 1 pt (FT), 2 pts, 3 pts (rough NBA mix)
POINT_WEIGHTS = (18, 12, 48, 22)

# Regulation: 4 quarters * 12 min = 2880 seconds total
REGULATION_SECONDS = 4 * 12 * 60
QUARTER_SECONDS = 12 * 60
OT_SECONDS = 5 * 60


def _win_pct_to_record(win_pct: float) -> tuple[int, int, float]:
    """Convert a win percentage to a realistic (wins, losses, pct) tuple."""
    total = random.randint(50, 60)
    wins = max(0, min(total, round(total * win_pct)))
    losses = total - wins
    pct = wins / total if total else 0.0
    return wins, losses, pct


def _win_pct_to_net_rating(win_pct: float) -> float:
    """Map win percentage to approximate net rating."""
    return (win_pct - 0.5) * 12.0


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


class GameScenario(str, Enum):
    """Available test game scenarios."""

    HOME_BLOWOUT = "home_blowout"
    AWAY_BLOWOUT = "away_blowout"
    CLOSE_GAME = "close_game"
    HOME_COMEBACK = "home_comeback"
    AWAY_COMEBACK = "away_comeback"
    FAILED_COMEBACK = "failed_comeback"
    OVERTIME_THRILLER = "overtime_thriller"
    WIRE_TO_WIRE = "wire_to_wire"
    LATE_COLLAPSE = "late_collapse"
    BACK_AND_FORTH = "back_and_forth"


def resolve_scenario(name: str | None) -> str:
    """Resolve a scenario name, picking randomly if None or "random".

    Returns the resolved scenario value string (e.g. "home_blowout").
    """
    if name and name != "random":
        try:
            return GameScenario(name).value
        except ValueError:
            logger.warning(f"Unknown scenario '{name}', picking random")
    return random.choice(list(GameScenario)).value


@dataclass(frozen=True)
class LeadWaypoint:
    """Target lead at a given game-time fraction.

    progress: 0.0 = start Q1, 0.25 = end Q1, 0.5 = halftime, 1.0 = end Q4.
              OT extends beyond 1.0 (up to ~1.104 for OT1).
    target_lead: desired home lead (positive=home, negative=away).
    noise_range: how wide the score can wander from target before correction kicks in.
    """

    progress: float
    target_lead: int
    noise_range: int


@dataclass(frozen=True)
class ScenarioDefinition:
    """Full definition of a test game scenario."""

    waypoints: list[LeadWaypoint]
    home_win_pct: float
    away_win_pct: float
    has_overtime: bool

    @property
    def final_waypoint(self) -> LeadWaypoint:
        return self.waypoints[-1]


SCENARIO_DEFINITIONS: dict[GameScenario, ScenarioDefinition] = {
    GameScenario.HOME_BLOWOUT: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 4),
            LeadWaypoint(0.25, 8, 5),
            LeadWaypoint(0.50, 15, 6),
            LeadWaypoint(0.75, 20, 6),
            LeadWaypoint(1.0, 22, 5),
        ],
        home_win_pct=0.65,
        away_win_pct=0.38,
        has_overtime=False,
    ),
    GameScenario.AWAY_BLOWOUT: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 4),
            LeadWaypoint(0.25, -8, 5),
            LeadWaypoint(0.50, -15, 6),
            LeadWaypoint(0.75, -20, 6),
            LeadWaypoint(1.0, -22, 5),
        ],
        home_win_pct=0.38,
        away_win_pct=0.65,
        has_overtime=False,
    ),
    GameScenario.CLOSE_GAME: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 3),
            LeadWaypoint(0.25, 2, 4),
            LeadWaypoint(0.50, -1, 4),
            LeadWaypoint(0.75, 3, 4),
            LeadWaypoint(1.0, 2, 3),
        ],
        home_win_pct=0.52,
        away_win_pct=0.50,
        has_overtime=False,
    ),
    GameScenario.HOME_COMEBACK: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 3),
            LeadWaypoint(0.25, -6, 4),
            LeadWaypoint(0.50, -12, 5),
            LeadWaypoint(0.75, -4, 5),
            LeadWaypoint(1.0, 4, 4),
        ],
        home_win_pct=0.55,
        away_win_pct=0.52,
        has_overtime=False,
    ),
    GameScenario.AWAY_COMEBACK: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 3),
            LeadWaypoint(0.25, 6, 4),
            LeadWaypoint(0.50, 12, 5),
            LeadWaypoint(0.75, 4, 5),
            LeadWaypoint(1.0, -4, 4),
        ],
        home_win_pct=0.52,
        away_win_pct=0.55,
        has_overtime=False,
    ),
    GameScenario.FAILED_COMEBACK: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 3),
            LeadWaypoint(0.25, -4, 4),
            LeadWaypoint(0.50, -12, 5),
            LeadWaypoint(0.75, -8, 5),
            LeadWaypoint(1.0, -4, 4),
        ],
        home_win_pct=0.48,
        away_win_pct=0.55,
        has_overtime=False,
    ),
    GameScenario.OVERTIME_THRILLER: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 3),
            LeadWaypoint(0.25, 3, 4),
            LeadWaypoint(0.50, -2, 4),
            LeadWaypoint(0.75, 4, 4),
            LeadWaypoint(1.0, 0, 2),  # tied at end of regulation → OT
            LeadWaypoint(1.104, 3, 3),  # OT1 end (5 min / 48 min ≈ 0.104)
        ],
        home_win_pct=0.50,
        away_win_pct=0.50,
        has_overtime=True,
    ),
    GameScenario.WIRE_TO_WIRE: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 3),
            LeadWaypoint(0.25, 5, 4),
            LeadWaypoint(0.50, 7, 4),
            LeadWaypoint(0.75, 6, 4),
            LeadWaypoint(1.0, 6, 3),
        ],
        home_win_pct=0.58,
        away_win_pct=0.45,
        has_overtime=False,
    ),
    GameScenario.LATE_COLLAPSE: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 3),
            LeadWaypoint(0.25, 6, 4),
            LeadWaypoint(0.50, 10, 5),
            LeadWaypoint(0.75, 12, 5),
            LeadWaypoint(1.0, -3, 4),
        ],
        home_win_pct=0.48,
        away_win_pct=0.55,
        has_overtime=False,
    ),
    GameScenario.BACK_AND_FORTH: ScenarioDefinition(
        waypoints=[
            LeadWaypoint(0.0, 0, 3),
            LeadWaypoint(0.25, -4, 5),
            LeadWaypoint(0.50, 5, 5),
            LeadWaypoint(0.75, -3, 5),
            LeadWaypoint(1.0, 5, 4),
        ],
        home_win_pct=0.52,
        away_win_pct=0.52,
        has_overtime=False,
    ),
}


def _interpolate_waypoints(
    waypoints: list[LeadWaypoint], progress: float
) -> tuple[float, float]:
    """Interpolate target_lead and noise_range at a given progress value.

    Returns (target_lead, noise_range).
    """
    if progress <= waypoints[0].progress:
        return float(waypoints[0].target_lead), float(waypoints[0].noise_range)
    if progress >= waypoints[-1].progress:
        return float(waypoints[-1].target_lead), float(waypoints[-1].noise_range)

    # Find surrounding waypoints
    for i in range(len(waypoints) - 1):
        wp_a, wp_b = waypoints[i], waypoints[i + 1]
        if wp_a.progress <= progress <= wp_b.progress:
            span = wp_b.progress - wp_a.progress
            if span <= 0:
                t = 1.0
            else:
                t = (progress - wp_a.progress) / span
            target = wp_a.target_lead + t * (wp_b.target_lead - wp_a.target_lead)
            noise = wp_a.noise_range + t * (wp_b.noise_range - wp_a.noise_range)
            return target, noise

    # Fallback (shouldn't reach)
    return float(waypoints[-1].target_lead), float(waypoints[-1].noise_range)


def _game_progress(period: Period, clock_seconds: int) -> float:
    """Calculate game progress as a fraction.

    0.0 = start Q1, 0.25 = end Q1, 0.50 = halftime, 1.0 = end Q4.
    OT extends beyond 1.0.
    """
    pv = period.value
    if pv <= 4:
        # Regulation: each quarter is 0.25 of progress
        quarter_progress = 1.0 - (clock_seconds / QUARTER_SECONDS)
        return (pv - 1) * 0.25 + quarter_progress * 0.25
    else:
        # Overtime periods extend beyond 1.0
        ot_number = pv - 4  # 1-based
        ot_progress = 1.0 - (clock_seconds / OT_SECONDS)
        return 1.0 + (ot_number - 1) * (OT_SECONDS / REGULATION_SECONDS) + ot_progress * (OT_SECONDS / REGULATION_SECONDS)


class TestGameProvider:
    """Scenario-driven test game: one state advanced by one possession per get_game_state.

    Each scenario defines waypoints for the target lead at key game moments.
    A proportional-control mechanism biases home_score_prob to steer the score
    toward the target, while keeping per-possession randomness realistic.
    """

    def __init__(self, n_states: int = 20, scenario: str | None = None):
        """Initialize with a scenario-driven game.

        Args:
            n_states: Unused, kept for API compatibility.
            scenario: Scenario name (e.g. "home_blowout"). None or "random" picks randomly.
        """
        # Resolve scenario (use pre-resolved name if provided, else pick)
        self._scenario = GameScenario(resolve_scenario(scenario))
        self._definition = SCENARIO_DEFINITIONS[self._scenario]
        self.scenario_name: str = self._scenario.value
        logger.info(f"Test game scenario: {self.scenario_name}")

        # Team records from scenario definition
        self._home_win_pct = self._definition.home_win_pct
        self._away_win_pct = self._definition.away_win_pct
        self._home_wins, self._home_losses, self._home_win_pct = _win_pct_to_record(
            self._home_win_pct
        )
        self._away_wins, self._away_losses, self._away_win_pct = _win_pct_to_record(
            self._away_win_pct
        )
        self._home_net_rating = _win_pct_to_net_rating(self._home_win_pct)
        self._away_net_rating = _win_pct_to_net_rating(self._away_win_pct)

        # Game state
        self._recent_plays: list[PlayEvent] = []
        self._play_counter: int = 0
        self._game_over: bool = False

        # Start at Q1 12:00, score 0-0
        self._state = _make_game_state(
            Period.FIRST_QUARTER, "12:00", 0, 0
        )

    def _advance(self) -> None:
        """Advance game by one possession with scenario-driven scoring."""
        if self._game_over:
            return

        period = self._state.period
        clock_sec = _clock_to_seconds(self._state.clock)
        clock_sec -= POSSESSION_SECONDS

        # Period transition
        if clock_sec <= 0:
            home_score = self._state.home_team.score
            away_score = self._state.away_team.score

            # Check for game end
            if period.value >= 4 and home_score != away_score:
                # Game ends: a team is leading at end of Q4 or later
                self._game_over = True
                self._state = _make_game_state(
                    period, "0:00", home_score, away_score,
                    status=GameStatus.FINAL,
                    recent_plays=list(self._recent_plays),
                )
                logger.info(
                    f"Test game FINAL: {TEST_HOME_ABBR} {home_score} - "
                    f"{TEST_AWAY_ABBR} {away_score} ({period.display_name})"
                )
                return

            if period.value >= 4 and home_score == away_score:
                # Tied at end of Q4+ → go to overtime (force winner at OT4)
                if period == Period.OVERTIME_4:
                    # Force a winner: give home +1
                    home_score += 1
                    self._game_over = True
                    self._state = _make_game_state(
                        period, "0:00", home_score, away_score,
                        status=GameStatus.FINAL,
                        recent_plays=list(self._recent_plays),
                    )
                    logger.info(
                        f"Test game FINAL (OT4 tiebreaker): {TEST_HOME_ABBR} {home_score} - "
                        f"{TEST_AWAY_ABBR} {away_score}"
                    )
                    return
                else:
                    period = _next_period(period)
                    clock_sec = OT_SECONDS
                    logger.info(
                        f"Test game going to {period.display_name}: "
                        f"{TEST_HOME_ABBR} {home_score} - {TEST_AWAY_ABBR} {away_score}"
                    )
            else:
                # Normal period transition (Q1→Q2, Q2→Q3, Q3→Q4)
                period = _next_period(period)
                quarter_sec = OT_SECONDS if period.value > 4 else QUARTER_SECONDS
                clock_sec = quarter_sec + clock_sec  # clock_sec is negative, so this subtracts remainder
                if clock_sec < 0:
                    clock_sec = 0

        clock_str = _seconds_to_clock(clock_sec)

        # Calculate game progress
        progress = _game_progress(period, clock_sec)

        # Interpolate target lead and noise range
        target_lead, noise_range = _interpolate_waypoints(
            self._definition.waypoints, progress
        )

        # Proportional control: steer actual lead toward target
        home_score = self._state.home_team.score
        away_score = self._state.away_team.score
        actual_lead = home_score - away_score
        error = target_lead - actual_lead

        noise_denom = max(noise_range, 1.0)
        correction = max(-0.25, min(0.25, error / noise_denom * 0.15))
        noise = random.gauss(0, 0.03)
        home_score_prob = max(0.25, min(0.75, 0.50 + correction + noise))

        # Score the possession
        pts = random.choices([0, 1, 2, 3], weights=POINT_WEIGHTS)[0]
        home_scored = random.random() < home_score_prob
        if home_scored:
            home_score += pts
        else:
            away_score += pts

        # Generate PlayEvent for scoring possessions
        if pts > 0:
            event_type = {
                1: EventType.FREE_THROW_MADE,
                2: EventType.FIELD_GOAL_MADE,
                3: EventType.THREE_POINTER_MADE,
            }[pts]
            self._play_counter += 1
            play = PlayEvent(
                event_id=f"test_{self._play_counter}",
                period=period,
                clock=clock_str,
                event_type=event_type,
                description=f"{'Home' if home_scored else 'Away'} scores {pts}",
                team_id=TEST_HOME_TEAM_ID if home_scored else TEST_AWAY_TEAM_ID,
                score_value=pts,
                home_score=home_score,
                away_score=away_score,
            )
            self._recent_plays.append(play)
            self._recent_plays = self._recent_plays[-15:]

        self._state = _make_game_state(
            period, clock_str, home_score, away_score,
            recent_plays=list(self._recent_plays),
        )

    def get_summary(self) -> GameSummary:
        """Return the test game summary for the current state."""
        s = self._state
        return GameSummary(
            game_id=TEST_GAME_ID,
            status=s.status,
            period=s.period,
            clock=s.clock,
            home_team_id=TEST_HOME_TEAM_ID,
            home_team_name=TEST_HOME_NAME,
            home_team_abbreviation=TEST_HOME_ABBR,
            home_score=s.home_team.score,
            away_team_id=TEST_AWAY_TEAM_ID,
            away_team_name=TEST_AWAY_NAME,
            away_team_abbreviation=TEST_AWAY_ABBR,
            away_score=s.away_team.score,
            game_date=datetime.now(),
        )

    def get_game_state(self, game_id: str) -> GameState | None:
        """Return current state and advance by one possession for next time."""
        if game_id != TEST_GAME_ID:
            return None
        state = self._state
        if not self._game_over:
            self._advance()
        return state

    def get_team_stats(self, team_id: str) -> TeamStats:
        """Return team stats for test home/away teams."""
        if team_id == TEST_HOME_TEAM_ID:
            total = self._home_wins + self._home_losses
            home_games = max(1, total // 2)
            away_games = total - home_games
            home_w = max(0, min(home_games, round(home_games * self._home_win_pct)))
            away_w = max(0, min(away_games, self._home_wins - home_w))
            return TeamStats(
                team_id=TEST_HOME_TEAM_ID,
                team_name=TEST_HOME_NAME,
                team_abbreviation=TEST_HOME_ABBR,
                wins=self._home_wins,
                losses=self._home_losses,
                win_percentage=self._home_win_pct,
                net_rating=self._home_net_rating,
                pace=100.0,
                home_wins=home_w,
                home_losses=home_games - home_w,
                away_wins=away_w,
                away_losses=away_games - away_w,
                current_streak=random.randint(-3, 3),
            )
        if team_id == TEST_AWAY_TEAM_ID:
            total = self._away_wins + self._away_losses
            home_games = max(1, total // 2)
            away_games = total - home_games
            home_w = max(0, min(home_games, round(home_games * self._away_win_pct)))
            away_w = max(0, min(away_games, self._away_wins - home_w))
            return TeamStats(
                team_id=TEST_AWAY_TEAM_ID,
                team_name=TEST_AWAY_NAME,
                team_abbreviation=TEST_AWAY_ABBR,
                wins=self._away_wins,
                losses=self._away_losses,
                win_percentage=self._away_win_pct,
                net_rating=self._away_net_rating,
                pace=100.0,
                home_wins=home_w,
                home_losses=home_games - home_w,
                away_wins=away_w,
                away_losses=away_games - away_w,
                current_streak=random.randint(-3, 3),
            )
        return TeamStats(
            team_id=team_id,
            team_name="Unknown",
            team_abbreviation="???",
            wins=0,
            losses=0,
        )


class TestDataManager:
    """DataManager-compatible facade that returns test game data only."""

    def __init__(self, n_game_states: int = 20, scenario: str | None = None):
        """Initialize with a test game provider.

        Args:
            n_game_states: Number of game states in the time series.
            scenario: Test game scenario name (or None/"random" for random).
        """
        self._provider = TestGameProvider(n_states=n_game_states, scenario=scenario)
        self.scenario_name: str = self._provider.scenario_name

    async def get_live_games(self, date: str | None = None) -> list[GameSummary]:
        """Return a single test game summary, or empty list if game ended."""
        summary = self._provider.get_summary()
        return [summary] if summary.is_live else []

    async def get_game_state(
        self, game_id: str, force_refresh: bool = False
    ) -> GameState | None:
        """Return the next game state in the series for the test game."""
        return self._provider.get_game_state(game_id)

    async def get_team_stats(
        self, team_id: str, force_refresh: bool = False
    ) -> TeamStats | None:
        """Return fixed team stats for test teams."""
        return self._provider.get_team_stats(team_id)

    async def get_all_games(self, date: str | None = None) -> list[GameSummary]:
        """Return the single test game (same as live for test mode)."""
        summary = self._provider.get_summary()
        return [summary] if summary.is_live else []

    async def get_team_context(
        self, team_id: str, opponent_id: str | None = None
    ) -> TeamContext | None:
        """Return a TeamContext with test stats and no injuries."""
        stats = await self.get_team_stats(team_id)
        if not stats:
            return None
        return TeamContext(stats=stats)

    async def close(self) -> None:
        """No-op for test manager."""
        pass
