"""API validation script — tests all external API integrations and parsing.

Run with: cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.tests.validate_apis
"""

import asyncio
import json
import logging
import sys
import traceback
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

# ── Configure logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("validate_apis")
logger.setLevel(logging.INFO)


# ── Helpers ──────────────────────────────────────────────────────────
class ValidationResult:
    """Tracks pass/fail/skip for a single check."""

    def __init__(self, name: str):
        self.name = name
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    def ok(self, msg: str) -> None:
        self.passed.append(msg)

    def fail(self, msg: str) -> None:
        self.failed.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def success(self) -> bool:
        return len(self.failed) == 0


def header(title: str) -> None:
    print(f"\n{'=' * 64}")
    print(f"  {title}")
    print(f"{'=' * 64}")


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def report(vr: ValidationResult) -> None:
    status = "PASS" if vr.success else "FAIL"
    icon = "[OK]" if vr.success else "[FAIL]"
    print(f"\n{icon} {vr.name}: {status}")
    for msg in vr.passed:
        print(f"    + {msg}")
    for msg in vr.warnings:
        print(f"    ? {msg}")
    for msg in vr.failed:
        print(f"    X {msg}")


# ── ESPN API Validation ──────────────────────────────────────────────
async def validate_espn_scoreboard() -> ValidationResult:
    """Validate ESPN scoreboard endpoint and parsing."""
    from polynba.data.sources.espn.client import ESPNClient
    from polynba.data.sources.espn.parser import ESPNParser

    vr = ValidationResult("ESPN Scoreboard")
    client = ESPNClient()

    try:
        # Fetch today's scoreboard
        raw = await client.get_scoreboard()

        # Validate raw response structure
        if "events" not in raw:
            vr.fail("Response missing 'events' key")
            return vr
        vr.ok(f"Raw response has {len(raw['events'])} events")

        # Parse to GameSummary
        games = ESPNParser.parse_scoreboard(raw)
        vr.ok(f"Parsed {len(games)} GameSummary objects")

        # If no games today, try yesterday
        if not games:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            raw = await client.get_scoreboard(date=yesterday)
            games = ESPNParser.parse_scoreboard(raw)
            if games:
                vr.ok(f"No games today; found {len(games)} games yesterday ({yesterday})")
            else:
                vr.warn("No games today or yesterday — cannot validate field parsing")
                return vr

        # Validate first game fields
        g = games[0]
        if g.game_id:
            vr.ok(f"game_id present: {g.game_id}")
        else:
            vr.fail("game_id is empty")

        if g.home_team_name and g.away_team_name:
            vr.ok(f"Teams: {g.away_team_abbreviation} @ {g.home_team_abbreviation}")
        else:
            vr.fail("Team names missing")

        if g.home_team_id and g.away_team_id:
            vr.ok(f"Team IDs: home={g.home_team_id}, away={g.away_team_id}")
        else:
            vr.fail("Team IDs missing")

        if g.status is not None:
            vr.ok(f"Status parsed: {g.status.name}")
        else:
            vr.fail("Status is None")

        if g.period is not None:
            vr.ok(f"Period: {g.period.name} (value={g.period.value})")
        else:
            vr.fail("Period is None")

        # Store game_id for subsequent tests
        vr._game_id = g.game_id
        vr._home_team_id = g.home_team_id
        vr._away_team_id = g.away_team_id

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await client.close()

    return vr


