/**
 * src/pages/AdminProfilePage.jsx
 *
 * Professional two-column admin profile page.
 *  LEFT  — avatar card with role info
 *  RIGHT — Update Credentials form with PIN strength indicator
 *
 * Flow:
 *  1. Shows current username from sessionStorage / GET /api/admin/profile
 *  2. Current PIN required; new username / new PIN are optional (blank = keep)
 *  3. On success → 2 s delay → clear session → redirect to /
 *  4. On 401 → "Current PIN is incorrect"
 */
import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Shield, Calendar, Lock, User, Eye, EyeOff,
  CheckCircle2, AlertCircle,
} from 'lucide-react'
import { getAdminProfile, updateAdminProfile } from '../services/api.js'

// ── PIN strength helper ───────────────────────────────────────────────────────
function pinStrength(pin) {
  const len = pin.trim().length
  if (len === 0) return null
  if (len < 6)  return { label: 'Weak',   color: '#EF4444', width: '33%'  }
  if (len < 10) return { label: 'Medium', color: '#F59E0B', width: '66%'  }
  return              { label: 'Strong', color: '#10B981', width: '100%' }
}

export default function AdminProfilePage() {
  const navigate = useNavigate()

  const [currentUsername, setCurrentUsername] = useState(
    sessionStorage.getItem('admin_username') || 'admin'
  )
  const loginTime = sessionStorage.getItem('login_time') || null

  // Form fields
  const [currentPin,  setCurrentPin]  = useState('')
  const [newUsername, setNewUsername] = useState('')
  const [newPin,      setNewPin]      = useState('')
  const [confirmPin,  setConfirmPin]  = useState('')

  // UI state
  const [showCurrentPin, setShowCurrentPin] = useState(false)
  const [showNewPin,     setShowNewPin]     = useState(false)
  const [saving,         setSaving]         = useState(false)
  const [result,         setResult]         = useState(null)    // {ok, msg}
  const [fieldErrors,    setFieldErrors]    = useState({})

  const currentPinRef = useRef(null)

  useEffect(() => {
    getAdminProfile()
      .then(d => { if (d?.username) setCurrentUsername(d.username) })
      .catch(() => {})
    currentPinRef.current?.focus()
  }, [])

  // ── Validation ──────────────────────────────────────────────────────────────
  const validate = () => {
    const errs = {}
    if (!currentPin.trim()) errs.currentPin = 'Current PIN is required'
    if (newUsername.trim() && !/^[a-zA-Z0-9_]{3,20}$/.test(newUsername.trim()))
      errs.newUsername = '3–20 characters: letters, digits, underscores only'
    if (newPin.trim() && (newPin.trim().length < 4 || newPin.trim().length > 20))
      errs.newPin = 'PIN must be 4–20 characters'
    if (newPin.trim() && newPin !== confirmPin)
      errs.confirmPin = 'PINs do not match'
    if (!newUsername.trim() && !newPin.trim())
      errs.general = 'Enter a new username, new PIN, or both'
    return errs
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setResult(null)
    const errs = validate()
    setFieldErrors(errs)
    if (Object.keys(errs).length > 0) return

    setSaving(true)
    try {
      await updateAdminProfile({
        current_pin:  currentPin.trim(),
        new_username: newUsername.trim() || undefined,
        new_pin:      newPin.trim()      || undefined,
      })
      setResult({ ok: true, msg: 'Profile updated. Logging you out…' })
      setTimeout(() => {
        sessionStorage.removeItem('admin_token')
        sessionStorage.removeItem('admin_username')
        sessionStorage.removeItem('authenticated')
        sessionStorage.removeItem('adminVerified')
        sessionStorage.removeItem('login_time')
        navigate('/', { replace: true })
      }, 2000)
    } catch (err) {
      const msg = err.message?.includes('401') ? 'Current PIN is incorrect'
        : err.message?.includes('409') ? 'Username already taken'
        : err.message?.includes('422') ? 'Validation error — check your inputs'
        : 'Update failed. Please try again.'
      setResult({ ok: false, msg })
    } finally {
      setSaving(false)
    }
  }

  const initials   = (currentUsername || 'A').charAt(0).toUpperCase()
  const strength   = pinStrength(newPin)

  // ── LEFT COLUMN: profile card ───────────────────────────────────────────────
  const ProfileCard = () => (
    <div
      className="card p-6 flex flex-col items-center gap-4 text-center"
      style={{
        background: 'linear-gradient(135deg, #f5f3ff, #ede9fe)',
        border: '1px solid #e9d5ff',
      }}
    >
      {/* Avatar */}
      <div
        className="w-24 h-24 rounded-full flex items-center justify-center shadow-lg"
        style={{ background: '#7C3AED' }}
      >
        <span className="text-3xl font-black text-white">{initials}</span>
      </div>

      {/* Name & title */}
      <div>
        <p className="text-xl font-bold text-gray-900">{currentUsername}</p>
        <p className="text-sm text-gray-500 mt-0.5">Main Administrator</p>
        <span
          className="inline-block mt-2 text-xs font-semibold px-3 py-1 rounded-full"
          style={{ background: '#ECFDF5', color: '#059669' }}
        >
          ● Active
        </span>
      </div>

      {/* Divider */}
      <div className="w-full border-t border-gray-100 my-1" />

      {/* Info rows */}
      <div className="w-full space-y-3 text-left">
        {[
          {
            icon: <Shield size={15} style={{ color: '#7C3AED' }} />,
            label: 'Role',
            value: 'Administrator',
          },
          {
            icon: <Calendar size={15} style={{ color: '#7C3AED' }} />,
            label: 'Last Login',
            value: loginTime
              ? new Date(loginTime).toLocaleString('en-GB', {
                  day: '2-digit', month: '2-digit', year: 'numeric',
                  hour: '2-digit', minute: '2-digit', second: '2-digit',
                })
              : 'This session',
          },
          {
            icon: <Lock size={15} style={{ color: '#7C3AED' }} />,
            label: 'Access',
            value: 'Full system access',
          },
        ].map(({ icon, label, value }) => (
          <div key={label} className="flex items-start gap-3">
            <div className="mt-0.5 flex-shrink-0">{icon}</div>
            <div>
              <p className="text-xs text-gray-500 font-medium">{label}</p>
              <p className="text-xs font-semibold text-gray-800 mt-0.5">{value}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )

  // ── RIGHT COLUMN: update form ───────────────────────────────────────────────
  const UpdateForm = () => (
    <div className="card p-6">
      {/* Header */}
      <div className="flex items-center gap-2 mb-5">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: '#EDE9FE' }}
        >
          <Lock size={15} style={{ color: '#7C3AED' }} />
        </div>
        <h3 className="text-sm font-semibold text-gray-800">Update Credentials</h3>
      </div>

      {/* Result banner */}
      {result && (
        <div
          className="flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm mb-4"
          style={{
            background:  result.ok ? '#F0FDF4' : '#FEF2F2',
            borderLeft: `3px solid ${result.ok ? '#10B981' : '#EF4444'}`,
          }}
        >
          {result.ok
            ? <CheckCircle2 size={15} style={{ color: '#10B981', flexShrink: 0, marginTop: 1 }} />
            : <AlertCircle  size={15} style={{ color: '#EF4444', flexShrink: 0, marginTop: 1 }} />
          }
          <span style={{ color: result.ok ? '#065F46' : '#991B1B' }}>{result.msg}</span>
        </div>
      )}

      {fieldErrors.general && (
        <p className="text-xs text-red-600 mb-3 flex items-center gap-1">
          <AlertCircle size={12} /> {fieldErrors.general}
        </p>
      )}

      <form onSubmit={handleSubmit} className="space-y-5" noValidate>

        {/* ── Current Verification ─── */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Current Verification
          </p>
          <div style={{ position: 'relative' }}>
            <Lock
              size={14}
              style={{
                position: 'absolute', left: 12, top: '50%',
                transform: 'translateY(-50%)', pointerEvents: 'none',
                color: '#9CA3AF', zIndex: 1,
              }}
            />
            <input
              ref={currentPinRef}
              type={showCurrentPin ? 'text' : 'password'}
              value={currentPin}
              onChange={e => { setCurrentPin(e.target.value); setFieldErrors(p => ({ ...p, currentPin: '' })); setResult(null) }}
              placeholder="Current PIN *"
              className={`form-input pr-10 ${fieldErrors.currentPin ? 'border-red-300' : ''}`}
              style={{ paddingLeft: '40px' }}
              autoComplete="current-password"
            />
            <button
              type="button"
              onClick={() => setShowCurrentPin(v => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              {showCurrentPin ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
          {fieldErrors.currentPin && (
            <p className="text-xs text-red-500 mt-1">{fieldErrors.currentPin}</p>
          )}
        </div>

        {/* Divider */}
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-dashed border-gray-200" />
          </div>
          <div className="relative flex justify-center">
            <span className="bg-white px-2 text-xs text-gray-400 font-medium">
              New Credentials (leave blank to keep current)
            </span>
          </div>
        </div>

        {/* ── New Details ─── */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            New Details
          </p>

          {/* New Username */}
          <div className="mb-4">
            <div style={{ position: 'relative' }}>
              <User
                size={14}
                style={{
                  position: 'absolute', left: 12, top: '50%',
                  transform: 'translateY(-50%)', pointerEvents: 'none',
                  color: '#9CA3AF', zIndex: 1,
                }}
              />
              <input
                type="text"
                value={newUsername}
                onChange={e => { setNewUsername(e.target.value); setFieldErrors(p => ({ ...p, newUsername: '', general: '' })); setResult(null) }}
                placeholder="New Username"
                className={`form-input ${fieldErrors.newUsername ? 'border-red-300' : ''}`}
                style={{ paddingLeft: '40px' }}
                autoComplete="username"
                autoCapitalize="none"
              />
            </div>
            {fieldErrors.newUsername
              ? <p className="text-xs text-red-500 mt-1">{fieldErrors.newUsername}</p>
              : <p className="text-xs text-gray-400 mt-1">3–20 characters, letters/digits/underscores only</p>
            }
          </div>

          {/* New PIN */}
          <div className="mb-4">
            <div style={{ position: 'relative' }}>
              <Lock
                size={14}
                style={{
                  position: 'absolute', left: 12, top: '50%',
                  transform: 'translateY(-50%)', pointerEvents: 'none',
                  color: '#9CA3AF', zIndex: 1,
                }}
              />
              <input
                type={showNewPin ? 'text' : 'password'}
                value={newPin}
                onChange={e => { setNewPin(e.target.value); setFieldErrors(p => ({ ...p, newPin: '', confirmPin: '', general: '' })); setResult(null) }}
                placeholder="New PIN (4–20 chars)"
                className={`form-input pr-10 ${fieldErrors.newPin ? 'border-red-300' : ''}`}
                style={{ paddingLeft: '40px' }}
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowNewPin(v => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showNewPin ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            {fieldErrors.newPin && (
              <p className="text-xs text-red-500 mt-1">{fieldErrors.newPin}</p>
            )}

            {/* PIN Strength bar */}
            {strength && (
              <div className="mt-2">
                <div className="flex justify-between mb-1">
                  <span className="text-xs text-gray-400">PIN Strength</span>
                  <span className="text-xs font-semibold" style={{ color: strength.color }}>{strength.label}</span>
                </div>
                <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{ width: strength.width, background: strength.color }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Confirm PIN — only when New PIN is typed */}
          {newPin && (
            <div>
              <div style={{ position: 'relative' }}>
                <Lock
                  size={14}
                  style={{
                    position: 'absolute', left: 12, top: '50%',
                    transform: 'translateY(-50%)', pointerEvents: 'none',
                    color: '#9CA3AF', zIndex: 1,
                  }}
                />
                <input
                  type="password"
                  value={confirmPin}
                  onChange={e => { setConfirmPin(e.target.value); setFieldErrors(p => ({ ...p, confirmPin: '' })); setResult(null) }}
                  placeholder="Confirm New PIN *"
                  className={`form-input ${
                    fieldErrors.confirmPin || (confirmPin && confirmPin !== newPin)
                      ? 'border-red-300' : ''
                  }`}
                  style={{ paddingLeft: '40px' }}
                  autoComplete="new-password"
                />
              </div>
              {(fieldErrors.confirmPin || (confirmPin && confirmPin !== newPin)) && (
                <p className="text-xs text-red-500 mt-1">
                  {fieldErrors.confirmPin || 'PINs do not match'}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={saving || result?.ok}
          className="w-full py-3 rounded-xl text-sm font-bold text-white transition-all disabled:opacity-50"
          style={{ background: '#7C3AED' }}
        >
          {saving ? 'Updating…' : 'Update Profile'}
        </button>

        {/* Warning */}
        <div
          className="flex gap-2 rounded-lg px-3 py-2.5"
          style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}
        >
          <span className="text-xs" style={{ color: '#92400E' }}>
            ⚠ After updating you will be logged out and must sign in again with your new credentials.
          </span>
        </div>

      </form>
    </div>
  )

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div>
        <h2 className="text-lg font-bold text-gray-900">Admin Profile</h2>
        <p className="text-xs text-gray-500 mt-0.5">Manage your login credentials</p>
      </div>

      {/* Two-column grid on desktop, stacked on mobile */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* LEFT — Profile card (1/3 width on desktop) */}
        <div className="lg:col-span-1">
          <ProfileCard />
        </div>

        {/* RIGHT — Update form (2/3 width on desktop) */}
        <div className="lg:col-span-2">
          <UpdateForm />
        </div>
      </div>
    </div>
  )
}
