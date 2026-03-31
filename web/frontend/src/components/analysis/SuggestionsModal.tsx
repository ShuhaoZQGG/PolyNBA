import { useEffect, useState } from 'react'
import type { GameAdvisoryResponse, OrderRequest } from '../../api/types'
import { usePlaceOrder, useRecordPregameOrder } from '../../api/hooks'

interface SuggestionsModalProps {
  advisories: GameAdvisoryResponse[]
  onClose: () => void
  onOrderPlaced?: () => void
  onReAnalyze?: () => void
  isReAnalyzing?: boolean
}

function verdictLabel(verdict: string): string {
  switch (verdict) {
    case 'HOME_FAVORITE': return 'Home Fav'
    case 'AWAY_FAVORITE': return 'Away Fav'
    case 'HOME_UPSET': return 'Home Upset'
    case 'AWAY_UPSET': return 'Away Upset'
    default: return verdict.replace(/_/g, ' ')
  }
}

function verdictColor(verdict: string): string {
  if (verdict.includes('UPSET')) return 'bg-amber-100 text-amber-700'
  if (verdict.includes('FAVORITE')) return 'bg-blue-100 text-blue-700'
  return 'bg-gray-100 text-gray-600'
}

function pct(v: number): string {
  return (v * 100).toFixed(1) + '%'
}

function efficiencyColor(eff: string): string {
  if (eff === 'inefficient') return 'text-green-600'
  if (eff === 'efficient') return 'text-red-500'
  return 'text-gray-600'
}

function upsetRiskColor(risk: string): string {
  if (risk === 'high') return 'text-red-600'
  if (risk === 'moderate') return 'text-amber-600'
  return 'text-gray-600'
}

