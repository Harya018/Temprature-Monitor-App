/**
 * src/services/api.js — All API calls to the SentinelEdge backend.
 *
 * Uses RELATIVE URLs so this works whether the app is served
 * on port 5000, 8000, or any reverse proxy — no hardcoded host/port.
 *
 * Auth: Authorization: Bearer <token> from POST /api/auth/admin-login.
 */

function adminHeaders() {
  const token = sessionStorage.getItem('admin_token') || ''
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
  }
}

function jsonHeaders() {
  return { 'Content-Type': 'application/json' }
}

async function req(method, path, body, headers = adminHeaders()) {
  const res = await fetch(path, {          // ← relative path, no BASE_URL
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'include',
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`)
  }
  // CSV responses
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('text/csv')) return res.blob()
  return res.json()
}

// ── Auth ───────────────────────────────────────────────────────────────────────
export const adminLogin              = (username, pin)   => req('POST', '/api/admin/login',             { username, pin }, jsonHeaders())

// ── Core ──────────────────────────────────────────────────────────────────────
export const fetchHealth             = ()             => req('GET',  '/api/health',                   undefined, jsonHeaders())
export const fetchAlerts             = (limit = 50)   => req('GET',  `/api/alerts?limit=${limit}`,    undefined, jsonHeaders())
export const acknowledgeAlert        = (id, name)     => req('POST', `/api/alerts/${id}/acknowledge`, { acknowledged_by: name })
export const fetchSubscribers        = ()             => req('GET',  '/api/subscribers',              undefined, jsonHeaders())
export const addSubscriber           = (data, pwd)    => req('POST', '/api/subscribers',              data, adminHeaders(pwd))
export const deleteSubscriber        = (id, pwd)      => req('DELETE',`/api/subscribers/${id}`,      undefined, adminHeaders(pwd))
export const disableSubscriber       = (id, pwd)      => req('PATCH', `/api/subscribers/${id}/disable`, undefined, adminHeaders(pwd))
export const enableSubscriber        = (id, pwd)      => req('PATCH', `/api/subscribers/${id}/enable`,  undefined, adminHeaders(pwd))
export const setSubscriberPin        = (id, pin)      => req('POST', `/api/subscribers/${id}/set-pin`,{ subscriber_id: id, pin })
export const fetchThresholds         = ()             => req('GET',  '/api/config/thresholds',        undefined, jsonHeaders())
export const updateThresholds        = (data, pwd)    => req('POST', '/api/config/thresholds',        data, adminHeaders(pwd))
export const resetThresholds         = (pwd)          => req('POST', '/api/config/thresholds/reset',  undefined, adminHeaders(pwd))
export const simulateBreach          = ()             => req('POST', '/api/simulate/breach',          undefined)
export const fetchRecentReadings     = ()             => req('GET',  '/api/readings/recent',          undefined, jsonHeaders())
export const fetchAdminConfigChanges = ()             => req('GET',  '/api/admin/config-changes')
export const fetchDatabaseStats      = ()             => req('GET',  '/api/admin/database/stats')
export const createBackup            = ()             => req('POST', '/api/admin/backup')
export const verifyAdminPassword     = (password)     => req('POST', '/api/admin/verify-password',   { password }, jsonHeaders())

// ── History ───────────────────────────────────────────────────────────────────
export const fetchHistoryStats   = (date)             => req('GET',  `/api/history/stats?date=${date}`)
export const fetchHistoryAlerts  = (date)             => req('GET',  `/api/history/alerts?date=${date}`)
export const exportAlertsCsv     = (start, end)       => req('GET',  `/api/history/export/alerts?start=${start}&end=${end}`)
export const exportReadingsCsv   = (start, end)       => req('GET',  `/api/history/export/readings?start=${start}&end=${end}`)

// ── Reports ───────────────────────────────────────────────────────────────────
export const fetchDailyReports   = (days = 30)        => req('GET',  `/api/reports/daily?days=${days}`)

// ── Receipts ──────────────────────────────────────────────────────────────────
export const fetchReceipts       = (limit = 100, channel = 'all', status = 'all') =>
  req('GET', `/api/receipts?limit=${limit}&channel=${channel}&status=${status}`)

// ── Events ────────────────────────────────────────────────────────────────────
export const fetchEvents         = (limit = 100, type = 'all') =>
  req('GET', `/api/events?limit=${limit}&type=${type}`)

// ── Demo controls (DELETE BEFORE PRODUCTION) ──────────────────────────────────
export const demoCoolingRun      = ()                 => req('POST', '/api/demo/cooling-run', undefined)
export const demoReset           = ()                 => req('POST', '/api/demo/reset',       undefined)

// ── Admin utilities ───────────────────────────────────────────────────────────
export const importCsv            = (filename)         => req('POST', '/api/admin/import-csv',           { filename })
export const fetchAckLog          = (limit = 100)      => req('GET',  `/api/ack-log?limit=${limit}`)
export const changeAdminPassword  = (current, newPwd)  => req('POST', '/api/admin/change-password',      { current_password: current, new_password: newPwd })
export const getAdminProfile      = ()                 => req('GET',  '/api/admin/profile')
export const updateAdminProfile   = (body)             => req('PATCH', '/api/admin/profile',               body)

// ── Sub-admin management (main admin only) ────────────────────────────────────
export const fetchAdmins          = ()                 => req('GET',  '/api/admin/admins')
export const createSubAdmin       = (name, password)   => req('POST', '/api/admin/admins',               { name, password })
export const deleteSubAdmin       = (id)               => req('DELETE',`/api/admin/admins/${id}`,        undefined)
export const updateSubAdminPwd    = (id, newPwd)       => req('PUT',  `/api/admin/admins/${id}/password`,{ new_password: newPwd })

// ── Alert management ─────────────────────────────────────────────────────────
export const deleteAlerts         = (period)           => req('DELETE', `/api/alerts?period=${period}`)

// ── Subscriber Profiles ───────────────────────────────────────────────────────
export const fetchSubscriber      = (id)               => req('GET',  `/api/subscribers/${id}`,                  undefined, adminHeaders())
export const updateSubscriber     = (id, data)         => req('PUT',  `/api/subscribers/${id}`,                  data)
export const fetchSubscriberAcks  = (id)               => req('GET',  `/api/subscribers/${id}/acknowledgements`, undefined, adminHeaders())
