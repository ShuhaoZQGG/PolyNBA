import type { PregameAIAnalysis } from '../../api/types'
import FactorsList from './FactorsList'

interface AnalysisPanelProps {
  analysis: PregameAIAnalysis
  betSide: string
}

const severityColor = {
  critical: 'text-red-600 bg-red-50 border-red-200',
  significant: 'text-amber-600 bg-amber-50 border-amber-200',
  minor: 'text-yellow-600 bg-yellow-50 border-yellow-200',
  none: 'text-gray-500 bg-gray-50 border-gray-200',
}

const upsetRiskLabel = {
  very_low: 'Very Low',
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
}

const upsetRiskColor = {
  very_low: 'text-green-600',
  low: 'text-green-500',
  moderate: 'text-amber-600',
  high: 'text-red-600',
}

const marketEfficiencyLabel = {
  inefficient: 'Inefficient',
  fair: 'Fair',
  efficient: 'Efficient',
}

const marketEfficiencyColor = {
  inefficient: 'text-green-600',
  fair: 'text-amber-600',
  efficient: 'text-gray-500',
}

const advantageIcon = {
  home: '→',
  away: '←',
  even: '=',
}

const advantageColor = {
  home: 'text-blue-600',
  away: 'text-purple-600',
  even: 'text-gray-400',
}

export default function AnalysisPanel({ analysis, betSide }: AnalysisPanelProps) {
  const confidencePct = (analysis.confidence_rating / 10) * 100

  return (
    <div className="space-y-6">
      {/* Headline */}
      <div>
        <h3 className="text-base font-semibold text-gray-900 leading-snug">
          {analysis.headline}
        </h3>
      </div>

      {/* Narrative */}
      <div>
        <p className="text-sm text-gray-600 leading-relaxed">{analysis.narrative}</p>
      </div>

      {/* Verdict rationale */}
      <div className="rounded-lg bg-gray-50 border border-[#E5E5E5] px-4 py-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
          Verdict Rationale
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">{analysis.verdict_rationale}</p>
      </div>

      {/* Confidence + meta */}
      <div className="grid grid-cols-3 gap-4">
        <div>
          <p className="text-xs text-gray-400 mb-1">Confidence</p>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${confidencePct}%` }}
              />
            </div>
            <span className="text-xs font-semibold tabular-nums text-gray-700">
              {analysis.confidence_rating}/10
            </span>
          </div>
        </div>
        <div>
          <p className="text-xs text-gray-400 mb-1">Market</p>
          <p className={`text-xs font-semibold ${marketEfficiencyColor[analysis.market_efficiency]}`}>
            {marketEfficiencyLabel[analysis.market_efficiency]}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-400 mb-1">Upset Risk</p>
          <p className={`text-xs font-semibold ${upsetRiskColor[analysis.upset_risk]}`}>
            {upsetRiskLabel[analysis.upset_risk]}
          </p>
        </div>
      </div>

      {/* Factors */}
      <FactorsList
        factorsFor={analysis.key_factors_for}
        factorsAgainst={analysis.key_factors_against}
        betSide={betSide}
      />

      {/* Matchup insights */}
      {analysis.matchup_insights.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Matchup Insights
          </h4>
          <div className="space-y-2">
            {analysis.matchup_insights.map((insight, i) => (
              <div
                key={i}
                className="flex items-start gap-3 text-sm border-b border-gray-50 pb-2 last:border-0"
              >
                <span
                  className={`text-base font-bold shrink-0 w-5 text-center ${advantageColor[insight.advantage]}`}
                >
                  {advantageIcon[insight.advantage]}
                </span>
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-gray-800 text-xs">{insight.category}</span>
                  <p className="text-xs text-gray-500 mt-0.5">{insight.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Injury impact */}
      {analysis.injury_impact.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Injury Impact
          </h4>
          <div className="space-y-2">
            {analysis.injury_impact.map((inj, i) => (
              <div
                key={i}
                className={`rounded-lg border px-3 py-2 text-xs ${severityColor[inj.severity]}`}
              >
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="font-semibold uppercase">{inj.team}</span>
                  <span className="capitalize font-medium opacity-80">{inj.severity}</span>
                </div>
                <p className="opacity-90">{inj.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Game script */}
      {analysis.game_script && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Game Script
          </h4>
          <p className="text-sm text-gray-600 leading-relaxed italic">{analysis.game_script}</p>
        </div>
      )}
    </div>
  )
}
