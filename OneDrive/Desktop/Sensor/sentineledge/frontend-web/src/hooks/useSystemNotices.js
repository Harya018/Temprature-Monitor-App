/**
 * src/hooks/useSystemNotices.js
 *
 * Notices for the notification bell that are not alerts. Today: "turn on Tailscale / connect to the main
 * server" (GET /api/admin/tailscale decides). Re-checked every minute; a notice the admin chose to
 * "remind me later" stays hidden for 12 hours, then comes back if the problem is still there.
 */
import { useState, useEffect, useCallback } from 'react'

const HIDE_MS = 12 * 3600 * 1000
const keyFor = (n) => `se_notice_hidden_${n.title}`

function hiddenNow(n) {
  try {
    const t = Number(localStorage.getItem(keyFor(n)) || 0)
    return t && Date.now() - t < HIDE_MS
  } catch { return false }
}

export default function useSystemNotices() {
  const [notices, setNotices] = useState([])

  const load = useCallback(async () => {
    const token = sessionStorage.getItem('admin_token') || ''
    if (!token) { setNotices([]); return }
    try {
      const r = await fetch('/api/admin/tailscale', { headers: { Authorization: `Bearer ${token}` } })
      if (!r.ok) return
      const d = await r.json()
      const list = d.notice ? [{ ...d.notice, id: 'tailscale', link: '/settings#tailscale' }] : []
      setNotices(list.filter(n => !hiddenNow(n)))
    } catch { /* silent: no network, no notice */ }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [load])

  const hide = useCallback((n) => {
    try { localStorage.setItem(keyFor(n), String(Date.now())) } catch { /* ignore */ }
    setNotices(list => list.filter(x => x.id !== n.id))
  }, [])

  return { notices, hide, reload: load }
}
