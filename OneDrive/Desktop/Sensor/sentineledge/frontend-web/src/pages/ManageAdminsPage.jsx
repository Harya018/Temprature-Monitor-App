/**
 * src/pages/ManageAdminsPage.jsx
 * Manage Admins — visible only to main admin (Group 3, item 24)
 * Create / delete sub-admins and change their passwords.
 */
import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, KeyRound, ShieldCheck, ShieldAlert, Eye, EyeOff, RefreshCw } from 'lucide-react'
import ConfirmModal from '../components/shared/ConfirmModal'
import { SkeletonTable } from '../components/Skeleton'

function adminHeaders() {
  const token = sessionStorage.getItem('admin_token') || ''
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function apiFetch(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: adminHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
  return data
}

export default function ManageAdminsPage() {
  const [admins,   setAdmins]   = useState([])
  const [loading,  setLoading]  = useState(true)
  const [toast,    setToast]    = useState(null)

  // Create form
  const [newName, setNewName]     = useState('')
  const [newPwd,  setNewPwd]      = useState('')
  const [showNew, setShowNew]     = useState(false)
  const [creating,setCreating]    = useState(false)

  // Password change form
  const [editId,   setEditId]    = useState(null)
  const [editPwd,  setEditPwd]   = useState('')
  const [showEdit, setShowEdit]  = useState(false)
  const [updating, setUpdating]  = useState(false)

  // Delete confirmation modal
  const [confirmTarget, setConfirmTarget] = useState(null) // admin object pending deletion

  function notify(msg, ok = true) {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 4000)
  }

  const load = useCallback(async () => {
    try {
      const rows = await apiFetch('GET', '/api/admin/admins')
      setAdmins(rows)
    } catch (err) {
      notify(err.message, false)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleCreate = async (e) => {
    e.preventDefault()
    setCreating(true)
    try {
      await apiFetch('POST', '/api/admin/admins', { name: newName.trim(), password: newPwd })
      notify(`Sub-admin "${newName.trim()}" created`)
      setNewName(''); setNewPwd('')
      load()
    } catch (err) {
      notify(err.message, false)
    } finally {
      setCreating(false)
    }
  }

  // Step 1: open the confirmation modal
  const handleDeleteClick = (admin) => {
    setConfirmTarget(admin)
  }

  // Step 2: user confirmed — run the actual delete
  const handleDeleteConfirm = async () => {
    const admin = confirmTarget
    setConfirmTarget(null)
    try {
      await apiFetch('DELETE', `/api/admin/admins/${admin.id}`)
      notify(`Sub-admin "${admin.name}" deleted`)
      load()
    } catch (err) {
      notify(err.message, false)
    }
  }

  const handleUpdatePwd = async (e) => {
    e.preventDefault()
    setUpdating(true)
    try {
      await apiFetch('PUT', `/api/admin/admins/${editId}/password`, { new_password: editPwd })
      notify('Password updated')
      setEditId(null); setEditPwd('')
    } catch (err) {
      notify(err.message, false)
    } finally {
      setUpdating(false)
    }
  }

  const fmtDate = (s) => {
    try {
      return new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
    } catch { return s }
  }

  return (
    <div className="space-y-5 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Manage Admins</h2>
          <p className="text-xs text-gray-500 mt-0.5">Create and manage sub-admin accounts</p>
        </div>
        <button onClick={load} className="flex items-center gap-1.5 text-xs font-semibold text-purple-600 border border-purple-200 rounded-lg px-3 py-1.5 hover:bg-purple-50 transition-colors">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Toast */}
      {toast && (
        <div className="rounded-lg px-4 py-2.5 text-sm font-medium"
             style={{
               background:  toast.ok ? '#f0fdf4' : '#fef2f2',
               color:       toast.ok ? '#065f46' : '#991b1b',
               borderLeft: `3px solid ${toast.ok ? '#10b981' : '#ef4444'}`,
             }}>
          {toast.msg}
        </div>
      )}

      {/* Create form */}
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-4">
          <Plus size={16} style={{ color: '#7c3aed' }} />
          <h3 className="text-sm font-semibold text-gray-800">Add Sub-Admin</h3>
        </div>
        <form onSubmit={handleCreate} className="flex gap-3 flex-wrap">
          <input
            type="text"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="Name"
            required
            minLength={2}
            className="flex-1 min-w-[140px] border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-200"
          />
          <div className="relative flex-1 min-w-[160px]">
            <input
              type={showNew ? 'text' : 'password'}
              value={newPwd}
              onChange={e => setNewPwd(e.target.value)}
              placeholder="Password (min 6 chars)"
              required
              minLength={6}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm pr-9 focus:outline-none focus:ring-2 focus:ring-purple-200"
            />
            <button type="button" onClick={() => setShowNew(v => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400">
              {showNew ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
          <button type="submit" disabled={creating}
                  className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-50"
                  style={{ background: '#7c3aed' }}>
            {creating ? 'Creating…' : 'Create'}
          </button>
        </form>
      </div>

      {/* Admin list */}
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-800">All Admin Accounts</h3>
        </div>
        {loading ? (
          <SkeletonTable />
        ) : admins.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-500">No admin accounts found</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                {['Name', 'Role', 'Created', 'Actions'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {admins.map(admin => (
                <tr key={admin.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                           style={{ background: admin.role === 'main' ? '#7c3aed15' : '#f0fdf4', color: admin.role === 'main' ? '#7c3aed' : '#059669' }}>
                        {admin.name[0].toUpperCase()}
                      </div>
                      <span className="font-medium text-gray-800">{admin.name}</span>
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full"
                          style={admin.role === 'main'
                            ? { background: '#ede9fe', color: '#7c3aed' }
                            : { background: '#f0fdf4', color: '#059669' }}>
                      {admin.role === 'main'
                        ? <ShieldCheck size={10} />
                        : <ShieldAlert size={10} />}
                      {admin.role === 'main' ? 'Main Admin' : 'Sub-Admin'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{fmtDate(admin.created_at)}</td>
                  <td className="px-4 py-3">
                    {admin.role !== 'main' && (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => { setEditId(admin.id); setEditPwd('') }}
                          title="Change password"
                          className="p-1.5 rounded-lg hover:bg-purple-50 text-purple-600 transition-colors"
                        >
                          <KeyRound size={14} />
                        </button>
                        <button
                          onClick={() => handleDeleteClick(admin)}
                          title="Delete"
                          className="p-1.5 rounded-lg hover:bg-red-50 text-red-500 transition-colors"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    )}
                    {admin.role === 'main' && (
                      <span className="text-xs text-gray-400 italic">Protected</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Change password modal */}
      {editId && (
        <div className="fixed inset-0 flex items-center justify-center z-50" style={{ background: 'rgba(0,0,0,0.4)' }}>
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm">
            <h3 className="font-bold text-gray-900 mb-4">Change Sub-Admin Password</h3>
            <form onSubmit={handleUpdatePwd} className="space-y-3">
              <div className="relative">
                <input
                  type={showEdit ? 'text' : 'password'}
                  value={editPwd}
                  onChange={e => setEditPwd(e.target.value)}
                  placeholder="New password (min 6 chars)"
                  required
                  minLength={6}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm pr-9 focus:outline-none focus:ring-2 focus:ring-purple-200"
                />
                <button type="button" onClick={() => setShowEdit(v => !v)}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400">
                  {showEdit ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => setEditId(null)}
                        className="flex-1 py-2 rounded-lg border border-gray-200 text-sm font-medium text-gray-600 hover:bg-gray-50">
                  Cancel
                </button>
                <button type="submit" disabled={updating}
                        className="flex-1 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-50"
                        style={{ background: '#7c3aed' }}>
                  {updating ? 'Saving…' : 'Save'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {/* Delete confirmation modal */}
      <ConfirmModal
        isOpen={confirmTarget !== null}
        title={`Delete Sub-Admin`}
        message={`Delete sub-admin "${confirmTarget?.name}"? This cannot be undone.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={handleDeleteConfirm}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  )
}
