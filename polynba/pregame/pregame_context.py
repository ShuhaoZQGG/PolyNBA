"""Pre-game context builder for Claude AI analysis.

Formats team stats, injuries, H2H, and model estimates into context strings
that the ClaudeAnalyzer can consume. Unlike the live-game ContextBuilder,
this module works with pre-game data only (no score/clock/momentum).
"""

from typing import Optional

from ..data.models import GameSummary, HeadToHead, PlayerSeasonStats, TeamContext
from .probability_model import PreGameEstimate


EDGE_PROMPT = """Analyze this upcoming NBA game for pre-game betting on Polymarket.

GAME CONTEXT:
{game_context}

MARKET INFORMATION:
{market_context}

QUANTITATIVE ANALYSIS:
{quant_analysis}

This is a PRE-GAME edge-finding analysis — the game has not started yet.
Our model found a potential market inefficiency. Your job is to determine
whether the market is truly mispricing this game.

Consider:
1. Does the model probability align with matchup fundamentals?
2. Are there injury, schedule, or motivation factors the market might misprice?
3. Is there a clear matchup advantage (pace, style, H2H history)?
4. What are the main risks that could undermine the edge?

For market_assessment:
- "undervalued" = the market IS mispricing this, edge is real
- "fair" = market is roughly correct, edge may be noise
- "overvalued" = the model is wrong, market is right

Provide your analysis in the structured format."""


CONVICTION_PROMPT = """Assess the conviction level for a high-probability NBA game outcome.

GAME CONTEXT:
{game_context}

MARKET INFORMATION:
{market_context}

QUANTITATIVE ANALYSIS:
{quant_analysis}

This is a CONVICTION analysis — NOT an edge-finding analysis.
The market and model roughly agree on the probability. Our model has HIGH
CONVICTION that the favored team will win. Your job is to evaluate whether
that conviction is justified and how aggressively to bet.

Consider:
1. How strong is the talent/matchup mismatch? Is this a true blowout candidate?
2. Are injuries amplifying the mismatch (key player out for the underdog)?
3. Any motivation or schedule traps? (back-to-back, tanking, rest starters?)
4. Does H2H history suggest upsets are plausible despite the stats?
5. Is there any reason the underdog could keep this close or steal a win?

For market_assessment — interpret as CONVICTION LEVEL, not market efficiency:
- "undervalued" = conviction is STRONG — the favored team is even more likely
  to win than the numbers suggest (bet aggressively)
- "fair" = conviction is SOLID — numbers are right, team should win as expected
  (bet moderately)
- "overvalued" = conviction is WEAK — there are meaningful upset risks the
  numbers miss (reduce or skip the bet)

For confidence (1–10) — rate how likely the favored team actually wins:
- 8-10: Near-certain win, go bigger
- 6-7: Likely win, moderate bet
- 4-5: Toss-up risks, small bet or skip
- 1-3: Upset is very possible, do not bet

For sentiment_adjustment and context_adjustment — use these to express how
much to scale the bet size UP or DOWN from the base Kelly calculation:
- Positive values = bet more (strong conviction factors)
- Negative values = bet less (upset risk factors)

Provide your analysis in the structured format."""


def build_pregame_context(
    game: GameSummary,
    home_ctx: TeamContext,
    away_ctx: TeamContext,
    h2h: Optional[HeadToHead],
    estimate: PreGameEstimate,
    market_home_price: float,
    bankroll: Optional[float] = None,
) -> tuple[str, str, str]:
    """Build formatted context strings for Claude pre-game analysis.

    Args:
        game: Game summary with team names and metadata.
        home_ctx: Full context for the home team.
        away_ctx: Full context for the away team.
        h2h: Optional head-to-head record (team1 = home).
        estimate: Pre-game probability model estimate.
        market_home_price: Polymarket mid-price for home team (0-1).
        bankroll: Optional available bankroll (included in quant context
            for conviction sizing analysis).

    Returns:
        Tuple of (game_context, market_context, quant_analysis) strings.
    """
    game_context = _build_game_context(game, home_ctx, away_ctx, h2h)
    market_context = _build_market_context(market_home_price)
    quant_analysis = _build_quant_analysis(estimate, bankroll, home_ctx, away_ctx)
    return game_context, market_context, quant_analysis


