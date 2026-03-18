"""Claude API integration for AI-powered analysis."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ClaudeAnalysisResponse(BaseModel):
    """Structured response from Claude analysis."""

    market_assessment: Literal["undervalued", "fair", "overvalued"]
    confidence: int = Field(ge=1, le=10, description="Confidence level 1-10")
    sentiment_adjustment: int = Field(
        ge=-50, le=50, description="Sentiment adjustment -50 to +50"
    )
    context_adjustment: int = Field(
        ge=-50, le=50, description="Context adjustment -50 to +50"
    )
    key_factors: list[str] = Field(description="Key factors influencing assessment")
    risk_flags: list[str] = Field(description="Risk factors to consider")
    reasoning: str = Field(description="Brief reasoning for assessment")


@dataclass
class ClaudeAnalysisConfig:
    """Configuration for Claude analyzer."""

    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 1024
    temperature: float = 0.3
    min_interval_seconds: float = 120.0  # Minimum seconds between analyses
    daily_budget_usd: float = 10.0
    cost_per_1k_input_tokens: float = 0.003
    cost_per_1k_output_tokens: float = 0.015


@dataclass
class AnalysisCache:
    """Cache for Claude analyses."""

    game_id: str
    analysis: ClaudeAnalysisResponse
    timestamp: datetime
    context_hash: str


@dataclass
class UsageStats:
    """Track API usage and costs."""

    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    requests_today: int = 0
    cost_today_usd: float = 0.0
    last_reset_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))


class ClaudeAnalyzer:
    """Integrates Claude for AI-powered game analysis.

    Uses structured output for reliable parsing and implements
    caching and rate limiting to manage costs.
    """

    ANALYSIS_PROMPT = """Analyze this NBA game situation for trading on Polymarket.

GAME STATE:
{game_context}

MARKET INFORMATION:
{market_context}

QUANTITATIVE ANALYSIS:
{quant_analysis}

Based on this information, provide your assessment of whether the current market price represents good value.

Consider:
1. Does the current score/time justify the market odds?
2. Are there momentum factors the market might be slow to price?
3. Any key matchup or situational factors?
4. What are the main risks to this trade?

