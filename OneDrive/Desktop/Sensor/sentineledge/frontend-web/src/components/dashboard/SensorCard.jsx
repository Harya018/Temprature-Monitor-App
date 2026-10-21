/**
 * src/components/dashboard/SensorCard.jsx
 * Generic sensor tile — same DashTile layout as the temperature / status tiles.
 *
 * Props:
 *   icon      : lucide-react component
 *   iconColor : string (hex)
 *   label     : string — e.g. "Pressure"
 *   value     : string | number | null  (null → "waiting for data")
 *   unit      : string — e.g. "bar"
 *   subtitle  : string — one line under the value
 *   footer    : string — bottom-left line (optional)
 *   simulated : boolean — value is generated locally, not from a sensor
 *   alert     : boolean — an unacknowledged alert is open for this parameter (red)
 *   warn      : boolean — value is outside its range, alert already acknowledged (amber)
 *   blink     : boolean — alert fired within the last 10 s (badge pulses)
 *   range     : string — e.g. "0 – 14" shown in the footer (optional)
 */
import DashTile from './DashTile.jsx'
import Badge from '../shared/Badge.jsx'

// "ph" → "pH", "humidity" → "Humidity"; DB parameter names arrive lower-case
export function displayParamName(name) {
  const s = String(name ?? '')
  if (s.toLowerCase() === 'ph') return 'pH'
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export default function SensorCard({
  icon, iconColor = '#7C3AED', label, value, unit, subtitle, footer,
  simulated = false, alert = false, warn = false, blink = false, range,
}) {
  const hasValue = value !== null && value !== undefined && value !== '—'
  const badge = alert
    ? <Badge color="red" label="ALERT" pulse={blink} />
    : warn
      ? <Badge color="amber" label="OUT OF RANGE" />
    : simulated
      ? <Badge color="gray" label="SIMULATED" />
      : hasValue
        ? <Badge color="purple" label="LIVE" />
        : <Badge color="gray" label="NO DATA" />

  return (
    <DashTile
      icon={icon}
      iconColor={iconColor}
      label={displayParamName(label)}
      badge={badge}
      value={hasValue ? value : null}
      valueColor={alert ? '#DC2626' : warn ? '#B45309' : '#1F2937'}
      unit={String(unit ?? '').toLowerCase() === 'ph' ? 'pH' : unit}
      caption={subtitle ?? (hasValue ? 'Live reading' : 'Waiting for sensor data…')}
      footerLeft={footer ?? `Live ${displayParamName(label)} reading`}
      footerRight={range ? `Range ${range}` : (simulated ? 'Demo · 3s' : 'Every 5s')}
    />
  )
}
