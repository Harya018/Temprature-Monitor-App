/**
 * src/components/dashboard/SuperAdminNotices.jsx
 * Shows what the super admin sent to this admin's company: maintenance mode,
 * the latest platform broadcast, and unread direct messages.
 * Data: GET /api/admin/inbox (refreshed every 60 s).
 */
import { useState, useEffect, useCallback } from 'react'
import { Megaphone, Mail, Wrench, X } from 'lucide-react'

const DISMISS_KEY = 'se_dismissed_broadcast'

function authHeaders() {
  const t = sessionStorage.getItem('admin_token')
  return t ? { Authorization: `Bearer ${t}` } : {}
}

function readDismissed() {
  try { return Number(localStorage.getItem(DISMISS_KEY)) || 0 } catch { return 0 }
}

function fmt(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d) ? '' : d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

const box = (bg, border) => ({
  background: bg, border: `1px solid ${border}`, borderRadius: 10,
  padding: '10px 14px', display: 'flex', gap: 10, alignItems: 'flex-start', fontSize: 13,
})

export default function SuperAdminNotices() {
  const [inbox, setInbox] = useState(null)
  const [dismissedId, setDismissedId] = useState(readDismissed)

  const load = useCallback(() => {
    fetch('/api/admin/inbox', { headers: authHeaders() })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d) setInbox(d) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [load])

  const markRead = (id) => {
    fetch(`/api/admin/inbox/messages/${id}/read`, { method: 'POST', headers: authHeaders() })
      .then(r => {
        if (!r.ok) return
        setInbox(prev => prev && {
          ...prev,
          messages: prev.messages.map(m => (m.id === id ? { ...m, read_at: new Date().toISOString() } : m)),
        })
      })
      .catch(() => {})
  }

  const dismissBroadcast = (id) => {
    setDismissedId(id)
    try { localStorage.setItem(DISMISS_KEY, String(id)) } catch { /* storage blocked */ }
  }

  if (!inbox) return null
  const unread = (inbox.messages || []).filter(m => !m.read_at)
  const broadcast = (inbox.broadcasts || [])[0]
  const showBroadcast = broadcast && broadcast.id > dismissedId
  if (!inbox.maintenance && !unread.length && !showBroadcast) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {inbox.maintenance && (
        <div style={box('#FFFBEB', '#FCD34D')}>
          <Wrench size={16} style={{ color: '#B45309', flexShrink: 0, marginTop: 1 }} />
          <div style={{ color: '#78350F' }}>
            <strong>Maintenance mode</strong>
            {inbox.maintenance.reason ? ` — ${inbox.maintenance.reason}` : ''}
            {inbox.maintenance.until && (
              <span style={{ color: '#92400E' }}> · until {fmt(inbox.maintenance.until)}</span>
            )}
          </div>
        </div>
      )}

      {showBroadcast && (
        <div style={box('#EFF6FF', '#BFDBFE')}>
          <Megaphone size={16} style={{ color: '#1D4ED8', flexShrink: 0, marginTop: 1 }} />
          <div style={{ flex: 1, color: '#1E3A8A' }}>
            <strong>{broadcast.title}</strong>
            <div style={{ color: '#1E40AF', marginTop: 2, whiteSpace: 'pre-wrap' }}>{broadcast.message}</div>
            <div style={{ color: '#60A5FA', fontSize: 11, marginTop: 4 }}>Announcement · {fmt(broadcast.sent_at)}</div>
          </div>
          <button onClick={() => dismissBroadcast(broadcast.id)} aria-label="Dismiss announcement"
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#60A5FA', padding: 2 }}>
            <X size={15} />
          </button>
        </div>
      )}

      {unread.map(m => (
        <div key={m.id} style={box('#F5F3FF', '#DDD6FE')}>
          <Mail size={16} style={{ color: '#6D28D9', flexShrink: 0, marginTop: 1 }} />
          <div style={{ flex: 1, color: '#4C1D95' }}>
            <strong>{m.subject}</strong>
            <div style={{ color: '#5B21B6', marginTop: 2, whiteSpace: 'pre-wrap' }}>{m.body}</div>
            <div style={{ color: '#A78BFA', fontSize: 11, marginTop: 4 }}>Message from Super Admin · {fmt(m.sent_at)}</div>
          </div>
          <button onClick={() => markRead(m.id)}
            style={{ background: '#fff', border: '1px solid #DDD6FE', borderRadius: 6, cursor: 'pointer', color: '#6D28D9', fontSize: 12, fontWeight: 600, padding: '4px 10px', whiteSpace: 'nowrap' }}>
            Mark read
          </button>
        </div>
      ))}
    </div>
  )
}
