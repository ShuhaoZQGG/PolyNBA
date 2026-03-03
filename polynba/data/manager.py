"""Data manager coordinating all data sources and caching."""

import asyncio
import logging
import unicodedata
from typing import Optional

from .cache import CacheConfig, DataCache, cached
from .failover import DataSource, FailoverManager
from .espn_teams import ESPN_IDS, ESPN_TEAMS
from .models import GameState, GameSummary, HeadToHead, PlayerInjury, PlayerSeasonStats, TeamContext, TeamStats
from .sources.espn.client import ESPNClient, ESPNClientError
from .sources.espn.parser import ESPNParser
from .sources.nba.client import NBAClient
from .sources.nba.parser import NBAParser

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    """Normalize player name: lowercase, strip, remove diacritics."""
    name = name.lower().strip()
    # Decompose Unicode chars and drop combining marks (accents)
    return "".join(
        c for c in unicodedata.normalize("NFD", name)
        if unicodedata.category(c) != "Mn"
    )


class DataManager:
    """Central coordinator for all NBA data access.

    Provides a unified interface for fetching game data with:
    - Automatic caching with configurable TTLs
    - Automatic failover between ESPN and NBA.com
    - Team context aggregation
    """

    def __init__(
        self,
        failover_manager: Optional[FailoverManager] = None,
        cache_config: Optional[CacheConfig] = None,
    ):
        """Initialize the data manager.

        Args:
            failover_manager: Optional FailoverManager instance
            cache_config: Optional cache configuration
        """
        self._failover = failover_manager or FailoverManager()
        self._cache = DataCache(cache_config)
        self._nba_client = NBAClient()
        self._espn_client = ESPNClient()

    @property
    def cache(self) -> DataCache:
        """Get the cache instance."""
        return self._cache

    @property
    def failover(self) -> FailoverManager:
        """Get the failover manager."""
        return self._failover

    async def close(self) -> None:
        """Close the data manager and all resources."""
        await self._nba_client.close()
        await self._espn_client.close()
        await self._failover.close()

    async def get_live_games(self, date: Optional[str] = None) -> list[GameSummary]:
        """Get all currently live games.

        Args:
            date: Optional date in YYYYMMDD format

        Returns:
            List of live GameSummary objects
        """
        cache_key = f"live_games_{date or 'today'}"

        return await cached(
            self._cache,
            "scoreboard",
            cache_key,
            lambda: self._failover.get_live_games(date),
        )

    async def get_all_games(self, date: Optional[str] = None) -> list[GameSummary]:
        """Get all games for a date.

        Args:
            date: Optional date in YYYYMMDD format

        Returns:
            List of all GameSummary objects
        """
        cache_key = f"all_games_{date or 'today'}"

        return await cached(
            self._cache,
            "scoreboard",
            cache_key,
            lambda: self._failover.get_all_games(date),
        )

    async def get_game_state(
        self, game_id: str, force_refresh: bool = False
    ) -> Optional[GameState]:
        """Get detailed game state.

        Args:
            game_id: Game ID
            force_refresh: If True, bypass cache

        Returns:
            GameState object or None
        """
        cache_key = f"game_state_{game_id}"

        if force_refresh:
            self._cache.invalidate("game_state", cache_key)

        return await cached(
            self._cache,
            "game_state",
            cache_key,
            lambda: self._failover.get_game_state(game_id),
        )

    async def get_team_stats(
        self, team_id: str, force_refresh: bool = False
    ) -> Optional[TeamStats]:
        """Get team statistics.

        Fetches base stats from ESPN via failover, then overlays NBA.com
        advanced team stats (ORtg, DRtg, eFG%, TS%, AST%, TOV%, PIE, rankings).

        Args:
            team_id: Team ID
            force_refresh: If True, bypass cache

        Returns:
            TeamStats object or None
        """
        cache_key = f"team_stats_{team_id}"

        if force_refresh:
            self._cache.invalidate("team_stats", cache_key)

        cached_value = self._cache.get("team_stats", cache_key)
        if cached_value is not None:
            return cached_value

        # Fetch ESPN base stats
        base_stats = await self._failover.get_team_stats(team_id)
        if not base_stats:
            return None

        # Overlay NBA.com advanced stats
        try:
            all_advanced = await self.get_all_team_advanced_stats()
            abbr = base_stats.team_abbreviation or ESPN_IDS.get(team_id)
            if abbr and abbr in all_advanced:
                self._merge_team_advanced_stats(base_stats, all_advanced[abbr])
                logger.info(f"Merged NBA.com advanced stats for {abbr}")
        except Exception as e:
            logger.warning(f"Failed to merge NBA.com team advanced stats: {e}")

        self._cache.set("team_stats", cache_key, base_stats)
        return base_stats

    async def get_all_team_advanced_stats(self) -> dict[str, dict[str, float]]:
        """Get NBA.com advanced stats for all 30 teams.

        Returns:
            Dictionary keyed by team abbreviation -> {field_name: value}
        """
        cache_key = "team_advanced_all"
        cached_value = self._cache.get("team_stats", cache_key)
        if cached_value is not None:
            return cached_value

        raw = await self._nba_client.get_advanced_team_stats()
        parsed = NBAParser.parse_advanced_team_stats(raw)
        if parsed:
            self._cache.set("team_stats", cache_key, parsed)
            logger.info(f"Cached NBA.com advanced stats for {len(parsed)} teams")
        return parsed

    @staticmethod
    def _merge_team_advanced_stats(
        team_stats: TeamStats, advanced: dict[str, float]
    ) -> None:
        """Merge NBA.com advanced stats onto a TeamStats object.

        NBA.com authoritative fields (ORtg, DRtg, pace, net_rating, eFG%, TS%,
        rankings) overwrite ESPN values. ESPN-only fields (home/away splits,
        streak, record) are preserved. New fields (AST%, TOV%, PIE, etc.)
        are always set.
        """
        for field_name, value in advanced.items():
            setattr(team_stats, field_name, value)

    async def get_all_team_stats(self) -> dict[str, TeamStats]:
        """Get stats for all 30 NBA teams efficiently.

        Fetches NBA.com advanced stats once (1 call), then ESPN base stats
        for all 30 teams in parallel, merging advanced onto each.

        Returns:
            Dictionary keyed by team abbreviation -> TeamStats
        """
        # 1. Fetch NBA.com advanced stats (single call for all 30 teams)
        all_advanced = {}
        try:
            all_advanced = await self.get_all_team_advanced_stats()
        except Exception as e:
            logger.warning(f"Failed to fetch NBA.com advanced stats: {e}")

        # 2. Fetch ESPN base stats for all 30 teams in parallel
        async def _fetch_one(abbr: str, team_id: str) -> tuple[str, TeamStats | None]:
            try:
                base = await self._failover.get_team_stats(team_id)
                if base and abbr in all_advanced:
                    self._merge_team_advanced_stats(base, all_advanced[abbr])
                return abbr, base
            except Exception as e:
                logger.warning(f"Failed to fetch stats for {abbr}: {e}")
                return abbr, None

        tasks = [
            _fetch_one(abbr, team_id)
            for abbr, team_id in ESPN_TEAMS.items()
        ]
        results = await asyncio.gather(*tasks)

        return {abbr: stats for abbr, stats in results if stats is not None}

    async def get_all_injuries(self) -> dict[str, list[PlayerInjury]]:
        """Get injury data for all NBA teams.

        Returns:
            Dictionary mapping team_id to list of PlayerInjury objects
        """
        return await cached(
            self._cache,
            "injuries",
            "all_injuries",
            lambda: self._failover.get_all_injuries(),
        )

    async def get_team_injuries(self, team_id: str) -> list[PlayerInjury]:
        """Get injuries for a specific team.

        Args:
            team_id: Team ID

        Returns:
            List of PlayerInjury objects for the team
        """
        all_injuries = await self.get_all_injuries()
        return all_injuries.get(team_id, [])

    async def get_player_index(self) -> dict[str, list[PlayerSeasonStats]]:
        """Get player season stats indexed by team abbreviation.

        Fetches basic player index and advanced stats in parallel.
        Advanced stats are merged in but optional — basic index still works if it fails.

        Returns:
            Dictionary mapping team_abbreviation to list of PlayerSeasonStats
        """
        cache_key = "player_index_all"
        cached_value = self._cache.get("player_index", cache_key)
        if cached_value is not None:
            return cached_value

        try:
            # Fetch basic index and advanced stats in parallel
            basic_task = self._nba_client.get_player_index()
            advanced_task = self._nba_client.get_advanced_player_stats()
            results = await asyncio.gather(basic_task, advanced_task, return_exceptions=True)

            basic_raw = results[0]
            advanced_raw = results[1]

            # Basic index is required
            if isinstance(basic_raw, Exception):
                raise basic_raw
            parsed = NBAParser.parse_player_index(basic_raw)

            # Advanced stats are optional — merge if available
            if not isinstance(advanced_raw, Exception):
                try:
                    advanced = NBAParser.parse_advanced_player_stats(advanced_raw)
                    if advanced:
                        self._merge_advanced_stats(parsed, advanced)
                        logger.info(f"Merged advanced stats for {len(advanced)} players")
                except Exception as e:
                    logger.warning(f"Failed to parse advanced stats: {e}")
            else:
                logger.warning(f"Advanced stats fetch failed: {type(advanced_raw).__name__}: {advanced_raw}")

            if parsed:
                self._cache.set("player_index", cache_key, parsed)
            return parsed
        except Exception as e:
            logger.warning(f"Failed to fetch player index: {e}")
            return {}

    def _merge_advanced_stats(
        self,
        player_index: dict[str, list[PlayerSeasonStats]],
        advanced: dict[str, dict[str, float]],
    ) -> None:
        """Merge advanced stats into player index entries.

        Matches by normalized "player_name|team_abbr" key.
        """
        for team_abbr, players in player_index.items():
            for ps in players:
                norm_name = _normalize_name(ps.player_name)
                key = f"{norm_name}|{team_abbr}"
                adv = advanced.get(key)
                if not adv:
                    continue

                # Set all advanced fields
                for field_name, value in adv.items():
                    # Fill GP/MIN only if currently empty
                    if field_name == "games_played" and ps.games_played > 0:
                        continue
                    if field_name == "minutes_per_game" and ps.minutes_per_game > 0:
                        continue
                    setattr(ps, field_name, value)

    async def get_all_players_full(self) -> dict[str, list[PlayerSeasonStats]]:
        """Fetch complete player data for all ~500 players in 3 NBA.com calls.

        Fetches player index + base stats + advanced stats in parallel, then
        merges all three datasets. No ESPN calls needed.

        Returns:
            Dictionary mapping team_abbreviation to list of PlayerSeasonStats
            with full base + advanced stats populated.
        """
        # Fetch all three in parallel
        basic_task = self._nba_client.get_player_index()
        base_task = self._nba_client.get_base_player_stats()
        advanced_task = self._nba_client.get_advanced_player_stats()
        results = await asyncio.gather(
            basic_task, base_task, advanced_task, return_exceptions=True
        )

        basic_raw, base_raw, advanced_raw = results

        # Basic index is required
        if isinstance(basic_raw, Exception):
            raise basic_raw
        parsed = NBAParser.parse_player_index(basic_raw)

        # Merge base stats (FG%, 3P%, FT%, STL, BLK, TOV, PF, MIN, GP)
        if not isinstance(base_raw, Exception):
            try:
                base_stats = NBAParser.parse_base_player_stats(base_raw)
                if base_stats:
                    self._merge_advanced_stats(parsed, base_stats)
                    logger.info(f"Merged base stats for {len(base_stats)} players")
            except Exception as e:
                logger.warning(f"Failed to parse base stats: {e}")
        else:
            logger.warning(f"Base stats fetch failed: {type(base_raw).__name__}: {base_raw}")

        # Merge advanced stats (NR, TS%, USG%, PIE, etc.)
        if not isinstance(advanced_raw, Exception):
            try:
                advanced = NBAParser.parse_advanced_player_stats(advanced_raw)
                if advanced:
                    self._merge_advanced_stats(parsed, advanced)
                    logger.info(f"Merged advanced stats for {len(advanced)} players")
            except Exception as e:
                logger.warning(f"Failed to parse advanced stats: {e}")
        else:
            logger.warning(f"Advanced stats fetch failed: {type(advanced_raw).__name__}: {advanced_raw}")

        return parsed

    async def _fetch_athlete_overview(self, player_id: str) -> Optional[dict[str, float]]:
        """Fetch and cache ESPN athlete overview for extended stats.

        Args:
            player_id: ESPN athlete ID

        Returns:
            Dict of stat_name -> value, or None on failure
        """
        cache_key = f"player_overview_{player_id}"
        cached_value = self._cache.get("player_index", cache_key)
        if cached_value is not None:
            return cached_value

        try:
            raw = await self._espn_client.get_athlete_overview(player_id)
            parsed = ESPNParser.parse_athlete_overview(raw)
            if parsed:
                self._cache.set("player_index", cache_key, parsed)
            return parsed
        except Exception as e:
            logger.debug(f"Failed to fetch athlete overview for {player_id}: {e}")
            return None

    async def _enrich_injuries_with_stats(
        self,
        injuries: list[PlayerInjury],
        team_abbr: str,
        player_index: dict[str, list[PlayerSeasonStats]],
    ) -> dict[str, PlayerSeasonStats]:
        """Match injured players to their season stats and enrich with ESPN overview.

        1. Name-match from NBA player index -> baseline PPG/RPG/APG
        2. For each injured player with player_id, fetch ESPN overview -> extended stats
        3. Merge extended stats into PlayerSeasonStats

        Args:
            injuries: List of player injuries
            team_abbr: Team abbreviation for lookup
            player_index: Player index keyed by team abbreviation

        Returns:
            player_stats_map for the team (player_name -> stats)
        """
        team_players = player_index.get(team_abbr, [])
        if not team_players:
            return {}

        # Build lookup: normalized name -> PlayerSeasonStats
        stats_by_name: dict[str, PlayerSeasonStats] = {}
        for ps in team_players:
            key = _normalize_name(ps.player_name)
            stats_by_name[key] = ps

        # Phase 1: Match injuries to baseline stats from NBA player index
        player_stats_map: dict[str, PlayerSeasonStats] = {}
        for injury in injuries:
            key = _normalize_name(injury.player_name)
            if key in stats_by_name:
                injury.player_stats = stats_by_name[key]
                player_stats_map[injury.player_name] = stats_by_name[key]

        # Phase 2: Fetch ESPN overview for injured players with player_id
        players_to_enrich = [
            inj for inj in injuries
            if inj.player_stats and inj.player_id
        ]

        if not players_to_enrich:
            return player_stats_map

        # Fetch all overviews concurrently
        overview_tasks = [
            self._fetch_athlete_overview(inj.player_id)
            for inj in players_to_enrich
        ]
        overviews = await asyncio.gather(*overview_tasks)

        # Phase 3: Merge extended stats into PlayerSeasonStats
        for injury, overview in zip(players_to_enrich, overviews):
            if not overview or not injury.player_stats:
                continue

            s = injury.player_stats
            s.games_played = int(overview.get("games_played", 0))
            s.minutes_per_game = overview.get("minutes_per_game", 0.0)
            s.field_goal_pct = overview.get("field_goal_pct", 0.0)
            s.three_point_pct = overview.get("three_point_pct", 0.0)
            s.free_throw_pct = overview.get("free_throw_pct", 0.0)
            s.blocks_per_game = overview.get("blocks_per_game", 0.0)
            s.steals_per_game = overview.get("steals_per_game", 0.0)
            s.fouls_per_game = overview.get("fouls_per_game", 0.0)
            s.turnovers_per_game = overview.get("turnovers_per_game", 0.0)

            logger.debug(
                f"Enriched {injury.player_name}: "
                f"{s.minutes_per_game:.1f} MIN, {s.field_goal_pct:.1f} FG%, "
                f"{s.steals_per_game:.1f} STL, {s.blocks_per_game:.1f} BLK"
            )

        return player_stats_map

    async def _get_espn_roster_ids(self, team_id: str) -> dict[str, str]:
        """Get ESPN athlete ID mapping for a team's roster.

        Args:
            team_id: ESPN team ID

        Returns:
            Mapping of lowercase player name -> ESPN athlete ID
        """
        cache_key = f"roster_ids_{team_id}"
        cached_value = self._cache.get("player_index", cache_key)
        if cached_value is not None:
            return cached_value

        try:
            raw = await self._espn_client.get_team_roster(team_id)
            players = ESPNParser.parse_team_roster(raw)
            mapping = {p["player_name"].lower().strip(): p["athlete_id"] for p in players}
            if mapping:
                self._cache.set("player_index", cache_key, mapping)
            return mapping
        except Exception as e:
            logger.debug(f"Failed to fetch roster IDs for team {team_id}: {e}")
            return {}

    async def _enrich_rotation_with_stats(
        self,
        team_id: str,
        team_abbr: str,
        player_index: dict[str, list[PlayerSeasonStats]],
    ) -> dict[str, PlayerSeasonStats]:
        """Fetch extended stats for top rotation players (not just injured).

        Gets ESPN athlete IDs via roster endpoint, then fetches ESPN overview
        for top-8 players by PPG to populate minutes, FG%, blocks, steals, etc.

        Args:
            team_id: ESPN team ID
            team_abbr: Team abbreviation for player index lookup
            player_index: Player index keyed by team abbreviation

        Returns:
            player_stats_map with enriched stats for rotation players
        """
        team_players = player_index.get(team_abbr, [])
        if not team_players:
            return {}

        # Get ESPN roster ID mapping
        roster_ids = await self._get_espn_roster_ids(team_id)
        if not roster_ids:
            logger.debug(f"No roster IDs for {team_abbr}, skipping rotation enrichment")
            return {}

        # Take top 8 by PPG
        sorted_players = sorted(team_players, key=lambda p: p.points_per_game, reverse=True)[:8]

        # Match to ESPN IDs and fetch overviews concurrently
        # Build normalized roster lookup to handle diacritics (e.g. Dončić vs Doncic)
        norm_roster: dict[str, str] = {_normalize_name(k): v for k, v in roster_ids.items()}
        players_to_enrich: list[tuple[PlayerSeasonStats, str]] = []
        for ps in sorted_players:
            key = _normalize_name(ps.player_name)
            espn_id = norm_roster.get(key)
            if espn_id:
                players_to_enrich.append((ps, espn_id))

        if not players_to_enrich:
            return {}

        overview_tasks = [
            self._fetch_athlete_overview(espn_id)
            for _, espn_id in players_to_enrich
        ]
        overviews = await asyncio.gather(*overview_tasks)

        player_stats_map: dict[str, PlayerSeasonStats] = {}
        for (ps, _), overview in zip(players_to_enrich, overviews):
            if not overview:
                player_stats_map[ps.player_name] = ps
                continue

            # Merge extended stats
            ps.games_played = int(overview.get("games_played", ps.games_played))
            ps.minutes_per_game = overview.get("minutes_per_game", ps.minutes_per_game)
            ps.field_goal_pct = overview.get("field_goal_pct", ps.field_goal_pct)
            ps.three_point_pct = overview.get("three_point_pct", ps.three_point_pct)
            ps.free_throw_pct = overview.get("free_throw_pct", ps.free_throw_pct)
            ps.blocks_per_game = overview.get("blocks_per_game", ps.blocks_per_game)
            ps.steals_per_game = overview.get("steals_per_game", ps.steals_per_game)
            ps.fouls_per_game = overview.get("fouls_per_game", ps.fouls_per_game)
            ps.turnovers_per_game = overview.get("turnovers_per_game", ps.turnovers_per_game)

            player_stats_map[ps.player_name] = ps

            logger.info(
                f"  Rotation: {ps.player_name} — {ps.minutes_per_game:.1f} MIN, "
                f"{ps.points_per_game:.1f} PPG, EIR {ps.estimated_impact_rating:.1f}"
            )

        return player_stats_map

    async def get_head_to_head(
        self, team_id: str, opponent_id: str
    ) -> Optional[HeadToHead]:
        """Get head-to-head record between two teams for the current season.

        Args:
            team_id: First team ID
            opponent_id: Second team ID

        Returns:
            HeadToHead object or None if no data found
        """
        cache_key = f"h2h_{team_id}_{opponent_id}"
        cached = self._cache.get("team_stats", cache_key)
        if cached is not None:
            return cached

        try:
            schedule_data = await self._espn_client.get_team_schedule(team_id)
            h2h = ESPNParser.parse_head_to_head(schedule_data, team_id, opponent_id)
            if h2h:
                self._cache.set("team_stats", cache_key, h2h)
            return h2h
        except Exception as e:
            logger.warning(f"Failed to fetch H2H for {team_id} vs {opponent_id}: {e}")
            return None

    async def get_team_context(
        self, team_id: str, opponent_id: Optional[str] = None
    ) -> Optional[TeamContext]:
        """Get full team context including stats and injuries.

        Args:
            team_id: Team ID
            opponent_id: Optional opponent ID for head-to-head data

        Returns:
            TeamContext object or None
        """
        cache_key = f"team_context_{team_id}_{opponent_id or 'none'}"

        cached_value = self._cache.get("team_context", cache_key)
        if cached_value:
            return cached_value

        # Fetch team stats
        stats = await self.get_team_stats(team_id)
        if not stats:
            return None

        # Fetch injuries
        injuries = await self.get_team_injuries(team_id)

        # Enrich injuries and rotation with player season stats
        player_stats_map: dict[str, PlayerSeasonStats] = {}
        if stats.team_abbreviation:
            try:
                player_index = await self.get_player_index()

                # Enrich injuries (sets player_stats on injuries)
                if injuries:
                    injury_stats = await self._enrich_injuries_with_stats(
                        injuries, stats.team_abbreviation, player_index
                    )
                    player_stats_map.update(injury_stats)

                # Enrich top rotation players (bench depth + active starters)
                rotation_stats = await self._enrich_rotation_with_stats(
                    team_id, stats.team_abbreviation, player_index
                )
                # Rotation fills in players not already covered by injuries
                for name, ps in rotation_stats.items():
                    if name not in player_stats_map:
                        player_stats_map[name] = ps
            except Exception as e:
                logger.warning(f"Failed to enrich player stats: {e}")

        # Fetch head-to-head data if opponent specified
        h2h = None
        if opponent_id:
            try:
                h2h = await self.get_head_to_head(team_id, opponent_id)
            except Exception as e:
                logger.debug(f"Failed to fetch H2H for context: {e}")

        # Build context
        context = TeamContext(
            stats=stats,
            injuries=injuries,
            head_to_head=h2h,
            player_stats_map=player_stats_map,
        )

        self._cache.set("team_context", cache_key, context)
        return context

    async def get_game_with_context(
        self, game_id: str
    ) -> tuple[Optional[GameState], dict[str, Optional[TeamContext]]]:
        """Get game state with full context for both teams.

        Args:
            game_id: Game ID

        Returns:
            Tuple of (GameState, {team_id: TeamContext})
        """
        game_state = await self.get_game_state(game_id)

        if not game_state:
            return None, {}

        # Get context for both teams
        home_context = await self.get_team_context(
            game_state.home_team.team_id,
            game_state.away_team.team_id,
        )

        away_context = await self.get_team_context(
            game_state.away_team.team_id,
            game_state.home_team.team_id,
        )

        contexts = {
            game_state.home_team.team_id: home_context,
            game_state.away_team.team_id: away_context,
        }

        return game_state, contexts

    def invalidate_game_cache(self, game_id: str) -> None:
        """Invalidate cached data for a specific game.

        Args:
            game_id: Game ID
        """
        self._cache.invalidate("game_state", f"game_state_{game_id}")
        logger.debug(f"Invalidated game cache for {game_id}")

    def invalidate_all_live_data(self) -> None:
        """Invalidate all live data caches."""
        self._cache.invalidate_all("game_state")
        self._cache.invalidate_all("scoreboard")
        logger.debug("Invalidated all live data caches")

    def set_primary_source(self, source: DataSource) -> None:
        """Manually set the primary data source.

        Args:
            source: DataSource to use as primary
        """
        self._failover.set_primary(source)

    @property
    def health_status(self) -> dict:
        """Get overall health status."""
        return {
            "failover": self._failover.health_status,
            "cache": self._cache.stats,
        }
