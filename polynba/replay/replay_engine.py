"""Core replay engine — feeds parsed snapshots through RuleEngine."""

import copy
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..analysis.edge_detector import EdgeOpportunity
from ..analysis.factors import (
    ClutchAnalysis,
    EfficiencyComparison,
    GameContextOutput,
    MarketSentimentOutput,
    MomentumAnalysis,
    StrengthTierComparison,
    TeamStrengthOutput,
)
from ..analysis.probability_calculator import FactorScores, ProbabilityEstimate
from ..data.models import GameState, GameStatus, Period, TeamGameState, TeamSide, TradeSide
from ..strategy.loader import StrategyConfig, StrategyLoader
from ..strategy.rule_engine import RuleContext, RuleEngine
from ..trading.position_tracker import Position
from .models import (
    ClosedPosition,
    MarketSnapshot,
    OpenPosition,
    ReplayResult,
    ReplayTrade,
)

logger = logging.getLogger(__name__)


def _stub_game_state(snap: MarketSnapshot) -> GameState:
    """Build a minimal GameState from a MarketSnapshot."""
    from ..replay.log_parser import _period_to_quarter_number

    quarter = _period_to_quarter_number(snap.period)
    period = Period.from_int(quarter)

    # Convert clock_seconds back to "M:SS" format for GameState
    mins = snap.clock_seconds // 60
    secs = snap.clock_seconds % 60
    clock_str = f"{mins}:{secs:02d}"

    home_team = TeamGameState(
        team_id=snap.home_team,
        team_name=snap.home_team,
        team_abbreviation=snap.home_team,
        score=snap.home_score,
    )
    away_team = TeamGameState(
        team_id=snap.away_team,
        team_name=snap.away_team,
        team_abbreviation=snap.away_team,
        score=snap.away_score,
    )

    return GameState(
        game_id=f"{snap.away_team}_{snap.home_team}",
        status=GameStatus.IN_PROGRESS,
        period=period,
        clock=clock_str,
        home_team=home_team,
        away_team=away_team,
        last_updated=snap.timestamp,
    )


def _stub_factor_scores() -> FactorScores:
    """Build minimal stub FactorScores for ProbabilityEstimate."""
    return FactorScores(
        market_sentiment=MarketSentimentOutput(
            score=0,
            home_implied_prob=0.0,
            away_implied_prob=0.0,
            fair_home_prob=0.0,
            fair_away_prob=0.0,
            mispricing_magnitude=0.0,
            reasoning="replay stub",
        ),
        game_context=GameContextOutput(
            score=0,
            momentum=MomentumAnalysis(
                recent_scoring_diff=0,
                scoring_run=0,
                momentum_team=None,
                momentum_strength=0,
            ),
            clutch=ClutchAnalysis(
                is_clutch=False, pressure_level=0, clutch_description=""
            ),
            home_timeouts=7,
            away_timeouts=7,
            timeout_advantage=0,
            foul_situation="normal",
            reasoning="replay stub",
        ),
        team_strength=TeamStrengthOutput(
            score=0,
            efficiency=EfficiencyComparison(
                home_net_rating=0.0,
                away_net_rating=0.0,
                net_rating_diff=0.0,
                home_pace=0.0,
                away_pace=0.0,
                expected_pace=0.0,
            ),
            tiers=StrengthTierComparison(
                home_tier="average",
                away_tier="average",
                tier_advantage="even",
                mismatch_level=0,
            ),
            home_advantages=[],
            away_advantages=[],
            injury_impact=0,
            reasoning="replay stub",
        ),
    )


def _stub_estimate(
    snap: MarketSnapshot, side: str
) -> ProbabilityEstimate:
    """Build a ProbabilityEstimate stub from snapshot data for a given side."""
    if side == "home":
        market_price = snap.home_market_price
        edge_pct = snap.home_edge_pct
    else:
        market_price = snap.away_market_price
        edge_pct = snap.away_edge_pct

    edge = Decimal(str(edge_pct)) / 100
    estimated_prob = market_price + edge

    return ProbabilityEstimate(
        market_price=snap.home_market_price,
        estimated_probability=snap.home_market_price + Decimal(str(snap.home_edge_pct)) / 100,
        edge=Decimal(str(snap.home_edge_pct)) / 100,
        edge_percentage=snap.home_edge_pct,
        combined_score=0,
        factor_scores=_stub_factor_scores(),
        confidence=snap.confidence,
        reasoning="replay stub",
        away_market_price=snap.away_market_price,
    )


