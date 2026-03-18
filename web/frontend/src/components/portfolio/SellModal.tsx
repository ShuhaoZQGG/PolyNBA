import { useState } from 'react'
import type { Position } from '../../api/types'
import { usePlaceOrder } from '../../api/hooks'

interface SellModalProps {
  position: Position
  onClose: () => void
}

export default function SellModal({ position, onClose }: SellModalProps) {
  const [shares, setShares] = useState(position.shares.toString())
  const [price, setPrice] = useState(position.current_price.toFixed(4))
  const placeOrder = usePlaceOrder()

  const sharesNum = parseFloat(shares) || 0
  const priceNum = parseFloat(price) || 0
  const proceeds = sharesNum * priceNum
  const isValid =
    sharesNum > 0 && sharesNum <= position.shares && priceNum > 0 && priceNum < 1

  const handleSell = () => {
    if (!isValid) return
    placeOrder.mutate(
      {
        market_id: position.condition_id,
        token_id: position.token_id,
        side: 'sell',
        size_usdc: proceeds,
        price: priceNum,
      },
      {
        onSuccess: () => onClose(),
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-lg font-semibold text-gray-900">Sell Position</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        {/* Position info */}
        <div className="bg-gray-50 rounded-xl p-4 mb-5">
          <p className="text-sm font-medium text-gray-900 truncate">{position.market_name}</p>
          <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
            <span className="bg-gray-200 text-gray-700 rounded px-1.5 py-0.5 font-medium">
              {position.outcome}
            </span>
            <span className="tabular-nums">{position.shares.toFixed(1)} shares held</span>
            <span className="tabular-nums">@ {(position.avg_price * 100).toFixed(0)}&cent; avg</span>
          </div>
        </div>

        {/* Shares input */}
        <div className="mb-4">
          <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">
            Shares to sell
          </label>
          <div className="flex gap-2">
            <input
              type="number"
              step="0.1"
              min="0"
              max={position.shares}
              value={shares}
              onChange={(e) => setShares(e.target.value)}
              className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <button
              onClick={() => setShares(position.shares.toString())}
              className="px-3 py-2 text-xs font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
            >
              Max
            </button>
          </div>
        </div>

        {/* Price input */}
        <div className="mb-5">
          <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">
            Price per share
          </label>
          <input
            type="number"
            step="0.01"
            min="0.01"
            max="0.99"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        {/* Estimated proceeds */}
        <div className="flex items-center justify-between py-3 border-t border-gray-100 mb-5">
          <span className="text-sm text-gray-500">Est. proceeds</span>
          <span className="text-lg font-semibold tabular-nums text-gray-900">
            ${proceeds.toFixed(2)}
          </span>
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-xl transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSell}
            disabled={!isValid || placeOrder.isPending}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl transition-colors"
          >
            {placeOrder.isPending ? 'Selling...' : 'Confirm Sell'}
          </button>
        </div>

        {placeOrder.isError && (
          <p className="mt-3 text-xs text-red-500 text-center">
            {placeOrder.error?.message ?? 'Failed to place sell order'}
          </p>
        )}
      </div>
    </div>
  )
}
