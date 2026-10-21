/**
 * src/pages/AdminProfilePage.jsx
 *
 * "My account" for the signed-in admin (main or sub):
 *  LEFT  — who you are: sign-in name, role, company, last sign-in
 *  RIGHT — change YOUR OWN password (current password required)
 *
 * Each admin has their own account: changing the password here affects only you.
 * Your other sign-ins (other browsers / PCs) end; this one stays signed in.
 * Sign-in names are set by the Super Admin. On a company server, passwords are
 * managed on the main server (the page says so instead of showing the form).
 */
import { useState, useEffect } from 'react'
import { Shield, Calendar, Lock, Building2, Eye, EyeOff, CheckCircle2, AlertCircle } from 'lucide-react'
import { getAdminProfile, updateAdminProfile } from '../services/api.js'

// Same rule the server uses (and Super Admin when creating an admin)
function missing(pw) {
  const p = pw.trim(), out = []
  if (p.length < 10) out.push('10+ characters')
  if (!/[A-Z]/.test(p)) out.push('a capital letter')
  if (!/[a-z]/.test(p)) out.push('a small letter')
  if (!/\d/.test(p)) out.push('a number')
  if (!/[^A-Za-z0-9]/.test(p)) out.push('a symbol')
  return out
}

function strength(pw) {
  if (!pw.trim()) return null
  const n = missing(pw).length
  if (n >= 3) return { label: 'Weak',   color: '#EF4444', width: '25%'  }
  if (n >= 1) return { label: 'Almost', color: '#F59E0B', width: '66%'  }
  return            { label: 'Strong', color: '#10B981', width: '100%' }
}

const ROLE_LABEL = {
  main: 'Main Admin',
  sub: 'Sub Admin (view + acknowledge only)',
  super_admin: 'Super Admin',
}

function errorText(err) {
  const m = String(err?.message || '')
  const body = m.replace(/^HTTP \d+:\s*/, '')
  try {
    const j = JSON.parse(body)
    return j.detail || j.error || j.message || 'Could not change the password'
  } catch {
    if (m.includes('401')) return 'Current password is incorrect'
    return 'Could not change the password. Please try again.'
  }
}

