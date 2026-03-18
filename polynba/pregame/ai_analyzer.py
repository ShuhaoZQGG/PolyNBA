"""Comprehensive AI pregame analysis using Claude API.

Provides structured, web-renderable analysis for BET and SPECULATE games
using the Anthropic Python SDK with structured output (tool calling).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, Field

from ..analysis.claude_analyzer import ClaudeAnalyzer, ClaudeAnalysisConfig
from .pregame_context import build_comprehensive_context

if TYPE_CHECKING:
    from .advisor import GameAdvisory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured response models
# ---------------------------------------------------------------------------


class MatchupInsight(BaseModel):
    """A single matchup insight."""

    category: str = Field(description="Category: pace, defense, shooting, rebounding, etc.")
    description: str = Field(description="Brief description of the matchup dynamic")
    advantage: Literal["home", "away", "even"] = Field(
        description="Which team has the advantage"
    )


class InjuryImpact(BaseModel):
    """Impact assessment for a team's injuries."""

    team: str = Field(description="Team abbreviation")
    severity: Literal["critical", "significant", "minor", "none"] = Field(
        description="How much the injuries affect the team"
    )
    description: str = Field(description="Brief description of injury impact")


class PregameAIAnalysis(BaseModel):
    """Comprehensive AI analysis for a pregame matchup — web-renderable."""

    headline: str = Field(
        description="Short headline, e.g. 'Celtics should dominate depleted Wizards'"
    )
    narrative: str = Field(
        description="2-3 sentence analysis of the game"
    )
    verdict_rationale: str = Field(
        description="Why the verdict (BET/SPECULATE) is justified"
    )
    matchup_insights: list[MatchupInsight] = Field(
        description="Key matchup dynamics (2-4 insights)"
    )
    injury_impact: list[InjuryImpact] = Field(
        description="Injury impact for each team"
    )
    key_factors_for: list[str] = Field(
        description="Factors supporting the bet (2-4 bullet points)"
    )
    key_factors_against: list[str] = Field(
        description="Risk factors against the bet (2-4 bullet points)"
    )
    confidence_rating: int = Field(
        ge=1, le=10, description="Overall confidence 1-10"
    )
    market_efficiency: Literal["inefficient", "fair", "efficient"] = Field(
        description="Whether the market is pricing this game correctly"
    )
    upset_risk: Literal["very_low", "low", "moderate", "high"] = Field(
        description="Risk of an upset outcome"
    )
    game_script: str = Field(
        description="Brief prediction of how the game plays out (2-3 sentences)"
    )


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

PREGAME_ANALYSIS_PROMPT = """You are an expert NBA analyst providing pre-game betting analysis for Polymarket.

{context}

=== ANALYSIS TYPE ===
{analysis_framing}

Provide a comprehensive analysis of this game. Be specific about matchup dynamics,
injury effects, and why the market may or may not be pricing this correctly.

Your analysis should be actionable — a bettor should understand exactly why this
is or isn't a good bet after reading your analysis.

Use the submit_pregame_analysis tool to return your structured analysis."""


EDGE_FRAMING = """This is an EDGE analysis. Our model found a potential market inefficiency.
The model probability diverges from the market price, suggesting mispricing.
Focus on whether the edge is real — is the market truly wrong here?
Evaluate the specific factors that could cause this mispricing."""

CONVICTION_FRAMING = """This is a CONVICTION analysis. Both model and market agree this team is favored,
but we want to assess how confident we should be in holding to resolution.
Focus on whether the favorite can reliably close out the game.
Evaluate upset risks and factors that could derail the expected outcome."""


# ---------------------------------------------------------------------------
# Analyzer class
# ---------------------------------------------------------------------------


class PregameAIAnalyzer:
    """Runs comprehensive AI analysis for actionable pregame advisories."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 2048,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._claude = ClaudeAnalyzer(
            config=ClaudeAnalysisConfig(min_interval_seconds=1.0),
        )
        self._semaphore = asyncio.Semaphore(3)

    async def analyze_games(self, advisories: list[GameAdvisory]) -> None:
        """Batch analyze all actionable games, populating advisory.ai_detail in-place."""
        tasks = []
        for adv in advisories:
            if self._should_analyze(adv):
                tasks.append(self._analyze_single(adv))

        if not tasks:
            logger.info("No games eligible for AI analysis")
            return

        logger.info("Running AI analysis for %d games...", len(tasks))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("AI analysis task failed: %s", result)

    def _should_analyze(self, advisory: GameAdvisory) -> bool:
        """Returns True for BET and SPECULATE verdicts."""
        verdict = advisory.estimate.verdict
        return verdict.startswith("BET") or verdict.startswith("SPECULATE")

    async def _analyze_single(self, advisory: GameAdvisory) -> None:
        """Analyze a single game and populate advisory.ai_detail."""
        game = advisory.game
        label = f"{game.away_team_abbreviation} @ {game.home_team_abbreviation}"

        async with self._semaphore:
            logger.info("AI analyzing %s...", label)
            try:
                prompt = self._build_prompt(advisory)
                result = await self._claude.analyze_with_schema(
                    prompt=prompt,
                    response_model=PregameAIAnalysis,
                    tool_name="submit_pregame_analysis",
                    game_id=game.game_id,
                    cache_key=f"{game.game_id}:pregame_ai",
                    model_override=self._model,
                    max_tokens_override=self._max_tokens,
                    force=True,
                )

                if result is not None:
                    advisory.ai_detail = result  # type: ignore[attr-defined]
                    logger.info(
                        "AI analysis for %s: %s (confidence %d/10)",
                        label, result.headline, result.confidence_rating,
                    )
                else:
                    logger.warning("AI analysis returned None for %s", label)

            except Exception as e:
                logger.error("AI analysis failed for %s: %s", label, e)

    def _build_prompt(self, advisory: GameAdvisory) -> str:
        """Build the comprehensive analysis prompt from advisory data."""
        est = advisory.estimate

        # Build context from stored data
        context = build_comprehensive_context(
            game=advisory.game,
            home_ctx=advisory.home_context,
            away_ctx=advisory.away_context,
            h2h=advisory.head_to_head,
            estimate=est,
            market_home_price=est.market_prob,
            bankroll=est.suggested_bet_usdc / est.kelly_fraction if est.kelly_fraction > 0 else None,
        )

        # Select framing based on verdict
        if est.verdict.startswith("SPECULATE"):
            framing = CONVICTION_FRAMING
        else:
            framing = EDGE_FRAMING

        return PREGAME_ANALYSIS_PROMPT.format(
            context=context,
            analysis_framing=framing,
        )

    @property
    def usage_stats(self) -> dict:
        """Get usage statistics from the underlying Claude analyzer."""
        return self._claude.usage_stats
