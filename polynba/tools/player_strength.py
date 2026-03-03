"""Player strength CLI — show rotation EIR, per-36, and bench classification.

Usage:
    python -m polynba.tools.player_strength --team LAL
    python -m polynba.tools.player_strength --player "LeBron"
    python -m polynba.tools.player_strength --team BOS --top 10
    python -m polynba.tools.player_strength --snapshot
    python -m polynba.tools.player_strength --team HOU --from-snapshot polynba/data/snapshots/players_20260228.json
"""

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_PACIFIC = timezone(timedelta(hours=-8))


def _today_pacific() -> date:
    """Today's date in US Pacific (UTC-8) time."""
    return datetime.now(_PACIFIC).date()

from polynba.data.espn_teams import ESPN_TEAMS, TEAM_NAMES, lookup_team
from polynba.data.manager import DataManager
from polynba.data.models import PlayerSeasonStats


def _normalize(text: str) -> str:
    """Strip diacritics for search matching."""
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Player strength lookup")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--team", type=str, help="Team abbreviation (e.g. LAL)")
    group.add_argument("--player", type=str, help="Player name substring search")
    group.add_argument("--snapshot", nargs="?", const="", metavar="PATH",
                       help="Download all teams to a snapshot JSON file (default: polynba/data/snapshots/players_YYYYMMDD.json)")
    parser.add_argument("--from-snapshot", type=str, metavar="PATH",
                        help="Load player data from a snapshot file instead of API")
    parser.add_argument("--top", type=int, default=8, help="Number of players to show (default 8)")
    parser.add_argument("--log-level", default="WARNING", help="Logging verbosity")
    return parser.parse_args()


def format_role(ps: PlayerSeasonStats) -> str:
    if ps.minutes_per_game <= 0:
        return "—"
    return "Bench" if ps.is_bench else "Starter"


def _fmt_pct(val: float) -> str:
    """Format a fraction as percentage string, or '-' if not available."""
    if val > 0:
        return f"{val * 100:.1f}"
    return "  —"


def _fmt_rating(val: float) -> str:
    """Format a rating value, or '-' if not available."""
    if val != 0.0:
        return f"{val:+.1f}"
    return "  —"


def print_player_table(players: list[PlayerSeasonStats], title: str) -> None:
    print(f"\n{'═' * 3} {title} {'═' * 3}\n")

    header = (
        f" {'#':>2}  {'Player':<22} {'Pos':<5} {'PPG':>5} {'RPG':>5} {'APG':>5} "
        f"{'MIN':>5} {'TS%':>5} {'USG%':>5} {'NR':>5} {'EIR':>6} {'Role':<8}"
    )
    print(header)
    print(" " + "─" * (len(header) - 1))

    starters_eir: list[float] = []
    bench_eir: list[float] = []
    best_bench: PlayerSeasonStats | None = None

    for i, ps in enumerate(players, 1):
        eir = ps.estimated_impact_rating
        role = format_role(ps)
        ts_str = _fmt_pct(ps.true_shooting_pct)
        usg_str = _fmt_pct(ps.usage_pct)
        nr_str = _fmt_rating(ps.net_rating)

        print(
            f" {i:>2}  {ps.player_name:<22} {ps.position:<5} "
            f"{ps.points_per_game:>5.1f} {ps.rebounds_per_game:>5.1f} {ps.assists_per_game:>5.1f} "
            f"{ps.minutes_per_game:>5.1f} {ts_str:>5} {usg_str:>5} {nr_str:>5} "
            f"{eir:>6.1f}   {role:<8}"
        )

        if ps.minutes_per_game > 0:
            if ps.is_bench:
                bench_eir.append(eir)
                if best_bench is None or eir > best_bench.estimated_impact_rating:
                    best_bench = ps
            else:
                starters_eir.append(eir)

    # Advanced stats detail section
    has_advanced = any(ps.offensive_rating != 0.0 for ps in players)
    if has_advanced:
        print(f"\n{'─' * 3} Advanced Stats {'─' * 3}\n")
        adv_header = (
            f" {'#':>2}  {'Player':<22} {'OFFRTG':>6} {'DEFRTG':>6} {'AST%':>5} "
            f"{'AST/TO':>6} {'OREB%':>5} {'DREB%':>5} {'REB%':>5} {'PIE':>5}"
        )
        print(adv_header)
        print(" " + "─" * (len(adv_header) - 1))

        for i, ps in enumerate(players, 1):
            print(
                f" {i:>2}  {ps.player_name:<22} "
                f"{ps.offensive_rating:>6.1f} {ps.defensive_rating:>6.1f} "
                f"{_fmt_pct(ps.assist_pct):>5} {ps.assist_to_turnover:>6.1f} "
                f"{_fmt_pct(ps.offensive_rebound_pct):>5} "
                f"{_fmt_pct(ps.defensive_rebound_pct):>5} "
                f"{_fmt_pct(ps.rebound_pct):>5} "
                f"{_fmt_pct(ps.player_impact_estimate):>5}"
            )

    # Summary
    print()
    print("Summary:")
    avg_s = sum(starters_eir) / len(starters_eir) if starters_eir else 0
    avg_b = sum(bench_eir) / len(bench_eir) if bench_eir else 0
    print(f"  Avg starter EIR: {avg_s:.1f} | Avg bench EIR: {avg_b:.1f}")

    all_players = sorted(players, key=lambda p: p.estimated_impact_rating, reverse=True)
    if all_players:
        top = all_players[0]
        print(f"  Top EIR: {top.player_name} ({top.estimated_impact_rating:.1f})")
    if best_bench:
        print(f"  Best bench player: {best_bench.player_name} (EIR {best_bench.estimated_impact_rating:.1f})")


