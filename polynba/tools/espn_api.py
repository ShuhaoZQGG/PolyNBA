"""ESPN API CLI — query any ESPN NBA endpoint.

Usage:
    python -m polynba.tools.espn_api scoreboard [DATE]
    python -m polynba.tools.espn_api live [DATE]
    python -m polynba.tools.espn_api game GAME_ID
    python -m polynba.tools.espn_api game-context GAME_ID
    python -m polynba.tools.espn_api team-stats TEAM
    python -m polynba.tools.espn_api roster TEAM
    python -m polynba.tools.espn_api injuries [TEAM]
    python -m polynba.tools.espn_api standings
    python -m polynba.tools.espn_api athlete ATHLETE_ID
    python -m polynba.tools.espn_api schedule TEAM [SEASON]
    python -m polynba.tools.espn_api head-to-head TEAM1 TEAM2
    python -m polynba.tools.espn_api play-by-play GAME_ID
"""

import asyncio
import dataclasses
import json
import sys
from datetime import datetime
from decimal import Decimal
from enum import Enum

from polynba.data.espn_teams import ESPN_TEAMS, lookup_team
from polynba.data.manager import DataManager
from polynba.data.sources.espn.client import ESPNClient
from polynba.data.sources.espn.parser import ESPNParser
from polynba.data.sources.espn.scraper import ESPNScraper


def _json_default(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Enum):
        return obj.name
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dump(data):
    print(json.dumps(data, indent=2, default=_json_default))


def _resolve_team(query):
    result = lookup_team(query)
    if not result:
        _dump({"error": f"Unknown team: {query}. Valid: {', '.join(sorted(ESPN_TEAMS))}"})
        sys.exit(1)
    return result


async def cmd_scoreboard(args):
    date = args[0] if args else None
    scraper = ESPNScraper()
    try:
        games = await scraper.get_all_games(date)
        _dump([dataclasses.asdict(g) for g in games])
    finally:
        await scraper.close()


async def cmd_live(args):
    date = args[0] if args else None
    scraper = ESPNScraper()
    try:
        games = await scraper.get_live_games(date)
        _dump([dataclasses.asdict(g) for g in games])
    finally:
        await scraper.close()


async def cmd_game(args):
    if not args:
        _dump({"error": "Usage: game GAME_ID"})
        sys.exit(1)
    scraper = ESPNScraper()
    try:
        state = await scraper.get_game_state(args[0])
        _dump(dataclasses.asdict(state) if state else None)
    finally:
        await scraper.close()


async def cmd_game_context(args):
    if not args:
        _dump({"error": "Usage: game-context GAME_ID"})
        sys.exit(1)
    scraper = ESPNScraper()
    try:
        game_state, team_stats = await scraper.get_game_with_context(args[0])
        _dump({
            "game_state": dataclasses.asdict(game_state) if game_state else None,
            "team_stats": {
                tid: dataclasses.asdict(ts) if ts else None
                for tid, ts in team_stats.items()
            },
        })
    finally:
        await scraper.close()


async def cmd_team_stats(args):
    if not args:
        _dump({"error": "Usage: team-stats TEAM"})
        sys.exit(1)
    _abbr, team_id = _resolve_team(args[0])
    dm = DataManager()
    try:
        stats = await dm.get_team_stats(team_id)
        _dump(dataclasses.asdict(stats) if stats else None)
    finally:
        await dm.close()


async def cmd_roster(args):
    if not args:
        _dump({"error": "Usage: roster TEAM"})
        sys.exit(1)
    _abbr, team_id = _resolve_team(args[0])
    client = ESPNClient()
    try:
        raw = await client.get_team_roster(team_id)
        players = ESPNParser.parse_team_roster(raw)
        _dump(players)
    finally:
        await client.close()


async def cmd_injuries(args):
    team_filter = args[0] if args else None
    scraper = ESPNScraper()
    try:
        all_injuries = await scraper.get_all_injuries()
        if team_filter:
            _abbr, team_id = _resolve_team(team_filter)
            injuries = all_injuries.get(team_id, [])
            _dump([dataclasses.asdict(inj) for inj in injuries])
        else:
            _dump({
                tid: [dataclasses.asdict(inj) for inj in injs]
                for tid, injs in all_injuries.items()
            })
    finally:
        await scraper.close()


async def cmd_standings(args):
    client = ESPNClient()
    try:
        raw = await client.get_standings()
        rankings = ESPNParser.parse_standings(raw)
        _dump(rankings)
    finally:
        await client.close()


async def cmd_athlete(args):
    if not args:
        _dump({"error": "Usage: athlete ATHLETE_ID"})
        sys.exit(1)
    client = ESPNClient()
    try:
        raw = await client.get_athlete_overview(args[0])
        parsed = ESPNParser.parse_athlete_overview(raw)
        _dump(parsed)
    finally:
        await client.close()


async def cmd_schedule(args):
    if not args:
        _dump({"error": "Usage: schedule TEAM [SEASON]"})
        sys.exit(1)
    _abbr, team_id = _resolve_team(args[0])
    season = int(args[1]) if len(args) > 1 else None
    client = ESPNClient()
    try:
        raw = await client.get_team_schedule(team_id, season)
        _dump(raw)
    finally:
        await client.close()


async def cmd_head_to_head(args):
    if len(args) < 2:
        _dump({"error": "Usage: head-to-head TEAM1 TEAM2"})
        sys.exit(1)
    _abbr1, id1 = _resolve_team(args[0])
    _abbr2, id2 = _resolve_team(args[1])
    dm = DataManager()
    try:
        h2h = await dm.get_head_to_head(id1, id2)
        _dump(dataclasses.asdict(h2h) if h2h else None)
    finally:
        await dm.close()


async def cmd_play_by_play(args):
    if not args:
        _dump({"error": "Usage: play-by-play GAME_ID"})
        sys.exit(1)
    client = ESPNClient()
    try:
        raw = await client.get_play_by_play(args[0])
        # Parse all plays from drives data
        drives = raw.get("drives", {})
        all_drives = drives.get("previous", [])
        current = drives.get("current")
        if current:
            all_drives = all_drives + [current]
        all_plays = []
        for drive in all_drives:
            for play_data in drive.get("plays", []):
                try:
                    play = ESPNParser._parse_play_event(play_data, "")
                    if play:
                        all_plays.append(play)
                except Exception:
                    pass
        _dump([dataclasses.asdict(p) for p in all_plays])
    finally:
        await client.close()


COMMANDS = {
    "scoreboard": cmd_scoreboard,
    "live": cmd_live,
    "game": cmd_game,
    "game-context": cmd_game_context,
    "team-stats": cmd_team_stats,
    "roster": cmd_roster,
    "injuries": cmd_injuries,
    "standings": cmd_standings,
    "athlete": cmd_athlete,
    "schedule": cmd_schedule,
    "head-to-head": cmd_head_to_head,
    "play-by-play": cmd_play_by_play,
}


async def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        _dump({"error": f"Usage: espn_api <subcommand> [args...]\nSubcommands: {', '.join(COMMANDS)}"})
        sys.exit(1)
    try:
        await COMMANDS[sys.argv[1]](sys.argv[2:])
    except Exception as e:
        _dump({"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
