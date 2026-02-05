"""Test game data provider: fake GameSummary, evolving GameState, and TestDataManager."""

import random
from datetime import datetime

from ..data.models import (
    GameState,
    GameStatus,
    GameSummary,
    Period,
    TeamGameState,
    TeamStats,
)


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
) -> GameState:
    return GameState(
        game_id=TEST_GAME_ID,
        status=GameStatus.IN_PROGRESS,
        period=period,
        clock=clock,
        home_team=_make_team_game_state(
            TEST_HOME_TEAM_ID, TEST_HOME_NAME, TEST_HOME_ABBR, home_score
        ),
        away_team=_make_team_game_state(
            TEST_AWAY_TEAM_ID, TEST_AWAY_NAME, TEST_AWAY_ABBR, away_score
        ),
        recent_plays=[],
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


def _random_team_record(
    min_games: int = 45,
    max_games: int = 65,
    min_win_pct: float = 0.28,
    max_win_pct: float = 0.72,
) -> tuple[int, int, float]:
    """Return (wins, losses, win_percentage) for a random team record."""
    total = random.randint(min_games, max_games)
    win_pct = random.uniform(min_win_pct, max_win_pct)
    wins = max(0, min(total, round(total * win_pct)))
    losses = total - wins
    pct = wins / total if total else 0.0
    return wins, losses, pct


def _win_pct_to_net_rating(win_pct: float) -> float:
    """Map win percentage to approximate net rating for tier logic (elite/contender/average/etc)."""
    # Tier thresholds: elite > 5, contender > 2, average > -2, below_average > -5
    # Linear map so ~0.5 -> 0, ~0.67 -> 2, ~0.83 -> 5, ~0.33 -> -2, ~0.17 -> -5
    return (win_pct - 0.5) * 12.0


class TestGameProvider:
    """Evolving test game: one state advanced by one possession per get_game_state.

    Score changes by 0/1/2/3 points per iteration (basketball-realistic). Clock
    decrements by one possession; period advances when clock hits 0.
    Team strength (wins/losses, net_rating) is randomized at init so confidence
    and tier mismatch can vary across runs.
    """

    def __init__(self, n_states: int = 20):
        """Initialize with a single evolving state (n_states unused, for API compat)."""
        # Start mid-game: Q2 8:00, home 45 – away 42
        self._state = _make_game_state(
            Period.SECOND_QUARTER, "8:00", 45, 42
        )
        # Random team records so strength/tiers/mismatch_level vary
        self._home_wins, self._home_losses, self._home_win_pct = _random_team_record()
        self._away_wins, self._away_losses, self._away_win_pct = _random_team_record()
        self._home_net_rating = _win_pct_to_net_rating(self._home_win_pct)
        self._away_net_rating = _win_pct_to_net_rating(self._away_win_pct)

    def _advance(self) -> None:
        """Advance game by one possession: clock down, then 0/1/2/3 pts to one team."""
        period = self._state.period
        clock_sec = _clock_to_seconds(self._state.clock)
        clock_sec -= POSSESSION_SECONDS
        if clock_sec <= 0:
            period = _next_period(period)
            # Quarter length: 12 min reg, 5 min OT
            quarter_sec = 5 * 60 if period.value > 4 else 12 * 60
            clock_sec = quarter_sec + clock_sec
            if clock_sec < 0:
                clock_sec = 0
        clock_str = _seconds_to_clock(clock_sec)
        # Add 0/1/2/3 points to home or away (50/50)
        pts = random.choices([0, 1, 2, 3], weights=POINT_WEIGHTS)[0]
        home_score = self._state.home_team.score
        away_score = self._state.away_team.score
        if random.random() < 0.5:
            home_score += pts
        else:
            away_score += pts
        self._state = _make_game_state(period, clock_str, home_score, away_score)

    def get_summary(self) -> GameSummary:
        """Return the test game summary for the current state."""
        s = self._state
        return GameSummary(
            game_id=TEST_GAME_ID,
            status=GameStatus.IN_PROGRESS,
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
        self._advance()
        return state

    def get_team_stats(self, team_id: str) -> TeamStats:
        """Return team stats for test home/away teams (randomized at init)."""
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

    def __init__(self, n_game_states: int = 20):
        """Initialize with a test game provider.

        Args:
            n_game_states: Number of game states in the time series.
        """
        self._provider = TestGameProvider(n_states=n_game_states)

    async def get_live_games(self, date: str | None = None) -> list[GameSummary]:
        """Return a single test game summary."""
        return [self._provider.get_summary()]

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
        return [self._provider.get_summary()]

    async def close(self) -> None:
        """No-op for test manager."""
        pass
