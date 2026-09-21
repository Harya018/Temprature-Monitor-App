import React, { Component } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, useLocation } from 'react-router-dom'
import App from './App.jsx'
import SubAdminApp from './SubAdminApp.jsx'
import './index.css'

// Root-level error boundary — catches anything App misses
class RootBoundary extends Component {
  state = { error: null }
  static getDerivedStateFromError(e) { return { error: e } }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: '100vh',
          background: '#1E1B4B', color: '#fff', padding: 32, textAlign: 'center',
        }}>
          <div style={{ fontSize: 48 }}>⚠️</div>
          <h1 style={{ margin: '16px 0 8px', fontSize: 24 }}>SentinelEdge crashed</h1>
          <p style={{ color: '#C7D2FE', marginBottom: 16 }}>{this.state.error.message}</p>
          <button
            onClick={() => { this.setState({ error: null }); window.location.reload() }}
            style={{ padding: '10px 24px', background: '#7C3AED', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 15 }}
          >
            Reload Dashboard
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

/** Route /sub-admin/* to SubAdminApp, everything else to main App */
function RootRouter() {
  const loc = useLocation()
  return loc.pathname.startsWith('/sub-admin') ? <SubAdminApp /> : <App />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RootBoundary>
      <BrowserRouter>
        <RootRouter />
      </BrowserRouter>
    </RootBoundary>
  </React.StrictMode>,
)

// Fade out and remove the boot splash once React has painted
requestAnimationFrame(() => {
  const boot = document.getElementById('boot')
  if (boot) {
    boot.classList.add('fade')
    setTimeout(() => boot.remove(), 350)
  }
})