# ---------------------------------------------------------------------------
# Snapshot save / load
# ---------------------------------------------------------------------------

def _default_snapshot_path() -> str:
    """Return default snapshot path: polynba/data/snapshots/players_YYYYMMDD.json"""
    base = Path(__file__).resolve().parent.parent / "data" / "snapshots"
    return str(base / f"players_{_today_pacific().strftime('%Y%m%d')}.json")


def save_snapshot(
    player_index: dict[str, list[PlayerSeasonStats]], path: str
) -> str:
    """Serialize player index to a JSON snapshot file.

    Returns the absolute path written.
    """
    teams: dict[str, list[dict]] = {}
    total_players = 0
    for team_abbr in sorted(player_index):
        team_list = []
        for ps in player_index[team_abbr]:
            team_list.append(dataclasses.asdict(ps))
        teams[team_abbr] = team_list
        total_players += len(team_list)

    snapshot = {
        "date": _today_pacific().isoformat(),
        "player_count": total_players,
        "teams": teams,
    }

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
    return os.path.abspath(path)


def load_snapshot(path: str) -> dict[str, list[PlayerSeasonStats]]:
    """Load a snapshot JSON file and reconstruct PlayerSeasonStats objects."""
    with open(path) as f:
        snapshot = json.load(f)

    result: dict[str, list[PlayerSeasonStats]] = {}
    teams = snapshot.get("teams", {})

    for team_abbr, players_data in teams.items():
        players: list[PlayerSeasonStats] = []
        for d in players_data:
            players.append(PlayerSeasonStats(**d))
        result[team_abbr] = players

    return result


# ---------------------------------------------------------------------------
# Daily snapshot cache
# ---------------------------------------------------------------------------

async def _auto_player_index(from_snapshot: str | None = None) -> dict[str, list[PlayerSeasonStats]]:
    """Load player data from snapshot cache or fetch fresh.

    Resolution order:
    1. Explicit --from-snapshot path
    2. Today's snapshot (daily cache, keyed by Pacific date)
    3. Fresh API fetch -> saved as today's snapshot
    """
    if from_snapshot:
        return load_snapshot(from_snapshot)

    today_path = _default_snapshot_path()
    if os.path.exists(today_path):
        print(f"  (using cached snapshot: {os.path.basename(today_path)})")
        return load_snapshot(today_path)

    # No cache — fetch and save
    dm = DataManager()
    try:
        print("Fetching all players (3 NBA.com calls)...")
        player_index = await dm.get_all_players_full()
        if player_index:
            abs_path = save_snapshot(player_index, today_path)
            print(f"  Snapshot cached: {abs_path}")
        return player_index
    finally:
        await dm.close()


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

async def run_snapshot(path: str | None, top_n: int) -> None:
    """Download all teams and save to a snapshot file."""
    snapshot_path = path if path else _default_snapshot_path()

    dm = DataManager()
    try:
        print("Fetching all players (3 NBA.com calls)...")
        player_index = await dm.get_all_players_full()

        if not player_index:
            print("Error: No player data returned")
            sys.exit(1)

        abs_path = save_snapshot(player_index, snapshot_path)

        total_players = sum(len(v) for v in player_index.values())
        print(f"\nSnapshot saved: {abs_path}")
        print(f"  {len(player_index)} teams, {total_players} players")

        # Print top 5 by EIR per team summary
        print(f"\n{'═' * 3} Top {top_n} EIR per team {'═' * 3}\n")
        for team_abbr in sorted(player_index):
            players = sorted(
                player_index[team_abbr],
                key=lambda p: p.estimated_impact_rating,
                reverse=True,
            )[:top_n]
            names = ", ".join(
                f"{p.player_name} ({p.estimated_impact_rating:.1f})"
                for p in players[:5]
            )
            full_name = TEAM_NAMES.get(team_abbr, team_abbr)
            print(f"  {full_name:<25} {names}")
    finally:
        await dm.close()


async def run_team(abbr: str, top_n: int, from_snapshot: str | None = None) -> None:
    result = lookup_team(abbr)
    if not result:
        print(f"Error: Unknown team '{abbr}'. Valid: {', '.join(sorted(ESPN_TEAMS))}")
        sys.exit(1)

    team_abbr, team_id = result
    full_name = TEAM_NAMES.get(team_abbr, team_abbr)

    player_index = await _auto_player_index(from_snapshot)
    team_players = player_index.get(team_abbr, [])
    if not team_players:
        print(f"No player data found for {team_abbr}")
        return
    players = sorted(team_players, key=lambda p: p.points_per_game, reverse=True)[:top_n]
    print_player_table(players, f"Player Strength: {full_name} ({team_abbr})")


async def run_player(name_query: str, top_n: int, from_snapshot: str | None = None) -> None:
    player_index = await _auto_player_index(from_snapshot)

    q = _normalize(name_query)

    # Search across all teams (normalize to handle diacritics)
    matches: list[PlayerSeasonStats] = []
    for team_abbr, players in player_index.items():
        for ps in players:
            if q in _normalize(ps.player_name):
                matches.append(ps)

    if not matches:
        print(f"No players found matching '{name_query}'")
        return

    matches.sort(key=lambda p: p.points_per_game, reverse=True)
    matches = matches[:top_n]
    print_player_table(matches, f"Player Strength: '{name_query}' search")


async def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))

    if args.snapshot is not None:
        await run_snapshot(args.snapshot or None, args.top)
    elif args.team:
        await run_team(args.team, args.top, args.from_snapshot)
    else:
        await run_player(args.player, args.top, args.from_snapshot)


if __name__ == "__main__":
    asyncio.run(main())