export default function SuggestionsModal({ advisories, onClose, onOrderPlaced, onReAnalyze, isReAnalyzing }: SuggestionsModalProps) {
  const [placedIds, setPlacedIds] = useState<Set<string>>(new Set())
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const placeOrder = usePlaceOrder()
  const recordOrder = useRecordPregameOrder()

  // Filter out NO_EDGE and missing trading plans, then sort
  const suggestions = advisories
    .filter((a) => a.estimate.verdict !== 'NO_EDGE' && a.trading_plan != null)
    .sort((a, b) => {
      const confDiff = b.estimate.confidence - a.estimate.confidence
      if (confDiff !== 0) return confDiff
      return (b.trading_plan?.expected_roi ?? 0) - (a.trading_plan?.expected_roi ?? 0)
    })

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  function advisoryKey(advisory: GameAdvisoryResponse): string {
    return `${advisory.game.game_id}:${advisory.estimate.bet_side}`
  }

  function handlePlaceOrder(advisory: GameAdvisoryResponse) {
    const key = advisoryKey(advisory)
    const betSide = advisory.estimate.bet_side.toUpperCase()
    const tokenId = betSide === 'HOME'
      ? advisory.market.home_token_id
      : advisory.market.away_token_id

    const order: OrderRequest = {
      market_id: advisory.market.condition_id,
      token_id: tokenId,
      side: 'buy',
      size_usdc: advisory.estimate.suggested_bet_usdc,
      price: advisory.trading_plan!.entry_price,
      strategy_id: 'pregame-advisor',
    }

    setPendingId(key)
    placeOrder.mutate(order, {
      onSuccess: (data) => {
        setPlacedIds((prev) => new Set(prev).add(key))
        setPendingId(null)
        onOrderPlaced?.()

        // Record in pregame ledger (fire-and-forget, don't block UI)
        if (data.order) {
          const tp = advisory.trading_plan!
          recordOrder.mutate({
            order_id: data.order.order_id,
            game: `${advisory.game.away_team_abbreviation} @ ${advisory.game.home_team_abbreviation}`,
            team: betSide === 'HOME'
              ? advisory.game.home_team_abbreviation
              : advisory.game.away_team_abbreviation,
            token_id: tokenId,
            market_id: advisory.market.condition_id,
            side: 'buy',
            shares: Math.floor(advisory.estimate.suggested_bet_usdc / tp.entry_price),
            entry_price: tp.entry_price,
            strategy: tp.exit_price != null ? 'TRADE' : 'RESOLUTION',
            exit_price: tp.exit_price,
          })
        }
      },
      onError: () => setPendingId(null),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Analysis Suggestions</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {suggestions.length} actionable {suggestions.length === 1 ? 'game' : 'games'} found
              {advisories.length - suggestions.length > 0 && (
                <span> &middot; {advisories.length - suggestions.length} skipped (no edge)</span>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none p-1"
          >
            &times;
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-4">
          {suggestions.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <p className="text-sm">No actionable suggestions found.</p>
              <p className="text-xs mt-1">All games were classified as NO_EDGE or lack trading plans.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {suggestions.map((advisory) => {
                const key = advisoryKey(advisory)
                const isPlaced = placedIds.has(key)
                const isPending = pendingId === key
                const isExpanded = expandedId === key
                const tp = advisory.trading_plan!
                const est = advisory.estimate
                const ai = advisory.ai_detail

                return (
                  <div
                    key={key}
                    className={`rounded-xl border transition-colors ${isExpanded ? 'border-blue-200 bg-blue-50/30' : 'border-gray-100 bg-gray-50/50 hover:bg-gray-50'}`}
                  >
                    {/* Summary row */}
                    <div
                      className="flex items-center gap-4 p-4 cursor-pointer select-none"
                      onClick={() => setExpandedId(isExpanded ? null : key)}
                    >
                      {/* Chevron */}
                      <svg
                        className={`w-4 h-4 text-gray-400 shrink-0 transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`}
                        fill="none" stroke="currentColor" viewBox="0 0 24 24"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>

                      {/* Game info */}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">
                          {advisory.game.away_team_abbreviation} @ {advisory.game.home_team_abbreviation}
                        </p>
                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          <span className={`text-xs font-medium rounded px-1.5 py-0.5 ${tp.exit_price != null ? 'bg-indigo-100 text-indigo-700' : 'bg-emerald-100 text-emerald-700'}`}>
                            {tp.exit_price != null ? 'TRADE' : 'RESOLUTION'}
                          </span>
                          <span className={`text-xs font-medium rounded px-1.5 py-0.5 ${verdictColor(est.verdict)}`}>
                            {est.bet_side.toUpperCase() === 'HOME' ? 'BET HOME' : 'BET AWAY'}
                          </span>
                          <span className="text-xs text-gray-500">
                            {est.bet_side.toUpperCase() === 'HOME' ? advisory.game.home_team_abbreviation : advisory.game.away_team_abbreviation}
                          </span>
                        </div>
                      </div>

                      {/* Stats */}
                      <div className="flex items-center gap-3 text-xs tabular-nums shrink-0">
                        <div className="text-center">
                          <p className="text-gray-400 uppercase tracking-wide" style={{ fontSize: '0.625rem' }}>Conf</p>
                          <p className="font-semibold text-gray-900">{est.confidence.toFixed(1)}</p>
                        </div>
                        <div className="text-center">
                          <p className="text-gray-400 uppercase tracking-wide" style={{ fontSize: '0.625rem' }}>Edge</p>
                          <p className="font-semibold text-gray-900">{est.edge_percent.toFixed(1)}%</p>
                        </div>
                        <div className="text-center">
                          <p className="text-gray-400 uppercase tracking-wide" style={{ fontSize: '0.625rem' }}>ROI</p>
                          <p className="font-semibold text-gray-900">{tp.expected_roi.toFixed(1)}%</p>
                        </div>
                        <div className="text-center">
                          <p className="text-gray-400 uppercase tracking-wide" style={{ fontSize: '0.625rem' }}>Bet</p>
                          <p className="font-semibold text-gray-900">${est.suggested_bet_usdc.toFixed(0)}</p>
                        </div>
                      </div>

                      {/* Action button */}
                      <div className="shrink-0" onClick={(e) => e.stopPropagation()}>
                        {isPlaced ? (
                          <span className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-green-700 bg-green-100 rounded-lg">
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                            </svg>
                            Placed
                          </span>
                        ) : (
                          <button
                            onClick={() => handlePlaceOrder(advisory)}
                            disabled={isPending}
                            className="px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
                          >
                            {isPending ? (
                              <span className="inline-flex items-center gap-1.5">
                                <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                Placing...
                              </span>
                            ) : (
                              'Place Order'
                            )}
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Expanded details */}
                    {isExpanded && (
                      <div className="px-4 pb-4 pt-1 border-t border-gray-100/80 space-y-3">
                        {/* Trading Plan */}
                        <div>
                          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Trading Plan</p>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                            <div className="bg-white rounded-lg px-2.5 py-1.5 border border-gray-100">
                              <span className="text-gray-400">Entry</span>
                              <span className="float-right font-medium text-gray-900">{pct(tp.entry_price)}</span>
                            </div>
                            {tp.exit_price != null && (
                              <div className="bg-white rounded-lg px-2.5 py-1.5 border border-gray-100">
                                <span className="text-gray-400">Exit</span>
                                <span className="float-right font-medium text-gray-900">{pct(tp.exit_price)}</span>
                              </div>
                            )}
                            <div className="bg-white rounded-lg px-2.5 py-1.5 border border-gray-100">
                              <span className="text-gray-400">Strategy</span>
                              <span className="float-right font-medium text-gray-900">{tp.strategy}</span>
                            </div>
                            {tp.spread != null && (
                              <div className="bg-white rounded-lg px-2.5 py-1.5 border border-gray-100">
                                <span className="text-gray-400">Spread</span>
                                <span className="float-right font-medium text-gray-900">{pct(tp.spread)}</span>
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Probabilities */}
                        <div>
                          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Probabilities</p>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                            <div className="bg-white rounded-lg px-2.5 py-1.5 border border-gray-100">
                              <span className="text-gray-400">Model ({advisory.game.home_team_abbreviation})</span>
                              <span className="float-right font-medium text-gray-900">{pct(est.model_prob)}</span>
                            </div>
                            <div className="bg-white rounded-lg px-2.5 py-1.5 border border-gray-100">
                              <span className="text-gray-400">Market ({advisory.game.home_team_abbreviation})</span>
                              <span className="float-right font-medium text-gray-900">{pct(est.market_prob)}</span>
                            </div>
                            <div className="bg-white rounded-lg px-2.5 py-1.5 border border-gray-100">
                              <span className="text-gray-400">Blended ({advisory.game.home_team_abbreviation})</span>
                              <span className="float-right font-medium text-gray-900">{pct(est.blended_prob)}</span>
                            </div>
                            <div className="bg-white rounded-lg px-2.5 py-1.5 border border-gray-100">
                              <span className="text-gray-400">Kelly</span>
                              <span className="float-right font-medium text-gray-900">{pct(est.kelly_fraction)}</span>
                            </div>
                          </div>
                        </div>

                        {/* AI Analysis */}
                        {ai && (
                          <div>
                            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">AI Analysis</p>
                            <div className="bg-white rounded-lg px-3 py-2 border border-gray-100 space-y-1.5">
                              <p className="text-xs font-medium text-gray-900">{ai.headline}</p>
                              <p className="text-xs text-gray-600 line-clamp-2">{ai.verdict_rationale}</p>
                              <div className="flex gap-3 text-xs pt-0.5">
                                <span className="text-gray-400">
                                  Efficiency: <span className={`font-medium ${efficiencyColor(ai.market_efficiency)}`}>{ai.market_efficiency}</span>
                                </span>
                                <span className="text-gray-400">
                                  Upset risk: <span className={`font-medium ${upsetRiskColor(ai.upset_risk)}`}>{ai.upset_risk.replace('_', ' ')}</span>
                                </span>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Factors */}
                        {est.factors_summary.length > 0 && (
                          <div>
                            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Key Factors</p>
                            <ul className="space-y-0.5">
                              {est.factors_summary.map((f, i) => (
                                <li key={i} className="text-xs text-gray-600 flex gap-1.5">
                                  <span className="text-gray-300 shrink-0">&bull;</span>
                                  {f}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* Liquidity warning */}
                        {tp.liquidity_warning && (
                          <div className="flex items-center gap-2 bg-amber-50 text-amber-700 rounded-lg px-3 py-2 text-xs border border-amber-200">
                            <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            Low liquidity &mdash; depth available: ${tp.depth_available.toFixed(0)}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-100 flex items-center justify-between">
          <div>
            {advisories[0]?.analyzed_at && (
              <p className="text-xs text-gray-400">
                Analyzed {new Date(advisories[0].analyzed_at).toLocaleTimeString()}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {onReAnalyze && (
              <button
                onClick={onReAnalyze}
                disabled={isReAnalyzing}
                className="px-4 py-2 text-sm font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl transition-colors"
              >
                {isReAnalyzing ? (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block w-3 h-3 border-2 border-amber-300 border-t-amber-600 rounded-full animate-spin" />
                    Re-Analyzing...
                  </span>
                ) : (
                  'Re-Analyze'
                )}
              </button>
            )}
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-xl transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
