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
  ShieldAlert, Download,
} from 'lucide-react'
import './SuperAdmin.css'

// ─── API layer ────────────────────────────────────────────────────────────────

function adminHeaders() {
  const token    = sessionStorage.getItem('admin_token') || ''
  const password = sessionStorage.getItem('adminPassword') || ''
  return {
    'Content-Type': 'application/json',
    'X-Admin-Password': password,
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
  if (res.status === 401 || res.status === 403) {
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
                      <td><Badge label={c.is_active ? 'Active' : 'Inactive'} type={c.is_active ? 'active' : 'inactive'} /></td>
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
                  <td><Badge label={c.is_active ? 'Active' : 'Inactive'} type={c.is_active ? 'active' : 'inactive'} /></td>
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

  const SUB_TABS = [
    { id: 'thresholds', label: 'Global Thresholds' },
    { id: 'templates',  label: 'Templates'          },
    { id: 'company',    label: 'Company Config'     },
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

function AnalyticsTab() {
  const [subTab,    setSubTab]    = useState('summary')
  const [summary,   setSummary]   = useState(null)
  const [health,    setHealth]    = useState([])
  const [compare,   setCompare]   = useState([])
  const [anomalies, setAnomalies] = useState(null)
  const [trends,    setTrends]    = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')

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
      }
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load(subTab) }, [subTab, load])

  const SUB_TABS = [
    { id: 'summary',   label: 'Summary & Health' },
    { id: 'compare',   label: 'Compare Companies' },
    { id: 'anomalies', label: 'Anomaly Detection' },
    { id: 'trends',    label: 'Trend Forecast'    },
  ]

  const statusColor = (s) => s === 'healthy' ? '#22C55E' : s === 'warning' ? '#F59E0B' : s === 'critical' ? '#EF4444' : '#7F1D1D'

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

  useEffect(() => { loadCompanies(); loadTiers() }, [loadCompanies, loadTiers])
  useEffect(() => {
    setError('')
    if (subTab === 'overview')      loadOverview()
    if (subTab === 'subscription')  loadSubData()
    if (subTab === 'report')        loadReport()
  }, [subTab, selCo, loadOverview, loadSubData, loadReport])

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
    { id: 'overview',      label: 'Overview'       },
    { id: 'tiers',         label: 'Tiers'          },
    { id: 'subscription',  label: 'Subscription'   },
    { id: 'report',        label: 'Monthly Report' },
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
      '2FA Mgmt':       `${SEC}/2fa/status`,
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

  const handleSetup2FA = () => {
    if (!form.admin_id || !form.email) return
    post(`${SEC}/2fa/setup`, { admin_id: parseInt(form.admin_id), email: form.email, enabled: 1 })
      .then(() => { setMsg('2FA configured'); setForm({}); load(sub) })
      .catch(e => setErr(e.message))
  }

  const handleDisable2FA = (adminId) => {
    const target = data.find(r => r.id === adminId)
    if (!target?.email) { setErr('No email set — run setup first'); return }
    post(`${SEC}/2fa/setup`, { admin_id: adminId, email: target.email, enabled: 0 })
      .then(() => { setMsg('2FA disabled'); load(sub) })
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
          <div className="sa-cfg-row" style={{ marginBottom: 16 }}>
            <input style={inpStyle} placeholder="Admin ID" type="number" value={form.admin_id || ''} onChange={e => setForm(f => ({ ...f, admin_id: e.target.value }))} />
            <input style={inpStyle} placeholder="Email for OTP" value={form.email || ''} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
            <button className="sa-btn primary" onClick={handleSetup2FA}>Enable 2FA</button>
          </div>
          {busy ? <Spinner /> : (
            <table className="sa-table">
              <thead><tr><th>ID</th><th>Admin</th><th>Email</th><th>2FA</th><th></th></tr></thead>
              <tbody>
                {data.map(r => (
                  <tr key={r.id}>
                    <td style={{ fontSize: 11 }}>{r.id}</td>
                    <td style={{ fontSize: 12 }}>{r.name}</td>
                    <td style={{ fontSize: 12 }}>{r.email || <span style={{ color: 'var(--sa-text-muted)' }}>—</span>}</td>
                    <td><Badge label={r.requires_2fa ? 'Enabled' : 'Off'} type={r.requires_2fa ? 'active' : 'inactive'} /></td>
                    <td>
                      {r.requires_2fa
                        ? <button className="sa-btn danger" onClick={() => handleDisable2FA(r.id)}>Disable</button>
                        : null
                      }
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
  { id: 'alerts',     label: 'Alerts',         Icon: AlertTriangle   },
  { id: 'live',       label: 'Live Feed',      Icon: Activity        },
  { id: 'broadcast',  label: 'Broadcast',      Icon: Megaphone       },
  { id: 'sessions',   label: 'Sessions',       Icon: KeyRound        },
]

export default function SuperAdmin() {
  const navigate = useNavigate()
  const [tab,          setTab]          = useState('overview')
  const [adminDetail,  setAdminDetail]  = useState(null)
  const [viewAdmins,   setViewAdmins]   = useState(null)
  const [pendingCount, setPendingCount] = useState(0)

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
      case 'alerts':    return <AlertsTab />
      case 'live':      return <LiveFeedTab />
      case 'broadcast': return <BroadcastTab />
      case 'sessions':  return <SessionsTab />
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
