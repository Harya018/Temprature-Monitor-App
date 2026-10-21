/**
 * src/pages/SettingsPage.jsx
 * Threshold config, demo controls (CSV playback), and admin info.
 */
import { useState, useEffect, useCallback, useRef, memo } from 'react'
import { Settings2, RotateCcw, Database, Info, Server, RefreshCw, Mail, CheckCircle, MessageSquare, Smartphone, PlusCircle, Trash2, Eye, EyeOff, Bell, BellOff, Building2 } from 'lucide-react'
import useAdminIdentity, { refreshAdminIdentity } from '../hooks/useAdminIdentity.js'
import useCompanyParameters from '../hooks/useCompanyParameters.js'
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

function timeSince(isoStr) {
  if (!isoStr) return null
  try {
    const secs = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000)
    if (secs < 5)  return 'just now'
    if (secs < 60) return `${secs}s ago`
    const mins = Math.floor(secs / 60)
    if (mins < 60) return `${mins}m ago`
    return `${Math.floor(mins / 60)}h ago`
  } catch { return null }
}

/* On/off switch used by the two live-source panels */
function SwitchBtn({ on, onClick, disabled }) {
  return (
    <button
      type="button" onClick={onClick} disabled={disabled}
      aria-pressed={on} title={on ? 'Switch off' : 'Switch on'}
      style={{
        width: 44, height: 24, borderRadius: 99, border: 'none', position: 'relative', flexShrink: 0,
        background: on ? '#10B981' : '#D1D5DB', cursor: disabled ? 'wait' : 'pointer',
        opacity: disabled ? 0.6 : 1, transition: 'background 0.2s',
      }}
    >
      <span style={{
        position: 'absolute', top: 3, left: on ? 23 : 3, width: 18, height: 18, borderRadius: '50%',
        background: '#fff', transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      }} />
    </button>
  )
}

/* Requests this company sent to the Super Admin, with their outcome. */
const REQ_STATUS = {
  pending:  { bg: '#FFFBEB', fg: '#92400E', label: 'Pending'  },
  approved: { bg: '#ECFDF5', fg: '#065F46', label: 'Approved' },
  rejected: { bg: '#FEF2F2', fg: '#991B1B', label: 'Rejected' },
}

