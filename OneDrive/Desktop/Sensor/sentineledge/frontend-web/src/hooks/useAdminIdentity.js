/**
 * src/hooks/useAdminIdentity.js
 *
 * The signed-in admin's identity from GET /api/admin/me:
 *   { id, name, role, company_id, company_name }
 * Fetched once per login token and shared by every component that asks
 * (header, dashboard, settings), so the request is not repeated per page.
 */
import { useState, useEffect } from 'react'

let cachedToken = null
let cached      = null
let inflight    = null

function load(token) {
  if (!inflight) {
    inflight = fetch('/api/admin/me', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null)
      .then(data => {
        if (data) { cached = data; cachedToken = token }
        return data
      })
      .finally(() => { inflight = null })
  }
  return inflight
}

/** Re-read /api/admin/me everywhere (e.g. after this company took over the live sensor feed). */
export function refreshAdminIdentity() {
  cached = null; cachedToken = null
  window.dispatchEvent(new Event('se:identity-refresh'))
}

export default function useAdminIdentity() {
  const token = sessionStorage.getItem('admin_token') || ''
  const [me, setMe] = useState(token && token === cachedToken ? cached : null)

  useEffect(() => {
    if (!token) { setMe(null); return }
    if (token === cachedToken && cached) { setMe(cached); return }
    let alive = true
    load(token).then(d => { if (alive && d) setMe(d) })
    return () => { alive = false }
  }, [token])

  useEffect(() => {
    const onRefresh = () => { if (token) load(token).then(d => { if (d) setMe(d) }) }
    window.addEventListener('se:identity-refresh', onRefresh)
    return () => window.removeEventListener('se:identity-refresh', onRefresh)
  }, [token])

  return me
}
