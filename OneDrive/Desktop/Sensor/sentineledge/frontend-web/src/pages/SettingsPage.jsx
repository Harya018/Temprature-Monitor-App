/**
 * src/pages/SettingsPage.jsx
 * Threshold config, demo controls (CSV playback), and admin info.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { Settings2, RotateCcw, Zap, Database, Info, Server, RefreshCw, AlertTriangle, Mail, CheckCircle, MessageSquare, Smartphone, PlusCircle, Pencil } from 'lucide-react'
import {
  fetchThresholds, updateThresholds, resetThresholds,
  simulateBreach, createBackup, fetchHealth,
} from '../services/api.js'
import { utcToIST } from '../utils/time.js'
import Badge from '../components/shared/Badge.jsx'
import { useToast, ToastContainer } from '../components/shared/Toast.jsx'
import PasswordConfirmModal from '../components/PasswordConfirmModal.jsx'

const simulateDemo = (speed) => fetch('/api/simulate/demo', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-Admin-Password': sessionStorage.getItem('adminPassword') || '',
  },
  body: JSON.stringify({ speed }),
  credentials: 'include',
}).then(r => r.json())

const simulateReset = () => fetch('/api/simulate/reset', {
  method: 'POST',
  headers: { 'X-Admin-Password': sessionStorage.getItem('adminPassword') || '' },
  credentials: 'include',
}).then(r => r.json())

const SPEED_OPTIONS = [
  { value: 10, label: '10x faster', desc: '~15 min per cycle' },
  { value: 30, label: '30x faster', desc: '~5 min per cycle' },
  { value: 50, label: '50x faster', desc: '~3 min per cycle' },
]

function Section({ title, icon: Icon, children }) {
  return (
    <div className="card">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-100">
        <div className="w-8 h-8 rounded-lg bg-purple-100 flex items-center justify-center">
          <Icon size={15} className="text-purple-600" />
        </div>
        <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
      </div>
      <div className="p-5">{children}</div>
    </div>
  )
}

function StatusMsg({ msg }) {
  if (!msg) return null
  return (
    <p className={`text-xs rounded-lg px-3 py-2 ${
      msg.type === 'success' ? 'text-emerald-700 bg-emerald-50' :
      msg.type === 'info'    ? 'text-blue-700 bg-blue-50' :
                               'text-red-700 bg-red-50'
    }`}>{msg.text}</p>
  )
}

// ── Add Parameter form — module-level so it has stable identity and its own
// state; parent re-renders (e.g. from WebSocket ticks) never interfere. ────────
function AddParameterForm({ onToast }) {
  const [paramName, setParamName]             = useState('')
  const [paramUnit, setParamUnit]             = useState('')
  const [paramMin,  setParamMin]              = useState('')
  const [paramMax,  setParamMax]              = useState('')
  const [paramSubmitting, setParamSubmitting] = useState(false)
  const [paramSaved, setParamSaved]           = useState(false)

  async function handleSaveParam() {
    if (!paramName.trim() || !paramUnit.trim()) {
      onToast({ type: 'warning', message: 'Parameter Name and Unit are required.' })
      return
    }
    setParamSubmitting(true)
    try {
      const token = sessionStorage.getItem('admin_token')
      const res = await fetch('/api/admin/parameters', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          name:      paramName.trim(),
          unit:      paramUnit.trim(),
          min_value: paramMin !== '' ? Number(paramMin) : null,
          max_value: paramMax !== '' ? Number(paramMax) : null,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.error || `Server error ${res.status}`)
      }
      onToast({ type: 'success', message: `"${paramName}" submitted for super admin approval.` })
      setParamSaved(true)
      setParamName(''); setParamUnit(''); setParamMin(''); setParamMax('')
      setTimeout(() => setParamSaved(false), 3000)
    } catch (err) {
      onToast({ type: 'error', message: err.message || 'Failed to submit parameter.' })
    } finally {
      setParamSubmitting(false)
    }
  }

  return (
    <>
      <p style={{ fontSize: 13, color: '#6B7280', marginBottom: 20, marginTop: -4 }}>
        Define a new sensor metric to monitor. This will appear as a live card on the Dashboard.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
            Parameter Name
          </label>
          <input
            className="form-input"
            value={paramName}
            onChange={e => setParamName(e.target.value)}
            placeholder="e.g. Pressure"
          />
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
            Unit
          </label>
          <input
            className="form-input"
            value={paramUnit}
            onChange={e => setParamUnit(e.target.value)}
            placeholder="e.g. bar, %, mm/s"
          />
        </div>
        <div>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
            Min Value
          </label>
          <input
            className="form-input"
            type="number"
            value={paramMin}
            onChange={e => setParamMin(e.target.value)}
            placeholder="e.g. 0.0"
          />
        </div>
        <div>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
            Max Value
          </label>
          <input
            className="form-input"
            type="number"
            value={paramMax}
            onChange={e => setParamMax(e.target.value)}
            placeholder="e.g. 10.0"
          />
        </div>
      </div>
      <div style={{ marginTop: 20, display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={handleSaveParam}
          disabled={paramSubmitting}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '9px 20px', borderRadius: 8, border: 'none',
            background: paramSubmitting ? '#A78BFA' : '#7C3AED', color: '#fff',
            fontSize: 13, fontWeight: 600,
            cursor: paramSubmitting ? 'not-allowed' : 'pointer',
            transition: 'background 0.15s',
          }}
        >
          {paramSubmitting
            ? <><RefreshCw size={14} className="animate-spin" /> Submitting…</>
            : <><PlusCircle size={15} /> Request Parameter</>
          }
        </button>
        {paramSaved && (
          <span style={{ fontSize: 12, color: '#10B981', fontWeight: 600 }}>✓ Saved!</span>
        )}
      </div>
      <div style={{
        marginTop: 16, padding: '10px 14px', borderRadius: 8,
        background: '#F0FDF4', border: '1px solid #BBF7D0', fontSize: 12, color: '#065F46',
      }}>
        💡 Submitted parameters go to the Super Admin for approval. Once approved they appear as live sensor cards on the Dashboard.
      </div>
    </>
  )
}

export default function SettingsPage() {
  const { toasts, addToast, dismiss } = useToast()

  const [threshData, setThreshData] = useState(null)
  const [high, setHigh] = useState(90)
  const [low, setLow] = useState(38)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [threshMsg, setThreshMsg] = useState(null)

  const [demoSpeed, setDemoSpeed] = useState(30)
  const [demoRunning, setDemoRunning] = useState(false)
  const [demoStatus, setDemoStatus] = useState(null)
  const [demoResetting, setDemoResetting] = useState(false)
  const [simulating, setSimulating] = useState(false)

  const [backing, setBacking] = useState(false)
  const [health, setHealth] = useState(null)

  const [testEmailAddr, setTestEmailAddr] = useState('crharya@gmail.com')
  const [testingEmail, setTestingEmail] = useState(false)
  const [testEmailMsg, setTestEmailMsg] = useState(null)

  const [testSmsPhone, setTestSmsPhone] = useState('6385936224')
  const [testingSms, setTestingSms] = useState(false)
  const [testSmsMsg, setTestSmsMsg] = useState(null)

  const [pwdAction, setPwdAction] = useState(null)
  const [pwdError, setPwdError] = useState(null)

  // Track whether user has touched the inputs so fetches don't overwrite
  const dirtyRef = useRef(false)

  const loadThresholds = useCallback(async () => {
    try {
      const d = await fetchThresholds()
      setThreshData(d)
      if (!dirtyRef.current) {
        setHigh(d.temperature?.high ?? 90)
        setLow(d.temperature?.low ?? 38)
      }
    } catch { /* silent */ }
  }, [])

  const loadHealth = useCallback(async () => {
    try { setHealth(await fetchHealth()) } catch { /* silent */ }
  }, [])

  useEffect(() => { loadThresholds(); loadHealth() }, [loadThresholds, loadHealth])

  useEffect(() => {
    if (health?.smtp_user) setTestEmailAddr(health.smtp_user)
  }, [health])

  const handleUpdate = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (Number(high) <= Number(low)) {
      setThreshMsg({ type: 'error', text: 'High must be greater than low.' })
      return
    }
    setPwdAction('update')
    setPwdError(null)
  }

  const doUpdate = async (password) => {
    setSaving(true); setThreshMsg(null)
    try {
      await updateThresholds({ temp_high: Number(high), temp_low: Number(low) }, password)
      setThreshMsg({ type: 'success', text: 'Thresholds updated.' })
      setPwdAction(null)
      dirtyRef.current = false
      loadThresholds()
    } catch (err) {
      if (err.message?.includes('401')) { setPwdError('Incorrect password'); return }
      setThreshMsg({ type: 'error', text: err.message })
      setPwdAction(null)
    } finally { setSaving(false) }
  }

  const handleReset = () => {
    setPwdAction('reset')
    setPwdError(null)
  }

  const doReset = async (password) => {
    setResetting(true); setThreshMsg(null)
    try {
      await resetThresholds(password)
      setThreshMsg({ type: 'success', text: 'Reset to defaults (90°C / 42°C).' })
      setPwdAction(null)
      dirtyRef.current = false
      loadThresholds()
    } catch (err) {
      if (err.message?.includes('401')) { setPwdError('Incorrect password'); return }
      setThreshMsg({ type: 'error', text: err.message })
      setPwdAction(null)
    } finally { setResetting(false) }
  }

  const handlePasswordConfirm = (password) => {
    setPwdError(null)
    if (pwdAction === 'update') doUpdate(password)
    if (pwdAction === 'reset') doReset(password)
  }

  const handleDemoRun = async () => {
    setDemoRunning(true); setDemoStatus(null)
    try {
      const r = await simulateDemo(demoSpeed)
      const mins = r.estimated_duration_minutes ?? '—'
      setDemoStatus({
        type: 'info',
        text: `Demo started at ${demoSpeed}x speed — ~${mins} min for full cycle. `
          + `Alert fires when temperature drops to 38°C.`,
      })
      addToast({
        type: 'warning',
        message: `🔬 Demo ${demoSpeed}x — playing ${r.total_readings ?? '—'} real readings. Alert fires at 38°C.`,
      })
    } catch (err) {
      setDemoStatus({ type: 'error', text: 'Demo failed: ' + err.message })
      addToast({ type: 'error', message: 'Demo failed: ' + err.message })
    } finally { setDemoRunning(false) }
  }

  const handleDemoReset = async () => {
    setDemoResetting(true)
    try {
      await simulateReset()
      setDemoStatus({ type: 'success', text: 'Sensor reset to beginning of real data.' })
      addToast({ type: 'success', message: '✅ Sensor rewound to beginning of CSV data.' })
    } catch (err) { addToast({ type: 'error', message: 'Reset failed: ' + err.message }) }
    finally { setDemoResetting(false) }
  }

  const handleSimulateBreach = async () => {
    setSimulating(true)
    try {
      await simulateBreach()
      addToast({ type: 'warning', message: '⚡ Breach simulated — 92°C for 10 readings.' })
    } catch (err) { addToast({ type: 'error', message: 'Simulate failed: ' + err.message }) }
    finally { setSimulating(false) }
  }

  const handleBackup = async () => {
    setBacking(true)
    try {
      const r = await createBackup()
      addToast({ type: 'success', message: `✅ Backup created: ${r.filename} (${r.size_mb} MB)` })
    } catch (err) { addToast({ type: 'error', message: 'Backup failed: ' + err.message }) }
    finally { setBacking(false) }
  }

  const handleTestEmail = async () => {
    if (!testEmailAddr.trim()) return
    setTestingEmail(true); setTestEmailMsg(null)
    try {
      const res = await fetch('/api/admin/test-email', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Password': sessionStorage.getItem('adminPassword') || 'admin123',
        },
        body: JSON.stringify({ email: testEmailAddr.trim() }),
        credentials: 'include',
      })
      const data = await res.json()
      if (res.ok && data.status === 'sent') {
        setTestEmailMsg({ type: 'success', text: `✅ Test email sent to ${data.email}` })
        addToast({ type: 'success', message: `📧 Test email sent to ${data.email}` })
      } else {
        const err = data.error || data.detail || 'Unknown error'
        setTestEmailMsg({ type: 'error', text: `Failed: ${err}` })
        addToast({ type: 'error', message: `Email failed: ${err}` })
      }
    } catch (err) {
      setTestEmailMsg({ type: 'error', text: 'Failed: ' + err.message })
      addToast({ type: 'error', message: 'Email test error: ' + err.message })
    } finally { setTestingEmail(false) }
  }

  const handleTestSms = async () => {
    if (!testSmsPhone.trim()) return
    setTestingSms(true); setTestSmsMsg(null)
    try {
      const res = await fetch('/api/admin/test-sms', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Password': sessionStorage.getItem('adminPassword') || 'admin123',
        },
        body: JSON.stringify({ phone: testSmsPhone.trim() }),
        credentials: 'include',
      })
      const data = await res.json()
      if (res.ok && data.status === 'sent') {
        setTestSmsMsg({
          type: 'success',
          text: `✅ SMS sent to ${data.phone} via ${data.method} (${data.chars} chars)`,
        })
        addToast({ type: 'success', message: `📱 Test SMS sent to ${data.phone} via ${data.method}` })
      } else {
        const err = data.error || data.detail || 'Unknown error'
        setTestSmsMsg({ type: 'error', text: `Failed: ${err}` })
        addToast({ type: 'error', message: `SMS failed: ${err}` })
      }
    } catch (err) {
      setTestSmsMsg({ type: 'error', text: 'Failed: ' + err.message })
      addToast({ type: 'error', message: 'SMS test error: ' + err.message })
    } finally { setTestingSms(false) }
  }

  const isOverride = threshData?.source === 'runtime_override'

  return (
    <>
      <div className="space-y-5 max-w-2xl">

        {/* ── Section 1: Threshold Configuration ─────────────────────────── */}
        <Section title="Threshold Configuration" icon={Settings2}>
          <form onSubmit={handleUpdate} className="space-y-4">
            <div className="flex items-center gap-2 mb-2">
              <Badge
                color={isOverride ? 'orange' : 'green'}
                label={isOverride ? 'Runtime Override Active' : 'Using Defaults'}
                dot={false}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              {/* ── High Threshold ── */}
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1 block">
                  High Threshold (°C) <span className="text-red-400">↑ Overheating danger</span>
                </label>
                <input
                  className="form-input"
                  type="number"
                  step="any"
                  value={high}
                  onChange={e => { setHigh(e.target.value); dirtyRef.current = true }}
                  onFocus={e => { e.target.select(); dirtyRef.current = true }}
                />
              </div>

              {/* ── Low Threshold ── */}
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1 block">
                  Low Threshold (°C) <span className="text-blue-400">↓ Machine ready</span>
                </label>
                <input
                  className="form-input"
                  type="number"
                  step="any"
                  value={low}
                  onChange={e => { setLow(e.target.value); dirtyRef.current = true }}
                  onFocus={e => { e.target.select(); dirtyRef.current = true }}
                />
              </div>
            </div>

            {isOverride && threshData?.last_changed && (
              <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2">
                Changed {utcToIST(threshData.last_changed)}
              </p>
            )}

            <StatusMsg msg={threshMsg} />

            <p className="text-xs text-gray-400">
              Changes take effect immediately. Reset restores 90°C / 38°C defaults.
            </p>

            <div className="flex gap-2">
              <button type="submit" disabled={saving} className="btn btn-primary btn-sm flex-1">
                <Settings2 size={13} /> {saving ? 'Saving…' : 'Update Thresholds'}
              </button>
              <button type="button" onClick={handleReset} disabled={resetting} className="btn btn-ghost btn-sm">
                <RotateCcw size={13} /> {resetting ? 'Resetting…' : 'Reset to Default'}
              </button>
            </div>
          </form>
        </Section>

        {/* ── Section 2: Demo Controls ────────────────────────────────────── */}
        <Section title="Demo Controls" icon={Zap}>
          <div className="space-y-4">

            <div className="rounded-xl bg-blue-50 border border-blue-200 px-4 py-3">
              <p className="text-xs font-semibold text-blue-800 mb-1">📊 Real Client Data Playback</p>
              <p className="text-xs text-blue-700 leading-relaxed">
                Normal mode plays <strong>real machine data</strong> from 9 CSV files at 1 reading/second
                (~2.5 hours for a full cooling cycle, 88°C → 38°C).
                Demo mode compresses this for presentations using the same real data.
              </p>
            </div>

            <div className="rounded-xl bg-orange-50 border border-orange-200 p-4 space-y-3">
              <div>
                <label className="text-xs font-semibold text-orange-800 block mb-2">
                  Demo Speed
                </label>
                <div className="flex gap-2">
                  {SPEED_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setDemoSpeed(opt.value)}
                      className={`flex-1 rounded-lg py-2 px-3 text-xs font-medium border transition-all ${demoSpeed === opt.value
                          ? 'bg-orange-500 text-white border-orange-500'
                          : 'bg-white text-orange-700 border-orange-300 hover:bg-orange-50'
                        }`}
                    >
                      <div className="font-semibold">{opt.label}</div>
                      <div className="opacity-75 mt-0.5">{opt.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-orange-800">Start Demo Cooling Run</p>
                  <p className="text-xs text-orange-600 mt-0.5">
                    Rewinds to first CSV reading and plays at {demoSpeed}x speed.
                    Alert fires when temperature drops to <strong>38°C</strong>.
                  </p>
                </div>
                <button
                  onClick={handleDemoRun}
                  disabled={demoRunning}
                  className="btn btn-sm flex-shrink-0 flex items-center gap-1.5"
                  style={{ background: '#F97316', color: '#fff', border: 'none' }}
                >
                  {demoRunning
                    ? <><RefreshCw size={13} className="animate-spin" /> Starting…</>
                    : '🔬 Start Demo'
                  }
                </button>
              </div>

              <StatusMsg msg={demoStatus} />
            </div>

            <div className="flex items-center gap-4 p-4 rounded-xl bg-gray-50 border border-gray-200">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-700">Reset to Normal</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Stop demo and rewind to first CSV reading at 1 reading/second.
                </p>
              </div>
              <button
                onClick={handleDemoReset}
                disabled={demoResetting}
                className="btn btn-ghost btn-sm flex-shrink-0 flex items-center gap-1.5"
              >
                {demoResetting
                  ? <><RefreshCw size={13} className="animate-spin" /> Resetting…</>
                  : <><RotateCcw size={13} /> Reset Sensor</>
                }
              </button>
            </div>

            <div className="flex items-center gap-4 p-4 rounded-xl bg-red-50 border border-red-200">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-red-700 flex items-center gap-1.5">
                  <AlertTriangle size={13} /> Simulate Breach
                  <span className="text-xs font-normal text-red-400 ml-1">(testing only)</span>
                </p>
                <p className="text-xs text-red-500 mt-0.5">
                  Forces 92°C for 10 readings — triggers the full alert pipeline.
                </p>
              </div>
              <button
                onClick={handleSimulateBreach}
                disabled={simulating}
                className="btn btn-sm flex-shrink-0 flex items-center gap-1.5"
                style={{ background: '#DC2626', color: '#fff', border: 'none' }}
              >
                {simulating
                  ? <><RefreshCw size={13} className="animate-spin" /> Firing…</>
                  : '⚡ Trigger'
                }
              </button>
            </div>

            <div className="flex items-center gap-4 p-4 rounded-xl bg-blue-50 border border-blue-200">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-blue-800">Create Database Backup</p>
                <p className="text-xs text-blue-600 mt-0.5">Snapshot the current database to the backups directory.</p>
              </div>
              <button onClick={handleBackup} disabled={backing}
                className="btn btn-sm flex-shrink-0 flex items-center gap-1.5"
                style={{ background: '#2563EB', color: '#fff', border: 'none' }}
              >
                {backing ? 'Backing up…' : '💾 Backup'}
              </button>
            </div>

          </div>
        </Section>

        {/* ── Section 3: Email Configuration ──────────────────────────── */}
        <Section title="Email Configuration" icon={Mail}>
          <div className="space-y-4">

            <div className="flex items-center justify-between py-2 border-b border-gray-100">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <Mail size={13} />
                <span className="font-medium">SMTP User</span>
              </div>
              <span className="text-xs font-semibold text-gray-700">
                {health?.smtp_user || 'crharya@gmail.com'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-b border-gray-100">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <CheckCircle size={13} />
                <span className="font-medium">Email Status</span>
              </div>
              <span className={`text-xs font-semibold ${String(health?.modules?.email?.status || health?.modules?.email || '') === 'configured'
                  || String(health?.modules?.email?.status || health?.modules?.email || '') === 'ok'
                  ? 'text-emerald-600' : 'text-amber-600'
                }`}>
                {String(health?.modules?.email?.status || health?.modules?.email || '') === 'configured'
                  || String(health?.modules?.email?.status || health?.modules?.email || '') === 'ok'
                  ? '✓ Configured' : '⚠ Not yet verified'}
              </span>
            </div>

            <div className="rounded-xl bg-indigo-50 border border-indigo-200 p-4 space-y-3">
              <p className="text-xs font-semibold text-indigo-800">
                📧 Send Test HTML Email
              </p>
              <p className="text-xs text-indigo-600 leading-relaxed">
                Sends a professional HTML alert email immediately — no breach required.
                Use this to verify the email template renders correctly in Gmail.
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="email"
                  value={testEmailAddr}
                  onChange={e => setTestEmailAddr(e.target.value)}
                  placeholder="recipient@example.com"
                  className="form-input flex-1 text-xs"
                />
                <button
                  onClick={handleTestEmail}
                  disabled={testingEmail || !testEmailAddr.trim()}
                  className="btn btn-sm flex-shrink-0 flex items-center gap-1.5"
                  style={{ background: '#4F46E5', color: '#fff', border: 'none' }}
                >
                  {testingEmail
                    ? <><RefreshCw size={13} className="animate-spin" /> Sending…</>
                    : <><Mail size={13} /> Send Test Email</>
                  }
                </button>
              </div>
              <StatusMsg msg={testEmailMsg} />
            </div>
          </div>
        </Section>

        {/* ── Section 4: SMS Configuration ─────────────────────────────── */}
        <Section title="SMS Configuration" icon={MessageSquare}>
          <div className="space-y-4">

            <div className="flex items-center justify-between py-2 border-b border-gray-100">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <Smartphone size={13} />
                <span className="font-medium">SMS Method</span>
              </div>
              <span className="text-xs font-semibold text-gray-700 uppercase">
                {health?.sms_method || 'adb'}
              </span>
            </div>
            <div className="flex items-center justify-between py-2 border-b border-gray-100">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <CheckCircle size={13} />
                <span className="font-medium">SMS Status</span>
              </div>
              <span className={`text-xs font-semibold ${String(health?.modules?.sms?.status || '').startsWith('ok') ? 'text-emerald-600' :
                  String(health?.modules?.sms?.status || '').startsWith('configured') ? 'text-emerald-600' :
                    String(health?.modules?.sms?.status || '').startsWith('error') ? 'text-red-500' :
                      'text-amber-600'
                }`}>
                {String(health?.modules?.sms?.status || '').startsWith('ok') || String(health?.modules?.sms?.status || '').startsWith('configured')
                  ? `✓ ${health.modules.sms.status ?? health.modules.sms}`
                  : String(health?.modules?.sms?.status || '').startsWith('error')
                    ? `⚠ ${health.modules.sms.status ?? health.modules.sms}`
                    : '⚠ Not yet tested'}
              </span>
            </div>

            {health?.sms_method === 'adb' || !health?.sms_method ? (
              <div className="rounded-xl bg-blue-50 border border-blue-200 px-4 py-3">
                <p className="text-xs font-semibold text-blue-800 mb-1">📱 ADB Mode (USB Android Phone)</p>
                <p className="text-xs text-blue-700 leading-relaxed">
                  Phone must be connected via <strong>USB</strong> with{' '}
                  <strong>USB debugging enabled</strong> in Developer Options.
                  Run <code className="bg-blue-100 px-1 rounded">adb devices</code> to confirm it shows as <em>device</em>.
                </p>
              </div>
            ) : health?.sms_method === 'gammu' ? (
              <div className="rounded-xl bg-purple-50 border border-purple-200 px-4 py-3">
                <p className="text-xs font-semibold text-purple-800 mb-1">📻 Gammu Mode (USB GSM Modem)</p>
                <p className="text-xs text-purple-700 leading-relaxed">
                  USB GSM modem must be connected to port{' '}
                  <code className="bg-purple-100 px-1 rounded">{String(health?.modules?.sms?.status || '').includes('COM') ? health.modules.sms.status : 'COM3'}</code>.
                  Install driver and run: <code className="bg-purple-100 px-1 rounded">pip install python-gammu</code>.
                </p>
              </div>
            ) : (
              <div className="rounded-xl bg-gray-50 border border-gray-200 px-4 py-3">
                <p className="text-xs font-semibold text-gray-700 mb-1">🌐 Gateway Mode (LAN Android App)</p>
                <p className="text-xs text-gray-600 leading-relaxed">
                  Android SMS Gateway app must be running on same Wi-Fi network.
                  Configure <code className="bg-gray-100 px-1 rounded">SMS_GATEWAY_URL</code> in .env.
                </p>
              </div>
            )}

            <div className="rounded-xl bg-green-50 border border-green-200 p-4 space-y-3">
              <p className="text-xs font-semibold text-green-800">
                📱 Send Test SMS
              </p>
              <p className="text-xs text-green-700 leading-relaxed">
                Sends a test SMS immediately using dummy data (37.5°C, below 38°C threshold).
                Routes through <strong>{health?.sms_method || 'adb'}</strong> method.
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="tel"
                  value={testSmsPhone}
                  onChange={e => setTestSmsPhone(e.target.value)}
                  placeholder="Phone number (e.g. 6385936224)"
                  className="form-input flex-1 text-xs"
                />
                <button
                  onClick={handleTestSms}
                  disabled={testingSms || !testSmsPhone.trim()}
                  className="btn btn-sm flex-shrink-0 flex items-center gap-1.5"
                  style={{ background: '#16A34A', color: '#fff', border: 'none' }}
                >
                  {testingSms
                    ? <><RefreshCw size={13} className="animate-spin" /> Sending…</>
                    : <><MessageSquare size={13} /> Send Test SMS</>
                  }
                </button>
              </div>
              <StatusMsg msg={testSmsMsg} />
            </div>
          </div>
        </Section>

        {/* ── Section 5: Add Parameter ──────────────────────────────────────── */}
        <Section title="Add Parameter" icon={PlusCircle}>
          <AddParameterForm onToast={addToast} />
        </Section>

        {/* ── Section 6: Admin Info ───────────────────────────────────────── */}
        <Section title="Admin Info" icon={Info}>
          <div className="space-y-3">
            {[
              { label: 'Dashboard Passcode', value: '••••  (4 digits)', icon: '🔐' },
              { label: 'Server Host', value: window.location.hostname, icon: <Server size={13} /> },
              { label: 'Backend Port', value: '5000 (HTTPS)', icon: '🌐' },
              { label: 'App Version', value: health?.version || 'v1.0.0', icon: '📦' },
              { label: 'Environment', value: health?.environment || 'development', icon: '⚙️' },
              { label: 'Sensor Mode', value: 'CSV Playback (real client data)', icon: '📊' },
            ].map(({ label, value, icon }) => (
              <div key={label} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <span>{icon}</span>
                  <span className="font-medium">{label}</span>
                </div>
                <span className="text-xs font-semibold text-gray-700">{value}</span>
              </div>
            ))}
          </div>
        </Section>

      </div>

      <ToastContainer toasts={toasts} onDismiss={dismiss} />

      <PasswordConfirmModal
        isOpen={!!pwdAction}
        actionLabel={pwdAction === 'update' ? 'update thresholds' : 'reset thresholds to defaults'}
        onConfirm={handlePasswordConfirm}
        onCancel={() => { setPwdAction(null); setPwdError(null) }}
        error={pwdError}
      />
    </>
  )
}