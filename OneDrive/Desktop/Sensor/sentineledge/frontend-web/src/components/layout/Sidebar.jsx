/**
 * src/components/layout/Sidebar.jsx
 * Collapsible sidebar with reordered nav.
 */
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Bell, TrendingUp, Terminal, BarChart2,
  History, Receipt,
  Users, Activity, ClipboardList, CheckCheck, UserCircle2, ShieldCheck,
  Settings, Thermometer, LogOut, ChevronLeft, ChevronRight,
} from 'lucide-react'

const NAV = [
  { to: '/dashboard',   icon: LayoutDashboard, label: 'Dashboard'    },
  { to: '/alerts',      icon: Bell,            label: 'Alerts'       },
  { to: '/analytics',   icon: TrendingUp,      label: 'Analytics'    },
  { to: '/logs',        icon: Terminal,        label: 'Live Logs'    },
  { to: '/reports',     icon: BarChart2,       label: 'Reports'      },
  { to: '/history',     icon: History,         label: 'History'      },
  { to: '/receipts',    icon: Receipt,         label: 'Receipts'     },
  { to: '/subscribers', icon: Users,           label: 'Subscribers', end: true },
  { to: '/health',      icon: Activity,        label: 'Health'       },
  { to: '/events',      icon: ClipboardList,   label: 'Audit Trail'  },
  { to: '/ack-log',     icon: CheckCheck,      label: 'Ack Log'      },
  { to: '/manage-admins', icon: ShieldCheck,   label: 'Admins'       },
  { to: '/profile',     icon: UserCircle2,     label: 'My Account'},
  { to: '/settings',    icon: Settings,        label: 'Settings'     },
]

export default function Sidebar({ unreadCount, collapsed, onToggle }) {
  const navigate = useNavigate()

  const handleLogout = () => {
    // end the sign-in on the server too, so the token cannot be reused on a shared PC
    const tok = sessionStorage.getItem('admin_token')
    if (tok) fetch('/api/admin/logout', { method: 'POST', headers: { Authorization: `Bearer ${tok}` } }).catch(() => {})
    sessionStorage.clear()
    navigate('/', { replace: true })
  }

  return (
    <aside className={`sidebar${collapsed ? ' sidebar-collapsed' : ''}`}>
      {/* Logo + toggle */}
      <div style={{
        padding: '12px 10px',
        borderBottom: '1px solid rgba(255,255,255,0.1)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: collapsed ? 'center' : 'space-between',
        gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, overflow: 'hidden' }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: '#7C3AED', display: 'flex', alignItems: 'center',
            justifyContent: 'center', flexShrink: 0,
          }}>
            <Thermometer size={18} color="#fff" />
          </div>
          {!collapsed && (
            <div style={{ overflow: 'hidden' }}>
              <p style={{ color: '#fff', fontWeight: 700, fontSize: 13, lineHeight: 1.2, whiteSpace: 'nowrap' }}>SentinelEdge</p>
              <p style={{ color: '#A5B4FC', fontSize: 11, whiteSpace: 'nowrap' }}>Monitoring System</p>
            </div>
          )}
        </div>

        <button
          onClick={onToggle}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{
            background: 'rgba(255,255,255,0.08)',
            border: 'none',
            borderRadius: 6,
            width: 28, height: 28,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer',
            flexShrink: 0,
            color: '#A5B4FC',
          }}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: '10px 8px', overflowY: 'auto', minHeight: 0 }}>
        {NAV.map(({ to, icon: Icon, label, end: endMatch }) => (
          <NavLink
            key={to}
            to={to}
            end={!!endMatch}
            title={collapsed ? label : undefined}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg transition-all w-full no-underline text-sm font-medium ${
                isActive ? 'text-white' : 'hover:bg-white/10'
              }`
            }
            style={({ isActive }) => ({
              background:    isActive ? '#7C3AED' : undefined,
              color:         isActive ? '#fff'    : '#C7D2FE',
              justifyContent: collapsed ? 'center' : undefined,
              marginBottom: 2,
            })}
          >
            {({ isActive }) => (
              <>
                <Icon size={16} style={{ color: isActive ? '#fff' : '#A5B4FC', flexShrink: 0 }} />
                <span className="sidebar-label truncate">{label}</span>
                {to === '/alerts' && !collapsed && unreadCount > 0 && (
                  <span style={{
                    marginLeft: 'auto', fontSize: 10, fontWeight: 700,
                    background: '#EF4444', color: '#fff',
                    borderRadius: 99, padding: '1px 6px', lineHeight: 1.6,
                  }}>
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Logout */}
      <div style={{ padding: '8px', borderTop: '1px solid rgba(255,255,255,0.1)', flexShrink: 0 }}>
        <button
          onClick={handleLogout}
          title={collapsed ? 'Logout' : undefined}
          style={{
            width: '100%', display: 'flex', alignItems: 'center',
            gap: 10, padding: '8px 12px', borderRadius: 8,
            background: 'none', border: 'none', cursor: 'pointer',
            color: '#C7D2FE', fontSize: 13, fontWeight: 500,
            justifyContent: collapsed ? 'center' : undefined,
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.08)'}
          onMouseLeave={e => e.currentTarget.style.background = 'none'}
        >
          <LogOut size={15} style={{ color: '#A5B4FC', flexShrink: 0 }} />
          <span className="sidebar-label">Logout</span>
        </button>
        {!collapsed && (
          <p style={{ textAlign: 'center', fontSize: 10, color: '#7C3AED', paddingTop: 4 }}>v1.0.0</p>
        )}
      </div>
    </aside>
  )
}
