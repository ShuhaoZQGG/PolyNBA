"""Pre-game probability model for NBA betting.

Converts team strength scores to win probabilities, applies head-to-head
adjustments, blends with Polymarket odds, and computes Kelly bet sizing.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from ..analysis.factors.team_strength import (
    TeamStrengthFactor,
    TeamStrengthInput,
    TeamStrengthOutput,
)
from ..data.models import HeadToHead, TeamContext, TeamStats

logger = logging.getLogger(__name__)


@dataclass
class PreGameModelConfig:
    """Configuration for the pre-game probability model."""

    # Logistic steepness: controls how quickly strength score maps to probability.
    # At k=0.018 a score of +50 → ~67% win probability.
    logistic_k: float = 0.018

    # Blend weights: model and market must sum to 1.0.
    model_weight: float = 0.30
    market_weight: float = 0.70

    # Maximum head-to-head probability shift in either direction (±3%).
    h2h_max_adjustment: float = 0.03

    # Minimum edge (in percentage points) required to recommend a bet.
    min_edge_percent: float = 2.0

    # Kelly conservatism factor: 0.25 = quarter-Kelly.
    kelly_fraction: float = 0.25

    # Hard cap on Kelly output as a percentage of bankroll.
    max_kelly_pct: float = 15.0

    # SPECULATE: bet on high-conviction model outcomes even without market edge.
    # Minimum model_prob (for either side) to trigger a speculate verdict.
    min_speculate_prob: float = 0.72
    # More conservative Kelly fraction for speculate bets.
    speculate_kelly_fraction: float = 0.15


@dataclass
class PreGameEstimate:
    """Full pre-game probability and sizing estimate for one matchup."""

    home_team_abbr: str
    away_team_abbr: str

    # Probability chain
    raw_model_prob: float          # Logistic output from strength score alone
    h2h_adjustment: float          # Probability shift applied from H2H data
    model_prob: float              # raw_model_prob + h2h_adjustment (clamped)
    market_prob: float             # Polymarket mid-price for home team
    blended_prob: float            # Weighted blend of model_prob and market_prob

    # Edge metrics
    edge: float                    # blended_prob - market_prob
    edge_percent: float            # edge * 100

    # Sizing
    kelly_fraction: float          # Optimal Kelly fraction of bankroll (0–max_kelly_pct/100)
    suggested_bet_usdc: float      # kelly_fraction * bankroll

    # Decision
    confidence: int                # 1–10 composite confidence score
    verdict: str                   # "BET HOME", "BET AWAY", or "HOLD"
    bet_side: str                  # "home" or "away"

    # Supporting detail (optional)
    strength_output: Optional[TeamStrengthOutput] = None
    head_to_head: Optional[HeadToHead] = None
    factors_summary: list[str] = field(default_factory=list)


class PreGameProbabilityModel:
    """Converts NBA team data into actionable pre-game betting estimates.

    Pipeline:
    1. Run TeamStrengthFactor to get a -100..+100 composite score.
    2. Map that score through a logistic function to a raw win probability.
    3. Apply a bounded head-to-head adjustment.
    4. Blend the adjusted model probability with the Polymarket price.
    5. Compute edge and Kelly-optimal bet size.
    6. Emit a structured PreGameEstimate with verdict and human-readable
       factor descriptions.
    """

    def __init__(self, config: Optional[PreGameModelConfig] = None) -> None:
        """Initialise model.

        Args:
            config: Model hyper-parameters.  Defaults to PreGameModelConfig().
        """
        self._config = config if config is not None else PreGameModelConfig()
        self._strength_factor = TeamStrengthFactor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(
        self,
        home_stats: TeamStats,
        away_stats: TeamStats,
        market_home_prob: float,
        bankroll: float,
        home_context: Optional[TeamContext] = None,
        away_context: Optional[TeamContext] = None,
        head_to_head: Optional[HeadToHead] = None,
    ) -> PreGameEstimate:
        """Produce a full pre-game estimate for a home vs. away matchup.

        Args:
            home_stats: Season statistics for the home team.
            away_stats: Season statistics for the away team.
            market_home_prob: Polymarket mid-price for the home-team outcome
                (0.0–1.0).
            bankroll: Current USDC bankroll used to size the suggested bet.
            home_context: Optional enriched context (injuries, etc.) for the
                home team.
            away_context: Optional enriched context for the away team.
            head_to_head: Optional current-season H2H record (team1 = home).

        Returns:
            PreGameEstimate with verdict, Kelly sizing, and factor summaries.
        """
        cfg = self._config

        # ----------------------------------------------------------------
        # Step 1 — Team strength score
        # ----------------------------------------------------------------
        strength_input = TeamStrengthInput(
            home_stats=home_stats,
            away_stats=away_stats,
            home_context=home_context,
            away_context=away_context,
        )
        strength_output: TeamStrengthOutput = self._strength_factor.calculate(
            strength_input
        )

        logger.debug(
            "Strength score %s vs %s: %+d",
            home_stats.team_abbreviation,
            away_stats.team_abbreviation,
            strength_output.score,
        )

        # ----------------------------------------------------------------
        # Step 2 — Logistic probability from strength score
        # ----------------------------------------------------------------
        raw_prob = 1.0 / (1.0 + math.exp(-cfg.logistic_k * strength_output.score))

        # ----------------------------------------------------------------
        # Step 3 — Head-to-head adjustment
        # ----------------------------------------------------------------
        adj = 0.0
        if head_to_head is not None and head_to_head.games_played > 0:
            h2h_win_pct = head_to_head.team1_win_percentage  # team1 == home
            # Scale by number of games (capped at 4) and a per-game weight.
            # Formula: (win_pct - 0.5) * games_capped * 0.008 * 2
            # At 4 games and 100% H2H: adj = 0.5 * 4 * 0.016 = +0.032 → clamped to +0.03
            raw_adj = (h2h_win_pct - 0.5) * min(head_to_head.games_played, 4) * 0.008 * 2
            adj = max(-cfg.h2h_max_adjustment, min(cfg.h2h_max_adjustment, raw_adj))

        logger.debug("H2H adjustment: %+.4f", adj)

        # ----------------------------------------------------------------
        # Step 4 — Model probability (clamped to [0.05, 0.95])
        # ----------------------------------------------------------------
        model_prob = max(0.05, min(0.95, raw_prob + adj))

        # ----------------------------------------------------------------
        # Step 5 — Blend with market probability
        # ----------------------------------------------------------------
        blended = cfg.model_weight * model_prob + cfg.market_weight * market_home_prob

        # ----------------------------------------------------------------
        # Step 6 — Edge
        # ----------------------------------------------------------------
        edge = blended - market_home_prob
        edge_percent = edge * 100.0

        # ----------------------------------------------------------------
        # Step 7 — Kelly sizing
        # ----------------------------------------------------------------
        kelly = self._compute_kelly(edge, edge_percent, blended, market_home_prob, cfg)
        suggested_bet = kelly * bankroll

        # ----------------------------------------------------------------
        # Step 8 — Verdict
        # ----------------------------------------------------------------
        verdict, bet_side = self._determine_verdict(edge, edge_percent, kelly, cfg)

        # ----------------------------------------------------------------
        # Step 8b — SPECULATE override for high-conviction HOLD games
        # ----------------------------------------------------------------
        if verdict == "HOLD":
            speculate_result = self._check_speculate(
                model_prob, market_home_prob, bankroll, cfg,
            )
            if speculate_result is not None:
                verdict, bet_side, kelly, suggested_bet = speculate_result

        # ----------------------------------------------------------------
        # Step 9 — Confidence score (1–10)
        # ----------------------------------------------------------------
        h2h_bonus = 1 if (head_to_head is not None and head_to_head.games_played > 0) else 0
        raw_conf = (
            abs(edge_percent) * 1.2
            + strength_output.tiers.mismatch_level
            + h2h_bonus
        )
        confidence = int(min(10, max(1, raw_conf)))

        # ----------------------------------------------------------------
        # Step 10 — Human-readable factor summaries
        # ----------------------------------------------------------------
        factors_summary = self._build_factors_summary(
            home_stats=home_stats,
            away_stats=away_stats,
            strength_output=strength_output,
            home_context=home_context,
            away_context=away_context,
            head_to_head=head_to_head,
            adj=adj,
        )

        return PreGameEstimate(
            home_team_abbr=home_stats.team_abbreviation,
            away_team_abbr=away_stats.team_abbreviation,
            raw_model_prob=raw_prob,
            h2h_adjustment=adj,
            model_prob=model_prob,
            market_prob=market_home_prob,
            blended_prob=blended,
            edge=edge,
            edge_percent=edge_percent,
            kelly_fraction=kelly,
            suggested_bet_usdc=suggested_bet,
            confidence=confidence,
            verdict=verdict,
            bet_side=bet_side,
            strength_output=strength_output,
            head_to_head=head_to_head,
            factors_summary=factors_summary,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_kelly(
        self,
        edge: float,
        edge_percent: float,
        blended: float,
        market_home_prob: float,
        cfg: PreGameModelConfig,
    ) -> float:
        """Compute fractional Kelly bet size.

        Returns a value in [0, max_kelly_pct / 100].
        """
        # Treat near-zero edge as no bet.
        if abs(edge_percent) < 0.5:
            return 0.0

        if edge > 0:
            # Betting home: blended probability is our edge estimate.
            bet_prob = blended
            # Decimal odds minus 1 (the "b" in Kelly formula b*p - q / b).
            # Guard against market_home_prob at or near 1 to avoid division by zero.
            market_prob_safe = max(1e-6, min(1.0 - 1e-6, market_home_prob))
            odds = (1.0 / market_prob_safe) - 1.0
        else:
            # Betting away.
            bet_prob = 1.0 - blended
            market_away_prob = 1.0 - market_home_prob
            market_away_safe = max(1e-6, min(1.0 - 1e-6, market_away_prob))
            odds = (1.0 / market_away_safe) - 1.0

        p = bet_prob
        q = 1.0 - p
        kelly_raw = (odds * p - q) / odds
        kelly = max(0.0, kelly_raw) * cfg.kelly_fraction

        # Hard cap
        kelly = min(kelly, cfg.max_kelly_pct / 100.0)
        return kelly

    def _determine_verdict(
        self,
        edge: float,
        edge_percent: float,
        kelly: float,
        cfg: PreGameModelConfig,
    ) -> tuple[str, str]:
        """Return (verdict, bet_side) based on edge and Kelly size."""
        if abs(edge_percent) >= cfg.min_edge_percent and kelly > 0:
            if edge > 0:
                return "BET HOME", "home"
            else:
                return "BET AWAY", "away"
        else:
            # No actionable edge — report which side is weakly preferred.
            bet_side = "home" if edge >= 0 else "away"
            return "HOLD", bet_side

    def _check_speculate(
        self,
        model_prob: float,
        market_home_prob: float,
        bankroll: float,
        cfg: PreGameModelConfig,
    ) -> Optional[tuple[str, str, float, float]]:
        """Check if SPECULATE verdict applies for a HOLD game.

        SPECULATE triggers when the model has high conviction (model_prob
        exceeds min_speculate_prob for either side) even though the
        blended edge doesn't meet the BET threshold.

        Uses pure model_prob vs market_prob for Kelly sizing (no blend),
        with the more conservative speculate_kelly_fraction.

        Returns:
            (verdict, bet_side, kelly, suggested_bet) or None if no speculate.
        """
        home_conviction = model_prob
        away_conviction = 1.0 - model_prob

        # Determine which side has high conviction
        if home_conviction >= cfg.min_speculate_prob:
            bet_side = "home"
            bet_prob = home_conviction
            market_prob = market_home_prob
        elif away_conviction >= cfg.min_speculate_prob:
            bet_side = "away"
            bet_prob = away_conviction
            market_prob = 1.0 - market_home_prob
        else:
            return None

        # Kelly using pure model prob vs market (not blended)
        market_safe = max(1e-6, min(1.0 - 1e-6, market_prob))
        odds = (1.0 / market_safe) - 1.0
        q = 1.0 - bet_prob
        kelly_raw = (odds * bet_prob - q) / odds
        kelly = max(0.0, kelly_raw) * cfg.speculate_kelly_fraction
        kelly = min(kelly, cfg.max_kelly_pct / 100.0)

        if kelly <= 0:
            return None

        suggested_bet = kelly * bankroll
        verdict = f"SPECULATE {'HOME' if bet_side == 'home' else 'AWAY'}"

        logger.info(
            "SPECULATE triggered: %s conviction %.1f%% > threshold %.1f%%, kelly %.2f%%",
            bet_side,
            bet_prob * 100,
            cfg.min_speculate_prob * 100,
            kelly * 100,
        )

        return verdict, bet_side, kelly, suggested_bet

    def _build_factors_summary(
        self,
        home_stats: TeamStats,
        away_stats: TeamStats,
        strength_output: TeamStrengthOutput,
        home_context: Optional[TeamContext],
        away_context: Optional[TeamContext],
        head_to_head: Optional[HeadToHead],
        adj: float,
    ) -> list[str]:
        """Build a list of human-readable strings summarising each signal."""
        summary: list[str] = []
        home_abbr = home_stats.team_abbreviation
        away_abbr = away_stats.team_abbreviation

        # ---- Team strength line ----
        home_tier = strength_output.tiers.home_tier
        away_tier = strength_output.tiers.away_tier
        summary.append(
            f"Team strength: {home_abbr} {home_tier} "
            f"(NRtg {home_stats.net_rating:+.1f}) vs "
            f"{away_abbr} {away_tier} "
            f"(NRtg {away_stats.net_rating:+.1f}) "
            f"→ score {strength_output.score:+d}"
        )

        # ---- Injury line ----
        home_out = home_context.key_players_out if home_context is not None else []
        away_out = away_context.key_players_out if away_context is not None else []
        if home_out or away_out:
            parts: list[str] = []
            if home_out:
                names = ", ".join(inj.player_name for inj in home_out)
                parts.append(f"{home_abbr} missing {names}")
            if away_out:
                names = ", ".join(inj.player_name for inj in away_out)
                parts.append(f"{away_abbr} missing {names}")
            injury_desc = "; ".join(parts)
            summary.append(f"Injuries: {injury_desc}")

        # ---- H2H line ----
        if head_to_head is not None and head_to_head.games_played > 0:
            summary.append(
                f"H2H: {head_to_head.team1_wins}-{head_to_head.team2_wins} "
                f"this season (adj {adj:+.1%})"
            )

        # ---- Home/away splits line ----
        summary.append(
            f"Home/away: {home_abbr} {home_stats.home_wins}-{home_stats.home_losses} home, "
            f"{away_abbr} {away_stats.away_wins}-{away_stats.away_losses} road"
        )

        return summary
