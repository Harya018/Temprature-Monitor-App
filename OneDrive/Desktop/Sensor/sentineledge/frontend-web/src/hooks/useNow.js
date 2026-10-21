/**
 * src/hooks/useNow.js — one shared 1-second ticker for every live-counting time on screen.
 * All subscribers share a single interval, so adding more counters costs nothing.
 */
import { useEffect, useMemo, useState } from 'react'

const subs = new Set()
let timer = null

function start() {
  if (!timer) timer = setInterval(() => { const t = Date.now(); subs.forEach(fn => fn(t)) }, 1000)
}
function stopIfIdle() {
  if (!subs.size && timer) { clearInterval(timer); timer = null }
}

/** Current time in ms, re-rendering the component once a second. */
export default function useNow() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    setNow(Date.now())
    subs.add(setNow); start()
    return () => { subs.delete(setNow); stopIfIdle() }
  }, [])
  return now
}

/**
 * A server-reported number of seconds (e.g. uptime) that keeps counting every second
 * between updates, instead of jumping each time the server is polled.
 */
export function useLiveSeconds(baseSeconds) {
  const now = useNow()
  const receivedAt = useMemo(() => Date.now(), [baseSeconds])   // eslint-disable-line react-hooks/exhaustive-deps
  if (baseSeconds == null) return null
  return baseSeconds + Math.max(0, Math.floor((now - receivedAt) / 1000))
}
