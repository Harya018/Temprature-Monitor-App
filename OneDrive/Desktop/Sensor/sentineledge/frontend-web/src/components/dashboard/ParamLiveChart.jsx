/**
 * src/components/dashboard/ParamLiveChart.jsx
 * Real-time chart for any company parameter (read from extra_params[name]).
 * Limit lines come from the parameter's own min/max (company_parameters) —
 * the same limits the backend uses to raise alerts for custom parameters.
 */
import { useMemo } from 'react'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend, Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import { formatTime } from '../../utils/time.js'
import Card from '../shared/Card.jsx'
import { displayParamName } from './SensorCard.jsx'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

const COLOR = '#7C3AED'

function valueOf(r, name) {
  const ep = r?.extra_params
  if (!ep || typeof ep !== 'object') return null
  const key = Object.keys(ep).find(k => k.toLowerCase() === String(name).toLowerCase())
  const v = key != null ? Number(ep[key]) : null
  return v == null || isNaN(v) ? null : v
}

export default function ParamLiveChart({ readings, param }) {
  const label = displayParamName(param.name)
  const unit  = param.unit ? ` ${param.unit}` : ''
  const rows  = Array.isArray(readings) ? readings : []
  const values = rows.map(r => valueOf(r, param.name))
  const hasData = values.some(v => v != null)

  if (!hasData) {
    return (
      <Card title={`Live ${label}`} subtitle="Real-time sensor data">
        <div style={{ height: 260 }} className="flex items-center justify-center text-gray-400 text-sm">
          <div className="text-center">
            <p>Waiting for {label} data…</p>
            <p className="text-xs text-gray-300 mt-1">{label} readings appear here in real time</p>
          </div>
        </div>
      </Card>
    )
  }
  return <Inner rows={rows} values={values} param={param} label={label} unit={unit} />
}

function Inner({ rows, values, param, label, unit }) {
  const high = param.max_value != null ? Number(param.max_value) : null
  const low  = param.min_value != null ? Number(param.min_value) : null
  const valid = values.filter(v => v != null)
  const lo = Math.min(...valid, ...(low  != null ? [low]  : []))
  const hi = Math.max(...valid, ...(high != null ? [high] : []))
  const pad = Math.max((hi - lo) * 0.1, 0.5)
  const outside = v => v != null && ((high != null && v > high) || (low != null && v < low))

  const data = useMemo(() => ({
    labels: rows.map((r, i) => (i % 10 === 0 ? (formatTime(r?.timestamp) || '') : '')),
    datasets: [
      {
        label, data: values, borderColor: COLOR, backgroundColor: 'rgba(124,58,237,0.08)',
        borderWidth: 2, tension: 0.4, fill: true, spanGaps: true,
        pointRadius: values.map(v => (outside(v) ? 5 : 0)),
        pointBackgroundColor: values.map(v => (outside(v) ? '#EF4444' : COLOR)),
        pointBorderColor: '#fff', pointBorderWidth: 2,
      },
      ...(high != null ? [{ label: `High: ${high}${unit}`, data: rows.map(() => high), borderColor: '#EF4444',
        borderDash: [6, 3], borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0 }] : []),
      ...(low != null ? [{ label: `Low: ${low}${unit}`, data: rows.map(() => low), borderColor: '#3B82F6',
        borderDash: [6, 3], borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0 }] : []),
    ],
  }), [rows, values, high, low, label, unit]) // eslint-disable-line

  const options = useMemo(() => ({
    animation: false, responsive: true, maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'top', labels: { font: { size: 11, family: 'Inter' }, color: '#6B7280',
        padding: 16, usePointStyle: true, pointStyleWidth: 8 } },
      tooltip: {
        callbacks: {
          label: ctx => (ctx.datasetIndex === 0 ? ` ${ctx.parsed.y?.toFixed(3) ?? '—'}${unit}` : ` ${ctx.dataset.label}`),
          title: items => formatTime(rows[items[0]?.dataIndex]?.timestamp) || '',
        },
        backgroundColor: '#1F2937', padding: 10, cornerRadius: 8,
      },
    },
    scales: {
      x: { grid: { color: '#F3F4F6' }, ticks: { font: { size: 10, family: 'Inter' }, color: '#9CA3AF', maxRotation: 0 } },
      y: { min: lo - pad, max: hi + pad, grid: { color: '#F3F4F6' },
        ticks: { font: { size: 10, family: 'Inter' }, color: '#9CA3AF' } },
    },
  }), [rows, lo, hi, pad, unit])

  const last = valid.at(-1)
  return (
    <Card
      title={`Live ${label}`}
      subtitle="Real-time sensor data"
      headerRight={
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">Updated {formatTime(rows.at(-1)?.timestamp) || '—'}</span>
          {last != null && (
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ background: '#EDE9FE', color: COLOR }}>
              {last.toFixed(3)}{unit}
            </span>
          )}
        </div>
      }
    >
      <div style={{ height: 260 }}>
        <Line data={data} options={options} />
      </div>
    </Card>
  )
}
