import { useEffect, useRef } from 'react'
import type { GameAdvisoryResponse } from '../../api/types'
import useStore from '../../store/useStore'
import { usePortfolio } from '../../api/hooks'
import TeamBadge from '../games/TeamBadge'
import OrderConfirmation from './OrderConfirmation'

interface OrderFormProps {
  advisory: GameAdvisoryResponse
}

const QUICK_SHARES = [10, 50, 100, 500]

export default function OrderForm({ advisory }: OrderFormProps) {
  const { game, prices, market } = advisory

  const {
    selectedTeam,
    orderSide,
    orderShares,
    orderPrice,
    showConfirmation,
    setSelectedTeam,
    setOrderSide,
    setOrderShares,
    setOrderPrice,
    addToShares,
    setShowConfirmation,
  } = useStore()

  const { data: portfolio } = usePortfolio()

  const homeAbbr = game.home_team_abbreviation
  const awayAbbr = game.away_team_abbreviation
  const homeMid = prices.home_mid_price
  const awayMid = prices.away_mid_price

  const selectedMid = selectedTeam === 'home' ? homeMid : awayMid
  const selectedTokenId = selectedTeam === 'home' ? market.home_token_id : market.away_token_id

  // Initialize price to mid price when team changes or on first render
  const prevTeamRef = useRef(selectedTeam)
  useEffect(() => {
    if (orderPrice === 0 || prevTeamRef.current !== selectedTeam) {
      setOrderPrice(selectedMid)
      prevTeamRef.current = selectedTeam
    }
  }, [selectedTeam, selectedMid, orderPrice, setOrderPrice])

  // Derived values
  const cost = orderShares * orderPrice
  const estPayout = orderShares // each share pays $1 if win
  const estProfit = estPayout - cost

  const availableBalance = portfolio?.balance.available_usdc ?? 0

  function handleSharesChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = parseFloat(e.target.value)
    if (!isNaN(val)) setOrderShares(val)
    else if (e.target.value === '') setOrderShares(0)
  }

  function handlePriceChange(e: React.ChangeEvent<HTMLInputElement>) {
    const cents = parseInt(e.target.value, 10)
    if (!isNaN(cents)) setOrderPrice(cents / 100)
    else if (e.target.value === '') setOrderPrice(0)
  }

  function handleMaxShares() {
    if (orderPrice > 0) {
      setOrderShares(Math.floor(availableBalance / orderPrice))
    }
  }

  const canPlace =
    orderShares > 0 &&
    orderPrice > 0 &&
    orderPrice < 1 &&
    cost <= availableBalance + 0.001

  // Values passed to confirmation (backend still expects size_usdc + price)
  const orderAmount = cost

  return (
    <>
      <div className="rounded-xl border border-[#E5E5E5] bg-white shadow-sm overflow-hidden">
        {/* Header */}
        <div className="px-5 py-4 border-b border-[#E5E5E5]">
          <h3 className="text-sm font-semibold text-gray-900">Place Order</h3>
          <p className="text-xs text-gray-400 mt-0.5">
            {market.is_tradeable ? 'Market is active' : 'Market not tradeable'}
          </p>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Team selector */}
          <div>
            <p className="text-xs font-medium text-gray-500 mb-2">Select Outcome</p>
            <div className="flex gap-2">
              <button
                className={`flex-1 flex items-center justify-between px-3 py-2.5 rounded-lg border-2 transition-all text-sm ${
                  selectedTeam === 'away'
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-[#E5E5E5] bg-white hover:border-gray-300'
                }`}
                onClick={() => setSelectedTeam('away')}
              >
                <TeamBadge abbr={awayAbbr} size="sm" />
                <span className="font-mono text-xs font-semibold text-gray-700">
                  {Math.round(awayMid * 100)}&#162;
                </span>
              </button>
              <button
                className={`flex-1 flex items-center justify-between px-3 py-2.5 rounded-lg border-2 transition-all text-sm ${
                  selectedTeam === 'home'
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-[#E5E5E5] bg-white hover:border-gray-300'
                }`}
                onClick={() => setSelectedTeam('home')}
              >
                <TeamBadge abbr={homeAbbr} size="sm" />
                <span className="font-mono text-xs font-semibold text-gray-700">
                  {Math.round(homeMid * 100)}&#162;
                </span>
              </button>
            </div>
          </div>

          {/* Buy / Sell toggle */}
          <div>
            <p className="text-xs font-medium text-gray-500 mb-2">Side</p>
            <div className="flex rounded-lg overflow-hidden border border-[#E5E5E5]">
              <button
                className={`flex-1 py-2 text-sm font-semibold transition-colors ${
                  orderSide === 'BUY'
                    ? 'bg-green-600 text-white'
                    : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
                onClick={() => setOrderSide('BUY')}
              >
                Buy
              </button>
              <button
                className={`flex-1 py-2 text-sm font-semibold transition-colors ${
                  orderSide === 'SELL'
                    ? 'bg-red-600 text-white'
                    : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
                onClick={() => setOrderSide('SELL')}
              >
                Sell
              </button>
            </div>
          </div>

          {/* Shares input */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-medium text-gray-500">Shares</p>
              {portfolio && (
                <p className="text-xs text-gray-400">
                  Avail: ${availableBalance.toFixed(2)}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2 border border-[#E5E5E5] rounded-lg overflow-hidden focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-500">
              <input
                type="number"
                min="0"
                step="1"
                value={orderShares || ''}
                onChange={handleSharesChange}
                placeholder="0"
                className="flex-1 py-2.5 px-3 text-sm font-medium text-gray-900 outline-none bg-transparent"
              />
            </div>
            {/* Quick add buttons */}
            <div className="flex gap-1.5 mt-2">
              {QUICK_SHARES.map((n) => (
                <button
                  key={n}
                  onClick={() => addToShares(n)}
                  className="flex-1 py-1 text-xs font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded transition-colors"
                >
                  +{n}
                </button>
              ))}
              <button
                onClick={handleMaxShares}
                className="px-2 py-1 text-xs font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded transition-colors"
              >
                Max
              </button>
            </div>
          </div>

          {/* Limit Price input */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-medium text-gray-500">Limit Price</p>
              <p className="text-xs text-gray-400">
                Mid: {Math.round(selectedMid * 100)}&cent;
              </p>
            </div>
            <div className="flex items-center gap-2 border border-[#E5E5E5] rounded-lg overflow-hidden focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-500">
              <input
                type="number"
                min="1"
                max="99"
                step="1"
                value={orderPrice > 0 ? Math.round(orderPrice * 100) : ''}
                onChange={handlePriceChange}
                placeholder="1–99"
                className="flex-1 py-2.5 px-3 text-sm font-medium text-gray-900 outline-none bg-transparent"
              />
              <span className="pr-3 text-gray-400 text-sm">&cent;</span>
            </div>
          </div>

          {/* Order summary */}
          {orderShares > 0 && orderPrice > 0 && (
            <div className="rounded-lg bg-gray-50 border border-[#E5E5E5] divide-y divide-gray-100">
              <div className="flex justify-between items-center px-3 py-2">
                <span className="text-xs text-gray-500">Shares</span>
                <span className="text-xs font-semibold tabular-nums text-gray-800">
                  {orderShares}
                </span>
              </div>
              <div className="flex justify-between items-center px-3 py-2">
                <span className="text-xs text-gray-500">Price per share</span>
                <span className="text-xs font-mono font-semibold text-gray-800">
                  {Math.round(orderPrice * 100)}&#162;
                </span>
              </div>
              <div className="flex justify-between items-center px-3 py-2">
                <span className="text-xs text-gray-500">Cost</span>
                <span className="text-xs font-semibold tabular-nums text-gray-800">
                  ${cost.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between items-center px-3 py-2">
                <span className="text-xs text-gray-500">Est. payout (if win)</span>
                <span className="text-xs font-semibold tabular-nums text-green-600">
                  ${estPayout.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between items-center px-3 py-2">
                <span className="text-xs text-gray-500">Est. profit (if win)</span>
                <span className={`text-xs font-semibold tabular-nums ${estProfit >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {estProfit >= 0 ? '+' : ''}${estProfit.toFixed(2)}
                </span>
              </div>
            </div>
          )}

          {/* Place order button */}
          <button
            disabled={!canPlace || !market.is_tradeable}
            onClick={() => setShowConfirmation(true)}
            className={`w-full py-3 rounded-lg text-sm font-semibold transition-colors ${
              canPlace && market.is_tradeable
                ? 'bg-blue-600 hover:bg-blue-700 text-white'
                : 'bg-gray-100 text-gray-400 cursor-not-allowed'
            }`}
          >
            {!market.is_tradeable
              ? 'Market Not Tradeable'
              : !canPlace
              ? orderShares === 0
                ? 'Enter Shares'
                : cost > availableBalance
                ? 'Insufficient Balance'
                : 'Enter Valid Price'
              : `Place ${orderSide} Order · $${cost.toFixed(2)}`}
          </button>
        </div>
      </div>

      {showConfirmation && (
        <OrderConfirmation
          advisory={advisory}
          selectedTeam={selectedTeam}
          orderSide={orderSide}
          orderAmount={orderAmount}
          selectedPrice={orderPrice}
          selectedTokenId={selectedTokenId}
          sharesEstimate={orderShares}
          estPayout={estPayout}
          onClose={() => setShowConfirmation(false)}
        />
      )}
    </>
  )
}
