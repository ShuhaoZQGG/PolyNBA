import { useState } from 'react'
import { usePregameDates, usePregameOrders, useCheckFills, usePlaceSell, useUpdateExitPrice } from '../../api/hooks'
import type { PregameOrder } from '../../api/types'

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<string, string> = {
  OPEN: 'bg-blue-50 text-blue-700',
  MATCHED: 'bg-amber-50 text-amber-700',
  SELL_PLACED: 'bg-purple-50 text-purple-700',
}

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PregameOrdersTab() {
  const { data: datesData, isLoading: datesLoading } = usePregameDates()
  const dates = datesData?.dates ?? []

  const [selectedDate, setSelectedDate] = useState<string>('')
  const activeDate = selectedDate || dates[0] || ''

  const { data, isLoading, error } = usePregameOrders(activeDate)
  const checkFills = useCheckFills()
  const placeSell = usePlaceSell()
  const updateExitPrice = useUpdateExitPrice()

  const [editingOrderId, setEditingOrderId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState<string>('')

  if (datesLoading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <span className="inline-block w-5 h-5 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" />
      </div>
    )
  }

  if (dates.length === 0) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-gray-400">No pregame order ledgers found</p>
      </div>
    )
  }

  return (
    <div>
      {/* Controls bar */}
      <div className="flex items-center gap-3 px-5 py-3 border-b border-[#E5E5E5]">
        <select
          value={activeDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-300"
        >
          {dates.map((d) => (
            <option key={d} value={d}>
              {d.slice(0, 4)}-{d.slice(4, 6)}-{d.slice(6, 8)}
            </option>
          ))}
        </select>

        <button
          onClick={() => checkFills.mutate(activeDate)}
          disabled={checkFills.isPending}
          className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50 transition-colors"
        >
          {checkFills.isPending ? 'Checking...' : 'Check Fills'}
        </button>

        {data?.summary && (
          <span className="ml-auto text-xs text-gray-400 tabular-nums">
            {data.summary.total} orders &middot; ${data.summary.total_cost.toFixed(2)} cost
          </span>
        )}
      </div>

      {/* Needs-sell alert */}
      {data?.summary && data.summary.needs_sell > 0 && (
        <div className="mx-5 mt-3 rounded-lg bg-amber-50 border border-amber-200 px-4 py-2.5 text-sm text-amber-800">
          {data.summary.needs_sell} order(s) filled — place sell orders
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-6 text-center">
          <p className="text-sm text-red-500">Failed to load orders: {error.message}</p>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="p-6 flex items-center justify-center">
          <span className="inline-block w-5 h-5 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" />
        </div>
      )}

      {/* Orders table */}
      {data && !isLoading && (
        <div className="overflow-x-auto">
          {data.orders.length === 0 ? (
            <div className="p-8 text-center">
              <p className="text-sm text-gray-400">No orders for this date</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  <th className="px-5 py-3">Game</th>
                  <th className="px-5 py-3">Team</th>
                  <th className="px-5 py-3">Strategy</th>
                  <th className="px-5 py-3 text-right">Entry</th>
                  <th className="px-5 py-3 text-right">Exit</th>
                  <th className="px-5 py-3 text-right">Filled</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F0F0F0]">
                {data.orders.map((order: PregameOrder) => (
                  <tr
                    key={order.order_id}
                    className={`hover:bg-gray-50/50 ${order.needs_sell ? 'border-l-2 border-l-amber-400' : ''}`}
                  >
                    <td className="px-5 py-3.5 text-gray-900 font-medium whitespace-nowrap">
                      {order.game}
                    </td>
                    <td className="px-5 py-3.5 text-gray-700 whitespace-nowrap">
                      {order.team}
                    </td>
                    <td className="px-5 py-3.5 text-gray-600 whitespace-nowrap">
                      {order.strategy}
                    </td>
                    <td className="px-5 py-3.5 text-right whitespace-nowrap tabular-nums">
                      {order.shares} @ {(order.entry_price * 100).toFixed(0)}&cent;
                    </td>
                    <td className="px-5 py-3.5 text-right whitespace-nowrap tabular-nums">
                      {editingOrderId === order.order_id ? (
                        <input
                          type="number"
                          autoFocus
                          className="w-16 rounded border border-gray-300 px-1.5 py-0.5 text-right text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-gray-400"
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              const cents = parseInt(editValue, 10)
                              updateExitPrice.mutate({
                                orderId: order.order_id,
                                date: activeDate,
                                exitPrice: isNaN(cents) || editValue.trim() === '' ? null : cents / 100,
                              })
                              setEditingOrderId(null)
                            } else if (e.key === 'Escape') {
                              setEditingOrderId(null)
                            }
                          }}
                          onBlur={() => {
                            const cents = parseInt(editValue, 10)
                            updateExitPrice.mutate({
                              orderId: order.order_id,
                              date: activeDate,
                              exitPrice: isNaN(cents) || editValue.trim() === '' ? null : cents / 100,
                            })
                            setEditingOrderId(null)
                          }}
                        />
                      ) : (
                        <span
                          className={`group cursor-pointer ${order.status === 'SELL_PLACED' ? 'cursor-default' : ''}`}
                          onClick={() => {
                            if (order.status === 'SELL_PLACED') return
                            setEditingOrderId(order.order_id)
                            setEditValue(order.exit_price ? (order.exit_price * 100).toFixed(0) : '')
                          }}
                        >
                          {order.exit_price ? `${(order.exit_price * 100).toFixed(0)}\u00a2` : (
                            <span className="text-gray-400">HOLD</span>
                          )}
                          {order.status !== 'SELL_PLACED' && (
                            <svg className="inline-block ml-1 w-3 h-3 text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                            </svg>
                          )}
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3.5 text-right whitespace-nowrap tabular-nums">
                      {order.filled_shares}/{order.shares}
                    </td>
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <StatusBadge status={order.status} />
                    </td>
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      {order.needs_sell && (
                        <button
                          onClick={() => placeSell.mutate({ orderId: order.order_id, date: activeDate })}
                          disabled={placeSell.isPending}
                          className="rounded-md bg-amber-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-amber-600 disabled:opacity-50 transition-colors"
                        >
                          Place Sell
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
