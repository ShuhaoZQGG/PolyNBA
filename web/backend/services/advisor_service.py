"""Advisor service: wraps PreGameAdvisor to run analysis with injected deps.

Instead of letting PreGameAdvisor create its own DataManager / MarketDiscovery /
PriceFetcher (which is what ``advisor.run()`` does), we inject the shared
singletons so we avoid redundant connections and benefit from their internal
caches.
"""

from __future__ import annotations

import logging
from typing import Optional

from polynba.data.manager import DataManager
from polynba.data.models import GameSummary
from polynba.polymarket.market_discovery import MarketDiscovery
from polynba.polymarket.models import MarketPrices, PolymarketNBAMarket
from polynba.polymarket.price_fetcher import PriceFetcher
from polynba.pregame.advisor import GameAdvisory, PreGameAdvisor
from polynba.pregame.ai_analyzer import PregameAIAnalyzer
from polynba.pregame.probability_model import PreGameModelConfig

from ..config import AI_ANALYSIS_ENABLED, AI_MODEL, DEFAULT_BANKROLL, DEFAULT_SCAN_DATE
from ..services.cache import matched_markets_cache
from ..services.market_service import get_matched_markets

logger = logging.getLogger(__name__)


def _make_advisor(bankroll: float, scan_date: Optional[str]) -> PreGameAdvisor:
    """Construct a PreGameAdvisor with sensible web defaults.

    AI analysis is intentionally left *off* here because the web layer
    triggers it separately through the PregameAIAnalyzer so that it can be
    cached and re-used across requests.
    """
    return PreGameAdvisor(
        model_config=PreGameModelConfig(),
        bankroll=bankroll,
        use_claude=False,
        show_hold=True,
        log_level="WARNING",
        scan_date=scan_date or DEFAULT_SCAN_DATE,
        ai_analysis=False,  # We handle AI analysis ourselves below
    )


async def run_all_analysis(
    data_manager: DataManager,
    market_discovery: MarketDiscovery,
    price_fetcher: PriceFetcher,
    bankroll: float = DEFAULT_BANKROLL,
    scan_date: Optional[str] = None,
    with_ai: bool = True,
    force: bool = False,
) -> list[GameAdvisory]:
    """Run the full pre-game analysis pipeline and return advisories.

    Reuses the cached matched-markets data (games + markets + prices) from
    the markets endpoint cache to avoid redundant ESPN / Polymarket API calls.
    Only the analysis-specific work (team context, probability model, trading
    plan) runs fresh.

    Args:
        data_manager: Shared DataManager instance.
        market_discovery: Shared MarketDiscovery instance.
        price_fetcher: Shared PriceFetcher instance.
        bankroll: Bankroll in USDC for Kelly sizing.
        scan_date: Optional YYYYMMDD date string (defaults to today).
        with_ai: Whether to run PregameAIAnalyzer after the quant pipeline.
        force: Bust the matched-markets cache and re-fetch from APIs.

    Returns:
        Sorted list of GameAdvisory objects (descending by |edge_percent|).
    """
    advisor = _make_advisor(bankroll, scan_date)

    # Reuse the matched-markets cache (games + markets + batch prices) so we
    # don't duplicate the ESPN / Polymarket API calls that the markets endpoint
    # already made.
    cache_key = f"markets:{scan_date or 'today'}"
    if force:
        matched_markets_cache.invalidate(cache_key)

    matched: list[tuple[GameSummary, PolymarketNBAMarket, Optional[MarketPrices]]] = (
        await matched_markets_cache.get_or_fetch(
            cache_key,
            lambda: get_matched_markets(
                data_manager=data_manager,
                market_discovery=market_discovery,
                price_fetcher=price_fetcher,
                date=scan_date,
            ),
        )
    )

    if not matched:
        logger.info("No matched markets found — nothing to analyse.")
        return []

    logger.info("Running analysis for %d matched games (cached markets)...", len(matched))

    advisories: list[GameAdvisory] = []
    for game, market, _prices in matched:
        # _process_game fetches team context, H2H, and runs probability model.
        # It also fetches fresh prices per-game (needed for spread/depth in
        # trading plan), but this is a single lightweight CLOB call.
        game_advisories = await advisor._process_game(
            game=game,
            market=market,
            data_manager=data_manager,
            price_fetcher=price_fetcher,
        )
        advisories.extend(game_advisories)

    advisories.sort(key=lambda a: abs(a.estimate.edge_percent), reverse=True)
    logger.info("Pipeline produced %d advisories.", len(advisories))

    # Optional AI enrichment pass
    if with_ai and AI_ANALYSIS_ENABLED and advisories:
        actionable = [
            a for a in advisories
            if a.estimate.verdict.startswith("BET") or a.estimate.verdict.startswith("SPECULATE")
        ]
        if actionable:
            logger.info("Running AI analysis for %d actionable games...", len(actionable))
            ai_analyzer = PregameAIAnalyzer(model=AI_MODEL)
            await ai_analyzer.analyze_games(actionable)

    return advisories


async def run_single_game_analysis(
    game,
    market: PolymarketNBAMarket,
    data_manager: DataManager,
    price_fetcher: PriceFetcher,
    bankroll: float = DEFAULT_BANKROLL,
    scan_date: Optional[str] = None,
    with_ai: bool = True,
) -> list[GameAdvisory]:
    """Run analysis for a single (game, market) pair.

    Returns a list of 0–2 GameAdvisory objects (primary + optional conviction
    RESOLUTION advisory for the opposite side).

    Args:
        game: GameSummary dataclass.
        market: Matched PolymarketNBAMarket dataclass.
        data_manager: Shared DataManager instance.
        price_fetcher: Shared PriceFetcher instance.
        bankroll: Bankroll in USDC.
        scan_date: Optional YYYYMMDD date string.
        with_ai: Whether to run AI analysis on the result.

    Returns:
        List of GameAdvisory objects.
    """
    advisor = _make_advisor(bankroll, scan_date)

    advisories = await advisor._process_game(
        game=game,
        market=market,
        data_manager=data_manager,
        price_fetcher=price_fetcher,
    )

    if not advisories:
        return []

    # Optional AI enrichment
    if with_ai and AI_ANALYSIS_ENABLED:
        actionable = [
            a for a in advisories
            if a.estimate.verdict.startswith("BET") or a.estimate.verdict.startswith("SPECULATE")
        ]
        if actionable:
            ai_analyzer = PregameAIAnalyzer(model=AI_MODEL)
            await ai_analyzer.analyze_games(actionable)

    return advisories
