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
  Thermometer, Bell, Clock, Wifi, Gauge, Droplets,
  Server, Zap, Terminal,
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

class SessionExpiredError extends Error {
  constructor() { super('Session expired — please log in again'); this.isSessionExpired = true }
}

function handleSessionExpiry() {
  sessionStorage.removeItem('admin_token')
  sessionStorage.removeItem('admin_username')
  sessionStorage.removeItem('authenticated')
  sessionStorage.removeItem('adminVerified')
  sessionStorage.removeItem('login_time')
  window.location.replace('/super-admin/login')
}

async function api(method, path, body) {
  let res
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 20000) // 20-second timeout
  try {
    res = await fetch(path, {
      method,
      headers: adminHeaders(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: 'include',
      signal: controller.signal,
    })
  } catch (networkErr) {
    if (networkErr.name === 'AbortError') throw new Error('Request timed out — server took too long to respond')
    // Only throw "Session expired" if we already know the session is gone
    if (!sessionStorage.getItem('admin_token')) throw new SessionExpiredError()
    throw networkErr
  } finally {
    clearTimeout(timer)
  }
  if (res.status === 401) {
    // Defer navigation so concurrent Promise.all fetches settle before page unloads
    setTimeout(handleSessionExpiry, 50)
    throw new SessionExpiredError()
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

// ─── Platform health helpers ──────────────────────────────────────────────────

function _humanUptime(s) {
  if (s == null) return '—'
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60)
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m ${sec}s`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

// ─── Platform Health Strip (white cards, dark-blue accents) ──────────────────

function SAHealthStrip({ activeSessions, readingsToday, alertsToday }) {
  const [uptime, setUptime] = useState(null)

  useEffect(() => {
    const load = () =>
      fetch('/api/health').then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.uptime_seconds != null) setUptime(d.uptime_seconds) })
        .catch(() => {})
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  const C = '#1E3A8A'          // dark navy text
  const A = '#3B82F6'          // accent blue
  const card = {
    background: '#FFFFFF', border: '1px solid #BFDBFE', borderRadius: 14,
    padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 10,
    boxShadow: '0 1px 4px rgba(30,58,138,0.07)',
  }
  const iconBox = { width: 34, height: 34, borderRadius: 9, background: '#EFF6FF', display: 'flex', alignItems: 'center', justifyContent: 'center' }
  const label   = { fontSize: 11, fontWeight: 700, color: C, textTransform: 'uppercase', letterSpacing: '0.06em' }
  const bigNum  = { fontSize: 32, fontWeight: 800, lineHeight: 1 }
  const sub     = { fontSize: 12, color: A }
  const foot    = { fontSize: 11, color: '#93C5FD', borderTop: '1px solid #DBEAFE', paddingTop: 8, display: 'flex', alignItems: 'center', gap: 6 }
  const dot     = (col) => ({ width: 7, height: 7, borderRadius: '50%', background: col, flexShrink: 0 })

  const alertCol  = alertsToday > 0 ? '#F59E0B' : '#22C55E'

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: C, letterSpacing: '0.04em' }}>PLATFORM HEALTH</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>

        {/* Active Sessions */}
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={label}>Active Sessions</span>
            <div style={iconBox}><KeyRound size={16} color={A} /></div>
          </div>
          <span style={{ ...bigNum, color: C }}>{activeSessions ?? '—'}</span>
          <span style={sub}>Admin sessions live</span>
          <div style={foot}>
            <span style={dot(A)} />
            <span>{activeSessions > 0 ? `${activeSessions} admin${activeSessions !== 1 ? 's' : ''} online` : 'No active sessions'}</span>
          </div>
        </div>

        {/* Readings Today */}
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={label}>Readings Today</span>
            <div style={iconBox}><Activity size={16} color="#8B5CF6" /></div>
          </div>
          <span style={{ ...bigNum, color: C }}>{readingsToday ?? '—'}</span>
          <span style={sub}>Sensor readings logged</span>
          <div style={foot}>
            <span style={dot('#8B5CF6')} />
            <span>Across all companies</span>
          </div>
        </div>

        {/* Alerts Today */}
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={label}>Alerts Today</span>
            <div style={iconBox}><Bell size={16} color={alertCol} /></div>
          </div>
          <span style={{ ...bigNum, color: alertCol }}>{alertsToday ?? '—'}</span>
          <span style={sub}>{alertsToday > 0 ? 'Breach events today' : 'All clear today'}</span>
          <div style={foot}>
            <span style={dot(alertCol)} />
            <span>{alertsToday > 0 ? `${alertsToday} alert${alertsToday !== 1 ? 's' : ''} fired` : 'No alerts today'}</span>
          </div>
        </div>

      </div>
    </div>
  )
}

// ─── Overview tab ─────────────────────────────────────────────────────────────

const SEV_COLOR = { critical: '#EF4444', warning: '#F59E0B', info: '#3B82F6' }

// ─── Company Health Grid ──────────────────────────────────────────────────────

function fmtAge(minutes) {
  if (minutes === null || minutes === undefined) return 'never'
  if (minutes < 1)   return 'just now'
  if (minutes < 60)  return `${Math.round(minutes)}m ago`
  if (minutes < 1440) return `${Math.round(minutes / 60)}h ago`
  return `${Math.round(minutes / 1440)}d ago`
}

function CompanyHealthGrid({ onNavigate }) {
  const [companies, setCompanies] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState('')

  const load = useCallback(async () => {
    try {
      setCompanies(await get(`${SA}/companies/health`))
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [load])

  if (loading) return <Spinner />

  const red    = companies.filter(c => c.health === 'red').length
  const yellow = companies.filter(c => c.health === 'yellow').length
  const green  = companies.filter(c => c.health === 'green').length

  const HEALTH = {
    red:    { border: '#EF4444', bg: '#FEF2F2', dot: '#EF4444', label: 'Critical' },
    yellow: { border: '#F59E0B', bg: '#FFFBEB', dot: '#F59E0B', label: 'Warning'  },
    green:  { border: '#22C55E', bg: '#F0FDF4', dot: '#22C55E', label: 'Healthy'  },
  }

  return (
    <div className="sa-card" style={{ marginBottom: 16 }}>
      {/* Header with summary counts */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: error ? 8 : 16, flexWrap: 'wrap', gap: 8 }}>
        <h2 className="sa-card-title" style={{ margin: 0 }}>
          Company Health Grid
          <span style={{ fontSize: 12, fontWeight: 400, color: '#9CA3AF', marginLeft: 8 }}>auto-refreshes every 30s</span>
        </h2>
        <div style={{ display: 'flex', gap: 10 }}>
          {[
            { count: red,    color: '#EF4444', bg: '#FEF2F2', label: 'Critical' },
            { count: yellow, color: '#F59E0B', bg: '#FFFBEB', label: 'Warning'  },
            { count: green,  color: '#22C55E', bg: '#F0FDF4', label: 'Healthy'  },
          ].map(({ count, color, bg, label }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5, background: bg, borderRadius: 8, padding: '4px 10px', border: `1px solid ${color}30` }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
              <span style={{ fontSize: 13, fontWeight: 700, color }}>{count}</span>
              <span style={{ fontSize: 11, color: '#6B7280' }}>{label}</span>
            </div>
          ))}
          <button className="sa-btn sm secondary" onClick={load}>↻ Refresh</button>
        </div>
      </div>

      {error && (
        <div style={{ fontSize: 13, color: '#B91C1C', background: '#FEF2F2', border: '1px solid #FCA5A5', borderRadius: 6, padding: '8px 12px', marginBottom: 12 }}>
          Could not load health data: {error} — retrying every 30s
        </div>
      )}

      {companies.length === 0
        ? <p style={{ color: '#9CA3AF', textAlign: 'center', padding: 24 }}>No companies yet.</p>
        : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
            {companies.map(c => {
              const h = HEALTH[c.health] || HEALTH.green
              return (
                <div
                  key={c.id}
                  onClick={() => onNavigate('companies')}
                  style={{
                    background: h.bg,
                    border: `2px solid ${h.border}`,
                    borderRadius: 12,
                    padding: '12px 14px',
                    cursor: 'pointer',
                    transition: 'box-shadow 0.15s',
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                  onMouseEnter={e => e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.12)'}
                  onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
                >
                  {/* Colored left strip */}
                  <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: h.dot, borderRadius: '12px 0 0 12px' }} />
                  <div style={{ paddingLeft: 8 }}>
                    {/* Company name + status dot */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                      <div style={{ width: 32, height: 32, borderRadius: 8, background: h.dot + '20', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 14, color: h.dot, flexShrink: 0 }}>
                        {(c.name || '?')[0].toUpperCase()}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 700, fontSize: 13, color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.name}</div>
                        <div style={{ fontSize: 11, color: '#9CA3AF', fontFamily: 'monospace' }}>{c.slug}</div>
                      </div>
                      <div style={{ width: 10, height: 10, borderRadius: '50%', background: h.dot, flexShrink: 0,
                        boxShadow: c.health === 'red' ? `0 0 6px ${h.dot}` : 'none',
                        animation: c.health === 'red' ? 'pulse 1.5s infinite' : 'none' }} />
                    </div>

                    {/* Warnings */}
                    {c.flatline && (
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#DC2626', background: '#FEE2E2', borderRadius: 6, padding: '2px 8px', marginBottom: 6, display: 'inline-block' }}>
                        ⚠ No data for {fmtAge(c.minutes_since_reading)}
                      </div>
                    )}
                    {c.maintenance_mode && (
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#D97706', background: '#FEF3C7', borderRadius: 6, padding: '2px 8px', marginBottom: 6, display: 'inline-block' }}>
                        🔧 Maintenance
                      </div>
                    )}
                    {!c.is_active && !c.maintenance_mode && (
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#6B7280', background: '#F3F4F6', borderRadius: 6, padding: '2px 8px', marginBottom: 6, display: 'inline-block' }}>
                        Inactive
                      </div>
                    )}

                    {/* Stats row */}
                    <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: 16, fontWeight: 800, color: c.unack_critical > 0 ? '#EF4444' : c.unack_total > 0 ? '#F59E0B' : '#9CA3AF' }}>{c.unack_total}</div>
                        <div style={{ fontSize: 10, color: '#9CA3AF' }}>Unacked</div>
                      </div>
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: 16, fontWeight: 800, color: '#374151' }}>{c.alerts_today}</div>
                        <div style={{ fontSize: 10, color: '#9CA3AF' }}>Today</div>
                      </div>
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: 16, fontWeight: 800, color: '#374151' }}>{c.subscriber_count}</div>
                        <div style={{ fontSize: 10, color: '#9CA3AF' }}>Subs</div>
                      </div>
                      <div style={{ textAlign: 'center', flex: 1 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: '#6B7280', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {c.last_reading_at ? fmtAge(c.minutes_since_reading) : 'No data'}
                        </div>
                        <div style={{ fontSize: 10, color: '#9CA3AF' }}>Last reading</div>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )
      }
    </div>
  )
}

// ─── Overview Tab ─────────────────────────────────────────────────────────────

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

  const statsRow1 = [
    { label: 'Total Companies',   value: data.total_companies,   cls: 'blue'  },
    { label: 'Active Admins',     value: data.active_admins,     cls: 'green' },
    { label: 'Total Subscribers', value: data.total_subscribers, cls: 'blue'  },
    { label: 'Alerts Today',      value: data.alerts_today,      cls: data.alerts_today > 0 ? 'amber' : '' },
    { label: 'Alerts This Week',  value: data.alerts_week,       cls: data.alerts_week > 0 ? 'red'   : '' },
  ]

  const companies = data.companies || []
  const activeCount      = companies.filter(c => !c.maintenance_mode && c.is_active).length
  const maintenanceCount = companies.filter(c => c.maintenance_mode).length
  const inactiveCount    = companies.filter(c => !c.maintenance_mode && !c.is_active).length
  const pieData = [
    { name: 'Active',      value: activeCount,      fill: '#22C55E' },
    { name: 'Maintenance', value: maintenanceCount, fill: '#F59E0B' },
    { name: 'Inactive',    value: inactiveCount,    fill: '#EF4444' },
  ].filter(d => d.value > 0)

  return (
    <>
      {/* Company Health Grid — CAPTAIN'S RADAR */}
      <CompanyHealthGrid onNavigate={onNavigate} />

      {/* Subscriber coverage warnings */}
      <SubscriberCoverageWidget />

      {/* Platform Health strip */}
      <SAHealthStrip
        activeSessions={data.active_sessions ?? 0}
        readingsToday={data.readings_today ?? 0}
        alertsToday={data.alerts_today ?? 0}
      />

      {/* Stat grids */}
      <div className="sa-stat-grid">
        {statsRow1.map(s => (
          <div className="sa-stat" key={s.label}>
            <div className="sa-stat-label">{s.label}</div>
            <div className={`sa-stat-value ${s.cls}`}>{s.value ?? '—'}</div>
          </div>
        ))}
      </div>

      {/* Company Status Pie Chart */}
      {pieData.length > 0 && (
        <div className="sa-card">
          <h2 className="sa-card-title">Company Status Distribution</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
            <div style={{ width: 220, height: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%" cy="50%"
                    innerRadius={60} outerRadius={95}
                    paddingAngle={pieData.length > 1 ? 4 : 0}
                    dataKey="value"
                    label={({ name, value }) => `${name} (${value})`}
                    labelLine={false}
                  >
                    {pieData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                  </Pie>
                  <Tooltip formatter={(v, name) => [v, name]} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {[
                { label: 'Active',      count: activeCount,      color: '#22C55E', bg: '#F0FDF4' },
                { label: 'Maintenance', count: maintenanceCount, color: '#F59E0B', bg: '#FFFBEB' },
                { label: 'Inactive',    count: inactiveCount,    color: '#EF4444', bg: '#FEF2F2' },
              ].map(({ label, count, color, bg }) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ width: 36, height: 36, borderRadius: 8, background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <span style={{ width: 12, height: 12, borderRadius: '50%', background: color, display: 'inline-block' }} />
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#1F2937' }}>{label}</div>
                    <div style={{ fontSize: 12, color: '#6B7280' }}>{count} {count === 1 ? 'company' : 'companies'}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ─── CSV Download helper ───────────────────────────────────────────────────────

function downloadCSV(endpoint, filename) {
  const token = sessionStorage.getItem('admin_token') || ''
  fetch(endpoint, { headers: { Authorization: `Bearer ${token}` } })
    .then(res => {
      if (!res.ok) throw new Error(`Export failed: ${res.status}`)
      return res.blob()
    })
    .then(blob => {
      const url = URL.createObjectURL(blob)
      const a   = document.createElement('a')
      a.href     = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    })
    .catch(err => alert(err.message))
}

// ─── Subscriber Coverage Widget ────────────────────────────────────────────────

function SubscriberCoverageWidget() {
  const [rows,    setRows]    = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    get(`${SA}/subscriber-coverage`)
      .then(setRows)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) return null
  if (!rows.length) return null

  const critical = rows.filter(r => r.risk_level === 'critical')
  const warning  = rows.filter(r => r.risk_level === 'warning')

  return (
    <div className="sa-card" style={{ border: '1px solid #FCA5A5', background: '#FFF5F5' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <h2 className="sa-card-title" style={{ margin: 0, color: '#B91C1C' }}>
          ⚠ Subscriber Coverage Gaps ({rows.length})
        </h2>
        <span style={{ fontSize: 12, color: '#6B7280' }}>Alerts reach nobody if subscribers = 0</span>
      </div>

      {critical.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#DC2626', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Critical — No Subscribers ({critical.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {critical.map(r => (
              <div key={r.id} style={{ background: '#FEE2E2', border: '1px solid #FCA5A5', borderRadius: 8, padding: '6px 12px', fontSize: 13 }}>
                <span style={{ fontWeight: 700, color: '#B91C1C' }}>{r.name}</span>
                <span style={{ color: '#DC2626', marginLeft: 6 }}>{r.risk_label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {warning.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#B45309', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Warning — Single Subscriber ({warning.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {warning.map(r => (
              <div key={r.id} style={{ background: '#FEF3C7', border: '1px solid #FCD34D', borderRadius: 8, padding: '6px 12px', fontSize: 13 }}>
                <span style={{ fontWeight: 700, color: '#92400E' }}>{r.name}</span>
                <span style={{ color: '#B45309', marginLeft: 6 }}>{r.risk_label}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── New Company Wizard ────────────────────────────────────────────────────────

const WIZARD_STEPS = ['Company Details', 'First Admin', 'Add Subscriber', 'Review & Enable']

function NewCompanyWizard({ onClose, onComplete }) {
  const [step,      setStep]      = useState(0)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')
  const [companyId, setCompanyId] = useState(null)
  const [adminId,   setAdminId]   = useState(null)

  // Step 0 — company
  const [cName,     setCName]     = useState('')
  const [cSlug,     setCSlug]     = useState('')
  const [cDesc,     setCDesc]     = useState('')
  const [cTier,     setCTier]     = useState('basic')

  // Step 1 — admin
  const [aName,     setAName]     = useState('')
  const [aEmail,    setAEmail]    = useState('')
  const [aPass,     setAPass]     = useState('')

  // Step 2 — subscriber
  const [sPhone,    setSPhone]    = useState('')
  const [sEmail,    setSEmail]    = useState('')
  const [sName,     setSName]     = useState('')
  const [skipSub,   setSkipSub]   = useState(false)

  const autoSlug = (name) => name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')

  const handleNameChange = (v) => {
    setCName(v)
    if (!cSlug || cSlug === autoSlug(cName)) setCSlug(autoSlug(v))
  }

  const go = async () => {
    setError(''); setLoading(true)
    try {
      if (step === 0) {
        const res = await post(`${SA}/wizard/company`, { name: cName, slug: cSlug, description: cDesc, tier: cTier })
        setCompanyId(res.id)
        setStep(1)
      } else if (step === 1) {
        const res = await post(`${SA}/wizard/admin`, { company_id: companyId, name: aName, email: aEmail, password: aPass })
        setAdminId(res.id)
        setStep(2)
      } else if (step === 2) {
        if (!skipSub) {
          await post(`${SA}/wizard/subscriber`, { company_id: companyId, phone: sPhone || null, email: sEmail || null, name: sName || null })
        }
        setStep(3)
      } else if (step === 3) {
        await post(`${SA}/wizard/enable/${companyId}`, {})
        onComplete?.()
        onClose()
      }
    } catch (e) {
      setError(e.message || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  const canAdvance = () => {
    if (step === 0) return cName.trim().length >= 2 && cSlug.trim().length >= 2
    if (step === 1) return aName.trim() && aEmail.trim() && aPass.trim().length >= 6
    if (step === 2) return skipSub || sPhone.trim() || sEmail.trim()
    return true
  }

  const iLabel = ['Create Company', 'Create Admin', skipSub ? 'Skip & Continue' : 'Add Subscriber', 'Enable & Finish']

  return (
    <Modal
      title="New Company Wizard"
      onClose={onClose}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
          <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
          <button className="sa-btn primary" onClick={go} disabled={loading || !canAdvance()}>
            {loading ? 'Working…' : iLabel[step]}
          </button>
        </div>
      }
    >
      {/* Progress bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 24 }}>
        {WIZARD_STEPS.map((label, i) => (
          <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <div style={{ width: '100%', height: 4, borderRadius: 2, background: i <= step ? '#1D4ED8' : '#E5E7EB', transition: 'background 0.3s' }} />
            <span style={{ fontSize: 10, color: i === step ? '#1D4ED8' : '#9CA3AF', fontWeight: i === step ? 700 : 400 }}>
              {i + 1}. {label}
            </span>
          </div>
        ))}
      </div>

      {error && <Err msg={error} />}

      {/* Step 0 — Company Details */}
      {step === 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label className="sa-label">Company Name *</label>
            <input className="sa-input" value={cName} onChange={e => handleNameChange(e.target.value)} placeholder="Acme Corp" />
          </div>
          <div>
            <label className="sa-label">Slug (URL-safe ID) *</label>
            <input className="sa-input" value={cSlug} onChange={e => setCSlug(autoSlug(e.target.value))} placeholder="acme-corp" style={{ fontFamily: 'monospace' }} />
          </div>
          <div>
            <label className="sa-label">Description</label>
            <input className="sa-input" value={cDesc} onChange={e => setCDesc(e.target.value)} placeholder="Optional description" />
          </div>
          <div>
            <label className="sa-label">Tier</label>
            <select className="sa-input" value={cTier} onChange={e => setCTier(e.target.value)}>
              <option value="basic">Basic</option>
              <option value="pro">Pro</option>
              <option value="enterprise">Enterprise</option>
            </select>
          </div>
          <p style={{ fontSize: 12, color: '#6B7280', margin: 0, background: '#F9FAFB', borderRadius: 6, padding: '8px 10px' }}>
            The company will be created as <strong>disabled</strong> until the wizard completes. No alerts will fire until you enable it on step 4.
          </p>
        </div>
      )}

      {/* Step 1 — Admin */}
      {step === 1 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: '#EFF6FF', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: '#1D4ED8', marginBottom: 4 }}>
            Creating first admin for <strong>{cName}</strong>
          </div>
          <div>
            <label className="sa-label">Admin Name *</label>
            <input className="sa-input" value={aName} onChange={e => setAName(e.target.value)} placeholder="John Smith" />
          </div>
          <div>
            <label className="sa-label">Email (login) *</label>
            <input className="sa-input" type="email" value={aEmail} onChange={e => setAEmail(e.target.value)} placeholder="john@acmecorp.com" />
          </div>
          <div>
            <label className="sa-label">Password * (min 6 chars)</label>
            <input className="sa-input" type="password" value={aPass} onChange={e => setAPass(e.target.value)} placeholder="••••••••" />
          </div>
        </div>
      )}

      {/* Step 2 — Subscriber */}
      {step === 2 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: '#FFF7ED', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: '#92400E', marginBottom: 4 }}>
            Subscribers receive alerts (SMS/email). A company with 0 subscribers won't notify anyone.
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, color: '#374151' }}>
            <input type="checkbox" checked={skipSub} onChange={e => setSkipSub(e.target.checked)} />
            Skip for now (add subscribers later in admin dashboard)
          </label>
          {!skipSub && (
            <>
              <div>
                <label className="sa-label">Subscriber Name</label>
                <input className="sa-input" value={sName} onChange={e => setSName(e.target.value)} placeholder="Jane Doe" />
              </div>
              <div>
                <label className="sa-label">Phone (for SMS)</label>
                <input className="sa-input" value={sPhone} onChange={e => setSPhone(e.target.value)} placeholder="+1234567890" />
              </div>
              <div>
                <label className="sa-label">Email</label>
                <input className="sa-input" type="email" value={sEmail} onChange={e => setSEmail(e.target.value)} placeholder="jane@acmecorp.com" />
              </div>
            </>
          )}
        </div>
      )}

      {/* Step 3 — Review & Enable */}
      {step === 3 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ background: '#F0FDF4', border: '1px solid #86EFAC', borderRadius: 10, padding: 16 }}>
            <div style={{ fontWeight: 700, color: '#15803D', marginBottom: 12, fontSize: 14 }}>✓ Setup Complete — Ready to enable</div>
            {[
              ['Company',    cName, '#1D4ED8'],
              ['Slug',       cSlug, '#6B7280'],
              ['Tier',       cTier, '#374151'],
              ['Admin',      `${aName} (${aEmail})`, '#374151'],
              ['Subscriber', skipSub ? 'None (skipped)' : (sName || sPhone || sEmail || '—'), '#374151'],
            ].map(([label, val, color]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #BBF7D0', fontSize: 13 }}>
                <span style={{ color: '#6B7280', fontWeight: 600 }}>{label}</span>
                <span style={{ color, fontWeight: 600 }}>{val}</span>
              </div>
            ))}
          </div>
          <p style={{ fontSize: 13, color: '#374151', margin: 0 }}>
            Clicking <strong>Enable & Finish</strong> will activate the company. Sensors can start sending data and admins can log in immediately.
          </p>
        </div>
      )}
    </Modal>
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

// ─── Company Detail View ──────────────────────────────────────────────────────

function CompanyDetailView({ companyId, onBack }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')
  const [tab,     setTab]     = useState('profile')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await get(`${SA}/companies/${companyId}/detail`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [companyId])

  useEffect(() => { load() }, [load])

  if (loading) return <><button className="sa-back-btn" onClick={onBack}>← Back</button><Spinner /></>
  if (error)   return <><button className="sa-back-btn" onClick={onBack}>← Back</button><Err msg={error} /></>

  const { company: c, admins, subscribers, parameters, alert_stats, reading_stats, sessions, recent_alerts } = data

  const field = (label, value) => (
    <div key={label} style={{ padding: '10px 0', borderBottom: '1px solid #F3F4F6' }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 14, color: '#111827', fontWeight: 500, wordBreak: 'break-all' }}>{value ?? '—'}</div>
    </div>
  )

  const SEV = { critical: '#EF4444', warning: '#F59E0B', info: '#3B82F6' }

  return (
    <>
      <button className="sa-back-btn" onClick={onBack}>← Back to Companies</button>

      {/* Hero header */}
      <div className="sa-card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
          <div style={{ width: 52, height: 52, borderRadius: 14, background: '#EFF6FF', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 22, fontWeight: 800, color: '#1D4ED8' }}>
            {(c.name || '?')[0].toUpperCase()}
          </div>
          <div style={{ flex: 1 }}>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#111827' }}>{c.name}</h2>
            <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <code style={{ fontSize: 12, background: '#F3F4F6', padding: '2px 8px', borderRadius: 6, color: '#6B7280' }}>{c.slug}</code>
              {c.maintenance_mode
                ? <Badge label="Maintenance" type="warning" />
                : c.is_active ? <Badge label="Active" type="active" /> : <Badge label="Inactive" type="inactive" />
              }
              <span style={{ fontSize: 12, color: '#9CA3AF' }}>Tier: <strong style={{ color: '#374151' }}>{c.tier_name}</strong></span>
              <span style={{ fontSize: 12, color: '#9CA3AF' }}>ID: <strong style={{ color: '#374151' }}>#{c.id}</strong></span>
            </div>
          </div>
          {/* Quick stats strip */}
          <div style={{ display: 'flex', gap: 20 }}>
            {[
              { label: 'Admins',      val: admins.length,      col: '#3B82F6' },
              { label: 'Subscribers', val: subscribers.length, col: '#8B5CF6' },
              { label: 'Parameters',  val: parameters.length,  col: '#10B981' },
              { label: 'Alerts Today',val: alert_stats.alerts_today ?? 0, col: alert_stats.alerts_today > 0 ? '#F59E0B' : '#22C55E' },
            ].map(({ label, val, col }) => (
              <div key={label} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 800, color: col }}>{val}</div>
                <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Tabs */}
        <div className="sa-tabs">
          {[
            { id: 'profile',     label: 'Profile'     },
            { id: 'admins',      label: `Admins (${admins.length})`           },
            { id: 'subscribers', label: `Subscribers (${subscribers.length})` },
            { id: 'parameters',  label: `Parameters (${parameters.length})`   },
            { id: 'stats',       label: 'Stats & Alerts' },
            { id: 'sessions',    label: `Sessions (${sessions.length})`       },
          ].map(t => (
            <button key={t.id} className={`sa-tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Profile tab ── */}
      {tab === 'profile' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div className="sa-card">
            <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#374151' }}>Identity</h3>
            {field('Company ID', `#${c.id}`)}
            {field('Name', c.name)}
            {field('Slug / URL key', c.slug)}
            {field('Domain', `${c.slug}.sentineledge.app`)}
            {field('Description', c.description || 'No description set')}
            {field('Created At', c.created_at ? new Date(c.created_at).toLocaleString() : '—')}
            {field('Subscription Tier', c.tier_name)}
          </div>
          <div className="sa-card">
            <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#374151' }}>Configuration</h3>
            {field('Status', c.maintenance_mode ? 'Maintenance' : c.is_active ? 'Active' : 'Inactive')}
            {field('Maintenance Reason', c.maintenance_reason || 'N/A')}
            {field('Max Subscribers', c.max_subscribers)}
            {field('Max Devices', c.max_devices)}
            {field('Allowed Channels', c.allowed_channels)}
            {field('SMS Used (this month)', c.sms_used)}
            {field('Email Used (this month)', c.email_used)}
            {field('Push Used (this month)', c.push_used)}
          </div>
        </div>
      )}

      {/* ── Admins tab ── */}
      {tab === 'admins' && (
        <div className="sa-card">
          <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#374151' }}>Admins ({admins.length})</h3>
          <div className="sa-table-wrap">
            <table className="sa-table">
              <thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Last Login</th><th>Last IP</th><th>Created</th></tr></thead>
              <tbody>
                {admins.length === 0
                  ? <tr><td colSpan={8} className="sa-empty">No admins assigned.</td></tr>
                  : admins.map(a => (
                    <tr key={a.id}>
                      <td style={{ color: '#9CA3AF', fontSize: 12 }}>#{a.id}</td>
                      <td><strong>{a.name}</strong></td>
                      <td style={{ fontSize: 12 }}>{a.email || '—'}</td>
                      <td><Badge label={a.role} type={a.role} /></td>
                      <td>{a.is_active ? <Badge label="Active" type="active" /> : <Badge label="Inactive" type="inactive" />}</td>
                      <td style={{ fontSize: 12, color: '#6B7280' }}>{a.last_login_at ? new Date(a.last_login_at).toLocaleString() : 'Never'}</td>
                      <td style={{ fontSize: 12, color: '#6B7280', fontFamily: 'monospace' }}>{a.last_login_ip || '—'}</td>
                      <td style={{ fontSize: 12, color: '#6B7280' }}>{a.created_at ? new Date(a.created_at).toLocaleDateString() : '—'}</td>
                    </tr>
                  ))
                }
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Subscribers tab ── */}
      {tab === 'subscribers' && (
        <div className="sa-card">
          <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#374151' }}>Subscribers ({subscribers.length})</h3>
          <div className="sa-table-wrap">
            <table className="sa-table">
              <thead><tr><th>ID</th><th>Name</th><th>Phone</th><th>Email</th><th>Escalation Order</th><th>Status</th><th>Joined</th></tr></thead>
              <tbody>
                {subscribers.length === 0
                  ? <tr><td colSpan={7} className="sa-empty">No subscribers.</td></tr>
                  : subscribers.map(s => (
                    <tr key={s.id}>
                      <td style={{ color: '#9CA3AF', fontSize: 12 }}>#{s.id}</td>
                      <td><strong>{s.name}</strong></td>
                      <td style={{ fontSize: 12 }}>{s.phone || '—'}</td>
                      <td style={{ fontSize: 12 }}>{s.email || '—'}</td>
                      <td style={{ textAlign: 'center' }}>{s.escalation_order}</td>
                      <td>{s.is_active ? <Badge label="Active" type="active" /> : <Badge label="Inactive" type="inactive" />}</td>
                      <td style={{ fontSize: 12, color: '#6B7280' }}>{s.created_at ? new Date(s.created_at).toLocaleDateString() : '—'}</td>
                    </tr>
                  ))
                }
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Parameters tab ── */}
      {tab === 'parameters' && (
        <div className="sa-card">
          <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#374151' }}>All Parameters ({parameters.length})</h3>
          <div className="sa-table-wrap">
            <table className="sa-table">
              <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Unit</th><th>Min</th><th>Max</th><th>Status</th></tr></thead>
              <tbody>
                {parameters.length === 0
                  ? <tr><td colSpan={7} className="sa-empty">No parameters configured.</td></tr>
                  : parameters.map((p, i) => (
                    <tr key={p.id ?? `builtin-${i}`}>
                      <td style={{ color: '#9CA3AF', fontSize: 12 }}>{p.id ? `#${p.id}` : '—'}</td>
                      <td><strong style={{ textTransform: 'capitalize' }}>{p.name}</strong></td>
                      <td>{p.builtin
                        ? <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10, background: '#EFF6FF', color: '#3B82F6' }}>Built-in</span>
                        : <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10, background: '#F0FDF4', color: '#16A34A' }}>Sensor</span>
                      }</td>
                      <td>{p.unit || '—'}</td>
                      <td>{p.min_value ?? '—'}</td>
                      <td>{p.max_value ?? '—'}</td>
                      <td><Badge label="Active" type="active" /></td>
                    </tr>
                  ))
                }
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Stats & Alerts tab ── */}
      {tab === 'stats' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 16 }}>
            {[
              { label: 'Total Alerts',    val: alert_stats.total_alerts   ?? 0, col: '#374151' },
              { label: 'Alerts Today',    val: alert_stats.alerts_today   ?? 0, col: alert_stats.alerts_today   > 0 ? '#F59E0B' : '#22C55E' },
              { label: 'Alerts This Week',val: alert_stats.alerts_week    ?? 0, col: alert_stats.alerts_week    > 0 ? '#F59E0B' : '#22C55E' },
              { label: 'Critical Alerts', val: alert_stats.critical       ?? 0, col: alert_stats.critical       > 0 ? '#EF4444' : '#22C55E' },
              { label: 'Warning Alerts',  val: alert_stats.warning        ?? 0, col: alert_stats.warning        > 0 ? '#F59E0B' : '#22C55E' },
              { label: 'Acknowledged',    val: alert_stats.acknowledged   ?? 0, col: '#3B82F6' },
              { label: 'Total Readings',  val: reading_stats.total_readings ?? 0, col: '#374151' },
              { label: 'Readings Today',  val: reading_stats.readings_today ?? 0, col: '#3B82F6' },
              { label: 'Last Reading',    val: reading_stats.last_reading_at ? new Date(reading_stats.last_reading_at).toLocaleString() : 'Never', col: '#374151' },
              { label: 'Min Temperature', val: reading_stats.min_temp != null ? `${reading_stats.min_temp}°C` : '—', col: '#3B82F6' },
              { label: 'Max Temperature', val: reading_stats.max_temp != null ? `${reading_stats.max_temp}°C` : '—', col: '#EF4444' },
              { label: 'Avg Temperature', val: reading_stats.avg_temp != null ? `${reading_stats.avg_temp}°C` : '—', col: '#374151' },
            ].map(({ label, val, col }) => (
              <div key={label} className="sa-stat">
                <div className="sa-stat-label">{label}</div>
                <div className="sa-stat-value" style={{ color: col }}>{val}</div>
              </div>
            ))}
          </div>

          <div className="sa-card">
            <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#374151' }}>Recent Alerts (last 10)</h3>
            <div className="sa-table-wrap">
              <table className="sa-table">
                <thead><tr><th>ID</th><th>Parameter</th><th>Value</th><th>Threshold</th><th>Direction</th><th>Severity</th><th>Time</th><th>Ack</th></tr></thead>
                <tbody>
                  {recent_alerts.length === 0
                    ? <tr><td colSpan={8} className="sa-empty">No alerts.</td></tr>
                    : recent_alerts.map(a => (
                      <tr key={a.id}>
                        <td style={{ color: '#9CA3AF', fontSize: 12 }}>#{a.id}</td>
                        <td><strong>{a.parameter}</strong></td>
                        <td>{a.value != null ? Number(a.value).toFixed(2) : '—'}</td>
                        <td>{a.threshold != null ? Number(a.threshold).toFixed(2) : '—'}</td>
                        <td>{a.direction}</td>
                        <td>
                          <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 12,
                            background: (SEV[a.severity] || '#6B7280') + '20', color: SEV[a.severity] || '#6B7280', textTransform: 'capitalize' }}>
                            {a.severity}
                          </span>
                        </td>
                        <td style={{ fontSize: 12, color: '#6B7280', whiteSpace: 'nowrap' }}>{a.timestamp ? new Date(a.timestamp).toLocaleString() : '—'}</td>
                        <td>{a.acknowledged ? <Badge label="Yes" type="active" /> : <Badge label="No" type="inactive" />}</td>
                      </tr>
                    ))
                  }
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── Sessions tab ── */}
      {tab === 'sessions' && (
        <div className="sa-card">
          <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#374151' }}>Active Admin Sessions ({sessions.length})</h3>
          <div className="sa-table-wrap">
            <table className="sa-table">
              <thead><tr><th>Admin</th><th>Role</th><th>Started</th><th>Expires</th><th>Last Active</th></tr></thead>
              <tbody>
                {sessions.length === 0
                  ? <tr><td colSpan={5} className="sa-empty">No active sessions.</td></tr>
                  : sessions.map(s => (
                    <tr key={s.id}>
                      <td><strong>{s.admin_name}</strong></td>
                      <td><Badge label={s.admin_role} type={s.admin_role} /></td>
                      <td style={{ fontSize: 12, color: '#6B7280' }}>{s.created_at ? new Date(s.created_at).toLocaleString() : '—'}</td>
                      <td style={{ fontSize: 12, color: '#6B7280' }}>{s.expires_at ? new Date(s.expires_at).toLocaleString() : '—'}</td>
                      <td style={{ fontSize: 12, color: '#6B7280' }}>{s.last_used_at ? new Date(s.last_used_at).toLocaleString() : '—'}</td>
                    </tr>
                  ))
                }
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}

// ─── Companies tab ────────────────────────────────────────────────────────────

function CompaniesTab({ onViewAdmins }) {
  const [companies,  setCompanies]  = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')
  const [formTarget, setFormTarget] = useState(undefined)
  const [delTarget,  setDelTarget]  = useState(null)
  const [delErr,     setDelErr]     = useState('')
  const [delLoading, setDelLoading] = useState(false)
  const [toast,      setToast]      = useState('')
  const [detailId,   setDetailId]   = useState(null)
  const [showWizard, setShowWizard] = useState(false)

  // ── Bulk selection ──────────────────────────────────────────────────────────
  const [selected,    setSelected]    = useState(new Set())
  const [bulkLoading, setBulkLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(''); setSelected(new Set())
    try { setCompanies(await get(`${SA}/companies`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3500) }

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

  const toggleSelect = (id) => setSelected(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const toggleAll = () => {
    if (selected.size === companies.length) setSelected(new Set())
    else setSelected(new Set(companies.map(c => c.id)))
  }

  const runBulk = async (action) => {
    if (!selected.size) return
    setBulkLoading(true)
    try {
      await post(`${SA}/companies/bulk`, { ids: [...selected], action })
      showToast(`Bulk ${action} applied to ${selected.size} companies`)
      load()
    } catch (e) { setError(e.message) }
    finally { setBulkLoading(false) }
  }

  if (detailId) {
    return <CompanyDetailView companyId={detailId} onBack={() => setDetailId(null)} />
  }

  const BULK_ACTIONS = [
    { action: 'enable',           label: 'Enable Selected' },
    { action: 'disable',          label: 'Disable Selected' },
    { action: 'maintenance_on',   label: 'Maintenance On' },
    { action: 'maintenance_off',  label: 'Maintenance Off' },
  ]

  return (
    <>
      {toast && <div style={{ position: 'fixed', top: 20, right: 20, background: '#D1FAE5', color: '#065F46', padding: '10px 18px', borderRadius: 8, fontWeight: 600, fontSize: 13, zIndex: 2000 }}>{toast}</div>}

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div style={{ position: 'sticky', top: 0, zIndex: 100, background: '#1D4ED8', color: '#fff', padding: '10px 18px', borderRadius: 10, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 12, boxShadow: '0 4px 16px rgba(29,78,216,0.35)' }}>
          <span style={{ fontWeight: 700, fontSize: 14 }}>{selected.size} selected</span>
          <div style={{ display: 'flex', gap: 8, marginLeft: 'auto', flexWrap: 'wrap' }}>
            {BULK_ACTIONS.map(({ action, label }) => (
              <button key={action} disabled={bulkLoading}
                onClick={() => runBulk(action)}
                style={{ background: 'rgba(255,255,255,0.15)', border: '1px solid rgba(255,255,255,0.3)', color: '#fff', borderRadius: 6, padding: '5px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
                {label}
              </button>
            ))}
            <button onClick={() => setSelected(new Set())}
              style={{ background: 'transparent', border: 'none', color: 'rgba(255,255,255,0.7)', fontSize: 12, cursor: 'pointer', padding: '5px 8px' }}>
              ✕ Clear
            </button>
          </div>
        </div>
      )}

      <div className="sa-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
          <h2 className="sa-card-title" style={{ margin: 0 }}>Companies ({companies.length})</h2>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="sa-btn secondary sm"
              onClick={() => downloadCSV(`${SA}/export/companies.csv`, 'companies.csv')}>
              ⬇ Export CSV
            </button>
            <button className="sa-btn primary" onClick={() => setShowWizard(true)}>+ New Company</button>
          </div>
        </div>
        {error && <Err msg={error} />}
        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead><tr>
              <th style={{ width: 36 }}>
                <input type="checkbox"
                  checked={companies.length > 0 && selected.size === companies.length}
                  onChange={toggleAll}
                  title="Select all"
                />
              </th>
              <th>Name</th><th>Slug</th><th>Status</th><th>Subscribers</th><th>Admins</th><th>Alerts Today</th><th>Actions</th>
            </tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={8} className="sa-empty"><Spinner /></td></tr>
               : companies.length === 0 ? <tr><td colSpan={8} className="sa-empty">No companies yet.</td></tr>
               : companies.map(c => (
                <tr key={c.id} style={{ background: selected.has(c.id) ? 'rgba(219,234,254,0.5)' : undefined }}>
                  <td style={{ textAlign: 'center' }}>
                    <input type="checkbox"
                      checked={selected.has(c.id)}
                      onChange={() => toggleSelect(c.id)}
                    />
                  </td>
                  <td>
                    <button
                      style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontWeight: 700, fontSize: 14, color: '#1D4ED8', textDecoration: 'underline', textUnderlineOffset: 3 }}
                      onClick={() => setDetailId(c.id)}
                    >
                      {c.name}
                    </button>
                  </td>
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

      {showWizard && (
        <NewCompanyWizard
          onClose={() => setShowWizard(false)}
          onComplete={load}
        />
      )}

      {formTarget !== undefined && formTarget !== null && (
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
    <Modal title={`Set / Update Password — ${admin.name}`} onClose={onClose}
      footer={done
        ? <button className="sa-btn primary" onClick={onClose}>Done</button>
        : <>
            <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
            <button className="sa-btn primary" onClick={handleSubmit} disabled={loading}>{loading ? 'Saving…' : 'Save Password'}</button>
          </>
      }
    >
      {done
        ? <p style={{ color: '#059669', margin: 0, fontWeight: 600 }}>Password updated successfully.</p>
        : <>
            <p style={{ fontSize: 13, color: '#6B7280', marginTop: 0, marginBottom: 14 }}>
              Enter a new password for <strong>{admin.name}</strong>. Minimum 6 characters.
            </p>
            <div className="sa-form-group">
              <label>New Password</label>
              <input className="sa-input" type="password" value={pwd} onChange={e => setPwd(e.target.value)} placeholder="min. 6 characters" autoFocus />
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

// Impersonation modal — opens the admin dashboard as that user in a new tab
function ImpersonateModal({ admin, code, expiresAt, onClose }) {
  const [opened, setOpened] = useState(false)

  const openDashboard = () => {
    const params = new URLSearchParams({
      imp_code:   code,
      admin_name: admin.name,
      ...(admin.company_id ? { company_id: admin.company_id } : {}),
    })
    // The new tab redeems the one-time code via POST to get the actual session token.
    window.open(`/sub-admin/dashboard?${params}`, '_blank', 'noopener,noreferrer')
    setOpened(true)
  }

  return (
    <Modal title={`Login As — ${admin.name}`} onClose={onClose}
      footer={
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="sa-btn secondary" onClick={onClose}>Close</button>
          <button className="sa-btn primary" onClick={openDashboard}>
            {opened ? '↗ Open Again' : '↗ Open Admin Dashboard'}
          </button>
        </div>
      }
    >
      {/* Context banner */}
      <div style={{ background: '#EFF6FF', border: '1px solid #BFDBFE', borderRadius: 8, padding: '10px 14px', marginBottom: 16, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <div style={{ width: 36, height: 36, borderRadius: 8, background: '#1D4ED8', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: 15, flexShrink: 0 }}>
          {(admin.name || '?')[0].toUpperCase()}
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, color: '#1E3A8A' }}>{admin.name}</div>
          <div style={{ fontSize: 12, color: '#3B82F6' }}>
            {admin.role} · {admin.company_name || 'Unassigned'}
          </div>
          <div style={{ fontSize: 11, color: '#6B7280', marginTop: 2 }}>
            Session valid until {new Date(expiresAt).toLocaleTimeString()}
          </div>
        </div>
      </div>

      <p style={{ color: '#374151', fontSize: 13, margin: '0 0 12px' }}>
        Click <strong>Open Admin Dashboard</strong> to view the platform exactly as <strong>{admin.name}</strong> sees it.
        All actions are logged with a note that the super admin was acting on their behalf.
      </p>

      {opened && (
        <div style={{ background: '#F0FDF4', border: '1px solid #86EFAC', borderRadius: 8, padding: '8px 12px', marginBottom: 12, fontSize: 12, color: '#15803D', fontWeight: 600 }}>
          ✓ Dashboard opened in new tab. Close that tab when done.
        </div>
      )}

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
      setImpersonateResult({ admin: a, code: data.impersonation_code, expiresAt: data.expires_at })
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
               : admins.filter(a => a.role !== 'super_admin').length === 0
                 ? <tr><td colSpan={7} className="sa-empty">No admins found.</td></tr>
               : admins.filter(a => a.role !== 'super_admin').map(a => {
                  const roleLabel = a.role === 'main' ? 'Admin' : 'Sub Admin'
                  const roleType  = a.role === 'main' ? 'main' : 'sub'
                  return (
                  <tr key={a.id}>
                    <td>
                      <button style={{ background: 'none', border: 'none', cursor: 'pointer', fontWeight: 700, color: '#4338CA', padding: 0 }}
                        onClick={() => onViewDetail(a.id)}>
                        {a.name}
                      </button>
                      {a.requires_approval ? <span className="sa-approval-tag">Approval req.</span> : null}
                    </td>
                    <td><Badge label={roleLabel} type={roleType} /></td>
                    <td>
                      {a.company_name
                        ? <span style={{ fontWeight: 600, color: '#374151' }}>{a.company_name}</span>
                        : <span style={{ color: '#D1D5DB', fontStyle: 'italic' }}>Not assigned</span>}
                    </td>
                    <td><Badge label={a.is_active === 0 ? 'Inactive' : 'Active'} type={a.is_active === 0 ? 'inactive' : 'active'} /></td>
                    <td style={{ fontSize: 12, color: '#6B7280' }}>{a.last_login_at ? new Date(a.last_login_at).toLocaleString() : 'Never'}</td>
                    <td style={{ textAlign: 'center' }}>{a.actions_7d ?? 0}</td>
                    <td>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <button className="sa-btn sm secondary" onClick={() => onViewDetail(a.id)}>Details</button>
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
                        <button className="sa-btn sm secondary" onClick={() => setResetTarget(a)}>Set/Update Pwd</button>
                        <button className="sa-btn sm secondary" onClick={() => setAssignTarget(a)}>Company</button>
                      </div>
                    </td>
                  </tr>
                )})
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
          code={impersonateResult.code}
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
  const [alerts,    setAlerts]    = useState([])
  const [companies, setCompanies] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState('')
  const [filter,    setFilter]    = useState('all')    // all | unacked | critical | warning
  const [company,   setCompany]   = useState('')
  const [acking,    setAcking]    = useState(null)     // alert id being acked
  const [toast,     setToast]     = useState('')

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3000) }

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const params = new URLSearchParams({ limit: 200 })
      if (company) params.set('company_id', company)
      if (filter === 'unacked')  params.set('unack_only', 'true')
      if (filter === 'critical') params.set('severity', 'critical')
      if (filter === 'warning')  params.set('severity', 'warning')
      const [a, c] = await Promise.all([
        get(`${SA}/alerts/triage?${params}`),
        get(`${SA}/companies`),
      ])
      setAlerts(Array.isArray(a) ? a : [])
      setCompanies(Array.isArray(c) ? c : [])
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [filter, company])

  useEffect(() => { load() }, [load])

  const autoRef = useRef()
  useEffect(() => {
    autoRef.current = setInterval(load, 15000)
    return () => clearInterval(autoRef.current)
  }, [load])

  const handleAck = async (alertId) => {
    setAcking(alertId)
    try {
      await post(`${SA}/alerts/${alertId}/acknowledge`, {})
      showToast(`Alert #${alertId} acknowledged`)
      load()
    } catch (e) { setError(e.message) }
    finally { setAcking(null) }
  }

  const unackedCount    = alerts.filter(a => !a.acknowledged).length
  const criticalUnacked = alerts.filter(a => !a.acknowledged && a.severity === 'critical').length
  const companiesHit    = new Set(alerts.filter(a => !a.acknowledged).map(a => a.company_id)).size

  const SEV_STYLE = {
    critical: { bg: '#FEF2F2', border: '#FCA5A5', text: '#DC2626', rowBg: '#FFF5F5' },
    warning:  { bg: '#FFFBEB', border: '#FDE68A', text: '#D97706', rowBg: '#FFFDF5' },
    info:     { bg: '#EFF6FF', border: '#BFDBFE', text: '#2563EB', rowBg: '#FAFBFF' },
  }

  const fmtOpen = (min) => {
    if (!min && min !== 0) return '—'
    if (min < 1)  return '<1m'
    if (min < 60) return `${Math.round(min)}m`
    if (min < 1440) return `${Math.round(min/60)}h ${Math.round(min%60)}m`
    return `${Math.round(min/1440)}d`
  }

  return (
    <>
      {toast && <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46', padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>}

      {/* Command strip */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12, marginBottom:16 }}>
        {[
          { label:'Unacknowledged', val: unackedCount,    color: unackedCount    > 0 ? '#EF4444' : '#22C55E' },
          { label:'Critical Unacked',val: criticalUnacked, color: criticalUnacked > 0 ? '#EF4444' : '#22C55E' },
          { label:'Companies Affected', val: companiesHit, color: companiesHit   > 0 ? '#F59E0B' : '#22C55E' },
        ].map(({ label, val, color }) => (
          <div key={label} className="sa-stat" style={{ borderLeft: `4px solid ${color}` }}>
            <div className="sa-stat-label">{label}</div>
            <div className="sa-stat-value" style={{ color }}>{val}</div>
          </div>
        ))}
      </div>

      <div className="sa-card">
        {/* Filters */}
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16, flexWrap:'wrap', gap:8 }}>
          <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
            <h2 className="sa-card-title" style={{ margin:0, marginRight:8 }}>Alert Triage</h2>
            {[
              { id:'all',      label:'All'       },
              { id:'unacked',  label:`Unacked (${unackedCount})` },
              { id:'critical', label:'Critical'  },
              { id:'warning',  label:'Warning'   },
            ].map(f => (
              <button key={f.id} className={`sa-btn sm ${filter === f.id ? 'primary' : 'secondary'}`}
                onClick={() => { setFilter(f.id); setCompany('') }}>{f.label}</button>
            ))}
          </div>
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            <select className="sa-select" style={{ width:'auto', padding:'6px 10px', fontSize:13 }}
              value={company} onChange={e => setCompany(e.target.value)}>
              <option value="">All companies</option>
              {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button className="sa-btn sm secondary"
              onClick={() => downloadCSV(`${SA}/export/alerts.csv`, 'alerts.csv')}>
              ⬇ Export
            </button>
            <button className="sa-btn sm secondary" onClick={load}>↻ Refresh</button>
          </div>
        </div>

        {error && <Err msg={error} />}

        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Company</th>
                <th>Parameter</th>
                <th>Value</th>
                <th>Threshold</th>
                <th>Open For</th>
                <th>Time</th>
                <th>Ack</th>
              </tr>
            </thead>
            <tbody>
              {loading
                ? <tr><td colSpan={8} className="sa-empty"><Spinner /></td></tr>
                : alerts.length === 0
                  ? <tr><td colSpan={8} className="sa-empty">No alerts match the current filter.</td></tr>
                  : alerts.map(a => {
                      const ss = SEV_STYLE[a.severity] || SEV_STYLE.info
                      const rowStyle = !a.acknowledged
                        ? { background: ss.rowBg, borderLeft: `3px solid ${ss.text}` }
                        : { opacity: 0.65 }
                      return (
                        <tr key={a.id} style={rowStyle}>
                          <td>
                            <span style={{
                              fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 12,
                              background: ss.bg, color: ss.text, border: `1px solid ${ss.border}`,
                              textTransform: 'capitalize',
                            }}>
                              {a.severity === 'critical' && !a.acknowledged ? '🔴 ' : a.severity === 'warning' && !a.acknowledged ? '🟡 ' : ''}
                              {a.severity}
                            </span>
                          </td>
                          <td>
                            <span style={{ background:'#EEF2FF', color:'#4338CA', padding:'2px 8px', borderRadius:4, fontSize:12, fontWeight:600 }}>
                              {a.company_name}
                            </span>
                          </td>
                          <td style={{ textTransform:'capitalize', fontWeight:600 }}>{a.parameter}</td>
                          <td style={{ fontWeight:700, color: a.acknowledged ? '#374151' : ss.text }}>
                            {typeof a.value === 'number' ? a.value.toFixed(2) : a.value ?? '—'}
                          </td>
                          <td style={{ color:'#6B7280', fontSize:12 }}>{a.threshold ?? '—'}</td>
                          <td>
                            {!a.acknowledged ? (
                              <span style={{
                                fontSize: 12, fontWeight: 700,
                                color: a.minutes_open > 60 ? '#DC2626' : a.minutes_open > 15 ? '#D97706' : '#059669',
                              }}>
                                {fmtOpen(a.minutes_open)}
                              </span>
                            ) : <span style={{ color:'#9CA3AF', fontSize:12 }}>—</span>}
                          </td>
                          <td style={{ fontSize:12, color:'#6B7280', whiteSpace:'nowrap' }}>
                            {a.timestamp ? new Date(a.timestamp).toLocaleString() : '—'}
                          </td>
                          <td>
                            {a.acknowledged
                              ? <span style={{ color:'#059669', fontWeight:700, fontSize:13 }}>✓ Done</span>
                              : (
                                <button
                                  className="sa-btn sm primary"
                                  disabled={acking === a.id}
                                  onClick={() => handleAck(a.id)}
                                  style={{ fontSize: 11, padding: '3px 10px' }}
                                >
                                  {acking === a.id ? '…' : 'Ack'}
                                </button>
                              )
                            }
                          </td>
                        </tr>
                      )
                    })
              }
            </tbody>
          </table>
        </div>
      </div>
    </>
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
              <th>#</th><th>Admin</th><th>Company</th><th>Action</th><th>Status</th><th>Waiting</th><th>Submitted</th><th>Actions</th>
            </tr></thead>
            <tbody>
              {loading
                ? <tr><td colSpan={8} className="sa-empty"><Spinner /></td></tr>
                : rows.length === 0
                  ? <tr><td colSpan={8} className="sa-empty">No {filter} approvals.</td></tr>
                  : rows.map(r => {
                      const ageMs  = r.created_at ? Date.now() - new Date(r.created_at).getTime() : 0
                      const ageH   = ageMs / 3600000
                      const ageMin = Math.round(ageMs / 60000)
                      const slaColor = ageH > 24 ? '#DC2626' : ageH > 4 ? '#D97706' : '#059669'
                      const slaBg    = ageH > 24 ? '#FEE2E2' : ageH > 4 ? '#FEF3C7' : '#D1FAE5'
                      const slaLabel = ageMin < 60
                        ? `${ageMin}m`
                        : ageH < 24 ? `${Math.round(ageH)}h ${Math.round(ageMin % 60)}m`
                        : `${Math.round(ageH / 24)}d ${Math.round(ageH % 24)}h`
                      return (
                        <tr key={r.id} style={r.status === 'pending' && ageH > 24 ? { background:'#FFF5F5' } : {}}>
                          <td style={{ color:'#9CA3AF', fontSize:12 }}>#{r.id}</td>
                          <td><strong>{r.admin_name}</strong></td>
                          <td>{r.company_name || <span style={{ color:'#9CA3AF' }}>—</span>}</td>
                          <td style={{ fontFamily:'monospace', fontSize:12 }}>{r.action_type}</td>
                          <td><span style={{ fontWeight:700, color:statusColor(r.status), fontSize:12, textTransform:'uppercase' }}>{r.status}</span></td>
                          <td>
                            {r.status === 'pending' ? (
                              <span style={{ fontSize:12, fontWeight:700, color: slaColor, background: slaBg, padding:'2px 8px', borderRadius:8 }}>
                                {slaLabel} old{ageH > 24 ? ' ⚠' : ''}
                              </span>
                            ) : <span style={{ color:'#9CA3AF', fontSize:12 }}>—</span>}
                          </td>
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
                      )
                    })
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

  // Parameters sub-tab
  const [paramsData,    setParamsData]    = useState([])  // [{id, name, sampling_interval_seconds, parameters:[...]}]
  const [paramsLoading, setParamsLoading] = useState(false)
  const [paramEdit,     setParamEdit]     = useState(null) // {coId, param} being edited
  const [addParamCo,    setAddParamCo]    = useState(null) // company id for add-param form
  const [newParam,      setNewParam]      = useState({ name:'', unit:'', min_value:'', max_value:'' })
  const [samplingEdit,  setSamplingEdit]  = useState({})  // {[coId]: seconds_string}
  const [paramSaving,   setParamSaving]   = useState(false)

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3000) }

  const loadParams = useCallback(() => {
    setParamsLoading(true)
    get(`${CFG}/companies-params`)
      .then(setParamsData)
      .catch(e => setError(e.message))
      .finally(() => setParamsLoading(false))
  }, [])

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

  useEffect(() => { loadThresholds(); loadTemplates(); loadCompanies(); loadParams() }, [loadThresholds, loadTemplates, loadCompanies, loadParams])
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
    { id: 'parameters', label: 'Parameters'          },
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

      {/* ── Parameters ────────────────────────────────────────────────── */}
      {subTab === 'parameters' && (
        <div>
          {paramsLoading && <p style={{ color:'#9CA3AF', fontSize:13 }}>Loading…</p>}
          {!paramsLoading && paramsData.length === 0 && (
            <p style={{ color:'#9CA3AF', fontSize:13 }}>No companies found.</p>
          )}
          {paramsData.map(co => (
            <div key={co.id} className="sa-card" style={{ marginBottom: 18 }}>
              {/* Company header */}
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:14 }}>
                <h2 className="sa-card-title" style={{ margin:0 }}>{co.name}</h2>
                <div style={{ display:'flex', alignItems:'center', gap:10 }}>
                  <span style={{ fontSize:12, color:'#6B7280' }}>Sampling interval:</span>
                  <input
                    type="number" min={1} className="sa-input"
                    style={{ width:90, padding:'4px 8px', fontSize:13 }}
                    value={samplingEdit[co.id] ?? co.sampling_interval_seconds}
                    onChange={e => setSamplingEdit(s => ({ ...s, [co.id]: e.target.value }))}
                  />
                  <span style={{ fontSize:12, color:'#6B7280' }}>seconds</span>
                  <button className="sa-btn sm primary"
                    onClick={async () => {
                      const v = parseInt(samplingEdit[co.id] ?? co.sampling_interval_seconds, 10)
                      if (isNaN(v) || v < 1) { setError('Sampling interval must be ≥ 1 second'); return }
                      try {
                        await put(`${CFG}/companies/${co.id}/sampling`, { sampling_interval_seconds: v })
                        showToast(`Sampling interval for ${co.name} saved`)
                        loadParams()
                      } catch (e) { setError(e.message) }
                    }}>Save</button>
                </div>
              </div>

              {/* Parameters table */}
              <div className="sa-table-wrap">
                <table className="sa-table">
                  <thead>
                    <tr>
                      <th>Parameter</th><th>Unit</th><th>Min (Low)</th><th>Max (High)</th><th style={{ width:90 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {co.parameters.map((p, i) => {
                      const key = p.builtin ? `${co.id}-temp` : `${co.id}-${p.id}`
                      const isEditing = paramEdit?.key === key
                      return (
                        <tr key={key}>
                          <td>
                            <span style={{ fontWeight: p.builtin ? 600 : 400 }}>{p.name}</span>
                            {p.builtin && <span style={{ marginLeft:6, fontSize:11, color:'#6366F1', background:'#EEF2FF', borderRadius:4, padding:'1px 6px' }}>built-in</span>}
                          </td>
                          {isEditing ? (
                            <>
                              <td>
                                {!p.builtin
                                  ? <input type="text" className="sa-input" style={{ padding:'3px 6px', fontSize:12, width:70 }}
                                      placeholder="unit" value={paramEdit.unit}
                                      onChange={e => setParamEdit(d => ({ ...d, unit: e.target.value }))} />
                                  : <span style={{ fontSize:13, color:'#6B7280' }}>°C</span>
                                }
                              </td>
                              <td>
                                <input type="number" className="sa-input" style={{ padding:'3px 6px', fontSize:12 }}
                                  value={paramEdit.min} onChange={e => setParamEdit(d => ({ ...d, min: e.target.value }))} />
                              </td>
                              <td>
                                <input type="number" className="sa-input" style={{ padding:'3px 6px', fontSize:12 }}
                                  value={paramEdit.max} onChange={e => setParamEdit(d => ({ ...d, max: e.target.value }))} />
                              </td>
                              <td style={{ display:'flex', gap:4 }}>
                                <button className="sa-btn sm primary" disabled={paramSaving}
                                  onClick={async () => {
                                    setParamSaving(true)
                                    const mn = paramEdit.min === '' ? null : parseFloat(paramEdit.min)
                                    const mx = paramEdit.max === '' ? null : parseFloat(paramEdit.max)
                                    try {
                                      if (p.builtin) {
                                        await put(`${CFG}/companies/${co.id}/temperature`, { min_value: mn, max_value: mx })
                                      } else {
                                        await patch(`${CFG}/parameters/${p.id}`, { min_value: mn, max_value: mx, unit: paramEdit.unit || null })
                                      }
                                      showToast('Thresholds saved')
                                      setParamEdit(null)
                                      loadParams()
                                    } catch (e) { setError(e.message) }
                                    finally { setParamSaving(false) }
                                  }}>
                                  {paramSaving ? '…' : 'Save'}
                                </button>
                                <button className="sa-btn sm secondary" onClick={() => setParamEdit(null)}>✕</button>
                              </td>
                            </>
                          ) : (
                            <>
                              <td style={{ fontSize:13, color:'#6B7280' }}>{p.unit || '—'}</td>
                              <td style={{ fontVariantNumeric:'tabular-nums' }}>{p.min_value ?? '—'}</td>
                              <td style={{ fontVariantNumeric:'tabular-nums' }}>{p.max_value ?? '—'}</td>
                              <td style={{ display:'flex', gap:4 }}>
                                <button className="sa-btn sm secondary"
                                  onClick={() => setParamEdit({ key, min: p.min_value ?? '', max: p.max_value ?? '', unit: p.unit ?? '' })}>
                                  Edit
                                </button>
                                {!p.builtin && (
                                  <button className="sa-btn sm danger"
                                    onClick={async () => {
                                      if (!window.confirm(`Delete parameter "${p.name}" from ${co.name}?`)) return
                                      try {
                                        await del(`${CFG}/parameters/${p.id}`)
                                        showToast(`"${p.name}" deleted`)
                                        loadParams()
                                      } catch (e) { setError(e.message) }
                                    }}>Del</button>
                                )}
                              </td>
                            </>
                          )}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Add parameter inline form */}
              {addParamCo === co.id ? (
                <div style={{ marginTop:12, background:'#F9FAFB', borderRadius:8, padding:14, display:'flex', gap:10, flexWrap:'wrap', alignItems:'flex-end' }}>
                  <div className="sa-form-group" style={{ minWidth:130, flex:2, margin:0 }}>
                    <label style={{ fontSize:11 }}>Name *</label>
                    <input className="sa-input" style={{ fontSize:13 }} placeholder="e.g. pH"
                      value={newParam.name} onChange={e => setNewParam(p => ({ ...p, name: e.target.value }))} />
                  </div>
                  <div className="sa-form-group" style={{ minWidth:80, flex:1, margin:0 }}>
                    <label style={{ fontSize:11 }}>Unit</label>
                    <input className="sa-input" style={{ fontSize:13 }} placeholder="e.g. bar"
                      value={newParam.unit} onChange={e => setNewParam(p => ({ ...p, unit: e.target.value }))} />
                  </div>
                  <div className="sa-form-group" style={{ minWidth:90, flex:1, margin:0 }}>
                    <label style={{ fontSize:11 }}>Min</label>
                    <input type="number" className="sa-input" style={{ fontSize:13 }}
                      value={newParam.min_value} onChange={e => setNewParam(p => ({ ...p, min_value: e.target.value }))} />
                  </div>
                  <div className="sa-form-group" style={{ minWidth:90, flex:1, margin:0 }}>
                    <label style={{ fontSize:11 }}>Max</label>
                    <input type="number" className="sa-input" style={{ fontSize:13 }}
                      value={newParam.max_value} onChange={e => setNewParam(p => ({ ...p, max_value: e.target.value }))} />
                  </div>
                  <button className="sa-btn sm primary" disabled={paramSaving || !newParam.name.trim()}
                    onClick={async () => {
                      setParamSaving(true)
                      try {
                        await post(`${CFG}/companies/${co.id}/parameters/direct`, {
                          name: newParam.name.trim(),
                          unit: newParam.unit.trim(),
                          min_value: newParam.min_value === '' ? null : parseFloat(newParam.min_value),
                          max_value: newParam.max_value === '' ? null : parseFloat(newParam.max_value),
                        })
                        setNewParam({ name:'', unit:'', min_value:'', max_value:'' })
                        setAddParamCo(null)
                        showToast('Parameter added')
                        loadParams()
                      } catch (e) { setError(e.message) }
                      finally { setParamSaving(false) }
                    }}>
                    {paramSaving ? 'Adding…' : 'Add'}
                  </button>
                  <button className="sa-btn sm secondary" onClick={() => { setAddParamCo(null); setNewParam({ name:'', unit:'', min_value:'', max_value:'' }) }}>Cancel</button>
                </div>
              ) : (
                <button className="sa-btn sm secondary" style={{ marginTop:10 }}
                  onClick={() => { setAddParamCo(co.id); setNewParam({ name:'', unit:'', min_value:'', max_value:'' }) }}>
                  + Add Parameter
                </button>
              )}
            </div>
          ))}
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
  const [summary,   setSummary]   = useState(null)
  const [health,    setHealth]    = useState([])
  const [compare,   setCompare]   = useState([])
  const [anomalies, setAnomalies] = useState(null)
  const [trends,    setTrends]    = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')
  const [anomalyLog,setAnomalyLog]= useState([])
  const [showAnomalyLog, setShowAnomalyLog] = useState(false)

  // ── Company Analytics (drill-down) ───────────────────────────────────────
  const [companies,  setCompanies]  = useState([])
  const [selCompany, setSelCompany] = useState('')
  const [coRange,    setCoRange]    = useState('30d')
  const [coLoading,  setCoLoading]  = useState(false)
  const [coError,    setCoError]    = useState('')
  const [coCharts,   setCoCharts]   = useState({})

  // ── Fleet Comparison state (kept for drill-down) ─────────────────────────
  const [fleetRange,   setFleetRange]   = useState('30d')
  const [fleetLoading, setFleetLoading] = useState(false)
  const [fleetError,   setFleetError]   = useState('')
  const [fleetData,    setFleetData]    = useState({})

  const loadAll = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [s, h, cmp, anm, tnd, alog] = await Promise.all([
        get(`${ANL}/summary`),
        get(`${ANL}/companies/health`),
        get(`${ANL}/companies/compare`),
        get(`${ANL}/anomalies`).catch(() => null),
        get(`${ANL}/trends`).catch(() => null),
        get(`${SA}/anomalies`).catch(() => []),
      ])
      setSummary(s); setHealth(h); setCompare(cmp)
      setAnomalies(anm); setTrends(tnd)
      setAnomalyLog(Array.isArray(alog) ? alog : [])
      setCompanies(h.map(c => ({ id: c.company_id, name: c.company_name })))
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const loadCoCharts = useCallback(async (companyId, range) => {
    if (!companyId) return
    setCoLoading(true); setCoError('')
    const { from, to } = rangeToDates(range)
    const base = `${ANL}/companies/${companyId}`
    try {
      const [breach, heatmap, subResp, delivery, summary, sevDist, daily, hourly, weekly, ackTime] = await Promise.all([
        get(withDates(`${base}/charts/breach-frequency`, from, to)),
        get(withDates(`${base}/charts/alert-heatmap`, from, to)),
        get(withDates(`${base}/charts/subscriber-response`, from, to)),
        get(withDates(`${base}/charts/delivery-rates`, from, to)),
        get(withDates(`${base}/charts/summary-stats`, from, to)),
        get(withDates(`${base}/charts/severity-dist`, from, to)),
        get(withDates(`${base}/charts/daily-trend`, from, to)),
        get(withDates(`${base}/charts/hourly-pattern`, from, to)),
        get(withDates(`${base}/charts/weekly-avg`, from, to)),
        get(withDates(`${base}/charts/ack-time`, from, to)),
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
        get(withDates(`${ANL}/compare/parameter`, from, to)),
        get(withDates(`${ANL}/compare/daily-trend`, from, to)),
        get(withDates(`${ANL}/compare/breach-counts`, from, to)),
        get(`${ANL}/benchmarks`),
        get(`${ANL}/health-scores`),
      ])
      setFleetData({ param, dailyTrend, breachCounts, benchmarks, healthScores })
    } catch (e) { setFleetError(e.message) }
    finally { setFleetLoading(false) }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])
  useEffect(() => { if (selCompany) loadCoCharts(selCompany, coRange) }, [selCompany, coRange, loadCoCharts])

  const statusColor = (s) => s === 'healthy' ? '#22C55E' : s === 'warning' ? '#F59E0B' : s === 'critical' ? '#EF4444' : '#7F1D1D'
  const statusBg    = (s) => s === 'healthy' ? '#F0FDF4' : s === 'warning' ? '#FFFBEB' : s === 'critical' ? '#FEF2F2' : '#FFF1F2'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* ── Header bar ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: '#1F2937' }}>Analytics Overview</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="sa-btn secondary" style={{ fontSize: 12, padding: '5px 12px' }}
            onClick={() => setShowAnomalyLog(v => !v)}>
            Anomaly Log {anomalyLog.length > 0 && <span style={{ background:'#EF4444', color:'#fff', borderRadius:10, padding:'1px 6px', fontSize:10, marginLeft:4 }}>{anomalyLog.length}</span>}
          </button>
          <button className="sa-btn secondary" style={{ fontSize: 12, padding: '5px 12px' }}
            onClick={loadAll} disabled={loading}>{loading ? '…' : '↺ Refresh'}</button>
        </div>
      </div>

      {error && <Err msg={error} />}
      {loading && <div style={{ textAlign: 'center', padding: 30 }}><Spinner /></div>}

      {/* ══ KPI Strip ══ */}
      {!loading && summary && (
        <div className="sa-anl-kpi-strip">
          {[
            { label: 'Companies',      val: summary.companies,      color: '#6366F1' },
            { label: 'Open Alerts',    val: summary.open_alerts,    color: summary.open_alerts > 0 ? '#EF4444' : '#22C55E' },
            { label: 'Emergency Open', val: summary.emergency_open, color: summary.emergency_open > 0 ? '#7F1D1D' : '#22C55E' },
            { label: 'Alerts (24 h)',  val: summary.alerts_24h,     color: '#F59E0B' },
            { label: 'Total Readings', val: summary.total_readings, color: '#3B82F6' },
            { label: 'Active Admins',  val: summary.active_admins,  color: '#6B7280' },
          ].map(k => (
            <div key={k.label} className="sa-anl-kpi">
              <span className="sa-anl-kpi-val" style={{ color: k.color }}>{k.val}</span>
              <span className="sa-anl-kpi-label">{k.label}</span>
            </div>
          ))}
        </div>
      )}

      {/* ══ Row 1: Health Scores | Compare Table ══ */}
      {!loading && (
        <div style={{ display: 'grid', gridTemplateColumns: '42% 1fr', gap: 12 }}>
          <div className="sa-card" style={{ padding: '12px 14px' }}>
            <h2 className="sa-card-title">Company Health Scores</h2>
            {health.length === 0
              ? <p style={{ color: '#6B7280', fontSize: 13 }}>No companies.</p>
              : health.map(h => (
                  <div key={h.company_id} style={{ marginBottom: 10 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                      <span style={{ fontSize: 12, fontWeight: 600 }}>{h.company_name}</span>
                      <span style={{ fontSize: 11, fontWeight: 600, color: statusColor(h.status), textTransform: 'uppercase' }}>{h.status}</span>
                    </div>
                    <ScoreBar score={h.score} />
                    <div style={{ display: 'flex', gap: 10, marginTop: 2, fontSize: 11, color: '#6B7280' }}>
                      {h.emergency_unacked > 0 && <span style={{ color: '#7F1D1D' }}>🔴 {h.emergency_unacked}</span>}
                      {h.critical_unacked  > 0 && <span style={{ color: '#EF4444' }}>🟠 {h.critical_unacked}</span>}
                      {h.warning_unacked   > 0 && <span style={{ color: '#F59E0B' }}>🟡 {h.warning_unacked}</span>}
                      {h.alerts_last_hour  > 0 && <span>⚡ {h.alerts_last_hour}/hr</span>}
                    </div>
                  </div>
                ))
            }
          </div>

          <div className="sa-card" style={{ padding: '12px 14px' }}>
            <h2 className="sa-card-title">Company Alert Comparison</h2>
            <div style={{ overflowX: 'auto' }}>
              <table className="sa-table">
                <thead><tr>
                  <th>Company</th><th>Total</th><th>Open</th><th>24 h</th><th>Emergency</th><th>Ack %</th>
                </tr></thead>
                <tbody>
                  {compare.length === 0
                    ? <tr><td colSpan={6} className="sa-empty">No data.</td></tr>
                    : compare.map(r => (
                        <tr key={r.id}>
                          <td style={{ fontWeight: 600, fontSize: 12 }}>{r.name}</td>
                          <td style={{ fontSize: 12 }}>{r.total_alerts}</td>
                          <td style={{ color: r.open_alerts > 0 ? '#EF4444' : '#22C55E', fontWeight: 600, fontSize: 12 }}>{r.open_alerts}</td>
                          <td style={{ fontSize: 12 }}>{r.alerts_24h}</td>
                          <td style={{ color: r.emergency_count > 0 ? '#7F1D1D' : '#6B7280', fontWeight: r.emergency_count > 0 ? 700 : 400, fontSize: 12 }}>{r.emergency_count}</td>
                          <td>
                            <span style={{ fontSize: 12, fontWeight: 700, color: r.ack_rate_pct >= 80 ? '#22C55E' : r.ack_rate_pct >= 50 ? '#F59E0B' : '#EF4444' }}>
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
        </div>
      )}

      {/* ══ Row 2: Anomaly Detection | Trend Forecast ══ */}
      {!loading && (anomalies || (trends && !trends.error)) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {anomalies && (
            <div className="sa-card" style={{ padding: '12px 14px' }}>
              <h2 className="sa-card-title">Anomaly Detection</h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 8, marginBottom: 10 }}>
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Scanned</span>
                  <span className="sa-cfg-stat-val" style={{ fontSize: 20 }}>{anomalies.readings_scanned}</span>
                </div>
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Anomalies</span>
                  <span className="sa-cfg-stat-val" style={{ fontSize: 20, color: anomalies.anomalies.length > 0 ? '#EF4444' : '#22C55E' }}>
                    {anomalies.anomalies.length}
                  </span>
                </div>
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Mean Temp</span>
                  <span className="sa-cfg-stat-val info" style={{ fontSize: 18 }}>{anomalies.mean} °C</span>
                </div>
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Std Dev</span>
                  <span className="sa-cfg-stat-val" style={{ fontSize: 18 }}>{anomalies.std} °C</span>
                </div>
              </div>
              {anomalies.anomalies.length > 0 && (
                <div style={{ overflowX: 'auto', maxHeight: 110, overflowY: 'auto' }}>
                  <table className="sa-table">
                    <thead><tr><th>Temp</th><th>Z</th><th>Dev</th><th>Time</th></tr></thead>
                    <tbody>
                      {anomalies.anomalies.slice(0, 5).map(a => (
                        <tr key={a.reading_id}>
                          <td style={{ color: a.z_score >= 3 ? '#7F1D1D' : '#EF4444', fontWeight: 700, fontSize: 12 }}>{a.temperature}</td>
                          <td style={{ fontSize: 12 }}>{a.z_score}σ</td>
                          <td style={{ color: a.deviation > 0 ? '#EF4444' : '#3B82F6', fontSize: 12 }}>{a.deviation > 0 ? '+' : ''}{a.deviation}</td>
                          <td style={{ fontSize: 10, color: '#6B7280' }}>{a.timestamp}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {trends && !trends.error && (
            <div className="sa-card" style={{ padding: '12px 14px' }}>
              <h2 className="sa-card-title">Trend Forecast</h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 8, marginBottom: 10 }}>
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Direction</span>
                  <span className="sa-cfg-stat-val" style={{ fontSize: 20 }}><TrendArrow direction={trends.direction} /></span>
                </div>
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Slope</span>
                  <span className="sa-cfg-stat-val" style={{ fontSize: 18, color: trends.slope > 0 ? '#EF4444' : trends.slope < 0 ? '#3B82F6' : '#6B7280' }}>
                    {trends.slope > 0 ? '+' : ''}{trends.slope}
                  </span>
                </div>
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Latest</span>
                  <span className="sa-cfg-stat-val info" style={{ fontSize: 18 }}>{trends.latest} °C</span>
                </div>
                <div className="sa-cfg-stat">
                  <span className="sa-cfg-stat-label">Projected Next</span>
                  <span className="sa-cfg-stat-val" style={{ fontSize: 18, color: trends.projected_next >= trends.high_threshold ? '#EF4444' : trends.projected_next <= trends.low_threshold ? '#3B82F6' : '#22C55E' }}>
                    {trends.projected_next} °C
                  </span>
                </div>
              </div>
              <MiniSparkline values={trends.recent_values} />
              {trends.steps_to_high_threshold !== null && (
                <div className="sa-anl-predict-warn danger" style={{ fontSize: 11, marginTop: 6 }}>
                  ⚠ ~{trends.steps_to_high_threshold} readings until HIGH threshold ({trends.high_threshold} °C)
                </div>
              )}
              {trends.steps_to_low_threshold !== null && (
                <div className="sa-anl-predict-warn info" style={{ fontSize: 11, marginTop: 4 }}>
                  ℹ ~{trends.steps_to_low_threshold} readings until LOW threshold ({trends.low_threshold} °C)
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ══ Collapsible Anomaly Log ══ */}
      {!loading && showAnomalyLog && (
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
                <thead><tr>
                  <th>Type</th><th>Company</th><th>Description</th><th>Severity</th><th>Detected</th><th>Action</th>
                </tr></thead>
                <tbody>
                  {anomalyLog.map(a => (
                    <tr key={a.id}>
                      <td style={{ fontWeight: 600, textTransform: 'capitalize', whiteSpace: 'nowrap', fontSize: 12 }}>
                        {a.anomaly_type.replace(/_/g, ' ')}
                      </td>
                      <td style={{ fontSize: 12 }}>{a.company_name}</td>
                      <td style={{ fontSize: 12, maxWidth: 280 }}>{a.description}</td>
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

      {/* ══ Company Analytics Drill-Down ══ */}
      <div className="sa-card">
        <h2 className="sa-card-title">Company Analytics Drill-Down</h2>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
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
          <p style={{ color: '#6B7280', fontSize: 13, textAlign: 'center', padding: '20px 0' }}>
            Select a company above to view its analytics.
          </p>
        )}
        {coError && <Err msg={coError} />}
        {coLoading && <div style={{ textAlign: 'center', padding: 30 }}><Spinner /></div>}

        {selCompany && !coLoading && Object.keys(coCharts).length > 0 && (() => {
          const { breach, heatmap, subResp, delivery, summary: sum, sevDist, daily, hourly } = coCharts
          const COLORS = ['#7C3AED', '#EF4444', '#F59E0B', '#3B82F6', '#10B981']
          const tip = <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />

          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {sum && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px,1fr))', gap: 10 }}>
                  {[
                    { label: 'Total Alerts', val: sum.total_alerts,       color: '#6366F1' },
                    { label: 'Open',         val: sum.open,               color: sum.open > 0 ? '#EF4444' : '#22C55E' },
                    { label: 'Acked',        val: sum.acked,              color: '#22C55E' },
                    { label: 'Ack Rate',     val: `${sum.ack_rate_pct}%`, color: sum.ack_rate_pct >= 80 ? '#22C55E' : '#F59E0B' },
                    { label: 'Emergency',    val: sum.emergency_count,    color: sum.emergency_count > 0 ? '#7F1D1D' : '#6B7280' },
                    { label: 'Critical',     val: sum.critical_count,     color: sum.critical_count  > 0 ? '#EF4444' : '#6B7280' },
                  ].map(k => (
                    <div key={k.label} className="sa-cfg-stat">
                      <span className="sa-cfg-stat-label">{k.label}</span>
                      <span className="sa-cfg-stat-val" style={{ color: k.color, fontSize: 18 }}>{k.val}</span>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div className="sa-card">
                  <h2 className="sa-card-title">Daily Breach Frequency</h2>
                  {breach?.length > 0
                    ? <ResponsiveContainer width="100%" height={160}>
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

                <div className="sa-card">
                  <h2 className="sa-card-title">Alert Severity Distribution</h2>
                  {sevDist?.length > 0
                    ? <ResponsiveContainer width="100%" height={160}>
                        <PieChart>
                          <Pie data={sevDist} dataKey="count" nameKey="severity" cx="50%" cy="50%" outerRadius={60}
                            label={({ severity, percent }) => `${severity} ${(percent*100).toFixed(0)}%`} labelLine={false}>
                            {sevDist.map((_, i) => <Cell key={i} fill={['#7F1D1D','#EF4444','#F59E0B','#3B82F6'][i % 4]} />)}
                          </Pie>
                          <Tooltip />
                        </PieChart>
                      </ResponsiveContainer>
                    : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No alert data.</p>
                  }
                </div>

                <div className="sa-card">
                  <h2 className="sa-card-title">Daily Alert Trend</h2>
                  {daily?.length > 0
                    ? <ResponsiveContainer width="100%" height={160}>
                        <LineChart data={daily}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                          <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                          <YAxis tick={{ fontSize: 10 }} />
                          {tip}<Legend />
                          <Line type="monotone" dataKey="open"  stroke="#EF4444" dot={false} strokeWidth={2} />
                          <Line type="monotone" dataKey="acked" stroke="#22C55E" dot={false} strokeWidth={2} />
                        </LineChart>
                      </ResponsiveContainer>
                    : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No daily data.</p>
                  }
                </div>

                <div className="sa-card">
                  <h2 className="sa-card-title">Hourly Alert Pattern</h2>
                  {hourly?.length > 0
                    ? <ResponsiveContainer width="100%" height={160}>
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
              </div>

              <div className="sa-card">
                <h2 className="sa-card-title">Alert Heatmap (Hour × Day)</h2>
                {heatmap?.grid
                  ? <AlertHeatmapSA grid={heatmap.grid} days={heatmap.days} />
                  : <p style={{ color: '#9CA3AF', fontSize: 13 }}>No heatmap data.</p>
                }
              </div>

              {subResp?.length > 0 && (
                <div className="sa-card">
                  <h2 className="sa-card-title">Subscriber Response Rates</h2>
                  <div style={{ overflowX: 'auto' }}>
                    <table className="sa-table">
                      <thead><tr>
                        <th>Subscriber</th><th>Channel</th><th>Total</th><th>Acked</th><th>Ack Rate</th><th>Avg (min)</th>
                      </tr></thead>
                      <tbody>
                        {subResp.map((r, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 600 }}>{r.name}</td>
                            <td>{r.channel}</td>
                            <td>{r.total_alerts}</td>
                            <td>{r.acked}</td>
                            <td>
                              <span style={{ fontWeight: 700, color: r.ack_rate_pct >= 80 ? '#22C55E' : r.ack_rate_pct >= 50 ? '#F59E0B' : '#EF4444' }}>
                                {r.ack_rate_pct ?? '—'}%
                              </span>
                            </td>
                            <td style={{ color: '#6B7280' }}>{r.avg_ack_minutes ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {delivery?.channels?.length > 0 && (
                <div className="sa-card">
                  <h2 className="sa-card-title">Channel Delivery Rates</h2>
                  <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', paddingTop: 8 }}>
                    {delivery.channels.map((ch, i) => (
                      <div key={i} style={{ textAlign: 'center', minWidth: 90 }}>
                        <div style={{ fontSize: 26, fontWeight: 800, color: ch.success_rate >= 90 ? '#22C55E' : ch.success_rate >= 70 ? '#F59E0B' : '#EF4444' }}>
                          {ch.success_rate}%
                        </div>
                        <div style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>{ch.channel}</div>
                        <div style={{ fontSize: 11, color: '#9CA3AF' }}>{ch.delivered}/{ch.total} sent</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })()}
      </div>

    </div>
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
  const [subTab,     setSubTab]     = useState('classic')
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
      {/* Sub-tab switcher */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {[
          { id: 'classic',  label: 'Summary & Log' },
          { id: 'advanced', label: '🔍 Advanced Explorer' },
        ].map(t => (
          <button key={t.id}
            className={`sa-btn ${subTab === t.id ? 'primary' : 'secondary'}`}
            onClick={() => setSubTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {subTab === 'advanced' && <AdvancedAuditExplorer />}

      {subTab === 'classic' && <>
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
      </>}
    </div>
  )
}


// ─── Tier 3: Advanced Audit Explorer ─────────────────────────────────────────

function AdvancedAuditExplorer() {
  const [rows,      setRows]      = useState([])
  const [total,     setTotal]     = useState(0)
  const [pages,     setPages]     = useState(1)
  const [page,      setPage]      = useState(1)
  const [cats,      setCats]      = useState([])
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')

  // Filters
  const [search,    setSearch]    = useState('')
  const [company,   setCompany]   = useState('')
  const [category,  setCategory]  = useState('')
  const [severity,  setSeverity]  = useState('')
  const [dateFrom,  setDateFrom]  = useState('')
  const [dateTo,    setDateTo]    = useState('')
  const [companies, setCompanies] = useState([])

  useEffect(() => {
    get(`${SA}/companies`).then(c => setCompanies(Array.isArray(c) ? c : [])).catch(() => {})
  }, [])

  const load = useCallback(async (p = 1) => {
    setLoading(true); setError('')
    try {
      const params = new URLSearchParams({ page: p, limit: 50 })
      if (search)   params.set('search',     search)
      if (company)  params.set('company_id', company)
      if (category) params.set('category',   category)
      if (severity) params.set('severity',   severity)
      if (dateFrom) params.set('date_from',  dateFrom)
      if (dateTo)   params.set('date_to',    dateTo)
      const d = await get(`${SA}/audit?${params}`)
      setRows(d.rows || [])
      setTotal(d.total || 0)
      setPages(d.pages || 1)
      setPage(p)
      setCats(d.categories || [])
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [search, company, category, severity, dateFrom, dateTo])

  useEffect(() => { load(1) }, [load])

  const SEV = {
    critical: { bg: '#FEF2F2', text: '#DC2626' },
    warning:  { bg: '#FFFBEB', text: '#D97706' },
    high:     { bg: '#FEF2F2', text: '#DC2626' },
    medium:   { bg: '#FFFBEB', text: '#D97706' },
    low:      { bg: '#F0FDF4', text: '#059669' },
    info:     { bg: '#EFF6FF', text: '#2563EB' },
  }

  return (
    <div className="sa-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <h2 className="sa-card-title" style={{ margin: 0 }}>
          Advanced Audit Explorer {total > 0 && <span style={{ color: '#6B7280', fontWeight: 400, fontSize: 13 }}>({total} entries)</span>}
        </h2>
        <button className="sa-btn sm secondary"
          onClick={() => downloadCSV(`${SA}/export/audit.csv${company ? `?company_id=${company}` : ''}`, 'audit.csv')}>
          ⬇ Export CSV
        </button>
      </div>

      {/* Filter row */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14, alignItems: 'center' }}>
        <input className="sa-input" placeholder="Search actions…" value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && load(1)}
          style={{ maxWidth: 220 }} />
        <select className="sa-input" value={company} onChange={e => setCompany(e.target.value)} style={{ maxWidth: 160 }}>
          <option value="">All companies</option>
          {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className="sa-input" value={category} onChange={e => setCategory(e.target.value)} style={{ maxWidth: 140 }}>
          <option value="">All categories</option>
          {cats.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="sa-input" value={severity} onChange={e => setSeverity(e.target.value)} style={{ maxWidth: 130 }}>
          <option value="">All severities</option>
          {['critical','high','medium','low','info'].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <input type="date" className="sa-input" value={dateFrom} onChange={e => setDateFrom(e.target.value)} style={{ maxWidth: 145 }} />
        <span style={{ color: '#9CA3AF', fontSize: 12 }}>→</span>
        <input type="date" className="sa-input" value={dateTo}   onChange={e => setDateTo(e.target.value)}   style={{ maxWidth: 145 }} />
        <button className="sa-btn sm primary" onClick={() => load(1)}>Search</button>
        <button className="sa-btn sm secondary" onClick={() => {
          setSearch(''); setCompany(''); setCategory(''); setSeverity('')
          setDateFrom(''); setDateTo('')
        }}>Clear</button>
      </div>

      {error && <Err msg={error} />}

      {loading ? <Spinner /> : (
        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead><tr>
              <th>Time</th><th>Severity</th><th>Category</th><th>Action</th>
              <th>Admin</th><th>Company</th><th>IP</th><th>Details</th>
            </tr></thead>
            <tbody>
              {rows.length === 0
                ? <tr><td colSpan={8} className="sa-empty">No entries found</td></tr>
                : rows.map(r => {
                    const sc = SEV[r.severity] || SEV.info
                    return (
                      <tr key={r.id}>
                        <td style={{ fontFamily: 'monospace', fontSize: 11, whiteSpace: 'nowrap' }}>
                          {r.created_at ? new Date(r.created_at).toLocaleString('en-IN', { hour12: false }) : '—'}
                        </td>
                        <td>
                          <span style={{ background: sc.bg, color: sc.text, padding: '1px 6px', borderRadius: 8, fontSize: 10, fontWeight: 700 }}>
                            {r.severity}
                          </span>
                        </td>
                        <td style={{ fontSize: 12, color: CAT_COLORS[r.category] || '#6B7280', fontWeight: 600 }}>{r.category}</td>
                        <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{r.action}</td>
                        <td style={{ fontSize: 12 }}>{r.admin_name || '—'}</td>
                        <td style={{ fontSize: 12 }}>{r.company_name || '—'}</td>
                        <td style={{ fontFamily: 'monospace', fontSize: 11, color: '#6B7280' }}>{r.ip_address || '—'}</td>
                        <td style={{ fontSize: 11, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          title={r.details || ''}>{r.details || '—'}</td>
                      </tr>
                    )
                  })
              }
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {pages > 1 && (
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 14, alignItems: 'center', fontSize: 13 }}>
          <button className="sa-btn secondary" disabled={page <= 1} onClick={() => load(page - 1)}>← Prev</button>
          <span style={{ color: '#6B7280' }}>Page {page} of {pages}</span>
          <button className="sa-btn secondary" disabled={page >= pages} onClick={() => load(page + 1)}>Next →</button>
        </div>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════════
// TIER 4 FRONTEND — Operations Automation & Intelligence
// ═══════════════════════════════════════════════════════════════════════════════

// ─── Tier 4 helpers ───────────────────────────────────────────────────────────

const INC_STATUS = {
  open:          { bg: '#FEF2F2', text: '#DC2626', label: 'Open'          },
  investigating: { bg: '#FFF7ED', text: '#EA580C', label: 'Investigating' },
  resolved:      { bg: '#F0FDF4', text: '#16A34A', label: 'Resolved'      },
  closed:        { bg: '#F9FAFB', text: '#6B7280', label: 'Closed'        },
}

const INC_SEV = {
  critical: { bg: '#FEF2F2', text: '#DC2626' },
  high:     { bg: '#FFF4ED', text: '#EA580C' },
  medium:   { bg: '#FFFBEB', text: '#D97706' },
  low:      { bg: '#F0FDF4', text: '#16A34A' },
}

const SLA_GRADE = {
  A: { bg: '#F0FDF4', text: '#15803D', border: '#86EFAC' },
  B: { bg: '#EFF6FF', text: '#1D4ED8', border: '#93C5FD' },
  C: { bg: '#FFFBEB', text: '#92400E', border: '#FCD34D' },
  D: { bg: '#FFF4ED', text: '#C2410C', border: '#FDBA74' },
  F: { bg: '#FEF2F2', text: '#B91C1C', border: '#FCA5A5' },
}

function IncStatusBadge({ status }) {
  const s = INC_STATUS[status] || INC_STATUS.open
  return (
    <span style={{ background: s.bg, color: s.text, borderRadius: 6, padding: '2px 8px', fontSize: 11, fontWeight: 700 }}>
      {s.label}
    </span>
  )
}

function SlaGradeBadge({ grade }) {
  const g = SLA_GRADE[grade] || SLA_GRADE.F
  return (
    <span style={{ background: g.bg, color: g.text, border: `1px solid ${g.border}`, borderRadius: 6, padding: '3px 10px', fontSize: 13, fontWeight: 800 }}>
      {grade}
    </span>
  )
}


// ─── Tier 4: Maintenance Windows ──────────────────────────────────────────────

function MaintenanceTab() {
  const [windows,   setWindows]   = useState([])
  const [companies, setCompanies] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [showForm,  setShowForm]  = useState(false)
  const [toast,     setToast]     = useState('')
  const [applying,  setApplying]  = useState(false)
  const [applyResult, setApplyResult] = useState(null)
  const [showPast,  setShowPast]  = useState(false)

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 4000) }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [w, c] = await Promise.all([
        get(`${SA}/maintenance-windows?include_past=${showPast}`),
        get(`${SA}/companies`),
      ])
      setWindows(Array.isArray(w) ? w : [])
      setCompanies(Array.isArray(c) ? c : [])
    } catch { /* silent */ }
    finally { setLoading(false) }
  }, [showPast])

  useEffect(() => { load() }, [load])

  const handleCancel = async (w) => {
    if (!window.confirm(`Cancel maintenance window for ${w.company_name}?`)) return
    try {
      await del(`${SA}/maintenance-windows/${w.id}`)
      showToast('Window cancelled')
      load()
    } catch (e) { alert(e.message) }
  }

  const handleApply = async () => {
    setApplying(true); setApplyResult(null)
    try {
      const res = await post(`${SA}/maintenance-windows/apply`, {})
      setApplyResult(res)
      showToast(`Applied: ${res.entered_maintenance.length} entered, ${res.exited_maintenance.length} exited`)
      load()
    } catch (e) { alert(e.message) }
    finally { setApplying(false) }
  }

  const active   = windows.filter(w => w.window_status === 'active')
  const upcoming = windows.filter(w => w.window_status === 'upcoming')
  const expired  = windows.filter(w => w.window_status === 'expired')

  const STATUS_STYLE = {
    active:   { bg: '#FFF7ED', border: '#FDBA74', dot: '#F97316', label: 'ACTIVE'   },
    upcoming: { bg: '#EFF6FF', border: '#93C5FD', dot: '#3B82F6', label: 'UPCOMING' },
    expired:  { bg: '#F9FAFB', border: '#E5E7EB', dot: '#9CA3AF', label: 'EXPIRED'  },
  }

  const WindowCard = ({ w }) => {
    const st = STATUS_STYLE[w.window_status] || STATUS_STYLE.expired
    return (
      <div style={{ background: st.bg, border: `1px solid ${st.border}`, borderRadius: 10, padding: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: st.dot, display: 'inline-block', ...(w.window_status === 'active' ? { animation: 'pulse 1.5s infinite' } : {}) }} />
            <span style={{ fontWeight: 800, fontSize: 14, color: '#1F2937' }}>{w.company_name}</span>
            <span style={{ fontSize: 10, fontWeight: 700, background: st.dot, color: '#fff', borderRadius: 4, padding: '1px 6px' }}>{st.label}</span>
          </div>
          {w.reason && <p style={{ fontSize: 12, color: '#6B7280', margin: '0 0 6px' }}>{w.reason}</p>}
          <div style={{ fontSize: 12, color: '#374151', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <span>Start: <strong>{new Date(w.start_at).toLocaleString()}</strong></span>
            <span>End: <strong>{new Date(w.end_at).toLocaleString()}</strong></span>
            <span style={{ color: '#9CA3AF' }}>by {w.created_by_name || 'system'}</span>
          </div>
        </div>
        {w.window_status !== 'expired' && (
          <button className="sa-btn sm danger" onClick={() => handleCancel(w)}>Cancel</button>
        )}
      </div>
    )
  }

  return (
    <>
      {toast && <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46', padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>}

      {/* Header */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16, flexWrap:'wrap', gap:10 }}>
        <div>
          <h2 style={{ margin:0, fontSize:18, fontWeight:800, color:'#1F2937' }}>Maintenance Windows</h2>
          <p style={{ margin:'4px 0 0', fontSize:13, color:'#6B7280' }}>Schedule alert suppression windows per company. Alerts fire as normal outside windows.</p>
        </div>
        <div style={{ display:'flex', gap:8 }}>
          <button className="sa-btn secondary" onClick={handleApply} disabled={applying}>
            {applying ? '…' : '▶ Sync Now'}
          </button>
          <button className="sa-btn secondary sm"
            onClick={() => downloadCSV(`${SA}/export/maintenance.csv`, 'maintenance.csv')}>
            ⬇ Export
          </button>
          <button className="sa-btn primary" onClick={() => setShowForm(true)}>+ Schedule Window</button>
        </div>
      </div>

      {/* Apply result */}
      {applyResult && (
        <div className="sa-card" style={{ marginBottom:12, background:'#F0FDF4', border:'1px solid #86EFAC' }}>
          <div style={{ fontWeight:700, color:'#15803D', marginBottom:6 }}>Sync complete</div>
          {applyResult.entered_maintenance.length > 0 && (
            <div style={{ fontSize:13, color:'#374151' }}>
              Entered maintenance: <strong>{applyResult.entered_maintenance.join(', ')}</strong>
            </div>
          )}
          {applyResult.exited_maintenance.length > 0 && (
            <div style={{ fontSize:13, color:'#374151' }}>
              Exited maintenance: <strong>{applyResult.exited_maintenance.join(', ')}</strong>
            </div>
          )}
          {applyResult.entered_maintenance.length === 0 && applyResult.exited_maintenance.length === 0 && (
            <div style={{ fontSize:13, color:'#6B7280' }}>No changes — all companies already in correct state.</div>
          )}
        </div>
      )}

      {/* Summary strip */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12, marginBottom:20 }}>
        {[
          { label:'Active Now',  val: active.length,   color:'#F97316' },
          { label:'Upcoming',    val: upcoming.length,  color:'#3B82F6' },
          { label:'Total Shown', val: windows.length,   color:'#6B7280' },
        ].map(s => (
          <div key={s.label} className="sa-stat" style={{ borderLeft:`4px solid ${s.color}` }}>
            <div className="sa-stat-label">{s.label}</div>
            <div className="sa-stat-value" style={{ color:s.color }}>{s.val}</div>
          </div>
        ))}
      </div>

      {loading ? <Spinner /> : (
        <>
          {active.length > 0 && (
            <div style={{ marginBottom:20 }}>
              <div style={{ fontSize:12, fontWeight:700, color:'#F97316', textTransform:'uppercase', letterSpacing:'0.05em', marginBottom:8 }}>Active Now</div>
              <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                {active.map(w => <WindowCard key={w.id} w={w} />)}
              </div>
            </div>
          )}
          {upcoming.length > 0 && (
            <div style={{ marginBottom:20 }}>
              <div style={{ fontSize:12, fontWeight:700, color:'#3B82F6', textTransform:'uppercase', letterSpacing:'0.05em', marginBottom:8 }}>Upcoming</div>
              <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                {upcoming.map(w => <WindowCard key={w.id} w={w} />)}
              </div>
            </div>
          )}
          {active.length === 0 && upcoming.length === 0 && (
            <div style={{ textAlign:'center', padding:40, color:'#9CA3AF', fontSize:14 }}>
              No active or upcoming maintenance windows.
            </div>
          )}
          {/* Past toggle */}
          <div style={{ marginTop:12 }}>
            <button className="sa-btn sm secondary" onClick={() => setShowPast(p => !p)}>
              {showPast ? '▲ Hide past windows' : '▼ Show past/expired windows'}
            </button>
            {showPast && expired.length > 0 && (
              <div style={{ marginTop:12, display:'flex', flexDirection:'column', gap:8, opacity:0.7 }}>
                {expired.map(w => <WindowCard key={w.id} w={w} />)}
              </div>
            )}
          </div>
        </>
      )}

      {showForm && (
        <ScheduleWindowModal companies={companies} onClose={() => setShowForm(false)} onSaved={load} />
      )}
    </>
  )
}

function ScheduleWindowModal({ companies, onClose, onSaved }) {
  const [companyId, setCompanyId] = useState('')
  const [startAt,   setStartAt]   = useState('')
  const [endAt,     setEndAt]     = useState('')
  const [reason,    setReason]    = useState('')
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')

  // Default start = now, end = 2h from now (local ISO)
  useEffect(() => {
    const now = new Date(); now.setSeconds(0, 0)
    const end = new Date(now.getTime() + 2 * 60 * 60 * 1000)
    const toLocal = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
    setStartAt(toLocal(now))
    setEndAt(toLocal(end))
  }, [])

  const handleSave = async () => {
    if (!companyId) return setError('Select a company')
    if (!startAt || !endAt) return setError('Set start and end times')
    setLoading(true); setError('')
    try {
      await post(`${SA}/maintenance-windows`, {
        company_id: Number(companyId),
        start_at:   new Date(startAt).toISOString(),
        end_at:     new Date(endAt).toISOString(),
        reason:     reason.trim() || null,
      })
      onSaved?.()
      onClose()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <Modal title="Schedule Maintenance Window" onClose={onClose}
      footer={
        <div style={{ display:'flex', gap:8 }}>
          <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
          <button className="sa-btn primary" onClick={handleSave} disabled={loading}>
            {loading ? 'Scheduling…' : 'Schedule Window'}
          </button>
        </div>
      }
    >
      <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
        {error && <Err msg={error} />}
        <div>
          <label className="sa-label">Company *</label>
          <select className="sa-input" value={companyId} onChange={e => setCompanyId(e.target.value)}>
            <option value="">Select company…</option>
            {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
          <div>
            <label className="sa-label">Start *</label>
            <input className="sa-input" type="datetime-local" value={startAt} onChange={e => setStartAt(e.target.value)} />
          </div>
          <div>
            <label className="sa-label">End *</label>
            <input className="sa-input" type="datetime-local" value={endAt} onChange={e => setEndAt(e.target.value)} />
          </div>
        </div>
        <div>
          <label className="sa-label">Reason (optional)</label>
          <input className="sa-input" value={reason} onChange={e => setReason(e.target.value)} placeholder="Planned firmware upgrade, network maintenance…" />
        </div>
        <div style={{ background:'#FFF7ED', border:'1px solid #FED7AA', borderRadius:8, padding:'8px 12px', fontSize:12, color:'#92400E' }}>
          ⚠ During the window the company will be in Maintenance mode — alerts are generated but suppressed from escalation. Click <strong>Sync Now</strong> on the main page to activate windows immediately.
        </div>
      </div>
    </Modal>
  )
}


// ─── Tier 4: Incident Management ─────────────────────────────────────────────

function IncidentsTab() {
  const [incidents,  setIncidents]  = useState([])
  const [companies,  setCompanies]  = useState([])
  const [admins,     setAdmins]     = useState([])
  const [loading,    setLoading]    = useState(true)
  const [showForm,   setShowForm]   = useState(false)
  const [detailId,   setDetailId]   = useState(null)
  const [toast,      setToast]      = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [sevFilter,    setSevFilter]    = useState('')

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 4000) }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: 100 })
      if (statusFilter) params.set('status', statusFilter)
      if (sevFilter)    params.set('severity', sevFilter)
      const [inc, co, adm] = await Promise.all([
        get(`${SA}/incidents?${params}`),
        get(`${SA}/companies`),
        get(`${SA}/admins`),
      ])
      setIncidents(Array.isArray(inc) ? inc : [])
      setCompanies(Array.isArray(co)  ? co  : [])
      setAdmins(Array.isArray(adm)    ? adm : [])
    } catch { /* silent */ }
    finally { setLoading(false) }
  }, [statusFilter, sevFilter])

  useEffect(() => { load() }, [load])

  const quickStatus = async (inc, newStatus) => {
    try {
      await patch(`${SA}/incidents/${inc.id}`, { status: newStatus })
      showToast(`#${inc.id} marked ${newStatus}`)
      load()
    } catch (e) { alert(e.message) }
  }

  const handleDelete = async (inc) => {
    if (!window.confirm(`Delete incident "${inc.title}"?`)) return
    try {
      await del(`${SA}/incidents/${inc.id}`)
      showToast('Incident deleted')
      load()
    } catch (e) { alert(e.message) }
  }

  if (detailId !== null) {
    return <IncidentDetailView incidentId={detailId} onBack={() => setDetailId(null)} onRefresh={load} admins={admins} />
  }

  const openCount = incidents.filter(i => i.status === 'open').length
  const invCount  = incidents.filter(i => i.status === 'investigating').length

  return (
    <>
      {toast && <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46', padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>}

      {/* Command strip */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12, marginBottom:16 }}>
        {[
          { label:'Open',          val: openCount,            color:'#DC2626' },
          { label:'Investigating', val: invCount,             color:'#EA580C' },
          { label:'Total',         val: incidents.length,     color:'#6B7280' },
          { label:'Resolved',      val: incidents.filter(i => i.status === 'resolved').length, color:'#16A34A' },
        ].map(s => (
          <div key={s.label} className="sa-stat" style={{ borderLeft:`4px solid ${s.color}` }}>
            <div className="sa-stat-label">{s.label}</div>
            <div className="sa-stat-value" style={{ color:s.color }}>{s.val}</div>
          </div>
        ))}
      </div>

      <div className="sa-card">
        {/* Filters */}
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16, flexWrap:'wrap', gap:10 }}>
          <h2 className="sa-card-title" style={{ margin:0 }}>Incidents ({incidents.length})</h2>
          <div style={{ display:'flex', gap:8, flexWrap:'wrap', alignItems:'center' }}>
            <select className="sa-input" value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ maxWidth:140 }}>
              <option value="">All statuses</option>
              {Object.entries(INC_STATUS).map(([k,v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
            <select className="sa-input" value={sevFilter} onChange={e => setSevFilter(e.target.value)} style={{ maxWidth:130 }}>
              <option value="">All severities</option>
              {Object.keys(INC_SEV).map(k => <option key={k} value={k}>{k}</option>)}
            </select>
            <button className="sa-btn sm secondary"
              onClick={() => downloadCSV(`${SA}/export/incidents.csv`, 'incidents.csv')}>
              ⬇ Export
            </button>
            <button className="sa-btn primary" onClick={() => setShowForm(true)}>+ New Incident</button>
          </div>
        </div>

        {loading ? <Spinner /> : incidents.length === 0 ? (
          <div style={{ textAlign:'center', padding:40, color:'#9CA3AF' }}>No incidents found.</div>
        ) : (
          <div className="sa-table-wrap">
            <table className="sa-table">
              <thead><tr>
                <th>#</th><th>Severity</th><th>Status</th><th>Title</th>
                <th>Company</th><th>Assignee</th><th>Alerts</th><th>Notes</th><th>Created</th><th>Actions</th>
              </tr></thead>
              <tbody>
                {incidents.map(inc => {
                  const sev = INC_SEV[inc.severity] || INC_SEV.medium
                  return (
                    <tr key={inc.id} style={{ background: inc.status === 'open' ? '#FFFBFB' : undefined }}>
                      <td style={{ fontFamily:'monospace', fontSize:12, color:'#6B7280' }}>#{inc.id}</td>
                      <td>
                        <span style={{ background:sev.bg, color:sev.text, padding:'2px 7px', borderRadius:6, fontSize:11, fontWeight:700 }}>
                          {inc.severity}
                        </span>
                      </td>
                      <td><IncStatusBadge status={inc.status} /></td>
                      <td>
                        <button
                          style={{ background:'none', border:'none', cursor:'pointer', padding:0, fontWeight:700, fontSize:13, color:'#1D4ED8', textAlign:'left', textDecoration:'underline', textUnderlineOffset:3 }}
                          onClick={() => setDetailId(inc.id)}>
                          {inc.title}
                        </button>
                      </td>
                      <td style={{ fontSize:12 }}>{inc.company_name || '—'}</td>
                      <td style={{ fontSize:12 }}>{inc.assignee_name || <span style={{ color:'#9CA3AF' }}>unassigned</span>}</td>
                      <td style={{ textAlign:'center', fontSize:12 }}>{inc.alert_count}</td>
                      <td style={{ textAlign:'center', fontSize:12 }}>{inc.note_count}</td>
                      <td style={{ fontSize:11, color:'#6B7280', whiteSpace:'nowrap' }}>
                        {inc.created_at ? new Date(inc.created_at).toLocaleDateString() : '—'}
                      </td>
                      <td>
                        <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
                          {inc.status === 'open' && (
                            <button className="sa-btn sm secondary" onClick={() => quickStatus(inc, 'investigating')}>Investigate</button>
                          )}
                          {inc.status === 'investigating' && (
                            <button className="sa-btn sm secondary" onClick={() => quickStatus(inc, 'resolved')}>Resolve</button>
                          )}
                          {inc.status !== 'closed' && inc.status !== 'open' && (
                            <button className="sa-btn sm secondary" onClick={() => quickStatus(inc, 'closed')}>Close</button>
                          )}
                          <button className="sa-btn sm danger" onClick={() => handleDelete(inc)}>✕</button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showForm && (
        <NewIncidentModal companies={companies} admins={admins}
          onClose={() => setShowForm(false)} onSaved={load} />
      )}
    </>
  )
}

function IncidentDetailView({ incidentId, onBack, onRefresh, admins }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [note,    setNote]    = useState('')
  const [addingNote, setAddingNote] = useState(false)
  const [tab,     setTab]     = useState('timeline')

  const load = useCallback(async () => {
    setLoading(true)
    try { setData(await get(`${SA}/incidents/${incidentId}`)) }
    catch { /* silent */ }
    finally { setLoading(false) }
  }, [incidentId])

  useEffect(() => { load() }, [load])

  const submitNote = async () => {
    if (!note.trim()) return
    setAddingNote(true)
    try {
      await post(`${SA}/incidents/${incidentId}/notes`, { note: note.trim() })
      setNote('')
      load()
      onRefresh?.()
    } catch (e) { alert(e.message) }
    finally { setAddingNote(false) }
  }

  const quickUpdate = async (fields) => {
    try {
      await patch(`${SA}/incidents/${incidentId}`, fields)
      load(); onRefresh?.()
    } catch (e) { alert(e.message) }
  }

  if (loading) return <><button className="sa-back-btn" onClick={onBack}>← Back to Incidents</button><Spinner /></>
  if (!data)   return <><button className="sa-back-btn" onClick={onBack}>← Back to Incidents</button><Err msg="Failed to load" /></>

  const sev = INC_SEV[data.severity] || INC_SEV.medium

  return (
    <>
      <button className="sa-back-btn" onClick={onBack}>← Back to Incidents</button>

      {/* Hero header */}
      <div className="sa-card" style={{ marginBottom:16 }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:16, flexWrap:'wrap' }}>
          <div style={{ flex:1 }}>
            <div style={{ display:'flex', gap:10, alignItems:'center', marginBottom:8, flexWrap:'wrap' }}>
              <span style={{ fontSize:12, color:'#9CA3AF', fontFamily:'monospace' }}>INC-{data.id}</span>
              <span style={{ background:sev.bg, color:sev.text, padding:'2px 8px', borderRadius:6, fontSize:11, fontWeight:700 }}>{data.severity}</span>
              <IncStatusBadge status={data.status} />
            </div>
            <h2 style={{ margin:'0 0 6px', fontSize:20, fontWeight:800, color:'#1F2937' }}>{data.title}</h2>
            {data.description && <p style={{ margin:0, fontSize:13, color:'#6B7280' }}>{data.description}</p>}
          </div>
          {/* Quick actions */}
          <div style={{ display:'flex', flexDirection:'column', gap:8, alignItems:'flex-end', flexShrink:0 }}>
            <div style={{ display:'flex', gap:6 }}>
              {data.status === 'open'          && <button className="sa-btn sm secondary" onClick={() => quickUpdate({ status:'investigating' })}>→ Investigate</button>}
              {data.status === 'investigating' && <button className="sa-btn sm primary"   onClick={() => quickUpdate({ status:'resolved' })}>✓ Resolve</button>}
              {['open','investigating'].includes(data.status) && <button className="sa-btn sm secondary" onClick={() => quickUpdate({ status:'closed' })}>Close</button>}
            </div>
            <div style={{ display:'flex', gap:6 }}>
              <select className="sa-input" style={{ fontSize:12, padding:'4px 8px', width:160 }}
                value={data.assignee_id || ''}
                onChange={e => quickUpdate({ assignee_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">Unassigned</option>
                {admins.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            <div style={{ fontSize:12, color:'#9CA3AF' }}>
              {data.company_name && <span>Company: <strong style={{ color:'#374151' }}>{data.company_name}</strong></span>}
            </div>
          </div>
        </div>
      </div>

      {/* Sub-tabs */}
      <div style={{ display:'flex', gap:8, marginBottom:16 }}>
        {[
          { id:'timeline', label:`Timeline (${data.notes?.length || 0})` },
          { id:'alerts',   label:`Linked Alerts (${data.linked_alerts?.length || 0})` },
        ].map(t => (
          <button key={t.id}
            className={`sa-btn ${tab === t.id ? 'primary' : 'secondary'}`}
            onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'timeline' && (
        <div className="sa-card">
          {/* Notes timeline */}
          {data.notes?.length === 0 && (
            <p style={{ color:'#9CA3AF', fontSize:13, textAlign:'center', padding:'20px 0' }}>No notes yet. Add the first update below.</p>
          )}
          <div style={{ display:'flex', flexDirection:'column', gap:0, marginBottom:20 }}>
            {/* Create event */}
            <div style={{ display:'flex', gap:12, padding:'10px 0', borderBottom:'1px solid #F3F4F6' }}>
              <div style={{ width:28, height:28, borderRadius:'50%', background:'#DBEAFE', display:'flex', alignItems:'center', justifyContent:'center', fontSize:12, fontWeight:700, color:'#1D4ED8', flexShrink:0 }}>✦</div>
              <div style={{ flex:1 }}>
                <div style={{ fontSize:12, fontWeight:700, color:'#374151' }}>Incident created by {data.created_by_name || 'system'}</div>
                <div style={{ fontSize:11, color:'#9CA3AF' }}>{data.created_at ? new Date(data.created_at).toLocaleString() : '—'}</div>
              </div>
            </div>
            {/* Notes */}
            {(data.notes || []).map((n, i) => (
              <div key={n.id} style={{ display:'flex', gap:12, padding:'10px 0', borderBottom:'1px solid #F3F4F6' }}>
                <div style={{ width:28, height:28, borderRadius:'50%', background:'#F3F4F6', display:'flex', alignItems:'center', justifyContent:'center', fontSize:12, fontWeight:700, color:'#374151', flexShrink:0 }}>
                  {(n.author_name || '?')[0].toUpperCase()}
                </div>
                <div style={{ flex:1 }}>
                  <div style={{ fontSize:12, fontWeight:700, color:'#374151' }}>{n.author_name || 'System'}</div>
                  <div style={{ fontSize:13, color:'#1F2937', margin:'4px 0', whiteSpace:'pre-wrap' }}>{n.note}</div>
                  <div style={{ fontSize:11, color:'#9CA3AF' }}>{n.created_at ? new Date(n.created_at).toLocaleString() : '—'}</div>
                </div>
              </div>
            ))}
            {/* Resolved event */}
            {data.resolved_at && (
              <div style={{ display:'flex', gap:12, padding:'10px 0' }}>
                <div style={{ width:28, height:28, borderRadius:'50%', background:'#DCFCE7', display:'flex', alignItems:'center', justifyContent:'center', fontSize:13, flexShrink:0 }}>✓</div>
                <div>
                  <div style={{ fontSize:12, fontWeight:700, color:'#16A34A' }}>Incident resolved</div>
                  <div style={{ fontSize:11, color:'#9CA3AF' }}>{new Date(data.resolved_at).toLocaleString()}</div>
                </div>
              </div>
            )}
          </div>

          {/* Add note */}
          {!['closed'].includes(data.status) && (
            <div style={{ borderTop:'1px solid #F3F4F6', paddingTop:14 }}>
              <label className="sa-label">Add note</label>
              <textarea
                className="sa-input"
                value={note}
                onChange={e => setNote(e.target.value)}
                rows={3}
                placeholder="Status update, action taken, root cause…"
                style={{ resize:'vertical', marginBottom:8 }}
              />
              <button className="sa-btn primary" onClick={submitNote} disabled={addingNote || !note.trim()}>
                {addingNote ? 'Adding…' : 'Add Note'}
              </button>
            </div>
          )}
        </div>
      )}

      {tab === 'alerts' && (
        <div className="sa-card">
          {!data.linked_alerts?.length ? (
            <p style={{ color:'#9CA3AF', fontSize:13, textAlign:'center', padding:'20px 0' }}>No alerts linked to this incident.</p>
          ) : (
            <div className="sa-table-wrap">
              <table className="sa-table">
                <thead><tr>
                  <th>Alert ID</th><th>Parameter</th><th>Value</th><th>Threshold</th><th>Severity</th><th>Company</th><th>Time</th><th>Acked</th>
                </tr></thead>
                <tbody>
                  {data.linked_alerts.map(a => {
                    const sc = INC_SEV[a.severity?.toLowerCase()] || INC_SEV.medium
                    return (
                      <tr key={a.id}>
                        <td style={{ fontFamily:'monospace', fontSize:12 }}>#{a.id}</td>
                        <td style={{ fontWeight:600 }}>{a.parameter}</td>
                        <td>{a.value?.toFixed(2)}</td>
                        <td>{a.threshold?.toFixed(2)}</td>
                        <td><span style={{ background:sc.bg, color:sc.text, padding:'2px 6px', borderRadius:6, fontSize:11, fontWeight:700 }}>{a.severity}</span></td>
                        <td style={{ fontSize:12 }}>{a.company_name}</td>
                        <td style={{ fontSize:11, color:'#6B7280' }}>{a.timestamp ? new Date(a.timestamp).toLocaleString() : '—'}</td>
                        <td>{a.acknowledged ? <span style={{ color:'#16A34A', fontWeight:700 }}>✓</span> : <span style={{ color:'#EF4444' }}>✕</span>}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  )
}

function NewIncidentModal({ companies, admins, onClose, onSaved }) {
  const [companyId,   setCompanyId]   = useState('')
  const [title,       setTitle]       = useState('')
  const [description, setDescription] = useState('')
  const [severity,    setSeverity]    = useState('medium')
  const [assigneeId,  setAssigneeId]  = useState('')
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState('')

  const handleSave = async () => {
    if (!title.trim()) return setError('Title required')
    setLoading(true); setError('')
    try {
      await post(`${SA}/incidents`, {
        company_id:  companyId  ? Number(companyId)  : null,
        assignee_id: assigneeId ? Number(assigneeId) : null,
        title:       title.trim(),
        description: description.trim() || null,
        severity,
      })
      onSaved?.()
      onClose()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <Modal title="New Incident" onClose={onClose}
      footer={
        <div style={{ display:'flex', gap:8 }}>
          <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
          <button className="sa-btn primary" onClick={handleSave} disabled={loading}>
            {loading ? 'Creating…' : 'Create Incident'}
          </button>
        </div>
      }
    >
      <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
        {error && <Err msg={error} />}
        <div>
          <label className="sa-label">Title *</label>
          <input className="sa-input" value={title} onChange={e => setTitle(e.target.value)} placeholder="Brief description of the incident" />
        </div>
        <div>
          <label className="sa-label">Description</label>
          <textarea className="sa-input" value={description} onChange={e => setDescription(e.target.value)} rows={3} placeholder="What happened, when, initial impact…" style={{ resize:'vertical' }} />
        </div>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
          <div>
            <label className="sa-label">Severity</label>
            <select className="sa-input" value={severity} onChange={e => setSeverity(e.target.value)}>
              {Object.keys(INC_SEV).map(k => <option key={k} value={k}>{k}</option>)}
            </select>
          </div>
          <div>
            <label className="sa-label">Company</label>
            <select className="sa-input" value={companyId} onChange={e => setCompanyId(e.target.value)}>
              <option value="">None (platform-wide)</option>
              {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
        </div>
        <div>
          <label className="sa-label">Assignee</label>
          <select className="sa-input" value={assigneeId} onChange={e => setAssigneeId(e.target.value)}>
            <option value="">Unassigned</option>
            {admins.filter(a => a.role === 'super_admin' || a.role === 'admin').map(a => (
              <option key={a.id} value={a.id}>{a.name} ({a.role})</option>
            ))}
          </select>
        </div>
      </div>
    </Modal>
  )
}


// ─── Tier 4: SLA Performance Dashboard ───────────────────────────────────────

function SLATab() {
  const [subTab, setSubTab] = useState('leaderboard')
  return (
    <div>
      <div style={{ display:'flex', gap:8, marginBottom:20 }}>
        {[
          { id:'leaderboard', label:'SLA Leaderboard'      },
          { id:'anomaly',     label:'Anomaly Detection'    },
        ].map(t => (
          <button key={t.id}
            className={`sa-btn ${subTab === t.id ? 'primary' : 'secondary'}`}
            onClick={() => setSubTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      {subTab === 'leaderboard' && <SLALeaderboard />}
      {subTab === 'anomaly'     && <AnomalyDetectionPanel />}
    </div>
  )
}

function SLALeaderboard() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [days,    setDays]    = useState(30)
  const [error,   setError]   = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await get(`${SA}/sla/leaderboard?days=${days}`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [days])

  useEffect(() => { load() }, [load])

  if (loading) return <Spinner />
  if (error)   return <Err msg={error} />
  if (!data)   return null

  const companies = data.companies || []
  const avgScore  = companies.length ? Math.round(companies.reduce((s, c) => s + c.sla_score, 0) / companies.length) : 0
  const avgAck    = companies.filter(c => c.avg_ack_minutes !== null).length
    ? Math.round(companies.filter(c => c.avg_ack_minutes !== null).reduce((s, c) => s + Number(c.avg_ack_minutes), 0) / companies.filter(c => c.avg_ack_minutes !== null).length)
    : null

  const gradeCounts = { A: 0, B: 0, C: 0, D: 0, F: 0 }
  companies.forEach(c => { if (gradeCounts[c.sla_grade] !== undefined) gradeCounts[c.sla_grade]++ })

  return (
    <>
      {/* Period selector */}
      <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:16 }}>
        <span style={{ fontSize:13, color:'#6B7280', fontWeight:600 }}>Period:</span>
        {[7, 14, 30, 60].map(d => (
          <button key={d} className={`sa-btn sm ${days === d ? 'primary' : 'secondary'}`} onClick={() => setDays(d)}>{d}d</button>
        ))}
      </div>

      {/* Fleet stats */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(150px, 1fr))', gap:12, marginBottom:20 }}>
        <div className="sa-stat" style={{ borderLeft:'4px solid #1D4ED8' }}>
          <div className="sa-stat-label">Fleet Avg Score</div>
          <div className="sa-stat-value" style={{ color: avgScore >= 75 ? '#059669' : avgScore >= 50 ? '#D97706' : '#DC2626' }}>{avgScore}%</div>
        </div>
        <div className="sa-stat" style={{ borderLeft:'4px solid #7C3AED' }}>
          <div className="sa-stat-label">Avg Ack Time</div>
          <div className="sa-stat-value" style={{ color:'#7C3AED' }}>{avgAck !== null ? `${avgAck}m` : '—'}</div>
        </div>
        {Object.entries(gradeCounts).map(([g, n]) => {
          const gc = SLA_GRADE[g]
          return (
            <div key={g} className="sa-stat" style={{ borderLeft:`4px solid ${gc.border}` }}>
              <div className="sa-stat-label">Grade {g}</div>
              <div className="sa-stat-value" style={{ color: gc.text }}>{n}</div>
            </div>
          )
        })}
      </div>

      {/* Leaderboard table */}
      <div className="sa-card">
        <h2 className="sa-card-title">Company SLA Leaderboard — {days}-day window</h2>
        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead><tr>
              <th>#</th><th>Company</th><th>Grade</th><th>Score</th>
              <th>Ack Rate</th><th>Avg Ack</th><th>Median Ack</th>
              <th>Total Alerts</th><th>Unacked</th><th>Critical Acked</th>
            </tr></thead>
            <tbody>
              {companies.length === 0
                ? <tr><td colSpan={10} className="sa-empty">No data for this period</td></tr>
                : companies.map((c, i) => (
                  <tr key={c.company_id}>
                    <td style={{ color:'#9CA3AF', fontSize:12 }}>{i + 1}</td>
                    <td style={{ fontWeight:700 }}>{c.company_name}</td>
                    <td><SlaGradeBadge grade={c.sla_grade} /></td>
                    <td style={{ fontWeight:700, color: c.sla_score >= 75 ? '#059669' : c.sla_score >= 50 ? '#D97706' : '#DC2626' }}>
                      {c.sla_score}%
                    </td>
                    <td style={{ textAlign:'center' }}>
                      <span style={{ color: c.ack_rate >= 80 ? '#059669' : c.ack_rate >= 50 ? '#D97706' : '#DC2626', fontWeight:700 }}>
                        {c.ack_rate}%
                      </span>
                    </td>
                    <td style={{ textAlign:'center', color: c.avg_ack_minutes > 60 ? '#DC2626' : '#374151' }}>
                      {c.avg_ack_minutes != null ? `${c.avg_ack_minutes}m` : <span style={{ color:'#9CA3AF' }}>—</span>}
                    </td>
                    <td style={{ textAlign:'center', color:'#6B7280' }}>
                      {c.median_ack_minutes != null ? `${c.median_ack_minutes}m` : <span style={{ color:'#9CA3AF' }}>—</span>}
                    </td>
                    <td style={{ textAlign:'center' }}>{c.total_alerts}</td>
                    <td style={{ textAlign:'center', color: c.unacked_alerts > 0 ? '#DC2626' : '#059669', fontWeight: c.unacked_alerts > 0 ? 700 : 400 }}>
                      {c.unacked_alerts}
                    </td>
                    <td style={{ textAlign:'center' }}>
                      {c.critical_total > 0
                        ? <span style={{ color: c.critical_acked === c.critical_total ? '#059669' : '#DC2626' }}>
                            {c.critical_acked}/{c.critical_total}
                          </span>
                        : <span style={{ color:'#9CA3AF' }}>—</span>
                      }
                    </td>
                  </tr>
                ))
              }
            </tbody>
          </table>
        </div>

        {/* Score legend */}
        <div style={{ marginTop:14, display:'flex', gap:12, flexWrap:'wrap' }}>
          {Object.entries(SLA_GRADE).map(([g, s]) => (
            <div key={g} style={{ display:'flex', alignItems:'center', gap:6, fontSize:12 }}>
              <span style={{ background:s.bg, color:s.text, border:`1px solid ${s.border}`, borderRadius:4, padding:'1px 7px', fontWeight:700 }}>{g}</span>
              <span style={{ color:'#6B7280' }}>{{ A:' ≥90%', B:' ≥75%', C:' ≥60%', D:' ≥40%', F:' <40%' }[g]}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

function AnomalyDetectionPanel() {
  const [data,      setData]      = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')
  const [window_d,  setWindowD]   = useState(7)
  const [baseline,  setBaseline]  = useState(30)
  const [threshold, setThreshold] = useState(2.0)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      setData(await get(`${SA}/anomaly-detection?window=${window_d}&baseline=${baseline}&threshold=${threshold}`))
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [window_d, baseline, threshold])

  useEffect(() => { load() }, [load])

  if (loading) return <Spinner />
  if (error)   return <Err msg={error} />
  if (!data)   return null

  const { anomalies = [], all_companies = [], fleet_stats = {} } = data

  return (
    <>
      {/* Controls */}
      <div className="sa-card" style={{ marginBottom:16 }}>
        <h2 className="sa-card-title">Statistical Anomaly Detection</h2>
        <p style={{ fontSize:13, color:'#6B7280', margin:'0 0 14px' }}>
          Compares each company's recent alert rate against the fleet average. Z-score &gt; {threshold} triggers an anomaly flag.
        </p>
        <div style={{ display:'flex', gap:12, flexWrap:'wrap', alignItems:'center' }}>
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            <label style={{ fontSize:12, color:'#6B7280', fontWeight:600 }}>Recent window:</label>
            {[3, 7, 14].map(d => (
              <button key={d} className={`sa-btn sm ${window_d === d ? 'primary' : 'secondary'}`} onClick={() => setWindowD(d)}>{d}d</button>
            ))}
          </div>
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            <label style={{ fontSize:12, color:'#6B7280', fontWeight:600 }}>Baseline:</label>
            {[14, 30, 60].map(d => (
              <button key={d} className={`sa-btn sm ${baseline === d ? 'primary' : 'secondary'}`} onClick={() => setBaseline(d)}>{d}d</button>
            ))}
          </div>
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            <label style={{ fontSize:12, color:'#6B7280', fontWeight:600 }}>Z threshold:</label>
            {[1.5, 2.0, 2.5, 3.0].map(t => (
              <button key={t} className={`sa-btn sm ${threshold === t ? 'primary' : 'secondary'}`} onClick={() => setThreshold(t)}>{t}</button>
            ))}
          </div>
          <button className="sa-btn sm secondary" onClick={load}>↻ Re-run</button>
        </div>

        {fleet_stats.n && (
          <div style={{ marginTop:12, display:'flex', gap:16, fontSize:12, color:'#6B7280', flexWrap:'wrap' }}>
            <span>Fleet size: <strong>{fleet_stats.n}</strong></span>
            <span>Mean daily alerts: <strong>{fleet_stats.mean_daily}</strong></span>
            <span>Std dev: <strong>{fleet_stats.std_daily}</strong></span>
          </div>
        )}
      </div>

      {anomalies.length === 0 ? (
        <div style={{ background:'#F0FDF4', border:'1px solid #86EFAC', borderRadius:10, padding:24, textAlign:'center' }}>
          <div style={{ fontSize:24, marginBottom:8 }}>✓</div>
          <div style={{ fontWeight:700, color:'#15803D', fontSize:15, marginBottom:4 }}>No anomalies detected</div>
          <div style={{ fontSize:13, color:'#6B7280' }}>All companies are within {threshold} standard deviations of the fleet average.</div>
        </div>
      ) : (
        <>
          <div style={{ background:'#FFF7ED', border:'1px solid #FCD34D', borderRadius:10, padding:'10px 16px', marginBottom:16, fontSize:13, color:'#92400E', fontWeight:600 }}>
            ⚠ {anomalies.length} {anomalies.length === 1 ? 'company' : 'companies'} flagged as anomalous
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {anomalies.map(a => (
              <div key={a.company_id} className="sa-card" style={{ padding:14, borderLeft:`4px solid ${a.direction === 'spike' ? '#EF4444' : '#3B82F6'}` }}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', gap:12, flexWrap:'wrap' }}>
                  <div>
                    <div style={{ display:'flex', gap:10, alignItems:'center', marginBottom:4 }}>
                      <span style={{ fontWeight:800, fontSize:14 }}>{a.company_name}</span>
                      <span style={{ fontSize:11, fontWeight:700, background: a.direction === 'spike' ? '#FEF2F2' : '#EFF6FF', color: a.direction === 'spike' ? '#DC2626' : '#1D4ED8', padding:'2px 8px', borderRadius:4 }}>
                        {a.direction === 'spike' ? '▲ SPIKE' : '▼ QUIET'}
                      </span>
                      <span style={{ fontSize:12, color:'#6B7280' }}>Z = {a.z_score > 0 ? '+' : ''}{a.z_score}</span>
                    </div>
                    <div style={{ fontSize:12, color:'#6B7280', display:'flex', gap:16, flexWrap:'wrap' }}>
                      <span>Recent ({window_d}d): <strong>{a.recent_daily}/day</strong></span>
                      <span>Baseline ({baseline}d): <strong>{a.baseline_daily}/day</strong></span>
                      <span>Fleet avg: <strong>{a.mean_daily}/day</strong></span>
                      <span>Critical alerts: <strong style={{ color: a.recent_critical > 0 ? '#DC2626' : undefined }}>{a.recent_critical}</strong></span>
                    </div>
                  </div>
                  <div style={{ textAlign:'right', flexShrink:0 }}>
                    <div style={{ fontSize:20, fontWeight:900, color: a.direction === 'spike' ? '#DC2626' : '#3B82F6' }}>
                      {Math.abs(a.z_score)}σ
                    </div>
                    <div style={{ fontSize:11, color:'#9CA3AF' }}>standard deviations</div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Full fleet mini-table */}
          <div className="sa-card" style={{ marginTop:16 }}>
            <h2 className="sa-card-title">All Companies — Alert Rate ({window_d}d)</h2>
            <div className="sa-table-wrap">
              <table className="sa-table">
                <thead><tr>
                  <th>Company</th><th>Recent /day</th><th>Baseline /day</th><th>Z-score</th><th>Critical</th><th>Status</th>
                </tr></thead>
                <tbody>
                  {[...all_companies].sort((a, b) => Math.abs(b.z_score) - Math.abs(a.z_score)).map(r => (
                    <tr key={r.company_id} style={{ background: r.anomaly ? (r.direction === 'spike' ? '#FFF5F5' : '#F5F8FF') : undefined }}>
                      <td style={{ fontWeight: r.anomaly ? 700 : 400 }}>{r.company_name}</td>
                      <td style={{ textAlign:'center' }}>{r.recent_daily}</td>
                      <td style={{ textAlign:'center', color:'#9CA3AF' }}>{r.baseline_daily}</td>
                      <td style={{ textAlign:'center', fontWeight:700, color: Math.abs(r.z_score) >= threshold ? (r.z_score > 0 ? '#DC2626' : '#1D4ED8') : '#374151' }}>
                        {r.z_score > 0 ? '+' : ''}{r.z_score}
                      </td>
                      <td style={{ textAlign:'center', color: r.recent_critical > 0 ? '#DC2626' : undefined }}>{r.recent_critical}</td>
                      <td>{r.anomaly
                        ? <span style={{ color: r.direction === 'spike' ? '#DC2626' : '#1D4ED8', fontWeight:700, fontSize:11 }}>
                            {r.direction === 'spike' ? '▲ Spike' : '▼ Quiet'}
                          </span>
                        : <span style={{ color:'#9CA3AF', fontSize:11 }}>Normal</span>
                      }</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  )
}


// ─── Tier 3: Platform Health Monitor ─────────────────────────────────────────

function PlatformHealthTab() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await get(`${SA}/platform/health`)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [load])

  if (loading) return <Spinner />
  if (error)   return <Err msg={error} />
  if (!data)   return null

  const pool   = data.db_pool || {}
  const mods   = data.module_status || {}
  const poolPct = pool.max_conn ? Math.round((pool.used / pool.max_conn) * 100) : 0

  const vitals = [
    { label: 'Active Sessions',      value: data.active_sessions,         color: '#1D4ED8' },
    { label: 'Readings / Last Hour', value: data.readings_last_hour,      color: '#059669' },
    { label: 'Alerts / Last Hour',   value: data.alerts_last_hour,        color: data.alerts_last_hour > 0 ? '#D97706' : '#059669' },
    { label: 'Unacked Critical',     value: data.unacked_critical,        color: data.unacked_critical > 0 ? '#DC2626' : '#059669' },
    { label: 'Audit Errors / 1h',    value: data.audit_errors_last_hour,  color: data.audit_errors_last_hour > 0 ? '#DC2626' : '#059669' },
  ]

  return (
    <>
      {/* Vitals strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12, marginBottom: 20 }}>
        {vitals.map(v => (
          <div key={v.label} className="sa-stat" style={{ borderLeft: `4px solid ${v.color}` }}>
            <div className="sa-stat-label">{v.label}</div>
            <div className="sa-stat-value" style={{ color: v.color }}>{v.value ?? '—'}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* DB Pool */}
        <div className="sa-card">
          <h2 className="sa-card-title">Database Connection Pool</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              ['Min connections',  pool.min_conn],
              ['Max connections',  pool.max_conn],
              ['Currently in use', pool.used],
              ['Free / waiting',   pool.free],
            ].map(([label, val]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '6px 0', borderBottom: '1px solid #F3F4F6' }}>
                <span style={{ color: '#6B7280' }}>{label}</span>
                <span style={{ fontWeight: 700 }}>{val ?? '—'}</span>
              </div>
            ))}
            {/* Pool utilisation bar */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#6B7280', marginBottom: 4 }}>
                <span>Pool utilisation</span>
                <span style={{ fontWeight: 700, color: poolPct > 80 ? '#DC2626' : '#059669' }}>{poolPct}%</span>
              </div>
              <div style={{ height: 8, background: '#F3F4F6', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${poolPct}%`, background: poolPct > 80 ? '#EF4444' : '#10B981', borderRadius: 4, transition: 'width 0.5s' }} />
              </div>
            </div>
          </div>
        </div>

        {/* Module statuses */}
        <div className="sa-card">
          <h2 className="sa-card-title">Module Status</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {Object.entries(mods).map(([mod, status]) => {
              const ok = status === 'ok' || status === 'connected'
              return (
                <div key={mod} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13, padding: '6px 0', borderBottom: '1px solid #F3F4F6' }}>
                  <span style={{ color: '#374151', fontWeight: 600, textTransform: 'capitalize' }}>{mod.replace(/_/g, ' ')}</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: ok ? '#059669' : '#DC2626', fontWeight: 700 }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: ok ? '#10B981' : '#EF4444', display: 'inline-block' }} />
                    {ok ? 'OK' : String(status).slice(0, 30)}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Server time */}
      <div style={{ marginTop: 12, fontSize: 12, color: '#9CA3AF', textAlign: 'right' }}>
        Server UTC: {data.server_time_utc ? new Date(data.server_time_utc).toLocaleString() : '—'}
        {' · '}
        <button className="sa-btn sm secondary" onClick={load} style={{ fontSize: 11 }}>↻ Refresh</button>
      </div>
    </>
  )
}


// ─── Tier 3: Advanced Audit Explorer (upgrade) ────────────────────────────────
// This overrides the existing AuditTab further up in this file — the switch
// statement now routes 'audit' → AuditTab (old, kept) and only the new tab ids
// route here. Actually we'll shadow-replace by defining NEW components for the
// new tabs and leave existing AuditTab untouched. The real "advanced" audit is
// available under a new sub-tab inside the existing AuditTab below — we add
// a AdvancedAuditPanel sub-section inside the existing AuditTab by patching it.
// For cleanliness, the cross-company analytics upgrade is a new component.

function CrossCompanyAnalyticsPanel() {
  const [activeMetric, setActiveMetric] = useState('alerts')
  const [days,         setDays]         = useState(7)
  const [topRows,      setTopRows]      = useState([])
  const [platform,     setPlatform]     = useState(null)
  const [compareIds,   setCompareIds]   = useState('')
  const [compareData,  setCompareData]  = useState([])
  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState('')

  const loadTop = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [top, plat] = await Promise.all([
        get(`${SA}/analytics/top-companies?metric=${activeMetric}&days=${days}&limit=10`),
        get(`${SA}/analytics/platform?days=${days}`),
      ])
      setTopRows(top.rows || [])
      setPlatform(plat)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [activeMetric, days])

  useEffect(() => { loadTop() }, [loadTop])

  const runCompare = async () => {
    if (!compareIds.trim()) return
    setLoading(true); setError('')
    try {
      const d = await get(`${SA}/analytics/compare?ids=${encodeURIComponent(compareIds)}&days=${days}`)
      setCompareData(Array.isArray(d) ? d : [])
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const METRICS = [
    { id: 'alerts',   label: 'Most Alerts',   color: '#EF4444' },
    { id: 'readings', label: 'Most Readings',  color: '#1D4ED8' },
    { id: 'sessions', label: 'Most Sessions',  color: '#059669' },
  ]
  const metricColor = METRICS.find(m => m.id === activeMetric)?.color || '#1D4ED8'

  return (
    <>
      {error && <Err msg={error} />}

      {/* Controls */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, color: '#6B7280', fontWeight: 600 }}>Rank by:</span>
        {METRICS.map(m => (
          <button key={m.id}
            className={`sa-btn sm ${activeMetric === m.id ? 'primary' : 'secondary'}`}
            onClick={() => setActiveMetric(m.id)}>
            {m.label}
          </button>
        ))}
        <span style={{ marginLeft: 8, fontSize: 13, color: '#6B7280' }}>Period:</span>
        {[7, 14, 30].map(d => (
          <button key={d}
            className={`sa-btn sm ${days === d ? 'primary' : 'secondary'}`}
            onClick={() => setDays(d)}>
            {d}d
          </button>
        ))}
        <button className="sa-btn sm secondary" onClick={loadTop}>↻</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* Top companies chart */}
        <div className="sa-card">
          <h2 className="sa-card-title">Top Companies — {METRICS.find(m => m.id === activeMetric)?.label} ({days}d)</h2>
          {loading ? <Spinner /> : (
            <div style={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topRows} layout="vertical" margin={{ left: 20, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={90} />
                  <Tooltip formatter={v => [v, activeMetric]} />
                  <Bar dataKey="value" fill={metricColor} radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Platform alert trend */}
        <div className="sa-card">
          <h2 className="sa-card-title">Platform Alert Trend ({days}d)</h2>
          {loading || !platform ? <Spinner /> : (
            <div style={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={platform.alert_trend || []} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={d => d?.slice(5)} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="total_alerts" stroke="#EF4444" dot={false} name="Total" />
                  <Line type="monotone" dataKey="critical"     stroke="#DC2626" dot={false} strokeDasharray="4 2" name="Critical" />
                  <Line type="monotone" dataKey="acknowledged" stroke="#10B981" dot={false} name="Acked" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* Readings trend */}
      {platform && (
        <div className="sa-card" style={{ marginBottom: 16 }}>
          <h2 className="sa-card-title">Sensor Readings & Admin Sessions ({days}d)</h2>
          <div style={{ height: 200 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="day" type="category" allowDuplicatedCategory={false}
                  tick={{ fontSize: 10 }} tickFormatter={d => d?.slice(5)} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Line data={platform.reading_trend || []} type="monotone" dataKey="readings" stroke="#1D4ED8" dot={false} name="Readings" />
                <Line data={platform.session_trend || []} type="monotone" dataKey="sessions" stroke="#7C3AED" dot={false} name="Sessions" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Company comparison */}
      <div className="sa-card">
        <h2 className="sa-card-title">Company Side-by-Side Comparison</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14 }}>
          <input className="sa-input" value={compareIds}
            onChange={e => setCompareIds(e.target.value)}
            placeholder="Company IDs, comma-separated  e.g. 1,2,3"
            style={{ maxWidth: 300 }} />
          <button className="sa-btn primary" onClick={runCompare} disabled={loading}>Compare</button>
        </div>
        {compareData.length > 0 && (
          <div className="sa-table-wrap">
            <table className="sa-table">
              <thead><tr>
                <th>Company</th>
                <th>Alerts ({days}d)</th><th>Critical</th><th>Unacked Now</th>
                <th>Readings ({days}d)</th><th>Uptime %</th>
                <th>Subscribers</th><th>Admins</th><th>Last Reading</th>
              </tr></thead>
              <tbody>
                {compareData.map(r => (
                  <tr key={r.id}>
                    <td><strong>{r.name}</strong>
                      {!r.is_active && <Badge label="Inactive" type="inactive" />}
                      {r.maintenance_mode && <Badge label="Maint" type="warning" />}
                    </td>
                    <td style={{ textAlign: 'center' }}>{r.alerts_period}</td>
                    <td style={{ textAlign: 'center', color: r.critical_period > 0 ? '#DC2626' : undefined, fontWeight: r.critical_period > 0 ? 700 : undefined }}>{r.critical_period}</td>
                    <td style={{ textAlign: 'center', color: r.unacked_now > 0 ? '#D97706' : undefined }}>{r.unacked_now}</td>
                    <td style={{ textAlign: 'center' }}>{r.readings_period}</td>
                    <td style={{ textAlign: 'center', color: r.uptime_pct < 50 ? '#DC2626' : r.uptime_pct < 80 ? '#D97706' : '#059669', fontWeight: 700 }}>{r.uptime_pct}%</td>
                    <td style={{ textAlign: 'center' }}>{r.active_subscribers}</td>
                    <td style={{ textAlign: 'center' }}>{r.admin_count}</td>
                    <td style={{ fontSize: 12, color: '#6B7280' }}>{r.minutes_since_reading !== null ? fmtAge(r.minutes_since_reading) : 'never'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {compareData.length === 0 && !loading && (
          <p style={{ color: '#9CA3AF', fontSize: 13, textAlign: 'center', padding: 20 }}>
            Enter company IDs above and click Compare to see side-by-side metrics.
          </p>
        )}
      </div>
    </>
  )
}


// ─── Tier 3: Templates & Rules Tab ────────────────────────────────────────────

function TemplatesRulesTab() {
  const [subTab, setSubTab] = useState('templates')
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {[
          { id: 'templates', label: 'Parameter Templates' },
          { id: 'rules',     label: 'Escalation Rules'    },
          { id: 'crossanalytics', label: 'Cross-Company Analytics' },
        ].map(t => (
          <button key={t.id}
            className={`sa-btn ${subTab === t.id ? 'primary' : 'secondary'}`}
            onClick={() => setSubTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      {subTab === 'templates'      && <ParameterTemplatesPanel />}
      {subTab === 'rules'          && <EscalationRulesPanel />}
      {subTab === 'crossanalytics' && <CrossCompanyAnalyticsPanel />}
    </div>
  )
}


function ParameterTemplatesPanel() {
  const [templates,  setTemplates]  = useState([])
  const [companies,  setCompanies]  = useState([])
  const [loading,    setLoading]    = useState(true)
  const [showForm,   setShowForm]   = useState(false)
  const [toast,      setToast]      = useState('')
  const [applyState, setApplyState] = useState({}) // { [tplId]: { company_id, loading } }

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3500) }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [t, c] = await Promise.all([
        get(`${SA}/parameter-templates`),
        get(`${SA}/companies`),
      ])
      setTemplates(Array.isArray(t) ? t : [])
      setCompanies(Array.isArray(c) ? c : [])
    } catch { /* silent */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const handleDelete = async (tpl) => {
    if (!window.confirm(`Delete template "${tpl.name}"?`)) return
    try {
      await del(`${SA}/parameter-templates/${tpl.id}`)
      showToast(`Template "${tpl.name}" deleted`)
      load()
    } catch (e) { alert(e.message) }
  }

  const handleApply = async (tpl) => {
    const state = applyState[tpl.id] || {}
    if (!state.company_id) return alert('Select a company first')
    setApplyState(prev => ({ ...prev, [tpl.id]: { ...state, loading: true } }))
    try {
      const res = await post(`${SA}/parameter-templates/${tpl.id}/apply/${state.company_id}`, {})
      showToast(`Applied: ${res.applied} params to ${res.company}, ${res.skipped} skipped (already existed)`)
      setApplyState(prev => ({ ...prev, [tpl.id]: { company_id: '', loading: false } }))
    } catch (e) {
      alert(e.message)
      setApplyState(prev => ({ ...prev, [tpl.id]: { ...state, loading: false } }))
    }
  }

  return (
    <>
      {toast && <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46', padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: '#1F2937' }}>Parameter Templates</h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#6B7280' }}>
            Create reusable parameter sets. Apply them to any company in one click.
          </p>
        </div>
        <button className="sa-btn primary" onClick={() => setShowForm(true)}>+ New Template</button>
      </div>

      {loading ? <Spinner /> : templates.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#9CA3AF' }}>
          No templates yet. Create one to define a reusable set of sensor parameters.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {templates.map(tpl => {
            const params = typeof tpl.params === 'string' ? JSON.parse(tpl.params) : (tpl.params || [])
            const st     = applyState[tpl.id] || {}
            return (
              <div key={tpl.id} className="sa-card" style={{ padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                      <span style={{ fontWeight: 800, fontSize: 15, color: '#1F2937' }}>{tpl.name}</span>
                      <span style={{ fontSize: 11, background: '#EFF6FF', color: '#1D4ED8', borderRadius: 4, padding: '2px 8px', fontWeight: 700 }}>
                        {params.length} param{params.length !== 1 ? 's' : ''}
                      </span>
                    </div>
                    {tpl.description && (
                      <p style={{ fontSize: 13, color: '#6B7280', margin: '0 0 8px' }}>{tpl.description}</p>
                    )}
                    {/* Param chips */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {params.map((p, i) => (
                        <span key={i} style={{ fontSize: 12, background: '#F3F4F6', borderRadius: 6, padding: '3px 10px', color: '#374151', fontWeight: 600 }}>
                          {p.name}{p.unit ? ` (${p.unit})` : ''}{p.min_value != null ? ` ≥${p.min_value}` : ''}{p.max_value != null ? ` ≤${p.max_value}` : ''}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end', flexShrink: 0 }}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <select className="sa-input" style={{ fontSize: 12, padding: '5px 8px', width: 160 }}
                        value={st.company_id || ''}
                        onChange={e => setApplyState(prev => ({ ...prev, [tpl.id]: { ...st, company_id: e.target.value } }))}>
                        <option value="">Select company…</option>
                        {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                      <button className="sa-btn sm primary" onClick={() => handleApply(tpl)} disabled={st.loading || !st.company_id}>
                        {st.loading ? '…' : '▶ Apply'}
                      </button>
                    </div>
                    <button className="sa-btn sm danger" onClick={() => handleDelete(tpl)}>Delete</button>
                    <span style={{ fontSize: 11, color: '#9CA3AF' }}>by {tpl.created_by_name || 'system'}</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {showForm && <NewTemplateModal onClose={() => setShowForm(false)} onSaved={load} />}
    </>
  )
}


function NewTemplateModal({ onClose, onSaved }) {
  const [name,    setName]    = useState('')
  const [desc,    setDesc]    = useState('')
  const [params,  setParams]  = useState([{ name: '', unit: '', min_value: '', max_value: '' }])
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')

  const addParam   = () => setParams(p => [...p, { name: '', unit: '', min_value: '', max_value: '' }])
  const removeParam = (i) => setParams(p => p.filter((_, idx) => idx !== i))
  const updateParam = (i, field, val) => setParams(p => p.map((row, idx) => idx === i ? { ...row, [field]: val } : row))

  const handleSave = async () => {
    if (!name.trim()) return setError('Template name required')
    const filled = params.filter(p => p.name.trim())
    if (!filled.length) return setError('Add at least one parameter')
    setLoading(true); setError('')
    try {
      await post(`${SA}/parameter-templates`, {
        name: name.trim(),
        description: desc.trim() || null,
        params: filled.map(p => ({
          name:      p.name.trim(),
          unit:      p.unit.trim() || null,
          min_value: p.min_value !== '' ? parseFloat(p.min_value) : null,
          max_value: p.max_value !== '' ? parseFloat(p.max_value) : null,
        })),
      })
      onSaved?.()
      onClose()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <Modal title="New Parameter Template"
      onClose={onClose}
      footer={
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
          <button className="sa-btn primary" onClick={handleSave} disabled={loading}>
            {loading ? 'Saving…' : 'Save Template'}
          </button>
        </div>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <label className="sa-label">Template Name *</label>
          <input className="sa-input" value={name} onChange={e => setName(e.target.value)} placeholder="Cold Storage Basic" />
        </div>
        <div>
          <label className="sa-label">Description</label>
          <input className="sa-input" value={desc} onChange={e => setDesc(e.target.value)} placeholder="Standard params for cold storage facilities" />
        </div>

        {error && <Err msg={error} />}

        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <label className="sa-label" style={{ margin: 0 }}>Parameters</label>
            <button className="sa-btn sm secondary" onClick={addParam}>+ Add</button>
          </div>
          {params.map((p, i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr auto', gap: 6, marginBottom: 6, alignItems: 'center' }}>
              <input className="sa-input" placeholder="Name *" value={p.name} onChange={e => updateParam(i, 'name', e.target.value)} />
              <input className="sa-input" placeholder="Unit" value={p.unit} onChange={e => updateParam(i, 'unit', e.target.value)} />
              <input className="sa-input" placeholder="Min" type="number" value={p.min_value} onChange={e => updateParam(i, 'min_value', e.target.value)} />
              <input className="sa-input" placeholder="Max" type="number" value={p.max_value} onChange={e => updateParam(i, 'max_value', e.target.value)} />
              <button className="sa-btn sm danger" onClick={() => removeParam(i)} disabled={params.length === 1}>✕</button>
            </div>
          ))}
        </div>
      </div>
    </Modal>
  )
}


function EscalationRulesPanel() {
  const [rules,     setRules]     = useState([])
  const [companies, setCompanies] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [showForm,  setShowForm]  = useState(false)
  const [editRule,  setEditRule]  = useState(null)
  const [toast,     setToast]     = useState('')
  const [evalResult, setEvalResult] = useState(null)
  const [evalLoading, setEvalLoading] = useState(false)

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 4000) }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [r, c] = await Promise.all([
        get(`${SA}/escalation-rules`),
        get(`${SA}/companies`),
      ])
      setRules(Array.isArray(r) ? r : [])
      setCompanies(Array.isArray(c) ? c : [])
    } catch { /* silent */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const handleDelete = async (rule) => {
    if (!window.confirm(`Delete rule "${rule.name}"?`)) return
    try { await del(`${SA}/escalation-rules/${rule.id}`); showToast('Rule deleted'); load() }
    catch (e) { alert(e.message) }
  }

  const runEval = async () => {
    setEvalLoading(true); setEvalResult(null)
    try {
      const res = await post(`${SA}/escalation-rules/evaluate`, {})
      setEvalResult(res)
      showToast(`Evaluated ${res.evaluated} rules — ${res.triggered.length} triggered`)
    } catch (e) { alert(e.message) }
    finally { setEvalLoading(false) }
  }

  const SEV_COLOR = { critical: '#DC2626', warning: '#D97706', info: '#1D4ED8' }
  const coMap = Object.fromEntries(companies.map(c => [c.id, c.name]))

  return (
    <>
      {toast && <div style={{ position:'fixed', top:20, right:20, background:'#D1FAE5', color:'#065F46', padding:'10px 18px', borderRadius:8, fontWeight:600, fontSize:13, zIndex:2000 }}>{toast}</div>}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: '#1F2937' }}>Escalation Rules</h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#6B7280' }}>
            Auto-trigger actions when unacked alerts stay open past a threshold.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="sa-btn secondary" onClick={runEval} disabled={evalLoading}>
            {evalLoading ? '…' : '▶ Evaluate Now'}
          </button>
          <button className="sa-btn primary" onClick={() => { setEditRule(null); setShowForm(true) }}>+ New Rule</button>
        </div>
      </div>

      {/* Last eval result */}
      {evalResult && (
        <div className="sa-card" style={{ background: evalResult.triggered.length > 0 ? '#FFF7ED' : '#F0FDF4', border: `1px solid ${evalResult.triggered.length > 0 ? '#FCD34D' : '#86EFAC'}`, marginBottom: 16 }}>
          <div style={{ fontWeight: 700, color: evalResult.triggered.length > 0 ? '#92400E' : '#15803D', marginBottom: 8 }}>
            Evaluation result — {evalResult.evaluated} rules checked, {evalResult.triggered.length} triggered
          </div>
          {evalResult.triggered.map((t, i) => (
            <div key={i} style={{ fontSize: 13, color: '#374151', padding: '4px 0', borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
              Rule <strong>{t.rule_name}</strong> → Alert #{t.alert_id} ({t.open_minutes}m open) — {t.webhook_status}
            </div>
          ))}
          {evalResult.triggered.length === 0 && (
            <div style={{ fontSize: 13, color: '#15803D' }}>No rules triggered — all alerts within thresholds.</div>
          )}
        </div>
      )}

      {loading ? <Spinner /> : rules.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#9CA3AF' }}>
          No escalation rules yet. Create one to auto-fire actions on stale critical alerts.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rules.map(rule => (
            <div key={rule.id} className="sa-card" style={{ padding: 14, borderLeft: `4px solid ${SEV_COLOR[rule.severity_filter] || '#6B7280'}`, opacity: rule.is_active ? 1 : 0.55 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                    <span style={{ fontWeight: 800, fontSize: 14 }}>{rule.name}</span>
                    {!rule.is_active && <Badge label="Disabled" type="inactive" />}
                    <span style={{ fontSize: 12, color: SEV_COLOR[rule.severity_filter], fontWeight: 700, background: '#FEF2F2', padding: '2px 8px', borderRadius: 4 }}>
                      {rule.severity_filter}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: '#6B7280', display: 'flex', gap: 16 }}>
                    <span>Fires after <strong>{rule.threshold_minutes}min</strong> open</span>
                    <span>Company: <strong>{rule.company_id ? coMap[rule.company_id] || `#${rule.company_id}` : 'All companies'}</strong></span>
                    <span>Action: <strong>{rule.action_type}</strong>{rule.action_target ? ` → ${rule.action_target.slice(0, 40)}` : ''}</span>
                    {rule.last_triggered_at && <span style={{ color: '#D97706' }}>Last: {new Date(rule.last_triggered_at).toLocaleString()}</span>}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                  <button className="sa-btn sm secondary" onClick={() => { setEditRule(rule); setShowForm(true) }}>Edit</button>
                  <button className="sa-btn sm danger" onClick={() => handleDelete(rule)}>Delete</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {showForm && (
        <EscalationRuleModal
          rule={editRule}
          companies={companies}
          onClose={() => setShowForm(false)}
          onSaved={load}
        />
      )}
    </>
  )
}


function EscalationRuleModal({ rule, companies, onClose, onSaved }) {
  const editing = !!rule
  const [name,      setName]      = useState(rule?.name || '')
  const [companyId, setCompanyId] = useState(rule?.company_id || '')
  const [severity,  setSeverity]  = useState(rule?.severity_filter || 'critical')
  const [threshold, setThreshold] = useState(rule?.threshold_minutes || 30)
  const [actionType, setActionType] = useState(rule?.action_type || 'log')
  const [actionTarget, setActionTarget] = useState(rule?.action_target || '')
  const [isActive,  setIsActive]  = useState(rule?.is_active !== false)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')

  const handleSave = async () => {
    if (!name.trim()) return setError('Rule name required')
    setLoading(true); setError('')
    const body = {
      name: name.trim(),
      company_id:        companyId ? Number(companyId) : null,
      severity_filter:   severity,
      threshold_minutes: Number(threshold),
      action_type:       actionType,
      action_target:     actionTarget.trim() || null,
      is_active:         isActive,
    }
    try {
      if (editing) await patch(`${SA}/escalation-rules/${rule.id}`, body)
      else         await post(`${SA}/escalation-rules`, body)
      onSaved?.()
      onClose()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <Modal
      title={editing ? `Edit Rule — ${rule.name}` : 'New Escalation Rule'}
      onClose={onClose}
      footer={
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="sa-btn secondary" onClick={onClose}>Cancel</button>
          <button className="sa-btn primary" onClick={handleSave} disabled={loading}>
            {loading ? 'Saving…' : editing ? 'Update Rule' : 'Create Rule'}
          </button>
        </div>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {error && <Err msg={error} />}
        <div>
          <label className="sa-label">Rule Name *</label>
          <input className="sa-input" value={name} onChange={e => setName(e.target.value)} placeholder="Critical alert escalation" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <label className="sa-label">Company (blank = all)</label>
            <select className="sa-input" value={companyId} onChange={e => setCompanyId(e.target.value)}>
              <option value="">All companies</option>
              {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="sa-label">Severity filter</label>
            <select className="sa-input" value={severity} onChange={e => setSeverity(e.target.value)}>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
          </div>
          <div>
            <label className="sa-label">Fire after (minutes open)</label>
            <input className="sa-input" type="number" min={1} value={threshold} onChange={e => setThreshold(e.target.value)} />
          </div>
          <div>
            <label className="sa-label">Action type</label>
            <select className="sa-input" value={actionType} onChange={e => setActionType(e.target.value)}>
              <option value="log">Log only (audit)</option>
              <option value="webhook">Webhook POST</option>
            </select>
          </div>
        </div>
        {actionType === 'webhook' && (
          <div>
            <label className="sa-label">Webhook URL</label>
            <input className="sa-input" value={actionTarget} onChange={e => setActionTarget(e.target.value)} placeholder="https://hooks.example.com/notify" />
          </div>
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
          <input type="checkbox" checked={isActive} onChange={e => setIsActive(e.target.checked)} />
          Rule is active
        </label>
      </div>
    </Modal>
  )
}


// ─── System Logs tab ──────────────────────────────────────────────────────────

function SystemLogsTab() {
  const [logLines,   setLogLines]   = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')
  const [levelFilter, setLevel]     = useState('')
  const [search,     setSearch]     = useState('')
  const [lineCount,  setLineCount]  = useState(200)
  const [paused,     setPaused]     = useState(false)
  const bottomRef  = useRef(null)
  const intervalRef = useRef(null)

  const load = useCallback(async () => {
    if (paused) return
    try {
      const p = new URLSearchParams({ lines: lineCount })
      if (levelFilter) p.append('level', levelFilter)
      if (search)      p.append('search', search)
      const data = await get(`${SA}/system-logs?${p}`)
      if (!data.exists) { setError('Log file not found on server.'); return }
      setLogLines(data.lines || [])
      setError('')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [paused, levelFilter, search, lineCount])

  useEffect(() => {
    load()
    intervalRef.current = setInterval(load, 3000)
    return () => clearInterval(intervalRef.current)
  }, [load])

  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logLines, paused])

  const LEVEL_COLOR = {
    CRITICAL: '#F87171', ERROR: '#FC8181', WARNING: '#FCD34D',
    INFO: '#A5B4FC', DEBUG: '#6B7280',
  }
  const LEVEL_BG = {
    CRITICAL: 'rgba(220,38,38,0.18)', ERROR: 'rgba(220,38,38,0.08)',
    WARNING:  'rgba(217,119,6,0.08)', INFO: 'transparent', DEBUG: 'transparent',
  }

  return (
    <div>
      {/* Controls */}
      <div style={{ display:'flex', gap:10, marginBottom:14, flexWrap:'wrap', alignItems:'center' }}>
        <select className="sa-input" style={{ width:'auto' }}
          value={levelFilter} onChange={e => setLevel(e.target.value)}>
          <option value="">All Levels</option>
          {['ERROR','WARNING','CRITICAL','INFO','DEBUG'].map(l =>
            <option key={l} value={l}>{l}</option>)}
        </select>
        <input className="sa-input" placeholder="Search…" style={{ width:200 }}
          value={search} onChange={e => setSearch(e.target.value)} />
        <select className="sa-input" style={{ width:'auto' }}
          value={lineCount} onChange={e => setLineCount(Number(e.target.value))}>
          <option value={100}>Last 100 lines</option>
          <option value={200}>Last 200 lines</option>
          <option value={500}>Last 500 lines</option>
        </select>
        <button className={`sa-btn ${paused ? 'primary' : 'secondary'}`}
          onClick={() => setPaused(p => !p)}>
          {paused ? '▶ Resume' : '⏸ Pause'}
        </button>
        <button className="sa-btn secondary" onClick={load}>
          <RefreshCw size={12} /> Refresh
        </button>
        <span style={{ marginLeft:'auto', fontSize:11, color:'#9CA3AF' }}>
          {logLines.length} lines · {paused ? 'paused' : 'live every 3s'}
        </span>
      </div>

      {/* Log pane */}
      {loading ? <Spinner /> : error ? <Err msg={error} /> : (
        <div style={{
          background:'#0F172A', borderRadius:10, height:580,
          overflowY:'auto', fontFamily:'Consolas,"Courier New",monospace',
          fontSize:11.5, padding:'8px 0',
        }}>
          {logLines.length === 0
            ? <p style={{ color:'#6B7280', textAlign:'center', padding:'40px 0' }}>
                No log entries match the filter.
              </p>
            : logLines.map((entry, i) => (
              <div key={i} style={{
                padding:'2px 14px',
                background: LEVEL_BG[entry.level] || 'transparent',
                borderLeft: `3px solid ${entry.level === 'INFO' || entry.level === 'DEBUG'
                  ? 'transparent' : LEVEL_COLOR[entry.level]}`,
              }}>
                <span style={{
                  color: LEVEL_COLOR[entry.level] || '#A5B4FC',
                  fontWeight: entry.level === 'ERROR' || entry.level === 'CRITICAL' ? 700 : 400,
                  whiteSpace:'pre-wrap', wordBreak:'break-all',
                }}>
                  {entry.text}
                </span>
              </div>
            ))
          }
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  )
}


// ─── Root ─────────────────────────────────────────────────────────────────────

const TABS = [
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
  { id: 'platform',   label: 'Platform Health',Icon: Server          },
  { id: 'templates',    label: 'Templates & Rules', Icon: Zap          },
  { id: 'incidents',   label: 'Incidents',        Icon: AlertTriangle },
  { id: 'maintenance', label: 'Maintenance',       Icon: Clock         },
  { id: 'sla',         label: 'SLA & Performance', Icon: Gauge         },
  { id: 'command',     label: 'Command Center',    Icon: Radio         },
  { id: 'syslogs',     label: 'System Logs',       Icon: Terminal      },
]

export default function SuperAdmin() {
  const navigate = useNavigate()
  const [tab,          setTab]          = useState('overview')
  const [adminDetail,  setAdminDetail]  = useState(null)
  const [viewAdmins,   setViewAdmins]   = useState(null)
  const [pendingCount,  setPendingCount]  = useState(0)
  const [anomalyCount,  setAnomalyCount]  = useState(0)

  const username = sessionStorage.getItem('admin_username') || 'superadmin'

  useEffect(() => {
    document.title = 'SentinelEdge — Super Admin'
    return () => { document.title = 'SentinelEdge — Admin Dashboard' }
  }, [])

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
    sessionStorage.removeItem('adminVerified')
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
      case 'platform':    return <PlatformHealthTab />
      case 'templates':   return <TemplatesRulesTab />
      case 'incidents':   return <IncidentsTab />
      case 'maintenance': return <MaintenanceTab />
      case 'sla':         return <SLATab />
      case 'syslogs':     return <SystemLogsTab />
      default:            return null
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
