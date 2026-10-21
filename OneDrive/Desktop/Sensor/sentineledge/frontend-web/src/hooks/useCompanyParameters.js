/**
 * src/hooks/useCompanyParameters.js
 *
 * The signed-in company's approved parameters (GET /api/admin/parameters).
 * Everything parameter-specific in the admin dashboard — tiles, charts,
 * analytics options, settings sections — is driven by this list, so a company
 * that only has pH sees only pH, and a new company with none sees none.
 *
 * Refreshes live: useWebSocket dispatches 'se:parameters-changed' when a
 * parameter is approved, added, edited or removed, and every page using this
 * hook re-reads the list without a reload.
 *
 *   const { params, loading, has, get } = useCompanyParameters()
 *   has('temperature') → boolean       get('ph') → parameter row or undefined
 */
import { useState, useEffect, useCallback } from 'react'

export const PARAMETERS_CHANGED = 'se:parameters-changed'

let cache = null          // { token, rows }
let inflight = null

function fetchParams(token) {
  if (!inflight) {
    inflight = fetch('/api/admin/parameters', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => (r.ok ? r.json() : []))
      .then(rows => (Array.isArray(rows) ? rows : []))
      .catch(() => null)
      .finally(() => { inflight = null })
  }
  return inflight
}

export default function useCompanyParameters() {
  const token = sessionStorage.getItem('admin_token') || ''
  const fresh = cache && cache.token === token
  const [params,  setParams]  = useState(fresh ? cache.rows : [])
  const [loading, setLoading] = useState(!fresh)

  const load = useCallback(async () => {
    if (!token) { setParams([]); setLoading(false); return }
    const rows = await fetchParams(token)
    if (rows) { cache = { token, rows }; setParams(rows) }
    setLoading(false)
  }, [token])

  useEffect(() => {
    load()
    const onChange = () => { cache = null; load() }
    window.addEventListener(PARAMETERS_CHANGED, onChange)
    return () => window.removeEventListener(PARAMETERS_CHANGED, onChange)
  }, [load])

  const key = n => String(n ?? '').toLowerCase()
  const get = useCallback(name => params.find(p => key(p.name) === key(name)), [params])
  const has = useCallback(name => !!get(name), [get])

  return { params, loading, has, get }
}