def _stub_opportunity(
    snap: MarketSnapshot, side: str, estimate: ProbabilityEstimate
) -> EdgeOpportunity:
    """Build an EdgeOpportunity stub from snapshot data."""
    if side == "home":
        team = snap.home_team
        market_price = snap.home_market_price
        edge_pct = snap.home_edge_pct
    else:
        team = snap.away_team
        market_price = snap.away_market_price
        edge_pct = snap.away_edge_pct

    edge = Decimal(str(edge_pct)) / 100
    estimated_prob = market_price + edge

    return EdgeOpportunity(
        game_id=f"{snap.away_team}_{snap.home_team}",
        market_id=f"replay_{snap.away_team}_{snap.home_team}",
        token_id=f"replay_token_{side}",
        side=side,
        team_name=team,
        team_abbreviation=team,
        market_price=market_price,
        estimated_probability=estimated_prob,
        edge=edge,
        edge_percentage=edge_pct,
        confidence=snap.confidence,
        estimate=estimate,
        detected_at=snap.timestamp,
    )


def apply_overrides(strategy: StrategyConfig, overrides: dict) -> StrategyConfig:
    """Deep-copy strategy and apply parameter overrides.

    Supported override keys:
        min_edge, min_confidence, stop_loss, profit_target,
        kelly_multiplier, max_position, min_position, time_stop
    """
    s = copy.deepcopy(strategy)

    if "min_edge" in overrides:
        for cond in s.entry_rules.conditions:
            if cond.name == "minimum_edge":
                cond.value = overrides["min_edge"]

    if "min_confidence" in overrides:
        for cond in s.entry_rules.conditions:
            if cond.name == "minimum_confidence":
                cond.value = overrides["min_confidence"]

    if "stop_loss" in overrides:
        s.exit_rules.stop_loss_percent = overrides["stop_loss"]

    if "profit_target" in overrides:
        for target in s.exit_rules.profit_targets:
            target.target_percentage = overrides["profit_target"]

    if "kelly_multiplier" in overrides:
        s.position_sizing.kelly_multiplier = overrides["kelly_multiplier"]

    if "max_position" in overrides:
        s.position_sizing.max_position_usdc = overrides["max_position"]

    if "min_position" in overrides:
        s.position_sizing.min_position_usdc = overrides["min_position"]

    if "time_stop" in overrides:
        s.exit_rules.time_stop_seconds = overrides["time_stop"]

    if "cooldown_iterations" in overrides:
        s.risk_limits.cooldown_iterations = overrides["cooldown_iterations"]

    if "max_stop_losses_per_game" in overrides:
        s.risk_limits.max_stop_losses_per_game = overrides["max_stop_losses_per_game"]

    if "max_loss_per_game_usdc" in overrides:
        s.risk_limits.max_loss_per_game_usdc = overrides["max_loss_per_game_usdc"]

    return s


@dataclass
class VolatilityConfig:
    """Volatility filter settings for replay."""

    min_edge_percent: float = 5.0
    score_threshold: int = 5
    period_threshold: int = 3
    edge_multiplier: float = 1.5

    def effective_min_edge(self, game_state: GameState) -> float:
        """Return the effective min edge, raised during volatile conditions."""
        is_tight = abs(game_state.score_differential) < self.score_threshold
        is_late = game_state.period.value >= self.period_threshold
        if is_tight and is_late:
            return self.min_edge_percent * self.edge_multiplier
        return self.min_edge_percent


