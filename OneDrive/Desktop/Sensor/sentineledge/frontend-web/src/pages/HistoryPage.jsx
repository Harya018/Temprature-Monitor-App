/**
 * src/pages/HistoryPage.jsx
 * Backup list, historical data explorer, CSV export.
 */
import { fmtAlertNumber } from '../utils/alertFormat.js'
import { useState, useCallback } from 'react'
import { Archive, Download, Plus, Calendar, RefreshCw } from 'lucide-react'
import {
  createBackup, fetchHistoryStats, fetchHistoryAlerts,
  exportAlertsCsv, exportReadingsCsv,
} from '../services/api.js'
import { utcToIST, timeAgo } from '../utils/time.js'
import { useToast, ToastContainer } from '../components/shared/Toast.jsx'
import Badge from '../components/shared/Badge.jsx'

const today = () => new Date().toISOString().slice(0, 10)

export default function HistoryPage() {
  const { toasts, addToast, dismiss } = useToast()
  const [selectedDate, setSelectedDate] = useState(today())
  const [statsDate,    setStatsDate]    = useState(null)
  const [dayAlerts,    setDayAlerts]    = useState([])
  const [loading,      setLoading]      = useState(false)
  const [backingUp,    setBackingUp]    = useState(false)
  const [exportStart,  setExportStart]  = useState(today())
  const [exportEnd,    setExportEnd]    = useState(today())

  const handleExplore = useCallback(async () => {
    setLoading(true)
    try {
      const [stats, alerts] = await Promise.all([
        fetchHistoryStats(selectedDate),
        fetchHistoryAlerts(selectedDate),
      ])
      setStatsDate({ ...stats, date: selectedDate })
      setDayAlerts(alerts)
    } catch (e) {
      addToast({ type: 'error', message: 'Failed: ' + e.message })
    } finally { setLoading(false) }
  }, [selectedDate, addToast])

  const handleBackup = async () => {
    setBackingUp(true)
    try {
      const r = await createBackup()
      addToast({ type: 'success', message: `✅ Backup created: ${r.filename}` })
    } catch (e) { addToast({ type: 'error', message: 'Backup failed: ' + e.message }) }
    finally { setBackingUp(false) }
  }

  const handleExport = async (type) => {
    try {
      const blob = type === 'alerts'
        ? await exportAlertsCsv(exportStart, exportEnd)
        : await exportReadingsCsv(exportStart, exportEnd)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${type}_${exportStart}_${exportEnd}.csv`
      a.click()
    } catch (e) { addToast({ type: 'error', message: 'Export failed: ' + e.message }) }
  }

  const SEV_COLOR = { WARNING:'amber', CRITICAL:'orange', EMERGENCY:'red' }

  return (
    <>
      <div className="space-y-6">
        {/* Section 1 — Backup Actions */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Archive size={18} className="text-purple-600" />
              <h2 className="text-sm font-bold text-gray-800">Database Backups</h2>
            </div>
            <button onClick={handleBackup} disabled={backingUp} className="btn btn-primary btn-sm">
              <Plus size={13} /> {backingUp ? 'Creating…' : 'Create Backup Now'}
            </button>
          </div>
          <p className="text-xs text-gray-500">
            Automatic backups run daily at midnight UTC. Manual backups can be created any time.
            All data is persisted to SQLite — history survives server restarts and shutdowns.
          </p>
        </div>

        {/* Section 2 — Historical Data Explorer */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Calendar size={18} className="text-purple-600" />
            <h2 className="text-sm font-bold text-gray-800">Historical Data Explorer</h2>
          </div>

          <div className="flex items-end gap-3 mb-5">
            <div className="flex-1">
              <label className="text-xs text-gray-500 mb-1 block font-medium">Select Date</label>
              <input
                type="date"
                className="form-input"
                value={selectedDate}
                max={today()}
                onChange={e => setSelectedDate(e.target.value)}
              />
            </div>
            <button onClick={handleExplore} disabled={loading} className="btn btn-primary">
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
              {loading ? 'Loading…' : 'View Data'}
            </button>
          </div>

          {statsDate && (
            <div className="space-y-4">
              {/* Day stats */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                {[
                  { label: 'Total Readings', value: statsDate.total_readings },
                  { label: 'Total Alerts',   value: statsDate.total_alerts, color: statsDate.total_alerts > 0 ? '#EF4444' : '#10B981' },
                  { label: 'Avg Temp',       value: statsDate.avg_temp != null ? `${statsDate.avg_temp}°C` : '—' },
                  { label: 'Peak Temp',      value: statsDate.peak_temp != null ? `${statsDate.peak_temp.toFixed(1)}°C` : '—', color: '#F97316' },
                  { label: 'Min Temp',       value: statsDate.min_temp != null ? `${statsDate.min_temp.toFixed(1)}°C` : '—', color: '#3B82F6' },
                ].map(s => (
                  <div key={s.label} className="rounded-xl bg-gray-50 p-3 text-center">
                    <p className="text-xl font-bold" style={{ color: s.color || '#7C3AED' }}>{s.value ?? '—'}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
                  </div>
                ))}
              </div>

              {/* Delivery breakdown */}
              <div className="grid grid-cols-2 gap-3">
                {['email','sms'].map(ch => (
                  <div key={ch} className="rounded-xl border border-gray-100 p-3">
                    <p className="text-xs font-bold text-gray-700 uppercase mb-2">{ch} Delivery</p>
                    <div className="flex gap-4 text-xs">
                      <span className="text-emerald-600 font-semibold">✅ {statsDate.delivery?.[ch]?.sent ?? 0} sent</span>
                      <span className="text-red-500 font-semibold">❌ {statsDate.delivery?.[ch]?.failed ?? 0} failed</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Alerts that day */}
              {dayAlerts.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-gray-600 mb-2">Alerts on {statsDate.date}</h3>
                  <div className="overflow-x-auto rounded-xl border border-gray-100">
                    <table className="data-table w-full">
                      <thead><tr><th>Time (IST)</th><th>Value</th><th>Severity</th><th>Status</th></tr></thead>
                      <tbody>
                        {dayAlerts.map(a => (
                          <tr key={a.id}>
                            <td className="text-xs">{utcToIST(a.timestamp)}</td>
                            <td className="font-bold">{fmtAlertNumber(a.parameter, a.value)}</td>
                            <td><Badge color={SEV_COLOR[a.severity] || 'gray'} label={a.severity} small /></td>
                            <td>{a.acknowledged ? <span className="text-emerald-600 text-xs">✅ Acked</span> : <span className="text-amber-600 text-xs">Pending</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              {dayAlerts.length === 0 && (
                <p className="text-sm text-emerald-600 text-center py-3">✅ No alerts on {statsDate.date}</p>
              )}
            </div>
          )}
        </div>

        {/* Section 3 — Data Export */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Download size={18} className="text-purple-600" />
            <h2 className="text-sm font-bold text-gray-800">Export Data</h2>
          </div>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Start Date</label>
              <input type="date" className="form-input" value={exportStart}
                max={today()} onChange={e => setExportStart(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">End Date</label>
              <input type="date" className="form-input" value={exportEnd}
                max={today()} onChange={e => setExportEnd(e.target.value)} />
            </div>
          </div>
          <div className="flex gap-3">
            <button onClick={() => handleExport('alerts')} className="btn btn-primary btn-sm flex-1">
              <Download size={13} /> Export Alerts CSV
            </button>
            <button onClick={() => handleExport('readings')} className="btn btn-ghost btn-sm flex-1">
              <Download size={13} /> Export Readings CSV
            </button>
          </div>
        </div>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </>
  )
}
