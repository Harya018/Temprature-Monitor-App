/**
 * src/pages/AlertsPage.jsx
 * Full dedicated alerts page with date filter, simplified table,
 * and a "Clear Alerts" button that opens a period selector + password modal.
 */
import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, Filter, CheckCircle, Trash2, FileText, X, Download, Printer } from 'lucide-react'
import { fetchAlerts, deleteAlerts } from '../services/api.js'
import { utcToIST, timeAgo } from '../utils/time.js'
import PasswordConfirmModal from '../components/PasswordConfirmModal.jsx'
import { useToast, ToastContainer } from '../components/shared/Toast.jsx'
import EmptyState from '../components/EmptyState'
import { exportCsv } from '../utils/exportCsv'

// ─── Period options ───────────────────────────────────────────────────────────
const CLEAR_PERIODS = [
  { value: '1h',  label: 'Last 1 Hour'   },
  { value: '24h', label: 'Last 24 Hours' },
  { value: '7d',  label: 'Last 7 Days'   },
  { value: '30d', label: 'Last 30 Days'  },
  { value: 'all', label: 'All Alerts'    },
]

const PERIOD_DESCRIPTIONS = {
  '1h':  'all alerts from the last 1 hour',
  '24h': 'all alerts from the last 24 hours',
  '7d':  'all alerts from the last 7 days',
  '30d': 'all alerts from the last 30 days',
  'all': 'ALL alert history permanently',
}