async def validate_espn_game_summary(game_id: str) -> ValidationResult:
    """Validate ESPN game summary endpoint and parsing."""
    from polynba.data.sources.espn.client import ESPNClient
    from polynba.data.sources.espn.parser import ESPNParser

    vr = ValidationResult(f"ESPN Game Summary (game_id={game_id})")
    client = ESPNClient()

    try:
        raw = await client.get_game_summary(game_id)

        # Check raw structure
        if "header" not in raw:
            vr.fail("Response missing 'header' key")
            return vr
        vr.ok("Raw response has 'header'")

        has_boxscore = "boxscore" in raw
        has_drives = "drives" in raw
        vr.ok(f"boxscore present: {has_boxscore}, drives present: {has_drives}")

        # Parse to GameState
        gs = ESPNParser.parse_game_summary(raw)
        if gs is None:
            vr.fail("parse_game_summary returned None")
            return vr
        vr.ok("Parsed GameState successfully")

        # Validate core fields
        if gs.game_id == game_id:
            vr.ok(f"game_id matches: {gs.game_id}")
        else:
            vr.fail(f"game_id mismatch: expected {game_id}, got {gs.game_id}")

        vr.ok(f"Status: {gs.status.name}, Period: {gs.period.name}, Clock: {gs.clock}")
        vr.ok(f"Home: {gs.home_team.team_abbreviation} ({gs.home_team.score})")
        vr.ok(f"Away: {gs.away_team.team_abbreviation} ({gs.away_team.score})")
        vr.ok(f"Score differential: {gs.score_differential}, Total seconds remaining: {gs.total_seconds_remaining}")

        # Check team stats were parsed (only meaningful for live/final games)
        ht = gs.home_team
        if ht.field_goals_attempted > 0:
            vr.ok(f"Home FG: {ht.field_goals_made}/{ht.field_goals_attempted} ({ht.field_goal_percentage:.1%})")
        elif gs.status.name in ("IN_PROGRESS", "FINAL"):
            vr.warn("Home team FG stats are 0 for a live/final game")
        else:
            vr.ok("Home FG stats are 0 (game not started yet — expected)")

        # Check recent plays
        n_plays = len(gs.recent_plays)
        vr.ok(f"Recent plays: {n_plays}")
        if n_plays > 0:
            p = gs.recent_plays[0]
            vr.ok(f"  First play: {p.event_type.name} — {p.description[:60]}")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await client.close()

    return vr


async def validate_espn_team_stats(team_id: str) -> ValidationResult:
    """Validate ESPN team stats endpoint and parsing."""
    from polynba.data.sources.espn.client import ESPNClient
    from polynba.data.sources.espn.parser import ESPNParser

    vr = ValidationResult(f"ESPN Team Stats (team_id={team_id})")
    client = ESPNClient()

    try:
        # Fetch both endpoints
        stats_raw = await client.get_team_stats(team_id)
        info_raw = await client.get_team_info(team_id)

        # Check raw responses
        if "results" in stats_raw or "statistics" in stats_raw or "team" in stats_raw:
            vr.ok("Stats raw response has expected keys")
        else:
            vr.warn(f"Stats raw top-level keys: {list(stats_raw.keys())[:10]}")

        if "team" in info_raw:
            vr.ok("Team info raw response has 'team' key")
        else:
            vr.warn(f"Team info raw top-level keys: {list(info_raw.keys())[:10]}")

        # Parse
        ts = ESPNParser.parse_team_stats(stats_raw, team_id, team_info_data=info_raw)
        if ts is None:
            vr.fail("parse_team_stats returned None")
            return vr
        vr.ok(f"Parsed TeamStats for {ts.team_name} ({ts.team_abbreviation})")

        # Validate key fields
        if ts.wins > 0 or ts.losses > 0:
            vr.ok(f"Record: {ts.wins}-{ts.losses} ({ts.win_percentage:.3f})")
        else:
            vr.warn("Wins and losses are both 0")

        if ts.points_per_game > 0:
            vr.ok(f"PPG: {ts.points_per_game:.1f}")
        else:
            vr.warn("PPG is 0")

        if ts.offensive_rating > 0:
            vr.ok(f"Offensive rating: {ts.offensive_rating:.1f}")
        else:
            vr.warn("Offensive rating is 0 (may fall back to PPG)")

        if ts.defensive_rating > 0:
            vr.ok(f"Defensive rating: {ts.defensive_rating:.1f}")
        else:
            vr.warn("Defensive rating is 0 (may fall back to PA)")

        vr.ok(f"Net rating: {ts.net_rating:+.1f}")
        vr.ok(f"FG%: {ts.field_goal_percentage:.1f}, 3P%: {ts.three_point_percentage:.1f}, FT%: {ts.free_throw_percentage:.1f}")

        if ts.home_wins + ts.home_losses > 0:
            vr.ok(f"Home: {ts.home_wins}-{ts.home_losses}, Away: {ts.away_wins}-{ts.away_losses}")
        else:
            vr.warn("Home/away splits are 0")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await client.close()

    return vr


