/**
 * src/pages/SettingsPage.jsx
 * Threshold config, demo controls (CSV playback), and admin info.
 */
import { useState, useEffect, useCallback, useRef, memo } from 'react'
import { Settings2, RotateCcw, Database, Info, Server, RefreshCw, Mail, CheckCircle, MessageSquare, Smartphone, PlusCircle, Trash2, Eye, EyeOff, Bell, BellOff } from 'lucide-react'
import {
  fetchThresholds, updateThresholds, resetThresholds,
  createBackup, fetchHealth, fetchAlertSettings, updateAlertSettings,
  fetchOpcSettings, saveOpcSettings, simulatePhBreach,
} from '../services/api.js'
import { utcToIST } from '../utils/time.js'
import Badge from '../components/shared/Badge.jsx'
import { useToast, ToastContainer } from '../components/shared/Toast.jsx'
import PasswordConfirmModal from '../components/PasswordConfirmModal.jsx'

function _bearerHeaders(extra = {}) {
  const token = sessionStorage.getItem('admin_token') || ''
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  }
}

function maskEmail(email) {
  if (!email) return '—'
  const at = email.indexOf('@')
  if (at < 0) return email
  const local = email.slice(0, at)
  const domain = email.slice(at)
  const shown = local.slice(0, Math.min(2, local.length))
  return shown + '•'.repeat(Math.max(3, local.length - shown.length)) + domain
}

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

// ── Add Parameter form — uses native <dialog> with showModal().
// showModal() puts the dialog in the browser top layer and TRAPS FOCUS INSIDE.
// No React re-render (WebSocket ticks, parent state, etc.) can steal focus
// from a native modal dialog — the browser enforces it at the OS level.
const AddParameterForm = memo(function AddParameterForm({ onToast, onAdded }) {
  const dialogRef = useRef(null)
  const nameRef   = useRef(null)
  const unitRef   = useRef(null)
  const minRef    = useRef(null)
  const maxRef    = useRef(null)
  const [paramSubmitting, setParamSubmitting] = useState(false)
  const [paramSaved,      setParamSaved]      = useState(false)

  const openDialog = useCallback(() => {
    dialogRef.current?.showModal()
    setTimeout(() => nameRef.current?.focus(), 30)
  }, [])

  const closeDialog = useCallback(() => {
    dialogRef.current?.close()
  }, [])

  // Close when clicking the backdrop (the dialog element itself, not its children)
  const handleDialogClick = useCallback((e) => {
    if (e.target === dialogRef.current) closeDialog()
  }, [closeDialog])

  async function handleSaveParam() {
    const name = nameRef.current?.value?.trim() || ''
    const unit = unitRef.current?.value?.trim() || ''
    const min  = minRef.current?.value  || ''
    const max  = maxRef.current?.value  || ''
    if (!name || !unit) {
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
          name,
          unit,
          min_value: min !== '' ? Number(min) : null,
          max_value: max !== '' ? Number(max) : null,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.error || `Server error ${res.status}`)
      }
      onToast({ type: 'success', message: `"${name}" submitted for super admin approval.` })
      if (nameRef.current) nameRef.current.value = ''
      if (unitRef.current) unitRef.current.value = ''
      if (minRef.current)  minRef.current.value  = ''
      if (maxRef.current)  maxRef.current.value  = ''
      setParamSaved(true)
      setTimeout(() => setParamSaved(false), 4000)
      onAdded?.()
      closeDialog()
    } catch (err) {
      onToast({ type: 'error', message: err.message || 'Failed to submit parameter.' })
    } finally {
      setParamSubmitting(false)
    }
  }

  return (
    <>
      <p style={{ fontSize: 13, color: '#6B7280', marginBottom: 16, marginTop: -4 }}>
        Define a new sensor metric to monitor. Once approved by the Super Admin it appears as a live card on the Dashboard.
      </p>

      {paramSaved && (
        <p style={{ fontSize: 12, color: '#10B981', fontWeight: 600, marginBottom: 12 }}>
          ✓ Parameter submitted for approval!
        </p>
      )}

      <button
        onClick={openDialog}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          padding: '9px 20px', borderRadius: 8, border: 'none',
          background: '#7C3AED', color: '#fff',
          fontSize: 13, fontWeight: 600, cursor: 'pointer',
        }}
      >
        <PlusCircle size={15} /> Request Parameter
      </button>

      <div style={{
        marginTop: 16, padding: '10px 14px', borderRadius: 8,
        background: '#F0FDF4', border: '1px solid #BBF7D0', fontSize: 12, color: '#065F46',
      }}>
        💡 Submitted parameters go to the Super Admin for approval. Once approved they appear as live sensor cards on the Dashboard.
      </div>

      {/* Native <dialog> — browser top-layer, focus trapped inside by OS */}
      <dialog
        ref={dialogRef}
        onClick={handleDialogClick}
        style={{
          border: 'none', borderRadius: 12, padding: 0,
          boxShadow: '0 20px 60px rgba(0,0,0,0.35)',
          width: '100%', maxWidth: 440,
          background: '#fff',
        }}
      >
        {/* Header */}
        <div style={{ padding: '18px 24px', borderBottom: '1px solid #E5E7EB', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#111827' }}>
              Request New Parameter
            </h3>
            <p style={{ margin: '3px 0 0', fontSize: 12, color: '#6B7280' }}>
              Fill in the details for the new sensor metric.
            </p>
          </div>
          <button
            type="button"
            onClick={closeDialog}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', fontSize: 20, lineHeight: 1, padding: 4 }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px 24px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={{ gridColumn: '1 / -1' }}>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
              Parameter Name
            </label>
            <input
              ref={nameRef}
              className="form-input"
              defaultValue=""
              autoComplete="off"
              placeholder="e.g. pH"
              style={{ caretColor: '#7C3AED' }}
            />
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
              Unit
            </label>
            <input
              ref={unitRef}
              className="form-input"
              defaultValue=""
              autoComplete="off"
              placeholder="e.g. pH, bar, %"
              style={{ caretColor: '#7C3AED' }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
              Min Value <span style={{ fontWeight: 400, color: '#9CA3AF' }}>(optional)</span>
            </label>
            <input
              ref={minRef}
              className="form-input"
              type="number"
              defaultValue=""
              autoComplete="off"
              placeholder="e.g. 6.5"
              style={{ caretColor: '#7C3AED' }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
              Max Value <span style={{ fontWeight: 400, color: '#9CA3AF' }}>(optional)</span>
            </label>
            <input
              ref={maxRef}
              className="form-input"
              type="number"
              defaultValue=""
              autoComplete="off"
              placeholder="e.g. 10.0"
              style={{ caretColor: '#7C3AED' }}
            />
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: '14px 24px', borderTop: '1px solid #E5E7EB', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 10 }}>
          <button
            type="button"
            onClick={closeDialog}
            style={{
              padding: '8px 18px', borderRadius: 8, border: '1px solid #D1D5DB',
              background: '#fff', color: '#374151', fontSize: 13, fontWeight: 500, cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSaveParam}
            disabled={paramSubmitting}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '8px 20px', borderRadius: 8, border: 'none',
              background: paramSubmitting ? '#A78BFA' : '#7C3AED', color: '#fff',
              fontSize: 13, fontWeight: 600,
              cursor: paramSubmitting ? 'not-allowed' : 'pointer',
            }}
          >
            {paramSubmitting
              ? <><RefreshCw size={14} className="animate-spin" /> Submitting…</>
              : <><PlusCircle size={15} /> Submit Parameter</>
            }
          </button>
        </div>
      </dialog>
    </>
  )
})

