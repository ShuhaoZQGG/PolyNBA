"""Enumerations for NBA game data."""

from enum import Enum, auto


class GameStatus(str, Enum):
    """Status of an NBA game."""

    SCHEDULED = "scheduled"
    PREGAME = "pregame"
    IN_PROGRESS = "in_progress"
    HALFTIME = "halftime"
    END_OF_PERIOD = "end_of_period"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELED = "canceled"
    DELAYED = "delayed"

    @classmethod
    def from_espn_status(cls, status_type: int | str, status_state: str) -> "GameStatus":
        """Convert ESPN status type and state to GameStatus."""
        state_lower = status_state.lower()

        # ESPN API returns status_type as string, convert to int
        status_type = int(status_type)

        if status_type == 1:
            return cls.SCHEDULED
        elif status_type == 2:
            if state_lower == "in":
                return cls.IN_PROGRESS
            elif state_lower == "halftime":
                return cls.HALFTIME
            elif state_lower == "end":
                return cls.END_OF_PERIOD
            return cls.IN_PROGRESS
        elif status_type == 3:
            return cls.FINAL
        elif status_type == 4:
            return cls.POSTPONED
        elif status_type == 5:
            return cls.CANCELED
        elif status_type == 6:
            return cls.DELAYED

        return cls.SCHEDULED


class Period(int, Enum):
    """NBA game periods."""

    FIRST_QUARTER = 1
    SECOND_QUARTER = 2
    THIRD_QUARTER = 3
    FOURTH_QUARTER = 4
    OVERTIME_1 = 5
    OVERTIME_2 = 6
    OVERTIME_3 = 7
    OVERTIME_4 = 8

    @property
    def is_overtime(self) -> bool:
        """Check if this is an overtime period."""
        return self.value > 4

    @property
    def display_name(self) -> str:
        """Get display name for the period."""
        if self.value <= 4:
            return f"Q{self.value}"
        return f"OT{self.value - 4}"

    @classmethod
    def from_int(cls, value: int) -> "Period":
        """Convert integer to Period, capping at OT4."""
        if value <= 0:
            return cls.FIRST_QUARTER
        if value > 8:
            return cls.OVERTIME_4
        return cls(value)


class EventType(str, Enum):
    """Types of play events in an NBA game."""

    # Scoring
    FIELD_GOAL_MADE = "field_goal_made"
    FIELD_GOAL_MISSED = "field_goal_missed"
    THREE_POINTER_MADE = "three_pointer_made"
    THREE_POINTER_MISSED = "three_pointer_missed"
    FREE_THROW_MADE = "free_throw_made"
    FREE_THROW_MISSED = "free_throw_missed"

    # Possession
    REBOUND = "rebound"
    TURNOVER = "turnover"
    STEAL = "steal"

    # Fouls
    PERSONAL_FOUL = "personal_foul"
    TECHNICAL_FOUL = "technical_foul"
    FLAGRANT_FOUL = "flagrant_foul"

    # Game flow
    TIMEOUT = "timeout"
    SUBSTITUTION = "substitution"
    JUMP_BALL = "jump_ball"

    # Other
    BLOCK = "block"
    ASSIST = "assist"
    VIOLATION = "violation"
    EJECTION = "ejection"
    PERIOD_START = "period_start"
    PERIOD_END = "period_end"
    UNKNOWN = "unknown"

    @classmethod
    def from_espn_type(cls, type_id: int, text: str = "") -> "EventType":
        """Convert ESPN event type ID to EventType."""
        text_lower = text.lower()

        # Check for scoring events
        if "three point" in text_lower or "3pt" in text_lower:
            if "made" in text_lower or "makes" in text_lower:
                return cls.THREE_POINTER_MADE
            return cls.THREE_POINTER_MISSED

        if "free throw" in text_lower:
            if "made" in text_lower or "makes" in text_lower:
                return cls.FREE_THROW_MADE
            return cls.FREE_THROW_MISSED

        if "made" in text_lower or "makes" in text_lower:
            return cls.FIELD_GOAL_MADE
        if "missed" in text_lower or "misses" in text_lower:
            return cls.FIELD_GOAL_MISSED

        # Other events
        if "rebound" in text_lower:
            return cls.REBOUND
        if "turnover" in text_lower:
            return cls.TURNOVER
        if "steal" in text_lower:
            return cls.STEAL
        if "block" in text_lower:
            return cls.BLOCK
        if "assist" in text_lower:
            return cls.ASSIST
        if "foul" in text_lower:
            if "technical" in text_lower:
                return cls.TECHNICAL_FOUL
            if "flagrant" in text_lower:
                return cls.FLAGRANT_FOUL
            return cls.PERSONAL_FOUL
        if "timeout" in text_lower:
            return cls.TIMEOUT
        if "substitution" in text_lower:
            return cls.SUBSTITUTION
        if "jump ball" in text_lower:
            return cls.JUMP_BALL
        if "violation" in text_lower:
            return cls.VIOLATION
        if "ejected" in text_lower:
            return cls.EJECTION

        return cls.UNKNOWN


class TeamSide(str, Enum):
    """Home or away team designation."""

    HOME = "home"
    AWAY = "away"


class TradeSide(str, Enum):
    """Trading side for market orders."""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """Status of a trading order."""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class MarketOutcome(str, Enum):
    """Possible market outcomes for NBA games."""

    HOME_WIN = "home_win"
    AWAY_WIN = "away_win"
    OVER = "over"
    UNDER = "under"
