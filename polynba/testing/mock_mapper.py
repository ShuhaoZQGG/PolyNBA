"""Mock market mapper that returns a synthetic Polymarket market for the test game."""

from decimal import Decimal

from ..data.models import GameState
from ..polymarket.models import MarketMapping, PolymarketNBAMarket

from .test_game_provider import (
    TEST_AWAY_NAME,
    TEST_GAME_ID,
    TEST_HOME_NAME,
)


TEST_CONDITION_ID = "test_market"
TEST_QUESTION_ID = "test_question"
TEST_SLUG = "test-game-home-vs-away"
TEST_HOME_TOKEN_ID = f"{TEST_GAME_ID}_home_token"
TEST_AWAY_TOKEN_ID = f"{TEST_GAME_ID}_away_token"


def _synthetic_market() -> PolymarketNBAMarket:
    """Build the single synthetic Polymarket market for the test game."""
    return PolymarketNBAMarket(
        condition_id=TEST_CONDITION_ID,
        question_id=TEST_QUESTION_ID,
        slug=TEST_SLUG,
        question=f"Will {TEST_HOME_NAME} beat {TEST_AWAY_NAME}?",
        home_token_id=TEST_HOME_TOKEN_ID,
        away_token_id=TEST_AWAY_TOKEN_ID,
        home_team_name=TEST_HOME_NAME,
        away_team_name=TEST_AWAY_NAME,
        active=True,
        closed=False,
        end_date=None,
        liquidity=Decimal("10000"),
        volume=Decimal("0"),
    )


class TestMarketMapper:
    """Returns a fake MarketMapping for the test game so the bot uses the time-series price fetcher."""

    def __init__(self) -> None:
        self._market = _synthetic_market()

    async def get_market_for_game(
        self,
        game_state: GameState,
    ) -> MarketMapping | None:
        """Return the synthetic market mapping if this is the test game."""
        if game_state.game_id != TEST_GAME_ID:
            return None
        return MarketMapping(
            espn_game_id=TEST_GAME_ID,
            espn_home_team_id=game_state.home_team.team_id,
            espn_away_team_id=game_state.away_team.team_id,
            polymarket_market=self._market,
            confidence=1.0,
            matched_home_team=TEST_HOME_NAME,
            matched_away_team=TEST_AWAY_NAME,
            match_method="exact",
        )