function ApprovalRequests({ refreshKey }) {
  const [rows, setRows] = useState(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/approvals', { headers: _bearerHeaders() })
      setRows(res.ok ? await res.json() : [])
    } catch { setRows([]) }
  }, [])

  useEffect(() => { load() }, [load, refreshKey])
  useEffect(() => { const t = setInterval(load, 30000); return () => clearInterval(t) }, [load])

  if (!rows || rows.length === 0) return null
  return (
    <div style={{ marginTop: 16 }}>
      <p style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 8 }}>Requests to Super Admin</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {rows.slice(0, 10).map(r => {
          const st = REQ_STATUS[r.status] || REQ_STATUS.pending
          const what = r.action_type === 'delete_parameter' ? 'Delete' : 'Add'
          return (
            <div key={r.id} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
              borderRadius: 8, border: '1px solid #E5E7EB', fontSize: 12,
            }}>
              <span style={{ background: st.bg, color: st.fg, fontWeight: 600, borderRadius: 999, padding: '2px 8px', flexShrink: 0 }}>
                {st.label}
              </span>
              <span style={{ color: '#111827', fontWeight: 500 }}>{what} parameter “{r.parameter_name || '—'}”</span>
              <span style={{ color: '#9CA3AF', marginLeft: 'auto', textAlign: 'right' }}>
                {r.status === 'pending'
                  ? `requested ${timeSince(r.created_at) || ''}`
                  : `${r.reviewed_by ? `by ${r.reviewed_by} ` : ''}${timeSince(r.reviewed_at) || ''}`}
                {r.review_note ? ` — “${r.review_note}”` : ''}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Section({ title, icon: Icon, children }) {
  const me = useAdminIdentity()
  const readOnly = me?.role === 'sub'          // a sub-admin can look, not change
  return (
    <div className="card">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-100">
        <div className="w-8 h-8 rounded-lg bg-purple-100 flex items-center justify-center">
          <Icon size={15} className="text-purple-600" />
        </div>
        <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
        {readOnly && <span className="ml-auto text-[11px] font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">Read-only</span>}
      </div>
      <fieldset disabled={readOnly} className="p-5" style={{ border: 0, margin: 0, minWidth: 0 }}>{children}</fieldset>
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

/**
 * Parameter limits & alerts — one row per parameter THIS company has (temperature, pH,
 * pressure, …). Nothing is shown for parameters the company does not have.
 */
function ParameterLimitsSection({ params, onSaved, addToast }) {
  const [edit, setEdit] = useState({})
  const [saving, setSaving] = useState(null)
  const [testing, setTesting] = useState(null)

  const sendTest = async (p) => {
    if (!window.confirm(`Send a TEST alert for ${p.name}?\n\nThis is a REAL alert: it is saved, shown on the dashboard and sent by SMS / e-mail / app to your company's subscribers.`)) return
    setTesting(p.id)
    try {
      const res = await fetch(`/api/admin/parameters/${p.id}/test-alert`, { method: 'POST', headers: _bearerHeaders() })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.error || d.detail || `Error ${res.status}`)
      addToast({ type: 'success', message: `Test alert #${d.alert_id} sent: ${d.parameter} ${d.value} (${d.direction} limit ${d.limit}) — ${d.subscribers} subscriber(s) notified` })
    } catch (err) {
      addToast({ type: 'error', message: err.message })
    } finally { setTesting(null) }
  }

  useEffect(() => {
    const e = {}
    for (const p of params) {
      e[p.id] = { min: p.min_value ?? '', max: p.max_value ?? '', on: p.alerts_enabled !== false }
    }
    setEdit(e)
  }, [params])

  const save = async (p) => {
    const v = edit[p.id] || {}
    const min = v.min === '' ? null : Number(v.min)
    const max = v.max === '' ? null : Number(v.max)
    if (min != null && max != null && min >= max) {
      addToast({ type: 'error', message: `${p.name}: minimum must be lower than maximum` }); return
    }
    setSaving(p.id)
    try {
      const res = await fetch(`/api/admin/parameters/${p.id}/limits`, {
        method: 'PUT', headers: _bearerHeaders(),
        body: JSON.stringify({ min_value: min, max_value: max, alerts_enabled: !!v.on }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.error || d.detail || `Error ${res.status}`)
      addToast({ type: 'success', message: `${p.name}: saved (${min ?? '—'} – ${max ?? '—'}, alerts ${v.on ? 'on' : 'off'})` })
      onSaved && onSaved()
    } catch (err) {
      addToast({ type: 'error', message: err.message })
    } finally { setSaving(null) }
  }

  if (!params.length) {
    return (
      <Section title="Parameter limits & alerts" icon={Settings2}>
        <p className="text-sm text-gray-500">
          Your company has no approved parameters yet. Request one below under <strong>Add Parameter</strong> —
          its settings appear here once Super Admin approves it.
        </p>
      </Section>
    )
  }
  return (
    <Section title="Parameter limits & alerts" icon={Settings2}>
      <div className="space-y-3">
        <p className="text-xs text-gray-500 leading-relaxed">
          An alert fires when a reading goes below the minimum or above the maximum. Switching alerts off stops
          notifications (SMS, e-mail, app) for that parameter only — readings are still recorded.
        </p>
        {params.map(p => {
          const v = edit[p.id] || { min: '', max: '', on: true }
          return (
            <div key={p.id} className="rounded-xl border border-gray-200 bg-gray-50 p-3 flex flex-wrap items-end gap-3">
              <div className="min-w-[140px]">
                <p className="text-sm font-semibold text-gray-800">{p.name}</p>
                <p className="text-xs text-gray-500">{p.unit || '—'}</p>
              </div>
              <label className="flex flex-col gap-1 text-xs text-gray-600">Minimum
                <input type="number" step="any" className="form-input text-xs" style={{ width: 110 }}
                  value={v.min} onChange={e => setEdit(s => ({ ...s, [p.id]: { ...v, min: e.target.value } }))} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-gray-600">Maximum
                <input type="number" step="any" className="form-input text-xs" style={{ width: 110 }}
                  value={v.max} onChange={e => setEdit(s => ({ ...s, [p.id]: { ...v, max: e.target.value } }))} />
              </label>
              <div className="flex flex-col gap-1 text-xs text-gray-600">Alerts
                <SwitchBtn on={!!v.on} onClick={() => setEdit(s => ({ ...s, [p.id]: { ...v, on: !v.on } }))} />
              </div>
              <button className="btn btn-primary btn-sm" disabled={saving === p.id} onClick={() => save(p)}>
                {saving === p.id ? 'Saving…' : 'Save'}
              </button>
              <button className="btn btn-sm" disabled={testing === p.id} onClick={() => sendTest(p)}
                title="Sends a real alert to your company's subscribers"
                style={{ background: '#0891B2', color: '#fff', border: 'none' }}>
                {testing === p.id ? 'Sending…' : 'Send test alert'}
              </button>
            </div>
          )
        })}
      </div>
    </Section>
  )
}


/**
 * Alert messages — for each parameter THIS company has, one form for the SMS and one for the e-mail.
 * The text uses {placeholders} that are filled in when the alert is sent. Empty = standard message.
 */
const MSG_FIELDS = [
  ['name', 'person who gets it'], ['company', 'company name'], ['parameter', 'e.g. pH'], ['unit', 'e.g. C, pH'],
  ['value', 'reading'], ['limit', 'limit crossed'], ['direction', 'above / below'], ['severity', 'WARNING…'],
  ['time', 'when (IST)'], ['min', 'allowed minimum'], ['max', 'allowed maximum'],
]
const SMS_EXAMPLE = '{company}: {parameter} is {value}{unit}, {direction} the limit {limit}{unit}. {time}'
const MAIL_SUBJECT_EXAMPLE = '[{severity}] {parameter} is {direction} the limit - {company}'
const MAIL_BODY_EXAMPLE =
  'Hello {name},\n\n{parameter} reached {value} {unit} at {time}.\n' +
  'The allowed range is {min} to {max} {unit}; the limit that was crossed is {limit} {unit}.\n\n' +
  'Please check the plant and acknowledge the alert on the dashboard.\n\n- {company}'

function Chips({ onPick }) {
  return (
    <div className="flex flex-wrap gap-1">
      {MSG_FIELDS.map(([k, hint]) => (
        <button key={k} type="button" title={hint} onClick={() => onPick(`{${k}}`)}
          className="text-[11px] px-1.5 py-0.5 rounded border border-gray-300 bg-white text-gray-600 hover:bg-violet-50 hover:border-violet-300">
          {`{${k}}`}
        </button>
      ))}
    </div>
  )
}

function AlertMessagesSection({ params, onSaved, addToast }) {
  const [edit, setEdit] = useState({})
  const [busy, setBusy] = useState(null)
  const [prev, setPrev] = useState({})
  const fieldRefs = useRef({})
  const lastServer = useRef({})
  const lastField = useRef({})        // which e-mail box (subject / body) was used last, per parameter

  useEffect(() => {
    setEdit(old => {
      const next = { ...old }
      for (const p of params) {
        const server = { sms: p.sms_template || '', subject: p.email_subject || '', body: p.email_body || '' }
        const before = lastServer.current[p.id]
        if (!before || before.sms !== server.sms || before.subject !== server.subject || before.body !== server.body) {
          next[p.id] = server          // new from the server (first load, or just saved)
          lastServer.current[p.id] = server
        }
      }
      return next
    })
  }, [params])

  const set = (id, field, value) => setEdit(s => ({ ...s, [id]: { ...(s[id] || {}), [field]: value } }))
  const insert = (id, field, token) => {
    const el = fieldRefs.current[`${id}:${field}`]
    const cur = (edit[id] || {})[field] || ''
    if (!el) { set(id, field, cur + token); return }
    const a = el.selectionStart ?? cur.length, b = el.selectionEnd ?? cur.length
    set(id, field, cur.slice(0, a) + token + cur.slice(b))
    setTimeout(() => { el.focus(); el.setSelectionRange(a + token.length, a + token.length) }, 0)
  }

  const call = async (p, path, method, body) => {
    const res = await fetch(`/api/admin/parameters/${p.id}/${path}`, { method, headers: _bearerHeaders(), body: JSON.stringify(body) })
    const d = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(d.error || d.detail || `Error ${res.status}`)
    return d
  }
  const bodyFor = (v, kind) => (kind === 'sms'
    ? { sms_template: v.sms || '' }
    : { email_subject: v.subject || '', email_body: v.body || '' })

  const save = async (p, kind) => {
    const v = edit[p.id] || {}
    setBusy(`${p.id}:${kind}`)
    try {
      await call(p, 'messages', 'PUT', bodyFor(v, kind))
      const empty = !((kind === 'sms' ? v.sms : `${v.subject || ''}${v.body || ''}`) || '').trim()
      addToast({ type: 'success', message: `${p.name}: ${kind === 'sms' ? 'SMS' : 'e-mail'} wording saved${empty ? ' (standard message)' : ''}` })
      lastServer.current[p.id] = undefined      // re-read what the server now holds
      onSaved && onSaved()
    } catch (err) { addToast({ type: 'error', message: err.message }) } finally { setBusy(null) }
  }
  const preview = async (p, kind) => {
    const v = edit[p.id] || {}
    setBusy(`${p.id}:${kind}:p`)
    try {
      const d = await call(p, 'messages/preview', 'POST', bodyFor(v, kind))
      setPrev(s => ({ ...s, [`${p.id}:${kind}`]: d }))
    } catch (err) { addToast({ type: 'error', message: err.message }) } finally { setBusy(null) }
  }

  if (!params.length) return null
  const box = { border: '1px solid #E5E7EB', borderRadius: 12, background: '#fff', padding: 12 }
  return (
    <Section title="Alert messages (SMS and e-mail)" icon={MessageSquare}>
      <div className="space-y-4">
        <p className="text-xs text-gray-500 leading-relaxed">
          Write what your people receive when a parameter goes out of range. Each parameter has its own SMS and its own
          e-mail. Click a placeholder such as <code>{'{value}'}</code> to insert it; it is replaced by the real value when the
          alert is sent. Leave a box empty to keep the standard message. An SMS is cut at 160 characters (one message).
        </p>
        {params.map(p => {
          const v = edit[p.id] || { sms: '', subject: '', body: '' }
          const ps = prev[`${p.id}:sms`], pm = prev[`${p.id}:email`]
          const smsLen = (v.sms || '').length
          return (
            <div key={p.id} className="rounded-xl border border-gray-200 bg-gray-50 p-3 space-y-3">
              <p className="text-sm font-semibold text-gray-800">{p.name} <span className="text-xs font-normal text-gray-500">{p.unit ? `(${p.unit})` : ''}</span></p>

              {/* ── SMS form ── */}
              <div style={box} className="space-y-2">
                <p className="text-xs font-semibold text-gray-700 flex items-center gap-1.5"><Smartphone size={13} /> SMS for {p.name}</p>
                <textarea ref={el => { fieldRefs.current[`${p.id}:sms`] = el }} rows={3} maxLength={300} className="form-input text-xs w-full"
                  placeholder="Standard SMS (leave empty), or type your own text"
                  value={v.sms} onChange={e => set(p.id, 'sms', e.target.value)} />
                <Chips onPick={t => insert(p.id, 'sms', t)} />
                <div className="flex flex-wrap items-center gap-2">
                  <button className="btn btn-primary btn-sm" disabled={busy === `${p.id}:sms`} onClick={() => save(p, 'sms')}>
                    {busy === `${p.id}:sms` ? 'Saving…' : 'Save SMS'}
                  </button>
                  <button className="btn btn-sm" disabled={busy === `${p.id}:sms:p`} onClick={() => preview(p, 'sms')}>Preview</button>
                  <button className="btn btn-sm" onClick={() => set(p.id, 'sms', SMS_EXAMPLE)}>Use example</button>
                  <button className="btn btn-sm" onClick={() => set(p.id, 'sms', '')}>Standard message</button>
                  <span className="text-xs ml-auto" style={{ color: smsLen > 160 ? '#B45309' : '#6B7280' }}>
                    {smsLen} typed{smsLen > 160 ? ' (the sent SMS is cut at 160)' : ''}
                  </span>
                </div>
                {ps && (
                  <div className="rounded-lg bg-gray-50 border border-gray-200 p-2 text-xs text-gray-700 whitespace-pre-wrap">
                    {ps.sms ? <>{ps.sms}<div className="text-gray-400 mt-1">{ps.sms_length} characters · example values</div></> : 'The standard SMS will be sent.'}
                  </div>
                )}
              </div>

              {/* ── E-mail form ── */}
              <div style={box} className="space-y-2">
                <p className="text-xs font-semibold text-gray-700 flex items-center gap-1.5"><Mail size={13} /> E-mail for {p.name}</p>
                <input ref={el => { fieldRefs.current[`${p.id}:subject`] = el }} maxLength={150} className="form-input text-xs w-full"
                  placeholder="Subject (leave empty for the standard subject)"
                  onFocus={() => { lastField.current[p.id] = 'subject' }}
                  value={v.subject} onChange={e => set(p.id, 'subject', e.target.value)} />
                <textarea ref={el => { fieldRefs.current[`${p.id}:body`] = el }} rows={7} maxLength={3000} className="form-input text-xs w-full"
                  placeholder="E-mail text (leave empty for the standard e-mail)"
                  onFocus={() => { lastField.current[p.id] = 'body' }}
                  value={v.body} onChange={e => set(p.id, 'body', e.target.value)} />
                <p className="text-[11px] text-gray-500">A placeholder goes into the box you clicked last (subject or text).</p>
                <Chips onPick={t => insert(p.id, lastField.current[p.id] || 'body', t)} />
                <div className="flex flex-wrap items-center gap-2">
                  <button className="btn btn-primary btn-sm" disabled={busy === `${p.id}:email`} onClick={() => save(p, 'email')}>
                    {busy === `${p.id}:email` ? 'Saving…' : 'Save e-mail'}
                  </button>
                  <button className="btn btn-sm" disabled={busy === `${p.id}:email:p`} onClick={() => preview(p, 'email')}>Preview</button>
                  <button className="btn btn-sm" onClick={() => { set(p.id, 'subject', MAIL_SUBJECT_EXAMPLE); set(p.id, 'body', MAIL_BODY_EXAMPLE) }}>Use example</button>
                  <button className="btn btn-sm" onClick={() => { set(p.id, 'subject', ''); set(p.id, 'body', '') }}>Standard e-mail</button>
                </div>
                {pm && (
                  <div className="rounded-lg bg-gray-50 border border-gray-200 p-2 text-xs text-gray-700">
                    <p className="font-semibold">{pm.email_subject || 'Standard subject'}</p>
                    <p className="whitespace-pre-wrap mt-1">{pm.email_body || 'The standard e-mail will be sent.'}</p>
                    <p className="text-gray-400 mt-1">example values</p>
                  </div>
                )}
              </div>
            </div>
          )
        })}
        <p className="text-xs text-gray-400">Tip: press <strong>Send test alert</strong> above to receive the real message on your own phone and e-mail.</p>
      </div>
    </Section>
  )
}


/**
 * E-mail account for alerts — the company's own mailbox. Alert e-mails and the daily report are sent
 * from it. The password is stored encrypted on the server and is never shown again.
 */
const MAIL_STEPS = {
  gmail: {
    title: 'Gmail / Google Workspace — how to get the app password',
    steps: [
      'Open myaccount.google.com and sign in with the Gmail address the alerts should be sent from.',
      'Go to Security and turn on "2-Step Verification" (Google only offers app passwords when it is on).',
      'Open myaccount.google.com/apppasswords (or type "App passwords" in the search box of your Google account).',
      'Type a name such as SentinelEdge and press Create.',
      'Google shows a 16-letter password. Copy it (spaces do not matter) and paste it into "App password" above. It is shown only once.',
      'Press Save, then "Send test e-mail".',
    ],
    notes: [
      'Use the APP password, never your normal Gmail password.',
      'Google Workspace (company) accounts: if "App passwords" is missing, your administrator has switched it off — ask them to allow it.',
      'Gmail sends up to about 500 e-mails a day, which is plenty for alerts.',
    ],
  },
  outlook: {
    title: 'Outlook.com / Hotmail — how to get the app password',
    steps: [
      'Sign in at account.microsoft.com and open Security, then "Advanced security options".',
      'Turn on "Two-step verification".',
      'Under "App passwords" choose "Create a new app password".',
      'Copy the password that is shown and paste it into "App password" above (it is shown only once).',
      'Use your full Outlook / Hotmail address as the e-mail address, press Save, then "Send test e-mail".',
    ],
    notes: ['Use the app password, not your normal Microsoft password.'],
  },
  office365: {
    title: 'Microsoft 365 (work account) — what to ask your IT administrator',
    steps: [
      'Use your work e-mail address as the e-mail address.',
      'Ask your IT administrator to allow "Authenticated SMTP" (SMTP AUTH) for that mailbox in the Microsoft 365 admin centre.',
      'If two-step verification is on for the mailbox, ask them for an app password and use it as the password.',
      'Press Save, then "Send test e-mail".',
    ],
    notes: ['Some organisations have switched off password sign-in for mail programs. If so, this will not work: use a Gmail or other account for alerts instead.'],
  },
  yahoo: {
    title: 'Yahoo Mail — how to get the app password',
    steps: [
      'Sign in at Yahoo and open Account Info, then "Account security".',
      'Turn on two-step verification.',
      'Choose "Generate app password", name it SentinelEdge and press Generate.',
      'Copy the password and paste it into "App password" above, press Save, then "Send test e-mail".',
    ],
    notes: ['Use the app password, not your normal Yahoo password.'],
  },
  other: {
    title: 'Another e-mail provider — what you need',
    steps: [
      'Ask your IT department or e-mail provider for the "outgoing mail (SMTP)" details: the server name, the port and the password to use.',
      'The port is usually 587 with STARTTLS, or 465 with SSL. Choose it in the boxes above.',
      'Enter the server, the port and the security, your e-mail address and the password.',
      'Press Save, then "Send test e-mail".',
    ],
    notes: ['Only secure connections (STARTTLS or SSL) are allowed.'],
  },
}

function EmailAccountSection({ addToast }) {
  const [info, setInfo] = useState(null)
  const [form, setForm] = useState({ provider: 'gmail', email: '', password: '', host: '', port: 587, security: 'starttls', from_name: '' })
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(null)
  const [testTo, setTestTo] = useState('')
  const [result, setResult] = useState(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/email-account', { headers: _bearerHeaders() })
      if (!res.ok) return
      const d = await res.json()
      setInfo(d)
      if (d.configured) {
        setForm(f => ({ ...f, provider: d.provider, email: d.email, host: d.provider === 'other' ? d.host : '', port: d.port, security: d.security, from_name: d.from_name || '', password: '' }))
      }
    } catch { /* silent */ }
  }, [])
  useEffect(() => { load() }, [load])

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const api = async (path, method, body) => {
    const res = await fetch(path, { method, headers: _bearerHeaders(), body: body ? JSON.stringify(body) : undefined })
    const d = await res.json().catch(() => ({}))
    if (!res.ok) throw Object.assign(new Error(d.error || d.detail || `Error ${res.status}`), { data: d })
    return d
  }

  const save = async () => {
    setBusy('save'); setResult(null)
    try {
      await api('/api/admin/email-account', 'PUT', {
        provider: form.provider, email: form.email, password: form.password || null,
        host: form.provider === 'other' ? form.host : null, port: form.provider === 'other' ? Number(form.port) : null,
        security: form.security, from_name: form.from_name || null,
      })
      addToast({ type: 'success', message: 'E-mail account saved. Press "Send test e-mail" to check it.' })
      setForm(f => ({ ...f, password: '' })); setShow(false)
      await load()
    } catch (err) { addToast({ type: 'error', message: err.message }) } finally { setBusy(null) }
  }
  const test = async () => {
    setBusy('test'); setResult(null)
    try {
      const d = await api('/api/admin/email-account/test', 'POST', { to: testTo || null })
      setResult({ ok: true, text: `Test e-mail sent to ${d.to}. Check that inbox (and the spam folder).` })
    } catch (err) { setResult({ ok: false, text: err.message }) } finally { setBusy(null); load() }
  }
  const remove = async () => {
    if (!window.confirm('Remove this e-mail account?\n\nThe saved password is deleted and NO alert e-mails are sent until you add an account again.')) return
    setBusy('remove')
    try { await api('/api/admin/email-account', 'DELETE'); setForm(f => ({ ...f, email: '', password: '' })); setResult(null); await load(); addToast({ type: 'success', message: 'E-mail account removed' }) }
    catch (err) { addToast({ type: 'error', message: err.message }) } finally { setBusy(null) }
  }

  const providers = info?.providers || {}
  const steps = MAIL_STEPS[form.provider] || MAIL_STEPS.other
  const configured = !!info?.configured
  return (
    <Section title="E-mail account for alerts" icon={Mail}>
      <div className="space-y-4">
        <div className="rounded-lg p-3 text-xs leading-relaxed"
          style={{ background: configured ? (info.last_status === 'failed' ? '#FEF2F2' : '#ECFDF5') : '#FFFBEB', border: '1px solid ' + (configured ? (info.last_status === 'failed' ? '#FECACA' : '#A7F3D0') : '#FDE68A') }}>
          {configured ? (
            <>
              <p className="font-semibold text-gray-800">Alerts and the daily report are sent from <span style={{ color: '#7C3AED' }}>{info.email}</span></p>
              {!info.password_ok && <p className="text-red-700 mt-1">The saved password can no longer be read on this computer. Type the app password again and press Save.</p>}
              {info.last_status === 'ok' && <p className="text-emerald-700 mt-1">Last e-mail sent successfully{info.last_at ? ` (${utcToIST ? utcToIST(info.last_at) : info.last_at})` : ''}.</p>}
              {info.last_status === 'failed' && <p className="text-red-700 mt-1">Last e-mail failed: {info.last_error}</p>}
              {!info.last_status && <p className="text-gray-500 mt-1">Not used yet — press "Send test e-mail".</p>}
            </>
          ) : (
            <p className="text-gray-700">
              No e-mail account is set up, so alert e-mails are NOT sent. Add your company's e-mail address and app password below
              (the steps for getting the app password are underneath).
            </p>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-gray-600">E-mail provider
            <select className="form-input text-xs" value={form.provider} onChange={e => set('provider', e.target.value)}>
              {Object.entries(providers).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-gray-600">Your e-mail address (alerts are sent from it)
            <input type="email" autoComplete="off" className="form-input text-xs" placeholder="alerts@yourcompany.com"
              value={form.email} onChange={e => set('email', e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-gray-600">App password
            <div className="flex gap-1">
              <input type={show ? 'text' : 'password'} autoComplete="new-password" className="form-input text-xs flex-1"
                placeholder={configured && info.password_ok ? '•••••••• saved (leave empty to keep it)' : 'Paste the app password here'}
                value={form.password} onChange={e => set('password', e.target.value)} />
              <button type="button" className="btn btn-sm" onClick={() => setShow(s => !s)} title={show ? 'Hide' : 'Show'}>{show ? <EyeOff size={14} /> : <Eye size={14} />}</button>
            </div>
          </label>
          <label className="flex flex-col gap-1 text-xs text-gray-600">Name shown to the reader (optional)
            <input className="form-input text-xs" maxLength={80} placeholder="e.g. Alpha Plant Alerts"
              value={form.from_name} onChange={e => set('from_name', e.target.value)} />
          </label>
          {form.provider === 'other' && (
            <>
              <label className="flex flex-col gap-1 text-xs text-gray-600">Mail server (SMTP)
                <input className="form-input text-xs" placeholder="smtp.yourprovider.com" value={form.host} onChange={e => set('host', e.target.value)} />
              </label>
              <div className="flex gap-2">
                <label className="flex flex-col gap-1 text-xs text-gray-600 flex-1">Port
                  <select className="form-input text-xs" value={form.port} onChange={e => set('port', e.target.value)}>
                    {[587, 465, 25, 2525].map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-xs text-gray-600 flex-1">Security
                  <select className="form-input text-xs" value={form.security} onChange={e => set('security', e.target.value)}>
                    <option value="starttls">STARTTLS</option><option value="ssl">SSL</option>
                  </select>
                </label>
              </div>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button className="btn btn-primary btn-sm" disabled={busy === 'save'} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save'}</button>
          <input className="form-input text-xs" style={{ width: 220 }} placeholder={configured ? `Send test to (default ${info.email})` : 'Send test to (optional)'}
            value={testTo} onChange={e => setTestTo(e.target.value)} />
          <button className="btn btn-sm" disabled={busy === 'test' || !configured} onClick={test}>{busy === 'test' ? 'Sending…' : 'Send test e-mail'}</button>
          {configured && <button className="btn btn-sm" disabled={busy === 'remove'} onClick={remove} style={{ color: '#B91C1C' }}>Remove account</button>}
        </div>
        {result && (
          <p className="text-xs rounded-lg p-2" style={{ background: result.ok ? '#ECFDF5' : '#FEF2F2', color: result.ok ? '#047857' : '#B91C1C' }}>{result.text}</p>
        )}
        <p className="text-[11px] text-gray-400">
          SentinelEdge only sends mail from this account; it never reads it. {info?.where === 'env'
            ? 'It is saved in the server\'s settings file (.env) automatically, so you never have to edit that file.'
            : 'The password is stored encrypted on this computer.'} The password is never shown again. A test e-mail can go to your own
          address or to someone on your Subscribers list.
        </p>

        <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
          <p className="text-sm font-semibold text-gray-800 mb-2">{steps.title}</p>
          <ol className="list-decimal pl-5 space-y-1 text-xs text-gray-700 leading-relaxed">
            {steps.steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
          {steps.notes.length > 0 && (
            <ul className="list-disc pl-5 mt-2 space-y-1 text-xs text-gray-500 leading-relaxed">
              {steps.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
          <p className="text-[11px] text-gray-400 mt-2">Choose another provider in the list above to see its steps.</p>
        </div>
      </div>
    </Section>
  )
}


/**
 * Phone app — the same app (APK) is used by every company; each phone is pointed at its own company's
 * server. This card shows the address to type into the app.
 */
function PhoneAppSection() {
  const [info, setInfo] = useState(null)
  useEffect(() => {
    fetch('/api/app/server-address', { headers: _bearerHeaders() })
      .then(r => (r.ok ? r.json() : null)).then(setInfo).catch(() => {})
  }, [])
  const list = info?.addresses || []
  return (
    <Section title="Phone app" icon={Smartphone}>
      <div className="space-y-3">
        <p className="text-xs text-gray-600 leading-relaxed">
          Everyone uses the <strong>same SentinelEdge app</strong>. It shows only the parameters of <strong>your company</strong>
          (what you added under Parameters), with your own limits. It receives your live values and your alerts and lets people acknowledge them.
        </p>
        <div className="rounded-xl bg-gray-50 border border-gray-200 px-4 py-3">
          <p className="text-xs font-semibold text-gray-700 mb-1">Server address to type into the app</p>
          {list.length === 0 ? (
            <p className="text-xs text-gray-500">The address could not be found automatically. Use this computer&apos;s IP address followed by :{info?.port || 5000}.</p>
          ) : (
            <ul className="space-y-1">
              {list.map(a => (
                <li key={a.address} className="text-sm font-mono text-gray-800">
                  {a.address}:{info.port}
                  <span className="ml-2 text-[11px] font-sans text-gray-500">
                    {a.kind === 'tailscale' ? 'Tailscale — works from anywhere' : 'this network (same Wi-Fi / LAN)'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <ol className="list-decimal pl-5 space-y-1 text-xs text-gray-600 leading-relaxed">
          <li>Install the SentinelEdge app on the phone.</li>
          <li>Open it and type the <strong>server address</strong> above, then the person&apos;s <strong>name</strong> and <strong>PIN</strong>. Set each person&apos;s PIN under Subscribers.</li>
          <li>The phone must reach this computer: the same Wi-Fi, or Tailscale / VPN when away. The app remembers the address.</li>
          <li>To change the server (for example another company), sign out in the app and enter the new address.</li>
        </ol>
        <p className="text-[11px] text-gray-400">Company admins can also sign in to the app with their admin name and password.</p>
      </div>
    </Section>
  )
}


/**
 * Connect to the main server (Tailscale) — status, the invitation link Super Admin gave, and the steps.
 * Company servers send their data to the main server, and phones reach company servers, through Tailscale.
 */
function TailscaleSection({ addToast }) {
  const [info, setInfo] = useState(null)
  const [busy, setBusy] = useState(false)
  const [link, setLink] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    try {
      const r = await fetch('/api/admin/tailscale', { headers: _bearerHeaders() })
      if (r.ok) setInfo(await r.json())
    } catch { /* silent */ } finally { setBusy(false) }
  }, [])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (info && window.location.hash === '#tailscale') document.getElementById('tailscale')?.scrollIntoView({ behavior: 'smooth' })
  }, [info])

  const saveLink = async () => {
    try {
      const r = await fetch('/api/admin/tailscale/invite', { method: 'PUT', headers: _bearerHeaders(), body: JSON.stringify({ url: link.trim() }) })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(d.error || d.detail || `Error ${r.status}`)
      addToast({ type: 'success', message: 'Invitation link saved' }); setLink(''); load()
    } catch (err) { addToast({ type: 'error', message: err.message }) }
  }

  const ts = info?.tailscale
  const isNode = info?.role === 'node'
  const stateLabel = !ts ? 'Checking…'
    : !ts.installed ? 'Not installed'
    : ts.state === 'running' ? 'Connected'
    : ts.state === 'needs_login' ? 'Installed — please sign in'
    : 'Installed — turned off'
  const good = ts?.running && (!isNode || !info?.hub_url || info?.hub_reachable)
  const color = good ? '#047857' : '#B45309'
  const bg = good ? '#ECFDF5' : '#FFFBEB'
  const border = good ? '#A7F3D0' : '#FDE68A'

  return (
    <div id="tailscale">
      <Section title={isNode ? 'Connect to the main server (Tailscale)' : 'Tailscale (company servers and phones reach this server)'} icon={Server}>
        <div className="space-y-4">
          <div className="rounded-lg p-3 text-xs leading-relaxed" style={{ background: bg, border: `1px solid ${border}`, color }}>
            <p className="font-semibold">Tailscale on this computer: {stateLabel}{ts?.ip ? ` · ${ts.ip}` : ''}</p>
            {isNode && info?.hub_url && (
              <p className="mt-1">
                Main server {info.hub_url}: {info.hub_reachable ? 'reachable ✓' : 'NOT reachable'}
              </p>
            )}
            {isNode && !info?.hub_url && <p className="mt-1">This server is not paired with the main server yet.</p>}
            {!isNode && ts?.running && <p className="mt-1">Company servers can reach this server at <strong>{ts.ip ? `http://${ts.ip}:${window.location.port || 5000}` : '—'}</strong>.</p>}
            <button className="btn btn-sm mt-2" disabled={busy} onClick={load}>{busy ? 'Checking…' : 'Check again'}</button>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
            <p className="text-sm font-semibold text-gray-800 mb-2">{isNode ? 'How to connect to the main server' : 'How to set up Tailscale on this computer'}</p>
            <ol className="list-decimal pl-5 space-y-1.5 text-xs text-gray-700 leading-relaxed">
              <li>Download <strong>Tailscale for Windows</strong> from <strong>tailscale.com/download</strong> (free) and install it.</li>
              <li>Click the Tailscale icon near the clock (bottom right) and choose <strong>Log in</strong>. Sign in with a Google or Microsoft account.</li>
              {isNode ? (
                <li>Open the <strong>invitation link</strong> below, sign in if asked, and press <strong>Accept</strong>. The main server then appears in your Tailscale.</li>
              ) : (
                <li>For each company: in the Tailscale admin console open <strong>Machines</strong>, choose this computer, then <strong>Share…</strong> and copy the link (switch on <em>Reusable link</em> to use it for several companies). Paste it in Super Admin → Config → Tailscale.</li>
              )}
              <li>The icon should show <strong>Connected</strong>. In the Tailscale menu turn on <strong>Run unattended</strong> and <strong>Start on login</strong>, so it stays on after a restart.</li>
              <li>Come back here and press <strong>Check again</strong>. It turns green when everything is connected.</li>
              {isNode && <li>Then pair this server with the main server (the address is the main server&apos;s Tailscale address{info?.hub_address ? `: ${info.hub_address}` : ''}) using the pairing code from Super Admin.</li>}
            </ol>
            <p className="text-[11px] text-gray-500 mt-2">
              Invitation and share links work once per person and expire after 30 days if unused. Ask Super Admin for a new one if yours has expired.
            </p>
          </div>

          {isNode && (
            <div className="rounded-xl border border-gray-200 bg-white p-3 space-y-2">
              <p className="text-xs font-semibold text-gray-700">Invitation link from Super Admin</p>
              {info?.invite_url ? (
                <div className="flex flex-wrap items-center gap-2">
                  <a className="btn btn-primary btn-sm" href={info.invite_url} target="_blank" rel="noreferrer">Open invitation link</a>
                  <button className="btn btn-sm" onClick={() => { navigator.clipboard?.writeText(info.invite_url); addToast({ type: 'success', message: 'Link copied' }) }}>Copy link</button>
                  <span className="text-[11px] text-gray-400 truncate" style={{ maxWidth: 260 }}>{info.invite_url}</span>
                </div>
              ) : (
                <p className="text-xs text-gray-500">Super Admin has not shared one yet. If you were given a link, paste it here.</p>
              )}
              <div className="flex flex-wrap gap-2">
                <input className="form-input text-xs flex-1" style={{ minWidth: 220 }} placeholder="https://login.tailscale.com/admin/invite/…"
                  value={link} onChange={e => setLink(e.target.value)} />
                <button className="btn btn-sm" disabled={!link.trim()} onClick={saveLink}>Save link</button>
              </div>
            </div>
          )}
        </div>
      </Section>
    </div>
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


  const [testSmsPhone, setTestSmsPhone] = useState('')
  const [testingSms, setTestingSms] = useState(false)
  const [testSmsMsg, setTestSmsMsg] = useState(null)

  const [pwdAction, setPwdAction] = useState(null)
  const [pwdError, setPwdError] = useState(null)

  const [existingParams, setExistingParams] = useState([])
  const [deletingId, setDeletingId] = useState(null)
  const [reqVersion, setReqVersion] = useState(0)   // bump to refresh the approval list
  const me = useAdminIdentity()
  const { has } = useCompanyParameters()   // Settings shows only the company's own parameters

  const [psSettings, setPsSettings] = useState({
    file_path: '', temp_col: 'TEMPERATURE', timestamp_col: '', date_col: 'DATE/TIME', time_col: '', auto_save: false,
  })
  const [psSaving,     setPsSaving]     = useState(false)
  const [psTesting,    setPsTesting]    = useState(false)
  const [psMsg,        setPsMsg]        = useState(null)
  const [psTestResult, setPsTestResult] = useState(null)
  const [psStatus,     setPsStatus]     = useState(null)  // {enabled, is_active, in_loop_mode}
  const [psDiag,       setPsDiag]       = useState(null)
  const [psDiagLoading, setPsDiagLoading] = useState(false)

  const [opcSettings, setOpcSettings] = useState({
    server_name: '', temp_tag: '', extra_tags: '', poll_interval: 2.0,
  })
  const [opcStatus,  setOpcStatus]  = useState(null)
  const [opcSaving,  setOpcSaving]  = useState(false)
  const [opcMsg,     setOpcMsg]     = useState(null)

  const [collectorStatus,     setCollectorStatus]     = useState(null)
  const [collectorRefreshing, setCollectorRefreshing] = useState(false)
  const [collectorStatusErr,  setCollectorStatusErr]  = useState(null)

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
      }
    } catch { /* silent */ }
  }, [])

  const loadCollectorStatus = useCallback(async () => {
    try {
      const token = sessionStorage.getItem('admin_token') || ''
      const res = await fetch('/api/collector/status', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setCollectorStatus(await res.json())
      setCollectorStatusErr(null)
    } catch (err) {
      setCollectorStatusErr('Unable to reach collector status service')
    }
  }, [])

  // ── The two live sources — each has its own on/off switch ───────────────────
  const [collectorOn, setCollectorOn] = useState(null)   // Pro-Server EX live collector
  const [excelOn,     setExcelOn]     = useState(null)   // Excel file reader
  const [dsSaving,    setDsSaving]    = useState(null)   // 'collector' | 'excel' while saving

  const loadDataSource = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/data-source', { headers: _bearerHeaders() })
      if (res.ok) {
        const d = await res.json()
        setCollectorOn(!!d.collector_enabled)
        setExcelOn(!!d.excel_enabled)
        if (d.excel) setPsStatus(d.excel)
      }
    } catch { /* silent */ }
  }, [])

  useEffect(() => { if (me) loadDataSource() }, [loadDataSource, me?.id, me?.owns_sensor_feed])

  const handleSourceToggle = async (which, on) => {
    setDsSaving(which)
    try {
      const res = await fetch('/api/admin/data-source', {
        method: 'POST',
        headers: _bearerHeaders(),
        body: JSON.stringify({ [which]: on }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || data.detail?.[0]?.msg || `Error ${res.status}`)
      refreshAdminIdentity()        // this company may now own the live feed
      setCollectorOn(!!data.collector_enabled)
      setExcelOn(!!data.excel_enabled)
      addToast({
        type: 'success',
        message: `${which === 'collector' ? 'Pro-Server EX live collector' : 'Excel reader'} switched ${on ? 'ON' : 'OFF'}`,
      })
      loadPsStatus()
    } catch (err) {
      addToast({ type: 'error', message: err.message })
    } finally { setDsSaving(null) }
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

  useEffect(() => { loadThresholds(); loadHealth(); loadParams(); loadAlertSettings(); if (me) { loadPsSettings(); loadOpcSettings(); loadPsStatus(); loadCollectorStatus() } }, [loadThresholds, loadHealth, loadParams, loadPsSettings, loadAlertSettings, loadOpcSettings, loadPsStatus, loadCollectorStatus, me?.id])

  // Poll Pro-Server EX status every 5 seconds to show live/loop/watchdog badge
  useEffect(() => {
    const id = setInterval(loadPsStatus, 5000)
    return () => clearInterval(id)
  }, [loadPsStatus])

  // Poll Live Collector status every 3 seconds
  useEffect(() => {
    const id = setInterval(loadCollectorStatus, 3000)
    return () => clearInterval(id)
  }, [loadCollectorStatus])

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
        setReqVersion(v => v + 1)
      } else {
        addToast({ type: 'error', message: data.error || `Error ${res.status}` })
      }
    } catch (err) {
      addToast({ type: 'error', message: err.message })
    } finally {
      setDeletingId(null)
    }
  }

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
        refreshAdminIdentity()        // saving the file settings moves the live feed to this company
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

        {/* ── Organisation ── */}
        <div className="card px-5 py-4 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" style={{ background: '#F3F0FF' }}>
            <Building2 size={18} style={{ color: '#7C3AED' }} />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Company</p>
            <p className="text-sm font-bold text-gray-900 truncate">{me?.company_name || '—'}</p>
          </div>
          {me?.name && (
            <div className="ml-auto text-right">
              <p className="text-xs text-gray-400">Signed in as</p>
              <p className="text-sm font-semibold text-gray-700">{me.name}</p>
            </div>
          )}
        </div>

        <ParameterLimitsSection params={existingParams} onSaved={loadParams} addToast={addToast} />
        <AlertMessagesSection params={existingParams} onSaved={loadParams} addToast={addToast} />
        <EmailAccountSection addToast={addToast} />
        <PhoneAppSection />
        <TailscaleSection addToast={addToast} />

                {/* ── Section 3: Database Backup ──────────────────────────────────── */}
{me?.owns_sensor_feed && (   /* a backup holds every company's data: main company only */
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
)}

        {/* ── Section 4: SMS Configuration ─────────────────────────────── */}
        <Section title="SMS Configuration" icon={MessageSquare}>
          <div className="space-y-4">

            {/* GSM modem status */}
            {(() => {
              const smsStatus = String(health?.modules?.sms?.status || '')
              const connected = smsStatus === 'connected' || smsStatus.startsWith('ok') || smsStatus.startsWith('configured')
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
                      ? `SIM7600 GSM modem is connected${health?.modules?.sms?.port ? ' on ' + health.modules.sms.port : ''} and ready. SMS alerts are sent automatically on a breach.`
                      : hasError
                      ? `Modem error: ${smsStatus}. Check USB connection and driver.`
                      : 'GSM modem not detected. Plug in the SIM7600 USB modem (with a SIM card) and restart SentinelEdge — SMS alerts then start automatically.'
                    }
                  </p>
                </div>
              )
            })()}

            <div className="rounded-xl bg-gray-50 border border-gray-200 px-4 py-3 space-y-2">
              <p className="text-xs font-semibold text-gray-700">What you need to send SMS</p>
              <p className="text-xs text-gray-600 leading-relaxed">
                SMS alerts are sent by a <strong>GSM modem</strong> plugged into this computer. SentinelEdge is set up for the
                <strong> SIM7600 (SIM7600 EI 4G modem / HAT, connected by USB)</strong> — the module SentinelEdge is built and tested with.
                Without it, only e-mail and app alerts are sent.
              </p>
              <ol className="list-decimal pl-5 space-y-1 text-xs text-gray-600 leading-relaxed">
                <li>A <strong>SIM7600</strong> USB GSM modem, with its antenna fitted.</li>
                <li>A working <strong>SIM card</strong> in the modem that can send SMS (active plan or balance, network signal, and the SIM&apos;s PIN lock switched off).</li>
                <li>The modem&apos;s <strong>USB driver</strong> installed on this computer. In Windows Device Manager, under "Ports (COM &amp; LPT)", the modem shows up as COM ports, one of them an "AT" port.</li>
                <li><strong>Plug the modem in, then restart SentinelEdge</strong> (STOP.bat, then START.bat). The status above turns to "Connected" when the modem answers.</li>
                <li>Press <strong>Send Test</strong> below (to a person on your Subscribers list) to check that a real SMS arrives.</li>
              </ol>
              <ul className="list-disc pl-5 space-y-1 text-xs text-gray-500 leading-relaxed">
                <li>One modem serves the whole computer: every company on this PC uses it, and each company's SMS goes only to its own subscribers.</li>
                <li>Each SMS is charged by the SIM&apos;s mobile plan. An SMS is one message of up to 160 characters.</li>
                <li>Write your own SMS wording per parameter under "Alert messages" above.</li>
                <li>If the status says "Not Connected": check the USB cable and driver, that the SIM is inserted and has signal, then restart.</li>
              </ul>
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
                  placeholder="Phone number (10 digits)"
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
          <ApprovalRequests refreshKey={reqVersion} />
        </Section>

        {/* ── Section 6: Add Parameter ──────────────────────────────────────── */}
        <Section title="Add Parameter" icon={PlusCircle}>
          <AddParameterForm onToast={addToast} onAdded={() => { loadParams(); setReqVersion(v => v + 1) }} />
        </Section>

{me && (
<>
        {/* ── Section 7: Pro-Server EX Data Source ──────────────────────────── */}
        <Section title={me.collector_available ? "Pro-Server EX Data Source" : "Excel Live Reader"} icon={Server}>
          <div className="space-y-4">
            {/* One plant per PC: show which company receives this PC's live readings */}
            {/* Each live source on this PC belongs to one company (they can differ) */}
            {me.company_id && me.source_owners && (
              <div className="rounded-xl border p-3 text-sm space-y-1" style={{ borderColor: '#C7D2FE', background: '#EEF2FF', color: '#3730A3' }}>
                {(me.collector_available ? [['collector', 'Live collector'], ['excel', 'Excel reader']] : [['excel', 'Excel reader']]).map(([src, label]) => {
                  const o = me.source_owners[src] || {}
                  const mine = o.company_id === me.company_id
                  return (
                    <div key={src}>
                      {label} on this PC → <strong>{o.company_name || '—'}</strong>{mine ? ' (your company)' : ''}
                    </div>
                  )
                })}
                <div className="text-xs" style={{ color: '#4F46E5' }}>
                  Switching a source on makes it {me.company_name}'s — unless another company is using it right now.
                  Only {me.company_name}'s approved parameters are stored.
                </div>
              </div>
            )}
            {/* ── Excel reader on/off (separate from the live collector) ── */}
            <div className="rounded-xl border p-3 space-y-2"
              style={{ borderColor: excelOn ? '#10B981' : '#D1D5DB', background: excelOn ? '#F0FDF4' : '#F9FAFB' }}>
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-800">Excel reader — {excelOn ? 'ON' : 'OFF'}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {excelOn
                      ? 'The dashboard follows the last row of the file below'
                      : 'Switch on to read the Excel file below. Save the file path first.'}
                  </p>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  {excelOn && psStatus && (
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{
                      background: !psStatus.is_active ? '#FEE2E2' : psStatus.in_loop_mode ? '#FEF3C7' : '#D1FAE5',
                      color:      !psStatus.is_active ? '#991B1B' : psStatus.in_loop_mode ? '#92400E' : '#065F46',
                    }}>
                      {!psStatus.is_active ? 'CANNOT READ FILE' : psStatus.in_loop_mode ? '↻ LAST ROW' : '● NEW ROWS'}
                    </span>
                  )}
                  <SwitchBtn on={!!excelOn} disabled={dsSaving === 'excel' || excelOn == null}
                    onClick={() => handleSourceToggle('excel', !excelOn)} />
                </div>
              </div>
              {excelOn && psStatus?.is_active && (
                <div className="text-xs text-gray-500 grid grid-cols-2 gap-x-4 gap-y-0.5">
                  <span>Reading via: <strong>{psStatus.mode === 'com' ? 'open Excel (live)' : 'saved file'}</strong></span>
                  <span>New rows seen: <strong>{psStatus.new_rows_seen ?? 0}</strong></span>
                  <span>Last row: <strong>{psStatus.current_temperature ?? '—'} °C</strong>
                    {psStatus.values && Object.entries(psStatus.values).map(([k, v]) => ` · ${k} ${v}`)}</span>
                  <span>Last new row: <strong>{psStatus.last_new_row_at ? utcToIST(psStatus.last_new_row_at) : '—'}</strong></span>
                </div>
              )}
            </div>

            <p className="text-xs text-gray-500 leading-relaxed">
              Point to the file Pro-face Pro-Server EX writes to (<strong>.xls</strong>, <strong>.xlsx</strong>,
              <strong> .xlsm</strong>, <strong>.xlsb</strong> or <strong>.csv</strong>). The reader takes the file's
              <strong> last row</strong> and keeps showing it until the next row is added; each new row is then stored
              and checked for alerts once. It works while Excel has the file open, and sees a row typed into an open
              workbook even before it is saved.
            </p>

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

{me?.collector_available && (
<>
        {/* ── Section 7b: Pro-Server EX Live Collector ──────────────────────── */}
        <Section title="Pro-Server EX Live Collector" icon={Server}>
          <div className="space-y-4">
            <p className="text-xs text-gray-500 leading-relaxed">
              Live industrial data received from the Pro-Server EX collector.
              The collector script (<code className="bg-gray-100 px-1 rounded">proserver_collector.py</code>) runs on the
              Pro-Server EX machine and POSTs readings to this backend over HTTP.
            </p>

            {/* ── Live collector on/off (separate from the Excel reader) ── */}
            <div className="flex items-center justify-between rounded-xl border p-3 gap-3"
              style={{ borderColor: collectorOn ? '#10B981' : '#D1D5DB', background: collectorOn ? '#F0FDF4' : '#F9FAFB' }}>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-800">Live collector — {collectorOn ? 'ON' : 'OFF'}</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {collectorOn
                    ? 'Readings sent by the collector feed the dashboard'
                    : 'Readings from the collector are ignored (the script can keep running)'}
                </p>
              </div>
              <SwitchBtn on={!!collectorOn} disabled={dsSaving === 'collector' || collectorOn == null}
                onClick={() => handleSourceToggle('collector', !collectorOn)} />
            </div>

            {/* ── Connection status banner ── */}
            {(() => {
              const cs = collectorStatus?.connection_state
              const cfg = !collectorStatusErr && {
                never_connected: { dot: '#9CA3AF', bg: '#F3F4F6', color: '#374151', label: 'NEVER CONNECTED' },
                stale:           { dot: '#F59E0B', bg: '#FEF3C7', color: '#92400E', label: 'STALE'           },
                live:            { dot: '#10B981', bg: '#D1FAE5', color: '#065F46', label: 'LIVE'             },
              }[cs] || { dot: '#EF4444', bg: '#FEE2E2', color: '#991B1B', label: 'DISCONNECTED' }

              return (
                <div className="rounded-xl border p-3 flex items-center justify-between"
                  style={{ background: collectorStatusErr ? '#FEE2E2' : cfg.bg, borderColor: collectorStatusErr ? '#FCA5A5' : 'transparent' }}>
                  <div className="flex items-center gap-2">
                    <span style={{ width: 10, height: 10, borderRadius: '50%', background: collectorStatusErr ? '#EF4444' : cfg.dot, display: 'inline-block', flexShrink: 0 }} />
                    <span className="text-sm font-bold" style={{ color: collectorStatusErr ? '#991B1B' : cfg.color }}>
                      {collectorStatusErr ? 'DISCONNECTED' : cfg.label}
                    </span>
                  </div>
                  <button
                    onClick={async () => { setCollectorRefreshing(true); await loadCollectorStatus(); setCollectorRefreshing(false) }}
                    disabled={collectorRefreshing}
                    className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg border"
                    style={{ background: '#fff', borderColor: '#D1D5DB', color: '#374151' }}
                  >
                    <RefreshCw size={12} className={collectorRefreshing ? 'animate-spin' : ''} />
                    Refresh Status
                  </button>
                </div>
              )
            })()}

            {collectorStatusErr ? (
              <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{collectorStatusErr}</p>
            ) : collectorStatus ? (
              <>
                {/* ── Status grid ── */}
                <div className="rounded-xl bg-gray-50 border border-gray-200 divide-y divide-gray-100">
                  {[
                    { label: 'Collector Status', value: collectorStatus.connection_state?.replace('_', ' ').toUpperCase() ?? '—' },
                    { label: 'Collector IP',     value: collectorStatus.collector_ip ?? '—' },
                    { label: 'Last Data Received', value: collectorStatus.last_received_at
                        ? new Date(collectorStatus.last_received_at).toLocaleTimeString()
                        : '—' },
                    { label: 'Time Since Last Data', value: timeSince(collectorStatus.last_received_at) ?? '—' },
                    { label: 'Total Readings',   value: collectorStatus.total_received ?? 0 },
                    { label: 'Backend Connection', value: 'CONNECTED' },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex items-center justify-between px-3 py-2">
                      <span className="text-xs text-gray-500">{label}</span>
                      <span className="text-xs font-semibold text-gray-800 font-mono">{value}</span>
                    </div>
                  ))}
                </div>

                {/* ── Latest values ── */}
                {collectorStatus.latest_reading ? (
                  <div className="rounded-xl bg-gray-50 border border-gray-200 p-3 space-y-2">
                    <p className="text-xs font-semibold text-gray-700">Latest Values</p>
                    <div className="grid grid-cols-3 gap-3">
                      {[
                        { label: 'Temperature', key: 'temperature', unit: '°C' },
                        { label: 'Pressure',    key: 'pressure',    unit: ''   },
                        { label: 'pH',          key: 'ph',          unit: ''   },
                      ].map(({ label, key, unit }) => {
                        const v = collectorStatus.latest_reading[key]
                        return (
                          <div key={key} className="rounded-lg bg-white border border-gray-200 px-3 py-2">
                            <p className="text-xs text-gray-500 mb-0.5">{label}</p>
                            <p className="text-sm font-bold text-gray-800 font-mono">
                              {v != null && !Number.isNaN(v) ? `${v}${unit}` : '—'}
                            </p>
                          </div>
                        )
                      })}
                    </div>
                    <p className="text-xs text-gray-400">
                      Last updated: {collectorStatus.last_received_at
                        ? new Date(collectorStatus.last_received_at).toLocaleTimeString()
                        : '—'}
                    </p>
                  </div>
                ) : (
                  <div className="rounded-xl bg-gray-50 border border-gray-200 px-3 py-4 text-center text-xs text-gray-400">
                    No readings received yet
                  </div>
                )}

                {/* ── Collector configuration (read-only, remote) ── */}
                <div className="rounded-xl bg-amber-50 border border-amber-200 p-3 space-y-2">
                  <p className="text-xs font-semibold text-amber-800">Collector Configuration</p>
                  <p className="text-xs text-amber-700 leading-relaxed">
                    The collector runs on the Pro-Server EX machine. Settings below are configured
                    locally on that machine in <code className="bg-amber-100 px-1 rounded">collector_config.json</code>.
                  </p>
                  <div className="space-y-1 pt-1">
                    {[
                      { label: 'Collector Endpoint', value: `${window.location.protocol}//${window.location.hostname}:5000/api/collector/reading` },
                      { label: 'Authentication',     value: 'Configured on Pro-Server EX machine' },
                      { label: 'Configuration',      value: 'Configured on Pro-Server EX machine' },
                    ].map(({ label, value }) => (
                      <div key={label} className="flex items-start justify-between gap-2">
                        <span className="text-xs text-amber-700 shrink-0">{label}</span>
                        <span className="text-xs font-mono text-amber-900 text-right break-all">{value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div className="rounded-xl bg-gray-50 border border-gray-200 px-3 py-4 text-center text-xs text-gray-400">
                Loading collector status…
              </div>
            )}
          </div>
        </Section>

</>
)}

{me?.collector_available && (
<>
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

</>
)}

</>
)}

                {/* ── Section 9: Admin Info ─────────────────────────────────────────── */}
        <Section title="Admin Info" icon={Info}>
          <div className="space-y-3">
            {[
              { label: 'Dashboard Passcode', value: '••••  (4 digits)', icon: '🔐' },
              { label: 'Server Host', value: window.location.hostname, icon: <Server size={13} /> },
              { label: 'Backend Port', value: '5000 (HTTPS)', icon: '🌐' },
              { label: 'App Version', value: health?.version || 'v1.0.0', icon: '📦' },
              { label: 'Environment', value: health?.environment || 'development', icon: '⚙️' },
              { label: 'Live data', value: me?.collector_available ? 'Pro-Server live collector / Excel reader' : 'Excel live reader', icon: '📊' },
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