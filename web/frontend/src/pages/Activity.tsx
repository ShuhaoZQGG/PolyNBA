import { useState } from 'react'
import { useOrders, usePortfolio, usePositions, useTradeHistory } from '../api/hooks'
import type { TradeHistoryEntry } from '../api/types'
import OrdersTable from '../components/trading/OrdersTable'
import BalanceCard from '../components/portfolio/BalanceCard'
import PositionsTable from '../components/portfolio/PositionsTable'
import PnLChart from '../components/portfolio/PnLChart'
import { SkeletonCard } from '../components/common/LoadingSkeleton'
import PregameOrdersTab from '../components/pregame/PregameOrdersTab'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(isoTimestamp: string): string {
  const now = Date.now()
  const then = new Date(isoTimestamp).getTime()
  const diffMs = now - then
  if (Number.isNaN(diffMs) || diffMs < 0) return ''

  const mins = Math.floor(diffMs / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`

  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`

  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`

  return new Date(isoTimestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

const ACTIVITY_STYLES: Record<string, { icon: string; color: string }> = {
  Bought: { icon: '↗', color: 'text-blue-600' },
  Sold: { icon: '↙', color: 'text-orange-600' },
  Won: { icon: '✓', color: 'text-green-600' },
  Lost: { icon: '✗', color: 'text-red-500' },
}

function ActivityBadge({ activity }: { activity: string }) {
  const style = ACTIVITY_STYLES[activity] ?? { icon: '•', color: 'text-gray-500' }
  return (
    <span className={`inline-flex items-center gap-1 text-sm font-medium ${style.color}`}>
      <span className="text-base leading-none">{style.icon}</span>
      {activity}
    </span>
  )
}

function ValueCell({ value }: { value: number }) {
  if (value === 0) return <span className="text-gray-400">-</span>
  const isPositive = value > 0
  return (
    <span className={`tabular-nums font-medium ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
      {isPositive ? '+' : ''}${Math.abs(value).toFixed(2)}
    </span>
  )
}

// ---------------------------------------------------------------------------
// History Table
// ---------------------------------------------------------------------------

