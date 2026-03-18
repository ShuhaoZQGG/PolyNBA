import { type ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  onClick?: () => void
  hoverable?: boolean
}

export default function Card({ children, className = '', onClick, hoverable }: CardProps) {
  const hoverClass = hoverable ? 'hover:shadow-md hover:border-gray-300 cursor-pointer transition-all duration-150' : ''
  return (
    <div
      className={`rounded-xl border border-[#E5E5E5] bg-white shadow-sm p-5 ${hoverClass} ${className}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
    >
      {children}
    </div>
  )
}
