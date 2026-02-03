"""Context builder for formatting data for Claude analysis."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..data.models import GameState, TeamContext, TeamSide, TeamStats
from .probability_calculator import ProbabilityEstimate


@dataclass
class FormattedContext:
    """Formatted context strings for Claude."""

    game_context: str
    market_context: str
    quant_analysis: str


class ContextBuilder:
    """Builds formatted context strings for Claude analysis."""

    def build(
        self,
        game_state: GameState,
        home_market_price: Decimal,
        estimate: ProbabilityEstimate,
        home_stats: Optional[TeamStats] = None,
        away_stats: Optional[TeamStats] = None,
        home_context: Optional[TeamContext] = None,
        away_context: Optional[TeamContext] = None,
    ) -> FormattedContext:
        """Build formatted context for Claude.

        Args:
            game_state: Current game state
            home_market_price: Market price for home win
            estimate: Quantitative probability estimate
            home_stats: Home team statistics
            away_stats: Away team statistics
            home_context: Home team full context
            away_context: Away team full context

        Returns:
            FormattedContext with all context strings
        """
        game_context = self._build_game_context(
            game_state, home_stats, away_stats, home_context, away_context
        )

        market_context = self._build_market_context(
            home_market_price, game_state, away_price=estimate.away_market_price
        )

        quant_analysis = self._build_quant_analysis(estimate)

        return FormattedContext(
            game_context=game_context,
            market_context=market_context,
            quant_analysis=quant_analysis,
        )

    def _build_game_context(
        self,
        game: GameState,
        home_stats: Optional[TeamStats],
        away_stats: Optional[TeamStats],
        home_context: Optional[TeamContext],
        away_context: Optional[TeamContext],
    ) -> str:
        """Build game state context string."""
        lines = []

        # Basic game info
        lines.append(f"## {game.away_team.team_name} @ {game.home_team.team_name}")
        lines.append("")

        # Score and time
        lines.append("### Current Score")
        lines.append(
            f"- {game.away_team.team_abbreviation}: {game.away_team.score}"
        )
        lines.append(
            f"- {game.home_team.team_abbreviation}: {game.home_team.score} (Home)"
        )

        diff = game.score_differential
        if diff > 0:
            lines.append(f"- Home leads by {diff}")
        elif diff < 0:
            lines.append(f"- Away leads by {-diff}")
        else:
            lines.append("- Game is tied")

        lines.append("")

        # Time remaining
        lines.append("### Time Remaining")
        lines.append(f"- Period: {game.period.display_name}")
        lines.append(f"- Clock: {game.clock}")
        minutes = game.total_seconds_remaining / 60
        lines.append(f"- Total time remaining: ~{minutes:.1f} minutes")

        if game.period.is_overtime:
            lines.append("- **OVERTIME**")

        lines.append("")

        # Recent momentum
        if game.recent_plays:
            lines.append("### Recent Scoring")
            momentum = game.get_momentum_indicator(5)
            if momentum[1]:
                team_name = (
                    game.home_team.team_abbreviation
                    if momentum[1] == TeamSide.HOME
                    else game.away_team.team_abbreviation
                )
                lines.append(f"- {team_name} has scored {momentum[0]} more points in last 5 scoring plays")

            # Recent plays summary
            recent_scoring = game.get_recent_scoring_plays(3)
            if recent_scoring:
                lines.append("- Last 3 scores:")
                for play in recent_scoring:
                    lines.append(f"  - {play.description[:50]}...")

            lines.append("")

        # Timeouts
        lines.append("### Resources")
        lines.append(
            f"- {game.home_team.team_abbreviation} timeouts: {game.home_team.timeouts_remaining}"
        )
        lines.append(
            f"- {game.away_team.team_abbreviation} timeouts: {game.away_team.timeouts_remaining}"
        )
        lines.append("")

        # Team statistics if available
        if home_stats and away_stats:
            lines.append("### Season Statistics")
            lines.append("")
            lines.append(f"**{home_stats.team_abbreviation}** (Home)")
            lines.append(f"- Record: {home_stats.wins}-{home_stats.losses}")
            lines.append(f"- Net Rating: {home_stats.net_rating:+.1f}")
            lines.append(f"- Home Record: {home_stats.home_wins}-{home_stats.home_losses}")
            if home_stats.current_streak != 0:
                streak_type = "W" if home_stats.current_streak > 0 else "L"
                lines.append(f"- Streak: {streak_type}{abs(home_stats.current_streak)}")

            lines.append("")
            lines.append(f"**{away_stats.team_abbreviation}** (Away)")
            lines.append(f"- Record: {away_stats.wins}-{away_stats.losses}")
            lines.append(f"- Net Rating: {away_stats.net_rating:+.1f}")
            lines.append(f"- Away Record: {away_stats.away_wins}-{away_stats.away_losses}")
            if away_stats.current_streak != 0:
                streak_type = "W" if away_stats.current_streak > 0 else "L"
                lines.append(f"- Streak: {streak_type}{abs(away_stats.current_streak)}")

            lines.append("")

        # Injuries if available
        if home_context and home_context.key_players_out:
            lines.append(f"### {game.home_team.team_abbreviation} Injuries")
            for inj in home_context.key_players_out[:3]:
                lines.append(f"- {inj.player_name}: {inj.status}")
            lines.append("")

        if away_context and away_context.key_players_out:
            lines.append(f"### {game.away_team.team_abbreviation} Injuries")
            for inj in away_context.key_players_out[:3]:
                lines.append(f"- {inj.player_name}: {inj.status}")
            lines.append("")

        return "\n".join(lines)

    def _build_market_context(
        self,
        home_market_price: Decimal,
        game: GameState,
        away_price: Optional[Decimal] = None,
    ) -> str:
        """Build market information context string (buy prices = best ask)."""
        lines = []

        if away_price is None:
            away_price = Decimal("1") - home_market_price

        lines.append("## Market Prices")
        lines.append("")
        lines.append(f"- {game.home_team.team_abbreviation} Win: {float(home_market_price):.1%}")
        lines.append(f"- {game.away_team.team_abbreviation} Win: {float(away_price):.1%}")
        lines.append("")

        # Implied odds
        lines.append("## Implied Odds")
        if home_market_price > 0:
            home_decimal = 1 / float(home_market_price)
            lines.append(f"- {game.home_team.team_abbreviation}: {home_decimal:.2f} decimal odds")
        if away_price > 0:
            away_decimal = 1 / float(away_price)
            lines.append(f"- {game.away_team.team_abbreviation}: {away_decimal:.2f} decimal odds")

        return "\n".join(lines)

    def _build_quant_analysis(self, estimate: ProbabilityEstimate) -> str:
        """Build quantitative analysis summary."""
        lines = []

        factors = estimate.factor_scores

        lines.append("## Factor Analysis")
        lines.append("")

        # Market sentiment
        lines.append("### Market Sentiment Factor")
        lines.append(f"- Score: {factors.market_sentiment.score:+d}/100")
        lines.append(f"- Fair home win probability: {factors.market_sentiment.fair_home_prob:.1%}")
        lines.append(f"- Market implied probability: {factors.market_sentiment.home_implied_prob:.1%}")
        lines.append(f"- Mispricing magnitude: {factors.market_sentiment.mispricing_magnitude:.1f}%")
        lines.append("")

        # Game context
        lines.append("### Game Context Factor")
        lines.append(f"- Score: {factors.game_context.score:+d}/100")
        if factors.game_context.momentum.momentum_team:
            lines.append(
                f"- Momentum: {'Home' if factors.game_context.momentum.momentum_team == TeamSide.HOME else 'Away'} "
                f"({factors.game_context.momentum.momentum_strength}% strength)"
            )
        if factors.game_context.clutch.is_clutch:
            lines.append(f"- Clutch: {factors.game_context.clutch.clutch_description}")
        lines.append(f"- Timeout advantage: {factors.game_context.timeout_advantage:+d}")
        lines.append("")

        # Team strength
        lines.append("### Team Strength Factor")
        lines.append(f"- Score: {factors.team_strength.score:+d}/100")
        lines.append(
            f"- Home tier: {factors.team_strength.tiers.home_tier} "
            f"(net rating: {factors.team_strength.efficiency.home_net_rating:+.1f})"
        )
        lines.append(
            f"- Away tier: {factors.team_strength.tiers.away_tier} "
            f"(net rating: {factors.team_strength.efficiency.away_net_rating:+.1f})"
        )
        lines.append("")

        # Summary
        lines.append("### Combined Analysis")
        lines.append(f"- Combined score: {estimate.combined_score:+d}/100")
        lines.append(f"- Market price: {float(estimate.market_price):.1%}")
        lines.append(f"- Estimated fair value: {float(estimate.estimated_probability):.1%}")
        lines.append(f"- Edge: {estimate.edge_percentage:+.1f}%")
        lines.append(f"- Confidence: {estimate.confidence}/10")

        return "\n".join(lines)
