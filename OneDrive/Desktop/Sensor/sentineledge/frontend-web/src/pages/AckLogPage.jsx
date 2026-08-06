/**
 * src/pages/AckLogPage.jsx
 * Acknowledgement Log — shows who acknowledged each alert, when, and
 * how many seconds elapsed between the alert firing and acknowledgement.
 * Updates in real time via WebSocket when a new acknowledgement arrives.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, CheckCircle2, Clock, User } from 'lucide-react'
import { fetchAckLog } from '../services/api.js'
import { SkeletonTable } from '../components/Skeleton'
import ErrorState from '../components/ErrorState'

// ── Time helpers ──────────────────────────────────────────────────────────────
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000

function toIST(utcStr) {
  if (!utcStr) return '—'
  try {
    const d = new Date(utcStr)
    const ist = new Date(d.getTime() + IST_OFFSET_MS)
    const dd   = String(ist.getUTCDate()).padStart(2, '0')
    const mo   = ist.toLocaleString('en', { month: 'short', timeZone: 'UTC' })
    const yyyy = ist.getUTCFullYear()
    let h = ist.getUTCHours()
    const mm  = String(ist.getUTCMinutes()).padStart(2, '0')
    const ss  = String(ist.getUTCSeconds()).padStart(2, '0')
    const ampm = h >= 12 ? 'PM' : 'AM'
    h = h % 12 || 12
    return `${dd} ${mo} ${yyyy}, ${String(h).padStart(2,'0')}:${mm}:${ss} ${ampm}`
  } catch {
    return utcStr
  }
}

function timeAgo(utcStr) {
  if (!utcStr) return '—'
  try {
    const diff = Math.floor((Date.now() - new Date(utcStr).getTime()) / 1000)
    if (diff < 60)   return `${diff}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    return `${Math.floor(diff / 3600)}h ago`
  } catch {
    return '—'
  }
}

function fmtResponseTime(secs) {
  if (secs == null) return '—'
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function AckLogPage({ wsData }) {
  const [rows,       setRows]       = useState([])
  const [loading,    setLoading]    = useState(true)
  const [fetchError, setFetchError] = useState(null)
  const [lastUpdate, setLastUpdate] = useState(null)
  const rowsRef = useRef(rows)
  rowsRef.current = rows

  const load = useCallback(async () => {
    setFetchError(null)
    try {
      const data = await fetchAckLog(200)
      setRows(data)
      setLastUpdate(new Date())
    } catch (err) {
      console.warn('[AckLog] fetch failed:', err)
      setFetchError(err?.message || 'Could not load acknowledgement log')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Real-time WebSocket update — listen for acknowledgement events
  useEffect(() => {
    const last = wsData?.lastReading
    if (!last || last.type !== 'acknowledgement') return
    // A new ack arrived — refresh the list
    load()
  }, [wsData?.lastReading, load])

  const severityColor = (dir) =>
    dir === 'high' ? '#ef4444' : '#f59e0b'

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Acknowledgement Log</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Who acknowledged each alert and how quickly — updated in real time
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdate && (
            <span className="text-xs text-gray-400">
              Updated {timeAgo(lastUpdate.toISOString())}
            </span>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs font-semibold text-purple-600 hover:text-purple-700 border border-purple-200 rounded-lg px-3 py-1.5 hover:bg-purple-50 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Total Acknowledged',  value: rows.length,     icon: CheckCircle2, color: '#10b981' },
          { label: 'Avg Response Time',   value: (() => {
              const valid = rows.filter(r => r.response_time_seconds != null)
              if (!valid.length) return '—'
              const avg = Math.round(valid.reduce((s, r) => s + r.response_time_seconds, 0) / valid.length)
              return fmtResponseTime(avg)
            })(),                                                  icon: Clock,        color: '#7c3aed' },
          { label: 'Fastest Response',    value: (() => {
              const valid = rows.filter(r => r.response_time_seconds != null)
              if (!valid.length) return '—'
              return fmtResponseTime(Math.min(...valid.map(r => r.response_time_seconds)))
            })(),                                                  icon: User,         color: '#0ea5e9' },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="card p-4 flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
                 style={{ background: color + '15' }}>
              <Icon size={18} style={{ color }} />
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium">{label}</p>
              <p className="text-xl font-bold text-gray-900">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-800">All Acknowledgements</h3>
        </div>

        {fetchError && !loading ? (
          <ErrorState message={fetchError} onRetry={load} />
        ) : loading ? (
          <SkeletonTable />
        ) : rows.length === 0 ? (
          <div className="p-12 text-center">
            <CheckCircle2 size={40} className="mx-auto mb-3 text-gray-200" />
            <p className="text-sm font-medium text-gray-500">No acknowledgements yet</p>
            <p className="text-xs text-gray-400 mt-1">Alerts acknowledged from the mobile app or dashboard will appear here</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  {['Alert', 'Temperature', 'Alert Time', 'Acknowledged By', 'Ack Time', 'Response Time'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((row) => (
                  <tr key={row.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className="w-2 h-2 rounded-full flex-shrink-0"
                          style={{ background: severityColor(row.direction) }}
                        />
                        <span className="text-xs font-mono text-gray-500">#{row.id}</span>
                        <span className="text-xs font-medium text-gray-700 capitalize">
                          {row.direction === 'high' ? '↑ High' : '↓ Low'}
                        </span>
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-bold" style={{ color: severityColor(row.direction) }}>
                        {Number(row.value).toFixed(1)}°C
                      </span>
                      <span className="text-xs text-gray-400 ml-1">/ {row.threshold}°C</span>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-xs text-gray-700">{toIST(row.timestamp)}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1.5">
                        <div className="w-6 h-6 rounded-full bg-purple-100 flex items-center justify-center flex-shrink-0">
                          <span className="text-xs font-bold text-purple-700">
                            {(row.acknowledged_by || '?')[0].toUpperCase()}
                          </span>
                        </div>
                        <span className="font-medium text-gray-800">{row.acknowledged_by || '—'}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-xs text-gray-700">{toIST(row.acknowledged_at)}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-bold"
                        style={
                          row.response_time_seconds == null
                            ? { background: '#f3f4f6', color: '#9ca3af' }
                            : row.response_time_seconds <= 30
                            ? { background: '#ecfdf5', color: '#059669' }
                            : row.response_time_seconds <= 120
                            ? { background: '#fffbeb', color: '#d97706' }
                            : { background: '#fef2f2', color: '#dc2626' }
                        }
                      >
                        <Clock size={10} />
                        {fmtResponseTime(row.response_time_seconds)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