async def validate_espn_injuries() -> ValidationResult:
    """Validate ESPN injuries endpoint and parsing."""
    from polynba.data.sources.espn.client import ESPNClient
    from polynba.data.sources.espn.parser import ESPNParser

    vr = ValidationResult("ESPN Injuries")
    client = ESPNClient()

    try:
        raw = await client.get_injuries()

        if "injuries" not in raw:
            vr.fail("Response missing 'injuries' key")
            return vr

        n_teams = len(raw.get("injuries", []))
        vr.ok(f"Raw response has injury data for {n_teams} teams")

        injuries = ESPNParser.parse_injuries(raw)
        total_injuries = sum(len(v) for v in injuries.values())
        vr.ok(f"Parsed {total_injuries} injuries across {len(injuries)} teams")

        if total_injuries > 0:
            # Show a sample
            sample_team_id = next(iter(injuries))
            sample = injuries[sample_team_id][0]
            vr.ok(f"Sample: {sample.player_name} ({sample.status}) — {sample.injury_description[:40]}")
        else:
            vr.warn("No injuries parsed (unusual but possible)")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await client.close()

    return vr


async def validate_espn_standings() -> ValidationResult:
    """Validate ESPN standings endpoint and parsing."""
    from polynba.data.sources.espn.client import ESPNClient
    from polynba.data.sources.espn.parser import ESPNParser

    vr = ValidationResult("ESPN Standings")
    client = ESPNClient()

    try:
        raw = await client.get_standings()

        if "children" not in raw:
            vr.fail("Response missing 'children' key")
            return vr
        vr.ok(f"Raw response has {len(raw['children'])} conference groups")

        rankings = ESPNParser.parse_standings(raw)
        vr.ok(f"Parsed standings for {len(rankings)} teams")

        if len(rankings) >= 28:
            vr.ok(f"Team count is plausible ({len(rankings)} >= 28)")
        else:
            vr.warn(f"Only {len(rankings)} teams in standings (expected ~30)")

        # Validate a sample entry
        if rankings:
            sample_id = next(iter(rankings))
            entry = rankings[sample_id]
            vr.ok(f"Sample team {sample_id}: rank={entry['conference_rank']}, {entry['wins']}-{entry['losses']}")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await client.close()

    return vr


# ── NBA.com CDN Validation ───────────────────────────────────────────
async def validate_nba_scoreboard() -> ValidationResult:
    """Validate NBA.com CDN scoreboard endpoint and parsing."""
    from polynba.data.sources.nba.client import NBAClient
    from polynba.data.sources.nba.parser import NBAParser

    vr = ValidationResult("NBA.com CDN Scoreboard")
    client = NBAClient()

    try:
        raw = await client.get_scoreboard()

        if "scoreboard" not in raw:
            vr.fail("Response missing 'scoreboard' key")
            return vr
        vr.ok(f"Raw response has 'scoreboard' with {len(raw['scoreboard'].get('games', []))} games")

        games = NBAParser.parse_scoreboard(raw)
        vr.ok(f"Parsed {len(games)} GameSummary objects")

        if games:
            g = games[0]
            vr.ok(f"First game: {g.away_team_abbreviation} @ {g.home_team_abbreviation} (status={g.status.name})")
            vr.ok(f"game_id={g.game_id}, period={g.period.name}, clock={g.clock}")
            vr._nba_game_id = g.game_id
            vr._nba_game_status = g.status.name
        else:
            vr.warn("No games found on NBA.com CDN scoreboard")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await client.close()

    return vr


