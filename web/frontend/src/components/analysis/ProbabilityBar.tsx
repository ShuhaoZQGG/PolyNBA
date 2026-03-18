interface ProbabilityBarProps {
  modelProb: number
  marketProb: number
  blendedProb: number
  homeAbbr: string
  awayAbbr: string
  betSide: string
}

interface ProbRowProps {
  label: string
  homeProb: number
  homeAbbr: string
  awayAbbr: string
  color: string
}

function ProbRow({ label, homeProb, homeAbbr, awayAbbr, color }: ProbRowProps) {
  const homePct = Math.round(homeProb * 100)
  const awayPct = 100 - homePct

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-gray-500">
        <span>{label}</span>
        <span className="tabular-nums">
          {homeAbbr} {homePct}% / {awayAbbr} {awayPct}%
        </span>
      </div>
      <div className="flex h-2.5 rounded-full overflow-hidden bg-gray-100">
        <div
          className="h-full transition-all duration-500"
          style={{ width: `${homePct}%`, backgroundColor: color }}
        />
        <div
          className="h-full flex-1"
          style={{ backgroundColor: `${color}33` }}
        />
      </div>
    </div>
  )
}

export default function ProbabilityBar({
  modelProb,
  marketProb,
  blendedProb,
  homeAbbr,
  awayAbbr,
  betSide,
}: ProbabilityBarProps) {
  // All probs (model, market, blended) are already expressed as home team win probability.
  // No flipping needed — bet_side only indicates which side to bet on.
  const homeModelProb = modelProb

  return (
    <div className="space-y-3">
      <ProbRow
        label="Model"
        homeProb={homeModelProb}
        homeAbbr={homeAbbr}
        awayAbbr={awayAbbr}
        color="#3b82f6"
      />
      <ProbRow
        label="Market"
        homeProb={marketProb}
        homeAbbr={homeAbbr}
        awayAbbr={awayAbbr}
        color="#8b5cf6"
      />
      <ProbRow
        label="Blended"
        homeProb={blendedProb}
        homeAbbr={homeAbbr}
        awayAbbr={awayAbbr}
        color="#10b981"
      />
    </div>
  )
}
