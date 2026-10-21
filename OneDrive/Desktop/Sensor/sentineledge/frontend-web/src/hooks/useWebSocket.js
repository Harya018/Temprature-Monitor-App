/**
 * src/hooks/useWebSocket.js
 *
 * Connects to the /ws endpoint on the CURRENT page host.
 * Uses wss: when page is https:, ws: when page is http:.
 * This means it works on any port or IP — no hardcoded localhost.
 *
 * Auto-reconnects with linear backoff (1s → 2s → 3s → max 5s).
 * Keeps last 60 readings in state.
 * Calls onBreach(breach) for each breach in an incoming message.
 */
import { useState, useEffect, useRef, useCallback } from 'react'

/** Derive the correct WebSocket URL, including the admin token if available. */
function getWsUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host     = window.location.host
  const token    = sessionStorage.getItem('admin_token') || ''
  return token ? `${protocol}//${host}/ws?token=${encodeURIComponent(token)}` : `${protocol}//${host}/ws`
}

const MAX_READINGS = 60
const MAX_BACKOFF  = 5000
// The server sends a heartbeat every 15 s. If nothing at all arrives for this
// long, the socket is dead even if the browser still reports it as open
// (common after sleep, a frozen background tab, or a Wi-Fi change).
const STALE_AFTER_MS   = 45000
const CONNECT_TIMEOUT  = 10000
const WATCHDOG_EVERY   = 10000
// A new alert blinks for this long; it stays shown (not blinking) until acknowledged
export const ALERT_BLINK_MS = 10000

/**
 * Merge a reading's breaches into the active-alert list (one entry per parameter).
 * The first breach keeps its exact time and value; later breaches on the same
 * parameter only add their alert ids and update latestValue — they do not
 * restart the blink, so a continuing breach does not flash forever.
 */
function mergeBreaches(prev, breaches, readingTs) {
  const now  = Date.now()
  const next = [...prev]
  for (const b of breaches) {
    if (!b?.parameter) continue
    const key = String(b.parameter).toLowerCase()
    const i   = next.findIndex(a => a.key === key)
    if (i >= 0) {
      const ids = b.alert_id && !next[i].alertIds.includes(b.alert_id)
        ? [...next[i].alertIds, b.alert_id] : next[i].alertIds
      next[i] = { ...next[i], alertIds: ids, latestValue: b.value }
    } else {
      next.push({
        key,
        parameter:   b.parameter,
        value:       b.value,          // exact value that triggered the alert
        latestValue: b.value,
        threshold:   b.threshold,
        direction:   b.direction,
        severity:    String(b.severity || 'WARNING').toUpperCase(),
        alertIds:    b.alert_id ? [b.alert_id] : [],
        firedAt:     readingTs || new Date().toISOString(),   // exact reading time
        blinkUntil:  now + ALERT_BLINK_MS,
      })
    }
  }
  return next
}

/** Drop acknowledged alert ids; an entry disappears once none of its ids remain. */
function removeAlertIds(prev, ids) {
  return prev.flatMap(a => {
    if (!a.alertIds.some(id => ids.includes(id))) return [a]
    const left = a.alertIds.filter(id => !ids.includes(id))
    return left.length ? [{ ...a, alertIds: left }] : []
  })
}

