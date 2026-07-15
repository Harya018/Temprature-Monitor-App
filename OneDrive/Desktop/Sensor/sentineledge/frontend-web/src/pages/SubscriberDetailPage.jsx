/**
 * src/pages/SubscriberDetailPage.jsx
 *
 * Detail view for a single subscriber.
 * Route: /subscribers/profiles/:id
 *
 * Three sections:
 *   A — Profile Card (inline edit with Save / Cancel)
 *   B — Acknowledgement History table
 *   C — Analytics Placeholder
 */
import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Edit3, Save, X, User2,
  Phone, Mail, MapPin, Briefcase, Clock, CreditCard,
  CheckCircle2, BarChart2,
} from 'lucide-react'
import { fetchSubscriber, updateSubscriber, fetchSubscriberAcks } from '../services/api.js'
import { useToast, ToastContainer } from '../components/shared/Toast.jsx'

// ── Helpers ───────────────────────────────────────────────────────────────────
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000

function toIST(utcStr) {
  if (!utcStr) return '—'
  try {
    const d   = new Date(utcStr)
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
  } catch { return utcStr }
}

function fmtResponseTime(secs) {
  if (secs == null) return '—'
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

// Returns displayable value or null; '—' rendered separately so it stays dim
const rawVal = (v) => (v ?? null) || null

// ── Severity badge ────────────────────────────────────────────────────────────
// Section 6: badges — keep background, ensure text is clearly visible
const SEV_STYLE = {
  HIGH:      { bg: '#FEE2E2', color: '#991B1B', text: 'HIGH'      },
  EMERGENCY: { bg: '#FEE2E2', color: '#991B1B', text: 'EMERGENCY' },
  CRITICAL:  { bg: '#FEF3C7', color: '#92400E', text: 'CRITICAL'  },
  WARNING:   { bg: '#D1FAE5', color: '#065F46', text: 'WARNING'   },
  MEDIUM:    { bg: '#FEF3C7', color: '#92400E', text: 'MEDIUM'    },
  LOW:       { bg: '#D1FAE5', color: '#065F46', text: 'LOW'       },
}

function SeverityBadge({ sev }) {
  const s = SEV_STYLE[sev?.toUpperCase()] || SEV_STYLE.LOW
  return (
    <span
      className="text-xs font-bold px-2 py-0.5 rounded-full"
      style={{ background: s.bg, color: s.color }}
    >
      {s.text}
    </span>
  )
}

// ── Editable field ────────────────────────────────────────────────────────────
// Section 4 (label): text-gray-600 (#4B5563)
// Section 5 (value): text-gray-900 font-medium (#111827)
// Section 7 (dash):  text-gray-400 (#9CA3AF)
function Field({ icon: Icon, label, value, editMode, name, onChange }) {
  const isEmpty = !value
  return (
    <div className="flex items-start gap-3">
      <div
        className="mt-0.5 w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ background: 'rgba(124,58,237,0.15)' }}
      >
        {/* Icon color intentionally unchanged */}
        <Icon size={14} style={{ color: '#A5B4FC' }} />
      </div>
      <div className="flex-1 min-w-0">
        {/* Section 4: card label */}
        <p className="text-xs mb-1" style={{ color: '#4B5563' }}>{label}</p>
        {editMode ? (
          <input
            type="text"
            name={name}
            value={value ?? ''}
            onChange={onChange}
            className="w-full bg-transparent border border-white/20 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-violet-500 transition-colors"
            style={{ color: '#111827' }}
          />
        ) : (
          /* Section 5: card value / Section 7: dash */
          <p
            className={`text-sm truncate ${isEmpty ? '' : 'font-medium'}`}
            style={{ color: isEmpty ? '#9CA3AF' : '#111827' }}
          >
            {isEmpty ? '—' : value}
          </p>
        )}
      </div>
    </div>
  )
}

// ── Loading spinner ───────────────────────────────────────────────────────────
function Spinner() {
  return (
    <div className="flex items-center justify-center h-48">
      <div className="w-8 h-8 border-4 border-violet-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

// ── Placeholder chart box ─────────────────────────────────────────────────────
function ChartPlaceholder({ label }) {
  return (
    <div
      className="flex-1 flex flex-col items-center justify-center rounded-xl p-8 min-h-44"
      style={{
        background: 'rgba(255,255,255,0.03)',
        border: '2px dashed rgba(255,255,255,0.12)',
      }}
    >
      {/* Section 9: helper text */}
      <p className="text-sm font-medium text-center" style={{ color: '#4B5563' }}>
        {label}
      </p>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function SubscriberDetailPage() {
  const { id }    = useParams()
  const navigate  = useNavigate()
  const { toasts, addToast, dismiss } = useToast()

  // Section A state
  const [sub,      setSub]      = useState(null)
  const [subErr,   setSubErr]   = useState(null)
  const [subLoad,  setSubLoad]  = useState(true)
  const [editMode, setEditMode] = useState(false)
  const [draft,    setDraft]    = useState({})
  const [saving,   setSaving]   = useState(false)

  // Section B state
  const [acks,     setAcks]     = useState([])
  const [acksLoad, setAcksLoad] = useState(true)
  const [acksErr,  setAcksErr]  = useState(null)

  // ── Load subscriber ────────────────────────────────────────────────────────
  const loadSub = useCallback(async () => {
    setSubLoad(true)
    setSubErr(null)
    try {
      const data = await fetchSubscriber(id)
      setSub(data)
      setDraft({ ...data })
    } catch {
      setSubErr('Could not load subscriber profile.')
    } finally {
      setSubLoad(false)
    }
  }, [id])

  // ── Load acks ─────────────────────────────────────────────────────────────
  const loadAcks = useCallback(async () => {
    setAcksLoad(true)
    setAcksErr(null)
    try {
      const data = await fetchSubscriberAcks(id)
      setAcks(data)
    } catch {
      setAcksErr('Could not load acknowledgement history.')
    } finally {
      setAcksLoad(false)
    }
  }, [id])

  useEffect(() => {
    loadSub()
    loadAcks()
  }, [loadSub, loadAcks])

  // ── Edit handlers ──────────────────────────────────────────────────────────
  const handleChange = (e) => {
    const { name, value } = e.target
    setDraft((prev) => ({ ...prev, [name]: value }))
  }

  const handleCancel = () => {
    setDraft({ ...sub })
    setEditMode(false)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const changed = {}
      const PROFILE_FIELDS = ['name','phone','email','employee_id','department','designation','shift_timing','address','escalation_order']
      PROFILE_FIELDS.forEach((k) => {
        if (draft[k] !== sub[k]) changed[k] = draft[k] || null
      })
      const updated = await updateSubscriber(id, changed)
      setSub(updated)
      setDraft({ ...updated })
      setEditMode(false)
      addToast({ type: 'success', message: 'Profile updated successfully' })
    } catch {
      addToast({ type: 'error', message: 'Update failed — please try again' })
    } finally {
      setSaving(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      {/* Back nav — Section 9: helper/nav text */}
      <button
        onClick={() => navigate('/subscribers/profiles')}
        className="flex items-center gap-2 text-sm font-medium transition-colors hover:text-gray-900"
        style={{ color: '#4B5563' }}
      >
        <ArrowLeft size={16} />
        Back to Subscriber Profiles
      </button>

      {/* ── SECTION A: Profile Card ──────────────────────────────────────── */}
      <div
        className="rounded-2xl border border-white/10 overflow-hidden"
        style={{ background: 'rgba(255,255,255,0.04)' }}
      >
        {/* Card header */}
        <div
          className="px-6 py-4 flex items-center justify-between border-b border-white/10"
          style={{ background: 'rgba(124,58,237,0.08)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ background: '#7C3AED' }}
            >
              {/* Icon inside colored chip stays white */}
              <User2 size={20} className="text-white" />
            </div>
            <div>
              {/* Section 8: section heading */}
              <h2 className="text-base font-bold" style={{ color: '#111827' }}>
                {sub?.name ?? 'Subscriber Profile'}
              </h2>
              {/* Section 9: subtext */}
              <p className="text-xs" style={{ color: '#4B5563' }}>
                {sub?.employee_id ? `EMP — ${sub.employee_id}` : 'No employee ID set'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {editMode ? (
              <>
                <button
                  onClick={handleCancel}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium hover:bg-white/10 transition-colors"
                  style={{ color: '#374151' }}
                >
                  <X size={14} /> Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors"
                  style={{ background: '#7C3AED', color: '#fff', opacity: saving ? 0.6 : 1 }}
                >
                  <Save size={14} />
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </>
            ) : (
              <button
                onClick={() => setEditMode(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium hover:bg-white/10 transition-colors"
                style={{ color: '#374151' }}
              >
                <Edit3 size={14} /> Edit
              </button>
            )}
          </div>
        </div>

        {/* Card body */}
        {subLoad ? (
          <Spinner />
        ) : subErr ? (
          <div className="p-8 text-center text-red-400 text-sm">{subErr}</div>
        ) : (
          <div className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-5">
            <Field icon={CreditCard}  label="Employee ID"   name="employee_id"  value={editMode ? draft.employee_id  : sub.employee_id}  editMode={editMode} onChange={handleChange} />
            <Field icon={User2}       label="Full Name"     name="name"         value={editMode ? draft.name         : sub.name}          editMode={editMode} onChange={handleChange} />
            <Field icon={Briefcase}   label="Department"    name="department"   value={editMode ? draft.department   : sub.department}    editMode={editMode} onChange={handleChange} />
            <Field icon={Briefcase}   label="Designation"   name="designation"  value={editMode ? draft.designation  : sub.designation}   editMode={editMode} onChange={handleChange} />
            <Field icon={Clock}       label="Shift Timing"  name="shift_timing" value={editMode ? draft.shift_timing : sub.shift_timing}  editMode={editMode} onChange={handleChange} />
            <Field icon={Phone}       label="Mobile"        name="phone"        value={editMode ? draft.phone        : sub.phone}         editMode={editMode} onChange={handleChange} />
            <Field icon={Mail}        label="Email"         name="email"        value={editMode ? draft.email        : sub.email}         editMode={editMode} onChange={handleChange} />
            <Field icon={MapPin}      label="Address"       name="address"      value={editMode ? draft.address      : sub.address}       editMode={editMode} onChange={handleChange} />
          </div>
        )}
      </div>

      {/* ── SECTION B: Acknowledgement History ──────────────────────────── */}
      <div
        className="rounded-2xl border border-white/10 overflow-hidden"
        style={{ background: 'rgba(255,255,255,0.04)' }}
      >
        <div className="px-6 py-4 border-b border-white/10 flex items-center gap-3">
          {/* Icon color unchanged */}
          <CheckCircle2 size={18} style={{ color: '#10B981' }} />
          {/* Section 8: section heading */}
          <h2 className="text-base font-bold" style={{ color: '#111827' }}>Acknowledgement History</h2>
          {!acksLoad && (
            <span
              className="ml-auto text-xs px-2 py-0.5 rounded-full font-medium"
              style={{ background: 'rgba(16,185,129,0.15)', color: '#065F46' }}
            >
              {acks.length} records
            </span>
          )}
        </div>

        {acksLoad ? (
          <Spinner />
        ) : acksErr ? (
          <div className="p-8 text-center text-red-400 text-sm">{acksErr}</div>
        ) : acks.length === 0 ? (
          <div className="p-10 text-center">
            <CheckCircle2 size={36} className="mx-auto mb-3" style={{ color: '#374151' }} />
            {/* Section 9: empty state */}
            <p className="text-sm" style={{ color: '#4B5563' }}>No acknowledgements found</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                {/* Section 2: table headers */}
                <tr
                  className="border-b border-white/10 text-xs uppercase tracking-wider font-semibold"
                  style={{ color: '#374151' }}
                >
                  <th className="px-4 py-3 text-left">Alert ID</th>
                  <th className="px-4 py-3 text-left">Sensor</th>
                  <th className="px-4 py-3 text-left">Severity</th>
                  <th className="px-4 py-3 text-right">Breach Temp</th>
                  <th className="px-4 py-3 text-left">Acknowledged At</th>
                  <th className="px-4 py-3 text-right">Response Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {acks.map((a) => (
                  <tr key={a.id} className="hover:bg-white/5 transition-colors">
                    {/* Section 3: table body values */}
                    <td className="px-4 py-3 font-mono text-xs font-medium" style={{ color: '#111827' }}>
                      #{a.alert_id}
                    </td>
                    <td className="px-4 py-3" style={{ color: a.sensor_id ? '#111827' : '#9CA3AF' }}>
                      {a.sensor_id || '—'}
                    </td>
                    <td className="px-4 py-3">
                      {/* Section 6: badges with visible text */}
                      <SeverityBadge sev={a.breach_severity} />
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs font-medium" style={{ color: '#111827' }}>
                      {a.breach_value != null ? `${Number(a.breach_value).toFixed(1)}°C` : <span style={{ color: '#9CA3AF' }}>—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs" style={{ color: '#374151' }}>
                      {toIST(a.acknowledged_at)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs font-semibold" style={{ color: '#065F46' }}>
                      {fmtResponseTime(a.response_time_seconds)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── SECTION C: Analytics Placeholder ────────────────────────────── */}
      <div
        className="rounded-2xl border border-white/10 overflow-hidden"
        style={{ background: 'rgba(255,255,255,0.04)' }}
      >
        <div className="px-6 py-4 border-b border-white/10 flex items-center gap-3">
          {/* Icon color unchanged */}
          <BarChart2 size={18} style={{ color: '#A5B4FC' }} />
          {/* Section 8: section heading */}
          <h2 className="text-base font-bold" style={{ color: '#111827' }}>Analytics Overview</h2>
          <span
            className="ml-auto text-xs px-2 py-0.5 rounded-full font-medium"
            style={{ background: 'rgba(165,180,252,0.12)', color: '#4338CA' }}
          >
            Pending Integration
          </span>
        </div>

        <div className="p-6 space-y-4">
          {/* Section 9: helper text */}
          <p className="text-sm" style={{ color: '#4B5563' }}>
            Analytics data from the data team will appear here
          </p>

          <div className="flex gap-4 flex-col sm:flex-row">
            <ChartPlaceholder label="Response Time Distribution (Pie Chart)" />
            <ChartPlaceholder label="Breach Frequency (Bar Chart)" />
          </div>

          {/* Section 9: footnote */}
          <p className="text-xs text-center pt-2" style={{ color: '#6B7280' }}>
            This section is reserved for the analytics team integration
          </p>
        </div>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </div>
  )
}
