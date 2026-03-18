interface VerdictBadgeProps {
  verdict: string
  size?: 'sm' | 'md'
}

function getVerdictStyle(verdict: string): { bg: string; text: string } {
  const v = verdict.toUpperCase()
  if (v.includes('BET')) return { bg: 'bg-green-100', text: 'text-green-700' }
  if (v.includes('SPECULATE')) return { bg: 'bg-amber-100', text: 'text-amber-700' }
  if (v.includes('HOLD')) return { bg: 'bg-gray-100', text: 'text-gray-600' }
  if (v.includes('AVOID') || v.includes('PASS')) return { bg: 'bg-red-100', text: 'text-red-600' }
  return { bg: 'bg-gray-100', text: 'text-gray-600' }
}

export default function VerdictBadge({ verdict, size = 'md' }: VerdictBadgeProps) {
  const { bg, text } = getVerdictStyle(verdict)
  const sizeClass = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'
  return (
    <span className={`inline-flex items-center rounded-full font-semibold ${bg} ${text} ${sizeClass}`}>
      {verdict}
    </span>
  )
}
