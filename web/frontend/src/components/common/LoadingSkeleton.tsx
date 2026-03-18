interface LoadingSkeletonProps {
  className?: string
  count?: number
}

export function SkeletonLine({ className = '' }: { className?: string }) {
  return <div className={`skeleton h-4 rounded ${className}`} />
}

export function SkeletonCard({ className = '' }: { className?: string }) {
  return (
    <div className={`rounded-xl border border-[#E5E5E5] bg-white p-5 ${className}`}>
      <div className="flex items-center gap-3 mb-4">
        <div className="skeleton h-6 w-16 rounded-full" />
        <div className="skeleton h-4 w-8" />
        <div className="skeleton h-6 w-16 rounded-full" />
      </div>
      <div className="space-y-2">
        <SkeletonLine className="w-3/4" />
        <SkeletonLine className="w-1/2" />
      </div>
      <div className="flex gap-2 mt-4">
        <div className="skeleton h-6 w-20 rounded-full" />
        <div className="skeleton h-6 w-16 rounded-full" />
      </div>
    </div>
  )
}

export default function LoadingSkeleton({ className = '', count = 1 }: LoadingSkeletonProps) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} className={className} />
      ))}
    </>
  )
}
