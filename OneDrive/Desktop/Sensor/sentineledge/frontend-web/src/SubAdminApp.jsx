/**
 * SubAdminApp.jsx — Sub-Admin Dashboard
 *
 * Identical to the main admin dashboard EXCEPT:
 *   - Settings page is hidden/inaccessible
 *   - Admin Profile page is hidden/inaccessible
 *   - Login uses name + password (admins table) instead of a passcode
 *   - After login, role is checked: 'sub' → this dashboard; 'main' → redirect to /
 *
 * Routes are prefixed with /sub-admin/*
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Bell, Terminal, Archive, BarChart2,
  Receipt, Monitor, Users, Activity, ClipboardList,
  Thermometer, LogOut, CheckCheck, Eye, EyeOff, ShieldAlert,
  User, Lock,
} from 'lucide-react'
import { VolumeX } from 'lucide-react'

import useWebSocket  from './hooks/useWebSocket.js'
import useAudioAlarm from './hooks/useAudioAlarm.js'
import useAdminIdentity from './hooks/useAdminIdentity.js'
import { ToastContainer, useToast } from './components/shared/Toast.jsx'
import { fetchHealth } from './services/api.js'

// Pages visible to sub-admins (no Settings, no Admin Profile)
import DashboardPage   from './pages/DashboardPage.jsx'
import AlertsPage      from './pages/AlertsPage.jsx'
import LogsPage        from './pages/LogsPage.jsx'
import HistoryPage     from './pages/HistoryPage.jsx'
import ReportsPage     from './pages/ReportsPage.jsx'
import ReceiptsPage    from './pages/ReceiptsPage.jsx'
import MonitorPage     from './pages/MonitorPage.jsx'
import SubscribersPage from './pages/SubscribersPage.jsx'
import HealthPage      from './pages/HealthPage.jsx'
import EventsPage      from './pages/EventsPage.jsx'
import AckLogPage      from './pages/AckLogPage.jsx'

// ── Sub-Admin Login ───────────────────────────────────────────────────────────
function SubAdminLoginPage() {
  const [name,    setName]    = useState('')
  const [pwd,     setPwd]     = useState('')
  const [showPwd, setShowPwd] = useState(false)
  const [error,   setError]   = useState('')
  const [loading, setLoading] = useState(false)
  const [shaking, setShaking] = useState(false)
  const nameRef  = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    document.title = 'SentinelEdge — Sub Admin Login'
    if (sessionStorage.getItem('subAdminAuthenticated') === 'true') {
      navigate('/sub-admin/dashboard', { replace: true })
    }
    nameRef.current?.focus()
  }, [navigate])

  const shake = (msg) => {
    setShaking(true)
    setError(msg)
    setPwd('')
    setTimeout(() => setShaking(false), 500)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!name.trim()) { shake('Name is required'); return }
    if (!pwd.trim())  { shake('Password is required'); return }
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/auth/admin-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), password: pwd }),
      })
      const data = await res.json()
      if (!res.ok) {
        shake(data.detail?.message || 'Invalid credentials')
        return
      }
      if (data.role === 'main') {
        shake('Please use the main admin dashboard to log in as main admin.')
        return
      }
      sessionStorage.setItem('subAdminAuthenticated', 'true')
      sessionStorage.setItem('subAdminName', data.name)
      sessionStorage.setItem('subAdminToken', data.token)
      navigate('/sub-admin/dashboard', { replace: true })
    } catch {
      shake('Connection failed. Check your server.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={saStyles.page}>
      <div className={shaking ? 'animate-shake' : ''} style={saStyles.card}>

        {/* LEFT PANEL */}
        <div style={saStyles.leftPanel} className="sentinel-card-left">
          <div style={{ ...saStyles.shape, ...saStyles.shape1 }} />
          <div style={{ ...saStyles.shape, ...saStyles.shape2 }} />
          <div style={{ ...saStyles.shape, ...saStyles.shape3 }} />
          <div style={{ ...saStyles.shape, ...saStyles.shape4 }} />
          <div style={saStyles.curveDivider} />
          <div style={saStyles.leftContent}>
            <div style={saStyles.leftIconWrap}>
              <ShieldAlert size={44} color="#fff" strokeWidth={1.5} />
            </div>
            <p style={saStyles.leftTitle}>SUB</p>
            <p style={{ ...saStyles.leftTitle, fontSize: 34 }}>ADMIN</p>
            <p style={saStyles.leftSubtitle}>PORTAL</p>
          </div>
        </div>

        {/* RIGHT PANEL */}
        <div style={saStyles.rightPanel} className="sentinel-card-right">

          <div style={saStyles.mobileHeader} className="mobile-only-header">
            <div style={saStyles.mobileIconWrap}>
              <ShieldAlert size={28} color="#fff" />
            </div>
            <span style={saStyles.mobileName}>Sub-Admin</span>
          </div>

          <div style={saStyles.avatarCircle}>
            <User size={32} color="#fff" strokeWidth={2} />
          </div>

          <h1 style={saStyles.loginHeading}>LOGIN</h1>

          <form onSubmit={handleSubmit} style={saStyles.form} noValidate>

            <div style={saStyles.fieldWrap} className="underline-field">
              <User size={18} color="#9CA3AF" style={{ flexShrink: 0 }} />
              <input
                ref={nameRef}
                type="text"
                placeholder="Your name"
                value={name}
                onChange={e => { setName(e.target.value); setError('') }}
                autoComplete="username"
                autoCapitalize="none"
                style={saStyles.underlineInput}
                className="underline-input"
              />
            </div>

            <div style={saStyles.fieldWrap} className="underline-field">
              <Lock size={18} color="#9CA3AF" style={{ flexShrink: 0 }} />
              <input
                type={showPwd ? 'text' : 'password'}
                placeholder="Password"
                value={pwd}
                onChange={e => { setPwd(e.target.value); setError('') }}
                autoComplete="current-password"
                style={saStyles.underlineInput}
                className="underline-input"
              />
              <button type="button" onClick={() => setShowPwd(v => !v)} style={saStyles.eyeBtn} tabIndex={-1}>
                {showPwd ? <EyeOff size={17} color="#9CA3AF" /> : <Eye size={17} color="#9CA3AF" />}
              </button>
            </div>

            {error && <p style={saStyles.errorText}>{error}</p>}

            <button
              type="submit"
              disabled={loading || !name.trim() || !pwd.trim()}
              style={{ ...saStyles.loginBtn, opacity: (loading || !name.trim() || !pwd.trim()) ? 0.65 : 1 }}
              className="login-btn-hover"
            >
              {loading ? 'Signing in…' : 'LOGIN'}
            </button>
          </form>

          <p style={saStyles.adminLink}>
            Main admin?{' '}
            <a href="/" style={{ color: '#7C3AED', fontWeight: 600, textDecoration: 'underline' }}>
              Use main dashboard
            </a>
          </p>

          <p style={saStyles.footer}>SentinelEdge v1.0.0 · Sub-Admin Portal</p>
        </div>
      </div>

      <style>{`
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          20%       { transform: translateX(-10px); }
          40%       { transform: translateX(10px); }
          60%       { transform: translateX(-7px); }
          80%       { transform: translateX(7px); }
        }
        .animate-shake { animation: shake 0.45s ease-in-out; }
        .underline-input:focus { outline: none; }
        .underline-field:focus-within { border-bottom-color: #7C3AED !important; }
        .login-btn-hover:hover:not(:disabled) {
          background: #6D28D9 !important;
          transform: translateY(-1px);
          box-shadow: 0 6px 20px rgba(124,58,237,0.4);
        }
        .login-btn-hover { transition: all 0.2s ease; }
        .mobile-only-header { display: none; }
        @media (max-width: 767px) {
          .sentinel-card-left  { display: none !important; }
          .sentinel-card-right { border-radius: 0 !important; min-height: 100svh !important; width: 100% !important; }
          .mobile-only-header  { display: flex !important; }
        }
      `}</style>
    </div>
  )
}

