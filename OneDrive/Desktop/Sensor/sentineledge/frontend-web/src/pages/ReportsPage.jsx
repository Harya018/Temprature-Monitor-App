/**
 * src/pages/ReportsPage.jsx
 * Daily summary reports — last 30 days + raw readings export.
 */
import { useState, useEffect, useCallback } from 'react'
import { BarChart2, RefreshCw, ChevronDown, ChevronUp, Download } from 'lucide-react'
import { fetchDailyReports } from '../services/api.js'
import { SkeletonTable } from '../components/Skeleton'

function adminHeaders() {
  const token    = sessionStorage.getItem('admin_token') || ''
  const password = sessionStorage.getItem('adminPassword') || 'admin123'
  return {
    'X-Admin-Password': password,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export default function ReportsPage() {
  const [reports,    setReports]    = useState([])
  const [loading,    setLoading]    = useState(false)
  const [expanded,   setExpanded]   = useState(null)
  const [exportFrom, setExportFrom] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 7)
    return d.toISOString().slice(0, 10)
  })
  const [exportTo,   setExportTo]   = useState(() => new Date().toISOString().slice(0, 10))
  const [exporting,  setExporting]  = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try { setReports(await fetchDailyReports(30)) }
    catch { /* silent */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const downloadExport = useCallback(async (fmt) => {
    if (!exportFrom || !exportTo) return
    setExporting(true)
    try {
      const res = await fetch(
        `/api/reports/readings-export?from_date=${exportFrom}&to_date=${exportTo}&format=${fmt}`,
        { headers: adminHeaders() },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const a    = document.createElement('a')
      a.href     = URL.createObjectURL(blob)
      a.download = `readings_${exportFrom}_${exportTo}.${fmt}`
      a.click()
    } catch (e) {
      alert('Export failed: ' + e.message)
    } finally {
      setExporting(false)
    }
  }, [exportFrom, exportTo])

  function statusIcon(r) {
    if (r.error) return '❓'
    if (!r.total_readings) return '⚫'
    if (r.total_alerts === 0) return '✅'
    if (r.total_alerts <= 3) return '⚠️'
    return '🔴'
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart2 size={18} className="text-purple-600" />
          <h1 className="text-base font-bold text-gray-800">Daily Reports — Last 30 Days</h1>
        </div>
        <button onClick={load} disabled={loading} className="btn btn-ghost btn-sm">
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {/* Raw data export */}
      <div className="card px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-700">
            <Download size={15} className="text-purple-600" />
            Export Raw Readings
          </div>
          <input type="date" value={exportFrom} onChange={e => setExportFrom(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-xs" />
          <span className="text-xs text-gray-400">to</span>
          <input type="date" value={exportTo} onChange={e => setExportTo(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-xs" />
          <button onClick={() => downloadExport('csv')} disabled={exporting}
            className="btn btn-sm btn-ghost text-xs border border-gray-200">
            {exporting ? 'Exporting…' : '↓ CSV'}
          </button>
          <button onClick={() => downloadExport('json')} disabled={exporting}
            className="btn btn-sm btn-ghost text-xs border border-gray-200">
            {exporting ? '…' : '↓ JSON'}
          </button>
          <span className="text-xs text-gray-400">All sensor readings including custom parameters</span>
        </div>
      </div>

      {loading && reports.length === 0 ? (
        <div className="card overflow-hidden"><SkeletonTable rows={5} /></div>
      ) : (
        <div className="space-y-2">
          {reports.map(r => (
            <div key={r.date} className="card overflow-hidden">
              <button
                className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-gray-50 transition-colors"
                onClick={() => setExpanded(expanded === r.date ? null : r.date)}
              >
                <span className="text-xl w-8 flex-shrink-0">{statusIcon(r)}</span>

                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-gray-800">{r.date}</p>
                  {r.error ? (
                    <p className="text-xs text-red-500">Error: {r.error}</p>
                  ) : (
                    <p className="text-xs text-gray-500">
                      {r.total_readings} readings · {r.total_alerts} alerts
                      {r.avg_temp != null ? ` · Avg ${r.avg_temp}°C` : ''}
                    </p>
                  )}
                </div>

                {!r.error && (
                  <div className="hidden md:flex items-center gap-6 text-xs text-gray-600 mr-4">
                    {r.peak_temp != null && (
                      <div className="text-center">
                        <p className="font-bold text-orange-600">{r.peak_temp.toFixed(1)}°C</p>
                        <p className="text-gray-400">Peak</p>
                      </div>
                    )}
                    <div className="text-center">
                      <p className="font-bold text-emerald-600">{r.email_sent ?? 0}</p>
                      <p className="text-gray-400">Email sent</p>
                    </div>
                    <div className="text-center">
                      <p className="font-bold text-blue-600">{r.sms_sent ?? 0}</p>
                      <p className="text-gray-400">SMS sent</p>
                    </div>
                  </div>
                )}

                {expanded === r.date ? <ChevronUp size={16} className="text-gray-400 flex-shrink-0" /> : <ChevronDown size={16} className="text-gray-400 flex-shrink-0" />}
              </button>

              {expanded === r.date && !r.error && (
                <div className="border-t border-gray-100 px-5 py-4 bg-gray-50">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {[
                      { label: 'Total Readings',  value: r.total_readings ?? '—' },
                      { label: 'Total Alerts',    value: r.total_alerts ?? '—', color: r.total_alerts > 0 ? '#EF4444' : '#10B981' },
                      { label: 'Average Temp',    value: r.avg_temp != null ? `${r.avg_temp}°C` : '—' },
                      { label: 'Peak Temp',       value: r.peak_temp != null ? `${r.peak_temp.toFixed(1)}°C` : '—', color: '#F97316' },
                      { label: 'Min Temp',        value: r.min_temp != null ? `${r.min_temp.toFixed(1)}°C` : '—', color: '#3B82F6' },
                      { label: 'Email Sent',      value: r.email_sent ?? 0, color: '#10B981' },
                      { label: 'Email Failed',    value: r.email_failed ?? 0, color: r.email_failed > 0 ? '#EF4444' : undefined },
                      { label: 'SMS Sent',        value: r.sms_sent ?? 0, color: '#3B82F6' },
                    ].map(s => (
                      <div key={s.label} className="bg-white rounded-lg px-3 py-2">
                        <p className="text-sm font-bold" style={{ color: s.color || '#1F2937' }}>{s.value}</p>
                        <p className="text-xs text-gray-500">{s.label}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