export default function SettingsPage() {
  const { toasts, addToast, dismiss } = useToast()

  const [threshData, setThreshData] = useState(null)
  const [high, setHigh] = useState(90)
  const [low, setLow] = useState(38)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [threshMsg, setThreshMsg] = useState(null)

  const [emailVisible, setEmailVisible] = useState(false)

  const [alertSettings, setAlertSettings] = useState({
    temp_alerts_enabled: true,
    ph_alerts_enabled:   true,
    ph_threshold_min:    5.5,
    ph_threshold_max:    7.0,
  })
  const [alertSettingsSaving, setAlertSettingsSaving] = useState(false)
  const [alertSettingsMsg,    setAlertSettingsMsg]    = useState(null)
  const [phSimulating,        setPhSimulating]        = useState(false)

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

  const [existingParams, setExistingParams] = useState([])
  const [deletingId, setDeletingId] = useState(null)

  const [psSettings, setPsSettings] = useState({
    file_path: '', temp_col: 'TEMPERATURE', timestamp_col: '', date_col: 'DATE/TIME', time_col: '', auto_save: false,
  })
  const [psSaving,     setPsSaving]     = useState(false)
  const [psTesting,    setPsTesting]    = useState(false)
  const [psMsg,        setPsMsg]        = useState(null)
  const [psTestResult, setPsTestResult] = useState(null)
  const [psEnabled,    setPsEnabled]    = useState(true)
  const [psStatus,     setPsStatus]     = useState(null)  // {enabled, is_active, in_loop_mode}
  const [psDiag,       setPsDiag]       = useState(null)
  const [psDiagLoading, setPsDiagLoading] = useState(false)

  const [opcSettings, setOpcSettings] = useState({
    server_name: '', temp_tag: '', extra_tags: '', poll_interval: 2.0,
  })
  const [opcStatus,  setOpcStatus]  = useState(null)
  const [opcSaving,  setOpcSaving]  = useState(false)
  const [opcMsg,     setOpcMsg]     = useState(null)

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

  const loadParams = useCallback(async () => {
    try {
      const token = sessionStorage.getItem('admin_token')
      if (!token) return
      const res = await fetch('/api/admin/parameters', { headers: { Authorization: `Bearer ${token}` } })
      if (res.ok) setExistingParams(await res.json())
    } catch { /* silent */ }
  }, [])

  const loadOpcSettings = useCallback(async () => {
    try {
      const d = await fetchOpcSettings()
      setOpcSettings({
        server_name:   d.server_name   || '',
        temp_tag:      d.temp_tag      || '',
        extra_tags:    d.extra_tags    || '',
        poll_interval: d.poll_interval ?? 2.0,
      })
      if (d.status) setOpcStatus(d.status)
    } catch { /* silent */ }
  }, [])

  const handleOpcSave = async () => {
    setOpcSaving(true); setOpcMsg(null)
    try {
      const r = await saveOpcSettings(opcSettings)
      const connected = r.connected
      setOpcMsg({
        type: connected ? 'success' : 'info',
        text: connected
          ? '✅ Saved — OPC DA connected and reading.'
          : '✅ Saved — server not yet reachable (check server name and tags).',
      })
      loadOpcSettings()
    } catch (err) {
      setOpcMsg({ type: 'error', text: err.message })
    } finally { setOpcSaving(false) }
  }

  const loadPsSettings = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/proserver/settings', { headers: _bearerHeaders() })
      if (res.ok) {
        const d = await res.json()
        setPsSettings({
          file_path:     d.file_path     || '',
          temp_col:      d.temp_col      || 'TEMPERATURE',
          timestamp_col: d.timestamp_col || '',
          date_col:      d.date_col      || 'DATE/TIME',
          time_col:      d.time_col      || '',
          auto_save:     !!d.auto_save,
        })
      }
    } catch { /* silent */ }
  }, [])

  const loadPsStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/proserver/reading-status', { headers: _bearerHeaders() })
      if (res.ok) {
        const d = await res.json()
        setPsStatus(d)
        setPsEnabled(d.enabled)
      }
    } catch { /* silent */ }
  }, [])

  const handlePsToggle = async (enabled) => {
    setPsEnabled(enabled)
    try {
      await fetch('/api/admin/proserver/reading-enabled', {
        method: 'POST',
        headers: _bearerHeaders(),
        body: JSON.stringify({ enabled }),
      })
      addToast({ type: enabled ? 'success' : 'info', message: enabled ? 'Excel reading enabled' : 'Excel reading disabled — watchdog active' })
      loadPsStatus()
    } catch { /* silent */ }
  }

  const loadAlertSettings = useCallback(async () => {
    try {
      const d = await fetchAlertSettings()
      setAlertSettings({
        temp_alerts_enabled: d.temp_alerts_enabled ?? true,
        ph_alerts_enabled:   d.ph_alerts_enabled   ?? true,
        ph_threshold_min:    d.ph_threshold_min     ?? 5.5,
        ph_threshold_max:    d.ph_threshold_max     ?? 7.0,
      })
    } catch { /* silent */ }
  }, [])

  const handleSaveAlertSettings = async () => {
    setAlertSettingsSaving(true); setAlertSettingsMsg(null)
    try {
      await updateAlertSettings(alertSettings)
      setAlertSettingsMsg({ type: 'success', text: 'Alert settings saved.' })
    } catch (err) {
      setAlertSettingsMsg({ type: 'error', text: err.message })
    } finally { setAlertSettingsSaving(false) }
  }

  useEffect(() => { loadThresholds(); loadHealth(); loadParams(); loadPsSettings(); loadAlertSettings(); loadOpcSettings(); loadPsStatus() }, [loadThresholds, loadHealth, loadParams, loadPsSettings, loadAlertSettings, loadOpcSettings, loadPsStatus])

  // Poll Pro-Server EX status every 5 seconds to show live/loop/watchdog badge
  useEffect(() => {
    const id = setInterval(loadPsStatus, 5000)
    return () => clearInterval(id)
  }, [loadPsStatus])

  const handleDeleteParam = async (param) => {
    if (!window.confirm(`Request deletion of "${param.name}"? Super Admin must approve before it's removed.`)) return
    setDeletingId(param.id)
    try {
      const token = sessionStorage.getItem('admin_token')
      const res = await fetch(`/api/admin/parameters/${param.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        addToast({ type: 'success', message: `Deletion of "${param.name}" submitted for Super Admin approval.` })
      } else {
        addToast({ type: 'error', message: data.error || `Error ${res.status}` })
      }
    } catch (err) {
      addToast({ type: 'error', message: err.message })
    } finally {
      setDeletingId(null)
    }
  }

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
        headers: _bearerHeaders(),
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
        headers: _bearerHeaders(),
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

  const handlePsSave = async () => {
    setPsSaving(true); setPsMsg(null); setPsTestResult(null)
    try {
      const res = await fetch('/api/admin/proserver/settings', {
        method: 'POST',
        headers: _bearerHeaders(),
        body: JSON.stringify({
          file_path:     psSettings.file_path     || '',
          temp_col:      psSettings.temp_col      || 'TEMPERATURE',
          timestamp_col: psSettings.timestamp_col || '',
          date_col:      psSettings.date_col      || 'DATE/TIME',
          time_col:      psSettings.time_col      || '',
          poll_interval: 1.0,
          auto_save:     !!psSettings.auto_save,
        }),
      })
      const data = await res.json()
      if (res.ok) {
        const msg = data.active
          ? '✅ Saved — sensor is now reading the file.'
          : '✅ Saved — file not yet found (check the path).'
        setPsMsg({ type: data.active ? 'success' : 'info', text: msg })
        addToast({ type: 'success', message: 'Pro-Server EX settings saved' })
      } else {
        setPsMsg({ type: 'error', text: data.detail || 'Save failed' })
      }
    } catch (err) {
      setPsMsg({ type: 'error', text: err.message })
    } finally { setPsSaving(false) }
  }

  const handlePsDiagnose = async () => {
    setPsDiagLoading(true); setPsDiag(null)
    try {
      const res = await fetch('/api/admin/proserver/diagnostic', { headers: _bearerHeaders() })
      const data = await res.json()
      setPsDiag(data)
    } catch (err) {
      setPsDiag({ status: 'error', message: err.message })
    } finally { setPsDiagLoading(false) }
  }

  const handlePsTest = async () => {
    if (!psSettings.file_path?.trim()) { setPsMsg({ type: 'error', text: 'Enter a file path first.' }); return }
    setPsTesting(true); setPsMsg(null); setPsTestResult(null)
    try {
      const res = await fetch('/api/admin/proserver/test', {
        method: 'POST',
        headers: _bearerHeaders(),
        body: JSON.stringify({ file_path: psSettings.file_path }),
      })
      const data = await res.json()
      if (data.status === 'ok') {
        setPsTestResult(data)
        setPsMsg({ type: 'success', text: data.message })
      } else {
        setPsMsg({ type: 'error', text: data.message })
      }
    } catch (err) {
      setPsMsg({ type: 'error', text: err.message })
    } finally { setPsTesting(false) }
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

        {/* ── Section 2: Alert Controls ────────────────────────────────────── */}
        <Section title="Alert Controls" icon={Bell}>
          <div className="space-y-4">
            <p className="text-xs text-gray-500 leading-relaxed">
              Disable an alert type to stop notifications (SMS, email, in-app) even if the threshold is breached.
              Sensor readings continue normally — only the alert dispatch is suppressed.
            </p>

            {/* Temperature alert toggle */}
            <div className="flex items-center justify-between py-3 px-4 rounded-xl bg-gray-50 border border-gray-200">
              <div className="flex items-center gap-3">
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${alertSettings.temp_alerts_enabled ? 'bg-orange-100' : 'bg-gray-100'}`}>
                  {alertSettings.temp_alerts_enabled
                    ? <Bell size={15} className="text-orange-600" />
                    : <BellOff size={15} className="text-gray-400" />
                  }
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-800">Temperature Alerts</p>
                  <p className="text-xs text-gray-500">Fire when temp &gt; {threshData?.temperature?.high ?? 90}°C or &lt; {threshData?.temperature?.low ?? 42}°C</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setAlertSettings(s => ({ ...s, temp_alerts_enabled: !s.temp_alerts_enabled }))}
                style={{
                  width: 44, height: 24, borderRadius: 12, border: 'none', cursor: 'pointer',
                  background: alertSettings.temp_alerts_enabled ? '#7C3AED' : '#D1D5DB',
                  position: 'relative', transition: 'background 0.2s',
                }}
              >
                <span style={{
                  position: 'absolute', top: 3,
                  left: alertSettings.temp_alerts_enabled ? 23 : 3,
                  width: 18, height: 18, borderRadius: '50%', background: '#fff',
                  transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                }} />
              </button>
            </div>

            {/* pH alert toggle */}
            <div className="flex items-center justify-between py-3 px-4 rounded-xl bg-gray-50 border border-gray-200">
              <div className="flex items-center gap-3">
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${alertSettings.ph_alerts_enabled ? 'bg-blue-100' : 'bg-gray-100'}`}>
                  {alertSettings.ph_alerts_enabled
                    ? <Bell size={15} className="text-blue-600" />
                    : <BellOff size={15} className="text-gray-400" />
                  }
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-800">pH Alerts</p>
                  <p className="text-xs text-gray-500">Fire when pH &lt; {alertSettings.ph_threshold_min} or pH &gt; {alertSettings.ph_threshold_max}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setAlertSettings(s => ({ ...s, ph_alerts_enabled: !s.ph_alerts_enabled }))}
                style={{
                  width: 44, height: 24, borderRadius: 12, border: 'none', cursor: 'pointer',
                  background: alertSettings.ph_alerts_enabled ? '#7C3AED' : '#D1D5DB',
                  position: 'relative', transition: 'background 0.2s',
                }}
              >
                <span style={{
                  position: 'absolute', top: 3,
                  left: alertSettings.ph_alerts_enabled ? 23 : 3,
                  width: 18, height: 18, borderRadius: '50%', background: '#fff',
                  transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                }} />
              </button>
            </div>

            {/* pH threshold range */}
            <div className="rounded-xl bg-blue-50 border border-blue-200 p-4 space-y-3">
              <p className="text-xs font-semibold text-blue-800">pH Alert Range</p>
              <p className="text-xs text-blue-600 leading-relaxed">
                Alert fires when pH drops <strong>below Minimum</strong> or rises <strong>above Maximum</strong>.
                Normal range is highlighted between the two thresholds.
              </p>
              <div className="flex items-center gap-4 flex-wrap">
                <div className="flex flex-col gap-1">
                  <label className="text-xs font-medium text-blue-700">Minimum pH</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="14"
                      value={alertSettings.ph_threshold_min}
                      onChange={e => setAlertSettings(s => ({ ...s, ph_threshold_min: parseFloat(e.target.value) || 5.5 }))}
                      className="form-input text-xs"
                      style={{ width: 90 }}
                    />
                    <span className="text-xs text-blue-500">pH</span>
                  </div>
                  <span className="text-xs text-blue-400">Default: 5.5</span>
                </div>
                <div style={{ fontSize: 18, color: '#93C5FD', alignSelf: 'center', marginTop: 4 }}>→</div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs font-medium text-blue-700">Maximum pH</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="14"
                      value={alertSettings.ph_threshold_max}
                      onChange={e => setAlertSettings(s => ({ ...s, ph_threshold_max: parseFloat(e.target.value) || 7.0 }))}
                      className="form-input text-xs"
                      style={{ width: 90 }}
                    />
                    <span className="text-xs text-blue-500">pH</span>
                  </div>
                  <span className="text-xs text-blue-400">Default: 7.0</span>
                </div>
              </div>
              <p className="text-xs text-blue-500">
                Safe zone: <strong>{alertSettings.ph_threshold_min} – {alertSettings.ph_threshold_max} pH</strong>
              </p>
            </div>

            <StatusMsg msg={alertSettingsMsg} />

            <div className="flex gap-2 flex-wrap">
              <button
                onClick={handleSaveAlertSettings}
                disabled={alertSettingsSaving}
                className="btn btn-primary btn-sm"
              >
                <Settings2 size={13} /> {alertSettingsSaving ? 'Saving…' : 'Save Alert Settings'}
              </button>
              <button
                onClick={async () => {
                  setPhSimulating(true)
                  try {
                    const r = await simulatePhBreach()
                    addToast({ type: r.breaches_fired > 0 ? 'success' : 'warning',
                      message: r.breaches_fired > 0
                        ? `✅ pH ${r.ph_value} injected — alert fired, notifications sent`
                        : `⚠ pH ${r.ph_value} injected but no breach (check threshold & ph_alerts_enabled)` })
                  } catch (err) {
                    addToast({ type: 'error', message: 'pH simulate failed: ' + err.message })
                  } finally { setPhSimulating(false) }
                }}
                disabled={phSimulating}
                className="btn btn-sm"
                style={{ background: '#0891B2', color: '#fff', border: 'none' }}
              >
                {phSimulating
                  ? <><RefreshCw size={13} className="animate-spin" /> Testing…</>
                  : '🧪 Simulate pH=7.5555'
                }
              </button>
            </div>
          </div>
        </Section>

        {/* ── Section 3: Database Backup ──────────────────────────────────── */}
        <Section title="Database Backup" icon={RotateCcw}>
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
        </Section>

        {/* ── Section 3: Email Configuration ──────────────────────────── */}
        <Section title="Email Configuration" icon={Mail}>
          <div className="space-y-4">

            {/* SMTP credentials (masked) */}
            <div className="rounded-xl bg-gray-50 border border-gray-200 divide-y divide-gray-100">
              <div className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <Mail size={13} />
                  <span className="font-medium">Sender Email</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-gray-700 font-mono">
                    {emailVisible
                      ? (health?.smtp_user || 'crharya@gmail.com')
                      : maskEmail(health?.smtp_user || 'crharya@gmail.com')
                    }
                  </span>
                  <button
                    type="button"
                    onClick={() => setEmailVisible(v => !v)}
                    className="text-gray-400 hover:text-gray-600 transition-colors"
                    title={emailVisible ? 'Hide' : 'Show'}
                  >
                    {emailVisible ? <EyeOff size={13} /> : <Eye size={13} />}
                  </button>
                </div>
              </div>
              <div className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <CheckCircle size={13} />
                  <span className="font-medium">App Password</span>
                </div>
                <span className="text-xs font-semibold text-gray-700 font-mono tracking-wider">••••••••••••</span>
              </div>
              <div className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <CheckCircle size={13} />
                  <span className="font-medium">Email Status</span>
                </div>
                <span className={`text-xs font-semibold ${
                  String(health?.modules?.email?.status || health?.modules?.email || '') === 'configured'
                  || String(health?.modules?.email?.status || health?.modules?.email || '') === 'ok'
                    ? 'text-emerald-600' : 'text-amber-600'
                }`}>
                  {String(health?.modules?.email?.status || health?.modules?.email || '') === 'configured'
                   || String(health?.modules?.email?.status || health?.modules?.email || '') === 'ok'
                    ? '✓ Configured' : '⚠ Not yet verified'}
                </span>
              </div>
            </div>

            {/* How to get Gmail App Password */}
            <div className="rounded-xl bg-indigo-50 border border-indigo-200 p-4 space-y-2">
              <p className="text-xs font-semibold text-indigo-800">How to update credentials (Gmail App Password)</p>
              <ol className="text-xs text-indigo-700 leading-relaxed space-y-1 list-decimal list-inside">
                <li>Go to <strong>myaccount.google.com → Security → 2-Step Verification</strong></li>
                <li>Scroll to the bottom — click <strong>App passwords</strong></li>
                <li>Choose app: <em>Mail</em>, device: <em>Windows Computer</em> → <strong>Generate</strong></li>
                <li>Copy the 16-character key shown (no spaces)</li>
                <li>Open <code className="bg-indigo-100 px-1 rounded">.env</code> on the server and update:<br />
                  <code className="bg-indigo-100 px-1 rounded">SMTP_USER=your@gmail.com</code><br />
                  <code className="bg-indigo-100 px-1 rounded">SMTP_PASSWORD=xxxx xxxx xxxx xxxx</code>
                </li>
                <li>Restart the server for changes to take effect</li>
              </ol>
            </div>

            {/* Test email */}
            <div className="rounded-xl bg-indigo-50 border border-indigo-200 p-4 space-y-3">
              <p className="text-xs font-semibold text-indigo-800">📧 Send Test Email</p>
              <p className="text-xs text-indigo-600 leading-relaxed">
                Sends a test alert email immediately — no breach required.
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
                    : <><Mail size={13} /> Send Test</>
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

            {/* GSM modem status */}
            {(() => {
              const smsStatus = String(health?.modules?.sms?.status || '')
              const connected = smsStatus.startsWith('ok') || smsStatus.startsWith('configured')
              const hasError  = smsStatus.startsWith('error')
              return (
                <div className={`rounded-xl px-4 py-3 border ${
                  connected ? 'bg-emerald-50 border-emerald-200' :
                  hasError  ? 'bg-red-50 border-red-200' :
                              'bg-amber-50 border-amber-200'
                }`}>
                  <div className="flex items-center gap-2 mb-1">
                    <Smartphone size={14} className={connected ? 'text-emerald-600' : hasError ? 'text-red-500' : 'text-amber-500'} />
                    <p className={`text-xs font-semibold ${connected ? 'text-emerald-800' : hasError ? 'text-red-700' : 'text-amber-700'}`}>
                      GSM Modem — {connected ? 'Connected' : hasError ? 'Error' : 'Not Connected'}
                    </p>
                  </div>
                  <p className={`text-xs leading-relaxed ${connected ? 'text-emerald-700' : hasError ? 'text-red-600' : 'text-amber-700'}`}>
                    {connected
                      ? 'USB GSM modem is connected and ready. SMS alerts will be sent automatically on breach.'
                      : hasError
                      ? `Modem error: ${smsStatus}. Check USB connection and driver.`
                      : 'GSM modem not detected. Plug in the USB GSM modem — SMS alerts will activate automatically once connected.'
                    }
                  </p>
                </div>
              )
            })()}

            <div className="rounded-xl bg-gray-50 border border-gray-200 px-4 py-3">
              <p className="text-xs font-semibold text-gray-700 mb-1">How it works</p>
              <p className="text-xs text-gray-600 leading-relaxed">
                The system uses a <strong>USB GSM modem</strong> to send SMS alerts.
                No configuration needed — plug in the modem and it works.
                If the modem is not connected, SMS alerts will be skipped.
              </p>
            </div>

            {/* Test SMS */}
            <div className="rounded-xl bg-green-50 border border-green-200 p-4 space-y-3">
              <p className="text-xs font-semibold text-green-800">📱 Send Test SMS</p>
              <p className="text-xs text-green-700 leading-relaxed">
                Sends a test SMS immediately via the GSM modem.
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
                    : <><MessageSquare size={13} /> Send Test</>
                  }
                </button>
              </div>
              <StatusMsg msg={testSmsMsg} />
            </div>
          </div>
        </Section>

        {/* ── Section 5: Manage Parameters ──────────────────────────────────── */}
        <Section title="Manage Parameters" icon={Database}>
          {existingParams.length === 0 ? (
            <p style={{ fontSize: 13, color: '#9CA3AF' }}>No custom parameters added yet.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {existingParams.map(p => (
                <div key={p.id} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 14px', borderRadius: 8, background: '#F9FAFB',
                  border: '1px solid #E5E7EB',
                }}>
                  <div>
                    <span style={{ fontSize: 13, fontWeight: 600, color: '#111827' }}>{p.name}</span>
                    <span style={{ fontSize: 12, color: '#6B7280', marginLeft: 8 }}>{p.unit || ''}</span>
                    {(p.min_value != null || p.max_value != null) && (
                      <span style={{ fontSize: 11, color: '#9CA3AF', marginLeft: 8 }}>
                        ({p.min_value ?? '—'} – {p.max_value ?? '—'})
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => handleDeleteParam(p)}
                    disabled={deletingId === p.id}
                    title="Request deletion (needs Super Admin approval)"
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4,
                      padding: '5px 12px', borderRadius: 6, border: '1px solid #FCA5A5',
                      background: '#FEF2F2', color: '#DC2626',
                      fontSize: 12, fontWeight: 500, cursor: deletingId === p.id ? 'not-allowed' : 'pointer',
                      opacity: deletingId === p.id ? 0.6 : 1,
                    }}
                  >
                    <Trash2 size={12} />
                    {deletingId === p.id ? 'Requesting…' : 'Delete'}
                  </button>
                </div>
              ))}
            </div>
          )}
          <p style={{ fontSize: 11, color: '#9CA3AF', marginTop: 12 }}>
            Deletion requests go to Super Admin for approval before the parameter is removed.
          </p>
        </Section>

        {/* ── Section 6: Add Parameter ──────────────────────────────────────── */}
        <Section title="Add Parameter" icon={PlusCircle}>
          <AddParameterForm onToast={addToast} onAdded={loadParams} />
        </Section>

        {/* ── Section 7: Pro-Server EX Data Source ──────────────────────────── */}
        <Section title="Pro-Server EX Data Source" icon={Server}>
          <div className="space-y-4">
            <p className="text-xs text-gray-500 leading-relaxed">
              Point to the file Pro-face Pro-Server EX writes to. The server will
              read the latest row in real time and push it to the dashboard.
              Supports <strong>.csv</strong> and <strong>.xlsx</strong> files.
            </p>

            {/* ── Live-Only toggle ── */}
            <div className="flex items-center justify-between rounded-xl border p-3"
              style={{ borderColor: psEnabled ? '#C4B5FD' : '#10B981', background: psEnabled ? '#F5F3FF' : '#F0FDF4' }}>
              <div>
                <p className="text-sm font-semibold text-gray-800">
                  {psEnabled ? 'Loop Mode (default)' : 'Live-Only Mode'}
                </p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {psEnabled
                    ? 'Shows historical rows while waiting for live data'
                    : 'Shows — until Pro-Server EX writes a new row, then shows live. No looping.'}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {/* Status badge */}
                {psStatus && (
                  <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{
                    background: !psStatus.is_active ? '#F3F4F6'
                      : !psStatus.enabled ? (psStatus.in_loop_mode ? '#FEF3C7' : '#D1FAE5')
                      : psStatus.in_loop_mode ? '#EDE9FE'
                      : '#D1FAE5',
                    color: !psStatus.is_active ? '#6B7280'
                      : !psStatus.enabled ? (psStatus.in_loop_mode ? '#92400E' : '#065F46')
                      : psStatus.in_loop_mode ? '#5B21B6'
                      : '#065F46',
                  }}>
                    {!psStatus.is_active ? 'INACTIVE'
                      : !psStatus.enabled
                        ? (psStatus.in_loop_mode ? '○ WAITING' : '● LIVE')
                        : psStatus.in_loop_mode ? '↻ LOOPING'
                        : '● LIVE'}
                  </span>
                )}
                {/* Toggle */}
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-gray-500">Loop</span>
                  <button
                    onClick={() => handlePsToggle(!psEnabled)}
                    style={{
                      width: 44, height: 24, borderRadius: 99,
                      background: psEnabled ? '#D1D5DB' : '#10B981',
                      border: 'none', cursor: 'pointer', position: 'relative',
                      transition: 'background 0.2s',
                    }}
                  >
                    <span style={{
                      position: 'absolute', top: 3,
                      left: psEnabled ? 3 : 23,
                      width: 18, height: 18, borderRadius: '50%',
                      background: '#fff', transition: 'left 0.2s',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                    }} />
                  </button>
                  <span className="text-xs text-gray-500">Live-Only</span>
                </div>
              </div>
            </div>

            {!psEnabled && (
              <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-3 flex gap-2 items-start">
                <span style={{ fontSize: 15 }}>⚡</span>
                <p className="text-xs text-emerald-800 leading-relaxed">
                  <strong>Live-Only mode active</strong> — saved and survives server restarts.
                  Dashboard shows <strong>—</strong> when Pro-Server EX is not writing.
                  The moment a new row appears with a current timestamp, it reads and displays instantly.
                  When writing stops, values return to <strong>—</strong> automatically. No old data is shown. Alerts fire only for live readings.
                </p>
              </div>
            )}

            {/* ── Auto-Save toggle ── */}
            <div className="flex items-center justify-between rounded-xl border p-3"
              style={{ borderColor: psSettings.auto_save ? '#2563EB' : '#D1D5DB', background: psSettings.auto_save ? '#EFF6FF' : '#F9FAFB' }}>
              <div>
                <p className="text-sm font-semibold text-gray-800">Auto-Save File</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {psSettings.auto_save
                    ? 'Saves the Excel file to disk every 5 s via COM so new rows are always readable'
                    : 'Pro-Server EX controls when the file is saved to disk'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPsSettings(s => ({ ...s, auto_save: !s.auto_save }))}
                  style={{
                    width: 44, height: 24, borderRadius: 99,
                    background: psSettings.auto_save ? '#2563EB' : '#D1D5DB',
                    border: 'none', cursor: 'pointer', position: 'relative',
                    transition: 'background 0.2s',
                  }}
                >
                  <span style={{
                    position: 'absolute', top: 3,
                    left: psSettings.auto_save ? 23 : 3,
                    width: 18, height: 18, borderRadius: '50%',
                    background: '#fff', transition: 'left 0.2s',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }} />
                </button>
                {psSettings.auto_save && (
                  <span className="text-xs font-semibold text-blue-600">every 5 s</span>
                )}
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 mb-1 block">
                File Path <span className="text-gray-400 font-normal">(full path to the file on the server)</span>
              </label>
              <input
                type="text"
                className="form-input font-mono text-xs"
                placeholder="C:\ProServer\data\readings.csv"
                value={psSettings.file_path}
                onChange={e => setPsSettings(s => ({ ...s, file_path: e.target.value }))}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1 block">Temperature Column</label>
                <input
                  type="text"
                  className="form-input text-xs"
                  placeholder="TEMPERATURE"
                  value={psSettings.temp_col}
                  onChange={e => setPsSettings(s => ({ ...s, temp_col: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1 block">
                  Timestamp Column <span className="text-gray-400 font-normal">(if date+time combined)</span>
                </label>
                <input
                  type="text"
                  className="form-input text-xs"
                  placeholder="DATE/TIME"
                  value={psSettings.timestamp_col}
                  onChange={e => setPsSettings(s => ({ ...s, timestamp_col: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1 block">
                  Date Column <span className="text-gray-400 font-normal">(if separate)</span>
                </label>
                <input
                  type="text"
                  className="form-input text-xs"
                  placeholder="Date"
                  value={psSettings.date_col}
                  onChange={e => setPsSettings(s => ({ ...s, date_col: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1 block">
                  Time Column <span className="text-gray-400 font-normal">(if separate)</span>
                </label>
                <input
                  type="text"
                  className="form-input text-xs"
                  placeholder="Time"
                  value={psSettings.time_col}
                  onChange={e => setPsSettings(s => ({ ...s, time_col: e.target.value }))}
                />
              </div>
            </div>

            {psTestResult && (
              <div className="text-xs bg-blue-50 rounded-lg p-3 space-y-2">
                <div>
                  <span className="font-semibold text-blue-700">Columns detected: </span>
                  <span className="text-blue-600">{psTestResult.columns?.join(', ')}</span>
                </div>
                <div>
                  <p className="font-semibold text-blue-700 mb-1">Latest values:</p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                    {Object.entries(psTestResult.latest_row || {}).map(([k, v]) => (
                      <p key={k} className="text-blue-600">
                        <span className="font-medium">{k}:</span> {v}
                      </p>
                    ))}
                  </div>
                </div>
              </div>
            )}

            <StatusMsg msg={psMsg} />

            <div className="flex items-center gap-2">
              <button
                onClick={handlePsTest}
                disabled={psTesting || !psSettings.file_path?.trim()}
                className="btn btn-sm flex items-center gap-1.5"
                style={{ background: '#2563EB', color: '#fff', border: 'none' }}
              >
                {psTesting
                  ? <><RefreshCw size={13} className="animate-spin" /> Testing…</>
                  : <><CheckCircle size={13} /> Test File</>
                }
              </button>
              <button
                onClick={handlePsSave}
                disabled={psSaving}
                className="btn btn-sm flex items-center gap-1.5"
                style={{ background: '#7C3AED', color: '#fff', border: 'none' }}
              >
                {psSaving
                  ? <><RefreshCw size={13} className="animate-spin" /> Saving…</>
                  : 'Save Settings'
                }
              </button>
              <button
                onClick={handlePsDiagnose}
                disabled={psDiagLoading}
                className="btn btn-sm flex items-center gap-1.5"
                style={{ background: '#0F766E', color: '#fff', border: 'none' }}
              >
                {psDiagLoading
                  ? <><RefreshCw size={13} className="animate-spin" /> Diagnosing…</>
                  : '🔍 Diagnose'
                }
              </button>
            </div>

            {/* ── Diagnostic result panel ── */}
            {psDiag && (() => {
              const ok = psDiag.status === 'ok'
              const bg = ok ? '#F0FDF4' : '#FFF7ED'
              const border = ok ? '#BBF7D0' : '#FED7AA'
              const titleColor = ok ? '#065F46' : '#92400E'
              return (
                <div className="rounded-xl border p-3 text-xs space-y-2" style={{ background: bg, borderColor: border }}>
                  <p className="font-bold" style={{ color: titleColor }}>
                    {ok ? '✅ Diagnostic OK' : `⚠️ Issue: ${psDiag.status?.replace(/_/g, ' ')}`}
                  </p>
                  {psDiag.message && <p style={{ color: titleColor }}>{psDiag.message}</p>}
                  {ok && (
                    <>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1" style={{ color: '#1F2937' }}>
                        <p><span className="font-medium">File:</span> {psDiag.file_path}</p>
                        <p><span className="font-medium">Active:</span> {psDiag.is_active ? 'Yes' : 'No'}</p>
                        <p><span className="font-medium">Mode:</span> {psDiag.in_loop_mode ? '↻ Looping' : '● Live'}</p>
                        <p><span className="font-medium">Temp column setting:</span> {psDiag.configured_temp_col}</p>
                        <p><span className="font-medium">Matched column:</span> {psDiag.temp_col_matched ?? <span className="text-red-600 font-semibold">NOT FOUND</span>}</p>
                        <p><span className="font-medium">Raw value:</span> {psDiag.temp_raw_value ?? '—'}</p>
                        <p><span className="font-medium">Parsed °C:</span> {psDiag.temp_float != null ? psDiag.temp_float : <span className="text-red-600">null (parse failed)</span>}</p>
                        <p><span className="font-medium">Live reading:</span> {psDiag.current_temperature ?? '—'}</p>
                      </div>
                      <div>
                        <p className="font-medium mb-1" style={{ color: '#374151' }}>Columns in file:</p>
                        <p style={{ color: '#6B7280' }}>{psDiag.columns_in_file?.join(', ')}</p>
                      </div>
                      {psDiag.last_row_preview && (
                        <div>
                          <p className="font-medium mb-1" style={{ color: '#374151' }}>Last row preview:</p>
                          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5" style={{ color: '#6B7280' }}>
                            {Object.entries(psDiag.last_row_preview).map(([k, v]) => (
                              <p key={k}><span className="font-medium">{k}:</span> {v}</p>
                            ))}
                          </div>
                        </div>
                      )}
                      {!psDiag.temp_col_matched && (
                        <div className="rounded-lg p-2 mt-1" style={{ background: '#FEF2F2', border: '1px solid #FCA5A5' }}>
                          <p className="font-semibold text-red-700">Column not matched!</p>
                          <p className="text-red-600 mt-0.5">
                            Your Temperature Column setting is <strong>"{psDiag.configured_temp_col}"</strong> but the
                            file has: <strong>{psDiag.columns_in_file?.join(', ')}</strong>.<br/>
                            Update the Temperature Column to exactly match one of the file's columns.
                          </p>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )
            })()}
          </div>
        </Section>

        {/* ── Section 8: OPC DA Secondary Sensor ────────────────────────────── */}
        <Section title="OPC DA (Secondary Sensor)" icon={Server}>
          <div className="space-y-4">
            <div className="rounded-xl bg-amber-50 border border-amber-200 p-3 flex gap-2 items-start">
              <span style={{ fontSize: 16, marginTop: 1 }}>🧪</span>
              <p className="text-xs text-amber-800 leading-relaxed">
                <strong>Secondary / Experimental.</strong> OPC DA reads directly from Pro-Server EX's built-in OPC server —
                no file needed. It activates automatically when the Excel file reader is not running.
                Requires <code className="bg-amber-100 px-1 rounded">OpenOPC-Python3</code> or <code className="bg-amber-100 px-1 rounded">pywin32</code> installed on the server.
              </p>
            </div>

            {/* Connection status pill */}
            {opcStatus && (
              <div className={`rounded-xl px-4 py-3 border flex items-center gap-3 ${
                opcStatus.active  ? 'bg-emerald-50 border-emerald-200' :
                opcStatus.connected ? 'bg-blue-50 border-blue-200' :
                                     'bg-gray-50 border-gray-200'
              }`}>
                <span style={{ fontSize: 18 }}>{opcStatus.active ? '🟢' : opcStatus.connected ? '🔵' : '⚪'}</span>
                <div className="flex-1 min-w-0">
                  <p className={`text-xs font-semibold ${opcStatus.active ? 'text-emerald-800' : 'text-gray-700'}`}>
                    {opcStatus.active ? 'Connected & Active' : opcStatus.connected ? 'Connected (no data yet)' : 'Not connected'}
                  </p>
                  {opcStatus.last_error && (
                    <p className="text-xs text-red-600 mt-0.5 truncate">{opcStatus.last_error}</p>
                  )}
                </div>
              </div>
            )}

            <div>
              <label className="text-xs font-medium text-gray-600 mb-1 block">
                OPC Server Name <span className="text-gray-400 font-normal">(ProgID from Pro-Server EX)</span>
              </label>
              <input
                type="text"
                className="form-input font-mono text-xs"
                placeholder="e.g. Pro-face.ProServer"
                value={opcSettings.server_name}
                onChange={e => setOpcSettings(s => ({ ...s, server_name: e.target.value }))}
              />
              <p className="text-xs text-gray-400 mt-1">
                Open Pro-Server EX → Tools → OPC Server Settings to find the exact ProgID.
              </p>
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 mb-1 block">Temperature Tag</label>
              <input
                type="text"
                className="form-input font-mono text-xs"
                placeholder="e.g. Device1.Temperature"
                value={opcSettings.temp_tag}
                onChange={e => setOpcSettings(s => ({ ...s, temp_tag: e.target.value }))}
              />
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 mb-1 block">
                Extra Tags <span className="text-gray-400 font-normal">(Label:TagPath, comma-separated)</span>
              </label>
              <input
                type="text"
                className="form-input font-mono text-xs"
                placeholder="e.g. pH:Device1.pH,DO:Device1.DO"
                value={opcSettings.extra_tags}
                onChange={e => setOpcSettings(s => ({ ...s, extra_tags: e.target.value }))}
              />
            </div>

            <div style={{ maxWidth: 160 }}>
              <label className="text-xs font-medium text-gray-600 mb-1 block">Poll Interval (seconds)</label>
              <input
                type="number"
                className="form-input text-xs"
                step="0.5"
                min="0.5"
                max="60"
                value={opcSettings.poll_interval}
                onChange={e => setOpcSettings(s => ({ ...s, poll_interval: parseFloat(e.target.value) || 2.0 }))}
              />
            </div>

            <div className="rounded-xl bg-blue-50 border border-blue-200 p-3 space-y-1">
              <p className="text-xs font-semibold text-blue-800">Installation (one-time, on the server PC)</p>
              <p className="text-xs text-blue-700 font-mono bg-blue-100 rounded px-2 py-1">pip install OpenOPC-Python3</p>
              <p className="text-xs text-blue-600">If that fails, install pywin32 + Graybox OPC DA Automation 2.02 instead.</p>
            </div>

            <StatusMsg msg={opcMsg} />

            <button
              onClick={handleOpcSave}
              disabled={opcSaving}
              className="btn btn-sm flex items-center gap-1.5"
              style={{ background: '#7C3AED', color: '#fff', border: 'none' }}
            >
              {opcSaving
                ? <><RefreshCw size={13} className="animate-spin" /> Saving…</>
                : 'Save OPC Settings'
              }
            </button>
          </div>
        </Section>

        {/* ── Section 9: Admin Info ───────────────────────────────────────── */}
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