/**
 * src/hooks/useAudioAlarm.js
 *
 * Web Audio API alarm system — no external files.
 * WARNING   → single beep 440 Hz, 0.4s
 * CRITICAL  → double beep 440 → 880 Hz, 0.3s each
 * EMERGENCY → repeating 880 Hz beep until stopped
 *
 * Browser autoplay policy: audio only starts after first
 * user interaction. AudioContext is created lazily.
 */
import { useState, useRef, useCallback } from 'react'

export default function useAudioAlarm() {
  const [isPlaying,       setIsPlaying]       = useState(false)
  const [currentSeverity, setCurrentSeverity] = useState(null)

  const ctxRef      = useRef(null)
  const intervalRef = useRef(null)
  const gainRef     = useRef(null)

  function getCtx() {
    if (!ctxRef.current) {
      ctxRef.current = new (window.AudioContext || window.webkitAudioContext)()
    }
    return ctxRef.current
  }

  function beep(freq, duration, startAt, ctx) {
    const osc  = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.value = freq
    osc.type = 'sine'
    gain.gain.setValueAtTime(0.3, startAt)
    gain.gain.exponentialRampToValueAtTime(0.001, startAt + duration)
    osc.start(startAt)
    osc.stop(startAt + duration)
  }

  /** Call from a click / key press so the browser allows sound later. */
  const unlock = useCallback(() => {
    const ctx = getCtx()
    if (ctx.state === 'suspended') ctx.resume()
  }, [])

  const stopAlarm = useCallback(() => {
    clearInterval(intervalRef.current)
    intervalRef.current = null
    setIsPlaying(false)
    setCurrentSeverity(null)
  }, [])

  const playAlarm = useCallback((severity) => {
    try {
      const ctx = getCtx()
      if (ctx.state === 'suspended') ctx.resume()

      stopAlarm()
      setIsPlaying(true)
      setCurrentSeverity(severity)

      const s = severity?.toUpperCase()

      if (s === 'WARNING') {
        // three short beeps: a single one is easy to miss
        beep(440, 0.25, ctx.currentTime,       ctx)
        beep(440, 0.25, ctx.currentTime + 0.4, ctx)
        beep(440, 0.25, ctx.currentTime + 0.8, ctx)
      } else if (s === 'CRITICAL') {
        beep(440, 0.3, ctx.currentTime,       ctx)
        beep(880, 0.3, ctx.currentTime + 0.4, ctx)
      } else if (s === 'EMERGENCY') {
        const doBeep = () => {
          const c = getCtx()
          beep(880, 0.25, c.currentTime, c)
        }
        doBeep()
        intervalRef.current = setInterval(doBeep, 600)
      }
    } catch (_) {
      // AudioContext blocked by browser — silent fail
    }
  }, [stopAlarm])

  return { playAlarm, stopAlarm, unlock, isPlaying, currentSeverity }
}
