/**
 * src/components/layout/Header.jsx
 * Sticky top bar — page title from useLocation, IST clock, connection badge, monitor link.
 */
import { useState, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Bell, WifiOff, Monitor, Sun, Moon, Building2, Network } from 'lucide-react'
import { nowIST } from '../../utils/time.js'
import { useTheme } from '../../hooks/useTheme.js'
import useAdminIdentity from '../../hooks/useAdminIdentity.js'
import useSystemNotices from '../../hooks/useSystemNotices.js'

const TITLES = {
  '/dashboard':   'Dashboard',
  '/alerts':      'Alert History',
  '/logs':        'Live Logs',
  '/history':     'Backup & History',
  '/reports':     'Daily Reports',
  '/receipts':    'Delivery Receipts',
  '/monitor':     'Monitor Mode',
  '/subscribers': 'Subscribers',
  '/settings':    'Settings',
  '/health':      'System Health',
  '/events':      'Audit Trail',
  '/analytics':   'Analytics',
  '/ack-log':     'Acknowledgement Log',
  '/profile':     'My Account',
  '/manage-admins': 'Admins',
}

export default function Header({ connectionStatus, unreadCount }) {
  const [time, setTime] = useState(nowIST())
  const location = useLocation()
  const navigate = useNavigate()
  const { isDark, toggle: toggleTheme } = useTheme()
  const me = useAdminIdentity()
  const { notices, hide } = useSystemNotices()
  const [open, setOpen] = useState(false)
  const bellRef = useRef(null)

  useEffect(() => {
    const t = setInterval(() => setTime(nowIST()), 1000)
    return () => clearInterval(t)
  }, [])

  // close the notification panel when clicking elsewhere
  useEffect(() => {
    const onDown = (e) => { if (bellRef.current && !bellRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  // once per sign-in, open the panel by itself when there is something to do (Tailscale off / not connected)
  useEffect(() => {
    if (!notices.length) return
    try {
      const tok = sessionStorage.getItem('admin_token') || ''
      if (sessionStorage.getItem('se_notice_shown') === tok) return      // already opened for this sign-in
      sessionStorage.setItem('se_notice_shown', tok)
    } catch { /* ignore */ }
    setOpen(true)
  }, [notices.length])

  const badge = (unreadCount || 0) + notices.length

  const title = TITLES[location.pathname] || 'SentinelEdge'
  const isLive = connectionStatus === 'LIVE'
  const isReconnecting = connectionStatus === 'RECONNECTING'

  return (
    <header
      className="flex items-center justify-between px-6 bg-white border-b border-gray-100"
      style={{ height: 64, position: 'sticky', top: 0, zIndex: 40, flexShrink: 0 }}
    >
      <div className="flex items-center gap-3 min-w-0">
        <h1 className="text-lg font-bold text-gray-900 whitespace-nowrap">{title}</h1>
        {me?.company_name && (
          <span
            className="hidden md:inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full truncate"
            style={{ background: '#F3F0FF', color: '#6D28D9', maxWidth: 360 }}
            title={me.company_name}
          >
            <Building2 size={12} style={{ flexShrink: 0 }} />
            <span className="truncate">{me.company_name}</span>
          </span>
        )}
      </div>

      <div className="flex items-center gap-4">
        {me?.role === 'sub' && (
          <span className="text-[11px] font-semibold px-2 py-1 rounded-full bg-gray-100 text-gray-600" title="You can view everything and acknowledge alerts, but not change settings">
            Read-only account
          </span>
        )}
        {/* Connection badge */}
        <div className="flex items-center gap-1.5">
          {isLive ? (
            <>
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
              </span>
              <span className="text-xs font-bold text-emerald-700 tracking-wide">LIVE</span>
            </>
          ) : isReconnecting ? (
            <>
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500" />
              </span>
              <span className="text-xs font-bold text-amber-700 tracking-wide">RECONNECTING</span>
            </>
          ) : (
            <>
              <WifiOff size={13} className="text-gray-400" />
              <span className="text-xs font-bold text-gray-500 tracking-wide">CONNECTING</span>
            </>
          )}
        </div>

        {/* IST clock */}
        <span className="text-xs font-mono text-gray-400 hidden sm:block">IST {time}</span>

        {/* Dark mode toggle */}
        <button
          onClick={toggleTheme}
          className="p-2 rounded-lg hover:bg-gray-100 transition-colors text-gray-500"
          title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {isDark ? <Sun size={17} /> : <Moon size={17} />}
        </button>

        {/* Monitor mode link */}
        <button
          onClick={() => navigate('/monitor')}
          className="p-2 rounded-lg hover:bg-gray-100 transition-colors text-gray-500"
          title="Full-screen monitor mode"
        >
          <Monitor size={17} />
        </button>

        {/* Notifications: alerts + system notices (e.g. connect Tailscale) */}
        <div className="relative" ref={bellRef}>
          <button
            onClick={() => setOpen(o => !o)}
            className="relative p-2 rounded-lg hover:bg-gray-100 transition-colors text-gray-500"
            title="Notifications"
            aria-label="Notifications"
          >
            <Bell size={17} />
            {badge > 0 && (
              <span className={`absolute -top-0.5 -right-0.5 text-xs font-bold text-white rounded-full w-4 h-4 flex items-center justify-center leading-none ${unreadCount > 0 ? 'bg-red-500' : 'bg-amber-500'}`}>
                {badge > 9 ? '9+' : badge}
              </span>
            )}
          </button>
          {open && (
            <div
              className="absolute right-0 mt-2 bg-white border border-gray-200 rounded-xl shadow-lg"
              style={{ width: 340, zIndex: 60 }}
              role="dialog"
              aria-label="Notifications panel"
            >
              <div className="px-4 py-3 border-b border-gray-100 text-sm font-semibold text-gray-800">Notifications</div>
              <div className="max-h-96 overflow-y-auto">
                {unreadCount > 0 && (
                  <button
                    className="w-full text-left px-4 py-3 hover:bg-gray-50 border-b border-gray-100"
                    onClick={() => { setOpen(false); navigate('/alerts') }}
                  >
                    <p className="text-sm font-semibold text-red-600">{unreadCount} alert{unreadCount === 1 ? '' : 's'} not acknowledged</p>
                    <p className="text-xs text-gray-500 mt-0.5">Open the alerts list</p>
                  </button>
                )}
                {notices.map(n => (
                  <div key={n.id} className="px-4 py-3 border-b border-gray-100" data-notice={n.id}>
                    <div className="flex items-start gap-2">
                      <Network size={16} className="text-amber-500 mt-0.5 flex-shrink-0" />
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-gray-800">{n.title}</p>
                        <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{n.text}</p>
                        <div className="flex gap-2 mt-2">
                          <button
                            className="text-xs font-semibold px-2.5 py-1 rounded-md text-white"
                            style={{ background: '#7C3AED' }}
                            onClick={() => { setOpen(false); navigate(n.link) ; setTimeout(() => { const el = document.getElementById('tailscale'); if (el) el.scrollIntoView({ behavior: 'smooth' }) }, 400) }}
                          >
                            How to connect
                          </button>
                          <button className="text-xs px-2.5 py-1 rounded-md border border-gray-200 text-gray-600" onClick={() => hide(n)}>
                            Remind me later
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
                {unreadCount === 0 && notices.length === 0 && (
                  <p className="px-4 py-6 text-sm text-gray-400 text-center">Nothing new</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
