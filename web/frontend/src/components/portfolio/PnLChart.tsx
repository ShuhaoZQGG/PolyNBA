import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'

interface PnLDataPoint {
  time: string
  pnl: number
}

interface PnLChartProps {
  data: PnLDataPoint[]
  title?: string
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ value: number }>
  label?: string
}) {
  if (!active || !payload?.length) return null
  const val = payload[0]?.value ?? 0
  return (
    <div className="bg-white border border-[#E5E5E5] rounded-lg px-3 py-2 shadow-lg">
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`text-sm font-semibold tabular-nums ${val >= 0 ? 'text-green-600' : 'text-red-600'}`}>
        {val >= 0 ? '+' : ''}${val.toFixed(2)}
      </p>
    </div>
  )
}

export default function PnLChart({ data, title = 'P&L' }: PnLChartProps) {
  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-[#E5E5E5] bg-white p-5">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-4">{title}</p>
        <div className="h-32 flex items-center justify-center">
          <p className="text-sm text-gray-400">No data yet</p>
        </div>
      </div>
    )
  }

  const lastVal = data[data.length - 1]?.pnl ?? 0
  const isPositive = lastVal >= 0

  return (
    <div className="rounded-xl border border-[#E5E5E5] bg-white p-5">
      <div className="flex items-center justify-between mb-4">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">{title}</p>
        <p className={`text-sm font-semibold tabular-nums ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
          {lastVal >= 0 ? '+' : ''}${lastVal.toFixed(2)}
        </p>
      </div>
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={data} margin={{ top: 2, right: 2, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="5%"
                stopColor={isPositive ? '#16A34A' : '#DC2626'}
                stopOpacity={0.15}
              />
              <stop
                offset="95%"
                stopColor={isPositive ? '#16A34A' : '#DC2626'}
                stopOpacity={0}
              />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
          <XAxis
            dataKey="time"
            tick={{ fontSize: 10, fill: '#9CA3AF' }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#9CA3AF' }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `$${v}`}
            width={40}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="pnl"
            stroke={isPositive ? '#16A34A' : '#DC2626'}
            strokeWidth={2}
            fill="url(#pnlGradient)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