Provide your analysis in the structured format."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[ClaudeAnalysisConfig] = None,
    ):
        """Initialize Claude analyzer.

        Args:
            api_key: Anthropic API key. If None, uses ANTHROPIC_API_KEY env var.
            config: Analysis configuration
        """
        self._api_key = api_key
        self._config = config or ClaudeAnalysisConfig()
        self._client = None

        # Caching
        self._cache: dict[str, AnalysisCache] = {}
        self._cache_ttl = timedelta(minutes=5)

        # Rate limiting
        self._last_analysis_time: Optional[datetime] = None

        # Usage tracking
        self._usage = UsageStats()

    async def _get_client(self):
        """Get or create Anthropic client."""
        if self._client is None:
            try:
                import anthropic

                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package required. Install with: pip install anthropic"
                )
        return self._client

    def _check_rate_limit(self) -> bool:
        """Check if we can make a request (rate limiting)."""
        if self._last_analysis_time is None:
            return True

        elapsed = (datetime.now() - self._last_analysis_time).total_seconds()
        return elapsed >= self._config.min_interval_seconds

    def _check_budget(self) -> bool:
        """Check if within daily budget."""
        # Reset daily counters if new day
        today = datetime.now().strftime("%Y-%m-%d")
        if self._usage.last_reset_date != today:
            self._usage.requests_today = 0
            self._usage.cost_today_usd = 0.0
            self._usage.last_reset_date = today

        return self._usage.cost_today_usd < self._config.daily_budget_usd

    def _get_cached(self, game_id: str, context_hash: str) -> Optional[ClaudeAnalysisResponse]:
        """Get cached analysis if available and fresh."""
        cached = self._cache.get(game_id)

        if cached is None:
            return None

        # Check if cache is still valid
        if datetime.now() - cached.timestamp > self._cache_ttl:
            return None

        # Check if context has changed significantly
        if cached.context_hash != context_hash:
            return None

        logger.debug(f"Using cached analysis for game {game_id}")
        return cached.analysis

    def _update_cache(
        self,
        game_id: str,
        analysis: ClaudeAnalysisResponse,
        context_hash: str,
    ) -> None:
        """Update cache with new analysis."""
        self._cache[game_id] = AnalysisCache(
            game_id=game_id,
            analysis=analysis,
            timestamp=datetime.now(),
            context_hash=context_hash,
        )

    def _update_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Update usage statistics."""
        cost = (
            input_tokens / 1000 * self._config.cost_per_1k_input_tokens
            + output_tokens / 1000 * self._config.cost_per_1k_output_tokens
        )

        self._usage.total_requests += 1
        self._usage.total_input_tokens += input_tokens
        self._usage.total_output_tokens += output_tokens
        self._usage.total_cost_usd += cost
        self._usage.requests_today += 1
        self._usage.cost_today_usd += cost

    async def analyze_with_schema(
        self,
        prompt: str,
        response_model: type[BaseModel],
        tool_name: str,
        game_id: str,
        cache_key: Optional[str] = None,
        model_override: Optional[str] = None,
        max_tokens_override: Optional[int] = None,
        force: bool = False,
    ) -> Optional[BaseModel]:
        """Analyze using any Pydantic model for structured output.

        Args:
            prompt: Complete prompt string.
            response_model: Pydantic model class for structured output.
            tool_name: Name of the tool for structured output.
            game_id: Game identifier for caching.
            cache_key: Optional namespaced cache key (defaults to game_id).
            model_override: Optional model override (e.g. Sonnet).
            max_tokens_override: Optional max_tokens override.
            force: Force analysis even if rate limited.

        Returns:
            Instance of response_model or None if skipped/failed.
        """
        effective_key = cache_key or game_id
        context_hash = str(hash(prompt))

        # Check cache
        cached = self._get_cached(effective_key, context_hash)
        if cached is not None:
            return cached

        # Check rate limit
        if not force and not self._check_rate_limit():
            logger.debug("Rate limited, skipping analysis for %s", effective_key)
            return None

        # Check budget
        if not self._check_budget():
            logger.warning("Daily budget exceeded, skipping analysis")
            return None

        try:
            client = await self._get_client()

            response = await client.messages.create(
                model=model_override or self._config.model,
                max_tokens=max_tokens_override or self._config.max_tokens,
                temperature=self._config.temperature,
                messages=[{"role": "user", "content": prompt}],
                tools=[
                    {
                        "name": tool_name,
                        "description": f"Submit the {tool_name} analysis",
                        "input_schema": response_model.model_json_schema(),
                    }
                ],
                tool_choice={"type": "tool", "name": tool_name},
            )

            self._last_analysis_time = datetime.now()

            # Update usage with appropriate cost rates
            if model_override and "sonnet" in model_override:
                old_input_cost = self._config.cost_per_1k_input_tokens
                old_output_cost = self._config.cost_per_1k_output_tokens
                self._config.cost_per_1k_input_tokens = 0.003
                self._config.cost_per_1k_output_tokens = 0.015
                self._update_usage(
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )
                self._config.cost_per_1k_input_tokens = old_input_cost
                self._config.cost_per_1k_output_tokens = old_output_cost
            else:
                self._update_usage(
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )

            tool_use = next(
                (block for block in response.content if block.type == "tool_use"),
                None,
            )

            if tool_use is None:
                logger.error("No tool use in Claude response for %s", effective_key)
                return None

            result = response_model(**tool_use.input)

            # Cache with namespaced key
            self._cache[effective_key] = AnalysisCache(
                game_id=effective_key,
                analysis=result,  # type: ignore[arg-type]
                timestamp=datetime.now(),
                context_hash=context_hash,
            )

            logger.info("Analysis complete for %s via %s", effective_key, tool_name)
            return result

        except Exception as e:
            logger.error("Analysis failed for %s: %s", effective_key, e)
            return None

    async def analyze(
        self,
        game_context: str,
        market_context: str,
        quant_analysis: str,
        game_id: str,
        force: bool = False,
        prompt_template: Optional[str] = None,
    ) -> Optional[ClaudeAnalysisResponse]:
        """Analyze game situation using Claude.

        Args:
            game_context: Formatted game state context
            market_context: Formatted market information
            quant_analysis: Quantitative analysis summary
            game_id: Game identifier for caching
            force: Force analysis even if rate limited
            prompt_template: Optional custom prompt template. Must contain
                {game_context}, {market_context}, {quant_analysis} placeholders.
                If None, uses the default ANALYSIS_PROMPT.

        Returns:
            ClaudeAnalysisResponse or None if skipped
        """
        # Create context hash for cache validation
        context_hash = hash(f"{game_context}{market_context}")

        # Check cache first
        cached = self._get_cached(game_id, str(context_hash))
        if cached is not None:
            return cached

        # Check rate limit
        if not force and not self._check_rate_limit():
            logger.debug(
                f"Rate limited, skipping analysis for game {game_id}"
            )
            return None

        # Check budget
        if not self._check_budget():
            logger.warning("Daily budget exceeded, skipping Claude analysis")
            return None

        try:
            client = await self._get_client()

            # Build prompt
            prompt = (prompt_template or self.ANALYSIS_PROMPT).format(
                game_context=game_context,
                market_context=market_context,
                quant_analysis=quant_analysis,
            )

            # Make API call with structured output
            response = await client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                # Use tool calling for structured output
                tools=[
                    {
                        "name": "submit_analysis",
                        "description": "Submit the game analysis",
                        "input_schema": ClaudeAnalysisResponse.model_json_schema(),
                    }
                ],
                tool_choice={"type": "tool", "name": "submit_analysis"},
            )

            # Update timing
            self._last_analysis_time = datetime.now()

            # Update usage
            self._update_usage(
                response.usage.input_tokens,
                response.usage.output_tokens,
            )

            # Parse response
            tool_use = next(
                (block for block in response.content if block.type == "tool_use"),
                None,
            )

            if tool_use is None:
                logger.error("No tool use in Claude response")
                return None

            analysis = ClaudeAnalysisResponse(**tool_use.input)

            # Cache result
            self._update_cache(game_id, analysis, str(context_hash))

            logger.info(
                f"Claude analysis for game {game_id}: "
                f"{analysis.market_assessment} (confidence: {analysis.confidence})"
            )

            return analysis

        except Exception as e:
            logger.error(f"Claude analysis failed: {e}")
            return None

    def apply_to_probability(
        self,
        base_probability: Decimal,
        analysis: ClaudeAnalysisResponse,
        base_weight: float = 0.3,
    ) -> Decimal:
        """Apply Claude's analysis to adjust probability estimate.

        Args:
            base_probability: Base probability from quant model
            analysis: Claude's analysis response
            base_weight: Base weight for Claude's adjustments (scaled by confidence)

        Returns:
            Adjusted probability estimate
        """
        # Scale weight by confidence
        effective_weight = base_weight * (analysis.confidence / 10)

        # Calculate total adjustment from Claude
        total_adjustment = (
            analysis.sentiment_adjustment + analysis.context_adjustment
        ) / 2  # Average of the two

        # Convert to probability adjustment (-0.25 to +0.25)
        prob_adjustment = Decimal(str(total_adjustment / 200))

        # Apply weighted adjustment
        adjusted = base_probability + prob_adjustment * Decimal(str(effective_weight))

        # Clamp to valid range
        return max(Decimal("0.01"), min(Decimal("0.99"), adjusted))

    @property
    def usage_stats(self) -> dict:
        """Get usage statistics."""
        return {
            "total_requests": self._usage.total_requests,
            "total_cost_usd": round(self._usage.total_cost_usd, 4),
            "requests_today": self._usage.requests_today,
            "cost_today_usd": round(self._usage.cost_today_usd, 4),
            "daily_budget_usd": self._config.daily_budget_usd,
            "budget_remaining": round(
                self._config.daily_budget_usd - self._usage.cost_today_usd, 4
            ),
        }

    def clear_cache(self) -> None:
        """Clear analysis cache."""
        self._cache.clear()
        logger.info("Claude analysis cache cleared")
