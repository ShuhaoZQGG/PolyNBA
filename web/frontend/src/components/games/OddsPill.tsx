interface OddsPillProps {
  price: number
  label?: string
  highlight?: boolean
}

export default function OddsPill({ price, label, highlight }: OddsPillProps) {
  const cents = Math.round(price * 100)
  return (
    <span
      className={`inline-flex items-center gap-1 font-mono text-sm font-medium ${
        highlight ? 'text-blue-600' : 'text-gray-700'
      }`}
    >
      {label && <span className="text-gray-500 font-sans text-xs">{label}</span>}
      {cents}&#162;
    </span>
  )
}
