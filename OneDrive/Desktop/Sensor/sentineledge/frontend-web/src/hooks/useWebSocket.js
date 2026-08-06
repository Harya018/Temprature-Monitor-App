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

/** Derive the correct WebSocket URL from the current page location. */
function getWsUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host     = window.location.host   // includes port if non-standard
  return `${protocol}//${host}/ws`
}

const MAX_READINGS = 60
const MAX_BACKOFF  = 5000

export default function useWebSocket({ onBreach } = {}) {
  const [lastReading,      setLastReading]      = useState(null)
  const [readings,         setReadings]         = useState([])
  const [isConnected,      setIsConnected]      = useState(false)
  const [connectionStatus, setConnectionStatus] = useState('CONNECTING')
  const [lastEvent,        setLastEvent]        = useState(null)

  const wsRef      = useRef(null)
  const retryDelay = useRef(1000)
  const retryTimer = useRef(null)
  const mountedRef = useRef(true)
  const onBreachRef = useRef(onBreach)
  useEffect(() => { onBreachRef.current = onBreach }, [onBreach])

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    setConnectionStatus('CONNECTING')

    try {
      const ws = new WebSocket(getWsUrl())
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        setIsConnected(true)
        setConnectionStatus('LIVE')
        retryDelay.current = 1000
      }

      ws.onmessage = (e) => {
        if (!mountedRef.current) return
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'server_shutdown') return

          if (msg.type === 'parameter_added') {
            setLastEvent(msg)
            return
          }

          // Temperature readings have no type field — detect by presence of 'temperature'
          if ('temperature' in msg) {
            setLastReading(msg)
            setReadings(prev => {
              const next = [...prev, msg]
              return next.length > MAX_READINGS ? next.slice(-MAX_READINGS) : next
            })
            if (msg.breaches && msg.breaches.length > 0 && onBreachRef.current) {
              msg.breaches.forEach(b => onBreachRef.current(b))
            }
            return
          }

          // All other types (pong, config_update, alert, unacknowledged): ignored
        } catch (_) { /* ignore parse errors */ }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setIsConnected(false)
        setConnectionStatus('RECONNECTING')
        wsRef.current = null

        retryTimer.current = setTimeout(() => {
          retryDelay.current = Math.min(retryDelay.current + 1000, MAX_BACKOFF)
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
    return () => {
      mountedRef.current = false
      clearTimeout(retryTimer.current)
      if (wsRef.current) wsRef.current.close()
    }
  }, [connect])

  return { lastReading, readings, isConnected, connectionStatus, lastEvent }
}
