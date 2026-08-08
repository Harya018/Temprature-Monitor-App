/**
 * pages/SuperAdmin/index.jsx — Super Admin control panel (v2).
 *
 * Multi-page dashboard: Overview | Companies | Admins | Alerts | Live Feed |
 * Broadcast | Sessions.  Admin Detail replaces the Admins view when a row is
 * clicked.  Auth: reads admin_token from sessionStorage; 401 → navigate to "/".
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Building2, Users, AlertTriangle,
  Activity, Megaphone, KeyRound, LogOut, ShieldCheck,
  Radio, Wrench, CheckCircle, RefreshCw, ClipboardList,
  Lock, Unlock, UserCheck, Copy, BarChart2, CreditCard,
  ShieldAlert, Download, BookOpen, ScrollText, Layers,
} from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Cell, PieChart, Pie, Legend,
} from 'recharts'
import { rangeToDates, withDates, RANGE_OPTIONS } from '../../utils/dateRangeHelper.js'
import './SuperAdmin.css'

// ─── API layer ────────────────────────────────────────────────────────────────

function adminHeaders() {
  const token = sessionStorage.getItem('admin_token') || ''
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: adminHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'include',
  })
  if (res.status === 401) {
    // Session expired or invalidated — wipe local state and go back to login.
    sessionStorage.removeItem('admin_token')
    sessionStorage.removeItem('admin_username')
    sessionStorage.removeItem('authenticated')
    sessionStorage.removeItem('adminPassword')
    sessionStorage.removeItem('login_time')
    window.location.replace('/super-admin/login')
    return
  }
  if (res.status === 403) {
    const err = new Error(`HTTP ${res.status}`)
    err.status = res.status
    throw err
  }
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 300)}`)
  }
  return res.json()
}

const SA  = '/api/super-admin'
const AC  = '/api/super-admin/admin-control'
const get  = (path)        => api('GET',    path)
const post = (path, body)  => api('POST',   path, body)
const patch= (path, body)  => api('PATCH',  path, body)
const put  = (path, body)  => api('PUT',    path, body)
const del  = (path)        => api('DELETE', path)

// ─── Tiny shared components ───────────────────────────────────────────────────

function Badge({ label, type }) {
  const cls = {
    active: 'active', inactive: 'inactive',
    main: 'main', sub: 'sub', super_admin: 'super',
    WARNING: 'warning', CRITICAL: 'critical',
    normal: 'normal', warning: 'warning', critical: 'critical',
  }[type] || 'sub'
  return <span className={`sa-badge ${cls}`}>{label}</span>
}

function Spinner() {
  return <span style={{ color: '#6B7280', fontSize: 13 }}>Loading…</span>
}

function Err({ msg }) {
  return msg ? <p className="sa-error" style={{ margin: '12px 0 0' }}>{msg}</p> : null
}

function CloseBtn({ onClick }) {
  return (
    <button onClick={onClick} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: '#6B7280', lineHeight: 1 }}>×</button>
  )
}

// ─── Modal wrapper ────────────────────────────────────────────────────────────

function Modal({ title, onClose, children, footer }) {
  return (
    <div className="sa-modal-overlay" onClick={onClose}>
      <div className="sa-modal" onClick={e => e.stopPropagation()}>
        <div className="sa-modal-header">
          <span className="sa-modal-title">{title}</span>
          <CloseBtn onClick={onClose} />
        </div>
        <div className="sa-modal-body">{children}</div>
        {footer && <div className="sa-modal-footer">{footer}</div>}
      </div>
    </div>
  )
}

// ─── Command Center tab ───────────────────────────────────────────────────────

const CMD = '/api/super-admin/command'

function DeviceDot({ device }) {
  const [tip, setTip] = useState(false)
  return (
    <div style={{ position: 'relative', display: 'inline-block' }}
      onMouseEnter={() => setTip(true)}
      onMouseLeave={() => setTip(false)}
    >
      <div className={`sa-device-dot sa-device-dot--${device.status}`} />
      {tip && (
        <div className="sa-device-tip">
          <div style={{ fontWeight: 700 }}>{device.name}</div>
          <div>{device.latest_value != null ? `${Number(device.latest_value).toFixed(1)} ${device.unit}` : '—'}</div>
          <div style={{ color: '#9CA3AF', fontSize: 11 }}>
            {device.last_reading_at ? new Date(device.last_reading_at).toLocaleTimeString() : 'No data'}
          </div>
          <div style={{ textTransform: 'capitalize', fontWeight: 600, color: device.status === 'critical' ? '#DC2626' : device.status === 'warning' ? '#D97706' : device.status === 'offline' ? '#6B7280' : '#059669' }}>
            {device.status}
          </div>
        </div>
      )}
    </div>
  )
}

function SystemMapPanel({ companies, lastUpdated, onRefresh }) {
  return (
    <div className="sa-map-panel">
      <div className="sa-map-header">
        <span style={{ fontWeight: 700, fontSize: 14 }}>System Map</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {lastUpdated && <span style={{ fontSize: 11, color: '#9CA3AF' }}>Updated {new Date(lastUpdated).toLocaleTimeString()}</span>}
          <button className="sa-btn sm secondary" onClick={onRefresh}><RefreshCw size={12} /></button>
        </div>
      </div>
      <div className="sa-map-body">
        {companies.length === 0
          ? <p style={{ color: '#9CA3AF', padding: '20px 0', textAlign: 'center' }}>No companies configured.</p>
          : companies.map(co => {
              const hasCritical = co.devices.some(d => d.status === 'critical')
              const hasWarning  = co.devices.some(d => d.status === 'warning')
              const statusLabel = co.maintenance_mode ? 'MAINTENANCE' : hasCritical ? 'CRITICAL' : hasWarning ? 'WARNING' : 'LIVE'
              const statusCls   = co.maintenance_mode ? 'amber' : hasCritical ? 'critical' : hasWarning ? 'warning' : 'active'

              return (
                <div key={co.id} className={`sa-co-card ${co.maintenance_mode ? 'sa-co-card--maintenance' : ''}`}>
                  <div className="sa-co-card-header">
                    <span className="sa-co-name">{co.name}</span>
                    <span className={`sa-badge ${statusCls}`}>{statusLabel}</span>
                  </div>

                  {co.maintenance_mode && co.maintenance_until && (
                    <div className="sa-maintenance-notice">
                      <Wrench size={12} />
                      <span>Until {new Date(co.maintenance_until).toLocaleTimeString()}</span>
                      {co.maintenance_reason && <span>— {co.maintenance_reason}</span>}
                    </div>
                  )}

                  <div className="sa-device-dots">
                    {co.devices.length === 0
                      ? <span style={{ fontSize: 12, color: '#9CA3AF' }}>No subscribers</span>
                      : co.devices.map(d => <DeviceDot key={d.id} device={d} />)
                    }
                  </div>
                </div>
              )
            })
        }
      </div>
    </div>
  )
}

function EmergencyPanel({ companies }) {
  const [selectedCo,    setSelectedCo]    = useState('')
  const [mmEnabled,     setMmEnabled]     = useState(false)
  const [mmDuration,    setMmDuration]    = useState(60)
  const [mmCustom,      setMmCustom]      = useState('')
  const [mmReason,      setMmReason]      = useState('')
  const [mmLoading,     setMmLoading]     = useState(false)
  const [mmMsg,         setMmMsg]         = useState('')
  const [mmErr,         setMmErr]         = useState('')

  const [alertId,       setAlertId]       = useState('')
  const [activeAlerts,  setActiveAlerts]  = useState([])
  const [ackReason,     setAckReason]     = useState('')
  const [ackLoading,    setAckLoading]    = useState(false)
  const [ackMsg,        setAckMsg]        = useState('')
  const [ackErr,        setAckErr]        = useState('')
  const [showAckModal,  setShowAckModal]  = useState(false)

  // Load current maintenance status when company changes
  useEffect(() => {
    if (!selectedCo) { setMmEnabled(false); return }
    get(`${CMD}/companies/${selectedCo}/maintenance`)
      .then(d => { setMmEnabled(d.maintenance_mode); setMmReason(d.maintenance_reason || '') })
      .catch(() => {})
    get(`${SA}/alerts?limit=100`)
      .then(all => setActiveAlerts((all || []).filter(a => !a.acknowledged && String(a.company_id) === selectedCo)))
      .catch(() => {})
  }, [selectedCo])

  const effectiveDuration = mmDuration === 0 ? (parseInt(mmCustom) || 60) : mmDuration

  const handleMaintenance = async () => {
    if (!selectedCo) { setMmErr('Select a company first'); return }
    if (mmEnabled && !mmReason.trim()) { setMmErr('Reason is required'); return }
    setMmLoading(true); setMmErr(''); setMmMsg('')
    try {
      await post(`${CMD}/companies/${selectedCo}/maintenance`, {
        enabled: mmEnabled,
        duration_minutes: effectiveDuration,
        reason: mmReason.trim(),
      })
      setMmMsg(mmEnabled ? `Maintenance enabled for ${effectiveDuration} min` : 'Maintenance disabled')
    } catch (e) { setMmErr(e.message) }
    finally { setMmLoading(false) }
  }

  const handleForceAck = async () => {
    if (!alertId) { setAckErr('Select or enter an alert ID'); return }
    if (!ackReason.trim()) { setAckErr('Reason is required'); return }
    setAckLoading(true); setAckErr(''); setAckMsg('')
    try {
      await post(`${CMD}/alerts/${alertId}/force-acknowledge`, { reason: ackReason.trim() })
      setAckMsg(`Alert #${alertId} acknowledged`)
      setAlertId(''); setAckReason(''); setShowAckModal(false)
    } catch (e) { setAckErr(e.message) }
    finally { setAckLoading(false) }
  }

  return (
    <div className="sa-emergency-panel">
      <div className="sa-emergency-title">Emergency Controls</div>

      {/* Company selector */}
      <div className="sa-form-group" style={{ marginBottom: 20 }}>
        <label>Company</label>
        <select className="sa-select" value={selectedCo} onChange={e => { setSelectedCo(e.target.value); setMmMsg(''); setMmErr('') }}>
          <option value="">— select company —</option>
          {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      {/* Maintenance mode */}
      <div className="sa-emergency-section">
        <div className="sa-emergency-section-title"><Wrench size={14} /> Maintenance Mode</div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <button
            className={`sa-btn ${mmEnabled ? 'primary' : 'secondary'}`}
            onClick={() => { setMmEnabled(true); setMmMsg(''); setMmErr('') }}
          >Enable</button>
          <button
            className={`sa-btn ${!mmEnabled ? 'primary' : 'secondary'}`}
            onClick={() => { setMmEnabled(false); setMmMsg(''); setMmErr('') }}
          >Disable</button>
        </div>

        {mmEnabled && (
          <>
            <div className="sa-form-group" style={{ marginBottom: 10 }}>
              <label>Duration</label>
              <select className="sa-select" value={mmDuration} onChange={e => setMmDuration(+e.target.value)}>
                <option value={30}>30 minutes</option>
                <option value={60}>1 hour</option>
                <option value={120}>2 hours</option>
                <option value={240}>4 hours</option>
                <option value={0}>Custom…</option>
              </select>
            </div>
            {mmDuration === 0 && (
              <div className="sa-form-group" style={{ marginBottom: 10 }}>
                <label>Custom (minutes)</label>
                <input className="sa-input" type="number" min={1} value={mmCustom} onChange={e => setMmCustom(e.target.value)} placeholder="e.g. 90" />
              </div>
            )}
            <div className="sa-form-group" style={{ marginBottom: 10 }}>
              <label>Reason <span style={{ color: '#DC2626' }}>*</span></label>
              <input className="sa-input" value={mmReason} onChange={e => setMmReason(e.target.value)} placeholder="Scheduled maintenance…" />
            </div>
          </>
        )}

        {mmMsg && <p style={{ color: '#059669', fontSize: 13, margin: '6px 0' }}>{mmMsg}</p>}
        {mmErr && <p style={{ color: '#DC2626', fontSize: 13, margin: '6px 0' }}>{mmErr}</p>}

        <button className="sa-btn primary" onClick={handleMaintenance} disabled={mmLoading} style={{ width: '100%', marginTop: 4 }}>
          {mmLoading ? 'Saving…' : mmEnabled ? 'Activate Maintenance' : 'Deactivate Maintenance'}
        </button>
      </div>

      {/* Force acknowledge */}
      <div className="sa-emergency-section">
        <div className="sa-emergency-section-title"><CheckCircle size={14} /> Force Acknowledge Alert</div>

        <div className="sa-form-group" style={{ marginBottom: 10 }}>
          <label>Alert</label>
          <select className="sa-select" value={alertId} onChange={e => setAlertId(e.target.value)}>
            <option value="">— select active alert —</option>
            {activeAlerts.map(a => (
              <option key={a.id} value={a.id}>#{a.id} {a.parameter} {a.value} ({a.severity})</option>
            ))}
          </select>
        </div>
        <div className="sa-form-group" style={{ marginBottom: 10 }}>
          <label>Or enter Alert ID</label>
          <input className="sa-input" type="number" min={1} value={alertId} onChange={e => setAlertId(e.target.value)} placeholder="Alert #" />
        </div>

        {ackMsg && <p style={{ color: '#059669', fontSize: 13, margin: '6px 0' }}>{ackMsg}</p>}
        {ackErr && <p style={{ color: '#DC2626', fontSize: 13, margin: '6px 0' }}>{ackErr}</p>}

        <button className="sa-btn danger" onClick={() => setShowAckModal(true)} disabled={!alertId} style={{ width: '100%', marginTop: 4 }}>
          Force Acknowledge
        </button>
      </div>

      {showAckModal && (
        <Modal
          title={`Force Acknowledge Alert #${alertId}`}
          onClose={() => { setShowAckModal(false); setAckErr('') }}
          footer={<>
            <button className="sa-btn secondary" onClick={() => setShowAckModal(false)}>Cancel</button>
            <button className="sa-btn danger" onClick={handleForceAck} disabled={ackLoading}>
              {ackLoading ? 'Acknowledging…' : 'Confirm'}
            </button>
          </>}
        >
          <div className="sa-form-group">
            <label>Reason <span style={{ color: '#DC2626' }}>*</span></label>
            <input className="sa-input" value={ackReason} onChange={e => { setAckReason(e.target.value); setAckErr('') }} placeholder="Reason for force-acknowledgement" autoFocus />
          </div>
          {ackErr && <p style={{ color: '#DC2626', fontSize: 13, marginTop: 8 }}>{ackErr}</p>}
        </Modal>
      )}
    </div>
  )
}

