/**
 * App.jsx — SentinelEdge Admin Dashboard
 * All 11 pages wired up with React Router v6.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { VolumeX } from 'lucide-react'

import useWebSocket  from './hooks/useWebSocket.js'
import useAudioAlarm from './hooks/useAudioAlarm.js'
import { fetchHealth } from './services/api.js'

import Layout          from './components/layout/Layout.jsx'
import ProtectedRoute  from './components/shared/ProtectedRoute.jsx'
import { ToastContainer, useToast } from './components/shared/Toast.jsx'

import LoginPage       from './pages/LoginPage.jsx'
import DashboardPage   from './pages/DashboardPage.jsx'
import AlertsPage      from './pages/AlertsPage.jsx'
import LogsPage        from './pages/LogsPage.jsx'
import HistoryPage     from './pages/HistoryPage.jsx'
import ReportsPage     from './pages/ReportsPage.jsx'
import ReceiptsPage    from './pages/ReceiptsPage.jsx'
import MonitorPage     from './pages/MonitorPage.jsx'
import SubscribersPage from './pages/SubscribersPage.jsx'
import SettingsPage    from './pages/SettingsPage.jsx'
import HealthPage      from './pages/HealthPage.jsx'
import EventsPage      from './pages/EventsPage.jsx'
import AckLogPage      from './pages/AckLogPage.jsx'
import AdminProfilePage from './pages/AdminProfilePage.jsx'
import ManageAdminsPage from './pages/ManageAdminsPage.jsx'
import SubscriberProfilesPage from './pages/SubscriberProfilesPage.jsx'
import SubscriberDetailPage   from './pages/SubscriberDetailPage.jsx'
import SuperAdmin            from './pages/SuperAdmin/index.jsx'
import SuperAdminLogin       from './pages/SuperAdminLogin.jsx'
import AnalyticsPage         from './pages/AnalyticsPage.jsx'

// ── Shell wraps a single page in Layout + optional alarm banner ───────────────
// Each protected route renders its own Shell so the page component
// is always directly passed as {children} into Layout → <main>.
function Shell({ children, wsData, alarm, alertCount }) {
  const connectionStatus = wsData?.connectionStatus ?? 'CONNECTING'
  const { isPlaying, currentSeverity, stopAlarm } = alarm ?? {}

  return (
    <>
      {isPlaying && (
        <div className="alarm-banner" style={{ marginLeft: 240 }}>
          <div className="flex items-center gap-3">
            <span className="status-dot bg-white animate-ping-slow" />
            <span>🔴 ALARM ACTIVE — {currentSeverity} breach detected</span>
          </div>
          <button onClick={stopAlarm} className="flex items-center gap-1.5 text-white/90 hover:text-white text-sm">
            <VolumeX size={15} /> Stop Alarm
          </button>
        </div>
      )}
      <div style={{ paddingTop: isPlaying ? 44 : 0 }}>
        <Layout connectionStatus={connectionStatus} unreadCount={alertCount}>
          {children}
        </Layout>
      </div>
    </>
  )
}

// ── Root ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [health,     setHealth]     = useState(null)
  const [thresholds, setThresholds] = useState(null)
  const [alertCount, setAlertCount] = useState(0)
  const prevConnected = useRef(null)

  // ── Impersonation: super admin opens a new tab with ?impersonate=TOKEN ────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const impToken = params.get('impersonate')
    const impName  = params.get('admin_name')
    if (impToken) {
      sessionStorage.setItem('admin_token',    impToken)
      sessionStorage.setItem('admin_username', impName || 'admin')
      sessionStorage.setItem('authenticated',  'true')
      const clean = new URL(window.location.href)
      clean.searchParams.delete('impersonate')
      clean.searchParams.delete('admin_name')
      clean.searchParams.delete('company_id')
      window.history.replaceState({}, '', clean.toString())
    }
  }, [])

  const { toasts, addToast, dismiss } = useToast()
  const alarm = useAudioAlarm()
  const { playAlarm, unlock } = alarm

  // Browsers keep sound blocked until the page has been clicked once: unlock it on the first click
  useEffect(() => {
    const u = () => { try { unlock && unlock() } catch { /* ignore */ } }
    window.addEventListener('pointerdown', u, { once: true })
    window.addEventListener('keydown', u, { once: true })
    return () => { window.removeEventListener('pointerdown', u); window.removeEventListener('keydown', u) }
  }, [unlock])

  const handleBreach = useCallback((breach) => {
    try {
      playAlarm(breach?.severity)
    } catch { /* AudioContext blocked */ }
    const name = String(breach?.parameter ?? 'value')
    const label = name.toLowerCase() === 'ph' ? 'pH' : name.charAt(0).toUpperCase() + name.slice(1)
    const unit = name.toLowerCase() === 'temperature' ? '°C' : ''
    const num = Number(breach?.value)
    const val = Number.isFinite(num) ? (Math.abs(num) >= 100 ? num.toFixed(1) : num.toFixed(2)) : '—'
    const rel = breach?.direction === 'low' ? 'below' : 'above'
    addToast({
      type: 'error',
      message: `🔴 ${label} ALERT: ${val}${unit} is ${rel} the limit ${breach?.threshold ?? '—'}${unit} — ${breach?.severity ?? ''}`,
      duration: 12000,
    })
  }, [playAlarm, addToast])

  const wsData = useWebSocket({ onBreach: handleBreach })

  useEffect(() => {
    const connected = wsData.isConnected
    if (prevConnected.current === null) { prevConnected.current = connected; return }
    if (prevConnected.current && !connected)
      addToast({ type: 'warning', message: '🔌 Connection lost. Reconnecting…' })
    if (!prevConnected.current && connected)
      addToast({ type: 'success', message: '✅ Connection restored.' })
    prevConnected.current = connected
  }, [wsData.isConnected, addToast])

  useEffect(() => {
    if (wsData.connectionStatus === 'SESSION EXPIRED')
      addToast({ type: 'warning', message: 'Your login session has expired. Log out and log in again to resume live data.', duration: 15000 })
  }, [wsData.connectionStatus, addToast])

  const loadHealth = useCallback(async () => {
    try {
      const h = await fetchHealth()
      setHealth(h)
      if (h.thresholds)
        setThresholds({ temperature: { high: h.thresholds.temp_high, low: h.thresholds.temp_low } })
    } catch { /* silent */ }
  }, [])

  useEffect(() => {
    loadHealth()
    const t = setInterval(loadHealth, 30000)
    // Refresh straight away when the user comes back to the tab
    const onVisible = () => { if (document.visibilityState === 'visible') loadHealth() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVisible) }
  }, [loadHealth])

  // Shorthand to wrap any page in the Shell + ProtectedRoute
  const protect = (page) => (
    <ProtectedRoute>
      <Shell wsData={wsData} alarm={alarm} alertCount={alertCount}>
        {page}
      </Shell>
    </ProtectedRoute>
  )

  return (
    <>
      <Routes>
        {/* Public */}
        <Route path="/" element={<LoginPage />} />

        {/* Monitor — full screen, no sidebar */}
        <Route path="/monitor" element={
          <ProtectedRoute>
            <MonitorPage wsData={wsData} thresholds={thresholds} />
          </ProtectedRoute>
        } />

        {/* All protected pages — each renders directly inside Layout > main */}
        <Route path="/dashboard"   element={protect(<DashboardPage wsData={wsData} health={health} thresholds={thresholds} onAlertCount={setAlertCount} />)} />
        <Route path="/alerts"      element={protect(<AlertsPage onCountChange={setAlertCount} />)} />
        <Route path="/logs"        element={protect(<LogsPage />)} />
        <Route path="/history"     element={protect(<HistoryPage />)} />
        <Route path="/reports"     element={protect(<ReportsPage />)} />
        <Route path="/receipts"    element={protect(<ReceiptsPage />)} />
        <Route path="/subscribers" element={protect(<SubscribersPage />)} />
        <Route path="/settings"    element={protect(<SettingsPage />)} />
        <Route path="/health"      element={protect(<HealthPage />)} />
        <Route path="/events"      element={protect(<EventsPage />)} />
        <Route path="/ack-log"     element={protect(<AckLogPage wsData={wsData} />)} />
        <Route path="/profile"        element={protect(<AdminProfilePage />)} />
        <Route path="/manage-admins"   element={protect(<ManageAdminsPage />)} />
        <Route path="/subscribers/profiles"     element={protect(<SubscriberProfilesPage />)} />
        <Route path="/subscribers/profiles/:id" element={protect(<SubscriberDetailPage />)} />

        <Route path="/analytics" element={protect(<AnalyticsPage wsData={wsData} />)} />

        {/* Super Admin portal — login + dashboard */}
        <Route path="/super-admin/login" element={<SuperAdminLogin />} />
        <Route path="/super-admin"       element={<SuperAdmin />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </>
  )
}