function HistoryTable({ entries }: { entries: TradeHistoryEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-gray-400">No trade history yet</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
            <th className="px-5 py-3">Activity</th>
            <th className="px-5 py-3">Market</th>
            <th className="px-5 py-3 text-right">Value</th>
            <th className="px-5 py-3 text-right">Time</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#F0F0F0]">
          {entries.map((entry, idx) => (
            <tr key={`${entry.asset_id}-${entry.timestamp}-${idx}`} className="hover:bg-gray-50/50">
              <td className="px-5 py-3.5 whitespace-nowrap">
                <ActivityBadge activity={entry.activity} />
              </td>
              <td className="px-5 py-3.5">
                <div className="flex flex-col gap-0.5">
                  <span className="text-gray-900 font-medium truncate max-w-[280px]">
                    {entry.market_name}
                  </span>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    {entry.outcome && (
                      <span className="inline-flex items-center gap-1">
                        <span className="bg-gray-100 text-gray-700 rounded px-1.5 py-0.5 font-medium">
                          {entry.outcome}
                        </span>
                        <span className="tabular-nums">{(entry.price * 100).toFixed(0)}&cent;</span>
                      </span>
                    )}
                    <span className="tabular-nums">{entry.shares.toFixed(1)} shares</span>
                  </div>
                </div>
              </td>
              <td className="px-5 py-3.5 text-right whitespace-nowrap">
                <ValueCell value={entry.value} />
              </td>
              <td className="px-5 py-3.5 text-right whitespace-nowrap text-xs text-gray-400">
                {relativeTime(entry.timestamp)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type ActiveTab = 'positions' | 'orders' | 'history' | 'pregame'

export default function Activity() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('positions')

  const { data: orders, isLoading: ordersLoading, error: ordersError } = useOrders()
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio()
  const { data: positions, isLoading: positionsLoading, error: positionsError } = usePositions()
  const { data: history, isLoading: historyLoading, error: historyError } = useTradeHistory()

  const openOrders = orders?.filter((o) => {
    const s = o.status.toLowerCase()
    return s === 'live' || s === 'open'
  }) ?? []

  // Build P&L chart from real trade history
  const pnlData = (() => {
    if (!history?.entries.length) return []
    // Sort oldest first for cumulative chart
    const sorted = [...history.entries].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
    )
    let running = 0
    return sorted.map((e) => {
      running += e.value
      return {
        time: new Date(e.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        pnl: parseFloat(running.toFixed(2)),
      }
    })
  })()

  const TAB_LABELS: Record<ActiveTab, string> = {
    positions: 'Positions',
    orders: 'Open Orders',
    history: 'History',
    pregame: 'Pregame Orders',
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Activity</h1>
        {history && (
          <div className="flex items-center gap-4 text-sm">
            <span
              className={`font-semibold tabular-nums ${
                history.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
              }`}
            >
              P&L: {history.total_pnl >= 0 ? '+' : ''}${history.total_pnl.toFixed(2)}
            </span>
            {history.total_fees > 0 && (
              <span className="text-gray-400 tabular-nums">
                Fees: ${history.total_fees.toFixed(2)}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Portfolio overview */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {portfolioLoading ? (
          <>
            <SkeletonCard />
            <SkeletonCard />
          </>
        ) : portfolio ? (
          <>
            <BalanceCard portfolio={portfolio} />
            <PnLChart data={pnlData} title="Realized P&L" />
          </>
        ) : null}
      </div>

      {/* Tabbed card: Positions | Open Orders | History */}
      <div className="rounded-xl border border-[#E5E5E5] bg-white shadow-sm overflow-hidden">
        {/* Tab bar */}
        <div className="border-b border-[#E5E5E5]">
          <div className="flex gap-0">
            {(['positions', 'orders', 'history', 'pregame'] as const).map((tab) => {
              const isActive = activeTab === tab
              return (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-5 py-3 text-sm font-medium transition-colors relative ${
                    isActive ? 'text-gray-900' : 'text-gray-400 hover:text-gray-600'
                  }`}
                >
                  {TAB_LABELS[tab]}
                  {isActive && (
                    <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-gray-900 rounded-full" />
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {/* Tab content */}
        {activeTab === 'positions' && (
          <>
            {positionsError ? (
              <div className="p-6 text-center">
                <p className="text-sm text-red-500">
                  Failed to load positions: {positionsError.message}
                </p>
              </div>
            ) : positionsLoading ? (
              <div className="p-6 flex items-center justify-center">
                <span className="inline-block w-5 h-5 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" />
              </div>
            ) : (
              <PositionsTable positions={positions?.positions ?? []} />
            )}
          </>
        )}

        {activeTab === 'orders' && (
          <>
            {ordersError ? (
              <div className="p-6 text-center">
                <p className="text-sm text-red-500">
                  Failed to load orders: {ordersError.message}
                </p>
              </div>
            ) : ordersLoading ? (
              <div className="p-6 flex items-center justify-center">
                <span className="inline-block w-5 h-5 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" />
              </div>
            ) : (
              <OrdersTable orders={openOrders} showCancel />
            )}
          </>
        )}

        {activeTab === 'history' && (
          <>
            {historyError ? (
              <div className="p-6 text-center">
                <p className="text-sm text-red-500">
                  Failed to load history: {historyError.message}
                </p>
              </div>
            ) : historyLoading ? (
              <div className="p-6 flex items-center justify-center">
                <span className="inline-block w-5 h-5 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" />
              </div>
            ) : (
              <HistoryTable entries={history?.entries ?? []} />
            )}
          </>
        )}

        {activeTab === 'pregame' && <PregameOrdersTab />}
      </div>
    </div>
  )
}
