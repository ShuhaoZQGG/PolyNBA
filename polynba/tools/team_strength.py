"""Team strength CLI — season stats, injuries, rotation, and matchup analysis.

Usage:
    python -m polynba.tools.team_strength LAL
    python -m polynba.tools.team_strength LAL SAC
"""

import argparse
import asyncio
import logging
import sys

from polynba.analysis.factors.team_strength import TeamStrengthFactor, TeamStrengthInput
from polynba.data.espn_teams import ESPN_TEAMS, TEAM_NAMES, lookup_team
from polynba.data.manager import DataManager
from polynba.data.models import PlayerSeasonStats, TeamContext


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Team strength lookup")
    parser.add_argument("teams", nargs="+", help="Team abbreviation(s): TEAM or TEAM1 TEAM2")
    parser.add_argument("--log-level", default="WARNING", help="Logging verbosity")
    return parser.parse_args()


def format_streak(streak: int) -> str:
    if streak > 0:
        return f"W{streak}"
    elif streak < 0:
        return f"L{-streak}"
    return "—"


def format_record(wins: int, losses: int) -> str:
    total = wins + losses
    pct = wins / total if total > 0 else 0
    return f"{wins}-{losses} (.{int(pct * 1000):03d})"


def print_single_team(ctx: TeamContext) -> None:
    s = ctx.stats
    abbr = s.team_abbreviation
    full_name = TEAM_NAMES.get(abbr, abbr)
    tier = s.strength_tier()

    print(f"\n{'═' * 3} Team Strength: {full_name} ({abbr}) {'═' * 3}\n")

    # Season line
    record = format_record(s.wins, s.losses)
    print(f"Season: {record} | Net Rating: {s.net_rating:+.1f} | Tier: {tier}")
    print(
        f"  ORtg: {s.offensive_rating:.1f} (#{s.offensive_rating_rank}) | "
        f"DRtg: {s.defensive_rating:.1f} (#{s.defensive_rating_rank}) | "
        f"Pace: {s.pace:.1f}"
    )
    home_rec = format_record(s.home_wins, s.home_losses)
    away_rec = format_record(s.away_wins, s.away_losses)
    print(f"  Home: {home_rec} | Away: {away_rec} | Streak: {format_streak(s.current_streak)}")

    # Injuries
    key_out = ctx.key_players_out
    if key_out:
        print(f"\nInjuries (OUT/Doubtful):")
        for inj in key_out:
            ps = inj.player_stats
            if ps:
                eir = ps.estimated_impact_rating
                print(
                    f"  {inj.player_name} — {ps.position}, {ps.points_per_game:.1f} PPG, "
                    f"{ps.minutes_per_game:.1f} min, EIR {eir:.1f} ({inj.injury_description})"
                )
            else:
                print(f"  {inj.player_name} — {inj.status} ({inj.injury_description})")
    else:
        print(f"\nInjuries (OUT/Doubtful): (none)")

    # Rotation
    if ctx.player_stats_map:
        rotation = sorted(
            ctx.player_stats_map.values(),
            key=lambda p: p.points_per_game,
            reverse=True,
        )[:8]

        has_advanced = any(ps.true_shooting_pct > 0 for ps in rotation)

        print(f"\nRotation (top {len(rotation)}):")
        if has_advanced:
            header = (
                f" {'#':>2}  {'Player':<22} {'Pos':<5} {'PPG':>5} {'MIN':>5} "
                f"{'TS%':>5} {'NR':>5} {'EIR':>6}   {'Role':<8}"
            )
        else:
            header = f" {'#':>2}  {'Player':<22} {'Pos':<5} {'PPG':>5} {'MIN':>5} {'EIR':>6}   {'Role':<8}"
        print(header)
        print(" " + "─" * (len(header) - 1))

        bench_eirs: list[float] = []
        for i, ps in enumerate(rotation, 1):
            eir = ps.estimated_impact_rating
            role = "Bench" if (ps.minutes_per_game > 0 and ps.is_bench) else ("Starter" if ps.minutes_per_game > 0 else "—")
            if has_advanced:
                ts_str = f"{ps.true_shooting_pct * 100:.1f}" if ps.true_shooting_pct > 0 else "  —"
                nr_str = f"{ps.net_rating:+.1f}" if ps.net_rating != 0.0 else "  —"
                print(
                    f" {i:>2}  {ps.player_name:<22} {ps.position:<5} "
                    f"{ps.points_per_game:>5.1f} {ps.minutes_per_game:>5.1f} "
                    f"{ts_str:>5} {nr_str:>5} {eir:>6.1f}   {role:<8}"
                )
            else:
                print(
                    f" {i:>2}  {ps.player_name:<22} {ps.position:<5} "
                    f"{ps.points_per_game:>5.1f} {ps.minutes_per_game:>5.1f} {eir:>6.1f}   {role:<8}"
                )
            if ps.minutes_per_game > 0 and ps.is_bench:
                bench_eirs.append(eir)

        # Per-player OFFRTG/DEFRTG detail for single-team view
        if has_advanced:
            print(f"\n  Advanced:")
            for ps in rotation:
                if ps.offensive_rating != 0.0:
                    print(
                        f"    {ps.player_name:<22} OFFRTG {ps.offensive_rating:.1f} | "
                        f"DEFRTG {ps.defensive_rating:.1f} | "
                        f"USG {ps.usage_pct * 100:.1f}% | PIE {ps.player_impact_estimate * 100:.1f}%"
                    )

        if bench_eirs:
            avg_bench = sum(bench_eirs) / len(bench_eirs)
            depth = "strong" if avg_bench >= 20 else ("average" if avg_bench >= 12 else "thin")
            print(f"\nBench Depth: avg EIR {avg_bench:.1f} ({depth})")