function CommandCenterTab() {
  const [mapData,      setMapData]      = useState(null)
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState('')
  const [lastUpdated,  setLastUpdated]  = useState(null)
  const timerRef = useRef(null)

  const loadMap = useCallback(async () => {
    try {
      const d = await get(`${CMD}/live-map`)
      setMapData(d)
      setLastUpdated(d.generated_at)
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadMap()
    timerRef.current = setInterval(loadMap, 10000)
    return () => clearInterval(timerRef.current)
  }, [loadMap])

  const companies = mapData?.companies || []

  return (
    <div className="sa-command-grid">
      <div>
        {loading && !mapData ? <Spinner /> : error ? <Err msg={error} /> : (
          <SystemMapPanel companies={companies} lastUpdated={lastUpdated} onRefresh={loadMap} />
        )}
      </div>
      <EmergencyPanel companies={companies} />
    </div>
  )
}

// ─── Overview tab ─────────────────────────────────────────────────────────────

function OverviewTab({ onNavigate }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await get(`${SA}/overview`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <Spinner />
  if (error)   return <Err msg={error} />
  if (!data)   return null

  const stats = [
    { label: 'Total Companies',    value: data.total_companies,  cls: 'blue'  },
    { label: 'Active Admins',      value: data.active_admins,    cls: 'green' },
    { label: 'Total Subscribers',  value: data.total_subscribers,cls: 'blue'  },
    { label: 'Alerts Today',       value: data.alerts_today,     cls: data.alerts_today > 0 ? 'amber' : '' },
    { label: 'Alerts This Week',   value: data.alerts_week,      cls: data.alerts_week > 0 ? 'red'   : '' },
  ]

  return (
    <>
      <div className="sa-stat-grid">
        {stats.map(s => (
          <div className="sa-stat" key={s.label}>
            <div className="sa-stat-label">{s.label}</div>
            <div className={`sa-stat-value ${s.cls}`}>{s.value ?? '—'}</div>
          </div>
        ))}
      </div>

      <div className="sa-card">
        <h2 className="sa-card-title">Company Summary</h2>
        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead><tr>
              <th>Name</th><th>Subscribers</th><th>Alerts Today</th><th>Status</th>
            </tr></thead>
            <tbody>
              {(data.companies || []).length === 0
                ? <tr><td colSpan={4} className="sa-empty">No companies yet.</td></tr>
                : (data.companies || []).map(c => (
                    <tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => onNavigate('companies')}>
                      <td><strong>{c.name}</strong></td>
                      <td>{c.subscriber_count}</td>
                      <td>{c.alerts_today}</td>
                      <td>{
                    c.maintenance_mode
                      ? <Badge label="Maintenance" type="warning" />
                      : c.is_active
                        ? <Badge label="Active" type="active" />
                        : <Badge label="Inactive" type="inactive" />
                  }</td>
                    </tr>
                  ))
              }
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

// ─── Companies tab ────────────────────────────────────────────────────────────

function CompanyFormModal({ company, onClose, onSaved }) {
  const editing = !!company
  const [name,       setName]       = useState(company?.name || '')
  const [slug,       setSlug]       = useState(company?.slug || '')
  const [desc,       setDesc]       = useState(company?.description || '')
  const [maxSub,     setMaxSub]     = useState(company?.max_subscribers ?? 100)
  const [maxDev,     setMaxDev]     = useState(company?.max_devices ?? 10)
  const [channels,   setChannels]   = useState(company?.allowed_channels || 'sms,email,push')
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState('')

  const handleName = (v) => {
    setName(v)
    if (!editing && !slug) setSlug(v.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!name.trim() || (!editing && !slug.trim())) { setError('Name and slug are required'); return }
    setLoading(true); setError('')
    try {
      if (editing) {
        await patch(`${SA}/companies/${company.id}`, { name: name.trim(), description: desc, max_subscribers: maxSub, max_devices: maxDev, allowed_channels: channels })
      } else {
        await post(`${SA}/companies`, { name: name.trim(), slug: slug.trim() })
      }
      onSaved()
      onClose()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <Modal title={editing ? `Edit — ${company.name}` : 'New Company'} onClose={onClose}
      footer={<>
        <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
        <button className="sa-btn primary" onClick={handleSubmit} disabled={loading}>{loading ? 'Saving…' : 'Save'}</button>
      </>}
    >
      <div className="sa-form-row">
        <div className="sa-form-group">
          <label>Company Name</label>
          <input className="sa-input" value={name} onChange={e => handleName(e.target.value)} placeholder="Acme Industries" />
        </div>
        {!editing && (
          <div className="sa-form-group">
            <label>Slug</label>
            <input className="sa-input" value={slug} onChange={e => setSlug(e.target.value)} placeholder="acme-industries" />
          </div>
        )}
      </div>
      <div className="sa-form-group" style={{ marginBottom: 12 }}>
        <label>Description</label>
        <input className="sa-input" value={desc} onChange={e => setDesc(e.target.value)} placeholder="Optional" />
      </div>
      <div className="sa-form-row">
        <div className="sa-form-group">
          <label>Max Subscribers</label>
          <input className="sa-input" type="number" value={maxSub} onChange={e => setMaxSub(+e.target.value)} min={1} />
        </div>
        <div className="sa-form-group">
          <label>Max Devices</label>
          <input className="sa-input" type="number" value={maxDev} onChange={e => setMaxDev(+e.target.value)} min={1} />
        </div>
      </div>
      <div className="sa-form-group" style={{ marginBottom: 4 }}>
        <label>Allowed Channels (comma-separated)</label>
        <input className="sa-input" value={channels} onChange={e => setChannels(e.target.value)} placeholder="sms,email,push" />
      </div>
      <Err msg={error} />
    </Modal>
  )
}

function CompaniesTab({ onViewAdmins }) {
  const [companies, setCompanies] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState('')
  const [formTarget, setFormTarget] = useState(undefined)  // undefined=closed, null=new, obj=edit
  const [delTarget,  setDelTarget]  = useState(null)
  const [delErr,     setDelErr]     = useState('')
  const [delLoading, setDelLoading] = useState(false)
  const [toast,      setToast]      = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setCompanies(await get(`${SA}/companies`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3000) }

  const handleToggle = async (c) => {
    try { await patch(`${SA}/companies/${c.id}/toggle`); load(); showToast(`${c.name} ${c.is_active ? 'disabled' : 'enabled'}`) }
    catch (e) { setError(e.message) }
  }

  const handleDelete = async () => {
    setDelLoading(true); setDelErr('')
    try { await del(`${SA}/companies/${delTarget.id}`); setDelTarget(null); load(); showToast(`${delTarget.name} deleted`) }
    catch (e) { setDelErr(e.message) }
    finally { setDelLoading(false) }
  }

  return (
    <>
      {toast && <div style={{ position: 'fixed', top: 20, right: 20, background: '#D1FAE5', color: '#065F46', padding: '10px 18px', borderRadius: 8, fontWeight: 600, fontSize: 13, zIndex: 2000 }}>{toast}</div>}

      <div className="sa-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 className="sa-card-title" style={{ margin: 0 }}>Companies ({companies.length})</h2>
          <button className="sa-btn primary" onClick={() => setFormTarget(null)}>+ New Company</button>
        </div>
        {error && <Err msg={error} />}
        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead><tr>
              <th>Name</th><th>Slug</th><th>Status</th><th>Subscribers</th><th>Admins</th><th>Alerts Today</th><th>Actions</th>
            </tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={7} className="sa-empty"><Spinner /></td></tr>
               : companies.length === 0 ? <tr><td colSpan={7} className="sa-empty">No companies yet.</td></tr>
               : companies.map(c => (
                <tr key={c.id}>
                  <td><strong>{c.name}</strong></td>
                  <td style={{ fontFamily: 'monospace', color: '#6B7280', fontSize: 13 }}>{c.slug}</td>
                  <td>{
                    c.maintenance_mode
                      ? <Badge label="Maintenance" type="warning" />
                      : c.is_active
                        ? <Badge label="Active" type="active" />
                        : <Badge label="Inactive" type="inactive" />
                  }</td>
                  <td style={{ textAlign: 'center' }}>{c.subscriber_count}</td>
                  <td style={{ textAlign: 'center' }}>{c.admin_count}</td>
                  <td style={{ textAlign: 'center' }}>—</td>
                  <td>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <button className="sa-btn sm secondary" onClick={() => setFormTarget(c)}>Edit</button>
                      <button className="sa-btn sm secondary" onClick={() => handleToggle(c)}>{c.is_active ? 'Disable' : 'Enable'}</button>
                      <button className="sa-btn sm secondary" onClick={() => onViewAdmins(c)}>Admins</button>
                      <button className="sa-btn sm danger" onClick={() => { setDelTarget(c); setDelErr('') }}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {formTarget !== undefined && (
        <CompanyFormModal company={formTarget} onClose={() => setFormTarget(undefined)} onSaved={load} />
      )}

      {delTarget && (
        <Modal title={`Delete "${delTarget.name}"?`} onClose={() => setDelTarget(null)}
          footer={<>
            <button className="sa-btn secondary" onClick={() => setDelTarget(null)}>Cancel</button>
            <button className="sa-btn danger" onClick={handleDelete} disabled={delLoading}>{delLoading ? 'Deleting…' : 'Delete'}</button>
          </>}
        >
          <p style={{ margin: 0, color: '#374151' }}>This cannot be undone. The company must have no subscribers or admins assigned to it.</p>
          <Err msg={delErr} />
        </Modal>
      )}
    </>
  )
}

// ─── Admin Detail view ────────────────────────────────────────────────────────

function AdminDetailView({ adminId, onBack }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')
  const [tab,     setTab]     = useState('profile')
  const [activity,    setActivity]    = useState([])
  const [actLoading,  setActLoading]  = useState(false)
  const [actFilter,   setActFilter]   = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await get(`${SA}/admins/${adminId}`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [adminId])

  const loadActivity = useCallback(async () => {
    setActLoading(true)
    try {
      const q = actFilter ? `?action=${actFilter}` : ''
      setActivity(await get(`${SA}/admins/${adminId}/activity${q}`))
    } catch { /* silent */ }
    finally { setActLoading(false) }
  }, [adminId, actFilter])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (tab === 'activity') loadActivity() }, [tab, loadActivity])

  const actRowClass = (action) => {
    if (action === 'login') return 'sa-activity-login'
    if (action.includes('threshold')) return 'sa-activity-threshold'
    if (action.includes('remove') || action.includes('delete')) return 'sa-activity-remove'
    if (action.includes('subscriber')) return 'sa-activity-subscriber'
    return 'sa-activity-profile'
  }

  if (loading) return <><button className="sa-back-btn" onClick={onBack}>← Back</button><Spinner /></>
  if (error)   return <><button className="sa-back-btn" onClick={onBack}>← Back</button><Err msg={error} /></>

  const a = data || {}
  return (
    <>
      <button className="sa-back-btn" onClick={onBack}>← Back to Admins</button>

      <div className="sa-card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
          <div style={{ width: 52, height: 52, borderRadius: '50%', background: '#EDE9FE', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 22, fontWeight: 800, color: '#5B21B6' }}>
            {(a.name || '?')[0].toUpperCase()}
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>{a.name}</h2>
            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <Badge label={a.role} type={a.role} />
              <Badge label={a.is_active === 0 ? 'Inactive' : 'Active'} type={a.is_active === 0 ? 'inactive' : 'active'} />
              {a.company_name && <span style={{ fontSize: 12, color: '#6B7280' }}>@ {a.company_name}</span>}
            </div>
          </div>
        </div>

        <div className="sa-tabs">
          {['profile', 'company', 'activity', 'subscribers'].map(t => (
            <button key={t} className={`sa-tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>

        {tab === 'profile' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px 32px' }}>
            {[
              ['Name',           a.name],
              ['Role',           a.role],
              ['Status',         a.is_active === 0 ? 'Inactive' : 'Active'],
              ['Created At',     a.created_at ? new Date(a.created_at).toLocaleString() : '—'],
              ['Last Login',     a.last_login_at ? new Date(a.last_login_at).toLocaleString() : 'Never'],
              ['Last Login IP',  a.last_login_ip || '—'],
              ['Company',        a.company_name || 'Unassigned'],
            ].map(([k, v]) => (
              <div key={k}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', marginBottom: 2 }}>{k}</div>
                <div style={{ fontSize: 14, color: '#111827' }}>{v}</div>
              </div>
            ))}
          </div>
        )}

        {tab === 'company' && (
          a.company ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px 32px' }}>
              {[
                ['Name',           a.company.name],
                ['Slug',           a.company.slug],
                ['Max Subscribers',a.company.max_subscribers ?? '—'],
                ['Max Devices',    a.company.max_devices ?? '—'],
                ['Channels',       a.company.allowed_channels || '—'],
                ['Description',    a.company.description || '—'],
              ].map(([k, v]) => (
                <div key={k}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', marginBottom: 2 }}>{k}</div>
                  <div style={{ fontSize: 14, color: '#111827' }}>{v}</div>
                </div>
              ))}
            </div>
          ) : <p style={{ color: '#6B7280', margin: 0 }}>No company assigned.</p>
        )}

        {tab === 'activity' && (
          <>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <select className="sa-select" style={{ width: 'auto', padding: '6px 10px', fontSize: 13 }}
                value={actFilter} onChange={e => setActFilter(e.target.value)}>
                <option value="">All actions</option>
                <option value="login">Login</option>
                <option value="add_subscriber">Add Subscriber</option>
                <option value="remove_subscriber">Remove Subscriber</option>
                <option value="update_subscriber">Update Subscriber</option>
              </select>
              <button className="sa-btn sm secondary" onClick={loadActivity}>Refresh</button>
            </div>
            {actLoading ? <Spinner /> : (
              <div className="sa-table-wrap">
                <table className="sa-table">
                  <thead><tr><th>Time</th><th>Action</th><th>Entity</th><th>Details</th></tr></thead>
                  <tbody>
                    {activity.length === 0
                      ? <tr><td colSpan={4} className="sa-empty">No activity logged.</td></tr>
                      : activity.map(row => (
                          <tr key={row.id} className={`sa-action-log-row ${actRowClass(row.action)}`}>
                            <td>{row.created_at ? new Date(row.created_at).toLocaleString() : '—'}</td>
                            <td style={{ fontWeight: 600 }}>{row.action}</td>
                            <td>{row.entity || '—'}</td>
                            <td style={{ color: '#6B7280', fontSize: 13 }}>{row.details || '—'}</td>
                          </tr>
                        ))
                    }
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {tab === 'subscribers' && (
          <div className="sa-table-wrap">
            <table className="sa-table">
              <thead><tr><th>Name</th><th>Phone</th><th>Email</th><th>Channels</th><th>Status</th></tr></thead>
              <tbody>
                {(!a.subscribers || a.subscribers.length === 0)
                  ? <tr><td colSpan={5} className="sa-empty">No subscribers in this company.</td></tr>
                  : a.subscribers.map(s => (
                      <tr key={s.id}>
                        <td>{s.name}</td>
                        <td>{s.phone}</td>
                        <td>{s.email}</td>
                        <td>—</td>
                        <td><Badge label={s.is_active === 0 ? 'Inactive' : 'Active'} type={s.is_active === 0 ? 'inactive' : 'active'} /></td>
                      </tr>
                    ))
                }
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}

// ─── Admins tab ───────────────────────────────────────────────────────────────

function AdminFormModal({ companies, onClose, onSaved }) {
  const [name,      setName]      = useState('')
  const [password,  setPassword]  = useState('')
  const [role,      setRole]      = useState('sub')
  const [companyId, setCompanyId] = useState('')
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!name.trim() || !password) { setError('Name and password are required'); return }
    setLoading(true); setError('')
    try {
      await post(`${SA}/admins`, { name: name.trim(), password, role, company_id: companyId ? +companyId : null })
      onSaved(); onClose()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <Modal title="New Admin" onClose={onClose}
      footer={<>
        <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
        <button className="sa-btn primary" onClick={handleSubmit} disabled={loading}>{loading ? 'Creating…' : 'Create'}</button>
      </>}
    >
      <div className="sa-form-row">
        <div className="sa-form-group">
          <label>Name</label>
          <input className="sa-input" value={name} onChange={e => setName(e.target.value)} placeholder="Ravi Kumar" />
        </div>
        <div className="sa-form-group">
          <label>Password</label>
          <input className="sa-input" type="password" value={password} onChange={e => setPassword(e.target.value)} />
        </div>
      </div>
      <div className="sa-form-row">
        <div className="sa-form-group">
          <label>Role</label>
          <select className="sa-select" value={role} onChange={e => setRole(e.target.value)}>
            <option value="sub">Sub Admin</option>
            <option value="main">Main Admin</option>
          </select>
        </div>
        <div className="sa-form-group">
          <label>Company</label>
          <select className="sa-select" value={companyId} onChange={e => setCompanyId(e.target.value)}>
            <option value="">— none —</option>
            {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      </div>
      <Err msg={error} />
    </Modal>
  )
}

function ResetPwdModal({ admin, onClose }) {
  const [pwd,     setPwd]     = useState('')
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')
  const [done,    setDone]    = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!pwd || pwd.length < 6) { setError('Password must be at least 6 characters'); return }
    setLoading(true); setError('')
    try { await put(`${SA}/admins/${admin.id}/password`, { new_password: pwd }); setDone(true) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <Modal title={`Reset Password — ${admin.name}`} onClose={onClose}
      footer={done
        ? <button className="sa-btn primary" onClick={onClose}>Close</button>
        : <>
            <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
            <button className="sa-btn primary" onClick={handleSubmit} disabled={loading}>{loading ? 'Saving…' : 'Reset'}</button>
          </>
      }
    >
      {done
        ? <p style={{ color: '#059669', margin: 0, fontWeight: 600 }}>Password reset successfully.</p>
        : <>
            <div className="sa-form-group">
              <label>New Password</label>
              <input className="sa-input" type="password" value={pwd} onChange={e => setPwd(e.target.value)} />
            </div>
            <Err msg={error} />
          </>
      }
    </Modal>
  )
}

function AssignCompanyModal({ admin, companies, onClose, onSaved }) {
  const [companyId, setCompanyId] = useState(admin.company_id?.toString() || '')
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true); setError('')
    try { await patch(`${SA}/admins/${admin.id}/company`, { company_id: companyId ? +companyId : null }); onSaved(); onClose() }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <Modal title={`Assign Company — ${admin.name}`} onClose={onClose}
      footer={<>
        <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
        <button className="sa-btn primary" onClick={handleSubmit} disabled={loading}>{loading ? 'Saving…' : 'Assign'}</button>
      </>}
    >
      <div className="sa-form-group">
        <label>Company</label>
        <select className="sa-select" value={companyId} onChange={e => setCompanyId(e.target.value)}>
          <option value="">— unassign —</option>
          {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <Err msg={error} />
    </Modal>
  )
}

// Lock modal
function LockAdminModal({ admin, onClose, onDone }) {
  const [reason,  setReason]  = useState('')
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!reason.trim()) { setError('Reason is required'); return }
    setLoading(true); setError('')
    try {
      await post(`${AC}/${admin.id}/lock`, { reason: reason.trim() })
      onDone()
      onClose()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <Modal title={`Lock "${admin.name}"?`} onClose={onClose}
      footer={<>
        <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
        <button className="sa-btn danger" onClick={handleSubmit} disabled={loading}>{loading ? 'Locking…' : 'Lock Account'}</button>
      </>}
    >
      <p style={{ color: '#374151', margin: '0 0 12px' }}>
        This will immediately suspend {admin.name}'s access and invalidate their active sessions.
      </p>
      <div className="sa-form-group">
        <label>Reason <span style={{ color: '#DC2626' }}>*</span></label>
        <input className="sa-input" value={reason} onChange={e => { setReason(e.target.value); setError('') }}
          placeholder="Reason for locking…" autoFocus />
      </div>
      <Err msg={error} />
    </Modal>
  )
}

// Impersonation token modal
function ImpersonateModal({ admin, token, expiresAt, onClose }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(token).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000) })
  }
  return (
    <Modal title={`Impersonating ${admin.name}`} onClose={onClose}
      footer={<button className="sa-btn primary" onClick={onClose}>Done</button>}
    >
      <p style={{ color: '#374151', margin: '0 0 12px', fontSize: 13 }}>
        Use this token as <code>Authorization: Bearer &lt;token&gt;</code> to act as <strong>{admin.name}</strong>.
        Valid for 1 hour (until {new Date(expiresAt).toLocaleTimeString()}).
      </p>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <input className="sa-input" readOnly value={token}
          style={{ fontFamily: 'monospace', fontSize: 12 }} onClick={e => e.target.select()} />
        <button className="sa-btn sm secondary" onClick={copy} style={{ flexShrink: 0 }}>
          {copied ? '✓' : <Copy size={13} />}
        </button>
      </div>
      <p style={{ fontSize: 12, color: '#6B7280', margin: 0 }}>
        All actions taken with this token are logged as "superadmin acting as {admin.name}".
      </p>
    </Modal>
  )
}

function AdminsTab({ onViewDetail }) {
  const [admins,    setAdmins]    = useState([])
  const [companies, setCompanies] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState('')
  const [showNew,   setShowNew]   = useState(false)
  const [resetTarget,       setResetTarget]       = useState(null)
  const [assignTarget,      setAssignTarget]      = useState(null)
  const [lockTarget,        setLockTarget]        = useState(null)
  const [impersonateResult, setImpersonateResult] = useState(null)  // { admin, token, expiresAt }
  const [toast, setToast] = useState('')

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3000) }

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [a, c] = await Promise.all([get(`${SA}/admins`), get(`${SA}/companies`)])
      setAdmins(a); setCompanies(c)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const handleToggle = async (a) => {
    try { await patch(`${SA}/admins/${a.id}/toggle`); load(); showToast(`${a.name} ${a.is_active === 0 ? 'activated' : 'deactivated'}`) }
    catch (e) { setError(e.message) }
  }

  const handleUnlock = async (a) => {
    try {
      await post(`${AC}/${a.id}/unlock`)
      load(); showToast(`${a.name} unlocked`)
    } catch (e) { setError(e.message) }
  }

  const handleToggleApproval = async (a) => {
    const newVal = !(a.requires_approval)
    try {
      await post(`${AC}/${a.id}/require-approval`, { enabled: newVal })
      load(); showToast(`Approval ${newVal ? 'required' : 'removed'} for ${a.name}`)
    } catch (e) { setError(e.message) }
  }

  const handleImpersonate = async (a) => {
    try {
      const data = await post(`${AC}/${a.id}/impersonate`)
      setImpersonateResult({ admin: a, token: data.impersonation_token, expiresAt: data.expires_at })
    } catch (e) { setError(e.message) }
  }

  return (
    <>
      {toast && <div style={{ position: 'fixed', top: 20, right: 20, background: '#D1FAE5', color: '#065F46', padding: '10px 18px', borderRadius: 8, fontWeight: 600, fontSize: 13, zIndex: 2000 }}>{toast}</div>}

      <div className="sa-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 className="sa-card-title" style={{ margin: 0 }}>Admins ({admins.length})</h2>
          <button className="sa-btn primary" onClick={() => setShowNew(true)}>+ New Admin</button>
        </div>
        {error && <Err msg={error} />}
        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead><tr>
              <th>Name</th><th>Role</th><th>Company</th><th>Status</th><th>Last Login</th><th>7d Actions</th><th>Actions</th>
            </tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={7} className="sa-empty"><Spinner /></td></tr>
               : admins.length === 0 ? <tr><td colSpan={7} className="sa-empty">No admins found.</td></tr>
               : admins.map(a => (
                  <tr key={a.id}>
                    <td>
                      <button style={{ background: 'none', border: 'none', cursor: 'pointer', fontWeight: 700, color: '#4338CA', padding: 0 }}
                        onClick={() => onViewDetail(a.id)}>
                        {a.name}
                      </button>
                      {a.requires_approval ? <span className="sa-approval-tag">Approval req.</span> : null}
                    </td>
                    <td><Badge label={a.role} type={a.role} /></td>
                    <td>{a.company_name || <span style={{ color: '#9CA3AF' }}>—</span>}</td>
                    <td><Badge label={a.is_active === 0 ? 'Inactive' : 'Active'} type={a.is_active === 0 ? 'inactive' : 'active'} /></td>
                    <td style={{ fontSize: 12, color: '#6B7280' }}>{a.last_login_at ? new Date(a.last_login_at).toLocaleString() : 'Never'}</td>
                    <td style={{ textAlign: 'center' }}>{a.actions_7d ?? 0}</td>
                    <td>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <button className="sa-btn sm secondary" onClick={() => onViewDetail(a.id)}>Details</button>
                        {a.role !== 'super_admin' && (<>
                          <button className="sa-btn sm secondary" onClick={() => handleToggle(a)}>
                            {a.is_active === 0 ? 'Activate' : 'Deactivate'}
                          </button>
                          {a.is_active !== 0
                            ? <button className="sa-btn sm danger" title="Lock account" onClick={() => setLockTarget(a)}><Lock size={12} /></button>
                            : <button className="sa-btn sm secondary" title="Unlock account" onClick={() => handleUnlock(a)}><Unlock size={12} /></button>
                          }
                          <button
                            className={`sa-btn sm ${a.requires_approval ? 'primary' : 'secondary'}`}
                            title={a.requires_approval ? 'Approval required — click to remove' : 'Click to require approval'}
                            onClick={() => handleToggleApproval(a)}
                          ><UserCheck size={12} /></button>
                          <button className="sa-btn sm secondary" title="Impersonate" onClick={() => handleImpersonate(a)}>
                            <Copy size={12} />
                          </button>
                        </>)}
                        <button className="sa-btn sm secondary" onClick={() => setResetTarget(a)}>Reset Pwd</button>
                        <button className="sa-btn sm secondary" onClick={() => setAssignTarget(a)}>Company</button>
                      </div>
                    </td>
                  </tr>
                ))
              }
            </tbody>
          </table>
        </div>
      </div>

      {showNew && <AdminFormModal companies={companies} onClose={() => setShowNew(false)} onSaved={load} />}
      {resetTarget && <ResetPwdModal admin={resetTarget} onClose={() => setResetTarget(null)} />}
      {assignTarget && <AssignCompanyModal admin={assignTarget} companies={companies} onClose={() => setAssignTarget(null)} onSaved={load} />}
      {lockTarget && <LockAdminModal admin={lockTarget} onClose={() => setLockTarget(null)} onDone={load} />}
      {impersonateResult && (
        <ImpersonateModal
          admin={impersonateResult.admin}
          token={impersonateResult.token}
          expiresAt={impersonateResult.expiresAt}
          onClose={() => setImpersonateResult(null)}
        />
      )}
    </>
  )
}

// ─── Company Parameters tab ───────────────────────────────────────────────────

function CompanyParametersTab() {
  const [data,    setData]    = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await get(`${SA}/company-parameters`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const BUILTIN_COLOR  = '#EEF2FF'
  const BUILTIN_TEXT   = '#4338CA'
  const CUSTOM_COLOR   = '#F0FDF4'
  const CUSTOM_TEXT    = '#065F46'

  return (
    <div className="sa-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 className="sa-card-title" style={{ margin: 0 }}>Company Parameters</h2>
          <p style={{ fontSize: 13, color: '#6B7280', marginTop: 4 }}>
            All monitored parameters per company — Temperature is built-in; custom parameters are approved by Super Admin.
          </p>
        </div>
        <button className="sa-btn sm secondary" onClick={load}><RefreshCw size={13} /> Refresh</button>
      </div>

      {error && <Err msg={error} />}

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}><Spinner /></div>
      ) : data.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#9CA3AF' }}>No companies found.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {data.map(co => (
            <div key={co.company_id} style={{
              border: '1px solid #E5E7EB', borderRadius: 10, overflow: 'hidden',
            }}>
              {/* Company header */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '12px 18px', background: '#F9FAFB', borderBottom: '1px solid #E5E7EB',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 8,
                    background: '#EEF2FF', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <Building2 size={15} color="#4338CA" />
                  </div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 14, color: '#111827' }}>{co.company_name}</div>
                    <div style={{ fontSize: 12, color: '#6B7280' }}>
                      {co.parameters.length} parameter{co.parameters.length !== 1 ? 's' : ''}
                      {' '}·{' '}
                      <span style={{ color: co.is_active ? '#059669' : '#DC2626', fontWeight: 600 }}>
                        {co.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Parameters table */}
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: '#F3F4F6' }}>
                      {['Parameter', 'Unit', 'Min', 'Max', 'Type'].map(h => (
                        <th key={h} style={{
                          padding: '8px 14px', textAlign: 'left',
                          fontWeight: 600, fontSize: 11, textTransform: 'uppercase',
                          color: '#6B7280', letterSpacing: '0.05em', borderBottom: '1px solid #E5E7EB',
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {co.parameters.map((p, i) => (
                      <tr key={p.name} style={{ background: i % 2 === 0 ? '#fff' : '#FAFAFA' }}>
                        <td style={{ padding: '10px 14px', fontWeight: 600, color: '#111827' }}>
                          {p.name}
                        </td>
                        <td style={{ padding: '10px 14px', color: '#374151' }}>
                          {p.unit || <span style={{ color: '#9CA3AF' }}>—</span>}
                        </td>
                        <td style={{ padding: '10px 14px', color: '#374151', fontFamily: 'monospace' }}>
                          {p.min_value != null ? p.min_value : <span style={{ color: '#9CA3AF' }}>—</span>}
                        </td>
                        <td style={{ padding: '10px 14px', color: '#374151', fontFamily: 'monospace' }}>
                          {p.max_value != null ? p.max_value : <span style={{ color: '#9CA3AF' }}>—</span>}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          <span style={{
                            background: p.builtin ? BUILTIN_COLOR : CUSTOM_COLOR,
                            color: p.builtin ? BUILTIN_TEXT : CUSTOM_TEXT,
                            padding: '2px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700,
                          }}>
                            {p.builtin ? 'Built-in' : 'Custom'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


// ─── Global Alerts tab ────────────────────────────────────────────────────────

function AlertsTab() {
  const [alerts,   setAlerts]   = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState('')
  const [limit,    setLimit]    = useState(100)
  const [company,  setCompany]  = useState('')
  const [companies,setCompanies]= useState([])

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [a, c] = await Promise.all([get(`${SA}/alerts?limit=${limit}`), get(`${SA}/companies`)])
      setAlerts(a); setCompanies(c)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [limit])

  useEffect(() => { load() }, [load])

  const filtered = company ? alerts.filter(a => String(a.company_id) === company) : alerts

  const autoRef = useRef()
  useEffect(() => {
    autoRef.current = setInterval(load, 30000)
    return () => clearInterval(autoRef.current)
  }, [load])

  return (
    <div className="sa-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h2 className="sa-card-title" style={{ margin: 0 }}>Global Alerts</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select className="sa-select" style={{ width: 'auto', padding: '6px 10px', fontSize: 13 }} value={company} onChange={e => setCompany(e.target.value)}>
            <option value="">All companies</option>
            {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select className="sa-select" style={{ width: 'auto', padding: '6px 10px', fontSize: 13 }} value={limit} onChange={e => setLimit(+e.target.value)}>
            {[50, 100, 250, 500].map(n => <option key={n} value={n}>Last {n}</option>)}
          </select>
          <button className="sa-btn sm secondary" onClick={load}>↻ Refresh</button>
        </div>
      </div>
      {error && <Err msg={error} />}
      <div className="sa-table-wrap">
        <table className="sa-table">
          <thead><tr>
            <th>Company</th><th>Parameter</th><th>Value</th><th>Threshold</th><th>Severity</th><th>Time</th><th>Acknowledged</th>
          </tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={7} className="sa-empty"><Spinner /></td></tr>
             : filtered.length === 0 ? <tr><td colSpan={7} className="sa-empty">No alerts.</td></tr>
             : filtered.map(a => (
                <tr key={a.id}>
                  <td><span style={{ background: '#EEF2FF', color: '#4338CA', padding: '2px 8px', borderRadius: 4, fontSize: 12, fontWeight: 600 }}>{a.company_name}</span></td>
                  <td style={{ textTransform: 'capitalize' }}>{a.parameter}</td>
                  <td style={{ fontWeight: 700 }}>{typeof a.value === 'number' ? a.value.toFixed(2) : a.value}</td>
                  <td>{a.threshold}</td>
                  <td><Badge label={a.severity} type={a.severity} /></td>
                  <td style={{ fontSize: 12, color: '#6B7280' }}>{a.timestamp ? new Date(a.timestamp).toLocaleString() : '—'}</td>
                  <td style={{ textAlign: 'center' }}>{a.acknowledged ? <span style={{ color: '#059669', fontWeight: 700 }}>✓</span> : <span style={{ color: '#9CA3AF' }}>—</span>}</td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Live Feed tab ────────────────────────────────────────────────────────────

function LiveFeedTab() {
  const [feed,    setFeed]    = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  const load = useCallback(async () => {
    try { setFeed(await get(`${SA}/live-feed`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])

  if (loading) return <Spinner />
  if (error)   return <Err msg={error} />

  return (
    <div className="sa-live-grid">
      {feed.length === 0
        ? <p style={{ color: '#9CA3AF' }}>No live data available.</p>
        : feed.map((f, i) => (
            <div className="sa-live-card" key={i}>
              <h3>{f.device}</h3>
              <div className="co">{f.company_name}</div>
              <div className={`val ${f.status}`}>
                <span className={`sa-live-dot ${f.status}`} />
                {typeof f.value === 'number' ? f.value.toFixed(1) : f.value}°C
              </div>
              <div style={{ fontSize: 12, color: '#9CA3AF', marginTop: 8 }}>
                {f.timestamp ? new Date(f.timestamp).toLocaleTimeString() : '—'}
              </div>
            </div>
          ))
      }
    </div>
  )
}

// ─── Broadcast tab ────────────────────────────────────────────────────────────

function BroadcastTab() {
  const [title,   setTitle]   = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [error,   setError]   = useState('')
  const [history, setHistory] = useState([])
  const [histLoad,setHistLoad]= useState(true)

  const loadHistory = useCallback(async () => {
    setHistLoad(true)
    try { setHistory(await get(`${SA}/broadcast`)) }
    catch { /* silent */ }
    finally { setHistLoad(false) }
  }, [])

  useEffect(() => { loadHistory() }, [loadHistory])

  const handleSend = async (e) => {
    e.preventDefault()
    if (!title.trim() || !message.trim()) { setError('Title and message are required'); return }
    setSending(true); setError('')
    try { await post(`${SA}/broadcast`, { title: title.trim(), message: message.trim() }); setTitle(''); setMessage(''); loadHistory() }
    catch (e) { setError(e.message) }
    finally { setSending(false) }
  }

  return (
    <>
      <div className="sa-card">
        <h2 className="sa-card-title">Send Broadcast</h2>
        <form onSubmit={handleSend}>
          <div className="sa-form-group" style={{ marginBottom: 12 }}>
            <label>Title</label>
            <input className="sa-input" value={title} onChange={e => setTitle(e.target.value)} placeholder="System maintenance alert" />
          </div>
          <div className="sa-form-group" style={{ marginBottom: 12 }}>
            <label>Message</label>
            <textarea className="sa-input" rows={4} value={message} onChange={e => setMessage(e.target.value)} placeholder="Enter your message…" style={{ resize: 'vertical' }} />
          </div>
          <Err msg={error} />
          <button className="sa-btn primary" type="submit" disabled={sending} style={{ marginTop: 12 }}>{sending ? 'Sending…' : 'Send Broadcast'}</button>
        </form>
      </div>

      <div className="sa-card">
        <h2 className="sa-card-title">Broadcast History</h2>
        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead><tr><th>Title</th><th>Sent By</th><th>Time</th></tr></thead>
            <tbody>
              {histLoad ? <tr><td colSpan={3} className="sa-empty"><Spinner /></td></tr>
               : history.length === 0 ? <tr><td colSpan={3} className="sa-empty">No broadcasts sent yet.</td></tr>
               : history.map(b => (
                  <tr key={b.id}>
                    <td><strong>{b.title}</strong><div style={{ fontSize: 12, color: '#6B7280', marginTop: 2 }}>{b.message?.slice(0, 80)}{b.message?.length > 80 ? '…' : ''}</div></td>
                    <td>{b.sent_by}</td>
                    <td style={{ fontSize: 12, color: '#6B7280' }}>{b.created_at ? new Date(b.created_at).toLocaleString() : '—'}</td>
                  </tr>
                ))
              }
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

// ─── Sessions tab ─────────────────────────────────────────────────────────────

function SessionsTab() {
  const [sessions, setSessions] = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setSessions(await get(`${SA}/sessions`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div className="sa-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 className="sa-card-title" style={{ margin: 0 }}>Active Sessions ({sessions.length})</h2>
        <button className="sa-btn sm secondary" onClick={load}>↻ Refresh</button>
      </div>
      {error && <Err msg={error} />}
      <div className="sa-table-wrap">
        <table className="sa-table">
          <thead><tr>
            <th>Admin</th><th>Company</th><th>Last Login</th><th>Expires</th><th>Token</th>
          </tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={5} className="sa-empty"><Spinner /></td></tr>
             : sessions.length === 0 ? <tr><td colSpan={5} className="sa-empty">No active sessions.</td></tr>
             : sessions.map(s => (
                <tr key={s.id}>
                  <td>{s.admin_name || '—'} {s.admin_role && <Badge label={s.admin_role} type={s.admin_role} />}</td>
                  <td>{s.company_name || '—'}</td>
                  <td style={{ fontSize: 12, color: '#6B7280' }}>{s.last_used_at ? new Date(s.last_used_at).toLocaleString() : '—'}</td>
                  <td style={{ fontSize: 12, color: '#6B7280' }}>{s.expires_at ? new Date(s.expires_at).toLocaleString() : '—'}</td>
                  <td style={{ fontFamily: 'monospace', fontSize: 12, color: '#9CA3AF' }}>{s.token}</td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Approvals tab ────────────────────────────────────────────────────────────

function ApprovalsTab({ onCountChange }) {
  const [filter,   setFilter]   = useState('pending')
  const [rows,     setRows]     = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState('')
  const [modal,    setModal]    = useState(null)   // { type:'approve'|'reject', row }
  const [note,     setNote]     = useState('')
  const [saving,   setSaving]   = useState(false)
  const [toast,    setToast]    = useState('')

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3000) }

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const data = await get(`${AC}/approvals?status=${filter}`)
      setRows(data)
      if (filter === 'pending' && onCountChange) onCountChange(data.length)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [filter, onCountChange])

  useEffect(() => { load() }, [load])

  const handleReview = async () => {
    if (!modal) return
    setSaving(true)
    try {
      const path = `${AC}/approvals/${modal.row.id}/${modal.type}`
      await post(path, { note })
      showToast(`Approval #${modal.row.id} ${modal.type}d`)
      setModal(null); setNote('')
      load()
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  const statusColor = (s) =>
    s === 'approved' ? '#059669' : s === 'rejected' ? '#DC2626' : '#D97706'

  return (
    <>
      {toast && <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46', padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>}

      <div className="sa-card">
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16, flexWrap:'wrap', gap:8 }}>
          <h2 className="sa-card-title" style={{ margin:0 }}>Approval Queue</h2>
          <div style={{ display:'flex', gap:6 }}>
            {['pending','approved','rejected'].map(f => (
              <button key={f} className={`sa-btn sm ${filter === f ? 'primary' : 'secondary'}`}
                onClick={() => setFilter(f)} style={{ textTransform:'capitalize' }}>
                {f}
              </button>
            ))}
            <button className="sa-btn sm secondary" onClick={load}>↻</button>
          </div>
        </div>

        {error && <Err msg={error} />}

        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead><tr>
              <th>#</th><th>Admin</th><th>Company</th><th>Action</th><th>Status</th><th>Submitted</th><th>Actions</th>
            </tr></thead>
            <tbody>
              {loading
                ? <tr><td colSpan={7} className="sa-empty"><Spinner /></td></tr>
                : rows.length === 0
                  ? <tr><td colSpan={7} className="sa-empty">No {filter} approvals.</td></tr>
                  : rows.map(r => (
                      <tr key={r.id}>
                        <td style={{ color:'#9CA3AF', fontSize:12 }}>#{r.id}</td>
                        <td><strong>{r.admin_name}</strong></td>
                        <td>{r.company_name || <span style={{ color:'#9CA3AF' }}>—</span>}</td>
                        <td style={{ fontFamily:'monospace', fontSize:12 }}>{r.action_type}</td>
                        <td><span style={{ fontWeight:700, color:statusColor(r.status), fontSize:12, textTransform:'uppercase' }}>{r.status}</span></td>
                        <td style={{ fontSize:12, color:'#6B7280' }}>{r.created_at ? new Date(r.created_at).toLocaleString() : '—'}</td>
                        <td>
                          {r.status === 'pending' && (
                            <div style={{ display:'flex', gap:6 }}>
                              <button className="sa-btn sm primary" onClick={() => { setModal({ type:'approve', row:r }); setNote('') }}>Approve</button>
                              <button className="sa-btn sm danger"   onClick={() => { setModal({ type:'reject',  row:r }); setNote('') }}>Reject</button>
                            </div>
                          )}
                          {r.review_note && <div style={{ fontSize:11, color:'#6B7280', marginTop:4 }}>{r.review_note}</div>}
                        </td>
                      </tr>
                    ))
              }
            </tbody>
          </table>
        </div>
      </div>

      {modal && (
        <Modal
          title={`${modal.type === 'approve' ? 'Approve' : 'Reject'} Approval #${modal.row.id}`}
          onClose={() => { setModal(null); setNote('') }}
          footer={<>
            <button className="sa-btn secondary" onClick={() => { setModal(null); setNote('') }}>Cancel</button>
            <button
              className={`sa-btn ${modal.type === 'approve' ? 'primary' : 'danger'}`}
              onClick={handleReview} disabled={saving}
            >{saving ? 'Saving…' : modal.type === 'approve' ? 'Approve' : 'Reject'}</button>
          </>}
        >
          <p style={{ margin:'0 0 12px', color:'#374151' }}>
            Action: <strong>{modal.row.action_type}</strong> by <strong>{modal.row.admin_name}</strong>
          </p>
          <div className="sa-form-group">
            <label>Note (optional)</label>
            <textarea className="sa-input" rows={3} value={note} onChange={e => setNote(e.target.value)}
              placeholder="Add a note for the admin…" style={{ resize:'vertical' }} />
          </div>
        </Modal>
      )}
    </>
  )
}

// ─── Phase 3: Config Tab ──────────────────────────────────────────────────────

const CFG = '/api/super-admin/config'

function ConfigTab() {
  const [subTab,      setSubTab]      = useState('thresholds')
  const [thresholds,  setThresholds]  = useState(null)
  const [templates,   setTemplates]   = useState([])
  const [companies,   setCompanies]   = useState([])
  const [selCompany,  setSelCompany]  = useState('')
  const [compCfg,     setCompCfg]     = useState([])
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState('')
  const [toast,       setToast]       = useState('')

  // Threshold form
  const [tHigh, setTHigh] = useState('')
  const [tLow,  setTLow]  = useState('')

  // Template form
  const [tmName, setTmName] = useState('')
  const [tmHigh, setTmHigh] = useState('')
  const [tmLow,  setTmLow]  = useState('')
  const [tmDesc, setTmDesc] = useState('')

  // Company config form
  const [ccField,  setCcField]  = useState('')
  const [ccValue,  setCcValue]  = useState('')
  const [ccLocked, setCcLocked] = useState(false)

  // Alert routing
  const [rtCompany, setRtCompany] = useState('')
  const [rtData,    setRtData]    = useState({})
  const [rtLoading, setRtLoading] = useState(false)

  // Escalation policy
  const [epCompany,  setEpCompany]  = useState('')
  const [epPolicy,   setEpPolicy]   = useState(null)
  const [epLoading,  setEpLoading]  = useState(false)
  const [epSaving,   setEpSaving]   = useState(false)

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3000) }

  const loadThresholds = useCallback(() =>
    get(`${CFG}/thresholds`).then(d => { setThresholds(d); setTHigh(d.temp_high); setTLow(d.temp_low) }).catch(e => setError(e.message))
  , [])

  const loadTemplates = useCallback(() =>
    get(`${CFG}/templates`).then(setTemplates).catch(e => setError(e.message))
  , [])

  const loadCompanies = useCallback(() =>
    get(`${SA}/companies`).then(setCompanies).catch(() => {})
  , [])

  const loadCompCfg = useCallback((cid) => {
    if (!cid) { setCompCfg([]); return }
    get(`${CFG}/companies/${cid}/config`).then(setCompCfg).catch(e => setError(e.message))
  }, [])

  useEffect(() => { loadThresholds(); loadTemplates(); loadCompanies() }, [loadThresholds, loadTemplates, loadCompanies])
  useEffect(() => { loadCompCfg(selCompany) }, [selCompany, loadCompCfg])

  const handleSetThresholds = async (e) => {
    e.preventDefault(); setError('')
    const h = parseFloat(tHigh), l = parseFloat(tLow)
    if (isNaN(h) || isNaN(l)) { setError('Enter valid numbers'); return }
    if (l >= h) { setError('Low must be less than High'); return }
    try {
      setLoading(true)
      await post(`${CFG}/thresholds`, { temp_high: h, temp_low: l })
      await loadThresholds()
      showToast('Global thresholds updated')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleCreateTemplate = async (e) => {
    e.preventDefault(); setError('')
    const h = parseFloat(tmHigh), l = parseFloat(tmLow)
    if (!tmName.trim()) { setError('Name is required'); return }
    if (isNaN(h) || isNaN(l)) { setError('Enter valid numbers'); return }
    if (l >= h) { setError('Low must be less than High'); return }
    try {
      setLoading(true)
      await post(`${CFG}/templates`, { name: tmName.trim(), temp_high: h, temp_low: l, description: tmDesc.trim() || null })
      setTmName(''); setTmHigh(''); setTmLow(''); setTmDesc('')
      await loadTemplates()
      showToast('Template created')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleApplyTemplate = async (id, name) => {
    if (!window.confirm(`Apply template "${name}" as global thresholds?`)) return
    setError('')
    try {
      await post(`${CFG}/templates/${id}/apply`)
      await loadThresholds()
      showToast(`Template "${name}" applied globally`)
    } catch (e) { setError(e.message) }
  }

  const handleDeleteTemplate = async (id, name) => {
    if (!window.confirm(`Delete template "${name}"?`)) return
    setError('')
    try {
      await del(`${CFG}/templates/${id}`)
      await loadTemplates()
      showToast('Template deleted')
    } catch (e) { setError(e.message) }
  }

  const handleSetCompCfg = async (e) => {
    e.preventDefault(); setError('')
    if (!selCompany) { setError('Select a company'); return }
    if (!ccField.trim()) { setError('Field name is required'); return }
    try {
      setLoading(true)
      await post(`${CFG}/companies/${selCompany}/config`, { field: ccField.trim(), value: ccValue, locked: ccLocked })
      setCcField(''); setCcValue(''); setCcLocked(false)
      loadCompCfg(selCompany)
      showToast('Config saved')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleRemoveCompCfg = async (field) => {
    if (!window.confirm(`Remove "${field}" override?`)) return
    try {
      await del(`${CFG}/companies/${selCompany}/config/${encodeURIComponent(field)}`)
      loadCompCfg(selCompany)
      showToast('Override removed')
    } catch (e) { setError(e.message) }
  }

  const loadRouting = useCallback((cid) => {
    if (!cid) { setRtData({}); return }
    setRtLoading(true)
    get(`${SA}/config/routing/${cid}`)
      .then(rows => {
        const map = {}
        rows.forEach(r => { map[r.severity] = r })
        setRtData(map)
      })
      .catch(() => {})
      .finally(() => setRtLoading(false))
  }, [])

  const saveRouting = async (severity, row) => {
    if (!rtCompany) return
    try {
      await patch(`${SA}/config/routing/${rtCompany}/${severity}`, {
        use_email:      row.use_email,
        use_sms:        row.use_sms,
        use_push:       row.use_push,
        use_escalation: row.use_escalation ?? 0,
      })
      showToast(`${severity} routing saved`)
    } catch (e) { setError(e.message) }
  }

  const loadPolicy = useCallback((cid) => {
    if (!cid) { setEpPolicy(null); return }
    setEpLoading(true)
    get(`${SA}/escalation/policy/${cid}`)
      .then(d => setEpPolicy({
        enabled:                 d.enabled                 ?? 1,
        initial_wait_minutes:    d.initial_wait_minutes    ?? 5,
        repeat_interval_minutes: d.repeat_interval_minutes ?? 10,
        max_escalations:         d.max_escalations         ?? 3,
        notify_super_admin:      d.notify_super_admin      ?? 0,
      }))
      .catch(e => setError(e.message))
      .finally(() => setEpLoading(false))
  }, [])

  const savePolicy = async () => {
    if (!epCompany || !epPolicy) return
    setEpSaving(true)
    try {
      await patch(`${SA}/escalation/policy/${epCompany}`, epPolicy)
      showToast('Escalation policy saved')
    } catch (e) { setError(e.message) }
    finally { setEpSaving(false) }
  }

  const SUB_TABS = [
    { id: 'thresholds', label: 'Global Thresholds'   },
    { id: 'templates',  label: 'Templates'            },
    { id: 'company',    label: 'Company Config'       },
    { id: 'routing',    label: 'Alert Routing'        },
    { id: 'escalation', label: 'Escalation Policy'   },
  ]

  return (
    <>
      {toast && <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46', padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>}

      {/* Sub-tab strip */}
      <div style={{ display:'flex', gap:8, marginBottom:20 }}>
        {SUB_TABS.map(s => (
          <button key={s.id} className={`sa-btn ${subTab === s.id ? 'primary' : 'secondary'}`}
            onClick={() => { setSubTab(s.id); setError('') }}>{s.label}</button>
        ))}
      </div>

      {error && <Err msg={error} />}

      {/* ── Global Thresholds ───────────────────────────────────────── */}
      {subTab === 'thresholds' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Current Global Thresholds</h2>
            {thresholds ? (
              <div className="sa-cfg-status">
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Temp High</span>
                  <span className="sa-cfg-stat-val danger">{thresholds.temp_high} °C</span>
                </div>
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Temp Low</span>
                  <span className="sa-cfg-stat-val info">{thresholds.temp_low} °C</span>
                </div>
                <div className="sa-cfg-stat" style={{ gridColumn:'1/-1' }}>
                  <span className="sa-cfg-stat-label">Source</span>
                  <span className="sa-cfg-stat-val">{thresholds.source}</span>
                </div>
                {thresholds.last_changed && (
                  <div className="sa-cfg-stat" style={{ gridColumn:'1/-1' }}>
                    <span className="sa-cfg-stat-label">Last changed</span>
                    <span className="sa-cfg-stat-val" style={{ fontSize:12 }}>{new Date(thresholds.last_changed).toLocaleString()}</span>
                  </div>
                )}
              </div>
            ) : <Spinner />}
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">Override Global Thresholds</h2>
            <form onSubmit={handleSetThresholds}>
              <div className="sa-cfg-row">
                <div className="sa-form-group">
                  <label>Temp High (°C)</label>
                  <input className="sa-input" type="number" step="0.1" value={tHigh}
                    onChange={e => setTHigh(e.target.value)} placeholder="e.g. 90" />
                </div>
                <div className="sa-form-group">
                  <label>Temp Low (°C)</label>
                  <input className="sa-input" type="number" step="0.1" value={tLow}
                    onChange={e => setTLow(e.target.value)} placeholder="e.g. 42" />
                </div>
              </div>
              <button className="sa-btn primary" type="submit" disabled={loading} style={{ marginTop:8 }}>
                {loading ? 'Saving…' : 'Apply Thresholds'}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* ── Templates ──────────────────────────────────────────────── */}
      {subTab === 'templates' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Create Template</h2>
            <form onSubmit={handleCreateTemplate}>
              <div className="sa-form-group">
                <label>Name</label>
                <input className="sa-input" value={tmName} onChange={e => setTmName(e.target.value)} placeholder="e.g. Industrial Cold Chain" />
              </div>
              <div className="sa-cfg-row">
                <div className="sa-form-group">
                  <label>Temp High (°C)</label>
                  <input className="sa-input" type="number" step="0.1" value={tmHigh} onChange={e => setTmHigh(e.target.value)} />
                </div>
                <div className="sa-form-group">
                  <label>Temp Low (°C)</label>
                  <input className="sa-input" type="number" step="0.1" value={tmLow} onChange={e => setTmLow(e.target.value)} />
                </div>
              </div>
              <div className="sa-form-group">
                <label>Description (optional)</label>
                <input className="sa-input" value={tmDesc} onChange={e => setTmDesc(e.target.value)} placeholder="Brief description…" />
              </div>
              <button className="sa-btn primary" type="submit" disabled={loading} style={{ marginTop:4 }}>
                {loading ? 'Creating…' : '+ Create Template'}
              </button>
            </form>
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">Saved Templates ({templates.length})</h2>
            {templates.length === 0
              ? <p style={{ color:'#6B7280', fontSize:13 }}>No templates yet.</p>
              : <div className="sa-table-wrap">
                  <table className="sa-table">
                    <thead><tr><th>Name</th><th>High</th><th>Low</th><th>Created</th><th>Actions</th></tr></thead>
                    <tbody>
                      {templates.map(t => (
                        <tr key={t.id}>
                          <td>
                            <span style={{ fontWeight:600 }}>{t.name}</span>
                            {t.description && <div style={{ fontSize:11, color:'#6B7280' }}>{t.description}</div>}
                          </td>
                          <td style={{ color:'#EF4444', fontWeight:600 }}>{t.temp_high} °C</td>
                          <td style={{ color:'#3B82F6', fontWeight:600 }}>{t.temp_low} °C</td>
                          <td style={{ fontSize:11, color:'#6B7280' }}>{new Date(t.created_at).toLocaleDateString()}</td>
                          <td>
                            <div style={{ display:'flex', gap:6 }}>
                              <button className="sa-btn sm primary" onClick={() => handleApplyTemplate(t.id, t.name)}>Apply</button>
                              <button className="sa-btn sm danger"  onClick={() => handleDeleteTemplate(t.id, t.name)}>Delete</button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
            }
          </div>
        </div>
      )}

      {/* ── Escalation Policy ──────────────────────────────────────── */}
      {subTab === 'escalation' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Escalation Policy</h2>
            <p style={{ fontSize: 13, color: '#6B7280', marginBottom: 16 }}>
              If an alert is not acknowledged within the initial wait time,
              subscribers will be re-notified at the configured interval.
            </p>
            <div className="sa-form-group">
              <label>Company</label>
              <select className="sa-input" value={epCompany}
                onChange={e => { setEpCompany(e.target.value); loadPolicy(e.target.value) }}>
                <option value="">— select company —</option>
                {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>

            {!epCompany ? (
              <p style={{ color: '#9CA3AF', fontSize: 13 }}>Select a company to configure its escalation policy.</p>
            ) : epLoading ? (
              <p style={{ color: '#9CA3AF', fontSize: 13 }}>Loading…</p>
            ) : epPolicy && (
              <>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginBottom: 20 }}>

                  <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#374151' }}>
                    <input type="checkbox" checked={!!epPolicy.enabled}
                      onChange={e => setEpPolicy(p => ({ ...p, enabled: e.target.checked ? 1 : 0 }))} />
                    <span><strong>Enabled</strong> — re-notify unacknowledged alerts</span>
                  </label>

                  <div className="sa-cfg-row" style={{ gap: 12 }}>
                    <div className="sa-form-group" style={{ flex: 1 }}>
                      <label>Initial wait (minutes)</label>
                      <input type="number" className="sa-input" min={1} max={1440}
                        value={epPolicy.initial_wait_minutes}
                        onChange={e => setEpPolicy(p => ({ ...p, initial_wait_minutes: Number(e.target.value) }))} />
                      <span style={{ fontSize: 11, color: '#9CA3AF' }}>
                        How long to wait before first re-notification
                      </span>
                    </div>
                    <div className="sa-form-group" style={{ flex: 1 }}>
                      <label>Repeat every (minutes)</label>
                      <input type="number" className="sa-input" min={1} max={1440}
                        value={epPolicy.repeat_interval_minutes}
                        onChange={e => setEpPolicy(p => ({ ...p, repeat_interval_minutes: Number(e.target.value) }))} />
                      <span style={{ fontSize: 11, color: '#9CA3AF' }}>
                        Interval between subsequent re-notifications
                      </span>
                    </div>
                    <div className="sa-form-group" style={{ flex: 1 }}>
                      <label>Max escalations</label>
                      <input type="number" className="sa-input" min={1} max={10}
                        value={epPolicy.max_escalations}
                        onChange={e => setEpPolicy(p => ({ ...p, max_escalations: Number(e.target.value) }))} />
                      <span style={{ fontSize: 11, color: '#9CA3AF' }}>
                        Stop re-notifying after this many attempts
                      </span>
                    </div>
                  </div>

                  <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#374151' }}>
                    <input type="checkbox" checked={!!epPolicy.notify_super_admin}
                      onChange={e => setEpPolicy(p => ({ ...p, notify_super_admin: e.target.checked ? 1 : 0 }))} />
                    <span><strong>Notify super admin</strong> on final escalation (requires super admin email configured)</span>
                  </label>
                </div>

                <div style={{ padding: '10px 14px', background: '#F3F4F6', borderRadius: 6, fontSize: 12, color: '#6B7280', marginBottom: 16 }}>
                  With these settings: re-notify after <strong>{epPolicy.initial_wait_minutes} min</strong>,
                  then every <strong>{epPolicy.repeat_interval_minutes} min</strong>,
                  up to <strong>{epPolicy.max_escalations}</strong> time(s).
                </div>

                <button className="sa-btn primary" onClick={savePolicy} disabled={epSaving}>
                  {epSaving ? 'Saving…' : 'Save Policy'}
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Alert Routing ──────────────────────────────────────────── */}
      {subTab === 'routing' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Alert Channel Routing</h2>
            <p style={{ fontSize: 13, color: '#6B7280', marginBottom: 16 }}>
              Control which channels fire for each severity level. Changes take effect on the next alert.
            </p>
            <div className="sa-form-group">
              <label>Company</label>
              <select className="sa-input" value={rtCompany}
                onChange={e => { setRtCompany(e.target.value); loadRouting(e.target.value) }}>
                <option value="">— select company —</option>
                {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>

            {!rtCompany ? (
              <p style={{ color: '#9CA3AF', fontSize: 13 }}>Select a company to view its routing rules.</p>
            ) : rtLoading ? (
              <p style={{ color: '#9CA3AF', fontSize: 13 }}>Loading…</p>
            ) : (
              <div className="sa-table-wrap">
                <table className="sa-table">
                  <thead>
                    <tr>
                      <th>Severity</th>
                      <th style={{ textAlign: 'center' }}>Email</th>
                      <th style={{ textAlign: 'center' }}>SMS</th>
                      <th style={{ textAlign: 'center' }}>Push</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {['WARNING', 'CRITICAL', 'EMERGENCY'].map(sev => {
                      const defaults = { use_email: 1, use_sms: sev !== 'WARNING' ? 1 : 0, use_push: 1, use_escalation: 0 }
                      const row = rtData[sev] ?? defaults
                      const sevColor = sev === 'EMERGENCY' ? '#EF4444' : sev === 'CRITICAL' ? '#F59E0B' : '#6366F1'
                      return (
                        <tr key={sev}>
                          <td>
                            <span style={{ fontWeight: 600, fontSize: 12, color: sevColor }}>
                              {sev}
                            </span>
                          </td>
                          <td style={{ textAlign: 'center' }}>
                            <input type="checkbox" checked={!!row.use_email}
                              onChange={e => setRtData(prev => ({
                                ...prev,
                                [sev]: { ...(prev[sev] ?? defaults), use_email: e.target.checked ? 1 : 0 },
                              }))} />
                          </td>
                          <td style={{ textAlign: 'center' }}>
                            <input type="checkbox" checked={!!row.use_sms}
                              onChange={e => setRtData(prev => ({
                                ...prev,
                                [sev]: { ...(prev[sev] ?? defaults), use_sms: e.target.checked ? 1 : 0 },
                              }))} />
                          </td>
                          <td style={{ textAlign: 'center' }}>
                            <input type="checkbox" checked={!!row.use_push}
                              onChange={e => setRtData(prev => ({
                                ...prev,
                                [sev]: { ...(prev[sev] ?? defaults), use_push: e.target.checked ? 1 : 0 },
                              }))} />
                          </td>
                          <td>
                            <button className="sa-btn sm primary"
                              onClick={() => saveRouting(sev, row)}>
                              Save
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Company Config ─────────────────────────────────────────── */}
      {subTab === 'company' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Set Company Config Override</h2>
            <div className="sa-form-group">
              <label>Company</label>
              <select className="sa-input" value={selCompany} onChange={e => setSelCompany(e.target.value)}>
                <option value="">— select company —</option>
                {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            {selCompany && (
              <form onSubmit={handleSetCompCfg}>
                <div className="sa-cfg-row">
                  <div className="sa-form-group">
                    <label>Field</label>
                    <input className="sa-input" value={ccField} onChange={e => setCcField(e.target.value)}
                      placeholder="e.g. temp_high, sms_enabled" />
                  </div>
                  <div className="sa-form-group">
                    <label>Value</label>
                    <input className="sa-input" value={ccValue} onChange={e => setCcValue(e.target.value)}
                      placeholder="e.g. 85, true, false" />
                  </div>
                </div>
                <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#374151', marginBottom:10 }}>
                  <input type="checkbox" checked={ccLocked} onChange={e => setCcLocked(e.target.checked)} />
                  Lock (advisory — marks field as super-admin controlled)
                </label>
                <button className="sa-btn primary" type="submit" disabled={loading}>
                  {loading ? 'Saving…' : 'Save Override'}
                </button>
              </form>
            )}
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">
              {selCompany
                ? `Overrides for ${companies.find(c => String(c.id) === String(selCompany))?.name ?? 'Company'}`
                : 'Select a company'}
            </h2>
            {!selCompany
              ? <p style={{ color:'#6B7280', fontSize:13 }}>Pick a company on the left to see its overrides.</p>
              : compCfg.length === 0
                ? <p style={{ color:'#6B7280', fontSize:13 }}>No overrides set.</p>
                : <div className="sa-table-wrap">
                    <table className="sa-table">
                      <thead><tr><th>Field</th><th>Value</th><th>Locked</th><th>Set by</th><th></th></tr></thead>
                      <tbody>
                        {compCfg.map(r => (
                          <tr key={r.id}>
                            <td style={{ fontFamily:'monospace', fontSize:12 }}>{r.field}</td>
                            <td style={{ fontFamily:'monospace', fontSize:12 }}>{r.value}</td>
                            <td>{r.locked ? <span className="sa-approval-tag">Locked</span> : <span style={{ color:'#9CA3AF', fontSize:12 }}>—</span>}</td>
                            <td style={{ fontSize:12, color:'#6B7280' }}>{r.set_by_name || '—'}</td>
                            <td>
                              <button className="sa-btn sm danger" onClick={() => handleRemoveCompCfg(r.field)}>Remove</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
            }
          </div>
        </div>
      )}
    </>
  )
}

// ─── Phase 4: Analytics Tab ───────────────────────────────────────────────────

const ANL = '/api/super-admin/analytics'

function ScoreBar({ score }) {
  const color = score >= 80 ? '#22C55E' : score >= 50 ? '#F59E0B' : score >= 20 ? '#EF4444' : '#7F1D1D'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 8, background: '#E5E7EB', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${score}%`, height: '100%', background: color, borderRadius: 4, transition: 'width .4s' }} />
      </div>
      <span style={{ fontSize: 13, fontWeight: 700, color, minWidth: 32 }}>{score}</span>
    </div>
  )
}

function TrendArrow({ direction }) {
  if (direction === 'rising')  return <span style={{ color: '#EF4444', fontWeight: 700 }}>↑ Rising</span>
  if (direction === 'falling') return <span style={{ color: '#3B82F6', fontWeight: 700 }}>↓ Falling</span>
  return <span style={{ color: '#6B7280', fontWeight: 700 }}>→ Stable</span>
}

function MiniSparkline({ values }) {
  if (!values || values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const w = 120, h = 32, pad = 3
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2)
    const y = h - pad - ((v - min) / range) * (h - pad * 2)
    return `${x},${y}`
  }).join(' ')
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke="#6366F1" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  )
}

function AlertHeatmapSA({ grid, days }) {
  const max = Math.max(...grid.flatMap(r => r), 1)
  const heat = (v) => {
    if (v === 0) return '#F3F4F6'
    const t = v / max
    if (t < 0.25) return '#FEF9C3'
    if (t < 0.5)  return '#FDE047'
    if (t < 0.75) return '#F97316'
    return '#DC2626'
  }
  const DAY_LABELS = days || ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']
  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ display: 'flex', gap: 3, paddingTop: 8, minWidth: 'max-content' }}>
        {/* Hour labels */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, paddingTop: 20, marginRight: 4 }}>
          {Array.from({ length: 24 }, (_, h) => (
            <div key={h} style={{ height: 14, fontSize: 9, color: '#9CA3AF', textAlign: 'right', lineHeight: '14px', minWidth: 22 }}>
              {h}h
            </div>
          ))}
        </div>
        {/* Day columns */}
        {DAY_LABELS.map((day, di) => (
          <div key={day} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div style={{ height: 18, fontSize: 10, color: '#6B7280', fontWeight: 600, textAlign: 'center', lineHeight: '18px' }}>{day}</div>
            {grid.map((hourRow, hi) => (
              <div key={hi}
                title={`${day} ${hi}h: ${hourRow[di]} alerts`}
                style={{
                  width: 22, height: 14,
                  borderRadius: 2,
                  background: heat(hourRow[di]),
                  cursor: 'default',
                }}
              />
            ))}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 8, fontSize: 10, color: '#6B7280' }}>
        <span>Low</span>
        {['#F3F4F6','#FEF9C3','#FDE047','#F97316','#DC2626'].map((c, i) => (
          <div key={i} style={{ width: 14, height: 10, borderRadius: 2, background: c }} />
        ))}
        <span>High</span>
      </div>
    </div>
  )
}

function AnalyticsTab() {
  const [subTab,    setSubTab]    = useState('summary')
  const [summary,   setSummary]   = useState(null)
  const [health,    setHealth]    = useState([])
  const [compare,   setCompare]   = useState([])
  const [anomalies,  setAnomalies]  = useState(null)
  const [trends,     setTrends]     = useState(null)
  const [anomalyLog, setAnomalyLog] = useState([])
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState('')

  // ── Company Analytics state ──────────────────────────────────────────────
  const [companies,     setCompanies]     = useState([])
  const [selCompany,    setSelCompany]    = useState('')
  const [coRange,       setCoRange]       = useState('30d')
  const [coLoading,     setCoLoading]     = useState(false)
  const [coError,       setCoError]       = useState('')
  const [coCharts,      setCoCharts]      = useState({})

  // ── Fleet Comparison state ───────────────────────────────────────────────
  const [fleetRange,    setFleetRange]    = useState('30d')
  const [fleetLoading,  setFleetLoading]  = useState(false)
  const [fleetError,    setFleetError]    = useState('')
  const [fleetData,     setFleetData]     = useState({})

  const load = useCallback(async (st) => {
    setLoading(true); setError('')
    try {
      if (st === 'summary') {
        const [s, h] = await Promise.all([get(`${ANL}/summary`), get(`${ANL}/companies/health`)])
        setSummary(s); setHealth(h)
      } else if (st === 'compare') {
        const d = await get(`${ANL}/companies/compare`)
        setCompare(d)
      } else if (st === 'anomalies') {
        const d = await get(`${ANL}/anomalies`)
        setAnomalies(d)
      } else if (st === 'trends') {
        const d = await get(`${ANL}/trends`)
        setTrends(d)
      } else if (st === 'anomaly-log') {
        const d = await get(`${SA}/anomalies`)
        setAnomalyLog(Array.isArray(d) ? d : [])
      } else if (st === 'company-analytics') {
        const list = await get(`${ANL}/companies/health`)
        setCompanies(list.map(c => ({ id: c.company_id, name: c.company_name })))
      } else if (st === 'fleet-comparison') {
        await loadFleet(fleetRange)
      }
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [fleetRange]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadCoCharts = useCallback(async (companyId, range) => {
    if (!companyId) return
    setCoLoading(true); setCoError('')
    const { from, to } = rangeToDates(range)
    const base = `${ANL}/companies/${companyId}`
    try {
      const [breach, heatmap, subResp, delivery, summary, sevDist, daily, hourly, weekly, ackTime] = await Promise.all([
        get(withDates(`${base}/charts/breach-frequency`, from, to)),
        get(withDates(`${base}/charts/alert-heatmap`,    from, to)),
        get(withDates(`${base}/charts/subscriber-response`, from, to)),
        get(withDates(`${base}/charts/delivery-rates`,   from, to)),
        get(withDates(`${base}/charts/summary-stats`,    from, to)),
        get(withDates(`${base}/charts/severity-dist`,    from, to)),
        get(withDates(`${base}/charts/daily-trend`,      from, to)),
        get(withDates(`${base}/charts/hourly-pattern`,   from, to)),
        get(withDates(`${base}/charts/weekly-avg`,       from, to)),
        get(withDates(`${base}/charts/ack-time`,         from, to)),
      ])
      setCoCharts({ breach, heatmap, subResp, delivery, summary, sevDist, daily, hourly, weekly, ackTime })
    } catch (e) { setCoError(e.message) }
    finally { setCoLoading(false) }
  }, [])

  const loadFleet = useCallback(async (range) => {
    setFleetLoading(true); setFleetError('')
    const { from, to } = rangeToDates(range)
    try {
      const [param, dailyTrend, breachCounts, benchmarks, healthScores] = await Promise.all([
        get(withDates(`${ANL}/compare/parameter`,    from, to)),
        get(withDates(`${ANL}/compare/daily-trend`,  from, to)),
        get(withDates(`${ANL}/compare/breach-counts`, from, to)),
        get(`${ANL}/benchmarks`),
        get(`${ANL}/health-scores`),
      ])
      setFleetData({ param, dailyTrend, breachCounts, benchmarks, healthScores })
    } catch (e) { setFleetError(e.message) }
    finally { setFleetLoading(false) }
  }, [])

  useEffect(() => { load(subTab) }, [subTab, load])

  useEffect(() => {
    if (subTab === 'company-analytics' && selCompany) loadCoCharts(selCompany, coRange)
  }, [selCompany, coRange, subTab, loadCoCharts])

  useEffect(() => {
    if (subTab === 'fleet-comparison') loadFleet(fleetRange)
  }, [fleetRange, subTab, loadFleet])

  const SUB_TABS = [
    { id: 'summary',           label: 'Summary & Health'   },
    { id: 'compare',           label: 'Compare Companies'  },
    { id: 'anomalies',         label: 'Anomaly Detection'  },
    { id: 'anomaly-log',       label: 'Anomaly Log'        },
    { id: 'trends',            label: 'Trend Forecast'     },
    { id: 'company-analytics', label: 'Company Analytics'  },
    { id: 'fleet-comparison',  label: 'Fleet Comparison'   },
  ]

  const statusColor = (s) => s === 'healthy' ? '#22C55E' : s === 'warning' ? '#F59E0B' : s === 'critical' ? '#EF4444' : '#7F1D1D'
  const gradeColor  = (g) => ({ A:'#22C55E', B:'#84CC16', C:'#F59E0B', D:'#EF4444', F:'#7F1D1D' })[g] || '#6B7280'

  return (
    <>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {SUB_TABS.map(s => (
          <button key={s.id} className={`sa-btn ${subTab === s.id ? 'primary' : 'secondary'}`}
            onClick={() => { setSubTab(s.id); setError('') }}>{s.label}</button>
        ))}
        <button className="sa-btn secondary" onClick={() => load(subTab)} disabled={loading} style={{ marginLeft: 'auto' }}>
          {loading ? '…' : '↺ Refresh'}
        </button>
      </div>

      {error && <Err msg={error} />}
      {loading && <div style={{ textAlign: 'center', padding: 40 }}><Spinner /></div>}

      {/* ── Summary & Health ───────────────────────────────────────── */}
      {!loading && subTab === 'summary' && summary && (
        <>
          {/* KPI strip */}
          <div className="sa-anl-kpi-strip">
            {[
              { label: 'Companies',       val: summary.companies,      color: '#6366F1' },
              { label: 'Open Alerts',     val: summary.open_alerts,    color: summary.open_alerts > 0 ? '#EF4444' : '#22C55E' },
              { label: 'Emergency Open',  val: summary.emergency_open, color: summary.emergency_open > 0 ? '#7F1D1D' : '#22C55E' },
              { label: 'Alerts (24 h)',   val: summary.alerts_24h,     color: '#F59E0B' },
              { label: 'Total Readings',  val: summary.total_readings, color: '#3B82F6' },
              { label: 'Active Admins',   val: summary.active_admins,  color: '#6B7280' },
            ].map(k => (
              <div key={k.label} className="sa-anl-kpi">
                <span className="sa-anl-kpi-val" style={{ color: k.color }}>{k.val}</span>
                <span className="sa-anl-kpi-label">{k.label}</span>
              </div>
            ))}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginTop: 20 }}>
            {/* Health scores */}
            <div className="sa-card">
              <h2 className="sa-card-title">Company Health Scores</h2>
              {health.length === 0
                ? <p style={{ color: '#6B7280', fontSize: 13 }}>No companies.</p>
                : health.map(h => (
                    <div key={h.company_id} style={{ marginBottom: 14 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: 13, fontWeight: 600 }}>{h.company_name}</span>
                        <span style={{ fontSize: 11, fontWeight: 600, color: statusColor(h.status), textTransform: 'uppercase' }}>{h.status}</span>
                      </div>
                      <ScoreBar score={h.score} />
                      <div style={{ display: 'flex', gap: 12, marginTop: 4, fontSize: 11, color: '#6B7280' }}>
                        {h.emergency_unacked > 0 && <span style={{ color: '#7F1D1D' }}>🔴 {h.emergency_unacked} emerg.</span>}
                        {h.critical_unacked  > 0 && <span style={{ color: '#EF4444' }}>🟠 {h.critical_unacked} critical</span>}
                        {h.warning_unacked   > 0 && <span style={{ color: '#F59E0B' }}>🟡 {h.warning_unacked} warning</span>}
                        {h.alerts_last_hour  > 0 && <span>⚡ {h.alerts_last_hour} this hour</span>}
                      </div>
                    </div>
                  ))
              }
            </div>

            {/* Top offenders */}
            <div className="sa-card">
              <h2 className="sa-card-title">Top Offenders (open alerts)</h2>
              {summary.top_offenders.length === 0
                ? <p style={{ color: '#22C55E', fontSize: 13 }}>All clear — no open alerts!</p>
                : summary.top_offenders.map(co => (
                    <div key={co.id} className="sa-anl-offender">
                      <span style={{ fontWeight: 600, fontSize: 14 }}>{co.name}</span>
                      <span className="sa-anl-badge-danger">{co.open_alerts} open</span>
                    </div>
                  ))
              }
              <div style={{ marginTop: 16, padding: '12px 0 0', borderTop: '1px solid #E5E7EB', fontSize: 12, color: '#6B7280' }}>
                Generated {new Date(summary.generated_at).toLocaleTimeString()}
              </div>
            </div>
          </div>
        </>
      )}

      {/* ── Compare Companies ──────────────────────────────────────── */}
      {!loading && subTab === 'compare' && (
        <div className="sa-card">
          <h2 className="sa-card-title">Company Alert Comparison</h2>
          <div className="sa-table-wrap">
            <table className="sa-table">
              <thead><tr>
                <th>Company</th>
                <th>Total Alerts</th>
                <th>Open</th>
                <th>24 h</th>
                <th>7 d</th>
                <th>Emergency</th>
                <th>Critical</th>
                <th>Warning</th>
                <th>Ack Rate</th>
              </tr></thead>
              <tbody>
                {compare.length === 0
                  ? <tr><td colSpan={9} className="sa-empty">No data.</td></tr>
                  : compare.map(r => (
                      <tr key={r.id}>
                        <td style={{ fontWeight: 600 }}>{r.name}</td>
                        <td>{r.total_alerts}</td>
                        <td style={{ color: r.open_alerts > 0 ? '#EF4444' : '#22C55E', fontWeight: 600 }}>{r.open_alerts}</td>
                        <td>{r.alerts_24h}</td>
                        <td>{r.alerts_7d}</td>
                        <td style={{ color: r.emergency_count > 0 ? '#7F1D1D' : '#6B7280', fontWeight: r.emergency_count > 0 ? 700 : 400 }}>{r.emergency_count}</td>
                        <td style={{ color: r.critical_count  > 0 ? '#EF4444' : '#6B7280' }}>{r.critical_count}</td>
                        <td style={{ color: r.warning_count   > 0 ? '#F59E0B' : '#6B7280' }}>{r.warning_count}</td>
                        <td>
                          <span style={{ color: r.ack_rate_pct >= 80 ? '#22C55E' : r.ack_rate_pct >= 50 ? '#F59E0B' : '#EF4444', fontWeight: 600 }}>
                            {r.ack_rate_pct}%
                          </span>
                        </td>
                      </tr>
                    ))
                }
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Anomaly Detection ──────────────────────────────────────── */}
      {!loading && subTab === 'anomalies' && anomalies && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <div className="sa-card">
            <h2 className="sa-card-title">Scan Parameters</h2>
            <div className="sa-cfg-status">
              <div className="sa-cfg-stat">
                <span className="sa-cfg-stat-label">Readings Scanned</span>
                <span className="sa-cfg-stat-val">{anomalies.readings_scanned}</span>
              </div>
              <div className="sa-cfg-stat">
                <span className="sa-cfg-stat-label">Mean Temp</span>
                <span className="sa-cfg-stat-val info">{anomalies.mean} °C</span>
              </div>
              <div className="sa-cfg-stat">
                <span className="sa-cfg-stat-label">Std Dev</span>
                <span className="sa-cfg-stat-val">{anomalies.std} °C</span>
              </div>
              <div className="sa-cfg-stat">
                <span className="sa-cfg-stat-label">Anomalies Found</span>
                <span className="sa-cfg-stat-val" style={{ color: anomalies.anomalies.length > 0 ? '#EF4444' : '#22C55E' }}>
                  {anomalies.anomalies.length}
                </span>
              </div>
            </div>
            {anomalies.note && <p style={{ color: '#6B7280', fontSize: 12, marginTop: 8 }}>{anomalies.note}</p>}
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">Detected Anomalies (Z ≥ 2.0)</h2>
            {anomalies.anomalies.length === 0
              ? <p style={{ color: '#22C55E', fontSize: 13 }}>No anomalies detected in last {anomalies.readings_scanned} readings.</p>
              : <div className="sa-table-wrap">
                  <table className="sa-table">
                    <thead><tr><th>Reading ID</th><th>Temp (°C)</th><th>Z-Score</th><th>Deviation</th><th>Timestamp</th></tr></thead>
                    <tbody>
                      {anomalies.anomalies.map(a => (
                        <tr key={a.reading_id}>
                          <td style={{ fontFamily: 'monospace' }}>#{a.reading_id}</td>
                          <td style={{ color: a.z_score >= 3 ? '#7F1D1D' : '#EF4444', fontWeight: 700 }}>{a.temperature}</td>
                          <td style={{ fontWeight: 700 }}>{a.z_score}σ</td>
                          <td style={{ color: a.deviation > 0 ? '#EF4444' : '#3B82F6' }}>
                            {a.deviation > 0 ? '+' : ''}{a.deviation}
                          </td>
                          <td style={{ fontSize: 11, color: '#6B7280' }}>{a.timestamp}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
            }
          </div>
        </div>
      )}

      {/* ── Anomaly Log ───────────────────────────────────────────── */}
      {!loading && subTab === 'anomaly-log' && (
        <div className="sa-card">
          <h2 className="sa-card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            Anomaly Log — Unresolved
            {anomalyLog.length > 0 && (
              <span style={{ background: '#EF4444', color: '#fff', borderRadius: 12, padding: '1px 8px', fontSize: 12 }}>
                {anomalyLog.length}
              </span>
            )}
          </h2>
          {anomalyLog.length === 0 ? (
            <p style={{ color: '#22C55E', fontSize: 13, padding: '12px 0' }}>No unresolved anomalies detected.</p>
          ) : (
            <div className="sa-table-wrap">
              <table className="sa-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Company</th>
                    <th>Description</th>
                    <th>Severity</th>
                    <th>Detected</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {anomalyLog.map(a => (
                    <tr key={a.id}>
                      <td style={{ fontWeight: 600, textTransform: 'capitalize', whiteSpace: 'nowrap' }}>
                        {a.anomaly_type.replace(/_/g, ' ')}
                      </td>
                      <td style={{ fontSize: 12 }}>{a.company_name}</td>
                      <td style={{ fontSize: 12, maxWidth: 320 }}>{a.description}</td>
                      <td>
                        <span style={{
                          padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                          background: a.severity === 'critical' ? '#FEE2E2' : a.severity === 'high' ? '#FEF3C7' : '#F3F4F6',
                          color:      a.severity === 'critical' ? '#991B1B' : a.severity === 'high' ? '#92400E' : '#374151',
                        }}>
                          {a.severity.toUpperCase()}
                        </span>
                      </td>
                      <td style={{ fontSize: 11, color: '#6B7280', whiteSpace: 'nowrap' }}>
                        {a.detected_at ? new Date(a.detected_at).toLocaleString() : '—'}
                      </td>
                      <td>
                        <button
                          className="sa-btn secondary"
                          style={{ padding: '3px 10px', fontSize: 12 }}
                          onClick={async () => {
                            try {
                              await patch(`${SA}/anomalies/${a.id}/resolve`)
                              setAnomalyLog(prev => prev.filter(x => x.id !== a.id))
                            } catch (e) { /* silent */ }
                          }}
                        >
                          Resolve
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Trend Forecast ─────────────────────────────────────────── */}
      {!loading && subTab === 'trends' && trends && !trends.error && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <div className="sa-card">
            <h2 className="sa-card-title">Trend Analysis</h2>
            <div className="sa-cfg-status">
              <div className="sa-cfg-stat">
                <span className="sa-cfg-stat-label">Direction</span>
                <span className="sa-cfg-stat-val" style={{ fontSize: 16 }}><TrendArrow direction={trends.direction} /></span>
              </div>
              <div className="sa-cfg-stat">
                <span className="sa-cfg-stat-label">Slope (°C/reading)</span>
                <span className="sa-cfg-stat-val" style={{ fontSize: 16, color: trends.slope > 0 ? '#EF4444' : trends.slope < 0 ? '#3B82F6' : '#6B7280' }}>
                  {trends.slope > 0 ? '+' : ''}{trends.slope}
                </span>
              </div>
              <div className="sa-cfg-stat">
                <span className="sa-cfg-stat-label">Latest Reading</span>
                <span className="sa-cfg-stat-val info">{trends.latest} °C</span>
              </div>
              <div className="sa-cfg-stat">
                <span className="sa-cfg-stat-label">Projected Next</span>
                <span className="sa-cfg-stat-val" style={{ color: trends.projected_next >= trends.high_threshold ? '#EF4444' : trends.projected_next <= trends.low_threshold ? '#3B82F6' : '#1E1B4B' }}>
                  {trends.projected_next} °C
                </span>
              </div>
            </div>

            {/* Predictive warning */}
            {trends.steps_to_high_threshold !== null && (
              <div className="sa-anl-predict-warn danger">
                ⚠ At current rate, temperature will reach HIGH threshold ({trends.high_threshold} °C)
                in approximately <strong>{trends.steps_to_high_threshold} readings</strong>.
              </div>
            )}
            {trends.steps_to_low_threshold !== null && (
              <div className="sa-anl-predict-warn info">
                ℹ At current rate, temperature will reach LOW threshold ({trends.low_threshold} °C)
                in approximately <strong>{trends.steps_to_low_threshold} readings</strong>.
              </div>
            )}
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">Last 10 Readings Sparkline</h2>
            <MiniSparkline values={trends.recent_values} />
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
              {trends.recent_values.map((v, i) => (
                <span key={i} style={{ fontSize: 11, background: '#F3F4F6', borderRadius: 4, padding: '2px 6px', fontFamily: 'monospace' }}>
                  {v}
                </span>
              ))}
            </div>
            <div style={{ marginTop: 12, fontSize: 12, color: '#6B7280' }}>
              Based on {trends.readings_used} readings · Mean {trends.mean_temperature} °C ·
              Thresholds: {trends.low_threshold} – {trends.high_threshold} °C
            </div>
          </div>
        </div>
      )}
      {!loading && subTab === 'trends' && trends?.error && <Err msg={trends.error} />}

      {/* ── Company Analytics ──────────────────────────────────────── */}
      {subTab === 'company-analytics' && (
        <div>
          {/* Controls */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 20 }}>
            <select className="sa-select" value={selCompany} onChange={e => setSelCompany(e.target.value)}>
              <option value="">— Select company —</option>
              {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <select className="sa-select" value={coRange} onChange={e => setCoRange(e.target.value)}>
              {RANGE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            {selCompany && (
              <button className="sa-btn secondary" onClick={() => loadCoCharts(selCompany, coRange)} disabled={coLoading}>
                {coLoading ? '…' : '↺ Refresh'}
              </button>
            )}
          </div>

          {!selCompany && (
            <div className="sa-card" style={{ textAlign: 'center', color: '#6B7280', padding: 48 }}>
              Select a company above to view its analytics.
            </div>
          )}

          {coError && <Err msg={coError} />}

          {coLoading && <div style={{ textAlign: 'center', padding: 40 }}><Spinner /></div>}

          {selCompany && !coLoading && Object.keys(coCharts).length > 0 && (() => {
            const { breach, heatmap, subResp, delivery, summary: sum, sevDist, daily, hourly, weekly, ackTime } = coCharts
            const COLORS = ['#7C3AED', '#EF4444', '#F59E0B', '#3B82F6', '#10B981']
            const tip = <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />

            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

                {/* Summary stat bar */}
                {sum && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px,1fr))', gap: 12 }}>
                    {[
                      { label: 'Total Alerts',  val: sum.total_alerts,    color: '#6366F1' },
                      { label: 'Open',          val: sum.open,            color: sum.open > 0 ? '#EF4444' : '#22C55E' },
                      { label: 'Acked',         val: sum.acked,           color: '#22C55E' },
                      { label: 'Ack Rate',      val: `${sum.ack_rate_pct}%`, color: sum.ack_rate_pct >= 80 ? '#22C55E' : '#F59E0B' },
                      { label: 'Emergency',     val: sum.emergency_count, color: sum.emergency_count > 0 ? '#7F1D1D' : '#6B7280' },
                      { label: 'Critical',      val: sum.critical_count,  color: sum.critical_count  > 0 ? '#EF4444' : '#6B7280' },
                    ].map(k => (
                      <div key={k.label} className="sa-cfg-stat">
                        <span className="sa-cfg-stat-label">{k.label}</span>
                        <span className="sa-cfg-stat-val" style={{ color: k.color, fontSize: 20 }}>{k.val}</span>
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                  {/* Breach frequency */}
                  <div className="sa-card">
                    <h2 className="sa-card-title">Daily Breach Frequency</h2>
                    {breach?.length > 0
                      ? <ResponsiveContainer width="100%" height={200}>
                          <BarChart data={breach}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                            <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                            <YAxis tick={{ fontSize: 10 }} />
                            {tip}
                            <Bar dataKey="breaches" fill="#EF4444" radius={[3,3,0,0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No breach data.</p>
                    }
                  </div>

                  {/* Severity distribution */}
                  <div className="sa-card">
                    <h2 className="sa-card-title">Alert Severity Distribution</h2>
                    {sevDist?.length > 0
                      ? <ResponsiveContainer width="100%" height={200}>
                          <PieChart>
                            <Pie data={sevDist} dataKey="count" nameKey="severity" cx="50%" cy="50%" outerRadius={75} label={({ severity, percent }) => `${severity} ${(percent*100).toFixed(0)}%`} labelLine={false}>
                              {sevDist.map((_, i) => <Cell key={i} fill={['#7F1D1D','#EF4444','#F59E0B','#3B82F6'][i % 4]} />)}
                            </Pie>
                            <Tooltip />
                          </PieChart>
                        </ResponsiveContainer>
                      : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No alert data.</p>
                    }
                  </div>

                  {/* Daily trend (open vs acked) */}
                  <div className="sa-card">
                    <h2 className="sa-card-title">Daily Alert Trend (Open vs Acked)</h2>
                    {daily?.length > 0
                      ? <ResponsiveContainer width="100%" height={200}>
                          <LineChart data={daily}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                            <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                            <YAxis tick={{ fontSize: 10 }} />
                            {tip}
                            <Legend />
                            <Line type="monotone" dataKey="open"  stroke="#EF4444" dot={false} strokeWidth={2} />
                            <Line type="monotone" dataKey="acked" stroke="#22C55E" dot={false} strokeWidth={2} />
                          </LineChart>
                        </ResponsiveContainer>
                      : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No daily data.</p>
                    }
                  </div>

                  {/* Hourly pattern */}
                  <div className="sa-card">
                    <h2 className="sa-card-title">Hourly Alert Pattern</h2>
                    {hourly?.length > 0
                      ? <ResponsiveContainer width="100%" height={200}>
                          <BarChart data={hourly}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                            <XAxis dataKey="hour" tick={{ fontSize: 10 }} tickFormatter={h => `${h}h`} />
                            <YAxis tick={{ fontSize: 10 }} />
                            {tip}
                            <Bar dataKey="count" fill="#7C3AED" radius={[2,2,0,0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No data.</p>
                    }
                  </div>

                  {/* Weekly average */}
                  <div className="sa-card">
                    <h2 className="sa-card-title">Weekly Alert Volume</h2>
                    {weekly?.length > 0
                      ? <ResponsiveContainer width="100%" height={200}>
                          <BarChart data={weekly}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                            <XAxis dataKey="week" tick={{ fontSize: 9 }} />
                            <YAxis tick={{ fontSize: 10 }} />
                            {tip}
                            <Bar dataKey="alerts" fill="#6366F1" radius={[3,3,0,0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No weekly data.</p>
                    }
                  </div>

                  {/* Ack time distribution */}
                  <div className="sa-card">
                    <h2 className="sa-card-title">Alert-to-Ack Time</h2>
                    {ackTime?.length > 0
                      ? <ResponsiveContainer width="100%" height={200}>
                          <BarChart data={ackTime}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                            <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
                            <YAxis tick={{ fontSize: 10 }} />
                            {tip}
                            <Bar dataKey="count" radius={[3,3,0,0]}>
                              {ackTime.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No ack-time data.</p>
                    }
                  </div>
                </div>

                {/* Alert heatmap */}
                <div className="sa-card">
                  <h2 className="sa-card-title">Alert Heatmap (Hour × Day)</h2>
                  {heatmap?.grid
                    ? <AlertHeatmapSA grid={heatmap.grid} days={heatmap.days} />
                    : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No heatmap data.</p>
                  }
                </div>

                {/* Subscriber response */}
                <div className="sa-card">
                  <h2 className="sa-card-title">Subscriber Response Rates</h2>
                  {subResp?.length > 0
                    ? <div style={{ overflowX: 'auto' }}>
                        <table className="sa-table">
                          <thead><tr>
                            <th>Subscriber</th><th>Channel</th>
                            <th>Total Alerts</th><th>Acked</th>
                            <th>Ack Rate</th><th>Avg Ack (min)</th>
                          </tr></thead>
                          <tbody>
                            {subResp.map((r, i) => (
                              <tr key={i}>
                                <td style={{ fontWeight: 600 }}>{r.name}</td>
                                <td>{r.channel}</td>
                                <td>{r.total_alerts}</td>
                                <td>{r.acked}</td>
                                <td>
                                  <span style={{
                                    fontWeight: 700,
                                    color: r.ack_rate_pct >= 80 ? '#22C55E' : r.ack_rate_pct >= 50 ? '#F59E0B' : '#EF4444',
                                  }}>
                                    {r.ack_rate_pct ?? '—'}%
                                  </span>
                                </td>
                                <td style={{ color: '#6B7280' }}>{r.avg_ack_minutes ?? '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No subscriber data.</p>
                  }
                </div>

                {/* Delivery rates */}
                <div className="sa-card">
                  <h2 className="sa-card-title">Channel Delivery Rates</h2>
                  {delivery?.available === false
                    ? <p style={{ color: '#9CA3AF', fontSize: 13 }}>No delivery receipt data.</p>
                    : delivery?.channels?.length > 0
                      ? <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', paddingTop: 8 }}>
                          {delivery.channels.map((ch, i) => (
                            <div key={i} style={{ textAlign: 'center', minWidth: 90 }}>
                              <div style={{
                                fontSize: 28, fontWeight: 800,
                                color: ch.success_rate >= 90 ? '#22C55E' : ch.success_rate >= 70 ? '#F59E0B' : '#EF4444',
                              }}>{ch.success_rate}%</div>
                              <div style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>{ch.channel}</div>
                              <div style={{ fontSize: 11, color: '#9CA3AF' }}>{ch.delivered}/{ch.total} sent</div>
                            </div>
                          ))}
                        </div>
                      : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No delivery data.</p>
                  }
                </div>

              </div>
            )
          })()}
        </div>
      )}

      {/* ── Fleet Comparison ────────────────────────────────────────── */}
      {subTab === 'fleet-comparison' && (
        <div>
          {/* Controls */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 20 }}>
            <select className="sa-select" value={fleetRange} onChange={e => setFleetRange(e.target.value)}>
              {RANGE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <button className="sa-btn secondary" onClick={() => loadFleet(fleetRange)} disabled={fleetLoading}>
              {fleetLoading ? '…' : '↺ Refresh'}
            </button>
          </div>

          {fleetError && <Err msg={fleetError} />}
          {fleetLoading && <div style={{ textAlign: 'center', padding: 40 }}><Spinner /></div>}

          {!fleetLoading && Object.keys(fleetData).length > 0 && (() => {
            const { param, dailyTrend, breachCounts, benchmarks: bm, healthScores } = fleetData
            const tip = <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />

            // Group dailyTrend by company name for multi-line chart
            const companies = [...new Set((dailyTrend || []).map(r => r.company))]
            const COLORS = ['#7C3AED','#EF4444','#F59E0B','#3B82F6','#10B981','#EC4899','#8B5CF6']

            const dailyByDate = {}
            ;(dailyTrend || []).forEach(r => {
              if (!dailyByDate[r.date]) dailyByDate[r.date] = { date: r.date }
              dailyByDate[r.date][r.company] = r.alerts
            })
            const dailyChartData = Object.values(dailyByDate).sort((a, b) => a.date.localeCompare(b.date))

            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

                {/* Benchmarks strip */}
                {bm && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px,1fr))', gap: 12 }}>
                    {[
                      { label: 'Fleet Companies',    val: bm.companies,              color: '#6366F1' },
                      { label: 'Total Alerts',        val: bm.fleet_total_alerts,    color: '#374151' },
                      { label: 'Fleet Ack Rate',      val: `${bm.fleet_ack_rate_pct}%`, color: bm.fleet_ack_rate_pct >= 75 ? '#22C55E' : '#F59E0B' },
                      { label: 'Delivery Rate',       val: `${bm.fleet_delivery_rate}%`, color: '#3B82F6' },
                      { label: 'Alerts / Company',    val: bm.avg_alerts_per_company, color: '#6B7280' },
                      { label: 'Last 24 h Alerts',    val: bm.alerts_last_24h,       color: bm.alerts_last_24h > 0 ? '#EF4444' : '#22C55E' },
                    ].map(k => (
                      <div key={k.label} className="sa-cfg-stat">
                        <span className="sa-cfg-stat-label">{k.label}</span>
                        <span className="sa-cfg-stat-val" style={{ color: k.color, fontSize: 18 }}>{k.val}</span>
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                  {/* Total breaches by company */}
                  <div className="sa-card">
                    <h2 className="sa-card-title">Total Breaches by Company</h2>
                    {breachCounts?.length > 0
                      ? <ResponsiveContainer width="100%" height={220}>
                          <BarChart data={breachCounts} layout="vertical">
                            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                            <XAxis type="number" tick={{ fontSize: 10 }} />
                            <YAxis type="category" dataKey="name" width={90} tick={{ fontSize: 10 }} />
                            {tip}
                            <Bar dataKey="breaches" radius={[0,3,3,0]}>
                              {breachCounts.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No breach data.</p>
                    }
                  </div>

                  {/* Alert comparison table */}
                  <div className="sa-card">
                    <h2 className="sa-card-title">Company Alert Comparison</h2>
                    {param?.length > 0
                      ? <div style={{ overflowX: 'auto' }}>
                          <table className="sa-table">
                            <thead><tr>
                              <th>Company</th><th>Total</th>
                              <th>Emergency</th><th>Critical</th><th>Warning</th><th>Ack Rate</th>
                            </tr></thead>
                            <tbody>
                              {param.map((r, i) => (
                                <tr key={i}>
                                  <td style={{ fontWeight: 600 }}>{r.name}</td>
                                  <td>{r.total_alerts}</td>
                                  <td style={{ color: r.emergency > 0 ? '#7F1D1D' : '#6B7280', fontWeight: r.emergency > 0 ? 700 : 400 }}>{r.emergency}</td>
                                  <td style={{ color: r.critical  > 0 ? '#EF4444' : '#6B7280' }}>{r.critical}</td>
                                  <td style={{ color: r.warning   > 0 ? '#F59E0B' : '#6B7280' }}>{r.warning}</td>
                                  <td style={{ fontWeight: 700, color: r.ack_rate_pct >= 80 ? '#22C55E' : r.ack_rate_pct >= 50 ? '#F59E0B' : '#EF4444' }}>
                                    {r.ack_rate_pct}%
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No comparison data.</p>
                    }
                  </div>
                </div>

                {/* Cross-company daily trend */}
                <div className="sa-card">
                  <h2 className="sa-card-title">Daily Alert Trend — All Companies</h2>
                  {dailyChartData.length > 0
                    ? <ResponsiveContainer width="100%" height={240}>
                        <LineChart data={dailyChartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                          <XAxis dataKey="date" tick={{ fontSize: 9 }} />
                          <YAxis tick={{ fontSize: 10 }} />
                          {tip}
                          <Legend />
                          {companies.map((co, i) => (
                            <Line key={co} type="monotone" dataKey={co} stroke={COLORS[i % COLORS.length]}
                              dot={false} strokeWidth={2} />
                          ))}
                        </LineChart>
                      </ResponsiveContainer>
                    : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No trend data.</p>
                  }
                </div>

                {/* Health scores v2 */}
                <div className="sa-card">
                  <h2 className="sa-card-title">Company Health Scores (Grade A–F)</h2>
                  {healthScores?.length > 0
                    ? <div className="sa-table-wrap">
                        <table className="sa-table">
                          <thead><tr>
                            <th>Company</th><th>Grade</th><th>Score</th>
                            <th>Breach</th><th>Ack</th><th>Delivery</th><th>Uptime</th>
                            <th>Open Emergency</th>
                          </tr></thead>
                          <tbody>
                            {healthScores.map(r => (
                              <tr key={r.company_id}>
                                <td style={{ fontWeight: 600 }}>{r.company_name}</td>
                                <td>
                                  <span style={{
                                    fontWeight: 800, fontSize: 16,
                                    color: gradeColor(r.grade),
                                  }}>{r.grade}</span>
                                </td>
                                <td>
                                  <ScoreBar score={r.composite} />
                                  <span style={{ fontSize: 11, color: '#6B7280' }}>{r.composite}</span>
                                </td>
                                <td style={{ fontSize: 12 }}>{r.breach_score}</td>
                                <td style={{ fontSize: 12 }}>{r.ack_score}%</td>
                                <td style={{ fontSize: 12 }}>{r.delivery_score}%</td>
                                <td style={{ fontSize: 12 }}>{r.uptime_score}</td>
                                <td style={{ color: r.open_emergency > 0 ? '#7F1D1D' : '#22C55E', fontWeight: 700 }}>
                                  {r.open_emergency}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No health score data.</p>
                  }
                </div>

              </div>
            )
          })()}
        </div>
      )}
    </>
  )
}

// ─── Phase 5: Communications Tab ─────────────────────────────────────────────

const COMMS = '/api/super-admin/comms'

function CommsTab() {
  const [subTab,     setSubTab]     = useState('messages')
  const [companies,  setCompanies]  = useState([])
  const [selCompany, setSelCompany] = useState('')

  // Messages
  const [messages,  setMessages]  = useState([])
  const [msgSubj,   setMsgSubj]   = useState('')
  const [msgBody,   setMsgBody]   = useState('')

  // Scheduled broadcasts
  const [scheduled,    setScheduled]    = useState([])
  const [schTitle,     setSchTitle]     = useState('')
  const [schMessage,   setSchMessage]   = useState('')
  const [schDateTime,  setSchDateTime]  = useState('')

  // Notes
  const [notes,      setNotes]      = useState([])
  const [noteText,   setNoteText]   = useState('')
  const [editNote,   setEditNote]   = useState(null)   // { id, content }

  // Onboarding
  const [checklist,  setChecklist]  = useState(null)
  const [newItem,    setNewItem]    = useState('')

  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState('')
  const [toast,      setToast]      = useState('')

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3000) }

  const loadCompanies = useCallback(() =>
    get(`${SA}/companies`).then(setCompanies).catch(() => {}), [])

  const loadMessages = useCallback(() => {
    if (!selCompany) return
    get(`${COMMS}/messages/${selCompany}`).then(setMessages).catch(e => setError(e.message))
  }, [selCompany])

  const loadScheduled = useCallback(() =>
    get(`${COMMS}/broadcast/scheduled`).then(setScheduled).catch(e => setError(e.message)), [])

  const loadNotes = useCallback(() => {
    if (!selCompany) return
    get(`${COMMS}/notes/${selCompany}`).then(setNotes).catch(e => setError(e.message))
  }, [selCompany])

  const loadChecklist = useCallback(() => {
    if (!selCompany) return
    get(`${COMMS}/onboarding/${selCompany}`).then(setChecklist).catch(e => setError(e.message))
  }, [selCompany])

  useEffect(() => { loadCompanies() }, [loadCompanies])

  useEffect(() => {
    setMessages([]); setNotes([]); setChecklist(null)
    if (subTab === 'messages')    loadMessages()
    if (subTab === 'scheduled')   loadScheduled()
    if (subTab === 'notes')       loadNotes()
    if (subTab === 'onboarding')  loadChecklist()
  }, [subTab, selCompany, loadMessages, loadScheduled, loadNotes, loadChecklist])

  // Company selector (used by messages, notes, onboarding sub-tabs)
  const CompanyPicker = () => (
    <div className="sa-form-group" style={{ marginBottom: 16 }}>
      <label>Company</label>
      <select className="sa-input" value={selCompany} onChange={e => { setSelCompany(e.target.value); setError('') }}>
        <option value="">— select company —</option>
        {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </div>
  )

  // ── Send Message ──────────────────────────────────────────────
  const handleSendMessage = async (e) => {
    e.preventDefault(); setError('')
    if (!selCompany) { setError('Select a company'); return }
    if (!msgSubj.trim() || !msgBody.trim()) { setError('Subject and body are required'); return }
    setLoading(true)
    try {
      await post(`${COMMS}/messages/${selCompany}`, { subject: msgSubj.trim(), body: msgBody.trim() })
      setMsgSubj(''); setMsgBody('')
      loadMessages()
      showToast('Message sent')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  // ── Schedule Broadcast ────────────────────────────────────────
  const handleSchedule = async (e) => {
    e.preventDefault(); setError('')
    if (!schTitle.trim() || !schMessage.trim() || !schDateTime) {
      setError('All fields are required'); return
    }
    setLoading(true)
    try {
      await post(`${COMMS}/broadcast/scheduled`, {
        title: schTitle.trim(), message: schMessage.trim(),
        scheduled_at: new Date(schDateTime).toISOString(),
      })
      setSchTitle(''); setSchMessage(''); setSchDateTime('')
      loadScheduled()
      showToast('Broadcast scheduled')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleCancelBroadcast = async (id, title) => {
    if (!window.confirm(`Cancel scheduled broadcast "${title}"?`)) return
    try {
      await del(`${COMMS}/broadcast/scheduled/${id}`)
      loadScheduled(); showToast('Broadcast cancelled')
    } catch (e) { setError(e.message) }
  }

  // ── Notes ─────────────────────────────────────────────────────
  const handleCreateNote = async (e) => {
    e.preventDefault(); setError('')
    if (!selCompany) { setError('Select a company'); return }
    if (!noteText.trim()) { setError('Note cannot be empty'); return }
    setLoading(true)
    try {
      await post(`${COMMS}/notes/${selCompany}`, { content: noteText.trim() })
      setNoteText(''); loadNotes(); showToast('Note saved')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleUpdateNote = async () => {
    if (!editNote?.content.trim()) return
    try {
      await put(`${COMMS}/notes/${editNote.id}`, { content: editNote.content.trim() })
      setEditNote(null); loadNotes(); showToast('Note updated')
    } catch (e) { setError(e.message) }
  }

  const handleDeleteNote = async (id) => {
    if (!window.confirm('Delete this note?')) return
    try {
      await del(`${COMMS}/notes/${id}`)
      loadNotes(); showToast('Note deleted')
    } catch (e) { setError(e.message) }
  }

  // ── Onboarding ────────────────────────────────────────────────
  const handleAddItem = async (e) => {
    e.preventDefault(); setError('')
    if (!selCompany) { setError('Select a company'); return }
    if (!newItem.trim()) { setError('Item text required'); return }
    setLoading(true)
    try {
      await post(`${COMMS}/onboarding/${selCompany}`, { item: newItem.trim() })
      setNewItem(''); loadChecklist(); showToast('Item added')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleToggle = async (id, done) => {
    try {
      await patch(`${COMMS}/onboarding/${id}`, { done: !done })
      loadChecklist()
    } catch (e) { setError(e.message) }
  }

  const handleRemoveItem = async (id) => {
    if (!window.confirm('Remove this checklist item?')) return
    try {
      await del(`${COMMS}/onboarding/${id}`)
      loadChecklist(); showToast('Item removed')
    } catch (e) { setError(e.message) }
  }

  const SUB_TABS = [
    { id: 'messages',   label: 'Direct Messages'        },
    { id: 'scheduled',  label: 'Scheduled Broadcasts'   },
    { id: 'notes',      label: 'Client Notes'           },
    { id: 'onboarding', label: 'Onboarding Checklist'   },
  ]

  return (
    <>
      {toast && <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46', padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>}

      <div style={{ display:'flex', gap:8, marginBottom:20, flexWrap:'wrap' }}>
        {SUB_TABS.map(s => (
          <button key={s.id} className={`sa-btn ${subTab === s.id ? 'primary' : 'secondary'}`}
            onClick={() => { setSubTab(s.id); setError('') }}>{s.label}</button>
        ))}
      </div>

      {error && <Err msg={error} />}

      {/* ── Direct Messages ─────────────────────────────────────── */}
      {subTab === 'messages' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Send Message</h2>
            <CompanyPicker />
            <form onSubmit={handleSendMessage}>
              <div className="sa-form-group">
                <label>Subject</label>
                <input className="sa-input" value={msgSubj} onChange={e => setMsgSubj(e.target.value)} placeholder="e.g. System maintenance window" />
              </div>
              <div className="sa-form-group">
                <label>Message</label>
                <textarea className="sa-input" rows={5} value={msgBody} onChange={e => setMsgBody(e.target.value)}
                  placeholder="Write your message…" style={{ resize:'vertical' }} />
              </div>
              <button className="sa-btn primary" type="submit" disabled={loading || !selCompany}>
                {loading ? 'Sending…' : 'Send Message'}
              </button>
            </form>
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">
              {selCompany
                ? `Messages — ${companies.find(c => String(c.id) === String(selCompany))?.name ?? ''}`
                : 'Select a company'}
            </h2>
            {!selCompany
              ? <p style={{ color:'#6B7280', fontSize:13 }}>Pick a company to see sent messages.</p>
              : messages.length === 0
                ? <p style={{ color:'#6B7280', fontSize:13 }}>No messages sent yet.</p>
                : messages.map(m => (
                    <div key={m.id} className="sa-comms-msg-card">
                      <div className="sa-comms-msg-subject">{m.subject}</div>
                      <div className="sa-comms-msg-body">{m.body}</div>
                      <div className="sa-comms-msg-meta">
                        Sent by {m.sent_by_name || '—'} · {m.sent_at ? new Date(m.sent_at).toLocaleString() : ''}
                        {m.read_at && <span style={{ color:'#22C55E', marginLeft:8 }}>✓ Read</span>}
                      </div>
                    </div>
                  ))
            }
          </div>
        </div>
      )}

      {/* ── Scheduled Broadcasts ────────────────────────────────── */}
      {subTab === 'scheduled' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Schedule a Broadcast</h2>
            <form onSubmit={handleSchedule}>
              <div className="sa-form-group">
                <label>Title</label>
                <input className="sa-input" value={schTitle} onChange={e => setSchTitle(e.target.value)} placeholder="e.g. Planned downtime notice" />
              </div>
              <div className="sa-form-group">
                <label>Message</label>
                <textarea className="sa-input" rows={4} value={schMessage} onChange={e => setSchMessage(e.target.value)}
                  placeholder="Broadcast content…" style={{ resize:'vertical' }} />
              </div>
              <div className="sa-form-group">
                <label>Send At</label>
                <input className="sa-input" type="datetime-local" value={schDateTime} onChange={e => setSchDateTime(e.target.value)} />
              </div>
              <button className="sa-btn primary" type="submit" disabled={loading}>
                {loading ? 'Scheduling…' : '+ Schedule Broadcast'}
              </button>
            </form>
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">Pending Broadcasts ({scheduled.length})</h2>
            {scheduled.length === 0
              ? <p style={{ color:'#6B7280', fontSize:13 }}>No broadcasts scheduled.</p>
              : scheduled.map(b => (
                  <div key={b.id} className="sa-comms-sched-card">
                    <div style={{ fontWeight:600, marginBottom:4 }}>{b.title}</div>
                    <div style={{ fontSize:12, color:'#6B7280', marginBottom:8 }}>{b.message?.slice(0, 100)}{b.message?.length > 100 ? '…' : ''}</div>
                    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                      <span style={{ fontSize:12, color:'#6366F1', fontWeight:600 }}>
                        🕐 {b.scheduled_at ? new Date(b.scheduled_at).toLocaleString() : '—'}
                      </span>
                      <button className="sa-btn sm danger" onClick={() => handleCancelBroadcast(b.id, b.title)}>Cancel</button>
                    </div>
                  </div>
                ))
            }
          </div>
        </div>
      )}

      {/* ── Client Notes ────────────────────────────────────────── */}
      {subTab === 'notes' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Add Note</h2>
            <CompanyPicker />
            {selCompany && (
              <form onSubmit={handleCreateNote}>
                <div className="sa-form-group">
                  <label>Note</label>
                  <textarea className="sa-input" rows={6} value={noteText} onChange={e => setNoteText(e.target.value)}
                    placeholder="Add a CRM note about this company…" style={{ resize:'vertical' }} />
                </div>
                <button className="sa-btn primary" type="submit" disabled={loading}>
                  {loading ? 'Saving…' : 'Save Note'}
                </button>
              </form>
            )}
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">
              {selCompany
                ? `Notes — ${companies.find(c => String(c.id) === String(selCompany))?.name ?? ''}`
                : 'Select a company'}
            </h2>
            {!selCompany
              ? <p style={{ color:'#6B7280', fontSize:13 }}>Pick a company to see notes.</p>
              : notes.length === 0
                ? <p style={{ color:'#6B7280', fontSize:13 }}>No notes yet.</p>
                : notes.map(n => (
                    <div key={n.id} className="sa-comms-note-card">
                      {editNote?.id === n.id
                        ? <>
                            <textarea className="sa-input" rows={4} value={editNote.content}
                              onChange={e => setEditNote({ ...editNote, content: e.target.value })}
                              style={{ resize:'vertical', marginBottom:8 }} />
                            <div style={{ display:'flex', gap:8 }}>
                              <button className="sa-btn sm primary" onClick={handleUpdateNote}>Save</button>
                              <button className="sa-btn sm secondary" onClick={() => setEditNote(null)}>Cancel</button>
                            </div>
                          </>
                        : <>
                            <p style={{ margin:'0 0 8px', fontSize:13, color:'#374151', whiteSpace:'pre-wrap' }}>{n.content}</p>
                            <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                              <span style={{ fontSize:11, color:'#9CA3AF' }}>
                                {n.created_by_name} · {n.created_at ? new Date(n.created_at).toLocaleDateString() : ''}
                                {n.updated_at !== n.created_at ? ' (edited)' : ''}
                              </span>
                              <div style={{ display:'flex', gap:6 }}>
                                <button className="sa-btn sm secondary" onClick={() => setEditNote({ id: n.id, content: n.content })}>Edit</button>
                                <button className="sa-btn sm danger"    onClick={() => handleDeleteNote(n.id)}>Delete</button>
                              </div>
                            </div>
                          </>
                      }
                    </div>
                  ))
            }
          </div>
        </div>
      )}

      {/* ── Onboarding Checklist ─────────────────────────────────── */}
      {subTab === 'onboarding' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Add Checklist Item</h2>
            <CompanyPicker />
            {selCompany && (
              <>
                {checklist && (
                  <div className="sa-comms-progress-wrap">
                    <div style={{ display:'flex', justifyContent:'space-between', fontSize:13, marginBottom:6 }}>
                      <span style={{ fontWeight:600 }}>Progress</span>
                      <span style={{ color:'#6B7280' }}>{checklist.done}/{checklist.total} done</span>
                    </div>
                    <div style={{ height:8, background:'#E5E7EB', borderRadius:4, overflow:'hidden' }}>
                      <div style={{ width:`${checklist.progress_pct}%`, height:'100%', background:'#22C55E', borderRadius:4, transition:'width .3s' }} />
                    </div>
                    <div style={{ fontSize:11, color:'#6B7280', marginTop:4, textAlign:'right' }}>{checklist.progress_pct}%</div>
                  </div>
                )}
                <form onSubmit={handleAddItem} style={{ marginTop:12 }}>
                  <div className="sa-form-group">
                    <label>New item</label>
                    <input className="sa-input" value={newItem} onChange={e => setNewItem(e.target.value)}
                      placeholder="e.g. Configure email alerts" />
                  </div>
                  <button className="sa-btn primary" type="submit" disabled={loading}>
                    {loading ? 'Adding…' : '+ Add Item'}
                  </button>
                </form>
              </>
            )}
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">
              {selCompany && checklist
                ? `Checklist — ${checklist.company_name}`
                : 'Select a company'}
            </h2>
            {!selCompany
              ? <p style={{ color:'#6B7280', fontSize:13 }}>Pick a company to see its checklist.</p>
              : !checklist || checklist.items.length === 0
                ? <p style={{ color:'#6B7280', fontSize:13 }}>No checklist items yet.</p>
                : checklist.items.map(item => (
                    <div key={item.id} className={`sa-comms-check-item ${item.done ? 'done' : ''}`}>
                      <input type="checkbox" checked={!!item.done}
                        onChange={() => handleToggle(item.id, item.done)}
                        style={{ width:16, height:16, cursor:'pointer', flexShrink:0 }} />
                      <span style={{ flex:1, fontSize:13, textDecoration: item.done ? 'line-through' : 'none', color: item.done ? '#9CA3AF' : '#374151' }}>
                        {item.item}
                      </span>
                      <button className="sa-btn sm danger" onClick={() => handleRemoveItem(item.id)}>✕</button>
                    </div>
                  ))
            }
          </div>
        </div>
      )}
    </>
  )
}

// ─── Phase 6: Billing Tab ────────────────────────────────────────────────────

const BIL = '/api/super-admin/billing'

function UsageBar({ used, max, label }) {
  const pct   = max > 0 ? Math.min(100, Math.round(used / max * 100)) : 0
  const color  = pct >= 90 ? '#EF4444' : pct >= 70 ? '#F59E0B' : '#22C55E'
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 3 }}>
        <span style={{ color: '#6B7280' }}>{label}</span>
        <span style={{ fontWeight: 600, color }}>{used} / {max} ({pct}%)</span>
      </div>
      <div style={{ height: 6, background: '#E5E7EB', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width .3s' }} />
      </div>
    </div>
  )
}

function TierBadge({ name }) {
  const colors = {
    Free:         { bg: '#F3F4F6', color: '#6B7280' },
    Basic:        { bg: '#DBEAFE', color: '#1D4ED8' },
    Professional: { bg: '#EDE9FE', color: '#6D28D9' },
    Enterprise:   { bg: '#FEF3C7', color: '#92400E' },
  }
  const style = colors[name] || { bg: '#F3F4F6', color: '#374151' }
  return (
    <span style={{ display: 'inline-block', padding: '2px 10px', borderRadius: 12,
      background: style.bg, color: style.color, fontSize: 12, fontWeight: 700 }}>
      {name || 'No tier'}
    </span>
  )
}

function BillingTab() {
  const [subTab,    setSubTab]    = useState('overview')
  const [overview,  setOverview]  = useState([])
  const [tiers,     setTiers]     = useState([])
  const [companies, setCompanies] = useState([])
  const [selCo,     setSelCo]     = useState('')
  const [subData,   setSubData]   = useState(null)
  const [report,    setReport]    = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')
  const [toast,     setToast]     = useState('')

  // Tier form
  const [tmName, setTmName] = useState('')
  const [tmMaxS, setTmMaxS] = useState('')
  const [tmMaxD, setTmMaxD] = useState('')
  const [tmChan, setTmChan] = useState('sms,email,push')
  const [tmPrice,setTmPrice]= useState('')
  const [tmDesc, setTmDesc] = useState('')

  // Quota override form
  const [qMaxS, setQMaxS] = useState('')
  const [qMaxD, setQMaxD] = useState('')
  const [qChan, setQChan] = useState('')

  // Usage dashboard
  const [usageData,    setUsageData]    = useState([])
  const [grantModal,   setGrantModal]   = useState(null)  // { company_id, company_name }
  const [grantChannel, setGrantChannel] = useState('sms')
  const [grantAmount,  setGrantAmount]  = useState('')

  // Task 3: month/year-parameterized monthly report
  const now = new Date()
  const [reportMonth,   setReportMonth]   = useState(String(now.getMonth() + 1))
  const [reportYear,    setReportYear]    = useState(String(now.getFullYear()))
  const [monthlyReport, setMonthlyReport] = useState(null)
  const [reportLoading, setReportLoading] = useState(false)

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3000) }

  const loadOverview = useCallback(() =>
    get(`${BIL}/overview`).then(setOverview).catch(e => setError(e.message)), [])
  const loadTiers = useCallback(() =>
    get(`${BIL}/tiers`).then(setTiers).catch(e => setError(e.message)), [])
  const loadCompanies = useCallback(() =>
    get(`${SA}/companies`).then(setCompanies).catch(() => {}), [])

  const loadSubData = useCallback(() => {
    if (!selCo) return
    setLoading(true)
    Promise.all([
      get(`${BIL}/companies/${selCo}/subscription`),
      get(`${BIL}/companies/${selCo}/usage`),
    ]).then(([sub, usage]) => setSubData({ sub, usage }))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [selCo])

  const loadReport = useCallback(() => {
    if (!selCo) return
    setLoading(true)
    get(`${BIL}/report/${selCo}`)
      .then(setReport)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [selCo])

  const loadUsage = useCallback(() => {
    get(`${BIL}/usage`)
      .then(d => setUsageData(Array.isArray(d) ? d : []))
      .catch(e => setError(e.message))
  }, [])

  const loadMonthlyReport = useCallback(() => {
    if (!selCo) return
    setReportLoading(true)
    setMonthlyReport(null)
    get(`${BIL}/companies/${selCo}/report?month=${reportMonth}&year=${reportYear}`)
      .then(setMonthlyReport)
      .catch(e => setError(e.message))
      .finally(() => setReportLoading(false))
  }, [selCo, reportMonth, reportYear])

  useEffect(() => { loadCompanies(); loadTiers() }, [loadCompanies, loadTiers])
  useEffect(() => {
    setError('')
    if (subTab === 'overview')      loadOverview()
    if (subTab === 'subscription')  loadSubData()
    if (subTab === 'report')        loadReport()
    if (subTab === 'usage')         loadUsage()
  }, [subTab, selCo, loadOverview, loadSubData, loadReport, loadUsage])

  // Auto-refresh usage dashboard every 5 minutes
  useEffect(() => {
    if (subTab !== 'usage') return
    const t = setInterval(loadUsage, 300_000)
    return () => clearInterval(t)
  }, [subTab, loadUsage])

  const handleCreateTier = async (e) => {
    e.preventDefault(); setError('')
    if (!tmName.trim() || !tmMaxS || !tmMaxD) { setError('Name, max subscribers and max devices are required'); return }
    setLoading(true)
    try {
      await post(`${BIL}/tiers`, {
        name: tmName.trim(), max_subscribers: parseInt(tmMaxS), max_devices: parseInt(tmMaxD),
        allowed_channels: tmChan.trim(), price_monthly: tmPrice.trim() || '0',
        description: tmDesc.trim() || null,
      })
      setTmName(''); setTmMaxS(''); setTmMaxD(''); setTmChan('sms,email,push'); setTmPrice(''); setTmDesc('')
      loadTiers(); showToast('Tier created')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleDeleteTier = async (id, name) => {
    if (!window.confirm(`Delete tier "${name}"? This cannot be undone.`)) return
    try {
      await del(`${BIL}/tiers/${id}`)
      loadTiers(); showToast('Tier deleted')
    } catch (e) { setError(e.message) }
  }

  const handleAssignTier = async (tierId) => {
    if (!selCo) { setError('Select a company first'); return }
    const tier = tiers.find(t => t.id === tierId)
    if (!window.confirm(`Assign "${tier?.name}" to this company? This will update their quotas.`)) return
    setError('')
    try {
      await post(`${BIL}/companies/${selCo}/subscribe`, { tier_id: tierId })
      loadSubData(); loadOverview(); showToast(`Tier "${tier?.name}" assigned`)
    } catch (e) { setError(e.message) }
  }

  const handleSetQuota = async (e) => {
    e.preventDefault(); setError('')
    if (!selCo) { setError('Select a company'); return }
    const body = {}
    if (qMaxS.trim()) body.max_subscribers  = parseInt(qMaxS)
    if (qMaxD.trim()) body.max_devices       = parseInt(qMaxD)
    if (qChan.trim()) body.allowed_channels  = qChan.trim()
    if (!Object.keys(body).length) { setError('Enter at least one quota field'); return }
    setLoading(true)
    try {
      await post(`${BIL}/companies/${selCo}/quota`, body)
      setQMaxS(''); setQMaxD(''); setQChan('')
      loadSubData(); showToast('Quota updated')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleSnapshot = async () => {
    if (!selCo) return
    try {
      await post(`${BIL}/companies/${selCo}/usage/snapshot`)
      loadSubData(); showToast('Snapshot captured')
    } catch (e) { setError(e.message) }
  }

  const CompanyPicker = ({ label = 'Company' }) => (
    <div className="sa-form-group" style={{ marginBottom: 16 }}>
      <label>{label}</label>
      <select className="sa-input" value={selCo} onChange={e => { setSelCo(e.target.value); setError('') }}>
        <option value="">— select company —</option>
        {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </div>
  )

  const SUB_TABS = [
    { id: 'overview',      label: 'Overview'        },
    { id: 'tiers',         label: 'Tiers'           },
    { id: 'subscription',  label: 'Subscription'    },
    { id: 'report',        label: 'Monthly Report'  },
    { id: 'usage',         label: 'Usage Dashboard' },
  ]

  return (
    <>
      {toast && <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46', padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>}

      <div style={{ display:'flex', gap:8, marginBottom:20, flexWrap:'wrap' }}>
        {SUB_TABS.map(s => (
          <button key={s.id} className={`sa-btn ${subTab === s.id ? 'primary' : 'secondary'}`}
            onClick={() => { setSubTab(s.id); setError('') }}>{s.label}</button>
        ))}
      </div>

      {error && <Err msg={error} />}

      {/* ── Overview ────────────────────────────────────────────── */}
      {subTab === 'overview' && (
        <div className="sa-card">
          <h2 className="sa-card-title">All Companies — Billing Overview</h2>
          <div className="sa-table-wrap">
            <table className="sa-table">
              <thead><tr>
                <th>Company</th><th>Tier</th><th>Subscribers</th>
                <th>Alerts (30d)</th><th>Open Alerts</th><th>Channels</th>
              </tr></thead>
              <tbody>
                {overview.length === 0
                  ? <tr><td colSpan={6} className="sa-empty"><Spinner /></td></tr>
                  : overview.map(r => (
                      <tr key={r.company_id}>
                        <td style={{ fontWeight: 600 }}>{r.company_name}</td>
                        <td><TierBadge name={r.tier_name} /></td>
                        <td>
                          <div style={{ minWidth: 140 }}>
                            <UsageBar used={r.subscribers} max={r.max_subscribers} label="" />
                          </div>
                        </td>
                        <td>{r.alerts_30d}</td>
                        <td style={{ color: r.open_alerts > 0 ? '#EF4444' : '#22C55E', fontWeight: 600 }}>{r.open_alerts}</td>
                        <td style={{ fontSize: 11, fontFamily: 'monospace' }}>{r.allowed_channels}</td>
                      </tr>
                    ))
                }
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Tiers ───────────────────────────────────────────────── */}
      {subTab === 'tiers' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Create Tier</h2>
            <form onSubmit={handleCreateTier}>
              <div className="sa-form-group">
                <label>Name</label>
                <input className="sa-input" value={tmName} onChange={e => setTmName(e.target.value)} placeholder="e.g. Starter" />
              </div>
              <div className="sa-cfg-row">
                <div className="sa-form-group">
                  <label>Max Subscribers</label>
                  <input className="sa-input" type="number" value={tmMaxS} onChange={e => setTmMaxS(e.target.value)} placeholder="100" />
                </div>
                <div className="sa-form-group">
                  <label>Max Devices</label>
                  <input className="sa-input" type="number" value={tmMaxD} onChange={e => setTmMaxD(e.target.value)} placeholder="10" />
                </div>
              </div>
              <div className="sa-form-group">
                <label>Allowed Channels</label>
                <input className="sa-input" value={tmChan} onChange={e => setTmChan(e.target.value)} placeholder="sms,email,push" />
              </div>
              <div className="sa-cfg-row">
                <div className="sa-form-group">
                  <label>Price / month ($)</label>
                  <input className="sa-input" value={tmPrice} onChange={e => setTmPrice(e.target.value)} placeholder="49" />
                </div>
                <div className="sa-form-group">
                  <label>Description</label>
                  <input className="sa-input" value={tmDesc} onChange={e => setTmDesc(e.target.value)} placeholder="Brief description" />
                </div>
              </div>
              <button className="sa-btn primary" type="submit" disabled={loading} style={{ marginTop: 4 }}>
                {loading ? 'Creating…' : '+ Create Tier'}
              </button>
            </form>
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">Subscription Tiers ({tiers.length})</h2>
            {tiers.map(t => (
              <div key={t.id} className="sa-bil-tier-card">
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:6 }}>
                  <div>
                    <TierBadge name={t.name} />
                    {t.price_monthly && t.price_monthly !== '0' && (
                      <span style={{ marginLeft:8, fontSize:13, fontWeight:700, color:'#1E1B4B' }}>${t.price_monthly}/mo</span>
                    )}
                  </div>
                  <button className="sa-btn sm danger" onClick={() => handleDeleteTier(t.id, t.name)}>Delete</button>
                </div>
                {t.description && <p style={{ fontSize:12, color:'#6B7280', margin:'0 0 8px' }}>{t.description}</p>}
                <div style={{ display:'flex', gap:16, fontSize:12, color:'#374151' }}>
                  <span>👤 {t.max_subscribers} subscribers</span>
                  <span>📡 {t.max_devices} devices</span>
                  <span style={{ fontFamily:'monospace' }}>{t.allowed_channels}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Subscription & Quota ─────────────────────────────────── */}
      {subTab === 'subscription' && (
        <div className="sa-cfg-grid">
          <div className="sa-card">
            <h2 className="sa-card-title">Assign Tier</h2>
            <CompanyPicker />
            {selCo && (
              <>
                <p style={{ fontSize:13, color:'#6B7280', marginBottom:12 }}>Click a tier to assign it to this company. This immediately updates the company's subscriber, device, and channel limits.</p>
                <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                  {tiers.map(t => (
                    <button key={t.id} className="sa-btn secondary"
                      style={{ textAlign:'left', display:'flex', justifyContent:'space-between', alignItems:'center' }}
                      onClick={() => handleAssignTier(t.id)}>
                      <span><TierBadge name={t.name} /> <span style={{ marginLeft:8, fontSize:12, color:'#6B7280' }}>{t.max_subscribers} subs · {t.allowed_channels}</span></span>
                      {t.price_monthly !== '0' && <span style={{ fontSize:13, fontWeight:700 }}>${t.price_monthly}/mo</span>}
                    </button>
                  ))}
                </div>

                <hr style={{ border:'none', borderTop:'1px solid #E5E7EB', margin:'16px 0' }} />
                <h3 style={{ fontSize:14, fontWeight:700, color:'#374151', marginBottom:12 }}>Manual Quota Override</h3>
                <form onSubmit={handleSetQuota}>
                  <div className="sa-cfg-row">
                    <div className="sa-form-group">
                      <label>Max Subscribers</label>
                      <input className="sa-input" type="number" value={qMaxS} onChange={e => setQMaxS(e.target.value)} placeholder="leave blank to keep" />
                    </div>
                    <div className="sa-form-group">
                      <label>Max Devices</label>
                      <input className="sa-input" type="number" value={qMaxD} onChange={e => setQMaxD(e.target.value)} placeholder="leave blank to keep" />
                    </div>
                  </div>
                  <div className="sa-form-group">
                    <label>Allowed Channels</label>
                    <input className="sa-input" value={qChan} onChange={e => setQChan(e.target.value)} placeholder="sms,email,push" />
                  </div>
                  <button className="sa-btn primary" type="submit" disabled={loading}>Apply Override</button>
                </form>
              </>
            )}
          </div>

          <div className="sa-card">
            <h2 className="sa-card-title">
              {selCo && subData ? `${subData.sub?.company_name} — Current Status` : 'Select a company'}
            </h2>
            {!selCo
              ? <p style={{ color:'#6B7280', fontSize:13 }}>Pick a company on the left.</p>
              : loading
                ? <Spinner />
                : subData && <>
                    <div style={{ marginBottom:16 }}>
                      <span style={{ fontSize:13, color:'#6B7280', marginRight:8 }}>Current tier:</span>
                      <TierBadge name={subData.sub?.current_tier?.tier_name ?? 'None'} />
                    </div>
                    <UsageBar
                      used={subData.sub?.usage?.subscribers ?? 0}
                      max={subData.sub?.quota?.max_subscribers ?? 100}
                      label="Subscribers" />
                    <div style={{ fontSize:12, color:'#6B7280', marginBottom:16 }}>
                      Devices limit: {subData.sub?.quota?.max_devices} ·
                      Channels: {subData.sub?.quota?.allowed_channels}
                    </div>
                    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
                      <span style={{ fontSize:14, fontWeight:700, color:'#374151' }}>Usage History</span>
                      <button className="sa-btn sm secondary" onClick={handleSnapshot}>Capture now</button>
                    </div>
                    {subData.usage.length === 0
                      ? <p style={{ color:'#6B7280', fontSize:12 }}>No snapshots yet.</p>
                      : <div className="sa-table-wrap">
                          <table className="sa-table">
                            <thead><tr><th>Month</th><th>Subscribers</th><th>Admins</th><th>Total Alerts</th></tr></thead>
                            <tbody>
                              {subData.usage.map(u => (
                                <tr key={u.month}>
                                  <td style={{ fontWeight:600 }}>{u.month}</td>
                                  <td>{u.subscriber_count}</td>
                                  <td>{u.admin_count}</td>
                                  <td>{u.alert_count}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                    }
                  </>
            }
          </div>
        </div>
      )}

      {/* ── Monthly Report ──────────────────────────────────────── */}
      {subTab === 'report' && (
        <div className="sa-cfg-grid">
          <div className="sa-card" style={{ gridColumn: '1 / -1' }}>
            <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
              <h2 className="sa-card-title" style={{ margin:0 }}>Monthly Report</h2>
              <div style={{ width:260 }}>
                <CompanyPicker label="" />
              </div>
            </div>

            {!selCo
              ? <p style={{ color:'#6B7280', fontSize:13 }}>Select a company to generate a report.</p>
              : loading
                ? <div style={{ textAlign:'center', padding:40 }}><Spinner /></div>
                : report && (
                    <>
                      <div className="sa-anl-kpi-strip" style={{ gridTemplateColumns:'repeat(5,1fr)', marginBottom:20 }}>
                        {[
                          { label:'Tier',         val: report.current_tier?.tier_name ?? 'None', color:'#6366F1' },
                          { label:'Subscribers',  val: report.live_usage?.subscribers ?? 0,       color:'#3B82F6' },
                          { label:'Sub Usage',    val: `${report.subscriber_usage_pct}%`,          color: report.subscriber_usage_pct >= 90 ? '#EF4444' : '#22C55E' },
                          { label:'Open Alerts',  val: report.live_usage?.open_alerts ?? 0,        color: (report.live_usage?.open_alerts ?? 0) > 0 ? '#EF4444' : '#22C55E' },
                          { label:'30d Alerts',   val: report.live_usage?.alerts_30d ?? 0,          color:'#F59E0B' },
                        ].map(k => (
                          <div key={k.label} className="sa-anl-kpi">
                            <span className="sa-anl-kpi-val" style={{ color:k.color, fontSize:22 }}>{k.val}</span>
                            <span className="sa-anl-kpi-label">{k.label}</span>
                          </div>
                        ))}
                      </div>

                      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20 }}>
                        <div>
                          <h3 style={{ fontSize:14, fontWeight:700, color:'#374151', marginBottom:10 }}>Alerts by Severity</h3>
                          {report.alerts_by_severity.length === 0
                            ? <p style={{ color:'#6B7280', fontSize:13 }}>No alerts.</p>
                            : report.alerts_by_severity.map(r => (
                                <div key={r.severity} style={{ display:'flex', justifyContent:'space-between', padding:'6px 0', borderBottom:'1px solid #F3F4F6', fontSize:13 }}>
                                  <span style={{ color: r.severity==='EMERGENCY'?'#7F1D1D': r.severity==='CRITICAL'?'#EF4444':'#F59E0B', fontWeight:700 }}>{r.severity}</span>
                                  <span>{r.cnt}</span>
                                </div>
                              ))
                          }
                        </div>
                        <div>
                          <h3 style={{ fontSize:14, fontWeight:700, color:'#374151', marginBottom:10 }}>Alerts by Month (12m)</h3>
                          {report.alerts_by_month.length === 0
                            ? <p style={{ color:'#6B7280', fontSize:13 }}>No data.</p>
                            : report.alerts_by_month.map(r => (
                                <div key={r.month} style={{ display:'flex', justifyContent:'space-between', padding:'6px 0', borderBottom:'1px solid #F3F4F6', fontSize:13 }}>
                                  <span style={{ fontFamily:'monospace' }}>{r.month}</span>
                                  <span style={{ fontWeight:600 }}>{r.cnt}</span>
                                </div>
                              ))
                          }
                        </div>
                      </div>

                      <p style={{ fontSize:11, color:'#9CA3AF', marginTop:16, textAlign:'right' }}>
                        Generated {new Date(report.generated_at).toLocaleString()}
                      </p>
                    </>
                  )
            }
          </div>
        </div>
      )}
      {/* ── Parameterized Monthly Usage (Task 3) ───────────────── */}
      {subTab === 'report' && selCo && (
        <div className="sa-card" style={{ marginTop: 16 }}>
          <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:16, flexWrap:'wrap' }}>
            <h2 className="sa-card-title" style={{ margin:0 }}>Usage for Specific Month</h2>
            <div style={{ display:'flex', gap:8, alignItems:'center' }}>
              <select value={reportMonth} onChange={e => setReportMonth(e.target.value)}
                style={{ padding:'4px 8px', borderRadius:6, border:'1px solid #D1D5DB', fontSize:13 }}>
                {['1','2','3','4','5','6','7','8','9','10','11','12'].map(m => (
                  <option key={m} value={m}>{new Date(2000, parseInt(m)-1).toLocaleString('default',{month:'long'})}</option>
                ))}
              </select>
              <select value={reportYear} onChange={e => setReportYear(e.target.value)}
                style={{ padding:'4px 8px', borderRadius:6, border:'1px solid #D1D5DB', fontSize:13 }}>
                {[...Array(5)].map((_,i) => {
                  const yr = new Date().getFullYear() - i
                  return <option key={yr} value={String(yr)}>{yr}</option>
                })}
              </select>
              <button className="sa-btn primary" onClick={loadMonthlyReport} disabled={reportLoading}>
                {reportLoading ? 'Loading…' : 'Generate'}
              </button>
            </div>
          </div>

          {monthlyReport && (
            <div>
              <div className="sa-anl-kpi-strip" style={{ gridTemplateColumns:'repeat(4,1fr)', marginBottom:16 }}>
                {[
                  { label:'Total Alerts',        val: monthlyReport.alerts?.total ?? 0,          color:'#6366F1' },
                  { label:'Critical',             val: monthlyReport.alerts?.critical ?? 0,        color:'#EF4444' },
                  { label:'Acknowledged',         val: monthlyReport.alerts?.acknowledged ?? 0,    color:'#22C55E' },
                  { label:'Notifications Sent',   val: monthlyReport.notifications_sent ?? 0,      color:'#F59E0B' },
                ].map(k => (
                  <div key={k.label} className="sa-anl-kpi">
                    <span className="sa-anl-kpi-val" style={{ color:k.color, fontSize:22 }}>{k.val}</span>
                    <span className="sa-anl-kpi-label">{k.label}</span>
                  </div>
                ))}
              </div>

              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, fontSize:13 }}>
                <div>
                  <h3 style={{ fontWeight:700, color:'#374151', marginBottom:8 }}>Quota Usage</h3>
                  {[
                    { label:'SMS',   used: monthlyReport.quota?.sms_used,   limit: monthlyReport.quota?.sms_limit   },
                    { label:'Email', used: monthlyReport.quota?.email_used, limit: monthlyReport.quota?.email_limit },
                  ].map(q => {
                    const pct = q.limit > 0 ? Math.round(q.used / q.limit * 100) : 0
                    const bar = pct >= 95 ? '#EF4444' : pct >= 80 ? '#F59E0B' : '#22C55E'
                    return (
                      <div key={q.label} style={{ marginBottom:10 }}>
                        <div style={{ display:'flex', justifyContent:'space-between', marginBottom:3 }}>
                          <span>{q.label}</span>
                          <span style={{ color: bar, fontWeight:600 }}>{q.used}/{q.limit} ({pct}%)</span>
                        </div>
                        <div style={{ background:'#F3F4F6', borderRadius:4, height:6 }}>
                          <div style={{ width:`${Math.min(pct,100)}%`, background: bar, borderRadius:4, height:6 }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
                <div>
                  <h3 style={{ fontWeight:700, color:'#374151', marginBottom:8 }}>Company Info</h3>
                  <div style={{ color:'#6B7280', lineHeight:'2em' }}>
                    <div><b>Tier:</b> {monthlyReport.tier}</div>
                    <div><b>Active Subscribers:</b> {monthlyReport.subscribers?.active}</div>
                    <div><b>Period:</b> {new Date(monthlyReport.period?.start).toLocaleDateString()} – {new Date(monthlyReport.period?.end).toLocaleDateString()}</div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Usage Dashboard ─────────────────────────────────────── */}
      {subTab === 'usage' && (
        <div className="sa-card">
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
            <h2 className="sa-card-title" style={{ margin:0 }}>Monthly Quota Usage</h2>
            <button className="sa-btn secondary" onClick={loadUsage}>↻ Refresh</button>
          </div>
          {usageData.length === 0
            ? <p style={{ color:'#6B7280', fontSize:13 }}><Spinner /></p>
            : (
              <div className="sa-table-wrap">
                <table className="sa-table">
                  <thead><tr>
                    <th>Company</th><th>Tier</th>
                    <th>Subscribers</th><th>SMS</th><th>Email</th>
                    <th></th>
                  </tr></thead>
                  <tbody>
                    {usageData.map(r => {
                      const uColor = (pct) =>
                        pct >= 95 ? '#EF4444' : pct >= 80 ? '#F59E0B' : '#22C55E'
                      return (
                        <tr key={r.company_id}>
                          <td style={{ fontWeight:600 }}>{r.company_name}</td>
                          <td><TierBadge name={r.tier_name} /></td>
                          <td style={{ color: uColor(r.subscribers?.percent ?? 0), fontWeight:600 }}>
                            {r.subscribers?.used ?? '—'} / {r.subscribers?.limit ?? '—'}
                            {r.subscribers?.limit > 0 && <span style={{ color:'#9CA3AF', fontWeight:400 }}> ({r.subscribers.percent}%)</span>}
                          </td>
                          <td style={{ color: uColor(r.sms?.percent ?? 0), fontWeight:600 }}>
                            {r.sms?.used ?? '—'} / {r.sms?.limit ?? '—'}
                            {r.sms?.limit > 0 && <span style={{ color:'#9CA3AF', fontWeight:400 }}> ({r.sms.percent}%)</span>}
                          </td>
                          <td style={{ color: uColor(r.email?.percent ?? 0), fontWeight:600 }}>
                            {r.email?.used ?? '—'} / {r.email?.limit ?? '—'}
                            {r.email?.limit > 0 && <span style={{ color:'#9CA3AF', fontWeight:400 }}> ({r.email.percent}%)</span>}
                          </td>
                          <td>
                            <button className="sa-btn secondary" style={{ fontSize:11, padding:'3px 10px' }}
                              onClick={() => { setGrantModal({ company_id: r.company_id, company_name: r.company_name }); setGrantChannel('sms'); setGrantAmount('') }}>
                              Grant Quota
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )
          }
        </div>
      )}

      {/* ── Grant Quota modal ──────────────────────────────────── */}
      {grantModal && (
        <Modal title={`Grant Quota — ${grantModal.company_name}`} onClose={() => setGrantModal(null)}
          footer={
            <button className="sa-btn primary" onClick={async () => {
              if (!grantAmount || isNaN(parseInt(grantAmount))) { setError('Enter a valid amount'); return }
              try {
                await post(`${BIL}/companies/${grantModal.company_id}/grant-quota`,
                  { channel: grantChannel, extra_amount: parseInt(grantAmount) })
                setGrantModal(null)
                loadUsage()
                showToast(`Granted ${grantAmount} ${grantChannel} quota`)
              } catch (e) { setError(e.message) }
            }}>Confirm Grant</button>
          }
        >
          <div className="sa-form-group">
            <label>Channel</label>
            <select className="sa-input" value={grantChannel} onChange={e => setGrantChannel(e.target.value)}>
              <option value="sms">SMS</option>
              <option value="email">Email</option>
              <option value="push">Push</option>
            </select>
          </div>
          <div className="sa-form-group">
            <label>Amount to grant (decrements current usage by this number)</label>
            <input className="sa-input" type="number" min="1" value={grantAmount}
              onChange={e => setGrantAmount(e.target.value)} placeholder="e.g. 50" />
          </div>
        </Modal>
      )}
    </>
  )
}

// ─── Phase 7: Security Tab ───────────────────────────────────────────────────

const SEC = '/api/super-admin/security'

const SEC_SUBTABS = ['Login Attempts', 'Blocked IPs', 'IP Whitelist', 'Audit Log', 'Retention', 'Incidents', '2FA Mgmt']

function SecurityTab() {
  const [sub, setSub]   = useState('Login Attempts')
  const [data, setData] = useState([])
  const [busy, setBusy] = useState(false)
  const [err,  setErr]  = useState('')
  const [form, setForm] = useState({})
  const [msg,  setMsg]  = useState('')

  const load = useCallback((subTab) => {
    setBusy(true); setErr(''); setData([])
    const map = {
      'Login Attempts': `${SEC}/login-attempts?days=7`,
      'Blocked IPs':    `${SEC}/login-attempts/blocked`,
      'IP Whitelist':   `${SEC}/ip-whitelist`,
      'Audit Log':      `${SEC}/audit?limit=200`,
      'Retention':      `${SEC}/retention`,
      'Incidents':      `${SEC}/incidents`,
      '2FA Mgmt':       `${SA}/2fa/status-all`,
    }
    get(map[subTab])
      .then(d => setData(Array.isArray(d) ? d : []))
      .catch(e => setErr(e.message))
      .finally(() => setBusy(false))
  }, [])

  useEffect(() => { load(sub) }, [sub, load])

  const handleAddWhitelist = () => {
    if (!form.ip) return
    post(`${SEC}/ip-whitelist`, { ip: form.ip, note: form.note || undefined })
      .then(() => { setMsg('IP added'); setForm({}); load(sub) })
      .catch(e => setErr(e.message))
  }

  const handleDelWhitelist = (id) => {
    del(`${SEC}/ip-whitelist/${id}`)
      .then(() => { setMsg('IP removed'); load(sub) })
      .catch(e => setErr(e.message))
  }

  const handleUpsertRetention = () => {
    if (!form.entity || !form.max_days) return
    post(`${SEC}/retention`, { entity: form.entity, max_days: parseInt(form.max_days), enabled: 1 })
      .then(() => { setMsg('Policy saved'); setForm({}); load(sub) })
      .catch(e => setErr(e.message))
  }

  const handleCreateIncident = () => {
    if (!form.title) return
    post(`${SEC}/incidents`, { title: form.title, description: form.description, severity: form.severity || 'medium' })
      .then(() => { setMsg('Incident created'); setForm({}); load(sub) })
      .catch(e => setErr(e.message))
  }

  const handleResolveIncident = (id) => {
    put(`${SEC}/incidents/${id}`, { status: 'resolved' })
      .then(() => { setMsg('Marked resolved'); load(sub) })
      .catch(e => setErr(e.message))
  }

  const handleEnforce2FA = (adminId, currentEnforced) => {
    post('/api/auth/admin/2fa/enforce', { admin_id: adminId, enforced: !currentEnforced })
      .then(() => { setMsg(currentEnforced ? '2FA enforcement removed' : '2FA enforced'); load('2FA Mgmt') })
      .catch(e => setErr(e.message))
  }

  const handleDisable2FA = (adminId) => {
    if (!window.confirm(`Disable 2FA for admin #${adminId}?`)) return
    post('/api/auth/admin/2fa/disable', { admin_id: adminId, enforced: false })
      .then(() => { setMsg('2FA disabled'); load('2FA Mgmt') })
      .catch(e => setErr(e.message))
  }

  const handleExportAudit = () => {
    const url = `${SEC}/audit/export?days=30`
    const a = document.createElement('a')
    a.href = url
    a.click()
  }

  const subStyle = (s) => ({
    padding: '4px 12px', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 500, border: 'none',
    background: sub === s ? '#6366F1' : 'transparent',
    color: sub === s ? '#fff' : 'var(--sa-text-muted)',
  })

  const rowStyle = { display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12, padding: '6px 0', borderBottom: '1px solid var(--sa-border)' }
  const inpStyle = { padding: '5px 8px', borderRadius: 6, border: '1px solid var(--sa-border)', background: 'var(--sa-surface)', color: 'inherit', fontSize: 12 }

  return (
    <div>
      {/* Sub-tab bar */}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 16, padding: '8px', background: 'var(--sa-surface)', borderRadius: 8 }}>
        {SEC_SUBTABS.map(s => (
          <button key={s} style={subStyle(s)} onClick={() => { setSub(s); setMsg(''); setErr(''); setForm({}) }}>{s}</button>
        ))}
      </div>

      {msg && <p style={{ color: '#22C55E', fontSize: 12, marginBottom: 8 }}>{msg}</p>}
      {err && <Err msg={err} />}

      {/* ── Login Attempts ── */}
      {sub === 'Login Attempts' && (
        <div>
          <div style={rowStyle}>
            <span className="sa-cfg-stat-val">{data.length} attempts (last 7 days)</span>
          </div>
          {busy ? <Spinner /> : (
            <table className="sa-table">
              <thead><tr><th>IP</th><th>Username</th><th>Result</th><th>Time</th></tr></thead>
              <tbody>
                {data.map(r => (
                  <tr key={r.id}>
                    <td><code style={{ fontSize: 11 }}>{r.ip}</code></td>
                    <td>{r.username}</td>
                    <td><Badge label={r.success ? 'Success' : 'Fail'} type={r.success ? 'active' : 'WARNING'} /></td>
                    <td style={{ fontSize: 11, color: 'var(--sa-text-muted)' }}>{r.attempted_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Blocked IPs ── */}
      {sub === 'Blocked IPs' && (
        <div>
          <p style={{ fontSize: 12, color: 'var(--sa-text-muted)', marginBottom: 8 }}>IPs with ≥5 failed attempts in the last 15 minutes.</p>
          {busy ? <Spinner /> : data.length === 0 ? <p style={{ color: '#22C55E', fontSize: 13 }}>No blocked IPs detected.</p> : (
            <table className="sa-table">
              <thead><tr><th>IP</th><th>Failures</th><th>Last Attempt</th></tr></thead>
              <tbody>
                {data.map((r, i) => (
                  <tr key={i}>
                    <td><code style={{ fontSize: 11 }}>{r.ip}</code></td>
                    <td><Badge label={r.failures} type="CRITICAL" /></td>
                    <td style={{ fontSize: 11 }}>{r.last_attempt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── IP Whitelist ── */}
      {sub === 'IP Whitelist' && (
        <div>
          <div className="sa-cfg-row" style={{ marginBottom: 12 }}>
            <input style={inpStyle} placeholder="IP address (e.g. 192.168.1.1)" value={form.ip || ''} onChange={e => setForm(f => ({ ...f, ip: e.target.value }))} />
            <input style={inpStyle} placeholder="Note (optional)" value={form.note || ''} onChange={e => setForm(f => ({ ...f, note: e.target.value }))} />
            <button className="sa-btn primary" onClick={handleAddWhitelist}>Add IP</button>
          </div>
          <p style={{ fontSize: 11, color: 'var(--sa-text-muted)', marginBottom: 12 }}>When the whitelist is non-empty, only listed IPs can access the super-admin panel.</p>
          {busy ? <Spinner /> : (
            <table className="sa-table">
              <thead><tr><th>IP</th><th>Note</th><th>Added By</th><th>Added At</th><th></th></tr></thead>
              <tbody>
                {data.map(r => (
                  <tr key={r.id}>
                    <td><code style={{ fontSize: 11 }}>{r.ip}</code></td>
                    <td style={{ fontSize: 12 }}>{r.note || '—'}</td>
                    <td style={{ fontSize: 12 }}>{r.added_by_name || '—'}</td>
                    <td style={{ fontSize: 11, color: 'var(--sa-text-muted)' }}>{r.added_at}</td>
                    <td><button className="sa-btn danger" onClick={() => handleDelWhitelist(r.id)}>Remove</button></td>
                  </tr>
                ))}
                {data.length === 0 && <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--sa-text-muted)', fontSize: 12 }}>No IPs whitelisted — all IPs are allowed.</td></tr>}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Audit Log ── */}
      {sub === 'Audit Log' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <span style={{ fontSize: 12, color: 'var(--sa-text-muted)' }}>Last 200 actions</span>
            <button className="sa-btn" onClick={handleExportAudit} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Download size={13} /> Export CSV (30d)
            </button>
          </div>
          {busy ? <Spinner /> : (
            <table className="sa-table">
              <thead><tr><th>Time</th><th>Admin</th><th>Action</th><th>Entity</th><th>Details</th></tr></thead>
              <tbody>
                {data.map(r => (
                  <tr key={r.id}>
                    <td style={{ fontSize: 11, color: 'var(--sa-text-muted)', whiteSpace: 'nowrap' }}>{r.created_at}</td>
                    <td style={{ fontSize: 12 }}>{r.admin_name || '—'}</td>
                    <td><code style={{ fontSize: 11 }}>{r.action}</code></td>
                    <td style={{ fontSize: 12 }}>{r.entity}</td>
                    <td style={{ fontSize: 11, color: 'var(--sa-text-muted)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.details}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Retention Policies ── */}
      {sub === 'Retention' && (
        <div>
          <div className="sa-cfg-row" style={{ marginBottom: 12 }}>
            <input style={inpStyle} placeholder="Entity (e.g. readings)" value={form.entity || ''} onChange={e => setForm(f => ({ ...f, entity: e.target.value }))} />
            <input style={inpStyle} placeholder="Max days" type="number" min="1" value={form.max_days || ''} onChange={e => setForm(f => ({ ...f, max_days: e.target.value }))} />
            <button className="sa-btn primary" onClick={handleUpsertRetention}>Save Policy</button>
          </div>
          {busy ? <Spinner /> : (
            <table className="sa-table">
              <thead><tr><th>Entity</th><th>Max Days</th><th>Enabled</th><th>Updated</th></tr></thead>
              <tbody>
                {data.map(r => (
                  <tr key={r.id}>
                    <td><code style={{ fontSize: 11 }}>{r.entity}</code></td>
                    <td>{r.max_days}d</td>
                    <td><Badge label={r.enabled ? 'Yes' : 'No'} type={r.enabled ? 'active' : 'inactive'} /></td>
                    <td style={{ fontSize: 11, color: 'var(--sa-text-muted)' }}>{r.updated_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Incidents ── */}
      {sub === 'Incidents' && (
        <div>
          <div className="sa-cfg-row" style={{ marginBottom: 12 }}>
            <input style={inpStyle} placeholder="Title" value={form.title || ''} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} />
            <input style={inpStyle} placeholder="Description" value={form.description || ''} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
            <select style={inpStyle} value={form.severity || 'medium'} onChange={e => setForm(f => ({ ...f, severity: e.target.value }))}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
            <button className="sa-btn primary" onClick={handleCreateIncident}>Create</button>
          </div>
          {busy ? <Spinner /> : (
            <table className="sa-table">
              <thead><tr><th>Title</th><th>Severity</th><th>Status</th><th>Company</th><th>Created</th><th></th></tr></thead>
              <tbody>
                {data.map(r => (
                  <tr key={r.id}>
                    <td style={{ fontSize: 12 }}>{r.title}</td>
                    <td><Badge label={r.severity} type={r.severity === 'critical' ? 'CRITICAL' : r.severity === 'high' ? 'WARNING' : 'sub'} /></td>
                    <td><Badge label={r.status} type={r.status === 'open' ? 'WARNING' : r.status === 'resolved' ? 'active' : 'sub'} /></td>
                    <td style={{ fontSize: 12 }}>{r.company_name || '—'}</td>
                    <td style={{ fontSize: 11, color: 'var(--sa-text-muted)' }}>{r.created_at}</td>
                    <td>
                      {r.status === 'open' || r.status === 'investigating'
                        ? <button className="sa-btn" onClick={() => handleResolveIncident(r.id)}>Resolve</button>
                        : <span style={{ fontSize: 11, color: '#22C55E' }}>Resolved</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── 2FA Management ── */}
      {sub === '2FA Mgmt' && (
        <div>
          <p style={{ fontSize: 12, color: 'var(--sa-text-muted)', marginBottom: 12 }}>
            Enforce 2FA on any admin — they must scan their QR code on next login.
            Super admin can set up their own 2FA via the QR Setup panel in their profile.
          </p>
          {busy ? <Spinner /> : (
            <table className="sa-table">
              <thead>
                <tr><th>ID</th><th>Admin</th><th>Role</th><th>Company</th><th>2FA Active</th><th>Enforced</th><th></th></tr>
              </thead>
              <tbody>
                {data.map(r => (
                  <tr key={r.id}>
                    <td style={{ fontSize: 11 }}>{r.id}</td>
                    <td style={{ fontSize: 12, fontWeight: 600 }}>{r.name}</td>
                    <td><Badge label={r.role} type={r.role === 'super_admin' ? 'CRITICAL' : 'sub'} /></td>
                    <td style={{ fontSize: 12 }}>{r.company_name || '—'}</td>
                    <td>
                      <Badge
                        label={r.totp_enabled ? 'Active' : 'Off'}
                        type={r.totp_enabled ? 'active' : 'inactive'}
                      />
                    </td>
                    <td>
                      <Badge
                        label={r.totp_enforced ? 'Enforced' : 'Optional'}
                        type={r.totp_enforced ? 'WARNING' : 'inactive'}
                      />
                    </td>
                    <td style={{ display: 'flex', gap: 4 }}>
                      <button
                        className="sa-btn secondary"
                        style={{ fontSize: 11, padding: '3px 8px' }}
                        onClick={() => handleEnforce2FA(r.id, r.totp_enforced)}
                      >
                        {r.totp_enforced ? 'Un-enforce' : 'Enforce'}
                      </button>
                      {r.totp_enabled && (
                        <button
                          className="sa-btn danger"
                          style={{ fontSize: 11, padding: '3px 8px' }}
                          onClick={() => handleDisable2FA(r.id)}
                        >
                          Disable
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Onboarding Wizard Tab ────────────────────────────────────────────────────

const OB = '/api/super-admin/onboarding'

const STEP_COLORS = {
  done:    { bg: '#D1FAE5', border: '#6EE7B7', icon: '✓', text: '#065F46' },
  pending: { bg: '#F3F4F6', border: '#D1D5DB', icon: '○', text: '#6B7280' },
  skipped: { bg: '#FEF3C7', border: '#FCD34D', icon: '⤼', text: '#92400E' },
}

function OnboardingTab() {
  const [companies,   setCompanies]   = useState([])
  const [selCo,       setSelCo]       = useState('')
  const [progress,    setProgress]    = useState(null)
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState('')
  const [toast,       setToast]       = useState('')
  const [simLoading,  setSimLoading]  = useState(false)

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3500) }

  useEffect(() => {
    get(`${SA}/companies`).then(setCompanies).catch(() => {})
  }, [])

  const loadProgress = useCallback(() => {
    if (!selCo) return
    setLoading(true)
    setError('')
    get(`${OB}/${selCo}`)
      .then(setProgress)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [selCo])

  useEffect(() => { loadProgress() }, [loadProgress])

  const handleInit = async () => {
    setLoading(true)
    try {
      await post(`${OB}/${selCo}/init`, {})
      showToast('Onboarding initialised')
      loadProgress()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleStepToggle = async (stepIndex, currentStatus) => {
    const newStatus = currentStatus === 'done' ? 'pending' : 'done'
    try {
      await patch(`${OB}/${selCo}/step/${stepIndex}?status=${newStatus}`, {})
      loadProgress()
    } catch (e) { setError(e.message) }
  }

  const handleTestBreach = async () => {
    setSimLoading(true)
    try {
      await post('/api/simulate/breach', {})
      showToast('Breach simulation triggered — check alerts')
      await patch(`${OB}/${selCo}/step/3?status=done`, {})
      loadProgress()
    } catch (e) { setError('Simulation failed: ' + e.message) }
    finally { setSimLoading(false) }
  }

  const pct = progress ? Math.round(progress.done_steps / progress.total_steps * 100) : 0
  const barColor = pct === 100 ? '#22C55E' : pct >= 60 ? '#3B82F6' : '#F59E0B'

  return (
    <div style={{ maxWidth: 800 }}>
      {toast && (
        <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46',
          padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>
      )}

      <div className="sa-card" style={{ marginBottom: 20 }}>
        <h2 className="sa-card-title">Onboarding Wizard</h2>
        <p style={{ color:'#6B7280', fontSize:13, marginBottom:16 }}>
          Track setup progress for each company through the 5-step onboarding checklist.
        </p>
        <div style={{ display:'flex', gap:10, alignItems:'center', flexWrap:'wrap' }}>
          <select value={selCo} onChange={e => { setSelCo(e.target.value); setProgress(null) }}
            className="sa-input" style={{ width:260 }}>
            <option value="">— Select company —</option>
            {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          {selCo && !progress && (
            <button className="sa-btn primary" onClick={handleInit} disabled={loading}>
              {loading ? 'Initialising…' : 'Initialise Onboarding'}
            </button>
          )}
          {selCo && progress && (
            <button className="sa-btn secondary" onClick={loadProgress}>↻ Refresh</button>
          )}
        </div>
        {error && <p style={{ color:'#EF4444', fontSize:13, marginTop:8 }}>{error}</p>}
      </div>

      {progress && (
        <div className="sa-card">
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
            <div>
              <h3 style={{ fontWeight:700, color:'#111827', margin:0 }}>{progress.company_name}</h3>
              <p style={{ color:'#6B7280', fontSize:13, margin:'4px 0 0' }}>
                {progress.done_steps} of {progress.total_steps} steps complete
                {progress.complete && ' — '}
                {progress.complete && <span style={{ color:'#22C55E', fontWeight:700 }}>LIVE</span>}
              </p>
            </div>
            <div style={{ textAlign:'right' }}>
              <span style={{ fontSize:24, fontWeight:800, color: barColor }}>{pct}%</span>
            </div>
          </div>

          {/* Progress bar */}
          <div style={{ background:'#F3F4F6', borderRadius:6, height:10, marginBottom:24 }}>
            <div style={{ width:`${pct}%`, background: barColor, borderRadius:6, height:10,
              transition:'width 0.4s ease' }} />
          </div>

          {/* Steps */}
          <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
            {progress.steps.map(step => {
              const sc = STEP_COLORS[step.step_status] || STEP_COLORS.pending
              const isStep3 = step.step_index === 3
              return (
                <div key={step.step_index} style={{
                  display:'flex', alignItems:'flex-start', gap:14, padding:14,
                  background: sc.bg, borderRadius:10, border:`1.5px solid ${sc.border}`,
                }}>
                  <div style={{ fontSize:20, color: sc.text, minWidth:24, textAlign:'center',
                    fontWeight:700, marginTop:2 }}>{sc.icon}</div>
                  <div style={{ flex:1 }}>
                    <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                      <span style={{ fontWeight:700, color:'#111827', fontSize:14 }}>
                        Step {step.step_index + 1}: {step.step_title}
                      </span>
                      <div style={{ display:'flex', gap:8 }}>
                        {isStep3 && step.step_status !== 'done' && (
                          <button className="sa-btn primary" style={{ fontSize:12, padding:'4px 10px' }}
                            onClick={handleTestBreach} disabled={simLoading}>
                            {simLoading ? 'Sending…' : '⚡ Trigger Test Breach'}
                          </button>
                        )}
                        <button
                          className={`sa-btn ${step.step_status === 'done' ? 'secondary' : 'primary'}`}
                          style={{ fontSize:12, padding:'4px 10px' }}
                          onClick={() => handleStepToggle(step.step_index, step.step_status)}>
                          {step.step_status === 'done' ? 'Mark Pending' : 'Mark Done'}
                        </button>
                      </div>
                    </div>
                    <p style={{ color:'#6B7280', fontSize:12, margin:'4px 0 0' }}>{step.description}</p>
                    {step.completed_at && (
                      <p style={{ color:'#6EE7B7', fontSize:11, margin:'4px 0 0' }}>
                        Completed {new Date(step.completed_at).toLocaleString()}
                      </p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Audit Log Tab ────────────────────────────────────────────────────────────

const AUDIT_SA = '/api/super-admin'

const SEV_COLORS = {
  info:     { bg: '#EFF6FF', text: '#1D4ED8', label: 'info' },
  warning:  { bg: '#FFFBEB', text: '#B45309', label: 'warn' },
  critical: { bg: '#FEF2F2', text: '#B91C1C', label: 'CRIT' },
}
const CAT_COLORS = {
  auth:     '#6366F1',
  config:   '#F59E0B',
  data:     '#3B82F6',
  security: '#EF4444',
  admin:    '#8B5CF6',
  general:  '#6B7280',
}

function AuditTab() {
  const [rows,       setRows]       = useState([])
  const [summary,    setSummary]    = useState(null)
  const [total,      setTotal]      = useState(0)
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState('')
  const [days,       setDays]       = useState('7')
  const [category,   setCategory]   = useState('')
  const [severity,   setSeverity]   = useState('')
  const [pageOffset, setPageOffset] = useState(0)
  const PAGE_SIZE = 50

  const loadSummary = useCallback(() => {
    get(`${AUDIT_SA}/audit-log/summary?days=${days}`)
      .then(setSummary)
      .catch(() => {})
  }, [days])

  const loadRows = useCallback(() => {
    setLoading(true)
    setError('')
    const params = new URLSearchParams({
      days, limit: PAGE_SIZE, offset: pageOffset,
      ...(category && { category }),
      ...(severity && { severity }),
    })
    get(`${AUDIT_SA}/audit-log?${params}`)
      .then(d => { setRows(d.rows || []); setTotal(d.total || 0) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [days, category, severity, pageOffset])

  useEffect(() => { loadSummary(); loadRows() }, [loadSummary, loadRows])

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const currentPage = Math.floor(pageOffset / PAGE_SIZE) + 1

  return (
    <div>
      {/* Summary strip */}
      {summary && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12, marginBottom:20 }}>
          <div className="sa-card" style={{ padding:14 }}>
            <h3 style={{ fontSize:12, fontWeight:700, color:'#6B7280', textTransform:'uppercase', marginBottom:10 }}>
              By Category ({days}d)
            </h3>
            {summary.by_category.length === 0
              ? <p style={{ color:'#9CA3AF', fontSize:12 }}>No data</p>
              : summary.by_category.map(r => (
                  <div key={r.category} style={{ display:'flex', justifyContent:'space-between',
                    fontSize:13, padding:'4px 0', borderBottom:'1px solid #F3F4F6' }}>
                    <span style={{ color: CAT_COLORS[r.category] || '#6B7280', fontWeight:600 }}>
                      {r.category}
                    </span>
                    <span style={{ fontWeight:700 }}>{r.cnt}</span>
                  </div>
                ))
            }
          </div>

          <div className="sa-card" style={{ padding:14 }}>
            <h3 style={{ fontSize:12, fontWeight:700, color:'#6B7280', textTransform:'uppercase', marginBottom:10 }}>
              By Severity ({days}d)
            </h3>
            {summary.by_severity.length === 0
              ? <p style={{ color:'#9CA3AF', fontSize:12 }}>No data</p>
              : summary.by_severity.map(r => {
                  const sc = SEV_COLORS[r.severity] || SEV_COLORS.info
                  return (
                    <div key={r.severity} style={{ display:'flex', justifyContent:'space-between',
                      fontSize:13, padding:'4px 0', borderBottom:'1px solid #F3F4F6' }}>
                      <span style={{ background: sc.bg, color: sc.text, padding:'1px 7px',
                        borderRadius:10, fontSize:11, fontWeight:700 }}>{r.severity}</span>
                      <span style={{ fontWeight:700 }}>{r.cnt}</span>
                    </div>
                  )
                })
            }
          </div>

          <div className="sa-card" style={{ padding:14 }}>
            <h3 style={{ fontSize:12, fontWeight:700, color:'#6B7280', textTransform:'uppercase', marginBottom:10 }}>
              Recent Critical
            </h3>
            {summary.critical_recent.length === 0
              ? <p style={{ color:'#9CA3AF', fontSize:12 }}>None — all clear</p>
              : summary.critical_recent.slice(0, 5).map((r, i) => (
                  <div key={i} style={{ fontSize:12, padding:'4px 0', borderBottom:'1px solid #F3F4F6',
                    color:'#B91C1C' }}>
                    <span style={{ fontWeight:700 }}>{r.action}</span>
                    {r.admin_name && <span style={{ color:'#6B7280' }}> ({r.admin_name})</span>}
                    {r.ip_address && <span style={{ color:'#9CA3AF' }}> {r.ip_address}</span>}
                  </div>
                ))
            }
          </div>
        </div>
      )}

      {/* Filters + table */}
      <div className="sa-card">
        <div style={{ display:'flex', gap:10, alignItems:'center', flexWrap:'wrap', marginBottom:16 }}>
          <h2 className="sa-card-title" style={{ margin:0, flex:1 }}>
            Audit Log {total > 0 && <span style={{ color:'#6B7280', fontWeight:400, fontSize:13 }}>({total} entries)</span>}
          </h2>
          <select value={days} onChange={e => { setDays(e.target.value); setPageOffset(0) }}
            style={{ padding:'4px 8px', borderRadius:6, border:'1px solid #D1D5DB', fontSize:13 }}>
            {[['1','24h'],['7','7d'],['14','14d'],['30','30d'],['90','90d']].map(([v,l]) =>
              <option key={v} value={v}>{l}</option>)}
          </select>
          <select value={category} onChange={e => { setCategory(e.target.value); setPageOffset(0) }}
            style={{ padding:'4px 8px', borderRadius:6, border:'1px solid #D1D5DB', fontSize:13 }}>
            <option value="">All categories</option>
            {['auth','config','data','security','admin','general'].map(c =>
              <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={severity} onChange={e => { setSeverity(e.target.value); setPageOffset(0) }}
            style={{ padding:'4px 8px', borderRadius:6, border:'1px solid #D1D5DB', fontSize:13 }}>
            <option value="">All severities</option>
            {['info','warning','critical'].map(s =>
              <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="sa-btn secondary" onClick={() => { loadSummary(); loadRows() }}>
            ↻ Refresh
          </button>
        </div>

        {error && <p style={{ color:'#EF4444', fontSize:13, marginBottom:8 }}>{error}</p>}

        {loading
          ? <div style={{ textAlign:'center', padding:40 }}><Spinner /></div>
          : (
            <div className="sa-table-wrap">
              <table className="sa-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Sev</th>
                    <th>Cat</th>
                    <th>Action</th>
                    <th>Admin</th>
                    <th>IP</th>
                    <th>Entity</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0
                    ? <tr><td colSpan={8} style={{ textAlign:'center', color:'#9CA3AF', padding:24 }}>
                        No entries for this filter
                      </td></tr>
                    : rows.map(r => {
                        const sc = SEV_COLORS[r.severity] || SEV_COLORS.info
                        const catColor = CAT_COLORS[r.category] || '#6B7280'
                        const ts = r.created_at
                          ? new Date(r.created_at).toLocaleString('en-IN', { hour12: false })
                          : '—'
                        return (
                          <tr key={r.id}>
                            <td style={{ fontFamily:'monospace', fontSize:11, whiteSpace:'nowrap' }}>{ts}</td>
                            <td>
                              <span style={{ background: sc.bg, color: sc.text, padding:'1px 6px',
                                borderRadius:8, fontSize:10, fontWeight:700 }}>{sc.label}</span>
                            </td>
                            <td>
                              <span style={{ color: catColor, fontWeight:600, fontSize:12 }}>{r.category}</span>
                            </td>
                            <td style={{ fontFamily:'monospace', fontSize:12 }}>{r.action}</td>
                            <td style={{ fontSize:12 }}>{r.admin_name || '—'}</td>
                            <td style={{ fontFamily:'monospace', fontSize:11, color:'#6B7280' }}>{r.ip_address || '—'}</td>
                            <td style={{ fontSize:12 }}>
                              {r.entity_type
                                ? `${r.entity_type}${r.entity_id ? ` #${r.entity_id}` : ''}`
                                : '—'}
                            </td>
                            <td style={{ fontSize:11, maxWidth:180, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                              {r.old_value || r.new_value
                                ? <span title={`${r.old_value || ''} → ${r.new_value || ''}`}>
                                    {r.old_value ? `${r.old_value} → ` : ''}{r.new_value || ''}
                                  </span>
                                : '—'}
                            </td>
                          </tr>
                        )
                      })
                  }
                </tbody>
              </table>
            </div>
          )
        }

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display:'flex', gap:8, justifyContent:'center', marginTop:16, alignItems:'center', fontSize:13 }}>
            <button className="sa-btn secondary" disabled={pageOffset === 0}
              onClick={() => setPageOffset(Math.max(0, pageOffset - PAGE_SIZE))}>← Prev</button>
            <span style={{ color:'#6B7280' }}>Page {currentPage} of {totalPages}</span>
            <button className="sa-btn secondary" disabled={currentPage >= totalPages}
              onClick={() => setPageOffset(pageOffset + PAGE_SIZE)}>Next →</button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Root ─────────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'command',    label: 'Command Center', Icon: Radio           },
  { id: 'overview',   label: 'Overview',       Icon: LayoutDashboard },
  { id: 'companies',  label: 'Companies',      Icon: Building2       },
  { id: 'admins',     label: 'Admins',         Icon: Users           },
  { id: 'approvals',  label: 'Approvals',      Icon: ClipboardList   },
  { id: 'config',     label: 'Config',         Icon: Wrench          },
  { id: 'analytics',  label: 'Analytics',      Icon: BarChart2       },
  { id: 'comms',      label: 'Communications', Icon: Megaphone       },
  { id: 'billing',    label: 'Billing',        Icon: CreditCard      },
  { id: 'security',   label: 'Security',       Icon: ShieldAlert     },
  { id: 'parameters', label: 'Parameters',     Icon: Layers          },
  { id: 'alerts',     label: 'Alerts',         Icon: AlertTriangle   },
  { id: 'live',       label: 'Live Feed',      Icon: Activity        },
  { id: 'broadcast',  label: 'Broadcast',      Icon: Megaphone       },
  { id: 'sessions',   label: 'Sessions',       Icon: KeyRound        },
  { id: 'onboarding', label: 'Onboarding',     Icon: BookOpen        },
  { id: 'audit',      label: 'Audit Log',      Icon: ScrollText      },
]

export default function SuperAdmin() {
  const navigate = useNavigate()
  const [tab,          setTab]          = useState('overview')
  const [adminDetail,  setAdminDetail]  = useState(null)
  const [viewAdmins,   setViewAdmins]   = useState(null)
  const [pendingCount,  setPendingCount]  = useState(0)
  const [anomalyCount,  setAnomalyCount]  = useState(0)

  const username = sessionStorage.getItem('admin_username') || 'superadmin'

  // Poll pending approval count every 30 s for the sidebar badge
  useEffect(() => {
    const fetchPending = () =>
      get(`${AC}/approvals/pending`)
        .then(d => setPendingCount(Array.isArray(d) ? d.length : 0))
        .catch(() => {})
    fetchPending()
    const t = setInterval(fetchPending, 30000)
    return () => clearInterval(t)
  }, [])

  // Poll unresolved anomaly count every 2 min for the sidebar badge
  useEffect(() => {
    const fetchAnomalies = () =>
      get(`${SA}/anomalies`)
        .then(d => setAnomalyCount(Array.isArray(d) ? d.length : 0))
        .catch(() => {})
    fetchAnomalies()
    const t = setInterval(fetchAnomalies, 120000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!sessionStorage.getItem('admin_token')) {
      navigate('/super-admin/login', { replace: true })
    }
  }, [navigate])

  const handleNavAdmins = (company) => {
    setViewAdmins(company)
    setTab('companies')
  }

  const switchTab = (id) => {
    setTab(id)
    setAdminDetail(null)
    setViewAdmins(null)
  }

  const handleLogout = () => {
    sessionStorage.removeItem('admin_token')
    sessionStorage.removeItem('adminPassword')
    sessionStorage.removeItem('admin_username')
    sessionStorage.removeItem('authenticated')
    navigate('/super-admin/login', { replace: true })
  }

  const renderContent = () => {
    if (adminDetail !== null) {
      return <AdminDetailView adminId={adminDetail} onBack={() => setAdminDetail(null)} />
    }
    switch (tab) {
      case 'command':   return <CommandCenterTab />
      case 'overview':  return <OverviewTab onNavigate={switchTab} />
      case 'companies': return <CompaniesTab onViewAdmins={handleNavAdmins} />
      case 'approvals': return <ApprovalsTab onCountChange={setPendingCount} />
      case 'config':     return <ConfigTab />
      case 'analytics':  return <AnalyticsTab />
      case 'comms':      return <CommsTab />
      case 'billing':    return <BillingTab />
      case 'security':   return <SecurityTab />
      case 'admins':     return <AdminsTab onViewDetail={(id) => setAdminDetail(id)} />
      case 'parameters': return <CompanyParametersTab />
      case 'alerts':    return <AlertsTab />
      case 'live':      return <LiveFeedTab />
      case 'broadcast': return <BroadcastTab />
      case 'sessions':  return <SessionsTab />
      case 'onboarding': return <OnboardingTab />
      case 'audit':      return <AuditTab />
      default:          return null
    }
  }

  const activeTab = adminDetail !== null ? null : tab

  return (
    <div className="sa-shell">

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside className="sa-sidebar">

        {/* Brand */}
        <div className="sa-sidebar-brand">
          <div className="sa-sidebar-logo">
            <ShieldCheck size={22} color="#A5B4FC" strokeWidth={2} />
            <span className="sa-sidebar-logo-name">SentinelEdge</span>
          </div>
          <div className="sa-sidebar-role">Super Admin Portal</div>
        </div>

        {/* Nav items */}
        <nav className="sa-sidebar-nav">
          {TABS.map(({ id, label, Icon }) => (
            <button
              key={id}
              className={`sa-sidebar-item ${activeTab === id ? 'active' : ''}`}
              onClick={() => switchTab(id)}
            >
              <Icon size={16} strokeWidth={2} style={{ flexShrink: 0 }} />
              {label}
              {id === 'approvals' && pendingCount > 0 && (
                <span className="sa-sidebar-badge">{pendingCount}</span>
              )}
              {id === 'analytics' && anomalyCount > 0 && (
                <span className="sa-sidebar-badge" style={{ background: '#EF4444' }}>{anomalyCount}</span>
              )}
            </button>
          ))}
        </nav>

        {/* Footer: user + logout */}
        <div className="sa-sidebar-footer">
          <div className="sa-sidebar-user">
            <div className="sa-sidebar-avatar">
              {username.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <div className="sa-sidebar-uname">{username}</div>
              <div className="sa-sidebar-urole">Super Admin</div>
            </div>
          </div>
          <button className="sa-sidebar-logout" onClick={handleLogout}>
            <LogOut size={13} strokeWidth={2} />
            Sign out
          </button>
        </div>
      </aside>

      {/* ── Main area ───────────────────────────────────────────────────── */}
      <div className="sa-main">

        {/* Top bar */}
        <div className="sa-topbar">
          <div className="sa-topbar-title">
            {adminDetail !== null
              ? 'Admin Detail'
              : TABS.find(t => t.id === tab)?.label ?? 'Dashboard'}
          </div>
        </div>

        {/* Content */}
        <div className="sa-body">
          {renderContent()}
        </div>
      </div>

    </div>
  )
}
