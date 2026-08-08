/**
 * src/pages/HealthPage.jsx
 * Full system health — modules, DB stats, config changes, backup.
 * Includes GSM modem status banner and Test SMS button.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  RefreshCw, Thermometer, Database, Mail, MessageSquare,
  Wifi, CheckCircle, AlertTriangle, XCircle, Archive,
  Signal, SignalZero, Send, X,
} from 'lucide-react'
import {
  fetchHealth, fetchDatabaseStats, fetchAdminConfigChanges,
  createBackup, fetchSubscribers,
} from '../services/api.js'
import { utcToIST, timeAgo } from '../utils/time.js'
import Badge from '../components/shared/Badge.jsx'
import { useToast, ToastContainer } from '../components/shared/Toast.jsx'

const MODULE_ICONS = {
  sensor:    <Thermometer   size={20} />,
  database:  <Database      size={20} />,
  email:     <Mail          size={20} />,
  sms:       <MessageSquare size={20} />,
  websocket: <Wifi          size={20} />,
}

function statusBadge(s) {
  const str = String(s || '')
  if (!str || str === 'not_built')      return { color:'gray',  label:'Not Built' }
  if (str === 'ok')                     return { color:'green', label:'OK' }
  if (str === 'starting')               return { color:'amber', label:'Starting' }
  if (str.startsWith('configured'))     return { color:'green', label:'Configured' }
  if (str.startsWith('ok'))             return { color:'green', label:'OK' }
  if (str.startsWith('error'))          return { color:'red',   label:'Error' }
  return { color:'gray', label: str }
}

function statusIcon(s) {
  const str = String(s || '')
  if (!str || str === 'not_built')   return <Archive size={16} className="text-gray-400" />
  if (str.startsWith('ok'))          return <CheckCircle size={16} className="text-emerald-500" />
  if (str.startsWith('configured'))  return <CheckCircle size={16} className="text-emerald-500" />
  if (str === 'starting')            return <AlertTriangle size={16} className="text-amber-500" />
  if (str.startsWith('error'))       return <XCircle size={16} className="text-red-500" />
  return <AlertTriangle size={16} className="text-amber-400" />
}

export default function HealthPage() {
  const { toasts, addToast, dismiss } = useToast()
  const [health,  setHealth]  = useState(null)
  const [stats,   setStats]   = useState(null)
  const [changes, setChanges] = useState([])
  const [loading, setLoading] = useState(false)
  const [backing, setBacking] = useState(false)

  // Test SMS modal state
  const [smsModal,   setSmsModal]   = useState(false)
  const [smsPhone,   setSmsPhone]   = useState('')
  const [smsSending, setSmsSending] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [h, s, c, subs] = await Promise.allSettled([
        fetchHealth(), fetchDatabaseStats(), fetchAdminConfigChanges(), fetchSubscribers(),
      ])
      if (h.status === 'fulfilled') setHealth(h.value)
      if (s.status === 'fulfilled') setStats(s.value)
      if (c.status === 'fulfilled') setChanges(c.value)
      // Pre-fill Test SMS with first active subscriber's phone
      if (subs.status === 'fulfilled') {
        const first = (subs.value || []).find(sub => sub.is_active && sub.phone)
        if (first) setSmsPhone(prev => prev || first.phone)
      }
    } finally { setLoading(false) }
  }, [])  // eslint-disable-line

  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [load])

  const handleBackup = async () => {
    setBacking(true)
    try {
      const r = await createBackup()
      addToast({ type:'success', message:`✅ Backup: ${r.filename} (${r.size_mb} MB)` })
      load()
    } catch (e) { addToast({ type:'error', message:'Backup failed: ' + e.message }) }
    finally { setBacking(false) }
  }

  const handleTestSms = async () => {
    if (!smsPhone.trim()) return
    setSmsSending(true)
    try {
      const token = sessionStorage.getItem('admin_token') || ''
      const res = await fetch('/api/admin/test-sms', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ phone: smsPhone.trim() }),
        credentials: 'include',
      })
      const data = await res.json()
      if (res.ok) {
        const isMock = data.mode === 'mock'
        addToast({
          type: 'success',
          message: isMock
            ? `📱 [MOCK] SMS logged for ${smsPhone} — no modem connected`
            : `✅ SMS sent to ${smsPhone} — check your phone`,
        })
        setSmsModal(false)
      } else {
        addToast({ type: 'error', message: `SMS failed: ${data.error || 'Unknown error'}` })
      }
    } catch (e) {
      addToast({ type: 'error', message: 'Test SMS error: ' + e.message })
    } finally {
      setSmsSending(false)
    }
  }

  const modules     = health?.modules || {}
  const overall     = health?.status
  const overallBg    = overall === 'ok' ? '#ECFDF5' : overall === 'degraded' ? '#FFFBEB' : '#FEF2F2'
  const overallColor = overall === 'ok' ? '#065F46' : overall === 'degraded' ? '#92400E' : '#991B1B'

  // GSM modem info
  const gsm     = health?.gsm_modem
  const gsmMode = gsm?.mode || 'mock'
  const gsmPort = gsm?.port || 'not detected'
  const gsmLive = gsmMode === 'live'

  return (
    <>
      <div className="space-y-5">

        {/* ── GSM Modem status banner ── */}
        {gsm && (
          <div
            className="card px-5 py-3 flex items-center justify-between gap-3"
            style={{
              background: gsmLive ? '#ECFDF5' : '#FFFBEB',
              border:     `1px solid ${gsmLive ? '#10B98130' : '#F59E0B50'}`,
            }}
          >
            <div className="flex items-center gap-3">
              {gsmLive
                ? <Signal     size={20} style={{ color: '#10B981', flexShrink: 0 }} />
                : <SignalZero size={20} style={{ color: '#D97706', flexShrink: 0 }} />
              }
              <div>
                <p className="text-sm font-semibold" style={{ color: gsmLive ? '#065F46' : '#92400E' }}>
                  {gsmLive
                    ? `✓ GSM Modem Connected on ${gsmPort} — SMS alerts active`
                    : '⚠ GSM Modem Not Connected — SMS alerts are in mock mode'}
                </p>
                {!gsmLive && (
                  <p className="text-xs mt-0.5" style={{ color: '#B45309' }}>
                    Plug in the GSM dongle and restart the server to enable real SMS delivery.
                  </p>
                )}
              </div>
            </div>
            <button
              id="btn-test-sms"
              onClick={() => setSmsModal(true)}
              className="btn btn-sm flex items-center gap-1.5 whitespace-nowrap"
              style={{
                background: gsmLive ? '#10B981' : '#F59E0B',
                color: '#fff',
                border: 'none',
              }}
            >
              <Send size={13} /> Send Test SMS
            </button>
          </div>
        )}

        {/* Overall status banner */}
        <div
          className="card px-6 py-4 flex items-center justify-between"
          style={{ background: overallBg, border: `1px solid ${overallColor}30` }}
        >
          <div className="flex items-center gap-3">
            {overall === 'ok'
              ? <CheckCircle size={22} style={{ color: '#10B981' }} />
              : <AlertTriangle size={22} style={{ color: '#F59E0B' }} />
            }
            <div>
              <p className="font-bold" style={{ color: overallColor, fontSize: '0.95rem' }}>
                System Status: {overall?.toUpperCase() || 'UNKNOWN'}
              </p>
              <p className="text-xs" style={{ color: overallColor, opacity: 0.8 }}>
                {overall === 'ok' ? 'All systems operational' : 'One or more modules need attention'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">v{health?.version || '1.0.0'}</span>
            <button onClick={load} disabled={loading} className="btn btn-ghost btn-sm">
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Module grid */}
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Module Status</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {['sensor','database','email','sms','websocket'].map(mod => {
              // API now returns modules as { status: "ok" } objects — unwrap .status
              const raw = modules[mod]
              const val = String(
                (raw && typeof raw === 'object' ? raw.status : raw) ?? 'unknown'
              )
              const sb      = statusBadge(val)
              const isError = val.startsWith('error')
              return (
                <div key={mod} className="card p-5">
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div
                        className="w-10 h-10 rounded-xl flex items-center justify-center"
                        style={{
                          background: sb.color === 'green' ? '#ECFDF5' : sb.color === 'red' ? '#FEF2F2' : '#FFFBEB',
                          color: sb.color === 'green' ? '#10B981' : sb.color === 'red' ? '#EF4444' : '#F59E0B',
                        }}
                      >
                        {MODULE_ICONS[mod]}
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-gray-800 capitalize">{mod}</p>
                        <Badge color={sb.color} label={sb.label} small />
                      </div>
                    </div>
                    {statusIcon(val)}
                  </div>
                  {isError && (
                    <p className="text-xs text-red-600 bg-red-50 rounded-lg px-2.5 py-1.5 mt-2">
                      {val.replace('error: ', '')}
                    </p>
                  )}
                  {val === 'not_built' && (
                    <p className="text-xs text-gray-400 mt-2">Module not implemented yet</p>
                  )}
                  {val !== 'unknown' && val !== 'not_built' && !isError && (
                    <p className="text-xs text-gray-400 mt-2 truncate" title={val}>{val}</p>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* DB Stats */}
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Database Statistics</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: 'Total Readings', value: stats?.readings_count  ?? '—', icon: '📡' },
              { label: 'Total Alerts',   value: stats?.alerts_count    ?? '—', icon: '🔔' },
              { label: 'DB Size',        value: stats ? `${stats.database_size_mb} MB` : '—', icon: '💾' },
              { label: 'Backups',        value: stats?.backup_count    ?? '—', icon: '📦' },
            ].map(s => (
              <div key={s.label} className="card p-4 flex items-center gap-3">
                <span className="text-2xl">{s.icon}</span>
                <div>
                  <p className="text-lg font-bold text-gray-900">{s.value}</p>
                  <p className="text-xs text-gray-500">{s.label}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex justify-end">
            <button onClick={handleBackup} disabled={backing} className="btn btn-info btn-sm">
              <Database size={13} /> {backing ? 'Creating backup…' : 'Create Backup Now'}
            </button>
          </div>
        </div>

        {/* Recent config changes */}
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Recent Config Changes</h2>
          <div className="card" style={{ overflow: 'hidden' }}>
            {changes.length === 0 ? (
              <div className="py-8 text-center text-gray-400 text-sm">No configuration changes recorded.</div>
            ) : (
              <table className="data-table w-full">
                <thead><tr>
                  <th>Field</th>
                  <th>Old Value</th>
                  <th>New Value</th>
                  <th>Changed By</th>
                  <th>Time (IST)</th>
                </tr></thead>
                <tbody>
                  {changes.slice(0,20).map(c => (
                    <tr key={c.id}>
                      <td className="font-medium">{c.field_name}</td>
                      <td className="text-gray-400">{c.old_value}</td>
                      <td className="font-semibold text-purple-700">{c.new_value}</td>
                      <td className="text-gray-500">{c.changed_by}</td>
                      <td>
                        <p className="text-xs">{timeAgo(c.changed_at)}</p>
                        <p className="text-xs text-gray-400">{utcToIST(c.changed_at)}</p>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* ── Test SMS Modal ── */}
      {smsModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.45)' }}
          onClick={e => { if (e.target === e.currentTarget) setSmsModal(false) }}
        >
          <div className="card p-6 w-full max-w-sm shadow-2xl" style={{ margin: '1rem' }}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-base font-bold text-gray-900">Send Test SMS</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  Mode: <span
                    className="font-semibold"
                    style={{ color: gsmLive ? '#10B981' : '#D97706' }}
                  >
                    {gsmLive ? `LIVE (${gsmPort})` : 'MOCK — will only log'}
                  </span>
                </p>
              </div>
              <button
                onClick={() => setSmsModal(false)}
                className="btn btn-ghost btn-sm"
                id="btn-test-sms-close"
              >
                <X size={16} />
              </button>
            </div>

            <label className="block text-sm font-medium text-gray-700 mb-1">
              Phone Number
            </label>
            <input
              id="test-sms-phone"
              type="tel"
              value={smsPhone}
              onChange={e => setSmsPhone(e.target.value)}
              placeholder="+916385936224 or 6385936224"
              className="input w-full mb-4"
              onKeyDown={e => { if (e.key === 'Enter') handleTestSms() }}
            />

            <div className="flex gap-3">
              <button
                id="btn-test-sms-send"
                onClick={handleTestSms}
                disabled={smsSending || !smsPhone.trim()}
                className="btn btn-primary flex-1 flex items-center justify-center gap-2"
              >
                <Send size={14} />
                {smsSending ? 'Sending…' : gsmLive ? 'Send SMS' : 'Log Mock SMS'}
              </button>
              <button
                onClick={() => setSmsModal(false)}
                className="btn btn-ghost"
              >
                Cancel
              </button>
            </div>

            {!gsmLive && (
              <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 mt-3">
                ⚠ No modem detected. SMS will be logged server-side only.
                Plug in the GSM dongle and restart to send real messages.
              </p>
            )}
          </div>
        </div>
      )}

      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </>
  )
}