export default function useWebSocket({ onBreach } = {}) {
  const [lastReading,          setLastReading]          = useState(null)
  const [lastCollectorReading, setLastCollectorReading] = useState(null)
  const [readings,             setReadings]             = useState([])
  const [isConnected,          setIsConnected]          = useState(false)
  const [connectionStatus,     setConnectionStatus]     = useState('CONNECTING')
  const [lastEvent,            setLastEvent]            = useState(null)
  const [activeAlerts,         setActiveAlerts]         = useState([])

  const wsRef      = useRef(null)
  const retryDelay = useRef(1000)
  const retryTimer = useRef(null)
  const mountedRef = useRef(true)
  const lastMsgAt  = useRef(0)
  const connectTimer = useRef(null)
  const failCount    = useRef(0)      // consecutive attempts that never opened
  const expiredToken = useRef(null)   // token the server confirmed as expired
  // Alerts that fired while this page was not open (or before a refresh) are still open:
  // load them so the banner, the Acknowledge option and the red tile are there.
  const loadOpenAlerts = useCallback(async () => {
    try {
      const token = sessionStorage.getItem('admin_token') || ''
      if (!token) return
      const r = await fetch('/api/alerts?limit=100', { headers: { Authorization: `Bearer ${token}` } })
      if (!r.ok) return
      const d = await r.json()
      const list = Array.isArray(d) ? d : (d.alerts || [])
      const since = Date.now() - 24 * 3600 * 1000
      const open = list.filter(a => !a.acknowledged && new Date(a.timestamp).getTime() >= since)
      if (!open.length) return
      setActiveAlerts(prev => {
        let next = prev
        for (const a of [...open].reverse()) {
          next = mergeBreaches(next, [{ parameter: a.parameter, value: a.value, threshold: a.threshold,
                                        direction: a.direction, severity: a.severity, alert_id: a.id }], a.timestamp)
        }
        // an alert loaded from the server is not new: do not blink it
        return next.map(x => (prev.some(p => p.key === x.key) ? x : { ...x, blinkUntil: 0 }))
      })
    } catch { /* silent */ }
  }, [])

  const onBreachRef = useRef(onBreach)
  useEffect(() => { onBreachRef.current = onBreach }, [onBreach])

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    clearTimeout(retryTimer.current)
    retryTimer.current = null

    // Never open a second socket while one is open or still connecting.
    const cur = wsRef.current
    if (cur && (cur.readyState === WebSocket.OPEN || cur.readyState === WebSocket.CONNECTING)) return

    // Don't attempt connection until we have an auth token.
    // Silently poll every 500 ms so the header never shows RECONNECTING
    // just because the user hasn't logged in yet.
    const token = sessionStorage.getItem('admin_token') || ''
    if (!token) {
      retryTimer.current = setTimeout(connect, 500)
      return
    }
    // Session expired: wait quietly until the user logs in again (new token).
    if (token === expiredToken.current) {
      retryTimer.current = setTimeout(connect, 2000)
      return
    }
    expiredToken.current = null

    setConnectionStatus('CONNECTING')

    try {
      const ws = new WebSocket(getWsUrl())
      wsRef.current = ws
      let opened = false

      // A connect attempt can hang (e.g. right after waking from sleep) —
      // give up after CONNECT_TIMEOUT so onclose schedules a fresh attempt.
      clearTimeout(connectTimer.current)
      connectTimer.current = setTimeout(() => {
        if (ws.readyState === WebSocket.CONNECTING) ws.close()
      }, CONNECT_TIMEOUT)

      ws.onopen = () => {
        clearTimeout(connectTimer.current)
        opened = true
        failCount.current = 0
        if (!mountedRef.current) return
        lastMsgAt.current = Date.now()
        setIsConnected(true)
        setConnectionStatus('LIVE')
        retryDelay.current = 1000
        loadOpenAlerts()          // alerts that fired while this page was closed / before the login
      }

      ws.onmessage = (e) => {
        if (!mountedRef.current) return
        lastMsgAt.current = Date.now()
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'server_shutdown' || msg.type === 'heartbeat') return

          // Live switched on/off in Settings: forget the other source's last
          // values so the dashboard shows only the newly selected source.
          if (msg.type === 'data_source_changed') {
            setLastCollectorReading(null)
            setLastReading(null)
            setReadings([])
            setLastEvent(msg)
            return
          }

          if (msg.type === 'test_alert') {
            // a manual test alert: show the alert banner only — no reading, no chart point
            if (msg.breaches && msg.breaches.length > 0) {
              setActiveAlerts(prev => mergeBreaches(prev, msg.breaches, msg.timestamp))
              if (onBreachRef.current) msg.breaches.forEach(b => onBreachRef.current(b))
            }
            return
          }

          if (msg.type === 'parameter_added' || msg.type === 'parameter_deleted') {
            setLastEvent(msg)
            // Every page using useCompanyParameters re-reads the list
            window.dispatchEvent(new CustomEvent('se:parameters-changed', { detail: msg }))
            return
          }

          // Acknowledged anywhere (dashboard, mobile app, SMS reply, Super Admin):
          // drop that alert id; a parameter's entry clears once all its ids are acked.
          if (msg.type === 'acknowledgement' && msg.alert_id != null) {
            setActiveAlerts(prev => removeAlertIds(prev, [msg.alert_id]))
            return
          }

          // Temperature readings — detect by presence of 'temperature'.
          // live_collector_reading is the authoritative live source; store it
          // separately so it is never overwritten by other temperature messages.
          if ('temperature' in msg) {
            setLastReading(msg)
            if (msg.type === 'live_collector_reading') {
              setLastCollectorReading(msg)
            }
            setReadings(prev => {
              const next = [...prev, msg]
              return next.length > MAX_READINGS ? next.slice(-MAX_READINGS) : next
            })
            if (msg.breaches && msg.breaches.length > 0) {
              setActiveAlerts(prev => mergeBreaches(prev, msg.breaches, msg.timestamp))
              if (onBreachRef.current) msg.breaches.forEach(b => onBreachRef.current(b))
            }
            return
          }

          // All other types (pong, config_update, alert, unacknowledged): ignored
        } catch (_) { /* ignore parse errors */ }
      }

      ws.onclose = () => {
        clearTimeout(connectTimer.current)
        if (!mountedRef.current) return
        // A newer socket may already have replaced this one — leave it alone.
        if (wsRef.current !== ws) return
        setIsConnected(false)
        setConnectionStatus('RECONNECTING')
        wsRef.current = null

        // Refused repeatedly before opening: ask the API whether the login
        // session is still valid. 401 → expired; stop retrying until re-login.
        // (A network error means the server is down — keep retrying.)
        if (!opened && ++failCount.current >= 2) {
          const tok = sessionStorage.getItem('admin_token') || ''
          fetch('/api/admin/me', { headers: { Authorization: `Bearer ${tok}` } })
            .then(r => {
              if (r.status === 401 && mountedRef.current && !wsRef.current) {
                expiredToken.current = tok
                setConnectionStatus('SESSION EXPIRED')
              }
            })
            .catch(() => {})
        }

        clearTimeout(retryTimer.current)
        retryTimer.current = setTimeout(() => {
          // Only back off if we have a token but the server keeps rejecting us.
          // If there's no token, connect() will poll silently and reset delay itself.
          const hasToken = !!(sessionStorage.getItem('admin_token') || '')
          if (hasToken) retryDelay.current = Math.min(retryDelay.current + 1000, MAX_BACKOFF)
          connect()
        }, retryDelay.current)
      }

      ws.onerror = () => { ws.close() }

    } catch (_) {
      setConnectionStatus('RECONNECTING')
      retryTimer.current = setTimeout(connect, retryDelay.current)
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    connect()

    // Drop a socket that is open but silent, or reconnect if none is pending.
    // A dead socket can take a long time to finish closing, so detach it and
    // open a fresh one straight away (its late onclose is ignored).
    const checkHealth = () => {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        if (Date.now() - lastMsgAt.current > STALE_AFTER_MS) {
          wsRef.current = null
          try { ws.close() } catch (_) { /* already closing */ }
          setIsConnected(false)
          setConnectionStatus('RECONNECTING')
          retryDelay.current = 1000
          connect()
        }
        return
      }
      if (!ws && !retryTimer.current) connect()
    }

    // Coming back to the tab / window, waking up, or the network returning:
    // check immediately instead of waiting for a throttled background timer.
    const resume = () => {
      if (document.visibilityState === 'hidden') return
      const ws = wsRef.current
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        retryDelay.current = 1000
        if (ws) wsRef.current = null
        connect()
      } else {
        checkHealth()
      }
    }

    const watchdog = setInterval(checkHealth, WATCHDOG_EVERY)
    document.addEventListener('visibilitychange', resume)
    window.addEventListener('focus', resume)
    window.addEventListener('online', resume)
    window.addEventListener('pageshow', resume)

    return () => {
      mountedRef.current = false
      clearInterval(watchdog)
      document.removeEventListener('visibilitychange', resume)
      window.removeEventListener('focus', resume)
      window.removeEventListener('online', resume)
      window.removeEventListener('pageshow', resume)
      clearTimeout(retryTimer.current)
      clearTimeout(connectTimer.current)
      if (wsRef.current) wsRef.current.close()
    }
  }, [connect])

  // Alerts without an alert id cannot be acknowledged — let them lapse after the blink.
  useEffect(() => {
    const pending = activeAlerts.filter(a => a.alertIds.length === 0)
    if (!pending.length) return
    const wait = Math.max(0, Math.min(...pending.map(a => a.blinkUntil)) - Date.now())
    const t = setTimeout(() => setActiveAlerts(prev =>
      prev.filter(a => a.alertIds.length > 0 || a.blinkUntil > Date.now())), wait + 50)
    return () => clearTimeout(t)
  }, [activeAlerts])

  // Remove alerts locally after a successful acknowledge from this dashboard
  // (the server's acknowledgement broadcast does the same for everyone else).
  const clearAlerts = useCallback((ids) => {
    setActiveAlerts(prev => removeAlertIds(prev, ids))
  }, [])

  return { lastReading, lastCollectorReading, readings, isConnected, connectionStatus, lastEvent, activeAlerts, clearAlerts }
}