export default function AdminProfilePage() {
  const [me, setMe] = useState({ username: sessionStorage.getItem('admin_username') || '', role: null })
  const [current, setCurrent] = useState('')
  const [next, setNext]       = useState('')
  const [confirm, setConfirm] = useState('')
  const [show, setShow]       = useState(false)
  const [saving, setSaving]   = useState(false)
  const [result, setResult]   = useState(null)      // {ok, msg}

  useEffect(() => {
    getAdminProfile().then(d => d && setMe(d)).catch(() => {})
  }, [])

  const s = strength(next)
  const mismatch = confirm && confirm !== next
  const needs = missing(next)
  const canSubmit = current.trim() && needs.length === 0 && next === confirm && !saving

  const submit = async (e) => {
    e.preventDefault()
    if (!canSubmit) return
    setSaving(true); setResult(null)
    try {
      await updateAdminProfile({ current_pin: current.trim(), new_pin: next.trim() })
      setResult({ ok: true, msg: 'Password changed. Your other sign-ins were ended; you stay signed in here.' })
      setCurrent(''); setNext(''); setConfirm('')
    } catch (err) {
      setResult({ ok: false, msg: errorText(err) })
    } finally {
      setSaving(false)
    }
  }

  const initials = (me.username || 'A').charAt(0).toUpperCase()
  const lastLogin = me.last_login_at
    ? new Date(me.last_login_at).toLocaleString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : 'This session'
  const canChange = me.can_change_password !== false

  const rows = [
    { icon: <Shield size={15} style={{ color: '#7C3AED' }} />,    label: 'Role',       value: ROLE_LABEL[me.role] || 'Admin' },
    { icon: <Building2 size={15} style={{ color: '#7C3AED' }} />, label: 'Company',    value: me.company_name || '—' },
    { icon: <Calendar size={15} style={{ color: '#7C3AED' }} />,  label: 'Last sign-in', value: lastLogin },
  ]

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-gray-900">My Account</h2>
        <p className="text-xs text-gray-500 mt-0.5">Your own sign-in. Other admins of your company have their own accounts.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Who you are */}
        <div className="lg:col-span-1">
          <div className="card p-6 flex flex-col items-center gap-4 text-center"
               style={{ background: 'linear-gradient(135deg, #f5f3ff, #ede9fe)', border: '1px solid #e9d5ff' }}>
            <div className="w-24 h-24 rounded-full flex items-center justify-center shadow-lg" style={{ background: '#7C3AED' }}>
              <span className="text-3xl font-black text-white">{initials}</span>
            </div>
            <div>
              <p className="text-xl font-bold text-gray-900">{me.username || '—'}</p>
              <p className="text-sm text-gray-500 mt-0.5">{ROLE_LABEL[me.role] || 'Admin'}</p>
            </div>
            <div className="w-full border-t border-gray-100 my-1" />
            <div className="w-full space-y-3 text-left">
              {rows.map(({ icon, label, value }) => (
                <div key={label} className="flex items-start gap-3">
                  <div className="mt-0.5 flex-shrink-0">{icon}</div>
                  <div>
                    <p className="text-xs text-gray-500 font-medium">{label}</p>
                    <p className="text-xs font-semibold text-gray-800 mt-0.5">{value}</p>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-500">Your sign-in name is set by the Super Admin.</p>
          </div>
        </div>

        {/* Change my password */}
        <div className="lg:col-span-2">
          <div className="card p-6">
            <div className="flex items-center gap-2 mb-5">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: '#EDE9FE' }}>
                <Lock size={15} style={{ color: '#7C3AED' }} />
              </div>
              <h3 className="text-sm font-semibold text-gray-800">Change my password</h3>
            </div>

            {result && (
              <div className="flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm mb-4"
                   style={{ background: result.ok ? '#F0FDF4' : '#FEF2F2', borderLeft: `3px solid ${result.ok ? '#10B981' : '#EF4444'}` }}>
                {result.ok
                  ? <CheckCircle2 size={15} style={{ color: '#10B981', flexShrink: 0, marginTop: 1 }} />
                  : <AlertCircle  size={15} style={{ color: '#EF4444', flexShrink: 0, marginTop: 1 }} />}
                <span style={{ color: result.ok ? '#065F46' : '#991B1B' }}>{result.msg}</span>
              </div>
            )}

            {!canChange ? (
              <p className="text-sm text-gray-600">
                {me.role === 'super_admin'
                  ? 'The Super Admin password is changed in Super Admin → Config.'
                  : 'Passwords of this company server are managed on the main server. Ask the Super Admin to change yours.'}
              </p>
            ) : (
              <form onSubmit={submit} className="space-y-4" noValidate>
                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide" htmlFor="pw-current">Current password</label>
                  <div className="relative mt-1">
                    <input id="pw-current" type={show ? 'text' : 'password'} value={current}
                           onChange={e => { setCurrent(e.target.value); setResult(null) }}
                           className="form-input pr-10" autoComplete="current-password" />
                    <button type="button" onClick={() => setShow(v => !v)} aria-label={show ? 'Hide passwords' : 'Show passwords'}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                      {show ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide" htmlFor="pw-new">New password</label>
                  <input id="pw-new" type={show ? 'text' : 'password'} value={next}
                         onChange={e => { setNext(e.target.value); setResult(null) }}
                         className="form-input mt-1" autoComplete="new-password" placeholder="10+ characters: capital, small letter, number, symbol" />
                  {next && needs.length > 0 && <p className="text-xs text-gray-500 mt-1">Still needed: {needs.join(', ')}</p>}
                  {s && (
                    <div className="mt-2">
                      <div className="flex justify-between mb-1">
                        <span className="text-xs text-gray-400">Strength</span>
                        <span className="text-xs font-semibold" style={{ color: s.color }}>{s.label}</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-300" style={{ width: s.width, background: s.color }} />
                      </div>
                    </div>
                  )}
                </div>

                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide" htmlFor="pw-confirm">Confirm new password</label>
                  <input id="pw-confirm" type={show ? 'text' : 'password'} value={confirm}
                         onChange={e => { setConfirm(e.target.value); setResult(null) }}
                         className={`form-input mt-1 ${mismatch ? 'border-red-300' : ''}`} autoComplete="new-password" />
                  {mismatch && <p className="text-xs text-red-500 mt-1">The passwords do not match</p>}
                </div>

                <button type="submit" disabled={!canSubmit}
                        className="w-full py-3 rounded-xl text-sm font-bold text-white transition-all disabled:opacity-50"
                        style={{ background: '#7C3AED' }}>
                  {saving ? 'Changing…' : 'Change password'}
                </button>

                <p className="text-xs text-gray-500">
                  Only your own account changes. Your sign-ins on other browsers or PCs end; other admins are not affected.
                </p>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
