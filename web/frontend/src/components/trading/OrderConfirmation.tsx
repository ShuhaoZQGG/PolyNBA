import { useEffect } from 'react'
import type { GameAdvisoryResponse } from '../../api/types'
import { usePlaceOrder } from '../../api/hooks'
import useStore from '../../store/useStore'
import TeamBadge from '../games/TeamBadge'

interface OrderConfirmationProps {
  advisory: GameAdvisoryResponse
  selectedTeam: 'home' | 'away'
  orderSide: 'BUY' | 'SELL'
  orderAmount: number
  selectedPrice: number
  selectedTokenId: string
  sharesEstimate: number
  estPayout: number
  onClose: () => void
}

export default function OrderConfirmation({
  advisory,
  selectedTeam,
  orderSide,
  orderAmount,
  selectedPrice,
  selectedTokenId,
  sharesEstimate,
  estPayout,
  onClose,
}: OrderConfirmationProps) {
  const { game, market } = advisory
  const { resetForm } = useStore()
  const placeOrder = usePlaceOrder()

  // Close on Escape
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  const teamAbbr =
    selectedTeam === 'home' ? game.home_team_abbreviation : game.away_team_abbreviation
  const teamName =
    selectedTeam === 'home' ? game.home_team_name : game.away_team_name

  async function handleConfirm() {
    try {
      await placeOrder.mutateAsync({
        market_id: market.condition_id,
        token_id: selectedTokenId,
        side: orderSide.toLowerCase() as 'buy' | 'sell',
        size_usdc: orderAmount,
        price: selectedPrice,
      })
      resetForm()
      onClose()
    } catch {
      // Error is shown via placeOrder.error
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 z-10">
        <h3 className="text-base font-semibold text-gray-900 mb-1">Confirm Order</h3>
        <p className="text-xs text-gray-400 mb-5">Review your order before placing</p>

        {/* Order summary */}
        <div className="rounded-xl border border-[#E5E5E5] divide-y divide-gray-50 mb-5">
          <div className="flex justify-between items-center px-4 py-3">
            <span className="text-xs text-gray-500">Outcome</span>
            <div className="flex items-center gap-2">
              <TeamBadge abbr={teamAbbr} size="sm" />
              <span className="text-xs text-gray-700">{teamName} wins</span>
            </div>
          </div>
          <div className="flex justify-between items-center px-4 py-3">
            <span className="text-xs text-gray-500">Side</span>
            <span className={`text-xs font-semibold ${orderSide === 'BUY' ? 'text-green-600' : 'text-red-600'}`}>
              {orderSide}
            </span>
          </div>
          <div className="flex justify-between items-center px-4 py-3">
            <span className="text-xs text-gray-500">Limit Price</span>
            <span className="text-xs font-mono font-semibold text-gray-800">
              {Math.round(selectedPrice * 100)}&#162;
            </span>
          </div>
          <div className="flex justify-between items-center px-4 py-3">
            <span className="text-xs text-gray-500">Shares</span>
            <span className="text-xs font-semibold tabular-nums text-gray-800">
              {sharesEstimate.toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between items-center px-4 py-3">
            <span className="text-xs text-gray-500">Total Cost</span>
            <span className="text-sm font-semibold tabular-nums text-gray-900">
              ${orderAmount.toFixed(2)} USDC
            </span>
          </div>
          <div className="flex justify-between items-center px-4 py-3">
            <span className="text-xs text-gray-500">Est. payout (if win)</span>
            <span className="text-xs font-semibold tabular-nums text-green-600">
              ${estPayout.toFixed(2)}
            </span>
          </div>
        </div>

        {/* Error message */}
        {placeOrder.error && (
          <div className="mb-4 px-3 py-2 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-xs text-red-600">{placeOrder.error.message}</p>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={placeOrder.isPending}
            className="flex-1 py-2.5 rounded-lg border border-[#E5E5E5] text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={placeOrder.isPending}
            className="flex-1 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
          >
            {placeOrder.isPending ? (
              <>
                <span className="inline-block w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                Placing...
              </>
            ) : (
              'Confirm Order'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