async def validate_nba_boxscore(game_id: str, game_status: str = "SCHEDULED") -> ValidationResult:
    """Validate NBA.com CDN boxscore endpoint and parsing."""
    from polynba.data.sources.nba.client import NBAClient, NBAClientError
    from polynba.data.sources.nba.parser import NBAParser

    vr = ValidationResult(f"NBA.com CDN Boxscore (game_id={game_id})")
    client = NBAClient()

    try:
        raw = await client.get_boxscore(game_id)

        if "game" not in raw:
            vr.fail("Response missing 'game' key")
            return vr
        vr.ok("Raw response has 'game' key")

        gs = NBAParser.parse_boxscore(raw)
        if gs is None:
            vr.fail("parse_boxscore returned None")
            return vr
        vr.ok(f"Parsed GameState: {gs.away_team.team_abbreviation} @ {gs.home_team.team_abbreviation}")
        vr.ok(f"Score: {gs.away_team.score}-{gs.home_team.score}, Period: {gs.period.name}")

    except NBAClientError as e:
        err_str = str(e)
        if "403" in err_str and game_status == "SCHEDULED":
            vr.ok("Got 403 for pre-game boxscore (expected — NBA.com CDN doesn't serve boxscores before tipoff)")
        else:
            vr.fail(f"NBAClientError: {err_str}")
    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await client.close()

    return vr


async def validate_nba_player_index() -> ValidationResult:
    """Validate NBA.com CDN player index endpoint and parsing."""
    from polynba.data.sources.nba.client import NBAClient
    from polynba.data.sources.nba.parser import NBAParser

    vr = ValidationResult("NBA.com CDN Player Index")
    client = NBAClient()

    try:
        raw = await client.get_player_index()

        result_sets = raw.get("resultSets", [])
        if not result_sets:
            vr.fail("Response missing 'resultSets'")
            return vr
        vr.ok(f"Raw response has {len(result_sets)} resultSets")

        headers = result_sets[0].get("headers", [])
        rows = result_sets[0].get("rowSet", [])
        vr.ok(f"Headers: {len(headers)} columns, Rows: {len(rows)} players")

        if len(rows) < 400:
            vr.fail(f"Expected 400+ players, got {len(rows)}")
        else:
            vr.ok(f"Player count plausible ({len(rows)} >= 400)")

        # Parse to PlayerSeasonStats
        parsed = NBAParser.parse_player_index(raw)
        n_teams = len(parsed)
        n_players = sum(len(v) for v in parsed.values())
        vr.ok(f"Parsed {n_players} active players across {n_teams} teams")

        if n_teams >= 28:
            vr.ok(f"Team count plausible ({n_teams} >= 28)")
        else:
            vr.fail(f"Only {n_teams} teams in player index (expected ~30)")

        # Validate sample players have stats
        has_ppg = sum(1 for team_players in parsed.values() for p in team_players if p.points_per_game > 0)
        vr.ok(f"Players with PPG > 0: {has_ppg}")

        has_position = sum(1 for team_players in parsed.values() for p in team_players if p.position)
        vr.ok(f"Players with position: {has_position}")

        # Show a sample star player
        all_players = [p for team_players in parsed.values() for p in team_players]
        all_players.sort(key=lambda p: p.points_per_game, reverse=True)
        if all_players:
            top = all_players[0]
            vr.ok(f"Top scorer: {top.player_name} ({top.team_abbreviation}) — {top.points_per_game} PPG, {top.assists_per_game} APG, {top.rebounds_per_game} RPG")

        # Cross-reference with injury data to validate name matching
        try:
            from polynba.data.sources.espn.client import ESPNClient
            from polynba.data.sources.espn.parser import ESPNParser

            espn_client = ESPNClient()
            inj_raw = await espn_client.get_injuries()
            injuries = ESPNParser.parse_injuries(inj_raw)
            await espn_client.close()

            # Try to match an injured player
            matched = 0
            unmatched = 0
            for team_injuries in injuries.values():
                for inj in team_injuries:
                    name_key = inj.player_name.lower().strip()
                    found = False
                    for team_players in parsed.values():
                        for p in team_players:
                            if p.player_name.lower().strip() == name_key:
                                found = True
                                break
                        if found:
                            break
                    if found:
                        matched += 1
                    else:
                        unmatched += 1

            total = matched + unmatched
            if total > 0:
                pct = matched / total * 100
                vr.ok(f"Injury cross-ref: {matched}/{total} injured players matched ({pct:.0f}%)")
                if unmatched > 0:
                    vr.warn(f"{unmatched} injured players not found in player index (may be inactive/G-League)")
            else:
                vr.warn("No injuries to cross-reference")
        except Exception as e:
            vr.warn(f"Could not cross-reference injuries: {e}")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await client.close()

    return vr


