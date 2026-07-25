/**
 * src/pages/SuperAdminDashboard.jsx
 *
 * Super Admin control panel — company management and global alert log.
 * NEW FILE — does not modify any existing page or component.
 *
 * Sections:
 *   1. Create Company form
 *   2. Companies table with toggle + Assign Admin action
 *   3. Assign Admin modal
 *   4. Global Alert Log table
 *
 * Auth: reads admin_token from sessionStorage (same pattern as all other pages).
 * All API calls go to /api/super-admin/* routes.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Building2, Plus, Globe, RefreshCw,
  ToggleLeft, ToggleRight, UserCheck, AlertTriangle,
  ChevronDown, ChevronUp, X, CheckCircle
} from 'lucide-react'

// ─── API helpers (relative URLs — no BASE_URL, matches existing api.js pattern) ─

function adminHeaders() {
  const token = sessionStorage.getItem('admin_token') || ''
  const password = sessionStorage.getItem('adminPassword') || ''
  return {
    'Content-Type': 'application/json',
    'X-Admin-Password': password,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function superReq(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: adminHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'include',
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 300)}`)
  }
  return res.json()
}

const fetchCompanies       = ()               => superReq('GET',   '/api/super-admin/companies')
const createCompany        = (name, slug)     => superReq('POST',  '/api/super-admin/companies', { name, slug })
const toggleCompany        = (id)             => superReq('PATCH', `/api/super-admin/companies/${id}/toggle`)
const assignAdmin          = (id, admin_id)   => superReq('POST',  `/api/super-admin/companies/${id}/assign-admin`, { admin_id })
const fetchGlobalAlerts    = (limit = 100)    => superReq('GET',   `/api/super-admin/alerts?limit=${limit}`)
const fetchCompanySubs     = (id)             => superReq('GET',   `/api/super-admin/companies/${id}/subscribers`)

// Fetch all admins from existing endpoint (read-only, admin-authed)
const fetchAdmins          = ()               => superReq('GET',   '/api/admin/admins')

// ─── Severity badge helper ─────────────────────────────────────────────────────

function SeverityBadge({ severity = 'WARNING' }) {
  const map = {
    WARNING:   { bg: '#FEF3C7', color: '#92400E', label: 'WARNING'   },
    CRITICAL:  { bg: '#FEE2E2', color: '#991B1B', label: 'CRITICAL'  },
    EMERGENCY: { bg: '#4C0519', color: '#FCA5A5', label: 'EMERGENCY' },
  }
  const s = map[severity] || map.WARNING
  return (
    <span style={{
      background: s.bg, color: s.color, padding: '2px 8px',
      borderRadius: 4, fontSize: 11, fontWeight: 600, letterSpacing: '0.04em',
    }}>{s.label}</span>
  )
}

// ─── Assign Admin Modal ────────────────────────────────────────────────────────

function AssignAdminModal({ company, admins, onClose, onAssign }) {
  const [selectedId, setSelectedId] = useState('')
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!selectedId) { setError('Please select an admin'); return }
    setLoading(true)
    setError('')
    try {
      await onAssign(company.id, parseInt(selectedId, 10))
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to assign admin')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={e => e.stopPropagation()}>
        <div style={styles.modalHeader}>
          <span style={styles.modalTitle}>
            <UserCheck size={16} style={{ marginRight: 8, verticalAlign: 'middle' }} />
            Assign Admin — {company.name}
          </span>
          <button onClick={onClose} style={styles.closeBtn}><X size={16} /></button>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '20px 24px' }}>
          <label style={styles.label}>Select Admin</label>
          <select
            style={styles.select}
            value={selectedId}
            onChange={e => setSelectedId(e.target.value)}
          >
            <option value="">— choose admin —</option>
            {admins.map(a => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.role})
              </option>
            ))}
          </select>

          {error && <p style={styles.errorText}>{error}</p>}

          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button type="button" onClick={onClose} style={styles.btnSecondary}>
              Cancel
            </button>
            <button type="submit" style={styles.btnPrimary} disabled={loading}>
              {loading ? 'Saving…' : 'Confirm'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function SuperAdminDashboard() {
  // Companies section
  const [companies,    setCompanies]    = useState([])
  const [compLoading,  setCompLoading]  = useState(false)
  const [compError,    setCompError]    = useState('')

  // Create company form
  const [newName,   setNewName]   = useState('')
  const [newSlug,   setNewSlug]   = useState('')
  const [creating,  setCreating]  = useState(false)
  const [createErr, setCreateErr] = useState('')
  const [createOk,  setCreateOk]  = useState(false)

  // Assign admin modal
  const [assignTarget, setAssignTarget] = useState(null)   // company object
  const [admins,       setAdmins]       = useState([])

  // Global alerts
  const [alerts,       setAlerts]       = useState([])
  const [alertLoading, setAlertLoading] = useState(false)
  const [alertError,   setAlertError]   = useState('')
  const [alertLimit,   setAlertLimit]   = useState(100)

  // Toast
  const [toast, setToast] = useState(null)
  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  // ── Data loading ──────────────────────────────────────────────────────────────

  const loadCompanies = useCallback(async () => {
    setCompLoading(true)
    setCompError('')
    try {
      const data = await fetchCompanies()
      setCompanies(data)
    } catch (err) {
      setCompError(err.message)
    } finally {
      setCompLoading(false)
    }
  }, [])

  const loadAlerts = useCallback(async () => {
    setAlertLoading(true)
    setAlertError('')
    try {
      const data = await fetchGlobalAlerts(alertLimit)
      setAlerts(data)
    } catch (err) {
      setAlertError(err.message)
    } finally {
      setAlertLoading(false)
    }
  }, [alertLimit])

  const loadAdmins = useCallback(async () => {
    try {
      const data = await fetchAdmins()
      setAdmins(data)
    } catch { /* silent — modal will show empty dropdown */ }
  }, [])

  useEffect(() => { loadCompanies() }, [loadCompanies])
  useEffect(() => { loadAlerts() },   [loadAlerts])

  // ── Create company ─────────────────────────────────────────────────────────────

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!newName.trim() || !newSlug.trim()) { setCreateErr('Name and slug are required'); return }
    setCreating(true)
    setCreateErr('')
    setCreateOk(false)
    try {
      await createCompany(newName.trim(), newSlug.trim())
      setNewName('')
      setNewSlug('')
      setCreateOk(true)
      showToast(`Company "${newName.trim()}" created`)
      loadCompanies()
      setTimeout(() => setCreateOk(false), 2500)
    } catch (err) {
      setCreateErr(err.message)
    } finally {
      setCreating(false)
    }
  }

  // ── Toggle company ─────────────────────────────────────────────────────────────

  const handleToggle = async (company) => {
    try {
      await toggleCompany(company.id)
      showToast(`Company "${company.name}" ${company.is_active ? 'disabled' : 'enabled'}`)
      loadCompanies()
    } catch (err) {
      showToast(err.message, 'error')
    }
  }

  // ── Assign admin ───────────────────────────────────────────────────────────────

  const openAssignModal = (company) => {
    setAssignTarget(company)
    loadAdmins()
  }

  const handleAssign = async (companyId, adminId) => {
    await assignAdmin(companyId, adminId)
    showToast('Admin assigned successfully')
    loadCompanies()
  }

  // ── Slug auto-fill ─────────────────────────────────────────────────────────────

  const handleNameChange = (val) => {
    setNewName(val)
    if (!newSlug) {
      setNewSlug(val.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''))
    }
  }

  // ─── Render ────────────────────────────────────────────────────────────────────

  return (
    <div style={styles.page}>

      {/* ── Toast ──────────────────────────────────────────────────────────── */}
      {toast && (
        <div style={{ ...styles.toast, background: toast.type === 'error' ? '#FEE2E2' : '#D1FAE5',
          color: toast.type === 'error' ? '#991B1B' : '#065F46' }}>
          {toast.type === 'error' ? <AlertTriangle size={14} /> : <CheckCircle size={14} />}
          <span style={{ marginLeft: 8 }}>{toast.msg}</span>
        </div>
      )}

      <div style={styles.header}>
        <Globe size={22} style={{ marginRight: 10, color: '#6366F1', verticalAlign: 'middle' }} />
        <h1 style={styles.h1}>Super Admin</h1>
        <span style={styles.subtitle}>Multi-tenancy control panel</span>
      </div>

      {/* ── Section 1: Create Company ─────────────────────────────────────── */}
      <section style={styles.card}>
        <h2 style={styles.sectionTitle}>
          <Plus size={16} style={{ marginRight: 8, verticalAlign: 'middle', color: '#6366F1' }} />
          Create Company
        </h2>

        <form onSubmit={handleCreate} style={styles.createForm}>
          <div style={styles.formRow}>
            <div style={styles.formGroup}>
              <label style={styles.label}>Company Name</label>
              <input
                style={styles.input}
                placeholder="Acme Industries"
                value={newName}
                onChange={e => handleNameChange(e.target.value)}
                disabled={creating}
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>Slug (unique identifier)</label>
              <input
                style={styles.input}
                placeholder="acme-industries"
                value={newSlug}
                onChange={e => setNewSlug(e.target.value)}
                disabled={creating}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button type="submit" style={styles.btnPrimary} disabled={creating}>
                {creating ? 'Creating…' : (createOk ? '✓ Created' : 'Create')}
              </button>
            </div>
          </div>
          {createErr && <p style={styles.errorText}>{createErr}</p>}
        </form>
      </section>

      {/* ── Section 2: Companies Table ────────────────────────────────────── */}
      <section style={styles.card}>
        <div style={styles.sectionHeader}>
          <h2 style={styles.sectionTitle}>
            <Building2 size={16} style={{ marginRight: 8, verticalAlign: 'middle', color: '#6366F1' }} />
            Companies ({companies.length})
          </h2>
          <button onClick={loadCompanies} style={styles.btnIcon} title="Refresh">
            <RefreshCw size={15} className={compLoading ? 'animate-spin' : ''} />
          </button>
        </div>

        {compError && <p style={{ ...styles.errorText, padding: '0 0 12px' }}>{compError}</p>}

        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr style={styles.thead}>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Slug</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Admins</th>
                <th style={styles.th}>Subscribers</th>
                <th style={styles.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {companies.length === 0 && !compLoading ? (
                <tr><td colSpan={6} style={styles.emptyCell}>No companies yet — create one above.</td></tr>
              ) : companies.map(c => (
                <tr key={c.id} style={styles.tr}>
                  <td style={styles.td}><strong>{c.name}</strong></td>
                  <td style={{ ...styles.td, fontFamily: 'monospace', color: '#6B7280' }}>{c.slug}</td>
                  <td style={styles.td}>
                    <button
                      onClick={() => handleToggle(c)}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
                        color: c.is_active ? '#059669' : '#9CA3AF' }}
                      title={c.is_active ? 'Click to disable' : 'Click to enable'}
                    >
                      {c.is_active
                        ? <><ToggleRight size={22} /> <span style={{ fontSize: 12, fontWeight: 600 }}>Active</span></>
                        : <><ToggleLeft  size={22} /> <span style={{ fontSize: 12, fontWeight: 600 }}>Inactive</span></>
                      }
                    </button>
                  </td>
                  <td style={{ ...styles.td, textAlign: 'center' }}>{c.admin_count}</td>
                  <td style={{ ...styles.td, textAlign: 'center' }}>{c.subscriber_count}</td>
                  <td style={styles.td}>
                    <button
                      onClick={() => openAssignModal(c)}
                      style={styles.btnSmall}
                    >
                      <UserCheck size={13} style={{ marginRight: 4 }} />
                      Assign Admin
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Section 3: Global Alert Log ───────────────────────────────────── */}
      <section style={styles.card}>
        <div style={styles.sectionHeader}>
          <h2 style={styles.sectionTitle}>
            <AlertTriangle size={16} style={{ marginRight: 8, verticalAlign: 'middle', color: '#EF4444' }} />
            Global Alert Log ({alerts.length})
          </h2>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <select
              style={{ ...styles.select, width: 'auto', fontSize: 13, padding: '4px 8px' }}
              value={alertLimit}
              onChange={e => setAlertLimit(Number(e.target.value))}
            >
              <option value={50}>Last 50</option>
              <option value={100}>Last 100</option>
              <option value={250}>Last 250</option>
              <option value={500}>Last 500</option>
            </select>
            <button onClick={loadAlerts} style={styles.btnIcon} title="Refresh">
              <RefreshCw size={15} className={alertLoading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {alertError && <p style={{ ...styles.errorText, padding: '0 0 12px' }}>{alertError}</p>}

        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr style={styles.thead}>
                <th style={styles.th}>Company</th>
                <th style={styles.th}>Parameter</th>
                <th style={styles.th}>Value</th>
                <th style={styles.th}>Threshold</th>
                <th style={styles.th}>Severity</th>
                <th style={styles.th}>Time</th>
                <th style={styles.th}>Acked</th>
              </tr>
            </thead>
            <tbody>
              {alerts.length === 0 && !alertLoading ? (
                <tr><td colSpan={7} style={styles.emptyCell}>No alerts yet.</td></tr>
              ) : alerts.map(a => (
                <tr key={a.id} style={styles.tr}>
                  <td style={styles.td}>
                    <span style={styles.companyBadge}>{a.company_name}</span>
                  </td>
                  <td style={{ ...styles.td, textTransform: 'capitalize' }}>{a.parameter}</td>
                  <td style={styles.td}>{typeof a.value === 'number' ? a.value.toFixed(2) : a.value}</td>
                  <td style={styles.td}>{a.threshold}</td>
                  <td style={styles.td}><SeverityBadge severity={a.severity} /></td>
                  <td style={{ ...styles.td, fontSize: 12, color: '#6B7280' }}>
                    {a.timestamp ? new Date(a.timestamp).toLocaleString() : '—'}
                  </td>
                  <td style={styles.td}>
                    {a.acknowledged
                      ? <span style={{ color: '#059669', fontWeight: 600 }}>✓</span>
                      : <span style={{ color: '#9CA3AF' }}>—</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Assign Admin Modal ───────────────────────────────────────────────── */}
      {assignTarget && (
        <AssignAdminModal
          company={assignTarget}
          admins={admins}
          onClose={() => setAssignTarget(null)}
          onAssign={handleAssign}
        />
      )}
    </div>
  )
}

// ─── Inline styles (matching existing project's inline-style pattern) ──────────

const styles = {
  page: {
    padding: '28px 32px',
    maxWidth: 1200,
    margin: '0 auto',
    position: 'relative',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    marginBottom: 28,
    gap: 4,
  },
  h1: {
    margin: 0,
    fontSize: 22,
    fontWeight: 700,
    color: '#111827',
  },
  subtitle: {
    marginLeft: 12,
    fontSize: 13,
    color: '#6B7280',
    fontWeight: 400,
  },
  card: {
    background: '#FFFFFF',
    borderRadius: 12,
    boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
    padding: '22px 24px',
    marginBottom: 24,
  },
  sectionHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  sectionTitle: {
    margin: 0,
    fontSize: 15,
    fontWeight: 600,
    color: '#111827',
  },
  createForm: { marginTop: 12 },
  formRow: {
    display: 'flex',
    gap: 16,
    alignItems: 'flex-start',
    flexWrap: 'wrap',
  },
  formGroup: { display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 180 },
  label: { fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 },
  input: {
    border: '1px solid #D1D5DB',
    borderRadius: 8,
    padding: '8px 12px',
    fontSize: 14,
    color: '#111827',
    outline: 'none',
    width: '100%',
  },
  select: {
    border: '1px solid #D1D5DB',
    borderRadius: 8,
    padding: '8px 12px',
    fontSize: 14,
    color: '#111827',
    outline: 'none',
    width: '100%',
    cursor: 'pointer',
  },
  errorText: { color: '#DC2626', fontSize: 13, margin: '8px 0 0' },
  tableWrap: { overflowX: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 14 },
  thead: { background: '#F9FAFB' },
  th: {
    padding: '10px 14px',
    textAlign: 'left',
    fontSize: 12,
    fontWeight: 600,
    color: '#6B7280',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    borderBottom: '1px solid #E5E7EB',
    whiteSpace: 'nowrap',
  },
  tr: { borderBottom: '1px solid #F3F4F6' },
  td: { padding: '12px 14px', color: '#374151', verticalAlign: 'middle' },
  emptyCell: {
    padding: '32px 0',
    textAlign: 'center',
    color: '#9CA3AF',
    fontSize: 14,
  },
  companyBadge: {
    background: '#EEF2FF',
    color: '#4338CA',
    padding: '2px 8px',
    borderRadius: 4,
    fontSize: 12,
    fontWeight: 600,
  },
  btnPrimary: {
    background: '#6366F1',
    color: '#FFFFFF',
    border: 'none',
    borderRadius: 8,
    padding: '8px 18px',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  btnSecondary: {
    background: '#F3F4F6',
    color: '#374151',
    border: '1px solid #D1D5DB',
    borderRadius: 8,
    padding: '8px 18px',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    flex: 1,
  },
  btnSmall: {
    background: '#EEF2FF',
    color: '#4338CA',
    border: '1px solid #C7D2FE',
    borderRadius: 6,
    padding: '4px 10px',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
  },
  btnIcon: {
    background: 'none',
    border: '1px solid #E5E7EB',
    borderRadius: 6,
    padding: '5px 8px',
    cursor: 'pointer',
    color: '#6B7280',
    display: 'flex',
    alignItems: 'center',
  },
  // Modal
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
  },
  modal: {
    background: '#FFFFFF', borderRadius: 12, width: 440, maxWidth: '95vw',
    boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
  },
  modalHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '16px 24px', borderBottom: '1px solid #E5E7EB',
  },
  modalTitle: { fontSize: 15, fontWeight: 700, color: '#111827', display: 'flex', alignItems: 'center' },
  closeBtn: {
    background: 'none', border: 'none', cursor: 'pointer', color: '#6B7280', padding: 4,
  },
  toast: {
    position: 'fixed', top: 20, right: 20,
    padding: '10px 18px', borderRadius: 8,
    display: 'flex', alignItems: 'center',
    fontSize: 13, fontWeight: 600,
    boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
    zIndex: 2000,
    animation: 'slideInRight 0.2s ease',
  },
}
