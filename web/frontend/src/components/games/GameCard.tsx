import { useNavigate } from 'react-router-dom'
import type { GameMarketSummary } from '../../api/types'
import TeamBadge from './TeamBadge'
import VerdictBadge from './VerdictBadge'

interface GameCardProps {
  summary: GameMarketSummary
  /** True when market/price data is still loading */
  pricesLoading?: boolean
}

function formatGameTime(isoString: string | null): string {
  if (!isoString) return 'TBD'
  try {
    const d = new Date(isoString)
    return d.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'America/New_York',
    }) + ' ET'
  } catch {
    return 'TBD'
  }
}

function formatVolume(vol: number): string {
  if (vol >= 1_000_000) return `$${(vol / 1_000_000).toFixed(1)}M`
  if (vol >= 1_000) return `$${(vol / 1_000).toFixed(0)}K`
  return `$${vol.toFixed(0)}`
}

export default function GameCard({ summary, pricesLoading }: GameCardProps) {
  const navigate = useNavigate()
  const { game, market, prices, cached_verdict, cached_estimate } = summary

  const homeAbbr = game.home_team_abbreviation
  const awayAbbr = game.away_team_abbreviation

  const homeMid = prices?.home_mid_price ?? market.home_price ?? null
  const awayMid = prices?.away_mid_price ?? market.away_price ?? null

  return (
    <div
      className="rounded-xl border border-[#E5E5E5] bg-white shadow-sm p-5 hover:shadow-md hover:border-gray-300 cursor-pointer transition-all duration-150 flex flex-col gap-4"
      onClick={() => navigate(`/game/${game.game_id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && navigate(`/game/${game.game_id}`)}
    >
      {/* Header row: teams + game time */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TeamBadge abbr={awayAbbr} />
          <span className="text-gray-400 text-xs font-medium">@</span>
          <TeamBadge abbr={homeAbbr} />
        </div>
        <span className="text-xs text-gray-400">{formatGameTime(game.game_date)}</span>
      </div>

      {/* Team names + records */}
      <div className="flex items-stretch gap-3">
        {/* Away */}
        <div className="flex-1">
          <p className="text-sm font-medium text-gray-900">{game.away_team_name}</p>
          <p className="text-xs text-gray-400">{game.away_team_id ? '' : ''}</p>
        </div>
        <div className="flex items-center text-gray-300 text-xs font-medium self-center">vs</div>
        {/* Home */}
        <div className="flex-1 text-right">
          <p className="text-sm font-medium text-gray-900">{game.home_team_name}</p>
        </div>
      </div>

      {/* Prices row */}
      {pricesLoading && homeMid === null && awayMid === null ? (
        <div className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500">{awayAbbr}</span>
            <span className="inline-block w-8 h-4 bg-gray-200 rounded animate-pulse" />
          </div>
          <div className="text-xs text-gray-300">|</div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500">{homeAbbr}</span>
            <span className="inline-block w-8 h-4 bg-gray-200 rounded animate-pulse" />
          </div>
        </div>
      ) : (homeMid !== null || awayMid !== null) ? (
        <div className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500">{awayAbbr}</span>
            {awayMid !== null ? (
              <span className="font-mono text-sm font-semibold text-gray-800">
                {Math.round(awayMid * 100)}&#162;
              </span>
            ) : (
              <span className="text-xs text-gray-400">—</span>
            )}
          </div>
          <div className="text-xs text-gray-300">|</div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500">{homeAbbr}</span>
            {homeMid !== null ? (
              <span className="font-mono text-sm font-semibold text-gray-800">
                {Math.round(homeMid * 100)}&#162;
              </span>
            ) : (
              <span className="text-xs text-gray-400">—</span>
            )}
          </div>
        </div>
      ) : null}

      {/* Footer: verdict + edge + volume */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          {cached_verdict && <VerdictBadge verdict={cached_verdict} size="sm" />}
          {cached_estimate && (
            <span className="text-xs font-medium text-gray-500">
              {cached_estimate.edge_percent > 0 ? '+' : ''}
              {cached_estimate.edge_percent.toFixed(1)}% edge
            </span>
          )}
        </div>
        {pricesLoading && !market.volume ? (
          <span className="inline-block w-12 h-3 bg-gray-200 rounded animate-pulse" />
        ) : (
          <span className="text-xs text-gray-400">
            Vol {formatVolume(market.volume)}
          </span>
        )}
      </div>

      {/* Suggested bet if available */}
      {cached_estimate && cached_estimate.suggested_bet_usdc > 0 && (
        <div className="text-xs text-gray-400 -mt-2">
          Suggested:{' '}
          <span className="font-medium text-gray-600">
            ${cached_estimate.suggested_bet_usdc.toFixed(0)} on {cached_estimate.bet_side.toUpperCase() === 'HOME' ? homeAbbr : awayAbbr}
          </span>
        </div>
      )}
    </div>
  )
}
