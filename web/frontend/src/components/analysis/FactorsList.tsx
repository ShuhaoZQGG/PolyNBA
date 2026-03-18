interface FactorsListProps {
  factorsFor: string[]
  factorsAgainst: string[]
  betSide: string
}

export default function FactorsList({ factorsFor, factorsAgainst, betSide }: FactorsListProps) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {/* Factors for */}
      <div>
        <h4 className="text-xs font-semibold text-green-700 uppercase tracking-wide mb-2">
          Factors For ({betSide})
        </h4>
        <ul className="space-y-1.5">
          {factorsFor.length === 0 ? (
            <li className="text-xs text-gray-400">None identified</li>
          ) : (
            factorsFor.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-gray-700">
                <span className="text-green-500 mt-0.5 shrink-0">✓</span>
                <span>{f}</span>
              </li>
            ))
          )}
        </ul>
      </div>

      {/* Factors against */}
      <div>
        <h4 className="text-xs font-semibold text-red-600 uppercase tracking-wide mb-2">
          Factors Against
        </h4>
        <ul className="space-y-1.5">
          {factorsAgainst.length === 0 ? (
            <li className="text-xs text-gray-400">None identified</li>
          ) : (
            factorsAgainst.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-gray-700">
                <span className="text-red-400 mt-0.5 shrink-0">✗</span>
                <span>{f}</span>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  )
}
