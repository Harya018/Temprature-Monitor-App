/**
 * src/pages/ReceiptsPage.jsx
 * Proof of delivery — email and SMS notification receipts.
 *
 * In-app (WebSocket push) receipts are excluded — they always show
 * "no active connection" because no push subscriptions are configured,
 * which was skewing the stats and cluttering the table.
 *
 * Status and error_message come directly from the backend database —
 * the backend writes the real result (success=true/false) and the
 * real error string when a send attempt finishes.
 */
import { useState, useEffect, useCallback } from 'react'
import { Receipt, RefreshCw, Filter, CheckCircle, XCircle, Mail, MessageSquare } from 'lucide-react'
import { fetchReceipts } from '../services/api.js'
import { utcToIST, timeAgo } from '../utils/time.js'
import { SkeletonTable } from '../components/Skeleton'
import ErrorState from '../components/ErrorState'

export default function ReceiptsPage() {
  const [receipts,   setReceipts]   = useState([])
  const [loading,    setLoading]    = useState(false)
  const [fetchError, setFetchError] = useState(null)
  const [channel,    setChannel]    = useState('all')   // all | email | sms
  const [status,     setStatus]     = useState('all')   // all | success | failed

  const load = useCallback(async () => {
    setLoading(true)
    setFetchError(null)
    try {
      // Fetch all receipts then filter client-side so we can always
      // exclude inapp rows regardless of the channel filter.
      const all = await fetchReceipts(500, 'all', 'all')

      // ── Exclude inapp receipts entirely ──────────────────────────────────
      // inapp entries are always "failed / no active connection" because no
      // push subscriptions exist — they are noise that harms the stats.
      const noInapp = all.filter(r => r.channel !== 'inapp')

      // ── Apply channel filter ──────────────────────────────────────────────
      const byChannel = channel === 'all'
        ? noInapp
        : noInapp.filter(r => r.channel === channel)

      // ── Apply status filter ───────────────────────────────────────────────
      const byStatus = status === 'all'
        ? byChannel
        : byChannel.filter(r => status === 'success' ? r.success : !r.success)

      setReceipts(byStatus)
    } catch (err) { setFetchError(err?.message || 'Could not load receipts') }
    finally { setLoading(false) }
  }, [channel, status])

  useEffect(() => { load() }, [load])

  // ── Stats — calculated from all email+sms receipts (no inapp) ─────────────
  // Re-fetch base (no-inapp) for accurate totals regardless of current filter.
  const [baseReceipts, setBaseReceipts] = useState([])
  useEffect(() => {
    fetchReceipts(500, 'all', 'all')
      .then(all => setBaseReceipts(all.filter(r => r.channel !== 'inapp')))
      .catch(() => {})
  }, [loading]) // refresh whenever main load cycle runs

  const totalSent  = baseReceipts.length
  const totalOk    = baseReceipts.filter(r =>  r.success).length
  const rate       = totalSent ? Math.round((totalOk / totalSent) * 100) : 0
  const emailOk    = baseReceipts.filter(r => r.channel === 'email' && r.success).length
  const smsOk      = baseReceipts.filter(r => r.channel === 'sms'   && r.success).length

  const FilterBtn = ({ value, current, set, label }) => (
    <button
      onClick={() => set(value)}
      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
        current === value
          ? 'bg-purple-600 text-white'
          : 'bg-white border border-gray-200 text-gray-600 hover:border-purple-300'
      }`}
    >
      {label}
    </button>
  )

  return (
    <div className="space-y-5">

      {/* Summary stats — email + sms only, inapp excluded */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Total Sent',    value: totalSent, icon: <Receipt       size={18} />, color: '#7C3AED' },
          { label: 'Success Rate',  value: `${rate}%`, icon: <CheckCircle  size={18} />, color: '#10B981' },
          { label: 'Email Success', value: emailOk,   icon: <Mail          size={18} />, color: '#3B82F6' },
          { label: 'SMS Success',   value: smsOk,     icon: <MessageSquare size={18} />, color: '#F59E0B' },
        ].map(s => (
          <div key={s.label} className="card p-4 flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                 style={{ background: s.color + '15', color: s.color }}>
              {s.icon}
            </div>
            <div>
              <p className="text-xl font-bold" style={{ color: s.color }}>{s.value}</p>
              <p className="text-xs text-gray-500">{s.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="card px-5 py-4 flex flex-wrap gap-4 items-center">
        <Filter size={13} className="text-gray-400" />

        <div className="flex gap-1">
          <FilterBtn value="all"   current={channel} set={setChannel} label="All Channels" />
          <FilterBtn value="email" current={channel} set={setChannel} label="📧 Email" />
          <FilterBtn value="sms"   current={channel} set={setChannel} label="💬 SMS" />
        </div>

        <div className="flex gap-1">
          <FilterBtn value="all"     current={status} set={setStatus} label="All Status" />
          <FilterBtn value="success" current={status} set={setStatus} label="✅ Success" />
          <FilterBtn value="failed"  current={status} set={setStatus} label="❌ Failed" />
        </div>

        <button onClick={load} disabled={loading} className="btn btn-ghost btn-sm ml-auto">
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100">
          <span className="text-sm font-semibold text-gray-800">{receipts.length} receipts</span>
        </div>

        {fetchError && !loading ? (
          <ErrorState message={fetchError} onRetry={load} />
        ) : loading && receipts.length === 0 ? (
          <SkeletonTable />
        ) : receipts.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <CheckCircle size={32} className="mx-auto mb-2 text-emerald-400" />
            <p>No receipts found</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full">
              <thead><tr>
                <th>Alert ID</th>
                <th>Alert Time (IST)</th>
                <th>Channel</th>
                <th>Subscriber</th>
                <th>Sent At (IST)</th>
                <th>Status</th>
                <th>Error</th>
              </tr></thead>
              <tbody>
                {receipts.map(r => {
                  // Truncate long error messages — show full text on hover
                  const errFull = r.error_message || ''
                  const errShort = errFull.length > 40
                    ? errFull.slice(0, 37) + '...'
                    : errFull

                  return (
                    <tr key={r.id}>
                      {/* Alert ID */}
                      <td className="font-mono text-xs">#{r.alert_id}</td>

                      {/* Alert time */}
                      <td className="text-xs text-gray-500">{utcToIST(r.alert_time)}</td>

                      {/* Channel icon + label */}
                      <td>
                        {r.channel === 'email'
                          ? <span className="flex items-center gap-1 text-xs"><Mail size={11} /> Email</span>
                          : <span className="flex items-center gap-1 text-xs"><MessageSquare size={11} /> SMS</span>
                        }
                      </td>

                      {/* Subscriber name */}
                      <td className="font-medium">{r.subscriber_name || '—'}</td>

                      {/* Sent At */}
                      <td className="text-xs text-gray-500">
                        <p>{utcToIST(r.sent_at)}</p>
                        <p className="text-gray-400">{timeAgo(r.sent_at)}</p>
                      </td>

                      {/* Status — directly from backend success flag */}
                      <td>
                        {r.success
                          ? <CheckCircle size={16} className="text-emerald-500" />
                          : <XCircle    size={16} className="text-red-500" />
                        }
                      </td>

                      {/* Error — real error_message from backend, truncated with full on hover */}
                      <td
                        className="text-xs max-w-[180px] truncate"
                        style={{ color: errFull ? '#EF4444' : '#9CA3AF' }}
                        title={errFull || undefined}
                      >
                        {errShort || '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  )
}