def _build_game_context(
    game: GameSummary,
    home_ctx: TeamContext,
    away_ctx: TeamContext,
    h2h: Optional[HeadToHead],
) -> str:
    """Build the game context section."""
    home = home_ctx.stats
    away = away_ctx.stats
    lines: list[str] = []

    lines.append(f"Matchup: {away.team_abbreviation} @ {home.team_abbreviation}")
    lines.append(f"Status: Pre-game (not yet started)")
    lines.append("")

    # Season records
    lines.append(f"{home.team_abbreviation}: {home.wins}-{home.losses} ({home.win_percentage:.3f})")
    lines.append(f"  Net Rating: {home.net_rating:+.1f} (rank #{home.net_rating_rank})")
    lines.append(f"  ORtg: {home.offensive_rating:.1f} (#{home.offensive_rating_rank}) | DRtg: {home.defensive_rating:.1f} (#{home.defensive_rating_rank})")
    lines.append(f"  Home: {home.home_wins}-{home.home_losses} | Streak: {_streak_str(home.current_streak)} | L10: {home.last_10_wins}-{home.last_10_losses}")
    lines.append("")

    lines.append(f"{away.team_abbreviation}: {away.wins}-{away.losses} ({away.win_percentage:.3f})")
    lines.append(f"  Net Rating: {away.net_rating:+.1f} (rank #{away.net_rating_rank})")
    lines.append(f"  ORtg: {away.offensive_rating:.1f} (#{away.offensive_rating_rank}) | DRtg: {away.defensive_rating:.1f} (#{away.defensive_rating_rank})")
    lines.append(f"  Away: {away.away_wins}-{away.away_losses} | Streak: {_streak_str(away.current_streak)} | L10: {away.last_10_wins}-{away.last_10_losses}")

    # Injuries
    home_out = home_ctx.key_players_out
    away_out = away_ctx.key_players_out
    if home_out or away_out:
        lines.append("")
        lines.append("Injuries (OUT/Doubtful):")
        for inj in home_out:
            stat_note = ""
            if inj.player_stats:
                s = inj.player_stats
                stat_note = f" ({s.points_per_game:.1f}/{s.rebounds_per_game:.1f}/{s.assists_per_game:.1f}, EIR {s.estimated_impact_rating:.1f})"
            lines.append(f"  {home.team_abbreviation}: {inj.player_name}{stat_note} — {inj.injury_description}")
        for inj in away_out:
            stat_note = ""
            if inj.player_stats:
                s = inj.player_stats
                stat_note = f" ({s.points_per_game:.1f}/{s.rebounds_per_game:.1f}/{s.assists_per_game:.1f}, EIR {s.estimated_impact_rating:.1f})"
            lines.append(f"  {away.team_abbreviation}: {inj.player_name}{stat_note} — {inj.injury_description}")

    # Active Depth (bench stepping up when starters are injured)
    if home_out or away_out:
        depth_lines: list[str] = []
        for ctx, abbr, team_out in [
            (home_ctx, home.team_abbreviation, home_out),
            (away_ctx, away.team_abbreviation, away_out),
        ]:
            if not team_out:
                continue
            injured_names = {inj.player_name for inj in ctx.injuries}
            bench_depth = _get_bench_depth(ctx.player_stats_map, injured_names)
            for ps in bench_depth:
                label = "quality" if ps.estimated_impact_rating >= 15 else "solid"
                depth_lines.append(
                    f"  {abbr}: {ps.player_name} "
                    f"({ps.points_per_game:.1f} PPG, {ps.minutes_per_game:.0f} min "
                    f"-> EIR {ps.estimated_impact_rating:.1f}) — {label} backup"
                )
        if depth_lines:
            lines.append("")
            lines.append("Active Depth (bench stepping up):")
            lines.extend(depth_lines)

    # Advanced Stats Matchup (when eFG% data available)
    if home.effective_field_goal_percentage > 0 and away.effective_field_goal_percentage > 0:
        lines.append("")
        lines.append("Advanced Stats Matchup:")

        def _edge(val: float) -> str:
            if val > 1.0:
                return " ◀"
            elif val < -1.0:
                return " ▶"
            return ""

        efg_diff = (home.effective_field_goal_percentage - away.effective_field_goal_percentage) * 100
        lines.append(
            f"  eFG%:   {home.team_abbreviation} {home.effective_field_goal_percentage*100:.1f}%  vs  "
            f"{away.team_abbreviation} {away.effective_field_goal_percentage*100:.1f}%{_edge(efg_diff)}"
        )

        if home.true_shooting_percentage > 0 and away.true_shooting_percentage > 0:
            ts_diff = (home.true_shooting_percentage - away.true_shooting_percentage) * 100
            lines.append(
                f"  TS%:    {home.team_abbreviation} {home.true_shooting_percentage*100:.1f}%  vs  "
                f"{away.team_abbreviation} {away.true_shooting_percentage*100:.1f}%{_edge(ts_diff)}"
            )

        if home.turnover_pct > 0 and away.turnover_pct > 0:
            # Lower TOV% is better, so negate for edge indicator
            tov_diff = -(home.turnover_pct - away.turnover_pct) * 100
            lines.append(
                f"  TOV%:   {home.team_abbreviation} {home.turnover_pct*100:.1f}%  vs  "
                f"{away.team_abbreviation} {away.turnover_pct*100:.1f}%{_edge(tov_diff)}"
            )

        if home.assist_to_turnover > 0 and away.assist_to_turnover > 0:
            ast_diff = home.assist_to_turnover - away.assist_to_turnover
            lines.append(
                f"  AST/TO: {home.team_abbreviation} {home.assist_to_turnover:.2f}  vs  "
                f"{away.team_abbreviation} {away.assist_to_turnover:.2f}{_edge(ast_diff * 3)}"
            )

        if home.offensive_rebound_pct > 0 and away.offensive_rebound_pct > 0:
            oreb_diff = (home.offensive_rebound_pct - away.offensive_rebound_pct) * 100
            lines.append(
                f"  OREB%:  {home.team_abbreviation} {home.offensive_rebound_pct*100:.1f}%  vs  "
                f"{away.team_abbreviation} {away.offensive_rebound_pct*100:.1f}%{_edge(oreb_diff)}"
            )

        lines.append(
            f"  Pace:   {home.team_abbreviation} {home.pace:.1f}  vs  "
            f"{away.team_abbreviation} {away.pace:.1f}"
        )

    # Rotation Strength (when player data available)
    home_players = list(home_ctx.player_stats_map.values())
    away_players = list(away_ctx.player_stats_map.values())
    if home_players and away_players:
        def _avg_eir(players: list[PlayerSeasonStats], min_mpg: float, max_count: int) -> float:
            eligible = sorted(
                [p for p in players if p.minutes_per_game >= min_mpg],
                key=lambda p: p.minutes_per_game, reverse=True,
            )[:max_count]
            return sum(p.estimated_impact_rating for p in eligible) / len(eligible) if eligible else 0.0

        def _bench_avg_eir(players: list[PlayerSeasonStats]) -> float:
            bench = [p for p in players if p.is_bench and p.estimated_impact_rating > 0]
            return sum(p.estimated_impact_rating for p in bench) / len(bench) if bench else 0.0

        h_starter = _avg_eir(home_players, 24, 5)
        a_starter = _avg_eir(away_players, 24, 5)
        h_top8 = _avg_eir(home_players, 0, 8)
        a_top8 = _avg_eir(away_players, 0, 8)
        h_bench = _bench_avg_eir(home_players)
        a_bench = _bench_avg_eir(away_players)

        if h_top8 > 0 or a_top8 > 0:
            lines.append("")
            lines.append("Rotation Strength (avg EIR):")
            lines.append(
                f"  Starters: {home.team_abbreviation} {h_starter:.1f}  vs  "
                f"{away.team_abbreviation} {a_starter:.1f}"
            )
            lines.append(
                f"  Top-8:    {home.team_abbreviation} {h_top8:.1f}  vs  "
                f"{away.team_abbreviation} {a_top8:.1f}"
            )
            lines.append(
                f"  Bench:    {home.team_abbreviation} {h_bench:.1f}  vs  "
                f"{away.team_abbreviation} {a_bench:.1f}"
            )

    # H2H
    if h2h is not None and h2h.games_played > 0:
        lines.append("")
        lines.append(f"Head-to-Head this season: {h2h.team1_wins}-{h2h.team2_wins} ({h2h.games_played} games)")
        lines.append(f"  Avg margin: {h2h.team1_avg_margin:+.1f} (home perspective)")

    return "\n".join(lines)


