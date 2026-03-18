import Card from '../common/Card'

interface PositionsListProps {
  positions: Record<string, number>
}

export default function PositionsList({ positions }: PositionsListProps) {
  const entries = Object.entries(positions).filter(([, size]) => size > 0)

  return (
    <Card>
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
        Open Positions
      </p>
      {entries.length === 0 ? (
        <p className="text-sm text-gray-400">No open positions</p>
      ) : (
        <ul className="space-y-2">
          {entries.map(([tokenId, size]) => (
            <li key={tokenId} className="flex items-center justify-between">
              <span className="text-xs text-gray-500 font-mono truncate max-w-[120px]">
                {tokenId.slice(0, 12)}…
              </span>
              <span className="text-sm font-semibold tabular-nums text-gray-800">
                {size.toFixed(2)} shares
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
