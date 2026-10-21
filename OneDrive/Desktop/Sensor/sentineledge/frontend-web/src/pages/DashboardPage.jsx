/**
 * src/pages/DashboardPage.jsx
 * Home overview — stat cards, live chart, mini alert preview.
 * Wrapped in an ErrorBoundary to surface crashes instead of blank screen.
 */
import { Component, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Cpu, FlaskConical, AlertTriangle, SlidersHorizontal } from 'lucide-react'
import { formatTime, formatDate } from '../utils/time.js'
import TemperatureCard  from '../components/dashboard/TemperatureCard.jsx'
import StatusCard       from '../components/dashboard/StatusCard.jsx'
import AlertsTodayCard  from '../components/dashboard/AlertsTodayCard.jsx'
import UptimeCard       from '../components/dashboard/UptimeCard.jsx'
import LiveChart        from '../components/dashboard/LiveChart.jsx'
import PhLiveChart      from '../components/dashboard/PhLiveChart.jsx'
import ParamLiveChart   from '../components/dashboard/ParamLiveChart.jsx'
import MiniAlertLog     from '../components/dashboard/MiniAlertLog.jsx'
import SensorCard, { displayParamName } from '../components/dashboard/SensorCard.jsx'
import SuperAdminNotices from '../components/dashboard/SuperAdminNotices.jsx'
import useCompanyParameters from '../hooks/useCompanyParameters.js'

/* ── Truncate to 3 decimal places without rounding ──────────────────────────── */
const trunc3 = v => { const n = Number(v); return isNaN(n) ? '—' : (Math.trunc(n * 1000) / 1000).toFixed(3) }

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

/* Red outline around a tile while its alert is open; pulses only while blinking. */
function AlertFrame({ alert, blinking, children }) {
  return (
    <div className="h-full" data-alert-frame={alert ? alert.key : undefined} data-blinking={alert ? blinking : undefined} style={alert ? {
      borderRadius: 12,
      outline: '2px solid #DC2626',
      animation: blinking ? 'phPulse 1s ease-in-out infinite' : 'none',
    } : undefined}>
      {children}
    </div>
  )
}

/* "Alert at 11:27:49 PM — 9.20 ≥ 8.00" — exact time and value the alert fired with */
const alertLine = a =>
  `Alert at ${formatTime(a.firedAt)} — ${fmtNum(a.value)} ${a.direction === 'low' ? '≤' : '≥'} ${fmtNum(a.threshold)}`

/* ── Active alert banner ─────────────────────────────────────────────────────────
   One line per unacknowledged alert with the exact value, threshold and time it
   fired. Blinks for the first 10 s only; stays red until acknowledged. */
const fmtNum = v => (v == null || isNaN(Number(v)) ? '—' : Number(v).toFixed(2))
const alertTime = ts => (ts ? `${formatTime(ts)}, ${formatDate(ts)}` : '—')