export default function AlertsPage({ onCountChange }) {
  const { toasts, addToast, dismiss } = useToast()
  const [alerts,     setAlerts]     = useState([])
  const [loading,    setLoading]    = useState(false)
  const [filterDate, setFilterDate] = useState('today') // today | week | all

  // ── Clear Alerts state ───────────────────────────────────────────────────────
  const [clearModal,   setClearModal]   = useState(false)   // period picker open
  const [clearPeriod,  setClearPeriod]  = useState('24h')   // selected period
  const [pwdModal,     setPwdModal]     = useState(false)   // password confirm open
  const [pwdError,     setPwdError]     = useState(null)
  const [clearing,     setClearing]     = useState(false)

  // ── Incident Report state ────────────────────────────────────────────────────
  const [reportAlertId, setReportAlertId] = useState(null)
  const [reportData,    setReportData]    = useState(null)
  const [reportLoading, setReportLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchAlerts(100)
      setAlerts(data)
      onCountChange?.(data.filter(a => !a.acknowledged).length)
    } catch { /* silent */ }
    finally { setLoading(false) }
  }, [onCountChange])

  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])

  // Date filter
  const now = Date.now()
  const filtered = alerts.filter(a => {
    if (filterDate === 'today') {
      const diff = now - new Date(a.timestamp).getTime()
      if (diff > 86400000) return false
    }
    if (filterDate === 'week') {
      const diff = now - new Date(a.timestamp).getTime()
      if (diff > 7 * 86400000) return false
    }
    return true
  })

  // ── Clear alerts flow ────────────────────────────────────────────────────────
  const handleClearConfirm = async (password) => {
    setPwdError(null)
    setClearing(true)
    try {
      const token = sessionStorage.getItem('admin_token') || ''
      const res = await fetch(`/api/alerts?period=${clearPeriod}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        credentials: 'include',
      })
      const data = await res.json()
      if (res.status === 401) {
        setPwdError('Incorrect password')
        return
      }
      if (!res.ok) {
        addToast({ type: 'error', message: `Failed to clear alerts: ${data.detail || 'Unknown error'}` })
        setPwdModal(false)
        setClearModal(false)
        return
      }
      addToast({
        type: 'success',
        message: `🗑 ${data.message}`,
      })
      setPwdModal(false)
      setClearModal(false)
      load()   // refresh the list
    } catch (e) {
      addToast({ type: 'error', message: 'Failed to clear alerts: ' + e.message })
    } finally {
      setClearing(false)
    }
  }

  const openReport = async (alertId) => {
    setReportAlertId(alertId)
    setReportData(null)
    setReportLoading(true)
    try {
      const token = sessionStorage.getItem('admin_token') || ''
      const res = await fetch(`/api/analytics/alerts/${alertId}/incident-report`, {
        headers: {
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        credentials: 'include',
      })
      if (!res.ok) {
        setReportData({ error: res.status === 401 ? 'Not authorized — admin login required.' : 'Failed to load report.' })
      } else {
        setReportData(await res.json())
      }
    } catch (e) {
      setReportData({ error: e.message })
    } finally {
      setReportLoading(false)
    }
  }

  const FilterBtn = ({ value, current, set, label }) => (
    <button
      onClick={() => set(value)}
      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
        current === value
          ? 'bg-purple-600 text-white shadow-sm'
          : 'bg-white text-gray-600 border border-gray-200 hover:border-purple-300'
      }`}
    >
      {label}
    </button>
  )

  return (
    <>
      <div className="space-y-5">

        {/* Header stats */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Total',           value: alerts.length,                             color: '#7C3AED' },
            { label: 'Unacknowledged',  value: alerts.filter(a => !a.acknowledged).length, color: '#EF4444' },
            { label: 'Acknowledged',    value: alerts.filter(a =>  a.acknowledged).length, color: '#10B981' },
          ].map(s => (
            <div key={s.label} className="card p-4 flex items-center gap-3">
              <span className="text-2xl font-bold" style={{ color: s.color }}>{s.value}</span>
              <span className="text-xs text-gray-500 font-medium">{s.label}</span>
            </div>
          ))}
        </div>

        {/* Filter bar */}
        <div className="card px-5 py-4">
          <div className="flex flex-wrap gap-4 items-center">
            <div className="flex items-center gap-1.5">
              <Filter size={13} className="text-gray-400" />
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Date</span>
            </div>
            <div className="flex gap-1.5">
              <FilterBtn value="today" current={filterDate} set={setFilterDate} label="Today" />
              <FilterBtn value="week"  current={filterDate} set={setFilterDate} label="Last 7 days" />
              <FilterBtn value="all"   current={filterDate} set={setFilterDate} label="All time" />
            </div>

            <div className="ml-auto flex items-center gap-2">
              <button
                id="btn-clear-alerts"
                onClick={() => { setClearPeriod('24h'); setClearModal(true) }}
                className="btn btn-sm flex items-center gap-1.5"
                style={{ background: '#FEF2F2', color: '#DC2626', border: '1px solid #FECACA' }}
              >
                <Trash2 size={13} /> Clear Alerts
              </button>
              <button
                onClick={() => exportCsv('alerts.csv', filtered.map(a => ({
                  id: a.id, parameter: a.parameter, value: a.value, threshold: a.threshold,
                  direction: a.direction, severity: a.severity, timestamp: a.timestamp,
                  acknowledged: a.acknowledged, acknowledged_by: a.acknowledged_by ?? '',
                })))}
                disabled={filtered.length === 0}
                className="btn btn-ghost btn-sm"
              >
                <Download size={13} /> Export CSV
              </button>
              <button onClick={load} disabled={loading} className="btn btn-ghost btn-sm">
                <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
              </button>
            </div>
          </div>
        </div>

        {/* Alerts table */}
        <div className="card" style={{ overflow: 'hidden' }}>
          <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-800">
              {filtered.length} alert{filtered.length !== 1 ? 's' : ''} shown
            </span>
            <span className="text-xs text-gray-400">Auto-refreshes every 10s</span>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              icon={CheckCircle}
              title="No alerts match the current filters"
              className="py-16"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table w-full">
                <thead><tr>
                  <th>Reading</th>
                  <th>Time</th>
                  <th style={{ width: 80, textAlign: 'center' }}>Report</th>
                </tr></thead>
                <tbody>
                  {filtered.map(alert => (
                    <tr key={alert.id}>
                      <td>
                        <span className="font-bold text-gray-800">{alert.value?.toFixed(1)}°C</span>
                        <span className="text-gray-400"> / {alert.threshold?.toFixed(1)}°C</span>
                      </td>
                      <td>
                        <p className="text-xs font-medium text-gray-700">{timeAgo(alert.timestamp)}</p>
                        <p className="text-xs text-gray-400">{utcToIST(alert.timestamp)}</p>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <button
                          title={`Incident report for alert #${alert.id}`}
                          onClick={() => openReport(alert.id)}
                          style={{
                            background: 'none', border: 'none', cursor: 'pointer',
                            padding: '4px 6px', borderRadius: 6,
                            color: '#7C3AED',
                          }}
                        >
                          <FileText size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── Period Selection Modal ──────────────────────────────────────────── */}
      {clearModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.5)' }}
          onClick={e => { if (e.target === e.currentTarget) setClearModal(false) }}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl p-6 flex flex-col gap-5"
            style={{ width: '100%', maxWidth: 420, margin: '1rem' }}
          >
            {/* Header */}
            <div>
              <div className="flex items-center gap-2 mb-1">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: '#FEF2F2' }}>
                  <Trash2 size={15} style={{ color: '#DC2626' }} />
                </div>
                <h2 className="text-base font-bold text-gray-900">Clear Alerts</h2>
              </div>
              <p className="text-sm text-gray-500 mt-1">
                Select which alerts to delete. <strong>This cannot be undone.</strong>
              </p>
            </div>

            {/* Period pill buttons */}
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Time Period
              </p>
              <div className="flex flex-wrap gap-2">
                {CLEAR_PERIODS.map(opt => (
                  <button
                    key={opt.value}
                    id={`clear-period-${opt.value}`}
                    onClick={() => setClearPeriod(opt.value)}
                    className="px-4 py-2 rounded-full text-xs font-semibold border transition-all"
                    style={
                      clearPeriod === opt.value
                        ? { background: '#7C3AED', color: '#fff', borderColor: '#7C3AED' }
                        : { background: '#fff', color: '#374151', borderColor: '#D1D5DB' }
                    }
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Dynamic description */}
            <div
              className="rounded-lg px-4 py-3 text-sm"
              style={{
                background: clearPeriod === 'all' ? '#FEF2F2' : '#F5F3FF',
                border: `1px solid ${clearPeriod === 'all' ? '#FECACA' : '#DDD6FE'}`,
              }}
            >
              {clearPeriod === 'all' ? (
                <p style={{ color: '#991B1B' }}>
                  ⚠ This will delete <strong>ALL alert history</strong> permanently.
                </p>
              ) : (
                <p style={{ color: '#5B21B6' }}>
                  This will permanently delete {PERIOD_DESCRIPTIONS[clearPeriod]}.
                </p>
              )}
            </div>

            {/* Action buttons */}
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setClearModal(false)}
                className="btn btn-ghost btn-sm"
              >
                Cancel
              </button>
              <button
                id="btn-clear-alerts-confirm"
                onClick={() => { setClearModal(false); setPwdError(null); setPwdModal(true) }}
                className="btn btn-sm flex items-center gap-1.5"
                style={{ background: '#DC2626', color: '#fff', border: 'none' }}
              >
                <Trash2 size={13} /> Clear Alerts
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Password Confirmation Modal ─────────────────────────────────────── */}
      <PasswordConfirmModal
        isOpen={pwdModal}
        actionLabel={`permanently delete ${PERIOD_DESCRIPTIONS[clearPeriod]}`}
        onConfirm={handleClearConfirm}
        onCancel={() => { setPwdModal(false); setPwdError(null) }}
        error={pwdError}
      />

      {/* ── Incident Report Modal ─────────────────────────────────────────── */}
      {reportAlertId !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.55)' }}
          onClick={e => { if (e.target === e.currentTarget) setReportAlertId(null) }}
        >
          <div
            className="incident-report-modal"
            style={{
              background: '#fff', borderRadius: 16, boxShadow: '0 24px 64px rgba(0,0,0,0.18)',
              width: '100%', maxWidth: 680, maxHeight: '85vh', overflowY: 'auto',
              margin: '1rem', padding: '1.5rem',
            }}
          >
            {/* Modal header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ background: '#F5F3FF', borderRadius: 8, padding: '6px 8px', display: 'flex' }}>
                  <FileText size={16} style={{ color: '#7C3AED' }} />
                </div>
                <div>
                  <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#111827' }}>
                    Incident Report — Alert #{reportAlertId}
                  </h2>
                  {reportData && !reportData.error && (
                    <p style={{ margin: 0, fontSize: 11, color: '#9CA3AF' }}>
                      Generated {utcToIST(reportData.generated_at)}
                    </p>
                  )}
                </div>
              </div>
              <div className="no-print" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {reportData && !reportData.error && (
                  <button
                    onClick={() => window.print()}
                    title="Print incident report"
                    style={{ background: '#F5F3FF', border: 'none', cursor: 'pointer', color: '#7C3AED', padding: '6px 8px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600 }}
                  >
                    <Printer size={14} /> Print
                  </button>
                )}
                <button
                  onClick={() => setReportAlertId(null)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', padding: 4 }}
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {reportLoading && (
              <p style={{ textAlign: 'center', color: '#6B7280', padding: '2rem 0' }}>Loading report…</p>
            )}
            {!reportLoading && reportData?.error && (
              <p style={{ color: '#DC2626', textAlign: 'center', padding: '2rem 0' }}>{reportData.error}</p>
            )}
            {!reportLoading && reportData && !reportData.error && (() => {
              const { alert, delivery, escalations, context_readings } = reportData
              const SEV_COLOR = { WARNING: '#D97706', CRITICAL: '#DC2626', EMERGENCY: '#7C3AED' }
              const sevColor  = SEV_COLOR[alert.severity] || '#6B7280'
              return (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

                  {/* Alert summary */}
                  <section>
                    <h3 style={{ fontSize: 12, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>Alert Summary</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
                      {[
                        { label: 'Severity',   value: alert.severity,            style: { color: sevColor, fontWeight: 700 } },
                        { label: 'Value',      value: `${Number(alert.value).toFixed(2)} / ${Number(alert.threshold).toFixed(2)}` },
                        { label: 'Direction',  value: alert.direction },
                        { label: 'Parameter',  value: alert.parameter },
                        { label: 'Time (IST)', value: utcToIST(alert.timestamp) },
                        { label: 'Status',     value: alert.acknowledged ? `Acked by ${alert.acknowledged_by}` : 'Unacknowledged',
                                               style: { color: alert.acknowledged ? '#10B981' : '#EF4444', fontWeight: 600 } },
                      ].map(item => (
                        <div key={item.label} style={{ background: '#F9FAFB', borderRadius: 8, padding: '10px 12px' }}>
                          <p style={{ margin: 0, fontSize: 10, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{item.label}</p>
                          <p style={{ margin: '3px 0 0', fontSize: 13, fontWeight: 600, color: '#111827', ...item.style }}>{item.value || '—'}</p>
                        </div>
                      ))}
                    </div>
                  </section>

                  {/* Delivery receipts */}
                  <section>
                    <h3 style={{ fontSize: 12, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                      Delivery Receipts ({delivery.length})
                    </h3>
                    {delivery.length === 0 ? (
                      <p style={{ fontSize: 13, color: '#9CA3AF' }}>No delivery data recorded.</p>
                    ) : (
                      <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                          <thead>
                            <tr style={{ background: '#F3F4F6' }}>
                              {['Channel', 'Subscriber', 'Sent At (IST)', 'Level', 'Status'].map(h => (
                                <th key={h} style={{ padding: '7px 10px', textAlign: 'left', fontWeight: 600, color: '#374151' }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {delivery.map((d, i) => (
                              <tr key={i} style={{ borderBottom: '1px solid #F3F4F6' }}>
                                <td style={{ padding: '7px 10px', textTransform: 'capitalize' }}>{d.channel}</td>
                                <td style={{ padding: '7px 10px' }}>{d.subscriber_name}</td>
                                <td style={{ padding: '7px 10px' }}>{utcToIST(d.sent_at)}</td>
                                <td style={{ padding: '7px 10px' }}>{d.escalation_level}</td>
                                <td style={{ padding: '7px 10px' }}>
                                  <span style={{ color: d.success ? '#10B981' : '#EF4444', fontWeight: 600 }}>
                                    {d.success ? 'Delivered' : `Failed${d.error_message ? `: ${d.error_message.slice(0,40)}` : ''}`}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>

                  {/* Escalation policy log */}
                  <section>
                    <h3 style={{ fontSize: 12, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                      Re-notification Log ({escalations.length})
                    </h3>
                    {escalations.length === 0 ? (
                      <p style={{ fontSize: 13, color: '#9CA3AF' }}>No escalations — alert was acknowledged within the initial wait time.</p>
                    ) : (
                      <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                          <thead>
                            <tr style={{ background: '#F3F4F6' }}>
                              {['Level', 'Subscriber', 'Notified At (IST)'].map(h => (
                                <th key={h} style={{ padding: '7px 10px', textAlign: 'left', fontWeight: 600, color: '#374151' }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {escalations.map((e, i) => (
                              <tr key={i} style={{ borderBottom: '1px solid #F3F4F6' }}>
                                <td style={{ padding: '7px 10px' }}>Level {e.escalation_level}</td>
                                <td style={{ padding: '7px 10px' }}>{e.subscriber_name}</td>
                                <td style={{ padding: '7px 10px' }}>{utcToIST(e.notified_at)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>

                  {/* Context readings */}
                  {context_readings.length > 0 && (
                    <section>
                      <h3 style={{ fontSize: 12, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                        Context Readings (±5 around alert)
                      </h3>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        {context_readings.map((r, i) => (
                          <div key={i} style={{
                            background: r.side === 'after' ? '#EFF6FF' : '#F9FAFB',
                            border: `1px solid ${r.side === 'after' ? '#BFDBFE' : '#E5E7EB'}`,
                            borderRadius: 8, padding: '6px 10px', fontSize: 12, textAlign: 'center',
                          }}>
                            <div style={{ fontWeight: 700, color: r.side === 'after' ? '#1D4ED8' : '#374151' }}>
                              {Number(r.temperature).toFixed(1)}°C
                            </div>
                            <div style={{ fontSize: 10, color: '#9CA3AF', marginTop: 2 }}>{timeAgo(r.timestamp)}</div>
                          </div>
                        ))}
                      </div>
                      <p style={{ fontSize: 11, color: '#9CA3AF', marginTop: 8 }}>
                        Blue = after alert · Gray = before alert
                      </p>
                    </section>
                  )}
                </div>
              )
            })()}
          </div>
        </div>
      )}

      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </>
  )
}
