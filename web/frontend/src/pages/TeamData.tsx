import { useState, useMemo, useEffect, Fragment } from 'react'
import { useTeamInjuries, useTeamStrength, usePlayerStats, useRefreshData } from '../api/hooks'
import type { TeamInjuries, TeamStats, PlayerStatsEntry, PlayerInjury } from '../api/types'
import { getTeamColor } from '../constants/teams'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ActiveTab = 'injuries' | 'strength' | 'players'
type SortKey = keyof PlayerStatsEntry
type SortDir = 'asc' | 'desc'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtStat(val: number | null, decimals = 1): string {
  if (val === null || val === undefined) return '-'
  return val.toFixed(decimals)
}

function fmtPct(val: number | null): string {
  if (val === null || val === undefined) return '-'
  return `${(val * 100).toFixed(1)}%`
}

// ---------------------------------------------------------------------------
// Inline SVG icons
// ---------------------------------------------------------------------------

function RefreshIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
      />
    </svg>
  )
}

function ChevronUpIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
    </svg>
  )
}

function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
    </svg>
  )
}

function SortIcon({ column, sortKey, sortDir }: { column: string; sortKey: string; sortDir: SortDir }) {
  if (column !== sortKey) {
    return (
      <span className="ml-1 inline-flex flex-col opacity-30">
        <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 10 10">
          <path d="M5 2l3 3H2l3-3zm0 6L2 5h6L5 8z" />
        </svg>
      </span>
    )
  }
  return sortDir === 'asc' ? (
    <ChevronUpIcon className="ml-1 w-3 h-3 inline-block" />
  ) : (
    <ChevronDownIcon className="ml-1 w-3 h-3 inline-block" />
  )
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function SkeletonRows({ rows = 6, cols = 8 }: { rows?: number; cols?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, ri) => (
        <tr key={ri} className="animate-pulse">
          {Array.from({ length: cols }).map((_, ci) => (
            <td key={ci} className="px-4 py-3">
              <div className="h-4 bg-gray-100 rounded" style={{ width: `${50 + Math.random() * 40}%` }} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const upper = status.toUpperCase()
  if (upper === 'OUT') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-red-100 text-red-700">
        OUT
      </span>
    )
  }
  if (upper.includes('QUESTIONABLE')) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-700">
        Questionable
      </span>
    )
  }
  if (upper.includes('DAY-TO-DAY') || upper.includes('DTD')) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-yellow-100 text-yellow-700">
        Day-to-Day
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-gray-100 text-gray-600">
      {status}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Team abbreviation pill
// ---------------------------------------------------------------------------

function TeamBadge({ abbr }: { abbr: string }) {
  const color = getTeamColor(abbr)
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold text-white"
      style={{ backgroundColor: color }}
    >
      {abbr}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Injuries tab
// ---------------------------------------------------------------------------

function InjuryRow({ injury }: { injury: PlayerInjury }) {
  return (
    <tr className="hover:bg-gray-50/50 transition-colors">
      <td className="px-4 py-3 text-sm font-medium text-gray-900 whitespace-nowrap">
        {injury.player_name}
      </td>
      <td className="px-4 py-3 whitespace-nowrap">
        <StatusBadge status={injury.status} />
      </td>
      <td className="px-4 py-3 text-sm text-gray-600 max-w-[200px] truncate">
        {injury.injury_description || '-'}
      </td>
      <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
        {fmtStat(injury.points_per_game)}
      </td>
      <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
        {fmtStat(injury.rebounds_per_game)}
      </td>
      <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
        {fmtStat(injury.assists_per_game)}
      </td>
      <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
        {fmtStat(injury.minutes_per_game)}
      </td>
    </tr>
  )
}

function TeamInjuryCard({ team }: { team: TeamInjuries }) {
  const [open, setOpen] = useState(true)
  const hasOut = team.key_players_out > 0

  return (
    <div className="rounded-xl border border-[#E5E5E5] bg-white overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50/50 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-3">
          <TeamBadge abbr={team.team_abbreviation} />
          <span className="text-sm font-semibold text-gray-900">
            {team.injuries.length} {team.injuries.length === 1 ? 'injury' : 'injuries'}
          </span>
          {hasOut && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-red-100 text-red-700">
              {team.key_players_out} OUT
            </span>
          )}
        </div>
        {open ? (
          <ChevronUpIcon className="w-4 h-4 text-gray-400" />
        ) : (
          <ChevronDownIcon className="w-4 h-4 text-gray-400" />
        )}
      </button>

      {open && (
        <div className="border-t border-[#E5E5E5] overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-left bg-gray-50">
                <th className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider">Player</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider">Injury</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">PPG</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">RPG</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">APG</th>
                <th className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">MPG</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F0F0F0]">
              {team.injuries.map((inj) => (
                <InjuryRow key={inj.player_id} injury={inj} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function TeamFilterBar({
  allTeams,
  selected,
  onToggle,
  onClear,
}: {
  allTeams: string[]
  selected: Set<string>
  onToggle: (abbr: string) => void
  onClear: () => void
}) {
  return (
    <div className="px-5 py-3 border-b border-[#E5E5E5] flex flex-wrap items-center gap-2">
      <span className="text-xs font-medium text-gray-500 uppercase tracking-wider mr-1">Filter:</span>
      {allTeams.map((abbr) => {
        const isActive = selected.has(abbr)
        const color = getTeamColor(abbr)
        return (
          <button
            key={abbr}
            onClick={() => onToggle(abbr)}
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold transition-all ${
              isActive ? 'text-white ring-2 ring-offset-1' : 'opacity-40 hover:opacity-70'
            }`}
            style={{
              backgroundColor: isActive ? color : undefined,
              color: isActive ? 'white' : color,
              border: isActive ? `2px solid ${color}` : `1px solid ${color}`,
            }}
          >
            {abbr}
          </button>
        )
      })}
      {selected.size > 0 && (
        <button
          onClick={onClear}
          className="ml-2 text-xs text-gray-400 hover:text-gray-600 underline transition-colors"
        >
          Clear all
        </button>
      )}
    </div>
  )
}

function InjuriesTab({ data, isLoading }: { data: TeamInjuries[] | undefined; isLoading: boolean }) {
  const [selectedTeams, setSelectedTeams] = useState<Set<string>>(new Set())

  const teamsWithInjuries = useMemo(() => {
    if (!data) return []
    return data
      .filter((t) => t.injuries.length > 0)
      .sort((a, b) => b.key_players_out - a.key_players_out || b.injuries.length - a.injuries.length)
  }, [data])

  const allTeamAbbrs = useMemo(
    () => teamsWithInjuries.map((t) => t.team_abbreviation).sort(),
    [teamsWithInjuries],
  )

  const filtered = useMemo(() => {
    if (selectedTeams.size === 0) return teamsWithInjuries
    return teamsWithInjuries.filter((t) => selectedTeams.has(t.team_abbreviation))
  }, [teamsWithInjuries, selectedTeams])

  function handleToggle(abbr: string) {
    setSelectedTeams((prev) => {
      const next = new Set(prev)
      if (next.has(abbr)) next.delete(abbr)
      else next.add(abbr)
      return next
    })
  }

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-[#E5E5E5] bg-white p-5 animate-pulse">
            <div className="flex items-center gap-3">
              <div className="h-6 w-10 bg-gray-200 rounded" />
              <div className="h-4 w-32 bg-gray-100 rounded" />
            </div>
          </div>
        ))}
      </div>
    )
  }

  if (teamsWithInjuries.length === 0) {
    return (
      <div className="p-12 text-center">
        <p className="text-sm text-gray-400">No injury data available</p>
      </div>
    )
  }

  return (
    <div>
      <TeamFilterBar
        allTeams={allTeamAbbrs}
        selected={selectedTeams}
        onToggle={handleToggle}
        onClear={() => setSelectedTeams(new Set())}
      />
      <div className="p-5 space-y-4">
        {filtered.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-gray-400">No injuries for the selected teams</p>
          </div>
        ) : (
          filtered.map((team) => <TeamInjuryCard key={team.team_id} team={team} />)
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Team Strength tab
// ---------------------------------------------------------------------------

type StrengthSubTab = 'stats' | 'effective'

function StreakCell({ streak }: { streak: number }) {
  if (streak === 0) return <span className="text-gray-400">-</span>
  const isWin = streak > 0
  return (
    <span className={`tabular-nums font-medium ${isWin ? 'text-green-600' : 'text-red-600'}`}>
      {isWin ? 'W' : 'L'}{Math.abs(streak)}
    </span>
  )
}

function NetRatingCell({ value }: { value: number }) {
  const isPositive = value >= 0
  return (
    <span className={`tabular-nums font-medium ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
      {isPositive ? '+' : ''}{value.toFixed(1)}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Effective Roster computation
// ---------------------------------------------------------------------------

interface InjuredPlayerImpact {
  playerName: string
  status: string
  ppg: number
  rpg: number
  apg: number
  mpg: number
  gamesPlayed: number
  totalTeamGames: number
  participationRate: number
  isNewImpact: boolean
}

interface EffectiveTeam {
  team: TeamStats
  injuredOut: InjuredPlayerImpact[]
  newImpactPpg: number
  alreadyReflectedPpg: number
  adjustedNetRating: number
  impactLevel: 'none' | 'minor' | 'moderate' | 'significant' | 'critical'
}

function computeEffectiveStrength(
  teams: TeamStats[],
  injuries: TeamInjuries[],
  playerStats: PlayerStatsEntry[],
): EffectiveTeam[] {
  const injuryByTeam = new Map<string, TeamInjuries>()
  for (const ti of injuries) {
    injuryByTeam.set(ti.team_abbreviation, ti)
  }

  // Build player lookup: normalize names to lowercase for fuzzy matching
  const playerByKey = new Map<string, PlayerStatsEntry>()
  for (const p of playerStats) {
    playerByKey.set(`${p.team_abbreviation}:${p.player_name.toLowerCase()}`, p)
  }

  return teams.map((team) => {
    const totalGames = team.wins + team.losses
    const teamInjuries = injuryByTeam.get(team.team_abbreviation)
    const outPlayers = teamInjuries?.injuries.filter((i) => i.is_out) ?? []

    const injuredOut: InjuredPlayerImpact[] = outPlayers.map((inj) => {
      const key = `${team.team_abbreviation}:${inj.player_name.toLowerCase()}`
      const stats = playerByKey.get(key)
      const gamesPlayed = stats?.games_played ?? 0
      const participationRate = totalGames > 0 ? gamesPlayed / totalGames : 0

      return {
        playerName: inj.player_name,
        status: inj.status,
        ppg: inj.points_per_game ?? stats?.points_per_game ?? 0,
        rpg: inj.rebounds_per_game ?? stats?.rebounds_per_game ?? 0,
        apg: inj.assists_per_game ?? stats?.assists_per_game ?? 0,
        mpg: inj.minutes_per_game ?? stats?.minutes_per_game ?? 0,
        gamesPlayed,
        totalTeamGames: totalGames,
        participationRate,
        // Player played >50% of the season → team stats include their contributions
        // so their current absence is a "new" hit not yet reflected in the record
        isNewImpact: participationRate > 0.5,
      }
    })

    injuredOut.sort((a, b) => b.ppg - a.ppg)

    const newImpactPpg = injuredOut
      .filter((p) => p.isNewImpact)
      .reduce((sum, p) => sum + p.ppg, 0)

    const alreadyReflectedPpg = injuredOut
      .filter((p) => !p.isNewImpact)
      .reduce((sum, p) => sum + p.ppg, 0)

    // Rough net rating adjustment: ~0.5 NRtg points per PPG of new impact lost
    const adjustedNetRating = team.net_rating - newImpactPpg * 0.5

    let impactLevel: EffectiveTeam['impactLevel'] = 'none'
    if (newImpactPpg >= 25) impactLevel = 'critical'
    else if (newImpactPpg >= 15) impactLevel = 'significant'
    else if (newImpactPpg >= 8) impactLevel = 'moderate'
    else if (newImpactPpg > 0) impactLevel = 'minor'

    return { team, injuredOut, newImpactPpg, alreadyReflectedPpg, adjustedNetRating, impactLevel }
  })
}

const IMPACT_BADGE: Record<EffectiveTeam['impactLevel'], { label: string; cls: string }> = {
  none: { label: 'Full Strength', cls: 'bg-green-100 text-green-700' },
  minor: { label: 'Minor', cls: 'bg-blue-100 text-blue-700' },
  moderate: { label: 'Moderate', cls: 'bg-amber-100 text-amber-700' },
  significant: { label: 'Significant', cls: 'bg-orange-100 text-orange-700' },
  critical: { label: 'Critical', cls: 'bg-red-100 text-red-700' },
}

function ParticipationBadge({ rate }: { rate: number }) {
  if (rate > 0.5) {
    return (
      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-50 text-red-600">
        New absence
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-gray-100 text-gray-500">
      Season-long
    </span>
  )
}

function EffectiveRosterView({
  teams,
  injuries,
  playerStats,
  isLoading,
}: {
  teams: TeamStats[] | undefined
  injuries: TeamInjuries[] | undefined
  playerStats: PlayerStatsEntry[] | undefined
  isLoading: boolean
}) {
  const [expandedTeam, setExpandedTeam] = useState<string | null>(null)

  const effective = useMemo(() => {
    if (!teams || !injuries || !playerStats) return []
    return computeEffectiveStrength(teams, injuries, playerStats).sort(
      (a, b) => b.adjustedNetRating - a.adjustedNetRating,
    )
  }, [teams, injuries, playerStats])

  if (isLoading) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-white">
            <tr className="text-left border-b border-[#E5E5E5]">
              {Array.from({ length: 9 }).map((_, i) => (
                <th key={i} className="px-4 py-3">
                  <div className="h-3 w-16 bg-gray-100 rounded animate-pulse" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F0F0F0]">
            <SkeletonRows rows={10} cols={9} />
          </tbody>
        </table>
      </div>
    )
  }

  if (effective.length === 0) {
    return (
      <div className="p-12 text-center">
        <p className="text-sm text-gray-400">No data available — needs team stats, injuries, and player stats</p>
      </div>
    )
  }

  return (
    <div>
      <div className="px-5 py-3 bg-amber-50 border-b border-amber-100 text-xs text-amber-700">
        <strong>How to read:</strong> &ldquo;New absence&rdquo; = player played &gt;50% of season games, so team stats
        include their contributions and overstate current effective strength. &ldquo;Season-long&rdquo; = player missed
        most of the season, team stats already reflect playing without them.
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-white">
            <tr className="text-left border-b border-[#E5E5E5]">
              <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">#</th>
              <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Team</th>
              <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Record</th>
              <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">
                Net Rtg
              </th>
              <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">
                Adj. Net Rtg
              </th>
              <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">
                OUT
              </th>
              <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">
                New Impact PPG
              </th>
              <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">
                Already Adj. PPG
              </th>
              <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Impact</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F0F0F0]">
            {effective.map((et, idx) => {
              const isExpanded = expandedTeam === et.team.team_id
              const badge = IMPACT_BADGE[et.impactLevel]
              return (
                <Fragment key={et.team.team_id}>
                  <tr
                    className={`hover:bg-gray-50/50 transition-colors cursor-pointer ${idx % 2 === 1 ? 'bg-gray-50/30' : ''}`}
                    onClick={() => setExpandedTeam(isExpanded ? null : et.team.team_id)}
                  >
                    <td className="px-4 py-3 text-sm text-gray-400 tabular-nums">{idx + 1}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <TeamBadge abbr={et.team.team_abbreviation} />
                        <span className="text-sm font-medium text-gray-900 hidden sm:inline">
                          {et.team.team_name}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm tabular-nums text-gray-900 whitespace-nowrap">
                      {et.team.wins}-{et.team.losses}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <NetRatingCell value={et.team.net_rating} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <NetRatingCell value={et.adjustedNetRating} />
                    </td>
                    <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
                      {et.injuredOut.length || '-'}
                    </td>
                    <td className="px-4 py-3 text-sm tabular-nums text-right">
                      {et.newImpactPpg > 0 ? (
                        <span className="text-red-600 font-medium">-{et.newImpactPpg.toFixed(1)}</span>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm tabular-nums text-right">
                      {et.alreadyReflectedPpg > 0 ? (
                        <span className="text-gray-500">{et.alreadyReflectedPpg.toFixed(1)}</span>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${badge.cls}`}
                      >
                        {badge.label}
                      </span>
                    </td>
                  </tr>
                  {isExpanded && et.injuredOut.length > 0 && (
                    <tr>
                      <td colSpan={9} className="bg-gray-50 px-4 py-3">
                        <div className="ml-8">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="text-left text-xs text-gray-500 uppercase">
                                <th className="pb-2 pr-4">Player</th>
                                <th className="pb-2 pr-4">Status</th>
                                <th className="pb-2 pr-4 text-right">PPG</th>
                                <th className="pb-2 pr-4 text-right">RPG</th>
                                <th className="pb-2 pr-4 text-right">APG</th>
                                <th className="pb-2 pr-4 text-right">MPG</th>
                                <th className="pb-2 pr-4 text-right">GP</th>
                                <th className="pb-2 pr-4 text-right">Played %</th>
                                <th className="pb-2">Classification</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200">
                              {et.injuredOut.map((p) => (
                                <tr key={p.playerName} className="text-gray-700">
                                  <td className="py-1.5 pr-4 font-medium">{p.playerName}</td>
                                  <td className="py-1.5 pr-4">
                                    <StatusBadge status={p.status} />
                                  </td>
                                  <td className="py-1.5 pr-4 text-right tabular-nums">{fmtStat(p.ppg)}</td>
                                  <td className="py-1.5 pr-4 text-right tabular-nums">{fmtStat(p.rpg)}</td>
                                  <td className="py-1.5 pr-4 text-right tabular-nums">{fmtStat(p.apg)}</td>
                                  <td className="py-1.5 pr-4 text-right tabular-nums">{fmtStat(p.mpg)}</td>
                                  <td className="py-1.5 pr-4 text-right tabular-nums">
                                    {p.gamesPlayed}/{p.totalTeamGames}
                                  </td>
                                  <td className="py-1.5 pr-4 text-right tabular-nums">
                                    {(p.participationRate * 100).toFixed(0)}%
                                  </td>
                                  <td className="py-1.5">
                                    <ParticipationBadge rate={p.participationRate} />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Team Strength tab with sub-tabs
// ---------------------------------------------------------------------------

function SeasonStatsView({ data, isLoading }: { data: TeamStats[] | undefined; isLoading: boolean }) {
  const sorted = useMemo(() => {
    if (!data) return []
    return [...data].sort((a, b) => b.win_percentage - a.win_percentage)
  }, [data])

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="sticky top-0 bg-white">
          <tr className="text-left border-b border-[#E5E5E5]">
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">#</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Team</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Record</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">Win%</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">Net Rtg</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">Off Rtg</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">Def Rtg</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">Pace</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">PPG</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">Opp PPG</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">Streak</th>
            <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">L10</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#F0F0F0]">
          {isLoading ? (
            <SkeletonRows rows={10} cols={12} />
          ) : sorted.length === 0 ? (
            <tr>
              <td colSpan={12} className="px-4 py-12 text-center text-sm text-gray-400">
                No team strength data available
              </td>
            </tr>
          ) : (
            sorted.map((team, idx) => (
              <tr
                key={team.team_id}
                className={`hover:bg-gray-50/50 transition-colors ${idx % 2 === 1 ? 'bg-gray-50/30' : ''}`}
              >
                <td className="px-4 py-3 text-sm text-gray-400 tabular-nums">{idx + 1}</td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <div className="flex items-center gap-2">
                    <TeamBadge abbr={team.team_abbreviation} />
                    <span className="text-sm font-medium text-gray-900 hidden sm:inline">
                      {team.team_name}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-gray-900 whitespace-nowrap">
                  {team.wins}-{team.losses}
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-gray-900 text-right">
                  {(team.win_percentage * 100).toFixed(1)}%
                </td>
                <td className="px-4 py-3 text-right">
                  <NetRatingCell value={team.net_rating} />
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
                  {team.offensive_rating.toFixed(1)}
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
                  {team.defensive_rating.toFixed(1)}
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
                  {team.pace.toFixed(1)}
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
                  {team.points_per_game.toFixed(1)}
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right">
                  {team.points_allowed_per_game.toFixed(1)}
                </td>
                <td className="px-4 py-3 text-right">
                  <StreakCell streak={team.current_streak} />
                </td>
                <td className="px-4 py-3 text-sm tabular-nums text-gray-700 text-right whitespace-nowrap">
                  {team.last_10_wins}-{team.last_10_losses}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

function TeamStrengthTab({
  data,
  injuriesData,
  playerData,
  isLoading,
  injuriesLoading,
  playerLoading,
}: {
  data: TeamStats[] | undefined
  injuriesData: TeamInjuries[] | undefined
  playerData: PlayerStatsEntry[] | undefined
  isLoading: boolean
  injuriesLoading: boolean
  playerLoading: boolean
}) {
  const [subTab, setSubTab] = useState<StrengthSubTab>('stats')

  return (
    <div>
      {/* Sub-tab bar */}
      <div className="border-b border-[#E5E5E5] px-4 flex gap-1 bg-gray-50/50">
        <button
          onClick={() => setSubTab('stats')}
          className={`px-3 py-2 text-xs font-medium rounded-t transition-colors ${
            subTab === 'stats'
              ? 'bg-white text-blue-600 border border-[#E5E5E5] border-b-white -mb-px'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          Season Stats
        </button>
        <button
          onClick={() => setSubTab('effective')}
          className={`px-3 py-2 text-xs font-medium rounded-t transition-colors ${
            subTab === 'effective'
              ? 'bg-white text-blue-600 border border-[#E5E5E5] border-b-white -mb-px'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          Effective Roster
        </button>
      </div>

      {subTab === 'stats' && <SeasonStatsView data={data} isLoading={isLoading} />}
      {subTab === 'effective' && (
        <EffectiveRosterView
          teams={data}
          injuries={injuriesData}
          playerStats={playerData}
          isLoading={isLoading || injuriesLoading || playerLoading}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Player Stats tab
// ---------------------------------------------------------------------------

interface ColDef {
  key: SortKey
  label: string
  title?: string
  align?: 'left' | 'right'
}

const PLAYER_COLS: ColDef[] = [
  { key: 'player_name', label: 'Player', align: 'left' },
  { key: 'team_abbreviation', label: 'Team', align: 'left' },
  { key: 'games_played', label: 'GP', title: 'Games Played', align: 'right' },
  { key: 'minutes_per_game', label: 'MPG', title: 'Minutes Per Game', align: 'right' },
  { key: 'points_per_game', label: 'PPG', title: 'Points Per Game', align: 'right' },
  { key: 'rebounds_per_game', label: 'RPG', title: 'Rebounds Per Game', align: 'right' },
  { key: 'assists_per_game', label: 'APG', title: 'Assists Per Game', align: 'right' },
  { key: 'steals_per_game', label: 'SPG', title: 'Steals Per Game', align: 'right' },
  { key: 'blocks_per_game', label: 'BPG', title: 'Blocks Per Game', align: 'right' },
  { key: 'field_goal_pct', label: 'FG%', title: 'Field Goal %', align: 'right' },
  { key: 'three_point_pct', label: '3P%', title: 'Three Point %', align: 'right' },
  { key: 'free_throw_pct', label: 'FT%', title: 'Free Throw %', align: 'right' },
  { key: 'true_shooting_pct', label: 'TS%', title: 'True Shooting %', align: 'right' },
  { key: 'usage_rate', label: 'USG%', title: 'Usage Rate', align: 'right' },
  { key: 'net_rating', label: 'NR', title: 'Net Rating', align: 'right' },
]

const PCT_KEYS = new Set<SortKey>(['field_goal_pct', 'three_point_pct', 'free_throw_pct', 'true_shooting_pct', 'usage_rate'])
const DEFAULT_SHOW = 200

function PlayerStatsTab({
  data,
  isLoading,
}: {
  data: PlayerStatsEntry[] | undefined
  isLoading: boolean
}) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('points_per_game')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [showAll, setShowAll] = useState(false)

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const filtered = useMemo(() => {
    if (!data) return []
    const q = search.trim().toLowerCase()
    const base = q
      ? data.filter(
          (p) =>
            p.player_name.toLowerCase().includes(q) ||
            p.team_abbreviation.toLowerCase().includes(q),
        )
      : data

    return [...base].sort((a, b) => {
      const av = a[sortKey] ?? -Infinity
      const bv = b[sortKey] ?? -Infinity
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [data, search, sortKey, sortDir])

  const displayed = showAll || search.trim() ? filtered : filtered.slice(0, DEFAULT_SHOW)
  const hasMore = !showAll && !search.trim() && filtered.length > DEFAULT_SHOW

  function renderCell(player: PlayerStatsEntry, col: ColDef): React.ReactNode {
    const raw = player[col.key]
    if (col.key === 'player_name') {
      return <span className="font-medium text-gray-900">{player.player_name}</span>
    }
    if (col.key === 'team_abbreviation') {
      return <TeamBadge abbr={player.team_abbreviation} />
    }
    if (col.key === 'games_played') {
      return <span className="tabular-nums text-gray-700">{raw as number}</span>
    }
    if (col.key === 'net_rating') {
      if (raw === null || raw === undefined) return <span className="text-gray-300">-</span>
      const nr = raw as number
      return <NetRatingCell value={nr} />
    }
    if (PCT_KEYS.has(col.key)) {
      return (
        <span className="tabular-nums text-gray-700">
          {fmtPct(raw as number | null)}
        </span>
      )
    }
    return (
      <span className="tabular-nums text-gray-700">
        {fmtStat(raw as number | null)}
      </span>
    )
  }

  return (
    <div>
      {/* Search bar */}
      <div className="px-5 py-4 border-b border-[#E5E5E5]">
        <div className="relative max-w-sm">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-4.35-4.35M17 11A6 6 0 111 11a6 6 0 0116 0z"
            />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search player or team..."
            className="w-full pl-9 pr-3 py-2 text-sm border border-[#E5E5E5] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-gray-400"
            aria-label="Search players"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="text-left border-b border-[#E5E5E5] bg-gray-50/50">
              {PLAYER_COLS.map((col) => (
                <th
                  key={col.key}
                  className={`px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer select-none hover:text-gray-800 transition-colors whitespace-nowrap ${
                    col.align === 'right' ? 'text-right' : ''
                  }`}
                  title={col.title}
                  onClick={() => handleSort(col.key)}
                >
                  {col.label}
                  <SortIcon column={col.key} sortKey={sortKey} sortDir={sortDir} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F0F0F0]">
            {isLoading ? (
              <SkeletonRows rows={10} cols={PLAYER_COLS.length} />
            ) : displayed.length === 0 ? (
              <tr>
                <td colSpan={PLAYER_COLS.length} className="px-4 py-12 text-center text-sm text-gray-400">
                  {search ? 'No players match your search' : 'No player stats available'}
                </td>
              </tr>
            ) : (
              displayed.map((player, idx) => (
                <tr
                  key={`${player.player_name}-${player.team_abbreviation}`}
                  className={`hover:bg-gray-50/50 transition-colors ${idx % 2 === 1 ? 'bg-gray-50/30' : ''}`}
                >
                  {PLAYER_COLS.map((col) => (
                    <td
                      key={col.key}
                      className={`px-4 py-3 text-sm ${col.align === 'right' ? 'text-right' : ''}`}
                    >
                      {renderCell(player, col)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Show all footer */}
      {hasMore && (
        <div className="px-5 py-4 border-t border-[#E5E5E5] flex items-center justify-between">
          <p className="text-xs text-gray-400">
            Showing {DEFAULT_SHOW} of {filtered.length} players
          </p>
          <button
            onClick={() => setShowAll(true)}
            className="text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
          >
            Show all {filtered.length} players
          </button>
        </div>
      )}
      {showAll && filtered.length > DEFAULT_SHOW && (
        <div className="px-5 py-4 border-t border-[#E5E5E5] flex items-center justify-between">
          <p className="text-xs text-gray-400">Showing all {filtered.length} players</p>
          <button
            onClick={() => setShowAll(false)}
            className="text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
          >
            Show fewer
          </button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab count badges
// ---------------------------------------------------------------------------

function CountBadge({ count }: { count: number | null }) {
  if (count === null) return null
  return (
    <span className="ml-1.5 inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-500">
      {count}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function formatRelativeTime(ts: number): string {
  const seconds = Math.floor((Date.now() - ts) / 1000)
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m ago`
}

export default function TeamData() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('injuries')
  const [lastRefreshTime, setLastRefreshTime] = useState<number | null>(null)
  const [, setTick] = useState(0)

  const { data: injuriesData, isLoading: injuriesLoading, dataUpdatedAt: injuriesUpdatedAt } = useTeamInjuries()
  const { data: strengthData, isLoading: strengthLoading, dataUpdatedAt: strengthUpdatedAt } = useTeamStrength()
  const { data: playerData, isLoading: playerLoading, dataUpdatedAt: playerUpdatedAt } = usePlayerStats()
  const refresh = useRefreshData()

  // Use earliest dataUpdatedAt as fallback, manual refresh time takes priority
  const latestFetchTime = useMemo(() => {
    const times = [injuriesUpdatedAt, strengthUpdatedAt, playerUpdatedAt].filter(Boolean)
    return times.length > 0 ? Math.max(...times) : null
  }, [injuriesUpdatedAt, strengthUpdatedAt, playerUpdatedAt])

  const displayTime = lastRefreshTime ?? latestFetchTime

  function handleRefresh() {
    refresh.mutate(['all'], {
      onSuccess: () => {
        setLastRefreshTime(Date.now())
      },
    })
  }

  // Re-render every 30s to update relative time display
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000)
    return () => clearInterval(id)
  }, [])

  const injuryTeamCount = useMemo(
    () => (injuriesData ? injuriesData.filter((t) => t.injuries.length > 0).length : null),
    [injuriesData],
  )
  const strengthCount = useMemo(
    () => (strengthData ? strengthData.length : null),
    [strengthData],
  )
  const playerCount = useMemo(
    () => (playerData ? playerData.length : null),
    [playerData],
  )

  const TAB_CONFIG: { id: ActiveTab; label: string; count: number | null }[] = [
    { id: 'injuries', label: 'Injuries', count: injuryTeamCount },
    { id: 'strength', label: 'Team Strength', count: strengthCount },
    { id: 'players', label: 'Player Stats', count: playerCount },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Team Data</h1>
          <p className="mt-0.5 text-sm text-gray-500">
            Injuries, team strength ratings, and player statistics
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <button
            onClick={handleRefresh}
            disabled={refresh.isPending}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
              refresh.isPending
                ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700 text-white'
            }`}
            aria-label="Refresh all team data"
          >
            {refresh.isPending ? (
              <>
                <span className="inline-block w-3.5 h-3.5 border-2 border-gray-300 border-t-gray-500 rounded-full animate-spin" />
                Refreshing...
              </>
            ) : (
              <>
                <RefreshIcon className="w-4 h-4" />
                Refresh All
              </>
            )}
          </button>
          {displayTime ? (
            <p className="text-xs text-gray-400">
              Last refreshed {formatRelativeTime(displayTime)}
            </p>
          ) : null}
        </div>
      </div>

      {/* Main card */}
      <div className="rounded-xl border border-[#E5E5E5] bg-white shadow-sm overflow-hidden">
        {/* Tab bar */}
        <div className="border-b border-[#E5E5E5] overflow-x-auto">
          <div className="flex gap-0 min-w-max">
            {TAB_CONFIG.map(({ id, label, count }) => {
              const isActive = activeTab === id
              return (
                <button
                  key={id}
                  onClick={() => setActiveTab(id)}
                  className={`px-5 py-3.5 text-sm font-medium transition-colors relative flex items-center whitespace-nowrap ${
                    isActive
                      ? 'text-blue-600 border-b-2 border-blue-600'
                      : 'text-gray-500 hover:text-gray-700 border-b-2 border-transparent'
                  }`}
                >
                  {label}
                  <CountBadge count={count} />
                </button>
              )
            })}
          </div>
        </div>

        {/* Tab content */}
        {activeTab === 'injuries' && (
          <InjuriesTab data={injuriesData} isLoading={injuriesLoading} />
        )}
        {activeTab === 'strength' && (
          <TeamStrengthTab
            data={strengthData}
            injuriesData={injuriesData}
            playerData={playerData}
            isLoading={strengthLoading}
            injuriesLoading={injuriesLoading}
            playerLoading={playerLoading}
          />
        )}
        {activeTab === 'players' && (
          <PlayerStatsTab data={playerData} isLoading={playerLoading} />
        )}
      </div>
    </div>
  )
}