const saStyles = {
  page: {
    minHeight: '100svh', display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: '#1E1B4B', padding: '1.5rem', fontFamily: "'Inter', 'Segoe UI', sans-serif",
  },
  card: {
    display: 'flex', flexDirection: 'row', width: '100%', maxWidth: 900,
    borderRadius: 24, overflow: 'hidden', boxShadow: '0 25px 60px rgba(0,0,0,0.45)',
    position: 'relative', minHeight: 520, background: '#fff',
  },
  leftPanel: {
    width: '45%', position: 'relative', overflow: 'hidden',
    background: 'linear-gradient(135deg, #3B1F8C 0%, #1E1B4B 100%)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
  },
  shape: { position: 'absolute', borderRadius: 20, pointerEvents: 'none' },
  shape1: { width: 280, height: 280, background: 'rgba(92,53,176,0.45)', top: '-60px', left: '-80px', transform: 'rotate(-20deg)' },
  shape2: { width: 220, height: 220, background: 'rgba(76,42,158,0.55)', bottom: '-50px', left: '-40px', transform: 'rotate(-35deg)' },
  shape3: { width: 200, height: 160, background: 'rgba(91,53,176,0.35)', top: '45%', right: '-30px', transform: 'rotate(-15deg)' },
  shape4: { width: 160, height: 120, background: 'rgba(109,40,217,0.3)', top: '10px', right: '20px', transform: 'rotate(12deg)' },
  curveDivider: {
    position: 'absolute', top: 0, right: -40, width: 80, height: '100%',
    background: '#fff', clipPath: 'ellipse(50% 100% at 100% 50%)', zIndex: 2,
  },
  leftContent: {
    position: 'relative', zIndex: 3, display: 'flex', flexDirection: 'column',
    alignItems: 'center', gap: 2, paddingRight: 32,
  },
  leftIconWrap: { marginBottom: 10, opacity: 0.9 },
  leftTitle: { color: '#fff', fontSize: 38, fontWeight: 900, letterSpacing: '0.12em', lineHeight: 1, margin: 0, textShadow: '0 2px 8px rgba(0,0,0,0.3)' },
  leftSubtitle: { color: 'rgba(255,255,255,0.75)', fontSize: 15, fontWeight: 600, letterSpacing: '0.3em', margin: '8px 0 0' },
  rightPanel: {
    flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
    justifyContent: 'center', padding: '3rem 2.5rem', background: '#fff', gap: 0,
  },
  mobileHeader: { display: 'none', alignItems: 'center', gap: 10, marginBottom: 28 },
  mobileIconWrap: {
    width: 42, height: 42, borderRadius: 12,
    background: 'linear-gradient(135deg, #7C3AED, #5B21B6)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  mobileName: { color: '#1E1B4B', fontSize: 20, fontWeight: 800, letterSpacing: '-0.02em' },
  avatarCircle: {
    width: 72, height: 72, borderRadius: '50%', background: '#7C3AED',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 4px 20px rgba(124,58,237,0.4)', marginBottom: 16,
  },
  loginHeading: { fontSize: 26, fontWeight: 800, color: '#1E1B4B', letterSpacing: '0.1em', margin: '0 0 28px 0' },
  form: { width: '100%', maxWidth: 320, display: 'flex', flexDirection: 'column', gap: 0 },
  fieldWrap: {
    display: 'flex', alignItems: 'center', gap: 10,
    borderBottom: '2px solid #E5E7EB', paddingBottom: 10, marginBottom: 24, transition: 'border-color 0.2s',
  },
  underlineInput: { flex: 1, border: 'none', outline: 'none', background: 'transparent', fontSize: 15, color: '#111827', padding: '4px 0' },
  eyeBtn: { background: 'none', border: 'none', cursor: 'pointer', padding: '0 2px', display: 'flex', alignItems: 'center', flexShrink: 0 },
  errorText: { color: '#DC2626', fontSize: 13, fontWeight: 500, textAlign: 'center', marginBottom: 12, marginTop: -8 },
  loginBtn: {
    width: '100%', padding: '13px 0', background: '#7C3AED', color: '#fff',
    border: 'none', borderRadius: 10, fontSize: 15, fontWeight: 700,
    letterSpacing: '0.08em', cursor: 'pointer', marginTop: 8, marginBottom: 20,
  },
  adminLink: { color: '#9CA3AF', fontSize: 13, textAlign: 'center', marginBottom: 6 },
  footer: { color: '#9CA3AF', fontSize: 12, textAlign: 'center', marginTop: 4 },
}

// ── Sub-Admin Sidebar ─────────────────────────────────────────────────────────
const SUB_NAV = [
  { to: '/sub-admin/dashboard',   icon: LayoutDashboard, label: 'Dashboard'    },
  { to: '/sub-admin/alerts',      icon: Bell,            label: 'Alerts'        },
  { to: '/sub-admin/logs',        icon: Terminal,        label: 'Live Logs'     },
  { to: '/sub-admin/history',     icon: Archive,         label: 'History'       },
  { to: '/sub-admin/reports',     icon: BarChart2,       label: 'Reports'       },
  { to: '/sub-admin/receipts',    icon: Receipt,         label: 'Receipts'      },
  { to: '/sub-admin/monitor',     icon: Monitor,         label: 'Monitor'       },
  { to: '/sub-admin/subscribers', icon: Users,           label: 'Subscribers'   },
  { to: '/sub-admin/health',      icon: Activity,        label: 'Health'        },
  { to: '/sub-admin/events',      icon: ClipboardList,   label: 'Audit Trail'   },
  { to: '/sub-admin/ack-log',     icon: CheckCheck,      label: 'Ack Log'       },
  // ✖ No Settings, ✖ No Admin Profile
]

function SubAdminSidebar({ unreadCount }) {
  const navigate = useNavigate()
  const name = sessionStorage.getItem('subAdminName') || 'Sub-Admin'

  const handleLogout = () => {
    sessionStorage.removeItem('subAdminAuthenticated')
    sessionStorage.removeItem('subAdminName')
    sessionStorage.removeItem('subAdminToken')
    navigate('/sub-admin', { replace: true })
  }

  return (
    <aside className="sidebar" style={{ overflowY: 'auto' }}>
      <div className="px-4 py-4 border-b border-white/10 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
               style={{ background: '#7C3AED' }}>
            <Thermometer size={18} className="text-white" />
          </div>
          <div className="sidebar-label overflow-hidden">
            <p className="text-white font-bold text-sm leading-tight">SentinelEdge</p>
            <p className="text-xs" style={{ color: '#A5B4FC' }}>Sub-Admin: {name}</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 py-3 space-y-0.5 px-2">
        {SUB_NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg transition-all w-full no-underline text-sm font-medium ${
                isActive ? 'text-white' : 'hover:bg-white/10'
              }`
            }
            style={({ isActive }) => ({
              background: isActive ? '#7C3AED' : undefined,
              color:      isActive ? '#fff'    : '#C7D2FE',
            })}
          >
            {({ isActive }) => (
              <>
                <Icon size={16} style={{ color: isActive ? '#fff' : '#A5B4FC', flexShrink: 0 }} />
                <span className="sidebar-label truncate">{label}</span>
                {to === '/sub-admin/alerts' && unreadCount > 0 && (
                  <span className="sidebar-label ml-auto text-xs font-bold bg-red-500 text-white rounded-full px-1.5 py-0.5 leading-none">
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="px-2 py-3 border-t border-white/10 flex-shrink-0">
        <button onClick={handleLogout}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white/10 transition-all text-left text-sm font-medium"
                style={{ color: '#C7D2FE' }}>
          <LogOut size={16} style={{ color: '#A5B4FC', flexShrink: 0 }} />
          <span className="sidebar-label">Logout</span>
        </button>
        <p className="sidebar-label text-center text-xs py-1" style={{ color: '#7C3AED' }}>v1.0.0 · Sub-Admin</p>
      </div>
    </aside>
  )
}

// ── Protected route for sub-admin ─────────────────────────────────────────────
function SubAdminProtected({ children }) {
  if (sessionStorage.getItem('subAdminAuthenticated') !== 'true') {
    return <Navigate to="/sub-admin" replace />
  }
  return children
}

// ── Layout wrapper ────────────────────────────────────────────────────────────
function SubAdminLayout({ children, connectionStatus, unreadCount }) {
  const me = useAdminIdentity()
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <SubAdminSidebar unreadCount={unreadCount} />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', marginLeft: 240 }}>
        <header className="flex items-center justify-between px-6 bg-white border-b border-gray-100"
                style={{ height: 64, position: 'sticky', top: 0, zIndex: 40, flexShrink: 0 }}>
          <span className="text-sm font-bold text-gray-700 truncate">
            {me?.company_name ? `${me.company_name} — Sub-Admin Dashboard` : 'Sub-Admin Dashboard'}
          </span>
          <span className={`text-xs font-bold px-2 py-1 rounded-full ${
            connectionStatus === 'LIVE' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
          }`}>
            {connectionStatus}
          </span>
        </header>
        <main style={{ flex: 1, overflowY: 'auto', padding: '24px', backgroundColor: '#F8F9FC' }}>
          {children}
        </main>
      </div>
    </div>
  )
}

// ── Root sub-admin app ────────────────────────────────────────────────────────
export default function SubAdminApp() {
  // Hold routing until an impersonation code is redeemed; otherwise
  // SubAdminProtected redirects first and strips imp_code from the URL.
  const [impPending, setImpPending] = useState(
    () => new URLSearchParams(window.location.search).has('imp_code')
  )
  const [alertCount, setAlertCount] = useState(0)
  const [health,     setHealth]     = useState(null)
  const [thresholds, setThresholds] = useState(null)

  // ── Impersonation: super admin opens a new tab with ?imp_code=CODE ─────────
  // The code is single-use and expires in 2 minutes; we redeem it immediately
  // to get the actual session token, which is never exposed in the URL.
  useEffect(() => {
    const params  = new URLSearchParams(window.location.search)
    const impCode = params.get('imp_code')
    const impName = params.get('admin_name')
    if (!impCode) return

    // Strip params from URL first so they don't linger in history
    const clean = new URL(window.location.href)
    clean.searchParams.delete('imp_code')
    clean.searchParams.delete('admin_name')
    clean.searchParams.delete('company_id')
    window.history.replaceState({}, '', clean.toString())

    fetch('/api/super-admin/admin-control/redeem-impersonation', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ code: impCode }),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        sessionStorage.setItem('admin_token',           data.token)
        sessionStorage.setItem('admin_username',        impName || 'admin')
        sessionStorage.setItem('subAdminAuthenticated', 'true')
        sessionStorage.setItem('authenticated',         'true')
      })
      .catch(() => {
        // Code was invalid or already used — leave auth state empty so the
        // normal login page renders instead of an authenticated shell.
      })
      .finally(() => setImpPending(false))
  }, [])

  useEffect(() => {
    document.title = 'SentinelEdge — Sub Admin'
    return () => { document.title = 'SentinelEdge — Admin Dashboard' }
  }, [])
  const { toasts, addToast, dismiss } = useToast()
  const alarm = useAudioAlarm()
  const { playAlarm } = alarm

  const handleBreach = useCallback((breach) => {
    try { playAlarm(breach?.severity) } catch {}
    addToast({ type: 'error', message: `⚠️ BREACH: ${breach?.value?.toFixed(1) ?? '—'}°C`, duration: 8000 })
  }, [playAlarm, addToast])

  const wsData = useWebSocket({ onBreach: handleBreach })
  const connectionStatus = wsData?.connectionStatus ?? 'CONNECTING'
  const { isPlaying, currentSeverity, stopAlarm } = alarm

  const loadHealth = useCallback(async () => {
    try {
      const h = await fetchHealth()
      setHealth(h)
      if (h.thresholds)
        setThresholds({ temperature: { high: h.thresholds.temp_high, low: h.thresholds.temp_low } })
    } catch {}
  }, [])

  useEffect(() => {
    loadHealth()
    const t = setInterval(loadHealth, 30000)
    // Refresh straight away when the user comes back to the tab
    const onVisible = () => { if (document.visibilityState === 'visible') loadHealth() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVisible) }
  }, [loadHealth])

  const protect = (page) => (
    <SubAdminProtected>
      <SubAdminLayout connectionStatus={connectionStatus} unreadCount={alertCount}>
        {isPlaying && (
          <div className="alarm-banner" style={{ position: 'fixed', top: 0, left: 240, right: 0, zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 24px', background: '#991b1b', color: '#fff' }}>
            <span>🔴 ALARM — {currentSeverity} breach</span>
            <button onClick={stopAlarm} style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#fff', background: 'none', border: 'none', cursor: 'pointer', fontSize: 13 }}>
              <VolumeX size={15} /> Stop Alarm
            </button>
          </div>
        )}
        {page}
      </SubAdminLayout>
    </SubAdminProtected>
  )

  if (impPending) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', color: '#6B7280', fontSize: 14 }}>
        Signing in as admin…
      </div>
    )
  }

  return (
    <>
      <Routes>
        <Route path="/sub-admin"            element={<SubAdminLoginPage />} />
        <Route path="/sub-admin/dashboard"  element={protect(<DashboardPage wsData={wsData} health={health} thresholds={thresholds} onAlertCount={setAlertCount} />)} />
        <Route path="/sub-admin/alerts"     element={protect(<AlertsPage onCountChange={setAlertCount} />)} />
        <Route path="/sub-admin/logs"       element={protect(<LogsPage />)} />
        <Route path="/sub-admin/history"    element={protect(<HistoryPage />)} />
        <Route path="/sub-admin/reports"    element={protect(<ReportsPage />)} />
        <Route path="/sub-admin/receipts"   element={protect(<ReceiptsPage />)} />
        <Route path="/sub-admin/monitor"    element={<SubAdminProtected><MonitorPage wsData={wsData} thresholds={thresholds} /></SubAdminProtected>} />
        <Route path="/sub-admin/subscribers" element={protect(<SubscribersPage />)} />
        <Route path="/sub-admin/health"     element={protect(<HealthPage />)} />
        <Route path="/sub-admin/events"     element={protect(<EventsPage />)} />
        <Route path="/sub-admin/ack-log"    element={protect(<AckLogPage wsData={wsData} />)} />
        {/* Redirect any unknown /sub-admin/* to login */}
        <Route path="/sub-admin/*"          element={<Navigate to="/sub-admin" replace />} />
      </Routes>
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </>
  )
}