def _build_market_context(market_home_price: float) -> str:
    """Build the market context section."""
    away_price = 1.0 - market_home_price
    lines: list[str] = [
        f"Polymarket home price: {market_home_price:.1%} (implied odds)",
        f"Polymarket away price: {away_price:.1%} (implied odds)",
    ]
    return "\n".join(lines)


def _build_quant_analysis(
    estimate: PreGameEstimate,
    bankroll: Optional[float] = None,
    home_ctx: Optional[TeamContext] = None,
    away_ctx: Optional[TeamContext] = None,
) -> str:
    """Build the quantitative analysis section."""
    lines: list[str] = [
        f"Model home win probability: {estimate.model_prob:.1%}",
        f"Market home win probability: {estimate.market_prob:.1%}",
        f"Blended probability: {estimate.blended_prob:.1%}",
        f"Edge (blended - market): {estimate.edge_percent:+.1f}%",
        f"Verdict: {estimate.verdict}",
        f"Confidence: {estimate.confidence}/10",
    ]

    if bankroll is not None:
        lines.append(f"Available bankroll: ${bankroll:.2f} USDC")
        lines.append(f"Base Kelly bet: ${estimate.suggested_bet_usdc:.2f} ({estimate.kelly_fraction:.1%} of bankroll)")

    if estimate.strength_output:
        so = estimate.strength_output
        lines.append(f"Strength score: {so.score:+d}")
        lines.append(f"Tiers: {so.tiers.home_tier} vs {so.tiers.away_tier} (mismatch: {so.tiers.mismatch_level})")

        if so.advanced_stats and so.advanced_stats.has_data:
            adv = so.advanced_stats
            lines.append(
                f"Four Factors score: {adv.four_factors_score:+.1f} "
                f"(eFG% {adv.efg_diff:+.1f}, TOV% {adv.tov_diff:+.1f}, OREB% {adv.oreb_diff:+.1f})"
            )

        if so.rotation and so.rotation.has_data:
            rot = so.rotation
            lines.append(
                f"Rotation score: {rot.rotation_score:+.1f} "
                f"(top-8 EIR: {rot.home_top8_avg_eir:.1f} vs {rot.away_top8_avg_eir:.1f})"
            )

    # Bench depth EIR averages (when injuries exist)
    if home_ctx and away_ctx:
        home_out = home_ctx.key_players_out
        away_out = away_ctx.key_players_out
        if home_out or away_out:
            home_bench = _get_bench_depth(
                home_ctx.player_stats_map,
                {inj.player_name for inj in home_ctx.injuries},
            )
            away_bench = _get_bench_depth(
                away_ctx.player_stats_map,
                {inj.player_name for inj in away_ctx.injuries},
            )
            home_avg = (
                sum(p.estimated_impact_rating for p in home_bench) / len(home_bench)
                if home_bench else 0.0
            )
            away_avg = (
                sum(p.estimated_impact_rating for p in away_bench) / len(away_bench)
                if away_bench else 0.0
            )

            def _depth_label(avg: float) -> str:
                if avg >= 16:
                    return "strong"
                elif avg >= 12:
                    return "solid"
                elif avg > 0:
                    return "thin"
                return "n/a"

            lines.append(
                f"Bench depth: HOME EIR avg {home_avg:.1f} ({_depth_label(home_avg)}) "
                f"| AWAY EIR avg {away_avg:.1f} ({_depth_label(away_avg)})"
            )

    if estimate.factors_summary:
        lines.append("")
        lines.append("Key factors:")
        for f in estimate.factors_summary:
            lines.append(f"  - {f}")

    return "\n".join(lines)


def _get_bench_depth(
    player_stats_map: dict[str, PlayerSeasonStats],
    injured_names: set[str],
) -> list[PlayerSeasonStats]:
    """Get bench players with meaningful EIR, sorted by EIR descending.

    Returns bench players (minutes < 24, not injured) with EIR >= 12.
    """
    bench: list[PlayerSeasonStats] = []
    for name, ps in player_stats_map.items():
        if name in injured_names:
            continue
        if ps.is_bench and ps.estimated_impact_rating >= 12:
            bench.append(ps)
    bench.sort(key=lambda p: p.estimated_impact_rating, reverse=True)
    return bench


def _streak_str(streak: int) -> str:
    """Format streak as 'W3' or 'L2'."""
    if streak > 0:
        return f"W{streak}"
    elif streak < 0:
        return f"L{abs(streak)}"
    return "—"
