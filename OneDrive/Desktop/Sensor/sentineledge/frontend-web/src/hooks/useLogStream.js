/**
 * src/hooks/useLogStream.js
 *
 * Connects to the /ws/logs endpoint on the CURRENT page host.
 * Uses wss: when page is https:, ws: when page is http:.
 * Works on any port or IP — no hardcoded localhost.
 *
 * Streams live backend log lines to the admin dashboard.
 * Supports pause/resume and keyword + level filtering.
 */
import { useState, useEffect, useRef, useCallback } from 'react'

const MAX_LINES = 1000

/** Derive the correct WebSocket URL from the current page location. */
function getLogWsUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host     = window.location.host   // includes port if non-standard
  const token    = sessionStorage.getItem('admin_token') || ''
  return `${protocol}//${host}/ws/logs?token=${encodeURIComponent(token)}`
}

export default function useLogStream() {
  const [lines,       setLines]       = useState([])
  const [isConnected, setIsConnected] = useState(false)
  const [isPaused,    setIsPaused]    = useState(false)
  const [filter,      setFilter]      = useState('')
  const [levelFilter, setLevelFilter] = useState('all')

  const wsRef      = useRef(null)
  const mountedRef = useRef(true)
  const pausedRef  = useRef(false)
  const retryTimer = useRef(null)

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    try {
      const ws = new WebSocket(getLogWsUrl())
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        setIsConnected(true)
      }

      ws.onmessage = (e) => {
        if (!mountedRef.current || pausedRef.current) return
        const line = e.data
        if (!line?.trim()) return
        setLines(prev => {
          const next = [...prev, line]
          return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next
        })
      }

      ws.onclose = () => {
        if (!mountedRef.current || wsRef.current !== ws) return
        setIsConnected(false)
        clearTimeout(retryTimer.current)
        retryTimer.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()
    } catch { /* silent */ }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    connect()

    // Back on the tab / network returned: reconnect now rather than waiting
    // for the (throttled) background retry timer.
    const resume = () => {
      if (document.visibilityState === 'hidden') return
      const ws = wsRef.current
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
      clearTimeout(retryTimer.current)
      connect()
    }
    document.addEventListener('visibilitychange', resume)
    window.addEventListener('focus', resume)
    window.addEventListener('online', resume)

    return () => {
      mountedRef.current = false
      document.removeEventListener('visibilitychange', resume)
      window.removeEventListener('focus', resume)
      window.removeEventListener('online', resume)
      clearTimeout(retryTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const togglePause = useCallback(() => {
    setIsPaused(prev => {
      pausedRef.current = !prev
      return !prev
    })
  }, [])

  const clearLines = useCallback(() => setLines([]), [])

  // Apply filters for display
  const filteredLines = lines.filter(line => {
    if (filter && !line.toLowerCase().includes(filter.toLowerCase())) return false
    if (levelFilter !== 'all') {
      const up = levelFilter.toUpperCase()
      if (!line.includes(`[${up}]`) && !line.includes(up)) return false
    }
    return true
  })

  return {
    lines: filteredLines,
    rawLines: lines,
    isConnected,
    isPaused,
    filter,
    levelFilter,
    setFilter,
    setLevelFilter,
    togglePause,
    clearLines,
  }
}
