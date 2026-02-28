"""Pre-game betting advisor — orchestrator for the pre-game analysis pipeline.

Coordinates:
  1. NBA data fetching (today's scheduled / pre-game games)
  2. Polymarket market discovery and price fetching
  3. Game-to-market matching
  4. Pre-game probability model estimation
  5. Formatted output to stdout

Run via:
    python -m polynba.pregame
"""

import asyncio
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from ..analysis.claude_analyzer import ClaudeAnalyzer, ClaudeAnalysisConfig
from ..data.manager import DataManager
from ..data.models import GameStatus, GameSummary, HeadToHead, TeamContext
from ..polymarket.market_discovery import MarketDiscovery
from ..polymarket.models import MarketPrices, PolymarketNBAMarket
from ..polymarket.price_fetcher import PriceFetcher
from .pregame_context import CONVICTION_PROMPT, EDGE_PROMPT, build_pregame_context
from .probability_model import PreGameEstimate, PreGameModelConfig, PreGameProbabilityModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


@dataclass
class GameAdvisory:
    """Full advisory for a single pre-game matchup."""

    game: GameSummary
    market: PolymarketNBAMarket
    prices: MarketPrices
    estimate: PreGameEstimate
    ai_analysis: Optional[str] = None


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------


class PreGameAdvisor:
    """Orchestrates the pre-game betting analysis pipeline.

    Usage::

        advisor = PreGameAdvisor(bankroll=500.0)
        advisories = asyncio.run(advisor.run())
    """

    def __init__(
        self,
        model_config: Optional[PreGameModelConfig] = None,
        bankroll: float = 500.0,
        use_claude: bool = False,
        show_hold: bool = True,
        log_level: str = "WARNING",
        scan_date: Optional[str] = None,
    ) -> None:
        """Initialise the advisor.

        Args:
            model_config: Probability model hyper-parameters.
            bankroll: Available bankroll in USDC used for Kelly sizing.
            use_claude: Whether to call Claude for additional AI analysis
                (reserved for future use; currently unused).
            show_hold: If False, HOLD recommendations are omitted from output.
            log_level: Python logging level string (DEBUG / INFO / WARNING / ERROR).
            scan_date: Date to scan in YYYYMMDD format (defaults to today).
        """
        self._model_config = model_config or PreGameModelConfig()
        self._bankroll = bankroll
        self._bankroll_is_live = False
        self._use_claude = use_claude
        self._show_hold = show_hold
        self._log_level = log_level
        self._scan_date = scan_date
        self._model = PreGameProbabilityModel(self._model_config)
        self._claude: Optional[ClaudeAnalyzer] = None
        if self._use_claude:
            self._claude = ClaudeAnalyzer(
                config=ClaudeAnalysisConfig(min_interval_seconds=5.0),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> list[GameAdvisory]:
        """Execute the full pre-game analysis pipeline.

        Returns:
            List of GameAdvisory objects sorted by absolute edge (descending),
            optionally filtered to exclude HOLD recommendations.
        """
        # Fetch live balance from Polymarket if credentials are available.
        live_balance = await self._fetch_live_balance()
        if live_balance is not None:
            self._bankroll = live_balance
            self._bankroll_is_live = True

        data_manager = DataManager()
        market_discovery = MarketDiscovery()
        price_fetcher = PriceFetcher()

        try:
            return await self._run_pipeline(
                data_manager, market_discovery, price_fetcher
            )
        finally:
            # Always release all network resources.
            await data_manager.close()
            await market_discovery.close()
            logger.debug("All clients closed.")

    async def _fetch_live_balance(self) -> Optional[float]:
        """Fetch USDC balance from Polymarket CLOB API.

        Returns the balance as a float, or None if credentials are
        unavailable or the fetch fails (in which case the CLI --bankroll
        default is used).
        """
        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
        if not private_key:
            logger.debug(
                "POLYMARKET_PRIVATE_KEY not set — using --bankroll default."
            )
            return None

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import (
                AssetType,
                BalanceAllowanceParams,
            )

            chain_id = int(os.environ.get("CHAIN_ID", "137"))
            funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS")

            client_kwargs = {
                "host": "https://clob.polymarket.com",
                "key": private_key,
                "chain_id": chain_id,
            }
            if funder:
                client_kwargs["signature_type"] = 1
                client_kwargs["funder"] = funder

            client = ClobClient(**client_kwargs)
            creds = client.create_or_derive_api_creds()
            client.set_api_creds(creds)

            result = client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            raw_balance = Decimal(result.get("balance", "0"))
            usdc_balance = raw_balance / Decimal("1000000")
            logger.info("Live Polymarket balance: $%.2f USDC", usdc_balance)
            return float(usdc_balance)

        except ImportError:
            logger.warning(
                "py-clob-client not installed — cannot fetch live balance."
            )
            return None
        except Exception as exc:
            logger.warning(
                "Failed to fetch live balance: %s — using --bankroll default.",
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        data_manager: DataManager,
        market_discovery: MarketDiscovery,
        price_fetcher: PriceFetcher,
    ) -> list[GameAdvisory]:
        """Core async pipeline: fetch, match, estimate, format."""

        # ----------------------------------------------------------------
        # 1. Fetch today's games
        # ----------------------------------------------------------------
        logger.info("Fetching today's NBA games...")
        games = await data_manager.get_all_games(date=self._scan_date)
        logger.debug("Total games fetched: %d", len(games))

        pre_game_statuses = (GameStatus.SCHEDULED, GameStatus.PREGAME)
        pregame_games = [g for g in games if g.status in pre_game_statuses]
        logger.info(
            "Pre-game / scheduled games today: %d", len(pregame_games)
        )

        if not pregame_games:
            logger.info("No pre-game NBA games found for today.")
            return []

        # ----------------------------------------------------------------
        # 2. Discover Polymarket markets
        # ----------------------------------------------------------------
        logger.info("Discovering Polymarket NBA markets...")
        markets = await market_discovery.discover_nba_markets()
        logger.info("Polymarket markets discovered: %d", len(markets))

        # ----------------------------------------------------------------
        # 3. Match games to markets by team abbreviation
        # ----------------------------------------------------------------
        matched: dict[str, tuple[GameSummary, PolymarketNBAMarket]] = {}

        for game in pregame_games:
            for market in markets:
                market_home_abbr = market_discovery.get_team_abbreviation(
                    market.home_team_name
                )
                market_away_abbr = market_discovery.get_team_abbreviation(
                    market.away_team_name
                )
                if (
                    market_home_abbr is not None
                    and market_away_abbr is not None
                    and game.home_team_abbreviation == market_home_abbr
                    and game.away_team_abbreviation == market_away_abbr
                ):
                    matched[game.game_id] = (game, market)
                    logger.debug(
                        "Matched: %s @ %s -> market %s",
                        game.away_team_abbreviation,
                        game.home_team_abbreviation,
                        market.condition_id[:20],
                    )
                    break  # Each game matched to at most one market.

        logger.info(
            "Games matched to Polymarket markets: %d / %d",
            len(matched),
            len(pregame_games),
        )

        if not matched:
            logger.warning(
                "No pre-game games could be matched to Polymarket markets."
            )
            return []

        # ----------------------------------------------------------------
        # 4. For each matched game: fetch prices, context, H2H, estimate
        # ----------------------------------------------------------------
        advisories: list[GameAdvisory] = []

        for game_id, (game, market) in matched.items():
            advisory = await self._process_game(
                game=game,
                market=market,
                data_manager=data_manager,
                price_fetcher=price_fetcher,
            )
            if advisory is not None:
                advisories.append(advisory)

        # ----------------------------------------------------------------
        # 5. Sort by absolute edge descending
        # ----------------------------------------------------------------
        advisories.sort(
            key=lambda a: abs(a.estimate.edge_percent), reverse=True
        )

        # ----------------------------------------------------------------
        # 6. Optionally filter out HOLD recommendations
        # ----------------------------------------------------------------
        if not self._show_hold:
            before = len(advisories)
            advisories = [
                a for a in advisories if a.estimate.verdict != "HOLD"
            ]
            logger.debug(
                "Filtered HOLD advisories: %d removed, %d remaining",
                before - len(advisories),
                len(advisories),
            )

        # ----------------------------------------------------------------
        # 7. Print formatted output
        # ----------------------------------------------------------------
        self._format_output(advisories)

        return advisories

    async def _process_game(
        self,
        game: GameSummary,
        market: PolymarketNBAMarket,
        data_manager: DataManager,
        price_fetcher: PriceFetcher,
    ) -> Optional[GameAdvisory]:
        """Fetch all data for one matched game and produce a GameAdvisory.

        Returns None if any critical data is missing.
        """
        home_abbr = game.home_team_abbreviation
        away_abbr = game.away_team_abbreviation
        label = f"{away_abbr} @ {home_abbr}"

        # ---- Prices ----
        logger.info("Fetching prices for %s...", label)
        prices = await price_fetcher.get_market_prices(market)
        if prices is None:
            logger.warning("No prices available for %s — skipping.", label)
            return None

        # Market's implied home-win probability (mid-price is already 0-1)
        market_home_prob = float(prices.home_mid_price)
        logger.debug(
            "%s — market home prob: %.4f, away prob: %.4f",
            label, market_home_prob, float(prices.away_mid_price),
        )

        # ---- Team contexts ----
        logger.info("Fetching team contexts for %s...", label)
        home_ctx, away_ctx = await asyncio.gather(
            data_manager.get_team_context(game.home_team_id, game.away_team_id),
            data_manager.get_team_context(game.away_team_id, game.home_team_id),
        )

        if home_ctx is None:
            logger.warning(
                "No home team context for %s (team_id=%s) — skipping.",
                label, game.home_team_id,
            )
            return None
        if away_ctx is None:
            logger.warning(
                "No away team context for %s (team_id=%s) — skipping.",
                label, game.away_team_id,
            )
            return None

        # ---- Head-to-head ----
        h2h: Optional[HeadToHead] = None
        try:
            h2h = await data_manager.get_head_to_head(
                game.home_team_id, game.away_team_id
            )
            if h2h is not None:
                logger.debug(
                    "%s — H2H: %d-%d (home-team wins first)",
                    label, h2h.team1_wins, h2h.team2_wins,
                )
        except AttributeError:
            logger.debug(
                "DataManager.get_head_to_head not available — H2H skipped for %s.",
                label,
            )
        except Exception as exc:
            logger.debug(
                "H2H fetch failed for %s: %s — continuing without H2H.",
                label, exc,
            )

        # ---- Probability estimate ----
        logger.info("Running probability model for %s...", label)
        try:
            estimate = self._model.estimate(
                home_stats=home_ctx.stats,
                away_stats=away_ctx.stats,
                market_home_prob=market_home_prob,
                bankroll=self._bankroll,
                home_context=home_ctx,
                away_context=away_ctx,
                head_to_head=h2h,
            )
        except Exception as exc:
            logger.error(
                "Probability model failed for %s: %s — skipping.",
                label, exc,
                exc_info=True,
            )
            return None

        logger.info(
            "%s — model: %.1f%%, market: %.1f%%, edge: %+.1f%%, verdict: %s",
            label,
            estimate.model_prob * 100,
            estimate.market_prob * 100,
            estimate.edge_percent,
            estimate.verdict,
        )

        # ---- Claude AI analysis ----
        ai_analysis: Optional[str] = None
        if estimate.verdict.startswith("SPECULATE") and self._claude is not None:
            ai_analysis = await self._run_conviction_analysis(
                game, estimate, home_ctx, away_ctx, h2h, market_home_prob, label,
            )
        # Future: BET verdicts could use EDGE_PROMPT here

        return GameAdvisory(
            game=game,
            market=market,
            prices=prices,
            estimate=estimate,
            ai_analysis=ai_analysis,
        )

    # ------------------------------------------------------------------
    # Claude AI conviction analysis
    # ------------------------------------------------------------------

    async def _run_conviction_analysis(
        self,
        game: GameSummary,
        estimate: PreGameEstimate,
        home_ctx: TeamContext,
        away_ctx: TeamContext,
        h2h: Optional[HeadToHead],
        market_home_prob: float,
        label: str,
    ) -> Optional[str]:
        """Run Claude conviction analysis for SPECULATE verdicts.

        Uses the CONVICTION_PROMPT to assess how confident we should be
        that the favored team wins, then scales the bet size accordingly.

        Conviction scaling:
            confidence >= 8  → 1.25x base Kelly (strong conviction)
            confidence  7    → 1.0x  base Kelly (solid)
            confidence  6    → 0.75x base Kelly (moderate)
            confidence  5    → 0.5x  base Kelly (marginal, keep small)
            confidence <  5  → downgrade to HOLD (upset risk too high)

        Returns:
            Formatted AI analysis string for display, or None.
        """
        assert self._claude is not None

        logger.info("Running conviction analysis for SPECULATE: %s...", label)
        base_kelly = estimate.kelly_fraction
        base_bet = estimate.suggested_bet_usdc

        try:
            game_ctx_str, market_ctx_str, quant_str = build_pregame_context(
                game=game,
                home_ctx=home_ctx,
                away_ctx=away_ctx,
                h2h=h2h,
                estimate=estimate,
                market_home_price=market_home_prob,
                bankroll=self._bankroll,
            )
            claude_result = await self._claude.analyze(
                game_context=game_ctx_str,
                market_context=market_ctx_str,
                quant_analysis=quant_str,
                game_id=game.game_id,
                force=True,
                prompt_template=CONVICTION_PROMPT,
            )
        except Exception as exc:
            logger.warning(
                "Conviction analysis failed for %s: %s — keeping base sizing.",
                label, exc,
            )
            return None

        if claude_result is None:
            return None

        confidence = claude_result.confidence
        assessment = claude_result.market_assessment  # conviction level

        logger.info(
            "Conviction for %s: %s (confidence %d/10)",
            label, assessment, confidence,
        )

        # ---- Conviction scaling ----
        if confidence < 5 or assessment == "overvalued":
            # Weak conviction → downgrade to HOLD
            logger.info(
                "Conviction too low → HOLD for %s (confidence=%d, assessment=%s)",
                label, confidence, assessment,
            )
            estimate.verdict = "HOLD"
            estimate.kelly_fraction = 0.0
            estimate.suggested_bet_usdc = 0.0
            return None

        # Scale factor based on confidence
        # confidence 5 → 0.5x, 6 → 0.75x, 7 → 1.0x, 8 → 1.25x, 9+ → 1.5x
        scale = 0.25 * (confidence - 3)
        # Boost further if Claude says conviction is strong
        if assessment == "undervalued":
            scale *= 1.2

        scaled_kelly = base_kelly * scale
        # Respect max Kelly cap
        max_kelly = self._model_config.max_kelly_pct / 100.0
        scaled_kelly = min(scaled_kelly, max_kelly)
        scaled_bet = scaled_kelly * self._bankroll

        logger.info(
            "Conviction sizing for %s: base Kelly %.2f%% × %.2f = %.2f%% → $%.2f",
            label, base_kelly * 100, scale, scaled_kelly * 100, scaled_bet,
        )

        estimate.kelly_fraction = scaled_kelly
        estimate.suggested_bet_usdc = scaled_bet

        # ---- Build display summary ----
        conviction_label = {
            "undervalued": "STRONG",
            "fair": "SOLID",
            "overvalued": "WEAK",
        }.get(assessment, assessment)

        parts: list[str] = [
            f"Conviction: {conviction_label} (confidence {confidence}/10, "
            f"scale {scale:.2f}x → ${scaled_bet:.2f})",
        ]
        if claude_result.key_factors:
            for kf in claude_result.key_factors:
                parts.append(f"  + {kf}")
        if claude_result.risk_flags:
            for rf in claude_result.risk_flags:
                parts.append(f"  ! {rf}")
        if claude_result.reasoning:
            parts.append(f"  → {claude_result.reasoning}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Output formatting
    # ------------------------------------------------------------------

    def _format_output(self, advisories: list[GameAdvisory]) -> None:
        """Print a formatted advisory table and per-game details to stdout."""
        if self._scan_date:
            today_str = datetime.strptime(self._scan_date, "%Y%m%d").strftime("%Y-%m-%d")
        else:
            today_str = date.today().strftime("%Y-%m-%d")

        # Header
        print()
        print("=" * 63)
        print(f"  PRE-GAME BETTING ADVISOR -- {today_str}")
        source = "LIVE" if self._bankroll_is_live else "default"
        print(f"  Balance: ${self._bankroll:.2f} USDC ({source})")
        print("=" * 63)

        if not advisories:
            print()
            print("  No pre-game opportunities found today.")
            print()
            return

        # ---- Summary table ----
        print()
        header = (
            f"{'#':>2}  {'Game':<18} {'Model':>6}  {'Market':>6}  "
            f"{'Edge':>6}  {'Kelly':>6}  {'Bet':>6}  {'Conf':>5}  {'Verdict'}"
        )
        print(header)
        print("-" * 78)

        for idx, adv in enumerate(advisories, start=1):
            game = adv.game
            est = adv.estimate
            game_label = f"{game.away_team_abbreviation} @ {game.home_team_abbreviation}"

            # Edge: always show from the home perspective for consistency.
            edge_sign = f"{est.edge_percent:+.1f}%"
            kelly_pct = f"{est.kelly_fraction:.1%}"
            bet_str = f"${est.suggested_bet_usdc:.0f}"
            conf_str = f"{est.confidence}/10"
            model_str = f"{est.model_prob:.1%}"
            market_str = f"{est.market_prob:.1%}"

            print(
                f"{idx:>2}  {game_label:<18} {model_str:>6}  {market_str:>6}  "
                f"{edge_sign:>6}  {kelly_pct:>6}  {bet_str:>6}  {conf_str:>5}  "
                f"{est.verdict}"
            )

        print()

        # ---- Per-game detail blocks ----
        for adv in advisories:
            game = adv.game
            est = adv.estimate
            away_abbr = game.away_team_abbreviation
            home_abbr = game.home_team_abbreviation

            # Which team is the suggested bet on?
            if est.bet_side == "home":
                bet_side_team = home_abbr
            else:
                bet_side_team = away_abbr

            print(f"--- Detailed: {away_abbr} @ {home_abbr} ---")
            print(
                f"  Model: {est.model_prob:.1%} | "
                f"Market: {est.market_prob:.1%} | "
                f"Edge: {est.edge_percent:+.1%}"
            )
            print(
                f"  Kelly: {est.kelly_fraction:.1%} | "
                f"Bet: ${est.suggested_bet_usdc:.2f} on {bet_side_team} | "
                f"Confidence: {est.confidence}/10"
            )
            print()

            if est.factors_summary:
                print("  Factors:")
                for factor_line in est.factors_summary:
                    print(f"    {factor_line}")
            print()

            # Claude AI analysis block (for SPECULATE verdicts)
            if adv.ai_analysis:
                print("  AI Analysis:")
                for ai_line in adv.ai_analysis.split("\n"):
                    print(f"    {ai_line}")
                print()

            # Execution command for BET and SPECULATE recommendations
            if est.verdict.startswith("BET") or est.verdict.startswith("SPECULATE"):
                cmd = self._build_execute_command(adv)
                if cmd:
                    print(f"  Execute: {cmd}")
                    print()

    def _build_execute_command(self, adv: GameAdvisory) -> str | None:
        """Build the CLI command string to execute a BET advisory."""
        est = adv.estimate
        market = adv.market
        prices = adv.prices

        # Pick the token ID and best ask for the bet side
        if est.bet_side == "home":
            token_id = market.home_token_id
            best_ask = prices.home_best_ask
        else:
            token_id = market.away_token_id
            best_ask = prices.away_best_ask

        if best_ask is None:
            return None

        price = float(best_ask)
        size_usdc = est.suggested_bet_usdc

        return (
            f"python -m polynba.pregame.execute"
            f" --token-id {token_id}"
            f" --market-id {market.condition_id}"
            f" --side buy"
            f" --size {size_usdc:.2f}"
            f" --price {price}"
        )
