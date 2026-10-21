/**
 * src/pages/ManageAdminsPage.jsx
 * Admins of your company — who else can sign in, their role, whether the account is on,
 * and when they last signed in. Read-only: accounts are created, switched off, moved and
 * given new passwords by the Super Admin only. Everyone changes their OWN password in My Account.
 */
import { useState, useEffect, useCallback } from 'react'
import { ShieldCheck, ShieldAlert, RefreshCw, Info } from 'lucide-react'
import { SkeletonTable } from '../components/Skeleton'

const ROLE = { main: 'Main Admin', sub: 'Sub Admin (view + acknowledge)', super_admin: 'Super Admin' }

function when(t) {
  if (!t) return 'Never'
  const d = new Date(t)
  return isNaN(d) ? String(t) : d.toLocaleString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function ManageAdminsPage() {
  const [admins,  setAdmins]  = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')
  const me = sessionStorage.getItem('admin_username') || ''

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const token = sessionStorage.getItem('admin_token') || ''
      const res = await fetch('/api/admin/admins', { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`)
      setAdmins(Array.isArray(data) ? data : [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Admins</h2>
          <p className="text-xs text-gray-500 mt-0.5">Everyone who can sign in to your company's dashboard.</p>
        </div>
        <button onClick={load} className="btn btn-ghost btn-sm flex items-center gap-1.5" disabled={loading}>
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm" style={{ background: '#EFF6FF', border: '1px solid #BFDBFE' }}>
        <Info size={15} style={{ color: '#2563EB', flexShrink: 0, marginTop: 2 }} />
        <span style={{ color: '#1E3A8A' }}>
          Admin accounts are added, switched off, moved and given new passwords by the Super Admin only.
          To change your own password use <strong>My Account</strong>. Every action is recorded under the
          name of the admin who did it, so each person should have their own account.
        </span>
      </div>

      <div className="card overflow-x-auto">
        {loading ? <SkeletonTable rows={3} /> : error ? (
          <p className="p-4 text-sm text-red-600">{error}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gray-500 border-b border-gray-100">
                <th className="px-4 py-2.5">Name</th>
                <th className="px-4 py-2.5">Role</th>
                <th className="px-4 py-2.5">Account</th>
                <th className="px-4 py-2.5">Last sign-in</th>
              </tr>
            </thead>
            <tbody>
              {admins.map(a => (
                <tr key={a.id} className="border-b border-gray-50 last:border-0">
                  <td className="px-4 py-2.5 font-medium text-gray-900">
                    {a.name}{a.name === me && <span className="ml-2 text-xs text-gray-400">(you)</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center gap-1 text-xs font-semibold">
                      {a.role === 'main' ? <ShieldCheck size={13} style={{ color: '#7C3AED' }} /> : <ShieldAlert size={13} style={{ color: '#6B7280' }} />}
                      {ROLE[a.role] || a.role}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full"
                          style={a.is_active === 0 ? { background: '#FEF2F2', color: '#DC2626' } : { background: '#ECFDF5', color: '#059669' }}>
                      {a.is_active === 0 ? 'Switched off' : 'Active'}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>{when(a.last_login_at)}</td>
                </tr>
              ))}
              {admins.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-6 text-center text-gray-400">No admins found</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