def print_matchup(home_ctx: TeamContext, away_ctx: TeamContext) -> None:
    h = home_ctx.stats
    a = away_ctx.stats
    h_abbr = h.team_abbreviation
    a_abbr = a.team_abbreviation
    h_name = TEAM_NAMES.get(h_abbr, h_abbr)
    a_name = TEAM_NAMES.get(a_abbr, a_abbr)

    print(f"\n{'═' * 3} Team Strength: {a_abbr} @ {h_abbr} {'═' * 3}\n")

    # Side-by-side comparison
    col_w = 18
    label_w = 20
    print(f"{'':>{label_w}} {h_abbr + ' (Home)':>{col_w}} {a_abbr + ' (Away)':>{col_w}}")

    rows = [
        ("Record", format_record(h.wins, h.losses), format_record(a.wins, a.losses)),
        ("Net Rating", f"{h.net_rating:+.1f}", f"{a.net_rating:+.1f}"),
        ("Tier", h.strength_tier(), a.strength_tier()),
        (
            "ORtg / DRtg",
            f"{h.offensive_rating:.1f} / {h.defensive_rating:.1f}",
            f"{a.offensive_rating:.1f} / {a.defensive_rating:.1f}",
        ),
        (
            "Home / Away",
            format_record(h.home_wins, h.home_losses),
            format_record(a.away_wins, a.away_losses),
        ),
        ("Streak", format_streak(h.current_streak), format_streak(a.current_streak)),
    ]
    for label, hv, av in rows:
        print(f"{label:>{label_w}} {hv:>{col_w}} {av:>{col_w}}")

    # Strength score
    factor = TeamStrengthFactor()
    input_data = TeamStrengthInput(
        home_stats=h,
        away_stats=a,
        home_context=home_ctx,
        away_context=away_ctx,
    )
    output = factor.calculate(input_data)

    advantage = "home advantage" if output.score > 0 else ("away advantage" if output.score < 0 else "even")
    print(f"\nStrength Score: {output.score:+d} ({advantage})")
    if output.tiers.mismatch_level > 0:
        print(
            f"  Tier mismatch: {output.tiers.mismatch_level} level{'s' if output.tiers.mismatch_level > 1 else ''} "
            f"({output.tiers.home_tier} vs {output.tiers.away_tier})"
        )

    # Injuries
    h_out = home_ctx.key_players_out
    a_out = away_ctx.key_players_out
    print(f"\nInjuries:")
    if h_out:
        for inj in h_out:
            eir_str = f" (EIR {inj.player_stats.estimated_impact_rating:.1f})" if inj.player_stats else ""
            print(f"  {h_abbr}: {inj.player_name}{eir_str} — {inj.status}")
    else:
        print(f"  {h_abbr}: (none)")
    if a_out:
        for inj in a_out:
            eir_str = f" (EIR {inj.player_stats.estimated_impact_rating:.1f})" if inj.player_stats else ""
            print(f"  {a_abbr}: {inj.player_name}{eir_str} — {inj.status}")
    else:
        print(f"  {a_abbr}: (none)")

    # Injury impact + replacement quality
    if output.injury_impact != 0:
        h_repl = factor._analyze_replacement_quality(home_ctx)
        a_repl = factor._analyze_replacement_quality(away_ctx)
        repl_net = h_repl - a_repl
        print(
            f"\nInjury Impact: {output.injury_impact:+d} | "
            f"Replacement offset: {repl_net:+.1f} | "
            f"Net: {output.injury_impact + repl_net:+.1f}"
        )

    print(f"Reasoning: {output.reasoning}")


async def run() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))

    # Resolve team(s)
    teams: list[tuple[str, str]] = []
    for t in args.teams:
        result = lookup_team(t)
        if not result:
            print(f"Error: Unknown team '{t}'. Valid: {', '.join(sorted(ESPN_TEAMS))}")
            sys.exit(1)
        teams.append(result)

    if len(teams) > 2:
        print("Error: Provide 1 team (single view) or 2 teams (matchup view)")
        sys.exit(1)

    dm = DataManager()
    try:
        if len(teams) == 1:
            abbr, team_id = teams[0]
            ctx = await dm.get_team_context(team_id)
            if not ctx:
                print(f"Failed to fetch data for {abbr}")
                return
            print_single_team(ctx)
        else:
            # Matchup mode: first team = home, second = away
            h_abbr, h_id = teams[0]
            a_abbr, a_id = teams[1]

            home_ctx, away_ctx = await asyncio.gather(
                dm.get_team_context(h_id, a_id),
                dm.get_team_context(a_id, h_id),
            )

            if not home_ctx:
                print(f"Failed to fetch data for {h_abbr}")
                return
            if not away_ctx:
                print(f"Failed to fetch data for {a_abbr}")
                return

            print_matchup(home_ctx, away_ctx)
    finally:
        await dm.close()


if __name__ == "__main__":
    asyncio.run(run())