async def validate_espn_athlete_overview() -> ValidationResult:
    """Validate ESPN athlete overview endpoint for extended player stats."""
    from polynba.data.sources.espn.client import ESPNClient
    from polynba.data.sources.espn.parser import ESPNParser

    vr = ValidationResult("ESPN Athlete Overview (extended stats)")
    client = ESPNClient()

    try:
        # First, find an injured player with an ESPN ID
        inj_raw = await client.get_injuries()
        injuries = ESPNParser.parse_injuries(inj_raw)

        target_player = None
        for team_injuries in injuries.values():
            for inj in team_injuries:
                if inj.player_id and inj.status.lower() == "out":
                    target_player = inj
                    break
            if target_player:
                break

        # Fall back to any injured player with an ID
        if not target_player:
            for team_injuries in injuries.values():
                for inj in team_injuries:
                    if inj.player_id:
                        target_player = inj
                        break
                if target_player:
                    break

        if not target_player:
            vr.warn("No injured players with ESPN IDs found — cannot test overview")
            return vr

        vr.ok(f"Target player: {target_player.player_name} (id={target_player.player_id}, status={target_player.status})")

        # Fetch athlete overview
        raw = await client.get_athlete_overview(target_player.player_id)

        if "statistics" not in raw:
            vr.fail("Response missing 'statistics' key")
            return vr
        vr.ok("Raw response has 'statistics'")

        # Parse
        parsed = ESPNParser.parse_athlete_overview(raw)
        if parsed is None:
            vr.fail("parse_athlete_overview returned None")
            return vr
        vr.ok(f"Parsed {len(parsed)} stat fields")

        # Validate key fields
        if parsed.get("minutes_per_game", 0) > 0:
            vr.ok(f"MIN: {parsed['minutes_per_game']:.1f}")
        else:
            vr.warn("MIN is 0 (player may not have played)")

        if parsed.get("field_goal_pct", 0) > 0:
            vr.ok(f"FG%: {parsed['field_goal_pct']:.1f}")
        else:
            vr.warn("FG% is 0")

        # Print full stat line
        stat_parts = []
        for key in ["games_played", "minutes_per_game", "points_per_game",
                     "rebounds_per_game", "assists_per_game", "steals_per_game",
                     "blocks_per_game", "turnovers_per_game", "field_goal_pct",
                     "three_point_pct", "free_throw_pct"]:
            val = parsed.get(key)
            if val is not None:
                stat_parts.append(f"{key}={val}")
        vr.ok(f"Full stat line: {', '.join(stat_parts)}")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await client.close()

    return vr


