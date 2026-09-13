/**
 * src/pages/SubscribersPage.jsx
 *
 * Subscriber management with:
 *  - Active / Disabled badge per subscriber card
 *  - "Disable" / "Enable" button (PATCH /disable or /enable)
 *  - "Remove" button (DELETE) with confirmation modal
 *  - PasswordConfirmModal gates all Add / Disable / Enable / Remove actions
 *  - Mobile app PIN management unchanged
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Plus, Trash2, Key, Check, Phone, Mail,
  ChevronDown, ChevronUp, Users, ChevronLeft, ChevronRight,
  AlertTriangle, Ban, PlayCircle,
} from 'lucide-react'
import {
  fetchSubscribers, addSubscriber, deleteSubscriber,
  setSubscriberPin, disableSubscriber, enableSubscriber,
} from '../services/api.js'
import Modal from '../components/shared/Modal.jsx'
import PasswordConfirmModal from '../components/PasswordConfirmModal.jsx'
import ErrorState from '../components/ErrorState'
import EmptyState from '../components/EmptyState'
import SubscriberProfilesPage from './SubscriberProfilesPage'

// ── Constants ──────────────────────────────────────────────────────────────────
const PAGE_SIZE = 6

const EMPTY_FORM = { name: '', phone: '', email: '', pin: '', confirmPin: '' }
const EMPTY_ERRORS = { name: '', phone: '', email: '', pin: '', confirmPin: '' }

// ── Validators ─────────────────────────────────────────────────────────────────
function validateForm(form) {
  const errors = { ...EMPTY_ERRORS }
  let valid = true

  if (!form.name.trim()) { errors.name = 'Name is required'; valid = false }

  const phone = form.phone.trim().replace(/\D/g, '')
  if (!phone)               { errors.phone = 'Phone number is required'; valid = false }
  else if (phone.length !== 10) { errors.phone = 'Must be exactly 10 digits'; valid = false }

  const emailRx = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!form.email.trim())         { errors.email = 'Email is required'; valid = false }
  else if (!emailRx.test(form.email.trim())) { errors.email = 'Enter a valid email address'; valid = false }

  if (form.pin) {
    if (!/^\d{4}$/.test(form.pin))     { errors.pin = 'PIN must be exactly 4 digits'; valid = false }
    else if (form.pin !== form.confirmPin) { errors.confirmPin = 'PINs do not match'; valid = false }
  }

  return { errors, valid }
}

function FieldError({ msg }) {
  if (!msg) return null
  return <p style={{ color: '#EF4444', fontSize: 11, marginTop: 3 }}>{msg}</p>
}

const AVATAR_COLORS = ['#7C3AED', '#2563EB', '#059669', '#D97706', '#DC2626', '#7C3AED', '#0891B2', '#9333EA']
const avatarColor = (idx) => AVATAR_COLORS[idx % AVATAR_COLORS.length]

// ── Main component ─────────────────────────────────────────────────────────────
export default function SubscribersPage() {
  const [activeTab,  setActiveTab]  = useState('subscribers')
  const [subs,       setSubs]       = useState([])
  const [loading,    setLoading]    = useState(false)
  const [fetchError, setFetchError] = useState(null)
  const [showForm,   setShowForm]   = useState(false)
  const [form,       setForm]       = useState(EMPTY_FORM)
  const [errors,     setErrors]     = useState(EMPTY_ERRORS)
  const [saving,     setSaving]     = useState(false)
  const [formErr,    setFormErr]    = useState('')
  const [page,       setPage]       = useState(0)

  // PIN modal
  const [pinModal,   setPinModal]   = useState(null)
  const [pinValue,   setPinValue]   = useState('')
  const [pinConfirm, setPinConfirm] = useState('')
  const [pinSaving,  setPinSaving]  = useState(false)
  const [pinErr,     setPinErr]     = useState('')

  // Delete confirmation modal
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting,     setDeleting]     = useState(false)

  // Password confirm modal state
  // pendingAction: { type: 'add'|'disable'|'enable'|'remove', target: subscriber|null, formData: obj|null }
  const [pendingAction, setPendingAction] = useState(null)
  const [pwdError,      setPwdError]      = useState(null)

  // ── Load ────────────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true)
    setFetchError(null)
    try { setSubs(await fetchSubscribers()) }
    catch (err) { setFetchError(err?.message || 'Could not load subscribers') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  // ── Field updater ───────────────────────────────────────────────────────────
  const setField = (field, value) => {
    setForm(f => ({ ...f, [field]: value }))
    setErrors(e => ({ ...e, [field]: '' }))
  }

  // ── Add subscriber — gated by PasswordConfirmModal ──────────────────────────
  const handleAddClick = (e) => {
    e.preventDefault()
    const { errors: errs, valid } = validateForm(form)
    setErrors(errs)
    if (!valid) return
    // Queue the add action behind the password modal
    setPendingAction({ type: 'add', target: null, formData: { ...form } })
    setPwdError(null)
  }

  const doAdd = async (password, formData) => {
    setSaving(true)
    setFormErr('')
    const nextOrder = subs.length > 0
      ? Math.max(...subs.map(s => s.escalation_order ?? 0)) + 1
      : 1
    try {
      await addSubscriber({
        name:             formData.name.trim(),
        phone:            formData.phone.trim().replace(/\D/g, ''),
        email:            formData.email.trim(),
        escalation_order: nextOrder,
        ...(formData.pin ? { pin: formData.pin } : {}),
      }, password)
      setForm(EMPTY_FORM)
      setErrors(EMPTY_ERRORS)
      setShowForm(false)
      setPendingAction(null)
      load()
    } catch (err) {
      if (err.message?.includes('401')) {
        setPwdError('Incorrect password')
      } else {
        setPendingAction(null)
        setFormErr(err.message || 'Failed to add subscriber')
      }
    } finally {
      setSaving(false)
    }
  }

  // ── Disable ─────────────────────────────────────────────────────────────────
  const handleDisableClick = (sub) => {
    setPendingAction({ type: 'disable', target: sub, formData: null })
    setPwdError(null)
  }

  const doDisable = async (password, sub) => {
    try {
      await disableSubscriber(sub.id, password)
      setPendingAction(null)
      load()
    } catch (err) {
      if (err.message?.includes('401')) setPwdError('Incorrect password')
      else { setPendingAction(null); alert('Disable failed: ' + err.message) }
    }
  }

  // ── Enable ──────────────────────────────────────────────────────────────────
  const handleEnableClick = (sub) => {
    setPendingAction({ type: 'enable', target: sub, formData: null })
    setPwdError(null)
  }

  const doEnable = async (password, sub) => {
    try {
      await enableSubscriber(sub.id, password)
      setPendingAction(null)
      load()
    } catch (err) {
      if (err.message?.includes('401')) setPwdError('Incorrect password')
      else { setPendingAction(null); alert('Enable failed: ' + err.message) }
    }
  }

  // ── Remove — confirmation modal, then PasswordConfirmModal ──────────────────
  const handleDeleteClick = (sub) => setDeleteTarget(sub)

  const handleDeleteConfirmed = () => {
    // Replace the simple confirm modal with password confirm
    setPendingAction({ type: 'remove', target: deleteTarget, formData: null })
    setDeleteTarget(null)
    setPwdError(null)
  }

  const doDelete = async (password, sub) => {
    setDeleting(true)
    try {
      await deleteSubscriber(sub.id, password)
      setPendingAction(null)
      const newTotal = subs.length - 1
      const maxPage  = Math.max(0, Math.ceil(newTotal / PAGE_SIZE) - 1)
      if (page > maxPage) setPage(maxPage)
      load()
    } catch (err) {
      if (err.message?.includes('401')) setPwdError('Incorrect password')
      else { setPendingAction(null); alert('Delete failed: ' + err.message) }
    } finally {
      setDeleting(false)
    }
  }

  // ── Master confirm dispatcher ────────────────────────────────────────────────
  const handlePasswordConfirm = (password) => {
    setPwdError(null)
    if (!pendingAction) return
    const { type, target, formData } = pendingAction
    if (type === 'add')     doAdd(password, formData)
    if (type === 'disable') doDisable(password, target)
    if (type === 'enable')  doEnable(password, target)
    if (type === 'remove')  doDelete(password, target)
  }

  const actionLabel = () => {
    if (!pendingAction) return ''
    const { type, target } = pendingAction
    if (type === 'add')     return 'add subscriber'
    if (type === 'disable') return `disable ${target?.name}`
    if (type === 'enable')  return `enable ${target?.name}`
    if (type === 'remove')  return `permanently remove ${target?.name}`
    return 'confirm'
  }

  // ── Set / change PIN ────────────────────────────────────────────────────────
  const handleSetPin = async () => {
    if (!/^\d{4}$/.test(pinValue)) { setPinErr('PIN must be exactly 4 digits'); return }
    if (pinValue !== pinConfirm)   { setPinErr('PINs do not match'); return }
    setPinSaving(true)
    setPinErr('')
    try {
      await setSubscriberPin(pinModal.id, pinValue)
      setPinModal(null)
      setPinValue('')
      setPinConfirm('')
      load()
    } catch (err) {
      setPinErr(err.message || 'Failed to set PIN')
    } finally {
      setPinSaving(false)
    }
  }

  // ── Pagination ──────────────────────────────────────────────────────────────
  const totalPages = Math.ceil(subs.length / PAGE_SIZE)
  const pageSubs   = subs.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-5">

      {/* ── Tab switcher ────────────────────────────────────────────────────── */}
      <div className="sub-tabs">
        <button
          className={`sub-tab-btn${activeTab === 'subscribers' ? ' active' : ''}`}
          onClick={() => setActiveTab('subscribers')}
        >
          Subscribers
        </button>
        <button
          className={`sub-tab-btn${activeTab === 'profiles' ? ' active' : ''}`}
          onClick={() => setActiveTab('profiles')}
        >
          Profiles
        </button>
      </div>

      {/* ── Profiles tab ────────────────────────────────────────────────────── */}
      {activeTab === 'profiles' && <SubscriberProfilesPage />}

      {/* ── Subscribers tab ─────────────────────────────────────────────────── */}
      {activeTab === 'subscribers' && <>

      {/* ── Header row ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-purple-100 flex items-center justify-center">
            <Users size={20} className="text-purple-600" />
          </div>
          <div>
            <p className="text-sm font-bold text-gray-900">
              {subs.length} Subscriber{subs.length !== 1 ? 's' : ''}
            </p>
            <p className="text-xs text-gray-500">Active subscribers are notified simultaneously on breach</p>
          </div>
        </div>
        <button
          onClick={() => { setShowForm(v => !v); setErrors(EMPTY_ERRORS); setFormErr('') }}
          className="btn btn-primary"
        >
          {showForm ? <ChevronUp size={15} /> : <Plus size={15} />}
          {showForm ? 'Cancel' : 'Add Subscriber'}
        </button>
      </div>

      {/* ── Add subscriber form ──────────────────────────────────────────────── */}
      {showForm && (
        <div className="card p-6">
          <h3 className="text-sm font-semibold text-gray-800 mb-5">New Subscriber</h3>
          <form onSubmit={handleAddClick} noValidate>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-5 gap-y-4">

              <div>
                <label className="text-xs text-gray-500 mb-1 block font-semibold">Name *</label>
                <input className="form-input" placeholder="e.g. Harya" value={form.name}
                  onChange={e => setField('name', e.target.value)} />
                <FieldError msg={errors.name} />
              </div>

              <div>
                <label className="text-xs text-gray-500 mb-1 block font-semibold">Phone Number * (10 digits)</label>
                <input className="form-input" placeholder="e.g. 9876543210" inputMode="numeric" maxLength={10}
                  value={form.phone} onChange={e => setField('phone', e.target.value.replace(/\D/g, ''))} />
                <FieldError msg={errors.phone} />
              </div>

              <div className="md:col-span-2">
                <label className="text-xs text-gray-500 mb-1 block font-semibold">Email *</label>
                <input className="form-input" type="email" placeholder="e.g. harya@example.com"
                  value={form.email} onChange={e => setField('email', e.target.value)} />
                <FieldError msg={errors.email} />
              </div>

              <div>
                <label className="text-xs text-gray-500 mb-1 block font-semibold">
                  Mobile App PIN <span className="text-gray-400 font-normal">(4 digits, optional)</span>
                </label>
                <input className="form-input tracking-widest text-center" type="password"
                  inputMode="numeric" placeholder="••••" maxLength={4}
                  value={form.pin} onChange={e => setField('pin', e.target.value.replace(/\D/g, ''))} />
                <FieldError msg={errors.pin} />
              </div>

              {form.pin && (
                <div>
                  <label className="text-xs text-gray-500 mb-1 block font-semibold">Confirm PIN *</label>
                  <input className="form-input tracking-widest text-center" type="password"
                    inputMode="numeric" placeholder="••••" maxLength={4}
                    value={form.confirmPin} onChange={e => setField('confirmPin', e.target.value.replace(/\D/g, ''))} />
                  <FieldError msg={errors.confirmPin} />
                </div>
              )}
            </div>

            <p style={{ fontSize: 11, color: '#6B7280', marginTop: 12 }}>
              💡 This PIN lets the subscriber log into the mobile app.
            </p>

            {formErr && (
              <p className="text-xs text-red-600 mt-3 flex items-center gap-1">
                <AlertTriangle size={12} /> {formErr}
              </p>
            )}

            <div className="flex justify-end gap-2 mt-5 pt-4 border-t border-gray-100">
              <button type="button" onClick={() => setShowForm(false)} className="btn btn-ghost btn-sm">
                Cancel
              </button>
              <button type="submit" disabled={saving} className="btn btn-primary btn-sm">
                {saving ? 'Saving…' : 'Add Subscriber'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── Subscriber cards ─────────────────────────────────────────────────── */}
      {fetchError && !loading ? (
        <ErrorState message={fetchError} onRetry={load} />
      ) : loading && subs.length === 0 ? (
        <div className="text-center py-12 text-gray-400">Loading…</div>
      ) : subs.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={Users}
            title="No subscribers configured"
            description="Add a subscriber to receive breach alerts"
          />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {pageSubs.map((s, pageIdx) => {
              const globalIdx = page * PAGE_SIZE + pageIdx
              const color     = avatarColor(globalIdx)
              const isActive  = s.active !== false && s.is_active !== 0

              return (
                <div
                  key={s.id}
                  className="card p-5 flex flex-col gap-4"
                  style={{
                    minHeight: 200,
                    opacity:   isActive ? 1 : 0.55,
                    border:    isActive ? undefined : '1px dashed #CBD5E1',
                  }}
                >
                  {/* Card header */}
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="font-bold text-gray-900 text-base">{s.name}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span
                          className="inline-block text-xs font-semibold px-2 py-0.5 rounded-full"
                          style={{ background: color + '18', color }}
                        >
                          Subscriber {s.escalation_order}
                        </span>
                        {/* Active / Disabled badge */}
                        <span
                          className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full"
                          style={isActive
                            ? { background: '#DCFCE7', color: '#16A34A' }
                            : { background: '#F1F5F9', color: '#64748B' }
                          }
                        >
                          <span
                            style={{
                              display: 'inline-block', width: 6, height: 6,
                              borderRadius: '50%',
                              background: isActive ? '#16A34A' : '#94A3B8',
                            }}
                          />
                          {isActive ? 'Active' : 'Disabled'}
                        </span>
                      </div>
                    </div>
                    <div
                      className="w-10 h-10 rounded-xl flex items-center justify-center font-bold text-white text-sm flex-shrink-0"
                      style={{ background: isActive ? color : '#94A3B8' }}
                    >
                      {s.name.charAt(0).toUpperCase()}
                    </div>
                  </div>

                  {/* Contact info */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-xs text-gray-600">
                      <Phone size={12} className="text-gray-400 flex-shrink-0" />
                      <span>{s.phone}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-600">
                      <Mail size={12} className="text-gray-400 flex-shrink-0" />
                      <span className="truncate">{s.email}</span>
                    </div>
                  </div>

                  {/* PIN status */}
                  <div className="flex items-center gap-2 py-2 px-3 rounded-lg bg-gray-50 mt-auto">
                    {s.has_pin ? (
                      <>
                        <Check size={14} className="text-emerald-500" />
                        <span className="text-xs text-emerald-700 font-medium">
                          Mobile PIN set — can log into app
                        </span>
                      </>
                    ) : (
                      <>
                        <Key size={14} className="text-amber-400" />
                        <span className="text-xs text-amber-700">
                          No PIN — cannot log into mobile app yet
                        </span>
                      </>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex gap-2">
                    {/* PIN button */}
                    <button
                      onClick={() => { setPinModal(s); setPinValue(''); setPinConfirm(''); setPinErr('') }}
                      className="btn btn-ghost btn-sm"
                      style={{ flex: 1 }}
                    >
                      <Key size={13} /> {s.has_pin ? 'Change PIN' : 'Set PIN'}
                    </button>

                    {/* Disable / Enable toggle */}
                    {isActive ? (
                      <button
                        onClick={() => handleDisableClick(s)}
                        className="btn btn-sm"
                        style={{ background: '#FFF7ED', color: '#C2410C', border: '1px solid #FED7AA' }}
                        title="Disable subscriber"
                      >
                        <Ban size={13} />
                      </button>
                    ) : (
                      <button
                        onClick={() => handleEnableClick(s)}
                        className="btn btn-sm"
                        style={{ background: '#DCFCE7', color: '#16A34A', border: '1px solid #86EFAC' }}
                        title="Enable subscriber"
                      >
                        <PlayCircle size={13} />
                      </button>
                    )}

                    {/* Remove */}
                    <button
                      onClick={() => handleDeleteClick(s)}
                      className="btn btn-danger btn-sm"
                      title="Remove subscriber permanently"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>

          {/* ── Pagination ───────────────────────────────────────────────────── */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-1">
              <span className="text-xs text-gray-400">
                Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, subs.length)} of {subs.length}
              </span>
              <div className="flex items-center gap-2">
                <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                  className="btn btn-ghost btn-sm">
                  <ChevronLeft size={14} /> Previous
                </button>
                {Array.from({ length: totalPages }, (_, i) => (
                  <button key={i} onClick={() => setPage(i)}
                    className={`w-7 h-7 rounded-lg text-xs font-semibold transition-all ${
                      i === page ? 'bg-purple-600 text-white' : 'bg-white border border-gray-200 text-gray-600 hover:border-purple-300'
                    }`}
                  >{i + 1}</button>
                ))}
                <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1} className="btn btn-ghost btn-sm">
                  Next <ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Set / Change PIN modal ────────────────────────────────────────────── */}
      <Modal
        isOpen={!!pinModal}
        onClose={() => setPinModal(null)}
        title={`${pinModal?.has_pin ? 'Change' : 'Set'} PIN — ${pinModal?.name}`}
        footer={
          <>
            <button onClick={() => setPinModal(null)} className="btn btn-ghost btn-sm">Cancel</button>
            <button onClick={handleSetPin} disabled={pinSaving} className="btn btn-primary btn-sm">
              {pinSaving ? 'Saving…' : 'Save PIN'}
            </button>
          </>
        }
      >
        <p className="text-sm text-gray-600 mb-4">
          Set a <strong>4-digit PIN</strong> for <strong>{pinModal?.name}</strong>.
          This PIN is used to log into the mobile monitoring app.
        </p>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 font-semibold block mb-1">New PIN</label>
            <input className="form-input text-center text-xl tracking-widest" type="password"
              inputMode="numeric" placeholder="••••" maxLength={4}
              value={pinValue}
              onChange={e => { setPinValue(e.target.value.replace(/\D/g, '')); setPinErr('') }}
              autoFocus />
          </div>
          <div>
            <label className="text-xs text-gray-500 font-semibold block mb-1">Confirm PIN</label>
            <input className="form-input text-center text-xl tracking-widest" type="password"
              inputMode="numeric" placeholder="••••" maxLength={4}
              value={pinConfirm}
              onChange={e => { setPinConfirm(e.target.value.replace(/\D/g, '')); setPinErr('') }} />
          </div>
        </div>
        {pinErr && <p className="text-xs text-red-600 mt-2">{pinErr}</p>}
        <p style={{ fontSize: 11, color: '#6B7280', marginTop: 12 }}>
          🔒 Stored as a SHA-256 hash — never saved in plain text.
        </p>
      </Modal>

      {/* ── Delete confirmation modal (first step) ────────────────────────────── */}
      <Modal
        isOpen={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Remove Subscriber"
        footer={
          <>
            <button onClick={() => setDeleteTarget(null)} className="btn btn-ghost btn-sm">
              Cancel
            </button>
            <button onClick={handleDeleteConfirmed} className="btn btn-danger btn-sm">
              Yes, Remove
            </button>
          </>
        }
      >
        <div className="flex flex-col items-center gap-3 py-2 text-center">
          <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
            <Trash2 size={22} className="text-red-500" />
          </div>
          <p className="text-sm font-semibold text-gray-800">
            Remove <span style={{ color: '#7C3AED' }}>{deleteTarget?.name}</span>?
          </p>
          <p className="text-xs text-gray-500 max-w-xs">
            Are you sure you want to permanently remove <strong>{deleteTarget?.name}</strong>?
            This cannot be undone. They will no longer receive alerts or log into the mobile app.
          </p>
        </div>
      </Modal>

      {/* ── Password Confirm Modal (gates all data-changing actions) ─────────── */}
      <PasswordConfirmModal
        isOpen={!!pendingAction}
        actionLabel={actionLabel()}
        onConfirm={handlePasswordConfirm}
        onCancel={() => { setPendingAction(null); setPwdError(null) }}
        error={pwdError}
      />

      </> /* end subscribers tab */}

    </div>
  )
}
