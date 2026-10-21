/**
 * src/pages/MonitorPage.jsx
 * Full-screen wall display. No sidebar/header. Press Escape to exit.
 */
import useCompanyParameters from '../hooks/useCompanyParameters.js'
import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { X } from 'lucide-react'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale,
  PointElement, LineElement, Filler, Tooltip,
} from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip)

function getSeverity(temp, thresholds) {
  if (!temp || !thresholds) return 'NORMAL'
  const { high, low } = thresholds.temperature || {}
  if (!high || !low) return 'NORMAL'
  const over  = temp - high
  const under  = low - temp
  const breach = Math.max(over, under)
  if (breach <= 0)                    return 'NORMAL'
  if (breach < (high - low) * 0.05)  return 'WARNING'
  if (breach < (high - low) * 0.10)  return 'CRITICAL'
  return 'EMERGENCY'
}

const SEV_CONFIG = {
  NORMAL:    { color: '#10B981', label: 'NORMAL',    bg: '#ECFDF5' },
  WARNING:   { color: '#F59E0B', label: 'WARNING',   bg: '#FFFBEB' },
  CRITICAL:  { color: '#F97316', label: 'CRITICAL',  bg: '#FFF7ED' },
  EMERGENCY: { color: '#EF4444', label: 'EMERGENCY', bg: '#FEF2F2' },
}

function nowIST() {
  return new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })
}

/* Monitor mode is the full-screen temperature display — shown only to
   companies that have a temperature parameter. */
export default function MonitorPage(props) {
  const { has, loading } = useCompanyParameters()
  if (!loading && !has('temperature')) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: '#111827', color: '#9CA3AF', textAlign: 'center', padding: 24 }}>
        <div>
          <p style={{ fontSize: 18, fontWeight: 700, color: '#F9FAFB' }}>Monitor mode shows temperature</p>
          <p style={{ fontSize: 13, marginTop: 6 }}>Your company has no temperature parameter. Use the Dashboard for your parameters.</p>
        </div>
      </div>
    )
  }
  return <MonitorScreen {...props} />
}

function MonitorScreen({ wsData, thresholds }) {
  const { lastReading, lastCollectorReading, readings, isConnected } = wsData || {}
  const navigate = useNavigate()
  const [time,   setTime]   = useState(nowIST())
  const [breach, setBreach] = useState(false)
  const prevTemp = useRef(null)

  useEffect(() => {
    const t = setInterval(() => setTime(nowIST()), 1000)
    return () => clearInterval(t)
  }, [])

  // Collector reading is authoritative while the collector is active, so the
  // display holds its value between the collector's ~4 s samples.
  const displayReading = lastCollectorReading ?? lastReading
  const temp     = displayReading?.temperature
  const severity = getSeverity(temp, thresholds)
  const cfg      = SEV_CONFIG[severity]

  // Flash on breach
  useEffect(() => {
    if (severity !== 'NORMAL' && temp !== prevTemp.current) {
      setBreach(true)
      setTimeout(() => setBreach(false), 1000)
    }
    prevTemp.current = temp
  }, [temp, severity])

  // Keyboard exit
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') navigate('/dashboard') }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigate])

  const tHigh = thresholds?.temperature?.high ?? 90
  const tLow  = thresholds?.temperature?.low  ?? 38
  const recent = (readings || []).slice(-20)

  const chartData = {
    labels: recent.map(() => ''),
    datasets: [{
      data: recent.map(r => r.temperature),
      borderColor: cfg.color,
      backgroundColor: cfg.color + '22',
      borderWidth: 2,
      pointRadius: 0,
      fill: true,
      tension: 0.4,
    }],
  }

  const chartOpts = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 200 },
    plugins: { legend: { display: false }, tooltip: { enabled: false } },
    scales: {
      x: { display: false },
      y: {
        display: false,
        min: Math.min(tLow - 5, ...(recent.map(r => r.temperature))),
        max: Math.max(tHigh + 5, ...(recent.map(r => r.temperature))),
      },
    },
  }

  // Threshold bar
  const range = tHigh - tLow
  const pct   = temp != null ? Math.max(0, Math.min(100, ((temp - tLow) / range) * 100)) : 50

  return (
    <div
      className="fixed inset-0 flex flex-col items-center justify-center transition-colors duration-500"
      style={{ background: breach ? '#7F1D1D' : '#0F1117', overflow: 'hidden' }}
    >
      {/* Exit button */}
      <button
        onClick={() => navigate('/dashboard')}
        className="absolute top-6 right-6 p-2 rounded-lg hover:bg-white/10 transition-colors text-white/50 hover:text-white"
        title="Exit (Esc)"
      >
        <X size={20} />
      </button>

      {/* Top brand */}
      <div className="absolute top-6 left-6 flex items-center gap-2">
        <span className="text-white/50 text-sm font-semibold tracking-wider uppercase">SentinelEdge</span>
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${isConnected ? 'bg-emerald-500 text-white' : 'bg-gray-600 text-gray-300'}`}>
          {isConnected ? '● LIVE' : '○ OFFLINE'}
        </span>
      </div>

      {/* BREACH overlay */}
      {breach && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
          <span className="text-white/30 font-black" style={{ fontSize: '20vw' }}>BREACH</span>
        </div>
      )}

      {/* Center — Temperature */}
      <div className="flex flex-col items-center gap-4 z-20">
        <div className="flex items-end gap-3" style={{ transition: 'color 0.5s' }}>
          <span
            className="font-black tabular-nums leading-none"
            style={{ fontSize: '18vw', color: cfg.color, transition: 'color 0.5s' }}
          >
            {temp != null ? temp.toFixed(1) : '--.-'}
          </span>
          <span className="font-bold text-white/50 pb-4" style={{ fontSize: '5vw' }}>°C</span>
        </div>

        {/* Severity badge */}
        <div
          className={`px-8 py-2 rounded-2xl font-black tracking-widest ${severity === 'EMERGENCY' ? 'animate-pulse' : ''}`}
          style={{ background: cfg.color + '25', color: cfg.color, fontSize: '2vw' }}
        >
          {cfg.label}
        </div>

        {/* Threshold bar */}
        <div className="w-64 mt-4">
          <div className="flex justify-between text-xs text-white/40 mb-1">
            <span>{tLow}°C</span>
            <span>Normal Range</span>
            <span>{tHigh}°C</span>
          </div>
          <div className="relative h-3 rounded-full bg-white/10">
            <div
              className="absolute left-0 h-full rounded-full transition-all duration-700"
              style={{ width: `${pct}%`, background: cfg.color }}
            />
          </div>
        </div>
      </div>

      {/* Mini chart */}
      {recent.length > 2 && (
        <div className="absolute bottom-16 left-6 right-6 h-24 opacity-40">
          <Line data={chartData} options={chartOpts} />
        </div>
      )}

      {/* IST clock */}
      <div className="absolute bottom-6 right-6 text-white/40 font-mono text-sm">
        IST {time}
      </div>
    </div>
  )
}