# ── Polymarket Validation ────────────────────────────────────────────
async def validate_polymarket_discovery() -> ValidationResult:
    """Validate Polymarket Gamma API market discovery."""
    from polynba.polymarket.market_discovery import MarketDiscovery

    vr = ValidationResult("Polymarket Market Discovery (Gamma API)")
    discovery = MarketDiscovery()

    try:
        markets = await discovery.discover_nba_markets(force_refresh=True)
        vr.ok(f"Discovered {len(markets)} NBA moneyline markets")

        if not markets:
            vr.warn("No NBA markets found (may be offseason or no upcoming games)")
            return vr

        # Validate market fields
        m = markets[0]
        if m.condition_id:
            vr.ok(f"condition_id present: {m.condition_id[:30]}...")
        else:
            vr.fail("condition_id is empty")

        if m.home_token_id and m.away_token_id:
            vr.ok(f"Token IDs present (home: {m.home_token_id[:20]}..., away: {m.away_token_id[:20]}...)")
        else:
            vr.fail("Token IDs missing")

        if m.home_team_name and m.away_team_name:
            home_abbr = discovery.get_team_abbreviation(m.home_team_name) or "???"
            away_abbr = discovery.get_team_abbreviation(m.away_team_name) or "???"
            vr.ok(f"Teams: {m.away_team_name} ({away_abbr}) @ {m.home_team_name} ({home_abbr})")
        else:
            vr.fail("Team names missing")

        if m.home_price is not None and m.away_price is not None:
            hp, ap = float(m.home_price), float(m.away_price)
            if 0 < hp < 1 and 0 < ap < 1:
                vr.ok(f"Prices sane: home=${hp:.2f}, away=${ap:.2f} (sum={hp + ap:.2f})")
            else:
                vr.fail(f"Prices out of range: home={hp}, away={ap}")
        else:
            vr.warn("Prices are None (Gamma API may not include them)")

        if m.end_date:
            vr.ok(f"End date: {m.end_date.isoformat()}")
        else:
            vr.warn("End date is None")

        vr.ok(f"Tradeable: {m.is_tradeable}, Volume: {m.volume}")

        # Store for price fetcher test
        vr._market = m

        # Also list all markets
        for i, mkt in enumerate(markets):
            home_abbr = discovery.get_team_abbreviation(mkt.home_team_name) or "???"
            away_abbr = discovery.get_team_abbreviation(mkt.away_team_name) or "???"
            hp_str = f"${float(mkt.home_price):.2f}" if mkt.home_price else "N/A"
            ap_str = f"${float(mkt.away_price):.2f}" if mkt.away_price else "N/A"
            date_str = mkt.end_date.strftime("%m/%d") if mkt.end_date else "?"
            print(f"    [{date_str}] {away_abbr} @ {home_abbr}: {home_abbr} {hp_str}, {away_abbr} {ap_str}")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")
    finally:
        await discovery.close()

    return vr


async def validate_polymarket_prices(market: Any) -> ValidationResult:
    """Validate Polymarket CLOB price fetching and order book parsing."""
    from polynba.polymarket.price_fetcher import PriceFetcher

    vr = ValidationResult(f"Polymarket CLOB Prices ({market.home_team_name} vs {market.away_team_name})")
    fetcher = PriceFetcher()

    try:
        prices = await fetcher.get_market_prices(market)

        if prices is None:
            vr.fail("get_market_prices returned None")
            return vr
        vr.ok("Fetched MarketPrices successfully")

        # Validate mid prices
        hm, am = float(prices.home_mid_price), float(prices.away_mid_price)
        if 0 < hm < 1 and 0 < am < 1:
            vr.ok(f"Mid prices: home={hm:.4f}, away={am:.4f}")
        else:
            vr.fail(f"Mid prices out of range: home={hm}, away={am}")

        price_sum = hm + am
        if 0.95 <= price_sum <= 1.05:
            vr.ok(f"Price sum ~1.0: {price_sum:.4f}")
        else:
            vr.warn(f"Price sum deviates from 1.0: {price_sum:.4f}")

        # Validate bid/ask
        if prices.home_best_bid is not None and prices.home_best_ask is not None:
            hb, ha = float(prices.home_best_bid), float(prices.home_best_ask)
            if hb < ha:
                vr.ok(f"Home bid/ask: {hb:.4f}/{ha:.4f} (spread={ha - hb:.4f})")
            else:
                vr.fail(f"Home bid >= ask: {hb} >= {ha}")
        else:
            vr.warn("Home bid/ask not available")

        if prices.away_best_bid is not None and prices.away_best_ask is not None:
            ab, aa = float(prices.away_best_bid), float(prices.away_best_ask)
            if ab < aa:
                vr.ok(f"Away bid/ask: {ab:.4f}/{aa:.4f} (spread={aa - ab:.4f})")
            else:
                vr.fail(f"Away bid >= ask: {ab} >= {aa}")
        else:
            vr.warn("Away bid/ask not available")

        # Validate depth
        hbd = float(prices.home_bid_depth)
        vr.ok(f"Home bid depth: ${hbd:,.0f}, Has liquidity: {prices.has_liquidity}")

        # Test get_token_sell_price
        sell_price = fetcher.get_token_sell_price(market.home_token_id)
        if sell_price is not None:
            vr.ok(f"Home token sell price (best bid): {float(sell_price):.4f}")
        else:
            vr.warn("get_token_sell_price returned None")

        # Test get_token_price_info
        mid, bid, spread_pct = fetcher.get_token_price_info(market.home_token_id)
        if mid is not None:
            vr.ok(f"Home token info: mid={float(mid):.4f}, bid={float(bid):.4f}, spread={spread_pct:.2f}%")
        else:
            vr.warn("get_token_price_info returned None for mid")

    except Exception as e:
        vr.fail(f"Exception: {e}\n{traceback.format_exc()}")

    return vr


