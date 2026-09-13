/**
 * src/components/dashboard/PhLiveChart.jsx
 * Real-time pH chart — mirrors LiveChart.jsx but reads extra_params.ph.
 * Fetches pH thresholds from /api/config/alert-settings on mount.
 */
import { useMemo, useRef, useState, useEffect } from 'react'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import { formatTime } from '../../utils/time.js'
import Card from '../shared/Card.jsx'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

const TEAL = '#0D9488'

function getPhValue(r) {
  const ep = r?.extra_params
  if (!ep || typeof ep !== 'object') return null
  const key = Object.keys(ep).find(k => k.toLowerCase() === 'ph')
  return key != null ? ep[key] : null
}

export default function PhLiveChart({ readings }) {
  const [thresholds, setThresholds] = useState({ high: 7.0, low: 5.5 })

  useEffect(() => {
    const token = sessionStorage.getItem('admin_token') || ''
    fetch('/api/config/alert-settings', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => r.ok ? r.json() : null)
      .then(s => {
        if (s) {
          setThresholds({
            high: s.ph_threshold_max ?? s.ph_threshold ?? 7.0,
            low:  s.ph_threshold_min ?? 5.5,
          })
        }
      })
      .catch(() => {})
  }, [])

  const safeReadings = Array.isArray(readings) ? readings : []

  if (safeReadings.length === 0) {
    return (
      <Card title="Live pH" subtitle="Real-time sensor data">
        <div style={{ height: 260 }} className="flex items-center justify-center text-gray-400 text-sm">
          <div className="text-center">
            <div className="text-2xl mb-2">🧪</div>
            <p>Waiting for pH data…</p>
            <p className="text-xs text-gray-300 mt-1">pH readings appear here in real time</p>
          </div>
        </div>
      </Card>
    )
  }

  return <PhLiveChartInner readings={safeReadings} thresholds={thresholds} />
}

function PhLiveChartInner({ readings, thresholds }) {
  const chartRef = useRef(null)
  const { high, low } = thresholds

  const phValues = readings.map(r => getPhValue(r))
  const validPh  = phValues.filter(v => v !== null)

  const minY = validPh.length ? Math.min(Math.floor(Math.min(...validPh) - 0.2), low - 0.5) : low - 1
  const maxY = validPh.length ? Math.max(Math.ceil(Math.max(...validPh)  + 0.2), high + 0.5) : high + 1

  const labels = readings.map((r, i) =>
    i % 10 === 0 ? (formatTime(r?.timestamp) || '') : ''
  )

  const data = useMemo(() => ({
    labels,
    datasets: [
      {
        label: 'pH',
        data: phValues,
        borderColor: TEAL,
        backgroundColor: (ctx) => {
          try {
            const chart = ctx.chart
            const { ctx: c, chartArea } = chart
            if (!chartArea) return 'rgba(13,148,136,0.05)'
            const grad = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom)
            grad.addColorStop(0, 'rgba(13,148,136,0.18)')
            grad.addColorStop(1, 'rgba(13,148,136,0.01)')
            return grad
          } catch { return 'rgba(13,148,136,0.05)' }
        },
        borderWidth: 2,
        pointRadius: phValues.map(v =>
          v != null && (v > high || v < low) ? 5 : 0
        ),
        pointBackgroundColor: phValues.map(v =>
          v != null && (v > high || v < low) ? '#EF4444' : TEAL
        ),
        pointBorderColor: '#fff',
        pointBorderWidth: 2,
        tension: 0.4,
        fill: true,
        spanGaps: true,
      },
      {
        label: `High: ${high} pH`,
        data: readings.map(() => high),
        borderColor: '#EF4444',
        borderDash: [6, 3],
        borderWidth: 1.5,
        pointRadius: 0,
        fill: false,
        tension: 0,
      },
      {
        label: `Low: ${low} pH`,
        data: readings.map(() => low),
        borderColor: '#3B82F6',
        borderDash: [6, 3],
        borderWidth: 1.5,
        pointRadius: 0,
        fill: false,
        tension: 0,
      },
    ],
  }), [readings, high, low, phValues, labels]) // eslint-disable-line

  const options = useMemo(() => ({
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        position: 'top',
        labels: {
          font: { size: 11, family: 'Inter' },
          color: '#6B7280',
          padding: 16,
          usePointStyle: true,
          pointStyleWidth: 8,
        },
      },
      tooltip: {
        callbacks: {
          label: (ctx) => {
            if (ctx.datasetIndex === 0) return ` ${ctx.parsed.y?.toFixed(3) ?? '—'} pH`
            return ` ${ctx.dataset.label}`
          },
          title: (items) => {
            const idx = items[0]?.dataIndex
            if (idx !== undefined && readings[idx]) {
              return formatTime(readings[idx]?.timestamp) || ''
            }
            return ''
          },
        },
        backgroundColor: '#1F2937',
        titleFont: { size: 11, family: 'Inter' },
        bodyFont:  { size: 12, family: 'Inter', weight: '600' },
        padding: 10,
        cornerRadius: 8,
      },
    },
    scales: {
      x: {
        grid: { color: '#F3F4F6' },
        ticks: {
          font: { size: 10, family: 'Inter' },
          color: '#9CA3AF',
          maxRotation: 0,
        },
      },
      y: {
        min: minY,
        max: maxY,
        grid: { color: '#F3F4F6' },
        ticks: {
          font: { size: 10, family: 'Inter' },
          color: '#9CA3AF',
          callback: v => `${v} pH`,
        },
      },
    },
  }), [readings, minY, maxY, high, low]) // eslint-disable-line

  const lastTs  = formatTime(readings.at(-1)?.timestamp) || '—'
  const lastPh  = phValues.filter(v => v != null).at(-1)

  return (
    <Card
      title="Live pH"
      subtitle="Real-time sensor data"
      headerRight={
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">Updated {lastTs}</span>
          {lastPh != null && (
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full"
              style={{ background: '#CCFBF1', color: '#0D9488' }}>
              {lastPh.toFixed(3)} pH
            </span>
          )}
        </div>
      }
    >
      <div style={{ height: 260 }}>
        <Line ref={chartRef} data={data} options={options} />
      </div>
    </Card>
  )
}
