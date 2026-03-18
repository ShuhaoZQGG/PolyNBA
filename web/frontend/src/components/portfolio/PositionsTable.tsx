import { useState } from 'react'
import type { Position } from '../../api/types'
import SellModal from './SellModal'

interface PositionsTableProps {
  positions: Position[]
}

export default function PositionsTable({ positions }: PositionsTableProps) {
  const [sellPosition, setSellPosition] = useState<Position | null>(null)

  if (positions.length === 0) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-gray-400">No open positions</p>
      </div>
    )
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
              <th className="px-5 py-3">Market</th>
              <th className="px-5 py-3 text-right">Avg &rarr; Now</th>
              <th className="px-5 py-3 text-right">Traded</th>
              <th className="px-5 py-3 text-right">To Win</th>
              <th className="px-5 py-3 text-right">Value</th>
              <th className="px-5 py-3 text-right"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F0F0F0]">
            {positions.map((pos) => (
              <tr key={pos.token_id} className="hover:bg-gray-50/50">
                {/* Market column: name + outcome badge with price + shares */}
                <td className="px-5 py-3.5">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-gray-900 font-medium truncate max-w-[280px]">
                      {pos.market_name}
                    </span>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <span className="bg-gray-100 text-gray-700 rounded px-1.5 py-0.5 font-medium">
                        {pos.outcome}
                      </span>
                      <span className="tabular-nums">
                        {(pos.current_price * 100).toFixed(0)}&cent;
                      </span>
                      <span className="tabular-nums">{pos.shares.toFixed(1)} shares</span>
                    </div>
                  </div>
                </td>
                {/* AVG -> NOW */}
                <td className="px-5 py-3.5 text-right whitespace-nowrap">
                  <span className="tabular-nums text-gray-500">
                    {(pos.avg_price * 100).toFixed(0)}&cent;
                  </span>
                  <span className="text-gray-300 mx-1">&rarr;</span>
                  <span
                    className={`tabular-nums font-medium ${
                      pos.current_price >= pos.avg_price ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {(pos.current_price * 100).toFixed(0)}&cent;
                  </span>
                </td>
                {/* TRADED (cost) */}
                <td className="px-5 py-3.5 text-right whitespace-nowrap tabular-nums text-gray-700">
                  ${pos.cost.toFixed(2)}
                </td>
                {/* TO WIN */}
                <td className="px-5 py-3.5 text-right whitespace-nowrap tabular-nums text-gray-700">
                  ${pos.to_win.toFixed(2)}
                </td>
                {/* VALUE with P&L */}
                <td className="px-5 py-3.5 text-right whitespace-nowrap">
                  <div className="flex flex-col items-end">
                    <span className="tabular-nums font-medium text-gray-900">
                      ${pos.current_value.toFixed(2)}
                    </span>
                    <span
                      className={`text-xs tabular-nums ${
                        pos.pnl >= 0 ? 'text-green-600' : 'text-red-600'
                      }`}
                    >
                      {pos.pnl >= 0 ? '+' : ''}${pos.pnl.toFixed(2)} ({pos.pnl >= 0 ? '+' : ''}
                      {pos.pnl_percent.toFixed(1)}%)
                    </span>
                  </div>
                </td>
                {/* Sell button */}
                <td className="px-5 py-3.5 text-right">
                  <button
                    onClick={() => setSellPosition(pos)}
                    className="px-3 py-1.5 text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors"
                  >
                    Sell
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sellPosition && (
        <SellModal position={sellPosition} onClose={() => setSellPosition(null)} />
      )}
    </>
  )
}
