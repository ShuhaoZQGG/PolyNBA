import { useParams, useNavigate } from 'react-router-dom'
import { useAnalysis, useRunAnalysis, useMarkets } from '../api/hooks'
import { SkeletonLine } from '../components/common/LoadingSkeleton'
import TeamBadge from '../components/games/TeamBadge'
import VerdictBadge from '../components/games/VerdictBadge'
import OddsPill from '../components/games/OddsPill'
import ProbabilityBar from '../components/analysis/ProbabilityBar'
import AnalysisPanel from '../components/analysis/AnalysisPanel'
import OrderForm from '../components/trading/OrderForm'
import Card from '../components/common/Card'
import { ApiError } from '../api/client'
import useStore from '../store/useStore'
import { useEffect } from 'react'

function formatTimeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function TradingPlanCard({ plan, advisory }: {
  plan: NonNullable<import('../api/types').GameAdvisoryResponse['trading_plan']>
  advisory: import('../api/types').GameAdvisoryResponse
}) {
  const { estimate } = advisory
  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-900">Trading Plan</h3>
        <VerdictBadge verdict={estimate.verdict} />
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm mb-4">
        <div>
          <p className="text-xs text-gray-400">Strategy</p>
          <p className="font-medium text-gray-800 text-xs mt-0.5">{plan.strategy}</p>
        </div>
        <div>
          <p className="text-xs text-gray-400">Bet Side</p>
          <p className="font-medium text-gray-800 text-xs mt-0.5">{estimate.bet_side.toUpperCase() === 'HOME' ? advisory.game.home_team_abbreviation : advisory.game.away_team_abbreviation}</p>
        </div>
        <div>
          <p className="text-xs text-gray-400">Entry Price</p>
          <p className="font-mono font-semibold text-gray-800">
            {Math.round(plan.entry_price * 100)}&#162;
          </p>
        </div>
        {plan.exit_price !== null && (
          <div>
            <p className="text-xs text-gray-400">Exit Price</p>
            <p className="font-mono font-semibold text-gray-800">
              {Math.round(plan.exit_price * 100)}&#162;
            </p>
          </div>
        )}
        <div>
          <p className="text-xs text-gray-400">Expected ROI</p>
          <p className={`font-semibold tabular-nums text-sm ${plan.expected_roi >= 0 ? 'text-green-600' : 'text-red-600'}`}>
            {plan.expected_roi >= 0 ? '+' : ''}{(plan.expected_roi * 100).toFixed(1)}%
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-400">Suggested Bet</p>
          <p className="font-semibold text-gray-800 tabular-nums text-sm">
            ${estimate.suggested_bet_usdc.toFixed(0)}
          </p>
        </div>
      </div>

      {/* Edge */}
      <div className="flex items-center gap-3 bg-gray-50 rounded-lg px-3 py-2">
        <div>
          <p className="text-xs text-gray-400">Edge</p>
          <p className={`font-semibold tabular-nums text-sm ${estimate.edge >= 0 ? 'text-green-600' : 'text-red-600'}`}>
            {estimate.edge >= 0 ? '+' : ''}{(estimate.edge_percent).toFixed(1)}%
          </p>
        </div>
        <div className="border-l border-gray-200 pl-3">
          <p className="text-xs text-gray-400">Kelly</p>
          <p className="font-semibold tabular-nums text-sm text-gray-800">
            {(estimate.kelly_fraction * 100).toFixed(1)}%
          </p>
        </div>
        <div className="border-l border-gray-200 pl-3">
          <p className="text-xs text-gray-400">Confidence</p>
          <p className="font-semibold tabular-nums text-sm text-gray-800">
            {estimate.confidence}/10
          </p>
        </div>
      </div>

      {/* Liquidity warning */}
      {plan.liquidity_warning && (
        <div className="mt-3 flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <span className="text-amber-500 shrink-0">!</span>
          <p className="text-xs text-amber-700">
            Low liquidity detected. Depth available: ${plan.depth_available.toFixed(0)}. Exercise caution with larger orders.
          </p>
        </div>
      )}

      {/* Factor summary */}
      {estimate.factors_summary.length > 0 && (
        <ul className="mt-3 space-y-1">
          {estimate.factors_summary.map((f, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-gray-600">
              <span className="text-gray-300 shrink-0">•</span>
              {f}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export default function GameDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const resetForm = useStore((s) => s.resetForm)

  // Reset order form when navigating to a new game
  useEffect(() => {
    resetForm()
  }, [id, resetForm])

  const { data: analysis, isLoading, error } = useAnalysis(id ?? '')
  const runAnalysis = useRunAnalysis()
  const { data: markets } = useMarkets()

  // Find summary from markets list as fallback before full analysis loads
  const marketSummary = markets?.find((m) => m.game.game_id === id)

  const isNotFound = error instanceof ApiError && error.status === 404

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="text-gray-400 hover:text-gray-600">
            ← Back
          </button>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          <div className="lg:col-span-3 space-y-4">
            <div className="rounded-xl border border-[#E5E5E5] bg-white p-5">
              <div className="flex items-center gap-3 mb-4">
                <div className="skeleton h-7 w-20 rounded-full" />
                <div className="skeleton h-4 w-6" />
                <div className="skeleton h-7 w-20 rounded-full" />
              </div>
              <SkeletonLine className="w-1/2 mb-2" />
              <SkeletonLine className="w-1/3" />
            </div>
          </div>
          <div className="lg:col-span-2">
            <div className="skeleton h-80 w-full rounded-xl" />
          </div>
        </div>
      </div>
    )
  }

  // If no analysis cached yet — show market summary + run button
  if (isNotFound || !analysis) {
    return (
      <div className="space-y-6">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back to Markets
        </button>

        <div className="rounded-xl border border-[#E5E5E5] bg-white p-8 text-center">
          {marketSummary ? (
            <>
              <div className="flex items-center justify-center gap-3 mb-4">
                <TeamBadge abbr={marketSummary.game.away_team_abbreviation} size="lg" />
                <span className="text-gray-400 text-sm">@</span>
                <TeamBadge abbr={marketSummary.game.home_team_abbreviation} size="lg" />
              </div>
              <h2 className="text-lg font-semibold text-gray-900 mb-1">
                {marketSummary.game.away_team_name} vs {marketSummary.game.home_team_name}
              </h2>
            </>
          ) : (
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Game Analysis</h2>
          )}

          <p className="text-gray-500 text-sm mb-6">
            No analysis has been run for this game yet.
          </p>

          {runAnalysis.error && (
            <div className="mb-4 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
              {runAnalysis.error.message}
            </div>
          )}

          <button
            onClick={() => runAnalysis.mutate({ gameId: id ?? '', withAi: true })}
            disabled={runAnalysis.isPending}
            className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg transition-colors disabled:opacity-60"
          >
            {runAnalysis.isPending ? (
              <>
                <span className="inline-block w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                Running Analysis...
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                Run Analysis
              </>
            )}
          </button>
        </div>
      </div>
    )
  }

  const { game, prices, estimate, trading_plan, ai_detail } = analysis

  return (
    <div className="space-y-6">
      {/* Back nav */}
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Back to Markets
      </button>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-start">
        {/* Left column: Analysis */}
        <div className="lg:col-span-3 space-y-5">
          {/* Game header */}
          <Card>
            <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
              <div className="flex items-center gap-3">
                <TeamBadge abbr={game.away_team_abbreviation} size="lg" />
                <span className="text-gray-400 text-sm font-medium">at</span>
                <TeamBadge abbr={game.home_team_abbreviation} size="lg" />
              </div>
              <VerdictBadge verdict={estimate.verdict} />
            </div>

            <div className="flex items-center gap-2 flex-wrap mb-4">
              <h1 className="text-base font-semibold text-gray-900">
                {game.away_team_name} vs {game.home_team_name}
              </h1>
            </div>

            {/* Live prices */}
            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                <TeamBadge abbr={game.away_team_abbreviation} size="sm" />
                <OddsPill price={prices.away_mid_price} />
                {prices.away_best_bid !== null && prices.away_best_ask !== null && (
                  <span className="text-xs text-gray-400 font-mono">
                    {Math.round(prices.away_best_bid * 100)}–{Math.round(prices.away_best_ask * 100)}
                  </span>
                )}
              </div>
              <div className="text-gray-200">|</div>
              <div className="flex items-center gap-2">
                <TeamBadge abbr={game.home_team_abbreviation} size="sm" />
                <OddsPill price={prices.home_mid_price} />
                {prices.home_best_bid !== null && prices.home_best_ask !== null && (
                  <span className="text-xs text-gray-400 font-mono">
                    {Math.round(prices.home_best_bid * 100)}–{Math.round(prices.home_best_ask * 100)}
                  </span>
                )}
              </div>
            </div>
          </Card>

          {/* Probability bars */}
          <Card>
            <h3 className="text-sm font-semibold text-gray-900 mb-4">Probability Breakdown</h3>
            <ProbabilityBar
              modelProb={estimate.model_prob}
              marketProb={estimate.market_prob}
              blendedProb={estimate.blended_prob}
              homeAbbr={game.home_team_abbreviation}
              awayAbbr={game.away_team_abbreviation}
              betSide={estimate.bet_side}
            />
          </Card>

          {/* Trading plan */}
          {trading_plan && (
            <TradingPlanCard plan={trading_plan} advisory={analysis} />
          )}

          {/* AI Analysis */}
          {ai_detail ? (
            <Card>
              <div className="flex items-center justify-between mb-5">
                <h3 className="text-sm font-semibold text-gray-900">AI Analysis</h3>
                <div className="flex items-center gap-2">
                  {analysis.analyzed_at && (
                    <span className="text-xs text-gray-400">
                      Cached {formatTimeAgo(analysis.analyzed_at)}
                    </span>
                  )}
                  <button
                    onClick={() => runAnalysis.mutate({ gameId: id ?? '', withAi: true, force: true })}
                    disabled={runAnalysis.isPending}
                    className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 rounded-full transition-colors disabled:opacity-50"
                    title="Re-analyze with fresh AI call"
                  >
                    <svg className={`w-3 h-3 ${runAnalysis.isPending ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Re-analyze
                  </button>
                  <span className="px-2 py-0.5 bg-purple-100 text-purple-700 text-xs font-semibold rounded-full">
                    Claude
                  </span>
                </div>
              </div>
              <AnalysisPanel analysis={ai_detail} betSide={estimate.bet_side} />
            </Card>
          ) : (
            <Card className="border-dashed">
              <div className="text-center py-6">
                <p className="text-sm text-gray-500 mb-3">No AI analysis available</p>
                <button
                  onClick={() => runAnalysis.mutate({ gameId: id ?? '', withAi: true })}
                  disabled={runAnalysis.isPending}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold rounded-lg transition-colors disabled:opacity-60"
                >
                  {runAnalysis.isPending ? 'Generating...' : 'Generate AI Analysis'}
                </button>
              </div>
            </Card>
          )}
        </div>

        {/* Right column: Order form (sticky) */}
        <div className="lg:col-span-2 lg:sticky lg:top-20">
          <OrderForm advisory={analysis} />
        </div>
      </div>
    </div>
  )
}
