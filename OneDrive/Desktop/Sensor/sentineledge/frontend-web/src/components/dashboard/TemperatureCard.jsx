/**
 * src/components/dashboard/TemperatureCard.jsx
 * Hero stat card — current temperature + severity status.
 * All props are fully optional/null-safe.
 */
import { Thermometer, AlertTriangle, Clock } from 'lucide-react'
import { utcToIST } from '../../utils/time.js'
import { getSeverityColor, getSeverityLabel, getTempColor, getTempBorderClass } from '../../utils/severity.js'
import Badge from '../shared/Badge.jsx'

function formatXlsTs(ts) {
  // ts from XLS has no timezone suffix → it's already IST from Pro-Server EX
  // ts from server has +00:00 or Z → needs UTC→IST conversion
  if (!ts) return null
  const hasZone = ts.includes('Z') || /[+-]\d{2}:\d{2}$/.test(ts)
  try {
    const d = hasZone ? new Date(ts) : new Date(ts + '+05:30')
    if (isNaN(d)) return ts
    return d.toLocaleString('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: true, timeZone: 'Asia/Kolkata',
    })
  } catch { return ts }
}

function relativeTime(ts) {
  if (!ts) return null
  try {
    const hasZone = ts.includes('Z') || /[+-]\d{2}:\d{2}$/.test(ts)
    const d = hasZone ? new Date(ts) : new Date(ts + '+05:30')
    if (isNaN(d)) return null
    const diffMs = Date.now() - d.getTime()
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1)  return { label: 'Just now',           stale: false }
    if (diffMin < 60) return { label: `${diffMin} min ago`, stale: diffMin > 5 }
    const diffH = Math.floor(diffMin / 60)
    if (diffH < 24)   return { label: `${diffH} hr ago`,    stale: true }
    return { label: `${Math.floor(diffH / 24)} day(s) ago`, stale: true }
  } catch { return null }
}

function severity2badge(s) {
  const m = { NORMAL:'green', WARNING:'amber', CRITICAL:'orange', EMERGENCY:'red' }
  return m[String(s ?? '').toUpperCase()] || 'green'
}

export default function TemperatureCard({ reading, thresholds }) {
  // All properties safely extracted with defaults
  const temp      = reading?.temperature ?? null
  const ts        = reading?.timestamp   ?? null
  const breaches  = Array.isArray(reading?.breaches) ? reading.breaches : []
  const hasBreach = breaches.length > 0
  const topBreach = breaches[0] ?? null
  const sev       = topBreach?.severity || (hasBreach ? 'WARNING' : 'NORMAL')
  const sevUp     = String(sev).toUpperCase()
  const tempColor = hasBreach ? getTempColor(sev) : '#1F2937'

  const high = thresholds?.temperature?.high ?? 90
  const low  = thresholds?.temperature?.low  ?? 38

  const borderClass = hasBreach ? getTempBorderClass(sev) : ''
  const isEmergency = sevUp === 'EMERGENCY'

  // Truncate to 3 decimals without rounding (e.g. 20.08000183 → "20.080")
  const trunc3 = v => { const n = Number(v); return isNaN(n) ? '—' : (Math.trunc(n * 1000) / 1000).toFixed(3) }
  const displayTemp = typeof temp === 'number' ? trunc3(temp) : '—'
  const rel = ts ? relativeTime(ts) : null

  return (
    <div
      className={`card p-5 flex flex-col gap-3 ${borderClass} transition-all duration-500
        ${isEmergency ? 'animate-flash-red' : ''}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Thermometer size={18} className="text-purple-500" />
          <span className="text-sm font-semibold text-gray-700">Temperature</span>
        </div>
        <Badge
          color={severity2badge(sev)}
          label={hasBreach ? getSeverityLabel(sev) : 'NORMAL'}
          pulse={isEmergency}
        />
      </div>

      {/* Big number */}
      <div className="flex items-end gap-2">
        <span
          className="temp-value animate-pulse-num"
          style={{ color: tempColor }}
        >
          {displayTemp}
        </span>
        <span className="text-2xl font-semibold text-gray-400 mb-2">°C</span>
      </div>

      {/* XLS timestamp below temperature */}
      {ts && (
        <div className="flex items-center gap-1.5 -mt-1">
          <Clock size={11} style={{ color: rel?.stale ? '#F59E0B' : '#6B7280', flexShrink: 0 }} />
          <span style={{
            fontSize: 11,
            color: rel?.stale ? '#B45309' : '#6B7280',
            fontWeight: rel?.stale ? 600 : 400,
          }}>
            {formatXlsTs(ts)}
          </span>
          {rel && (
            <span style={{
              fontSize: 10,
              color: rel.stale ? '#D97706' : '#9CA3AF',
              background: rel.stale ? '#FEF3C7' : '#F3F4F6',
              borderRadius: 4,
              padding: '1px 5px',
              fontWeight: 500,
            }}>
              {rel.label}
            </span>
          )}
        </div>
      )}

      {/* Breach banner */}
      {hasBreach && topBreach && (
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-lg"
          style={{ background: getSeverityColor(sev)?.bg ?? '#FEF2F2' }}
        >
          <AlertTriangle size={14} style={{ color: getSeverityColor(sev)?.dot ?? '#EF4444', flexShrink: 0 }} />
          <span className="text-xs font-semibold" style={{ color: getSeverityColor(sev)?.text ?? '#991B1B' }}>
            BREACH ACTIVE — {getSeverityLabel(sev)} ·{' '}
            {topBreach.direction === 'high' ? 'Above' : 'Below'} threshold
          </span>
        </div>
      )}

      {/* Loading state when no data yet */}
      {!reading && (
        <div className="text-xs text-gray-400 text-center py-1">Connecting to sensor…</div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between mt-auto pt-1 border-t border-gray-100">
        <span className="text-xs text-gray-400">Normal: {low}°C – {high}°C</span>
        <span className="text-xs text-gray-400">{ts ? utcToIST(ts) : 'No data yet'}</span>
      </div>
    </div>
  )
}
