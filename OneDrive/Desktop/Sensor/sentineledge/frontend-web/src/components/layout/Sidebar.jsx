/**
 * src/components/layout/Sidebar.jsx
 * Fixed dark sidebar with 11 navigation items.
 * Uses NavLink for automatic active-state detection.
 */
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Bell, Terminal, Archive, BarChart2,
  Receipt, Monitor, Users, Settings, Activity,
  ClipboardList, Thermometer, LogOut, CheckCheck, UserCircle2, ShieldCheck, UserRoundSearch,
  TrendingUp,
} from 'lucide-react'


const NAV = [
  { to: '/dashboard',   icon: LayoutDashboard, label: 'Dashboard'    },
  { to: '/alerts',      icon: Bell,            label: 'Alerts'        },
  { to: '/logs',        icon: Terminal,        label: 'Live Logs'     },
  { to: '/history',     icon: Archive,         label: 'History'       },
  { to: '/reports',     icon: BarChart2,       label: 'Reports'       },
  { to: '/analytics',   icon: TrendingUp,      label: 'Analytics'     },
  { to: '/receipts',    icon: Receipt,         label: 'Receipts'      },
  { to: '/monitor',     icon: Monitor,         label: 'Monitor'       },
  { to: '/subscribers', icon: Users,            label: 'Subscribers',       end: true  },
  { to: '/subscribers/profiles', icon: UserRoundSearch, label: 'Subscriber Profiles' },
  { to: '/settings',    icon: Settings,        label: 'Settings'      },
  { to: '/health',      icon: Activity,        label: 'Health'        },
  { to: '/events',      icon: ClipboardList,   label: 'Audit Trail'   },
  { to: '/ack-log',     icon: CheckCheck,      label: 'Ack Log'       },
  { to: '/profile',        icon: UserCircle2,  label: 'Admin Profile' },
  { to: '/manage-admins',  icon: ShieldCheck,  label: 'Manage Admins' },
]

export default function Sidebar({ unreadCount }) {
  const navigate = useNavigate()

  const handleLogout = () => {
    sessionStorage.clear()
    navigate('/', { replace: true })
  }

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-white/10 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
               style={{ background: '#7C3AED' }}>
            <Thermometer size={18} className="text-white" />
          </div>
          <div className="sidebar-label overflow-hidden">
            <p className="text-white font-bold text-sm leading-tight">SentinelEdge</p>
            <p className="text-xs" style={{ color: '#A5B4FC' }}>Monitoring System</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 space-y-0.5 px-2" style={{ overflowY: 'auto', minHeight: 0 }}>
        {NAV.map(({ to, icon: Icon, label, end: endMatch }) => (
          <NavLink
            key={to}
            to={to}
            end={!!endMatch}
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
                {to === '/alerts' && unreadCount > 0 && (
                  <span className="sidebar-label ml-auto text-xs font-bold bg-red-500 text-white rounded-full px-1.5 py-0.5 leading-none">
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Logout */}
      <div className="px-2 py-3 border-t border-white/10 flex-shrink-0">
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white/10 transition-all text-left text-sm font-medium"
          style={{ color: '#C7D2FE' }}
        >
          <LogOut size={16} style={{ color: '#A5B4FC', flexShrink: 0 }} />
          <span className="sidebar-label">Logout</span>
        </button>
        <p className="sidebar-label text-center text-xs py-1" style={{ color: '#7C3AED' }}>v1.0.0</p>
      </div>
    </aside>
  )
}