# ── Main ─────────────────────────────────────────────────────────────
async def main() -> int:
    results: list[ValidationResult] = []

    # ── ESPN API ──
    header("1. ESPN API")

    section("1a. Scoreboard")
    scoreboard_result = await validate_espn_scoreboard()
    results.append(scoreboard_result)
    report(scoreboard_result)

    # Use game_id from scoreboard for subsequent tests
    game_id = getattr(scoreboard_result, "_game_id", None)
    home_team_id = getattr(scoreboard_result, "_home_team_id", None)

    if game_id:
        section("1b. Game Summary")
        gs_result = await validate_espn_game_summary(game_id)
        results.append(gs_result)
        report(gs_result)

    if home_team_id:
        section("1c. Team Stats")
        ts_result = await validate_espn_team_stats(home_team_id)
        results.append(ts_result)
        report(ts_result)

    section("1d. Injuries")
    inj_result = await validate_espn_injuries()
    results.append(inj_result)
    report(inj_result)

    section("1e. Standings")
    stand_result = await validate_espn_standings()
    results.append(stand_result)
    report(stand_result)

    # ── NBA.com CDN ──
    header("2. NBA.com CDN")

    section("2a. Scoreboard")
    nba_sb_result = await validate_nba_scoreboard()
    results.append(nba_sb_result)
    report(nba_sb_result)

    nba_game_id = getattr(nba_sb_result, "_nba_game_id", None)
    nba_game_status = getattr(nba_sb_result, "_nba_game_status", "SCHEDULED")
    if nba_game_id:
        section("2b. Boxscore")
        nba_box_result = await validate_nba_boxscore(nba_game_id, nba_game_status)
        results.append(nba_box_result)
        report(nba_box_result)

    section("2c. Player Index")
    pi_result = await validate_nba_player_index()
    results.append(pi_result)
    report(pi_result)

    section("2d. ESPN Athlete Overview (extended stats)")
    overview_result = await validate_espn_athlete_overview()
    results.append(overview_result)
    report(overview_result)

    # ── Polymarket ──
    header("3. Polymarket")

    section("3a. Market Discovery (Gamma API)")
    discovery_result = await validate_polymarket_discovery()
    results.append(discovery_result)
    report(discovery_result)

    market = getattr(discovery_result, "_market", None)
    if market:
        section("3b. CLOB Price Fetching")
        price_result = await validate_polymarket_prices(market)
        results.append(price_result)
        report(price_result)

    # ── Summary ──
    header("SUMMARY")
    total_pass = sum(1 for r in results if r.success)
    total_fail = sum(1 for r in results if not r.success)
    total_checks = sum(len(r.passed) for r in results)
    total_failures = sum(len(r.failed) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)

    print(f"\nSections:  {total_pass} passed, {total_fail} failed (of {len(results)} total)")
    print(f"Checks:    {total_checks} passed, {total_failures} failed, {total_warnings} warnings")

    for r in results:
        icon = "[OK]  " if r.success else "[FAIL]"
        print(f"  {icon} {r.name}")

    if total_fail > 0:
        print(f"\n{total_fail} SECTION(S) FAILED")
        return 1
    else:
        print("\nALL SECTIONS PASSED")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