class ReplayEngine:
    """Replays parsed snapshots through the RuleEngine with modified strategy."""

    def __init__(
        self,
        strategy_id: str,
        overrides: Optional[dict] = None,
        bankroll: Optional[Decimal] = None,
        volatility_config: Optional[VolatilityConfig] = None,
    ):
        self._strategy_id = strategy_id
        self._overrides = overrides or {}
        self._bankroll = bankroll or Decimal("500")
        self._volatility = volatility_config
        self._rule_engine = RuleEngine()
        self._loader = StrategyLoader()

    def run(
        self,
        snapshots: list[MarketSnapshot],
        original_signal_count: int = 0,
        log_path: str = "",
        verbose: bool = False,
    ) -> ReplayResult:
        """Run the replay loop over all snapshots.

        Args:
            snapshots: Parsed market snapshots from LogParser
            original_signal_count: Signal count from original session
            log_path: Path to log for result metadata
            verbose: Print per-iteration details

        Returns:
            ReplayResult with all trades, positions, and summary stats
        """
        if not snapshots:
            raise ValueError("No snapshots to replay")

        # Load and override strategy
        base_strategy = self._loader.load_by_id(self._strategy_id)
        if base_strategy is None:
            raise ValueError(f"Strategy not found: {self._strategy_id}")

        strategy = apply_overrides(base_strategy, self._overrides)
        # Clear rule cache so overridden conditions take effect
        self._rule_engine.clear_cache()

        first_snap = snapshots[0]
        result = ReplayResult(
            log_path=log_path,
            away_team=first_snap.away_team,
            home_team=first_snap.home_team,
            game_date=first_snap.timestamp.strftime("%Y-%m-%d"),
            strategy_id=self._strategy_id,
            overrides=self._overrides,
            total_snapshots=len(snapshots),
            first_timestamp=first_snap.timestamp,
            last_timestamp=snapshots[-1].timestamp,
            bankroll=self._bankroll,
            original_signal_count=original_signal_count,
        )

        # Open replay positions: side -> (ReplayTrade, Position)
        open_positions: dict[str, tuple[ReplayTrade, Position]] = {}
        max_position_per_game = strategy.risk_limits.max_position_per_game
        equity = Decimal("0")

        # Stop-loss cooldown tracking
        cooldown_iterations = strategy.risk_limits.cooldown_iterations
        max_stop_losses = strategy.risk_limits.max_stop_losses_per_game
        last_stop_loss_iteration: dict[str, int] = {}  # side -> iteration
        game_stop_loss_count = 0

        # Per-game loss cap tracking
        max_loss_per_game = Decimal(str(strategy.risk_limits.max_loss_per_game_usdc))
        game_cumulative_pnl = Decimal("0")

        for snap in snapshots:
            game_state = _stub_game_state(snap)

            # --- Check exits for open positions ---
            for side in list(open_positions.keys()):
                entry_trade, position = open_positions[side]
                current_price = snap.home_market_price if side == "home" else snap.away_market_price

                should_exit, reason, _limit_price = self._rule_engine.evaluate_exit(
                    strategy,
                    position,
                    current_price,
                    snap.total_seconds_remaining,
                    spread_pct=0.0,  # Replay logs don't have spread data; guard stays disabled
                )

                if should_exit:
                    # Close position
                    pnl = position.unrealized_pnl(current_price)
                    pnl_pct = position.unrealized_pnl_percent(current_price)

                    exit_trade = ReplayTrade(
                        iteration=snap.iteration,
                        timestamp=snap.timestamp,
                        side=side,
                        team=snap.home_team if side == "home" else snap.away_team,
                        action="sell",
                        shares=position.size,
                        price=current_price,
                        size_usdc=position.size * current_price,
                        edge_pct=snap.home_edge_pct if side == "home" else snap.away_edge_pct,
                        confidence=snap.confidence,
                        reason=reason,
                        strategy_id=self._strategy_id,
                    )
                    result.trades.append(exit_trade)

                    result.closed_positions.append(
                        ClosedPosition(
                            entry_trade=entry_trade,
                            exit_trade=exit_trade,
                            pnl_usdc=pnl,
                            pnl_percent=pnl_pct,
                            hold_iterations=snap.iteration - entry_trade.iteration,
                        )
                    )
                    equity += pnl
                    game_cumulative_pnl += pnl
                    del open_positions[side]

                    # Track stop losses for cooldown
                    if "stop loss" in reason.lower():
                        last_stop_loss_iteration[side] = snap.iteration
                        game_stop_loss_count += 1
                        if verbose:
                            logger.info(
                                f"  [Iter {snap.iteration}] STOP LOSS #{game_stop_loss_count} "
                                f"on {side} | Game PnL: ${game_cumulative_pnl:+.2f}"
                            )

                    if verbose:
                        logger.info(
                            f"  [Iter {snap.iteration}] EXIT {side} @ {current_price} "
                            f"| PnL: ${pnl:+.2f} ({pnl_pct:+.1f}%) | {reason}"
                        )

            # --- Per-game loss cap: skip all entries if exceeded ---
            if max_loss_per_game > 0 and game_cumulative_pnl <= -max_loss_per_game:
                continue

            # --- Max stop losses per game: skip all entries if exceeded ---
            if max_stop_losses > 0 and game_stop_loss_count >= max_stop_losses:
                continue

            # --- Check entries for each side ---
            for side in ("home", "away"):
                # Respect max_position_per_game
                if len(open_positions) >= max_position_per_game:
                    break
                if side in open_positions:
                    continue

                # Stop-loss cooldown: skip entry if recently stopped out on this side
                if cooldown_iterations > 0 and side in last_stop_loss_iteration:
                    iters_since_stop = snap.iteration - last_stop_loss_iteration[side]
                    if iters_since_stop < cooldown_iterations:
                        if verbose:
                            logger.info(
                                f"  [Iter {snap.iteration}] Cooldown: {side} stopped out "
                                f"{iters_since_stop} iters ago (need {cooldown_iterations})"
                            )
                        continue

                # Volatility pre-filter: skip if edge below raised threshold
                if self._volatility is not None:
                    edge_pct = snap.home_edge_pct if side == "home" else snap.away_edge_pct
                    eff_min = self._volatility.effective_min_edge(game_state)
                    if edge_pct < eff_min:
                        if verbose and eff_min > self._volatility.min_edge_percent:
                            logger.info(
                                f"  [Iter {snap.iteration}] Volatility filter: "
                                f"{side} edge {edge_pct:.1f}% < {eff_min:.2f}% (raised)"
                            )
                        continue

                estimate = _stub_estimate(snap, side)
                opportunity = _stub_opportunity(snap, side, estimate)
                context = RuleContext(game_state=game_state, opportunity=opportunity)

                eval_result = self._rule_engine.evaluate_entry(strategy, context)

                if eval_result.passed:
                    # Calculate position size
                    size_usdc = self._rule_engine.calculate_position_size(
                        strategy,
                        opportunity,
                        self._bankroll,
                        time_remaining_seconds=snap.total_seconds_remaining,
                    )

                    market_price = snap.home_market_price if side == "home" else snap.away_market_price
                    if market_price <= 0:
                        continue

                    shares = size_usdc / market_price

                    entry_trade = ReplayTrade(
                        iteration=snap.iteration,
                        timestamp=snap.timestamp,
                        side=side,
                        team=snap.home_team if side == "home" else snap.away_team,
                        action="buy",
                        shares=shares,
                        price=market_price,
                        size_usdc=size_usdc,
                        edge_pct=snap.home_edge_pct if side == "home" else snap.away_edge_pct,
                        confidence=snap.confidence,
                        reason=f"Entry: {', '.join(eval_result.passed_rules)}",
                        strategy_id=self._strategy_id,
                    )
                    result.trades.append(entry_trade)

                    # Create Position object for exit evaluation
                    position = Position(
                        market_id=f"replay_{snap.away_team}_{snap.home_team}",
                        token_id=f"replay_token_{side}",
                        side=TradeSide.BUY,
                        size=shares,
                        avg_entry_price=market_price,
                        strategy_id=self._strategy_id,
                        opened_at=snap.timestamp,
                        total_cost=size_usdc,
                    )
                    open_positions[side] = (entry_trade, position)

                    if verbose:
                        edge = snap.home_edge_pct if side == "home" else snap.away_edge_pct
                        logger.info(
                            f"  [Iter {snap.iteration}] ENTRY {side} "
                            f"{snap.home_team if side == 'home' else snap.away_team} "
                            f"@ {market_price} | ${size_usdc:.2f} | Edge: {edge:+.1f}%"
                        )

        # --- Mark remaining positions to market ---
        last_snap = snapshots[-1]
        for side, (entry_trade, position) in open_positions.items():
            current_price = last_snap.home_market_price if side == "home" else last_snap.away_market_price
            unrealized = position.unrealized_pnl(current_price)
            unrealized_pct = position.unrealized_pnl_percent(current_price)

            result.open_positions.append(
                OpenPosition(
                    entry_trade=entry_trade,
                    current_price=current_price,
                    unrealized_pnl_usdc=unrealized,
                    unrealized_pnl_percent=unrealized_pct,
                )
            )

        return result
