/**
 * src/components/layout/Layout.jsx
 * Sidebar + Header + scrollable main content area.
 * {children} is the active page component, rendered inside <main>.
 */
import Sidebar from './Sidebar.jsx'
import Header  from './Header.jsx'

export default function Layout({ children, connectionStatus, unreadCount }) {
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar unreadCount={unreadCount} />

      <div className="layout-content" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
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
