import Card from './Card'

interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  trend?: 'up' | 'down' | 'neutral'
  accent?: boolean
}

export default function StatCard({ label, value, sub, trend, accent }: StatCardProps) {
  const trendColor =
    trend === 'up' ? 'text-[#16A34A]' : trend === 'down' ? 'text-[#DC2626]' : 'text-gray-500'

  return (
    <Card className={accent ? 'border-blue-200 bg-blue-50' : ''}>
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-semibold tabular-nums ${trendColor}`}>
        {value}
      </p>
      {sub && (
        <p className="text-xs text-gray-400 mt-0.5">{sub}</p>
      )}
    </Card>
  )
}
