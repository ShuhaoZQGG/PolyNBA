"""Team strength CLI — season stats, injuries, rotation, matchup, snapshot & rankings.

Usage:
    python -m polynba.tools.team_strength LAL
    python -m polynba.tools.team_strength LAL SAC
    python -m polynba.tools.team_strength --snapshot
    python -m polynba.tools.team_strength --rankings offensive_rating
    python -m polynba.tools.team_strength LAL --from-snapshot polynba/data/snapshots/teams_20260228.json
"""

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_PACIFIC = timezone(timedelta(hours=-8))


def _today_pacific() -> date:
    """Today's date in US Pacific (UTC-8) time."""
    return datetime.now(_PACIFIC).date()

from polynba.analysis.factors.team_strength import TeamStrengthFactor, TeamStrengthInput
from polynba.data.espn_teams import ESPN_TEAMS, TEAM_NAMES, lookup_team
from polynba.data.manager import DataManager
from polynba.data.models import PlayerSeasonStats, TeamContext, TeamStats


# ---------------------------------------------------------------------------
# Ranking metrics
# ---------------------------------------------------------------------------

RANKING_METRICS: dict[str, tuple[str, bool, bool]] = {
    # metric_name: (display_label, higher_is_better, is_fraction)
    "net_rating": ("Net Rtg", True, False),
    "offensive_rating": ("ORtg", True, False),
    "defensive_rating": ("DRtg", False, False),
    "effective_field_goal_percentage": ("eFG%", True, True),
    "true_shooting_percentage": ("TS%", True, True),
    "pace": ("Pace", True, False),
    "team_pie": ("PIE", True, True),
    "assist_to_turnover": ("AST/TO", True, False),
    "turnover_pct": ("TOV%", False, True),
    "rebound_percentage": ("REB%", True, True),
    "win_percentage": ("Win%", True, True),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Team strength lookup")
    parser.add_argument("teams", nargs="*", help="Team abbreviation(s): TEAM or TEAM1 TEAM2")
    parser.add_argument(
        "--snapshot", nargs="?", const="", metavar="PATH",
        help="Fetch all 30 teams and save to snapshot JSON (default: polynba/data/snapshots/teams_YYYYMMDD.json)",
    )
    parser.add_argument(
        "--rankings", nargs="?", const="net_rating", metavar="METRIC",
        help=f"Rank all 30 teams by metric (default: net_rating). Options: {', '.join(RANKING_METRICS)}",
    )
    parser.add_argument(
        "--from-snapshot", type=str, metavar="PATH",
        help="Load team data from a snapshot file instead of API",
    )
    parser.add_argument("--top", type=int, default=30, help="Number of teams to show in rankings (default: 30)")
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

    # Advanced stats from NBA.com
    has_advanced_team = s.effective_field_goal_percentage > 0 or s.team_pie > 0
    if has_advanced_team:
        print(f"\nAdvanced Stats:")
        efg_str = f"{s.effective_field_goal_percentage * 100:.1f}%" if s.effective_field_goal_percentage > 0 else "—"
        ts_str = f"{s.true_shooting_percentage * 100:.1f}%" if s.true_shooting_percentage > 0 else "—"
        ast_str = f"{s.assist_pct * 100:.1f}%" if s.assist_pct > 0 else "—"
        astto_str = f"{s.assist_to_turnover:.2f}" if s.assist_to_turnover > 0 else "—"
        oreb_str = f"{s.offensive_rebound_pct * 100:.1f}%" if s.offensive_rebound_pct > 0 else "—"
        dreb_str = f"{s.defensive_rebound_pct * 100:.1f}%" if s.defensive_rebound_pct > 0 else "—"
        reb_str = f"{s.rebound_percentage * 100:.1f}%" if s.rebound_percentage > 0 else "—"
        tov_str = f"{s.turnover_pct * 100:.1f}%" if s.turnover_pct > 0 else "—"
        pie_str = f"{s.team_pie * 100:.1f}%" if s.team_pie > 0 else "—"

        def _rank(r: int) -> str:
            return f" (#{r})" if r > 0 else ""

        print(f"  eFG%: {efg_str}{_rank(s.effective_fg_pct_rank)} | TS%: {ts_str}{_rank(s.true_shooting_pct_rank)}")
        print(f"  AST%: {ast_str}{_rank(s.assist_pct_rank)} | AST/TO: {astto_str}{_rank(s.assist_to_turnover_rank)}")
        print(f"  OREB%: {oreb_str} | DREB%: {dreb_str} | REB%: {reb_str}{_rank(s.rebound_pct_rank)}")
        print(f"  TOV%: {tov_str}{_rank(s.turnover_pct_rank)} | PIE: {pie_str}{_rank(s.pie_rank)}")

        # Four Factors spotlight
        print(f"\nFour Factors:")
        print(f"  Shooting (eFG%): {efg_str}{_rank(s.effective_fg_pct_rank)}")
        print(f"  Turnovers (TOV%): {tov_str}{_rank(s.turnover_pct_rank)}")
        print(f"  Rebounding (OREB%): {oreb_str}")
        print(f"  Free Throws (FT%): {s.free_throw_percentage:.1f}%")

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

    # Advanced comparison rows (only if data available)
    has_adv = h.effective_field_goal_percentage > 0 or a.effective_field_goal_percentage > 0
    if has_adv:
        def _pct(v: float) -> str:
            return f"{v * 100:.1f}%" if v > 0 else "—"
        def _ratio(v: float) -> str:
            return f"{v:.2f}" if v > 0 else "—"

        rows.append(("eFG%", _pct(h.effective_field_goal_percentage), _pct(a.effective_field_goal_percentage)))
        rows.append(("TS%", _pct(h.true_shooting_percentage), _pct(a.true_shooting_percentage)))
        rows.append(("AST/TO", _ratio(h.assist_to_turnover), _ratio(a.assist_to_turnover)))
        rows.append(("TOV%", _pct(h.turnover_pct), _pct(a.turnover_pct)))
        rows.append(("REB%", _pct(h.rebound_percentage), _pct(a.rebound_percentage)))
        rows.append(("PIE", _pct(h.team_pie), _pct(a.team_pie)))

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


# ---------------------------------------------------------------------------
# Snapshot save / load
# ---------------------------------------------------------------------------

def _default_snapshot_path() -> str:
    """Return default snapshot path: polynba/data/snapshots/teams_YYYYMMDD.json"""
    base = Path(__file__).resolve().parent.parent / "data" / "snapshots"
    return str(base / f"teams_{_today_pacific().strftime('%Y%m%d')}.json")


def _json_serial(obj: object) -> str:
    """JSON serializer for datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def save_team_snapshot(all_stats: dict[str, TeamStats], path: str) -> str:
    """Serialize all team stats to a JSON snapshot file.

    Returns the absolute path written.
    """
    teams: dict[str, dict] = {}
    for abbr in sorted(all_stats):
        teams[abbr] = dataclasses.asdict(all_stats[abbr])

    snapshot = {
        "date": _today_pacific().isoformat(),
        "team_count": len(teams),
        "teams": teams,
    }

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2, default=_json_serial)
    return os.path.abspath(path)


def load_team_snapshot(path: str) -> dict[str, TeamStats]:
    """Load a snapshot JSON file and reconstruct TeamStats objects."""
    with open(path) as f:
        snapshot = json.load(f)

    result: dict[str, TeamStats] = {}
    teams = snapshot.get("teams", {})

    for abbr, data in teams.items():
        # Convert ISO datetime string back to datetime
        if "last_updated" in data and isinstance(data["last_updated"], str):
            try:
                data["last_updated"] = datetime.fromisoformat(data["last_updated"])
            except (ValueError, TypeError):
                data["last_updated"] = datetime.now()
        result[abbr] = TeamStats(**data)

    return result


# ---------------------------------------------------------------------------
# Rankings display
# ---------------------------------------------------------------------------

def _fmt_metric(value: float, is_fraction: bool) -> str:
    """Format a metric value for display."""
    if is_fraction:
        return f"{value * 100:.1f}%"
    return f"{value:.1f}"


def print_rankings(
    all_stats: dict[str, TeamStats], metric: str, top_n: int = 30
) -> None:
    """Print all teams ranked by a given metric."""
    if metric not in RANKING_METRICS:
        print(f"Error: Unknown metric '{metric}'. Options: {', '.join(RANKING_METRICS)}")
        sys.exit(1)

    label, higher_is_better, is_fraction = RANKING_METRICS[metric]

    # Sort teams
    teams = sorted(
        all_stats.values(),
        key=lambda s: getattr(s, metric, 0.0),
        reverse=higher_is_better,
    )[:top_n]

    print(f"\n{'═' * 3} Team Rankings by {label} {'═' * 3}\n")

    # Header: rank, team, record, primary metric, then context columns
    context_cols = ["net_rating", "offensive_rating", "defensive_rating", "pace", "win_percentage"]
    # Remove the primary metric from context to avoid duplication
    context_cols = [c for c in context_cols if c != metric][:4]

    # Build header
    hdr = f" {'#':>2}  {'Team':<25} {'Record':>12}  {label:>8}"
    for col in context_cols:
        col_label = RANKING_METRICS[col][0]
        hdr += f"  {col_label:>8}"
    print(hdr)
    print(" " + "─" * (len(hdr) - 1))

    for i, s in enumerate(teams, 1):
        val = getattr(s, metric, 0.0)
        full_name = TEAM_NAMES.get(s.team_abbreviation, s.team_abbreviation)
        rec = format_record(s.wins, s.losses)

        row = f" {i:>2}  {full_name:<25} {rec:>12}  {_fmt_metric(val, is_fraction):>8}"
        for col in context_cols:
            col_val = getattr(s, col, 0.0)
            _, _, col_frac = RANKING_METRICS[col]
            row += f"  {_fmt_metric(col_val, col_frac):>8}"
        print(row)

    print(f"\n  {len(teams)} teams | sorted by {label} ({'desc' if higher_is_better else 'asc'})")


# ---------------------------------------------------------------------------
# Daily snapshot cache
# ---------------------------------------------------------------------------

async def _auto_team_stats(from_snapshot: str | None = None) -> dict[str, TeamStats]:
    """Load team stats from snapshot cache or fetch fresh.

    Resolution order:
    1. Explicit --from-snapshot path
    2. Today's snapshot (daily cache, keyed by Pacific date)
    3. Fresh API fetch -> saved as today's snapshot
    """
    if from_snapshot:
        return load_team_snapshot(from_snapshot)

    today_path = _default_snapshot_path()
    if os.path.exists(today_path):
        print(f"  (using cached snapshot: {os.path.basename(today_path)})")
        return load_team_snapshot(today_path)

    # No cache — fetch and save
    dm = DataManager()
    try:
        print("Fetching all 30 teams (1 NBA.com + 30 ESPN calls)...")
        all_stats = await dm.get_all_team_stats()
        if all_stats:
            abs_path = save_team_snapshot(all_stats, today_path)
            print(f"  Snapshot cached: {abs_path}")
        return all_stats
    finally:
        await dm.close()


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

async def run_snapshot(path: str | None) -> None:
    """Fetch all 30 teams and save to a snapshot file."""
    snapshot_path = path if path else _default_snapshot_path()

    dm = DataManager()
    try:
        print("Fetching all 30 teams (1 NBA.com + 30 ESPN calls)...")
        all_stats = await dm.get_all_team_stats()

        if not all_stats:
            print("Error: No team data returned")
            sys.exit(1)

        abs_path = save_team_snapshot(all_stats, snapshot_path)

        print(f"\nSnapshot saved: {abs_path}")
        print(f"  {len(all_stats)} teams")

        # Print summary table
        print(f"\n{'═' * 3} Team Snapshot Summary {'═' * 3}\n")
        teams_sorted = sorted(
            all_stats.values(),
            key=lambda s: s.net_rating,
            reverse=True,
        )
        hdr = f" {'#':>2}  {'Team':<25} {'Record':>12}  {'Net Rtg':>8}  {'ORtg':>6}  {'DRtg':>6}  {'Tier':<12}"
        print(hdr)
        print(" " + "─" * (len(hdr) - 1))
        for i, s in enumerate(teams_sorted, 1):
            full_name = TEAM_NAMES.get(s.team_abbreviation, s.team_abbreviation)
            rec = format_record(s.wins, s.losses)
            print(
                f" {i:>2}  {full_name:<25} {rec:>12}  {s.net_rating:>+8.1f}  "
                f"{s.offensive_rating:>6.1f}  {s.defensive_rating:>6.1f}  {s.strength_tier():<12}"
            )
    finally:
        await dm.close()


async def run_rankings(
    metric: str, top_n: int, from_snapshot: str | None
) -> None:
    """Show all 30 teams ranked by a metric."""
    all_stats = await _auto_team_stats(from_snapshot)
    if not all_stats:
        print("Error: No team data available")
        sys.exit(1)
    print_rankings(all_stats, metric, top_n)


async def run_single_team(
    abbr: str, team_id: str, from_snapshot: str | None
) -> None:
    """Show single team view using daily snapshot cache."""
    all_stats = await _auto_team_stats(from_snapshot)
    stats = all_stats.get(abbr)
    if not stats:
        print(f"No data for {abbr}")
        return
    ctx = TeamContext(stats=stats)
    print_single_team(ctx)


async def run_matchup(
    h_abbr: str, h_id: str, a_abbr: str, a_id: str, from_snapshot: str | None
) -> None:
    """Show matchup view using daily snapshot cache."""
    all_stats = await _auto_team_stats(from_snapshot)
    h_stats = all_stats.get(h_abbr)
    a_stats = all_stats.get(a_abbr)
    if not h_stats:
        print(f"No data for {h_abbr}")
        return
    if not a_stats:
        print(f"No data for {a_abbr}")
        return
    home_ctx = TeamContext(stats=h_stats)
    away_ctx = TeamContext(stats=a_stats)
    print_matchup(home_ctx, away_ctx)


async def run() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))

    has_teams = bool(args.teams)
    has_snapshot = args.snapshot is not None
    has_rankings = args.rankings is not None

    # Require at least one mode
    if not has_teams and not has_snapshot and not has_rankings:
        print("Error: Provide team(s), --snapshot, or --rankings")
        sys.exit(1)

    # Snapshot mode
    if has_snapshot:
        await run_snapshot(args.snapshot or None)
        return

    # Rankings mode
    if has_rankings:
        await run_rankings(args.rankings, args.top, args.from_snapshot)
        return

    # Team mode(s)
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

    if len(teams) == 1:
        abbr, team_id = teams[0]
        await run_single_team(abbr, team_id, args.from_snapshot)
    else:
        h_abbr, h_id = teams[0]
        a_abbr, a_id = teams[1]
        await run_matchup(h_abbr, h_id, a_abbr, a_id, args.from_snapshot)


if __name__ == "__main__":
    asyncio.run(run())
