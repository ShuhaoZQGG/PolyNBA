"""Market service: game-to-market matching and price enrichment.

Replicates the matching logic from PreGameAdvisor._run_pipeline so the
web layer can build the markets list without running the full analysis
pipeline.
"""

from __future__ import annotations

import logging
from typing import Optional

from polynba.data.manager import DataManager
from polynba.data.models import GameStatus, GameSummary
from polynba.polymarket.market_discovery import MarketDiscovery
from polynba.polymarket.models import MarketPrices, PolymarketNBAMarket
from polynba.polymarket.price_fetcher import PriceFetcher

logger = logging.getLogger(__name__)

# Normalisation table for non-standard ESPN abbreviations (mirrors advisor.py).
_ESPN_ABBR_NORMALISE: dict[str, str] = {
    "GS": "GSW",
    "WSH": "WAS",
    "NO": "NOP",
    "UTAH": "UTA",
    "NY": "NYK",
    "SA": "SAS",
    "PHO": "PHX",
    "BKLYN": "BKN",
    "BK": "BKN",
}


def _normalise_espn_abbr(abbr: str) -> str:
    return _ESPN_ABBR_NORMALISE.get(abbr, abbr)


async def get_matched_markets(
    data_manager: DataManager,
    market_discovery: MarketDiscovery,
    price_fetcher: PriceFetcher,
    date: Optional[str] = None,
) -> list[tuple[GameSummary, PolymarketNBAMarket, Optional[MarketPrices]]]:
    """Fetch games, discover markets, match them, and return prices.

    Returns a list of (game, market, prices) triples for every game that
    could be matched to a Polymarket market.  ``prices`` may be None when
    the CLOB API returns no data for a market.

    Args:
        data_manager: Shared DataManager singleton.
        market_discovery: Shared MarketDiscovery singleton.
        price_fetcher: Shared PriceFetcher singleton.
        date: Optional date string in YYYYMMDD format (defaults to today).

    Returns:
        List of (GameSummary, PolymarketNBAMarket, Optional[MarketPrices]).
    """
    # 1. Fetch all games for the date (all statuses — let the caller filter)
    all_games = await data_manager.get_all_games(date=date)
    logger.debug("Total games for date %s: %d", date or "today", len(all_games))

    pre_game_statuses = (GameStatus.SCHEDULED, GameStatus.PREGAME)
    pregame_games = [g for g in all_games if g.status in pre_game_statuses]
    logger.info("Pre-game / scheduled games: %d", len(pregame_games))

    if not pregame_games:
        return []

    # 2. Discover Polymarket NBA markets
    markets = await market_discovery.discover_nba_markets()
    logger.info("Polymarket markets discovered: %d", len(markets))

    if not markets:
        return []

    # 3. Match games to markets (exact abbreviation match — same logic as advisor)
    matched: list[tuple[GameSummary, PolymarketNBAMarket]] = []

    for game in pregame_games:
        for market in markets:
            market_home_abbr = market_discovery.get_team_abbreviation(market.home_team_name)
            market_away_abbr = market_discovery.get_team_abbreviation(market.away_team_name)
            game_home = _normalise_espn_abbr(game.home_team_abbreviation)
            game_away = _normalise_espn_abbr(game.away_team_abbreviation)

            if (
                market_home_abbr is not None
                and market_away_abbr is not None
                and game_home == market_home_abbr
                and game_away == market_away_abbr
            ):
                matched.append((game, market))
                logger.debug(
                    "Matched: %s @ %s -> market %s",
                    game.away_team_abbreviation,
                    game.home_team_abbreviation,
                    market.condition_id[:20],
                )
                break

    logger.info(
        "Games matched to Polymarket markets: %d / %d",
        len(matched),
        len(pregame_games),
    )

    if not matched:
        return []

    # 4. Batch-fetch prices for all matched markets
    markets_to_price = [m for _, m in matched]
    prices_by_condition: dict[str, MarketPrices] = {}
    if markets_to_price:
        try:
            prices_by_condition = await price_fetcher.get_prices_batch(markets_to_price)
        except Exception as exc:
            logger.warning("Batch price fetch failed: %s — prices will be None", exc)

    # 5. Assemble results
    result: list[tuple[GameSummary, PolymarketNBAMarket, Optional[MarketPrices]]] = []
    for game, market in matched:
        prices = prices_by_condition.get(market.condition_id)
        result.append((game, market, prices))

    return result


async def get_market_for_game(
    game_id: str,
    data_manager: DataManager,
    market_discovery: MarketDiscovery,
    price_fetcher: PriceFetcher,
    date: Optional[str] = None,
) -> Optional[tuple[GameSummary, PolymarketNBAMarket, Optional[MarketPrices]]]:
    """Return the (game, market, prices) triple for a single game_id.

    Returns None when the game cannot be found or matched to a market.
    """
    matched = await get_matched_markets(data_manager, market_discovery, price_fetcher, date)
    for game, market, prices in matched:
        if game.game_id == game_id:
            return game, market, prices
    return None
