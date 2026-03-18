import { NavLink } from 'react-router-dom'
import { usePortfolio } from '../../api/hooks'

function formatUSDC(val: number) {
  return `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function TopBar() {
  const { data: portfolio } = usePortfolio()

  return (
    <header className="sticky top-0 z-50 bg-white border-b border-[#E5E5E5] h-14 flex items-center px-4 md:px-6 gap-6">
      {/* Logo */}
      <NavLink to="/markets" className="flex items-center gap-2 shrink-0">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-600 to-blue-800 flex items-center justify-center">
          <span className="text-white text-xs font-bold">P</span>
        </div>
        <span className="font-semibold text-gray-900 text-sm tracking-tight">PolyNBA</span>
      </NavLink>

      {/* Nav */}
      <nav className="flex items-center gap-1 flex-1">
        <NavLink
          to="/markets"
          className={({ isActive }) =>
            `px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              isActive
                ? 'bg-gray-100 text-gray-900'
                : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'
            }`
          }
        >
          Markets
        </NavLink>
        <NavLink
          to="/activity"
          className={({ isActive }) =>
            `px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              isActive
                ? 'bg-gray-100 text-gray-900'
                : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'
            }`
          }
        >
          Activity
        </NavLink>
      </nav>

      {/* Portfolio balance */}
      <div className="flex items-center gap-3 shrink-0">
        {portfolio ? (
          <>
            <div className="text-right hidden sm:block">
              <p className="text-xs text-gray-400">Balance</p>
              <p className="text-sm font-semibold tabular-nums text-gray-900">
                {formatUSDC(portfolio.balance.usdc)}
              </p>
            </div>
            {portfolio.is_live_mode ? (
              <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs font-semibold rounded-full">
                LIVE
              </span>
            ) : (
              <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs font-semibold rounded-full">
                PAPER
              </span>
            )}
          </>
        ) : (
          <div className="skeleton h-8 w-24 rounded" />
        )}
      </div>
    </header>
  )
}
