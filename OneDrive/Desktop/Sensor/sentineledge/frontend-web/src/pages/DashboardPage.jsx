/**
 * src/pages/DashboardPage.jsx
 * Home overview — stat cards, live chart, mini alert preview.
 * Wrapped in an ErrorBoundary to surface crashes instead of blank screen.
 */
import { Component, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Gauge, Droplets, Activity, Cpu } from 'lucide-react'
import TemperatureCard  from '../components/dashboard/TemperatureCard.jsx'
import StatusCard       from '../components/dashboard/StatusCard.jsx'
import AlertsTodayCard  from '../components/dashboard/AlertsTodayCard.jsx'
import UptimeCard       from '../components/dashboard/UptimeCard.jsx'
import LiveChart        from '../components/dashboard/LiveChart.jsx'
import MiniAlertLog     from '../components/dashboard/MiniAlertLog.jsx'
import SensorCard       from '../components/dashboard/SensorCard.jsx'

/* ── Random helpers ─────────────────────────────────────────────────────────── */
const randomInRange = (min, max) =>
  (Math.random() * (max - min) + min).toFixed(2)

/* ── Error boundary ── catches any render crash and shows a readable message ── */
class ErrorBoundary extends Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          padding: 24, color: '#991B1B', background: '#FEF2F2',
          borderRadius: 12, margin: 24, fontFamily: 'monospace', fontSize: 13,
        }}>
          <strong>Dashboard render error:</strong>
          <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {this.state.error.message}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            style={{ marginTop: 12, padding: '6px 16px', background: '#7C3AED', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}
          >
            Retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

/* ── Dashboard page ─────────────────────────────────────────────────────────── */
export default function DashboardPage({ wsData, health, thresholds, onAlertCount }) {
  // Defensive destructure — all values have safe defaults
  const lastReading      = wsData?.lastReading      ?? null
  const readings         = wsData?.readings         ?? []
  const isConnected      = wsData?.isConnected      ?? false
  const connectionStatus = wsData?.connectionStatus ?? 'CONNECTING'
  const lastEvent        = wsData?.lastEvent        ?? null

  const navigate = useNavigate()

  // ── Simulated sensor state ───────────────────────────────────────────────────
  const [pressure,  setPressure]  = useState(() => randomInRange(1.98, 2.50))
  const [humidity,  setHumidity]  = useState(() => randomInRange(54.0, 62.0))
  const [vibration, setVibration] = useState(() => randomInRange(2.2,  2.5))

  useEffect(() => {
    const id = setInterval(() => {
      setPressure(randomInRange(1.98, 2.50))
      setHumidity(randomInRange(54.0, 62.0))
      setVibration(randomInRange(2.2, 2.5))
    }, 3000)
    return () => clearInterval(id)
  }, [])

  // ── Dynamic parameters from DB ───────────────────────────────────────────────
  const [companyId,   setCompanyId]   = useState(null)
  const [extraParams, setExtraParams] = useState([])
  const [paramToast,  setParamToast]  = useState('')

  useEffect(() => {
    const token = sessionStorage.getItem('admin_token')
    if (!token) return
    const headers = { Authorization: `Bearer ${token}` }
    fetch('/api/admin/me', { headers })
      .then(r => r.ok ? r.json() : null)
      .then(me => {
        if (me?.company_id) setCompanyId(me.company_id)
        return fetch('/api/admin/parameters', { headers })
          .then(r => r.ok ? r.json() : [])
          .then(params => setExtraParams(Array.isArray(params) ? params : []))
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!lastEvent || lastEvent.type !== 'parameter_added') return
    if (companyId && lastEvent.company_id !== companyId) return
    const p = lastEvent.parameter
    if (!p?.name) return
    setExtraParams(prev => {
      if (prev.some(ep => ep.name === p.name)) return prev
      return [...prev, { name: p.name, unit: p.unit, min_value: p.min_value, max_value: p.max_value }]
    })
    setParamToast(`New parameter added: ${p.name}`)
    setTimeout(() => setParamToast(''), 4000)
  }, [lastEvent, companyId])

  useEffect(() => {
    if (!lastEvent || lastEvent.type !== 'parameter_deleted') return
    if (companyId && lastEvent.company_id !== companyId) return
    const deletedId   = lastEvent.parameter_id
    const deletedName = lastEvent.name
    setExtraParams(prev =>
      prev.filter(ep => ep.id !== deletedId && ep.name !== deletedName)
    )
    setParamToast(`Parameter removed: ${deletedName}`)
    setTimeout(() => setParamToast(''), 4000)
  }, [lastEvent, companyId])

  return (
    <ErrorBoundary>
      {paramToast && (
        <div style={{
          position: 'fixed', top: 20, right: 20, zIndex: 2000,
          background: '#D1FAE5', color: '#065F46',
          padding: '10px 18px', borderRadius: 8, fontWeight: 600, fontSize: 13,
        }}>
          {paramToast}
        </div>
      )}
      <div className="space-y-5">

        {/* Row 1 — Stat cards (4 columns) */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <TemperatureCard reading={lastReading} thresholds={thresholds} />
          <StatusCard isConnected={isConnected} connectionStatus={connectionStatus} />
          <AlertsTodayCard count={health?.alerts_today ?? 0} />
          <UptimeCard uptimeSeconds={health?.uptime_seconds ?? null} />
        </div>

        {/* Row 2 — Sensor parameter cards (show simulated unless real sensor data exists for that name) */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {(() => {
            const liveP = lastReading?.extra_params?.['Pressure'] ?? lastReading?.extra_params?.['pressure'] ?? null
            const liveH = lastReading?.extra_params?.['Humidity'] ?? lastReading?.extra_params?.['humidity'] ?? null
            const liveV = lastReading?.extra_params?.['Vibration'] ?? lastReading?.extra_params?.['vibration'] ?? null
            const hasP  = extraParams.some(p => p.name.toLowerCase() === 'pressure')
            const hasH  = extraParams.some(p => p.name.toLowerCase() === 'humidity')
            const hasV  = extraParams.some(p => p.name.toLowerCase() === 'vibration')
            return (
              <>
                {!hasP && (
                  <SensorCard icon={Gauge} iconColor="#0EA5E9" label="Pressure"
                    value={pressure} unit="bar" subtitle="Δ −0.2 predicted"
                    footer="Operating range 1.5 – 3.0 bar" />
                )}
                {!hasH && (
                  <SensorCard icon={Droplets} iconColor="#10B981" label="Humidity"
                    value={humidity} unit="%" subtitle="Trending upward"
                    footer="Acceptable 40 – 70 %" />
                )}
                {!hasV && (
                  <SensorCard icon={Activity} iconColor="#F59E0B" label="Vibration"
                    value={vibration} unit="mm/s" subtitle="RMS velocity"
                    footer="Limit < 4.5 mm/s" />
                )}
              </>
            )
          })()}
        </div>

        {/* Row 3 — Dynamic parameter cards (from approved company_parameters) */}
        {extraParams.length > 0 && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {extraParams.map(p => {
              // Case-insensitive match — Pro-Server EX column names may differ in case
              const ep = lastReading?.extra_params
              const liveValue = ep
                ? (ep[p.name] ?? Object.entries(ep).find(([k]) => k.toLowerCase() === p.name.toLowerCase())?.[1] ?? null)
                : null
              const mn = p.min_value != null ? Number(p.min_value) : null
              const mx = p.max_value != null ? Number(p.max_value) : null
              const inRange = liveValue != null && mn != null && mx != null
                ? liveValue >= mn && liveValue <= mx
                : null
              const subtitle = liveValue != null && inRange != null
                ? inRange ? 'Within normal range' : 'Out of range!'
                : (mn != null && mx != null ? `Range: ${mn} – ${mx}` : undefined)
              return (
                <SensorCard
                  key={p.name}
                  icon={Cpu}
                  iconColor={
                    liveValue != null && inRange === false ? '#EF4444' : '#7C3AED'
                  }
                  label={p.name}
                  value={liveValue != null ? Number(liveValue).toFixed(2) : null}
                  unit={p.unit || ''}
                  subtitle={subtitle}
                  footer={p.unit ? `Live ${p.name} reading (${p.unit})` : `Live ${p.name} reading`}
                />
              )
            })}
          </div>
        )}

        {/* Row 4 — Live chart */}
        <LiveChart readings={readings} thresholds={thresholds} />

        {/* Row 5 — Mini alert preview */}
        <div className="card">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <div>
              <h3 className="text-sm font-semibold text-gray-800">Recent Alerts</h3>
              <p className="text-xs text-gray-500 mt-0.5">Last 5 breach events</p>
            </div>
            <button
              onClick={() => navigate('/alerts')}
              className="flex items-center gap-1.5 text-xs font-semibold text-purple-600 hover:text-purple-700"
            >
              View all alerts <ArrowRight size={13} />
            </button>
          </div>
          <div className="p-5">
            <MiniAlertLog limit={5} onCountChange={onAlertCount} />
          </div>
        </div>

      </div>
    </ErrorBoundary>
  )
}
