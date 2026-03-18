import type { GameMarketSummary } from '../../api/types'
import GameCard from './GameCard'
import LoadingSkeleton from '../common/LoadingSkeleton'

interface GameGridProps {
  summaries: GameMarketSummary[]
  isLoading: boolean
  error: Error | null
  /** True when market/price data is still loading (games already shown) */
  pricesLoading?: boolean
}

export default function GameGrid({ summaries, isLoading, error, pricesLoading }: GameGridProps) {
  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-red-600 font-medium text-sm">Failed to load games</p>
        <p className="text-red-400 text-xs mt-1">{error.message}</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <LoadingSkeleton count={6} />
      </div>
    )
  }

  if (summaries.length === 0) {
    return (
      <div className="rounded-xl border border-[#E5E5E5] bg-white p-12 text-center">
        <p className="text-gray-500 font-medium">No games found for today</p>
        <p className="text-gray-400 text-xs mt-1">
          Check back later or try a different date
        </p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {summaries.map((s) => (
        <GameCard key={s.game.game_id} summary={s} pricesLoading={pricesLoading} />
      ))}
    </div>
  )
}
