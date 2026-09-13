/**
 * src/components/layout/Layout.jsx
 * Sidebar + Header + scrollable main content area.
 * {children} is the active page component, rendered inside <main>.
 */
import { useState } from 'react'
import Sidebar from './Sidebar.jsx'
import Header  from './Header.jsx'

export default function Layout({ children, connectionStatus, unreadCount }) {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('sidebar_collapsed') === 'true' } catch { return false }
  })

  const toggle = () => setCollapsed(prev => {
    const next = !prev
    try { localStorage.setItem('sidebar_collapsed', next) } catch {}
    return next
  })

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar unreadCount={unreadCount} collapsed={collapsed} onToggle={toggle} />

      <div className={`layout-content${collapsed ? ' sidebar-collapsed' : ''}`}
           style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <Header connectionStatus={connectionStatus} unreadCount={unreadCount} />

        <main style={{
          flex: 1,
          overflowY: 'auto',
          padding: '24px',
          backgroundColor: '#F8F9FC',
        }}>
          {children}
        </main>
      </div>
    </div>
  )
}
