/**
 * src/components/layout/Header.jsx
 * Sticky top bar — page title from useLocation, IST clock, connection badge, monitor link.
 */
import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Bell, WifiOff, Monitor, Sun, Moon } from 'lucide-react'
import { nowIST } from '../../utils/time.js'
import { useTheme } from '../../hooks/useTheme.js'

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
}

export default function Header({ connectionStatus, unreadCount }) {
  const [time, setTime] = useState(nowIST())
  const location = useLocation()
  const navigate = useNavigate()
  const { isDark, toggle: toggleTheme } = useTheme()

  useEffect(() => {
    const t = setInterval(() => setTime(nowIST()), 1000)
    return () => clearInterval(t)
  }, [])

  const title = TITLES[location.pathname] || 'SentinelEdge'
  const isLive = connectionStatus === 'LIVE'
  const isReconnecting = connectionStatus === 'RECONNECTING'

  return (
    <header
      className="flex items-center justify-between px-6 bg-white border-b border-gray-100"
      style={{ height: 64, position: 'sticky', top: 0, zIndex: 40, flexShrink: 0 }}
    >
      <h1 className="text-lg font-bold text-gray-900">{title}</h1>

      <div className="flex items-center gap-4">
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

        {/* Alert bell */}
        <button
          onClick={() => navigate('/alerts')}
          className="relative p-2 rounded-lg hover:bg-gray-100 transition-colors text-gray-500"
          title="Alerts"
        >
          <Bell size={17} />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 text-xs font-bold bg-red-500 text-white rounded-full w-4 h-4 flex items-center justify-center leading-none">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>
      </div>
    </header>
  )
}
