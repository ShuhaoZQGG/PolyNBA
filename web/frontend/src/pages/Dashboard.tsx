import { useMemo, useState } from 'react'
import { useGames, useMarkets, usePortfolio, useRunAllAnalysis } from '../api/hooks'
import type { GameAdvisoryResponse, GameMarketSummary } from '../api/types'
import GameGrid from '../components/games/GameGrid'
import StatCard from '../components/common/StatCard'
import SuggestionsModal from '../components/analysis/SuggestionsModal'

function formatUSDC(val: number) {
  return `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(d: Date) {
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}

function dateToParam(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}${m}${day}`
}

export default function Dashboard() {
  const [selectedDate, setSelectedDate] = useState<Date>(new Date())
  const dateParam = dateToParam(selectedDate)

  const { data: portfolio } = usePortfolio()
  // Fast: just ESPN game data (<500ms)
  const { data: games, isLoading: gamesLoading, error: gamesError } = useGames(dateParam)
  // Slow: games + Polymarket markets + prices
  const { data: markets, isLoading: marketsLoading } = useMarkets(dateParam)
  const [suggestionsData, setSuggestionsData] = useState<GameAdvisoryResponse[] | null>(null)
  const runAll = useRunAllAnalysis()

  // Build market lookup by game_id for merging
  const marketsByGameId = useMemo(() => {
    if (!markets) return new Map<string, GameMarketSummary>()
    return new Map(markets.map((m) => [m.game.game_id, m]))
  }, [markets])

  // Merge: show games immediately, enrich with market data when available
  const summaries: GameMarketSummary[] = useMemo(() => {
    if (markets) return markets  // fully loaded — use as-is
    if (!games) return []
    // Games loaded but markets still loading — build placeholder summaries
    return games.map((game) => ({
      game,
      market: marketsByGameId.get(game.game_id)?.market ?? {
        condition_id: '',
        question: '',
        home_token_id: '',
        away_token_id: '',
        home_team_name: game.home_team_name,
        away_team_name: game.away_team_name,
        liquidity: 0,
        volume: 0,
        home_price: null,
        away_price: null,
        is_tradeable: false,
        end_date: null,
      },
      prices: null,
      cached_verdict: null,
      cached_estimate: null,
    }))
  }, [games, markets, marketsByGameId])

  const isLoading = gamesLoading
  const error = gamesError

  const positionCount = portfolio ? Object.keys(portfolio.positions).filter(
    (k) => (portfolio.positions[k] ?? 0) > 0,
  ).length : 0

  // Count games that have cached analysis
  const analyzedCount = markets?.filter((m) => m.cached_verdict !== null).length ?? 0

  function prevDay() {
    const d = new Date(selectedDate)
    d.setDate(d.getDate() - 1)
    setSelectedDate(d)
  }

  function nextDay() {
    const d = new Date(selectedDate)
    d.setDate(d.getDate() + 1)
    setSelectedDate(d)
  }

  function isToday(d: Date) {
    const today = new Date()
    return (
      d.getFullYear() === today.getFullYear() &&
      d.getMonth() === today.getMonth() &&
      d.getDate() === today.getDate()
    )
  }

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Total Balance"
          value={portfolio ? formatUSDC(portfolio.balance.usdc) : '—'}
          sub={portfolio ? `${formatUSDC(portfolio.balance.available_usdc)} available` : undefined}
        />
        <StatCard
          label="Active Positions"
          value={portfolio ? positionCount : '—'}
          sub={portfolio ? `${portfolio.open_orders.length} open orders` : undefined}
        />
        <StatCard
          label="Games Analyzed"
          value={`${analyzedCount} / ${markets?.length ?? '—'}`}
          sub={markets ? `${markets.length} games on slate` : undefined}
        />
      </div>

      {/* Date navigation + Run All button */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <button
            onClick={prevDay}
            className="p-1.5 rounded-lg border border-[#E5E5E5] bg-white hover:bg-gray-50 text-gray-600 transition-colors"
            aria-label="Previous day"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-gray-900">{formatDate(selectedDate)}</p>
            {isToday(selectedDate) && (
              <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs font-semibold rounded-full">
                Today
              </span>
            )}
          </div>
          <button
            onClick={nextDay}
            className="p-1.5 rounded-lg border border-[#E5E5E5] bg-white hover:bg-gray-50 text-gray-600 transition-colors"
            aria-label="Next day"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        <button
          onClick={() => runAll.mutate({ withAi: true, date: dateParam }, {
            onSuccess: (data) => setSuggestionsData(data),
          })}
          disabled={runAll.isPending || isLoading}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
            runAll.isPending
              ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
              : 'bg-blue-600 hover:bg-blue-700 text-white'
          }`}
        >
          {runAll.isPending ? (
            <>
              <span className="inline-block w-3.5 h-3.5 border-2 border-gray-300 border-t-gray-500 rounded-full animate-spin" />
              Analyzing...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Run All Analysis
            </>
          )}
        </button>
      </div>

      {/* Pending feedback */}
      {runAll.isPending && (
        <p className="text-xs text-gray-500">Analysis may take up to 60 seconds...</p>
      )}

      {/* Error from run-all */}
      {runAll.error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3">
          <p className="text-sm text-red-600">Analysis failed: {runAll.error.message}</p>
        </div>
      )}

      {/* Game grid */}
      <GameGrid
        summaries={summaries}
        isLoading={isLoading}
        error={error}
        pricesLoading={marketsLoading && !markets}
      />

      {/* Post-analysis suggestions modal */}
      {suggestionsData && (
        <SuggestionsModal
          advisories={suggestionsData}
          onClose={() => setSuggestionsData(null)}
          isReAnalyzing={runAll.isPending}
          onReAnalyze={() => {
            runAll.mutate({ withAi: true, date: dateParam, force: true }, {
              onSuccess: (data) => setSuggestionsData(data),
            })
          }}
        />
      )}
    </div>
  )
}