function AlertBanner({ alerts, now, unitOf, onAck, acking }) {
  if (!alerts.length) return null
  const anyBlinking = alerts.some(a => a.blinkUntil > now)
  return (
    <div data-alert-banner data-blinking={anyBlinking} style={{
      background: '#DC2626', color: '#fff', borderRadius: 10, padding: '10px 16px',
      display: 'flex', flexDirection: 'column', gap: 6,
      animation: anyBlinking ? 'phPulse 1s ease-in-out infinite' : 'none',
    }}>
      {alerts.map(a => {
        const unit = unitOf(a.key)
        const sign = a.direction === 'low' ? '≤' : '≥'
        return (
          <div key={a.key} style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: 14 }}>
            <AlertTriangle size={18} style={{ flexShrink: 0 }} />
            <span style={{ fontWeight: 700 }}>
              {displayParamName(a.parameter)} {a.severity} — {fmtNum(a.value)}{unit} {sign} {fmtNum(a.threshold)}{unit}
            </span>
            <span style={{ opacity: 0.9, fontVariantNumeric: 'tabular-nums' }}>at {alertTime(a.firedAt)}</span>
            {a.alertIds.length > 0 && (
              <button
                onClick={() => onAck(a)}
                disabled={acking === a.key}
                style={{
                  marginLeft: 'auto', background: '#fff', color: '#B91C1C', border: 'none',
                  borderRadius: 6, padding: '4px 12px', fontSize: 12, fontWeight: 700,
                  cursor: acking === a.key ? 'wait' : 'pointer',
                }}
              >
                {acking === a.key ? 'Acknowledging…' : 'Acknowledge'}
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ── Dashboard page ─────────────────────────────────────────────────────────── */
export default function DashboardPage({ wsData, health, thresholds, onAlertCount }) {
  // Defensive destructure — all values have safe defaults
  const lastReading          = wsData?.lastReading          ?? null
  const lastCollectorReading = wsData?.lastCollectorReading ?? null
  const readings             = wsData?.readings             ?? []
  const isConnected          = wsData?.isConnected          ?? false
  const connectionStatus     = wsData?.connectionStatus     ?? 'CONNECTING'
  const lastEvent            = wsData?.lastEvent            ?? null

  // When the collector is active, use its reading as the authoritative live
  // display value so the dashboard never switches to a non-collector source
  // between the collector's ~4 s polling intervals.
  const displayReading = lastCollectorReading ?? lastReading

  const navigate = useNavigate()

  // ── Company parameters — drive every tile and chart on this page ────────────
  // Only what the company has is shown (a pH-only company sees only pH; a new
  // company sees none). The list refreshes live when a parameter is approved,
  // added or removed (server events are already scoped to this company).
  const { params, loading: paramsLoading, has } = useCompanyParameters()
  const sensorParams = params.filter(p => p.name.toLowerCase() !== 'temperature')
  const [paramToast, setParamToast] = useState('')

  useEffect(() => {
    if (lastEvent?.type === 'parameter_added' && lastEvent.parameter?.name) {
      setParamToast(`New parameter added: ${displayParamName(lastEvent.parameter.name)}`)
    } else if (lastEvent?.type === 'parameter_deleted' && lastEvent.name) {
      setParamToast(`Parameter removed: ${displayParamName(lastEvent.name)}`)
    } else return
    const t = setTimeout(() => setParamToast(''), 4000)
    return () => clearTimeout(t)
  }, [lastEvent])

  // ── Active (unacknowledged) alerts ─────────────────────────────────────────
  // Driven by alert events, not by whichever reading is on screen, so tiles keep
  // showing live values while an alert is open and the red goes on acknowledge.
  const activeAlerts = wsData?.activeAlerts ?? []
  const alertFor = name => activeAlerts.find(a => a.key === String(name).toLowerCase())
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    // Re-render when the next alert's 10 s blink ends so the blinking stops on time
    const ends = activeAlerts.map(a => a.blinkUntil).filter(t => t > Date.now())
    if (!ends.length) return
    const t = setTimeout(() => setNow(Date.now()), Math.min(...ends) - Date.now() + 30)
    return () => clearTimeout(t)
  }, [activeAlerts, now])
  const blinking = a => !!a && a.blinkUntil > now

  const unitOf = key => {
    if (key === 'temperature') return '°C'
    if (key === 'ph') return ''
    const p = params.find(ep => ep.name.toLowerCase() === key)
    return p?.unit ? ` ${p.unit}` : ''
  }

  const [acking, setAcking] = useState(null)
  const acknowledge = async (a) => {
    setAcking(a.key)
    const token = sessionStorage.getItem('admin_token') || ''
    const who   = sessionStorage.getItem('admin_username') || 'admin'
    const done  = []
    for (const id of a.alertIds) {
      try {
        const r = await fetch(`/api/alerts/${id}/acknowledge`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ acknowledged_by: who }),
        })
        // 409 = another admin acknowledged it first, 404 = gone — clear it here too
        if (r.ok || r.status === 404 || r.status === 409) done.push(id)
      } catch { /* leave it active; the user can retry */ }
    }
    if (done.length) wsData?.clearAlerts?.(done)
    if (done.length < a.alertIds.length) {
      setParamToast('Could not acknowledge — check the connection and try again')
      setTimeout(() => setParamToast(''), 4000)
    }
    setAcking(null)
  }

  return (
    <ErrorBoundary>
      {/* pH pulse keyframe injected once */}
      <style>{`
        @keyframes phPulse {
          0%,100% { box-shadow: 0 0 0 0 rgba(220,38,38,0.7); }
          50%      { box-shadow: 0 0 0 12px rgba(220,38,38,0); }
        }
      `}</style>

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
        {/* First screen: notices + the 8 tiles. It fills the visible area so the
            charts below always start on the next screen, fully visible. */}
        <section className="dash-first-screen space-y-5">
        <SuperAdminNotices />

        {/* Active alerts — red until acknowledged, blinks for the first 10 s */}
        <AlertBanner alerts={activeAlerts} now={now} unitOf={unitOf} onAck={acknowledge} acking={acking} />

        {/* Tiles — status tiles always; sensor tiles only for the company's own parameters */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 auto-rows-fr gap-4">
          {has('temperature') && (
            <AlertFrame alert={alertFor('temperature')} blinking={blinking(alertFor('temperature'))}>
              <TemperatureCard reading={displayReading} thresholds={thresholds}
                alert={alertFor('temperature')} blinking={blinking(alertFor('temperature'))} />
            </AlertFrame>
          )}
          <StatusCard isConnected={isConnected} connectionStatus={connectionStatus} />
          <AlertsTodayCard count={Math.max(health?.alerts_today ?? 0, activeAlerts.length)} />
          <UptimeCard uptimeSeconds={health?.uptime_seconds ?? null} />

          {sensorParams.map(p => {
            // Case-insensitive match — Pro-Server EX column names may differ in case
            const ep = displayReading?.extra_params
            const liveValue = ep
              ? (ep[p.name] ?? Object.entries(ep).find(([k]) => k.toLowerCase() === p.name.toLowerCase())?.[1] ?? null)
              : null
            const pa    = alertFor(p.name)
            const shown = liveValue ?? pa?.latestValue ?? null
            const mn = p.min_value != null ? Number(p.min_value) : null
            const mx = p.max_value != null ? Number(p.max_value) : null
            const inRange = shown != null && mn != null && mx != null ? shown >= mn && shown <= mx : null
            const outOfRange = !pa && shown != null && inRange === false
            const subtitle = pa
              ? alertLine(pa)
              : shown != null
                ? (inRange == null ? 'Live reading' : inRange ? 'Within normal range' : 'Out of range')
                : 'Waiting for sensor data…'
            const isPh = p.name.toLowerCase() === 'ph'
            return (
              <AlertFrame key={p.name} alert={pa} blinking={blinking(pa)}>
                <SensorCard
                  icon={isPh ? FlaskConical : Cpu}
                  iconColor={pa ? '#DC2626' : outOfRange ? '#D97706' : '#7C3AED'}
                  label={p.name}
                  value={shown != null ? trunc3(shown) : null}
                  alert={!!pa}
                  warn={outOfRange}
                  blink={blinking(pa)}
                  unit={p.unit || ''}
                  subtitle={subtitle}
                  footer={`Live ${displayParamName(p.name)} reading`}
                  range={mn != null && mx != null ? `${mn} – ${mx}` : undefined}
                />
              </AlertFrame>
            )
          })}
        </div>

        {/* Nothing configured yet (new company) */}
        {!paramsLoading && params.length === 0 && (
          <div className="card px-6 py-8 text-center">
            <SlidersHorizontal size={26} className="mx-auto mb-2 text-purple-400" />
            <p className="text-sm font-semibold text-gray-800">No parameters yet</p>
            <p className="text-xs text-gray-500 mt-1 max-w-md mx-auto">
              Request your first parameter in Settings → Add Parameter. Once the Super Admin
              approves it, its tile and live chart appear here automatically.
            </p>
            <button onClick={() => navigate('/settings')}
              className="mt-3 text-xs font-semibold text-purple-600 hover:text-purple-700">
              Go to Settings →
            </button>
          </div>
        )}

        </section>

        {/* Second screen — one live chart per parameter the company has */}
        {params.length > 0 && (
          <div className="dash-snap grid grid-cols-1 lg:grid-cols-2 gap-4">
            {has('temperature') && <LiveChart readings={readings} thresholds={thresholds} />}
            {sensorParams.map(p => (
              p.name.toLowerCase() === 'ph'
                ? <PhLiveChart key={p.name} readings={readings} />
                : <ParamLiveChart key={p.name} readings={readings} param={p} />
            ))}
          </div>
        )}
        {/* Row 5 — Mini alert preview */}
        <div className="dash-snap card">
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
