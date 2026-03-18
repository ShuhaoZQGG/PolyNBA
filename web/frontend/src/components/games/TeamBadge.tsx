import { getTeamColor } from '../../constants/teams'

interface TeamBadgeProps {
  abbr: string
  size?: 'sm' | 'md' | 'lg'
}

const sizeClasses = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-xs',
  lg: 'px-3 py-1.5 text-sm',
}

export default function TeamBadge({ abbr, size = 'md' }: TeamBadgeProps) {
  const color = getTeamColor(abbr)
  return (
    <span
      className={`inline-flex items-center rounded-full font-semibold text-white ${sizeClasses[size]}`}
      style={{ backgroundColor: color }}
    >
      {abbr.toUpperCase()}
    </span>
  )
}
