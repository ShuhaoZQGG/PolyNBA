"""NBA.com API CLI — query any NBA.com endpoint.

Usage:
    python -m polynba.tools.nba_api scoreboard
    python -m polynba.tools.nba_api live
    python -m polynba.tools.nba_api boxscore GAME_ID
    python -m polynba.tools.nba_api game GAME_ID
    python -m polynba.tools.nba_api players [TEAM]
    python -m polynba.tools.nba_api players-full [TEAM]
    python -m polynba.tools.nba_api player-stats-base [SEASON]
    python -m polynba.tools.nba_api player-stats-advanced [SEASON]
    python -m polynba.tools.nba_api team-stats-advanced [SEASON]
    python -m polynba.tools.nba_api playbyplay GAME_ID
"""

import asyncio
import dataclasses
import json
import sys
from datetime import datetime
from decimal import Decimal
from enum import Enum

from polynba.data.manager import DataManager
from polynba.data.sources.nba.client import NBAClient, NBAClientError
from polynba.data.sources.nba.parser import NBAParser
from polynba.data.sources.nba.scraper import NBAScraper


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


async def cmd_scoreboard(args):
    scraper = NBAScraper()
    try:
        games = await scraper.get_all_games()
        _dump([dataclasses.asdict(g) for g in games])
    finally:
        await scraper.close()


async def cmd_live(args):
    scraper = NBAScraper()
    try:
        games = await scraper.get_live_games()
        _dump([dataclasses.asdict(g) for g in games])
    finally:
        await scraper.close()


async def cmd_boxscore(args):
    if not args:
        _dump({"error": "Usage: boxscore GAME_ID"})
        sys.exit(1)
    client = NBAClient()
    try:
        raw = await client.get_boxscore(args[0])
        state = NBAParser.parse_boxscore(raw)
        _dump(dataclasses.asdict(state) if state else None)
    except NBAClientError as e:
        if "403" in str(e):
            _dump({"error": "403 Forbidden — boxscore not available (game may not have started)"})
        else:
            _dump({"error": str(e)})
        sys.exit(1)
    finally:
        await client.close()


async def cmd_game(args):
    if not args:
        _dump({"error": "Usage: game GAME_ID"})
        sys.exit(1)
    scraper = NBAScraper()
    try:
        state = await scraper.get_game_state(args[0])
        _dump(dataclasses.asdict(state) if state else None)
    finally:
        await scraper.close()


async def cmd_players(args):
    team_filter = args[0].upper() if args else None
    dm = DataManager()
    try:
        index = await dm.get_player_index()
        if team_filter:
            players = index.get(team_filter, [])
            _dump([dataclasses.asdict(p) for p in players])
        else:
            _dump({t: [dataclasses.asdict(p) for p in ps] for t, ps in index.items()})
    finally:
        await dm.close()


async def cmd_players_full(args):
    team_filter = args[0].upper() if args else None
    dm = DataManager()
    try:
        index = await dm.get_all_players_full()
        if team_filter:
            players = index.get(team_filter, [])
            _dump([dataclasses.asdict(p) for p in players])
        else:
            _dump({t: [dataclasses.asdict(p) for p in ps] for t, ps in index.items()})
    finally:
        await dm.close()


async def cmd_player_stats_base(args):
    season = args[0] if args else "2025-26"
    client = NBAClient()
    try:
        raw = await client.get_base_player_stats(season)
        parsed = NBAParser.parse_base_player_stats(raw)
        _dump(parsed)
    finally:
        await client.close()


async def cmd_player_stats_advanced(args):
    season = args[0] if args else "2025-26"
    client = NBAClient()
    try:
        raw = await client.get_advanced_player_stats(season)
        parsed = NBAParser.parse_advanced_player_stats(raw)
        _dump(parsed)
    finally:
        await client.close()


async def cmd_team_stats_advanced(args):
    season = args[0] if args else "2025-26"
    client = NBAClient()
    try:
        raw = await client.get_advanced_team_stats(season)
        parsed = NBAParser.parse_advanced_team_stats(raw)
        _dump(parsed)
    finally:
        await client.close()


async def cmd_playbyplay(args):
    if not args:
        _dump({"error": "Usage: playbyplay GAME_ID"})
        sys.exit(1)
    client = NBAClient()
    try:
        raw = await client.get_playbyplay(args[0])
        plays = NBAParser.parse_playbyplay(raw, "")
        _dump([dataclasses.asdict(p) for p in plays])
    except NBAClientError as e:
        if "403" in str(e):
            _dump({"error": "403 Forbidden — play-by-play not available (game may not have started)"})
        else:
            _dump({"error": str(e)})
        sys.exit(1)
    finally:
        await client.close()


COMMANDS = {
    "scoreboard": cmd_scoreboard,
    "live": cmd_live,
    "boxscore": cmd_boxscore,
    "game": cmd_game,
    "players": cmd_players,
    "players-full": cmd_players_full,
    "player-stats-base": cmd_player_stats_base,
    "player-stats-advanced": cmd_player_stats_advanced,
    "team-stats-advanced": cmd_team_stats_advanced,
    "playbyplay": cmd_playbyplay,
}


async def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        _dump({"error": f"Usage: nba_api <subcommand> [args...]\nSubcommands: {', '.join(COMMANDS)}"})
        sys.exit(1)
    try:
        await COMMANDS[sys.argv[1]](sys.argv[2:])
    except Exception as e:
        _dump({"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
