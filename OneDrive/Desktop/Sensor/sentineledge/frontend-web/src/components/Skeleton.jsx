import './Skeleton.css'

export function SkeletonTable({ rows = 6 }) {
  return (
    <div className="skeleton-table-wrapper">
      {Array.from({ length: rows }).map((_, ri) => (
        <div key={ri} className="skeleton-row">
          <div className="skeleton-cell animate-shimmer" style={{ flex: 1 }} />
          <div className="skeleton-cell animate-shimmer" style={{ flex: 2 }} />
          <div className="skeleton-cell animate-shimmer" style={{ flex: 1.5 }} />
          <div className="skeleton-cell animate-shimmer" style={{ flex: 2 }} />
          <div className="skeleton-cell animate-shimmer" style={{ flex: 1 }} />
        </div>
      ))}
    </div>
  )
}

export function SkeletonCard({ rows = 2 }) {
  return (
    <div className="card" style={{ padding: '1.25rem' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ marginBottom: '0.75rem' }}>
          <div
            className="skeleton-base animate-shimmer"
            style={{ height: '1rem', width: '40%', marginBottom: '0.4rem', borderRadius: '0.25rem' }}
          />
          <div
            className="skeleton-base animate-shimmer"
            style={{ height: '0.75rem', width: '65%', borderRadius: '0.25rem' }}
          />
        </div>
      ))}
    </div>
  )
}

export function SkeletonChart({ bars = 8 }) {
  const heights = [60, 80, 45, 90, 70, 55, 85, 65].slice(0, bars)
  return (
    <div className="card" style={{ padding: '1rem' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: '0.5rem', height: 120 }}>
        {heights.map((h, i) => (
          <div
            key={i}
            className="skeleton-base animate-shimmer"
            style={{ flex: 1, height: `${h}%`, borderRadius: '0.25rem 0.25rem 0 0' }}
          />
        ))}
      </div>
    </div>
  )
}

export function SkeletonText({ width = '100%', height = '0.875rem' }) {
  return (
    <div
      className="skeleton-base animate-shimmer"
      style={{ width, height, borderRadius: '0.25rem' }}
    />
  )
}

export default function Skeleton({ width = '100%', height = '1rem', className = '' }) {
  return (
    <div
      className={`skeleton-base animate-shimmer ${className}`}
      style={{ width, height }}
    />
  )
}
