import type { PortfolioResponse } from '../../api/types'
import Card from '../common/Card'

interface BalanceCardProps {
  portfolio: PortfolioResponse
}

function fmt(n: number) {
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function BalanceCard({ portfolio }: BalanceCardProps) {
  const { balance, is_live_mode } = portfolio

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Portfolio</p>
        <span
          className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
            is_live_mode
              ? 'bg-green-100 text-green-700'
              : 'bg-amber-100 text-amber-700'
          }`}
        >
          {is_live_mode ? 'Live' : 'Paper'}
        </span>
      </div>
      <p className="text-2xl font-semibold tabular-nums text-gray-900 mb-3">
        {fmt(balance.usdc)}
      </p>
      <div className="flex gap-4">
        <div>
          <p className="text-xs text-gray-400">Available</p>
          <p className="text-sm font-semibold tabular-nums text-gray-700">
            {fmt(balance.available_usdc)}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-400">Locked</p>
          <p className="text-sm font-semibold tabular-nums text-gray-500">
            {fmt(balance.locked_usdc)}
          </p>
        </div>
      </div>
    </Card>
  )
}
