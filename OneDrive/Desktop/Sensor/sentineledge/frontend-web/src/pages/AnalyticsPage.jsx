/**
 * AnalyticsPage.jsx — Sensor data analytics dashboard.
 * 10 charts: live trend, daily/hourly/weekly avg, distribution,
 * breach frequency, alert heatmap, subscriber response,
 * channel delivery, summary stats.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  LineChart, Line, BarChart, Bar, ComposedChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, ErrorBar, RadialBarChart, RadialBar,
  Cell, Legend,
} from 'recharts'
import {
  TrendingUp, Upload, RefreshCw, Download,
  CheckCircle, AlertCircle, BarChart2, Clock,
  Wifi, WifiOff, ChevronDown,
} from 'lucide-react'
import './AnalyticsPage.css'

// ── auth headers (matches api.js pattern) ─────────────────────────────────────
function adminHeaders() {
  const token = sessionStorage.getItem('admin_token') || ''
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function apiFetch(path) {
  const res = await fetch(path, { headers: adminHeaders() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

function exportRows(rows, filename) {
  if (!rows?.length) return
  const header = Object.keys(rows[0]).join(',')
  const body   = rows.map(r =>
    Object.values(r).map(v => (Array.isArray(v) ? JSON.stringify(v) : (v ?? ''))).join(',')
  ).join('\n')
  const blob = new Blob([header + '\n' + body], { type: 'text/csv' })
  const a    = document.createElement('a')
  a.href     = URL.createObjectURL(blob)
  a.download = filename
  a.click()
}

// ── colour palette ─────────────────────────────────────────────────────────────
const PURPLE    = '#7C3AED'
const PURPLE_LT = '#C4B5FD'
const TEAL      = '#0D9488'
const AMBER     = '#D97706'
const CORAL     = '#EF4444'
const DAYS      = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function barColor(value, max) {
  const ratio = max > 0 ? value / max : 0
  if (ratio < 0.4) return TEAL
  if (ratio < 0.7) return AMBER
  return CORAL
}

// ── fetch approved company parameters ────────────────────────────────────────
async function fetchCompanyParams() {
  try {
    const rows = await apiFetch('/api/admin/parameters')
    return Array.isArray(rows) ? rows : []
  } catch { return [] }
}

// ── shared chart states ────────────────────────────────────────────────────────
function useChartData(url, deps = []) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try { setData(await apiFetch(url)) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps])

  useEffect(() => { load() }, [load])
  return { data, loading, error, reload: load }
}

// ── skeleton / empty / error wrappers ─────────────────────────────────────────
function Skeleton({ h = 220 }) {
  return <div className="chart-skeleton" style={{ height: h }} />
}

function Empty({ h = 220 }) {
  return (
    <div className="chart-empty" style={{ height: h }}>
      <BarChart2 size={28} />
      <span>No data for selected range</span>
    </div>
  )
}

function ChartError({ h = 220, onRetry }) {
  return (
    <div className="chart-error" style={{ height: h }}>
      <AlertCircle size={24} />
      <span>Failed to load</span>
      <button className="retry-btn" onClick={onRetry}>Retry</button>
    </div>
  )
}

// ── custom tooltip ─────────────────────────────────────────────────────────────
function CustomTooltip({ active, payload, label, unit = '' }) {
  if (!active || !payload?.length) return null
  return (
    <div className="custom-tooltip">
      <div className="ct-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="ct-value" style={{ color: p.color || '#F9FAFB' }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(1) : p.value}{unit}
        </div>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 1 — Live Trend
// ─────────────────────────────────────────────────────────────────────────────
function LiveTrendChart({ source, parameter, fromDate, toDate, wsData, unit = '' }) {
  const [data,      setData]      = useState([])
  const [thresholds, setThresholds] = useState({ high: null, low: null })
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const intervalRef = useRef(null)

  // Extract so the effect dep tracks the array reference, not the whole wsData object
  const wsReadings = wsData?.readings

  const buildUrl = useCallback(() => {
    const params = new URLSearchParams({ parameter, source, limit: 60 })
    if (fromDate) params.append('from_date', fromDate)
    if (toDate)   params.append('to_date',   toDate)
    return `/api/analytics/charts/live-trend?${params}`
  }, [parameter, source, fromDate, toDate])

  const load = useCallback(async () => {
    try {
      const rows = await apiFetch(buildUrl())
      setData(rows.map(r => ({
        ts:    r.timestamp ? r.timestamp.slice(11, 19) : '',
        value: r.value,
      })))
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [buildUrl])

  useEffect(() => {
    apiFetch('/api/health')
      .then(h => {
        if (h?.thresholds) {
          setThresholds({ high: h.thresholds.temp_high, low: h.thresholds.temp_low })
        }
      })
      .catch(() => {})
  }, [])

  // Initial API fetch + polling fallback (for non-live sources or when WS has no data yet)
  useEffect(() => {
    clearInterval(intervalRef.current)
    setLoading(true)
    load()
    if (source === 'live') {
      // Polling fallback — cancelled immediately once WS readings arrive below
      intervalRef.current = setInterval(load, 5000)
    }
    return () => clearInterval(intervalRef.current)
  }, [load, source])

  // Real-time sync from WebSocket — fires every second when live + temperature
  useEffect(() => {
    if (source !== 'live' || parameter !== 'temperature') return
    if (!wsReadings?.length) return
    clearInterval(intervalRef.current)   // WS is active — cancel API polling
    setData(wsReadings.map(r => ({
      ts:    r.timestamp ? r.timestamp.slice(11, 19) : '',
      value: r.temperature,
    })))
    setLoading(false)
    setError(null)
  }, [wsReadings, source, parameter])

  const isLive = source === 'live'

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title">
          <TrendingUp size={15} color={PURPLE} />
          Live Sensor Trend — {parameter}
          {isLive && (
            <span className="chart-live-badge">
              <span className="chart-live-dot" /> LIVE
            </span>
          )}
        </span>
        <button className="btn-export-small" onClick={() => exportRows(data, `live-trend-${parameter}.csv`)}>↓ CSV</button>
      </div>

      {loading && !data.length ? <Skeleton h={240} /> :
       error ? <ChartError h={240} onRetry={load} /> :
       !data.length ? <Empty h={240} /> : (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="ts" tick={{ fontSize: 10, fill: '#9CA3AF' }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: '#9CA3AF' }} domain={['auto', 'auto']} />
            <Tooltip content={<CustomTooltip unit={unit} />} />
            {thresholds.high != null && (
              <ReferenceLine y={thresholds.high} stroke={CORAL} strokeDasharray="4 3"
                label={{ value: `High: ${thresholds.high}${unit}`, position: 'insideTopRight', fontSize: 10, fill: CORAL }} />
            )}
            {thresholds.low != null && (
              <ReferenceLine y={thresholds.low} stroke="#3B82F6" strokeDasharray="4 3"
                label={{ value: `Low: ${thresholds.low}${unit}`, position: 'insideBottomRight', fontSize: 10, fill: '#3B82F6' }} />
            )}
            <Line
              type="monotone" dataKey="value" stroke={PURPLE} strokeWidth={2}
              dot={(props) => {
                const { cx, cy, value } = props
                const breach =
                  (thresholds.high != null && value > thresholds.high) ||
                  (thresholds.low  != null && value < thresholds.low)
                if (!breach) return <circle key={`dot-${cx}-${cy}`} r={0} />
                return <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={4} fill={CORAL} stroke="#fff" strokeWidth={1.5} />
              }}
              activeDot={{ r: 5, fill: PURPLE }}
              name={parameter}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 2 — Daily Average
// ─────────────────────────────────────────────────────────────────────────────
function DailyAvgChart({ source, parameter, fromDate, toDate }) {
  const unit = parameter === 'temperature' ? '°C' : 'hPa'
  const url = `/api/analytics/charts/daily-avg?parameter=${parameter}&source=${source}` +
    (fromDate ? `&from_date=${fromDate}` : '') + (toDate ? `&to_date=${toDate}` : '')
  const { data, loading, error, reload } = useChartData(url)

  const rows = (data || []).map(r => ({
    date: (r.date || '').slice(5),
    avg:  Number(r.avg),
    min:  Number(r.min),
    max:  Number(r.max),
    cnt:  r.reading_count,
  }))

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title"><TrendingUp size={14} color={PURPLE} /> Daily Average</span>
        <button className="btn-export-small" onClick={() => exportRows(rows, `daily-avg-${parameter}.csv`)}>↓ CSV</button>
      </div>
      {loading ? <Skeleton /> : error ? <ChartError onRetry={reload} /> :
       !rows.length ? <Empty /> : (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9CA3AF' }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: '#9CA3AF' }} domain={['auto', 'auto']} />
            <Tooltip content={<CustomTooltip unit={unit} />} />
            <Area type="monotone" dataKey="max" fill={PURPLE_LT} stroke="none" fillOpacity={0.25} name="max" />
            <Area type="monotone" dataKey="min" fill="#fff" stroke="none" fillOpacity={1} name="min" />
            <Line type="monotone" dataKey="avg" stroke={PURPLE} strokeWidth={2} dot={false} name="avg" />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 3 — Hourly Average
// ─────────────────────────────────────────────────────────────────────────────
function HourlyAvgChart({ source, parameter, fromDate, toDate }) {
  const unit = parameter === 'temperature' ? '°C' : 'hPa'
  const url = `/api/analytics/charts/hourly-avg?parameter=${parameter}&source=${source}` +
    (fromDate ? `&from_date=${fromDate}` : '') + (toDate ? `&to_date=${toDate}` : '')
  const { data, loading, error, reload } = useChartData(url)

  const byHour = Object.fromEntries((data || []).map(r => [r.hour, { hour: r.hour, avg: Number(r.avg), cnt: r.reading_count }]))
  const rows   = Array.from({ length: 24 }, (_, h) => byHour[h] ?? { hour: h, avg: 0, cnt: 0 })
  const maxAvg = rows.length ? Math.max(...rows.map(r => r.avg)) : 1

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title"><Clock size={14} color={PURPLE} /> Avg by Hour of Day</span>
        <button className="btn-export-small" onClick={() => exportRows(rows, `hourly-avg-${parameter}.csv`)}>↓ CSV</button>
      </div>
      {loading ? <Skeleton /> : error ? <ChartError onRetry={reload} /> :
       !data?.length ? <Empty /> : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" vertical={false} />
            <XAxis dataKey="hour" tick={{ fontSize: 10, fill: '#9CA3AF' }} />
            <YAxis tick={{ fontSize: 10, fill: '#9CA3AF' }} domain={['auto', 'auto']} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const d = payload[0].payload
                return (
                  <div className="custom-tooltip">
                    <div className="ct-label">Hour {d.hour}:00</div>
                    <div className="ct-value">Avg: {d.avg.toFixed(1)}{unit}</div>
                    <div className="ct-label">{d.cnt} readings</div>
                  </div>
                )
              }}
            />
            <Bar dataKey="avg" radius={[3, 3, 0, 0]}>
              {rows.map((r, i) => (
                <Cell key={i} fill={barColor(r.avg, maxAvg)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 4 — Weekly Average
// ─────────────────────────────────────────────────────────────────────────────
function WeeklyAvgChart({ source, parameter, fromDate, toDate }) {
  const unit = parameter === 'temperature' ? '°C' : 'hPa'
  const url = `/api/analytics/charts/weekly-avg?parameter=${parameter}&source=${source}` +
    (fromDate ? `&from_date=${fromDate}` : '') + (toDate ? `&to_date=${toDate}` : '')
  const { data, loading, error, reload } = useChartData(url)

  const rows = (data || []).map(r => ({
    week:  `Wk ${r.week_number}`,
    avg:   Number(r.avg),
    error: [Number(r.avg) - Number(r.min), Number(r.max) - Number(r.avg)],
  }))

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title"><BarChart2 size={14} color={PURPLE} /> Weekly Average</span>
        <button className="btn-export-small" onClick={() => exportRows(rows, `weekly-avg-${parameter}.csv`)}>↓ CSV</button>
      </div>
      {loading ? <Skeleton /> : error ? <ChartError onRetry={reload} /> :
       !rows.length ? <Empty /> : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="week" tick={{ fontSize: 10, fill: '#9CA3AF' }} />
            <YAxis tick={{ fontSize: 10, fill: '#9CA3AF' }} domain={['auto', 'auto']} />
            <Tooltip content={<CustomTooltip unit={unit} />} />
            <Line type="monotone" dataKey="avg" stroke={PURPLE} strokeWidth={2} dot={{ r: 4, fill: PURPLE }} name="avg">
              <ErrorBar dataKey="error" width={4} strokeWidth={1.5} stroke={PURPLE_LT} direction="y" />
            </Line>
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 5 — Distribution (horizontal bar)
// ─────────────────────────────────────────────────────────────────────────────
function DistributionChart({ source, parameter, fromDate, toDate }) {
  const url = `/api/analytics/charts/distribution?parameter=${parameter}&source=${source}` +
    (fromDate ? `&from_date=${fromDate}` : '') + (toDate ? `&to_date=${toDate}` : '')
  const { data, loading, error, reload } = useChartData(url)
  const rows = data || []

  const bucketColor = (label) => {
    if (label.startsWith('<'))  return TEAL
    if (label.startsWith('>'))  return CORAL
    const lo = parseFloat(label)
    if (lo < 50) return TEAL
    if (lo < 70) return AMBER
    return CORAL
  }

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title"><BarChart2 size={14} color={PURPLE} /> Distribution</span>
        <button className="btn-export-small" onClick={() => exportRows(rows, `distribution-${parameter}.csv`)}>↓ CSV</button>
      </div>
      {loading ? <Skeleton /> : error ? <ChartError onRetry={reload} /> :
       !rows.length ? <Empty /> : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 40, bottom: 0, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: '#9CA3AF' }} />
            <YAxis type="category" dataKey="bucket_label" tick={{ fontSize: 10, fill: '#6B7280' }} width={58} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const d = payload[0].payload
                return (
                  <div className="custom-tooltip">
                    <div className="ct-label">{d.bucket_label}</div>
                    <div className="ct-value">{d.count} readings ({d.percentage}%)</div>
                  </div>
                )
              }}
            />
            <Bar dataKey="count" radius={[0, 3, 3, 0]}>
              {rows.map((r, i) => (
                <Cell key={i} fill={bucketColor(r.bucket_label)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 6 — Breach Frequency
// ─────────────────────────────────────────────────────────────────────────────
const BREACH_COLORS = [PURPLE, CORAL, AMBER, TEAL, '#EC4899', '#8B5CF6']

function BreachFrequencyChart({ fromDate, toDate }) {
  const url = `/api/analytics/charts/breach-frequency` +
    `?${fromDate ? `from_date=${fromDate}&` : ''}${toDate ? `to_date=${toDate}` : ''}`
  const { data, loading, error, reload } = useChartData(url)
  const series = data || []

  // Flatten at component level so export button can access chartData during any render phase
  const bfDateSet = new Set()
  series.forEach(s => s.daily_series?.forEach(d => bfDateSet.add(d.date)))
  const bfDates   = [...bfDateSet].sort()
  const chartData = bfDates.map(d => {
    const row = { date: d.slice(5) }
    series.forEach(s => {
      const match = s.daily_series?.find(x => x.date === d)
      row[s.parameter] = match ? match.count : 0
    })
    return row
  })

  if (loading) return <div className="chart-card"><Skeleton h={240} /></div>
  if (error)   return <div className="chart-card"><ChartError h={240} onRetry={reload} /></div>
  if (!series.length || series.every(s => s.breach_count === 0))
    return (
      <div className="chart-card">
        <div className="chart-card-header">
          <span className="chart-card-title"><AlertCircle size={14} color={PURPLE} /> Breach Frequency</span>
          <button className="btn-export-small" onClick={() => exportRows(chartData, 'breach-frequency.csv')}>↓ CSV</button>
        </div>
        <div className="all-clear-card"><CheckCircle size={18} /> All clear — no breaches in this period</div>
      </div>
    )

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title"><AlertCircle size={14} color={CORAL} /> Breach Frequency</span>
        <button className="btn-export-small" onClick={() => exportRows(chartData, 'breach-frequency.csv')}>↓ CSV</button>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={chartData} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9CA3AF' }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 10, fill: '#9CA3AF' }} allowDecimals={false} />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
          {series.map((s, i) => (
            <Bar key={s.parameter} dataKey={s.parameter} fill={BREACH_COLORS[i % BREACH_COLORS.length]} radius={[3,3,0,0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 7 — Alert Heatmap
// ─────────────────────────────────────────────────────────────────────────────
function cellColor(count) {
  if (count === 0) return '#F9FAFB'
  if (count <= 2)  return '#FEF3C7'
  if (count <= 5)  return '#FCD34D'
  return '#EF4444'
}

function AlertHeatmap({ fromDate, toDate }) {
  const url = `/api/analytics/charts/alert-heatmap` +
    `?${fromDate ? `from_date=${fromDate}&` : ''}${toDate ? `to_date=${toDate}` : ''}`
  const { data, loading, error, reload } = useChartData(url)

  const grid = {}
  ;(data || []).forEach(r => {
    const key = `${r.hour}-${r.day_of_week}`
    grid[key] = r.count
  })

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title"><BarChart2 size={14} color={PURPLE} /> Alert Heatmap (Hour × Day)</span>
        <button className="btn-export-small" onClick={() => exportRows(data || [], 'alert-heatmap.csv')}>↓ CSV</button>
      </div>
      {loading ? <Skeleton h={200} /> : error ? <ChartError h={200} onRetry={reload} /> : (
        <>
          <div className="heatmap-wrapper">
            <div className="heatmap-grid">
              {/* Hour labels */}
              <div className="heatmap-row-labels">
                {Array.from({ length: 24 }, (_, h) => (
                  <div key={h} className="heatmap-row-label">
                    {h % 3 === 0 ? `${h}h` : ''}
                  </div>
                ))}
              </div>
              {/* Day columns */}
              <div className="heatmap-cols">
                {DAYS.map((day, d) => (
                  <div key={d} className="heatmap-col">
                    <div className="heatmap-col-label">{day}</div>
                    {Array.from({ length: 24 }, (_, h) => {
                      const count = grid[`${h}-${d}`] || 0
                      return (
                        <div
                          key={h}
                          className="heatmap-cell"
                          style={{ background: cellColor(count) }}
                          data-tip={`${day} ${h}:00 — ${count} alert${count !== 1 ? 's' : ''}`}
                        />
                      )
                    })}
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="heatmap-legend">
            <span>0</span>
            <div className="heatmap-legend-scale">
              {['#F9FAFB','#FEF3C7','#FCD34D','#F59E0B','#EF4444'].map((c, i) => (
                <div key={i} className="heatmap-legend-cell" style={{ background: c }} />
              ))}
            </div>
            <span>High</span>
          </div>
        </>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 8 — Subscriber Response Times (table)
// ─────────────────────────────────────────────────────────────────────────────
function SubscriberResponseTable({ fromDate, toDate }) {
  const url = `/api/analytics/charts/subscriber-response` +
    `?${fromDate ? `from_date=${fromDate}&` : ''}${toDate ? `to_date=${toDate}` : ''}`
  const { data, loading, error, reload } = useChartData(url)
  const rows = data || []

  const ackClass = (pct) => pct >= 90 ? 'ack-high' : pct >= 70 ? 'ack-mid' : 'ack-low'

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title"><Clock size={14} color={PURPLE} /> Subscriber Response</span>
        <button className="btn-export-small" onClick={() => exportRows(rows, 'subscriber-response.csv')}>↓ CSV</button>
      </div>
      {loading ? <Skeleton /> : error ? <ChartError onRetry={reload} /> :
       !rows.length ? (
         <div className="chart-empty" style={{ height: 180 }}>
           <Clock size={24} />
           <span>No acknowledgement data available</span>
         </div>
       ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="response-table">
            <thead>
              <tr>
                <th>Subscriber</th>
                <th>Avg Ack</th>
                <th>Fastest</th>
                <th>Slowest</th>
                <th>Alerts</th>
                <th>Ack Rate</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 500 }}>{r.name}</td>
                  <td>{r.avg_minutes} min</td>
                  <td style={{ color: '#059669' }}>{r.fastest_minutes} min</td>
                  <td style={{ color: '#DC2626' }}>{r.slowest_minutes} min</td>
                  <td>{r.total_alerts}</td>
                  <td>
                    <span className={`ack-rate-cell ${ackClass(r.ack_rate_percent)}`}>
                      {r.ack_rate_percent}%
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 9 — Channel Delivery Rates (progress rings)
// ─────────────────────────────────────────────────────────────────────────────
function DeliveryRing({ label, sent, failed, rate, color }) {
  const r = 38, circ = 2 * Math.PI * r
  const fill = (rate / 100) * circ

  return (
    <div className="delivery-ring-item">
      <div className="ring-label">{label}</div>
      <div className="ring-svg" style={{ width: 88, height: 88, position: 'relative' }}>
        <svg width="88" height="88" viewBox="0 0 88 88">
          <circle cx="44" cy="44" r={r} fill="none" stroke="#F3F4F6" strokeWidth="8" />
          <circle
            cx="44" cy="44" r={r} fill="none" stroke={color}
            strokeWidth="8" strokeDasharray={`${fill} ${circ}`}
            strokeLinecap="round"
            transform="rotate(-90 44 44)"
          />
        </svg>
        <div className="ring-pct" style={{ color }}>{rate}%</div>
      </div>
      <div className="ring-sub">{sent} sent · {failed} failed</div>
    </div>
  )
}

function ChannelDeliveryChart({ fromDate, toDate }) {
  const url = `/api/analytics/charts/delivery-rates` +
    `?${fromDate ? `from_date=${fromDate}&` : ''}${toDate ? `to_date=${toDate}` : ''}`
  const { data, loading, error, reload } = useChartData(url)

  const ringColor = (rate) => rate >= 95 ? '#059669' : rate >= 80 ? '#D97706' : '#EF4444'

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title"><Wifi size={14} color={PURPLE} /> Channel Delivery</span>
        <button className="btn-export-small" onClick={() => {
          const chs = ['email', 'sms', 'push', 'mobile_push', 'inapp']
          exportRows(chs.map(k => ({ channel: k, ...(data?.[k] || { sent: 0, failed: 0, rate_percent: 0 }) })), 'channel-delivery.csv')
        }}>↓ CSV</button>
      </div>
      {loading ? <Skeleton /> : error ? <ChartError onRetry={reload} /> :
       data?.available === false ? (
         <div className="chart-empty" style={{ height: 180 }}>
           <WifiOff size={24} />
           <span>No delivery data available</span>
         </div>
       ) : (
        <div className="delivery-rings" style={{ minHeight: 180 }}>
          {[
            { key: 'email',        label: 'Email'       },
            { key: 'sms',          label: 'SMS'         },
            { key: 'push',         label: 'Web Push'    },
            { key: 'mobile_push',  label: 'Mobile Push' },
            { key: 'inapp',        label: 'In-App'      },
          ].map(({ key, label }) => {
            const d = data?.[key] || { sent: 0, failed: 0, rate_percent: 0 }
            return (
              <DeliveryRing
                key={key}
                label={label}
                sent={d.sent}
                failed={d.failed}
                rate={d.rate_percent}
                color={ringColor(d.rate_percent)}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart 10 — Summary Stats
// ─────────────────────────────────────────────────────────────────────────────
function SummaryStats({ source, parameter, fromDate, toDate }) {
  const url = `/api/analytics/charts/summary-stats?parameter=${parameter}&source=${source}` +
    (fromDate ? `&from_date=${fromDate}` : '') + (toDate ? `&to_date=${toDate}` : '')
  const { data, loading, error, reload } = useChartData(url)
  const stats = (data || [])[0]
  const unit = stats?.unit || ''

  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <span className="chart-card-title"><BarChart2 size={14} color={PURPLE} /> Summary — {parameter}</span>
        <button className="btn-export-small" onClick={() => exportRows(data || [], `summary-${parameter}.csv`)}>↓ CSV</button>
      </div>
      {loading ? <Skeleton h={100} /> : error ? <ChartError h={100} onRetry={reload} /> :
       !stats ? <Empty h={100} /> : (
        <div className="summary-stats-grid">
          <div className="stat-card">
            <div className="stat-card-label">Average</div>
            <div className="stat-card-value">{stats.avg}</div>
            <div className="stat-card-unit">{unit}</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-label">Min</div>
            <div className="stat-card-value" style={{ color: TEAL }}>{stats.min}</div>
            <div className="stat-card-unit">{unit}</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-label">Max</div>
            <div className="stat-card-value" style={{ color: CORAL }}>{stats.max}</div>
            <div className="stat-card-unit">{unit}</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-label">Std Dev</div>
            <div className="stat-card-value">{stats.std_dev}</div>
            <div className="stat-card-unit">{unit}</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-label">Readings</div>
            <div className="stat-card-value">{stats.reading_count.toLocaleString()}</div>
            <div className="stat-card-unit">samples</div>
          </div>
          <div className="stat-card stat-card-breach">
            <div className="stat-card-label">Breaches</div>
            <div className="stat-card-value">{stats.breach_count}</div>
            <div className="stat-card-unit">alerts</div>
          </div>
          <div className="stat-card stat-card-above">
            <div className="stat-card-label">Above Threshold</div>
            <div className="stat-card-value">{stats.time_above_threshold_percent}</div>
            <div className="stat-card-unit">% of time</div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// CSV Import Panel
// ─────────────────────────────────────────────────────────────────────────────
function CsvImportPanel({ onImported }) {
  const [status,    setStatus]    = useState(null)
  const [uploading, setUploading] = useState(false)
  const [dragOver,  setDragOver]  = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    apiFetch('/api/analytics/csv/status')
      .then(s => { if (s.row_count > 0) setStatus(s) })
      .catch(() => {})
  }, [])

  const doUpload = async (file) => {
    if (!file) return
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await fetch('/api/analytics/csv/import', {
        method: 'POST',
        headers: adminHeaders(),
        body: form,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const result = await res.json()
      const fresh = await apiFetch('/api/analytics/csv/status')
      setStatus(fresh)
      onImported?.()
      alert(`Imported ${result.imported} rows. Skipped: ${result.skipped}.`)
    } catch (e) {
      alert(`Upload failed: ${e.message}`)
    } finally {
      setUploading(false)
    }
  }

  const onFile = (e) => doUpload(e.target.files?.[0])

  const onDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    doUpload(e.dataTransfer.files?.[0])
  }

  const clearCsv = async () => {
    if (!confirm('Delete all imported CSV data?')) return
    await fetch('/api/analytics/csv/clear', { method: 'DELETE', headers: adminHeaders() })
    setStatus(null)
    onImported?.()
  }

  if (status?.row_count > 0) {
    return (
      <div className="csv-import-panel">
        <div className="csv-status-bar">
          <CheckCircle size={16} color="#059669" />
          <span><strong>{status.row_count.toLocaleString()}</strong> rows imported</span>
          {status.earliest_date && <span>· Earliest: <strong>{status.earliest_date?.slice(0,10)}</strong></span>}
          {status.latest_date   && <span>· Latest: <strong>{status.latest_date?.slice(0,10)}</strong></span>}
          <button className="csv-clear-link" onClick={clearCsv}>Clear CSV data</button>
        </div>
      </div>
    )
  }

  return (
    <div
      className={`csv-import-panel ${dragOver ? 'dragging' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
    >
      <Upload size={28} className="csv-drop-icon" />
      <div className="csv-drop-text">Drop CSV file here or click to browse</div>
      <div className="csv-drop-sub">
        Columns detected automatically. Needs a datetime column + temp / pressure.
      </div>
      {uploading ? (
        <div className="csv-progress"><div className="csv-progress-bar" /></div>
      ) : (
        <>
          <button className="csv-btn" onClick={() => inputRef.current?.click()}>
            Choose file
          </button>
          <input ref={inputRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={onFile} />
        </>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────
const DEFAULT_PARAMS = [
  { value: 'temperature', label: 'Temperature', unit: '°C' },
]
const RANGES = [
  { value: '1d',     label: 'Last 24h' },
  { value: '7d',     label: '7 Days'   },
  { value: '30d',    label: '30 Days'  },
  { value: 'custom', label: 'Custom'   },
]

function rangeToDates(range) {
  const today = new Date()
  const fmt   = (d) => d.toISOString().slice(0, 10)
  if (range === '1d')  return { from: fmt(new Date(today - 86400000)), to: fmt(today) }
  if (range === '7d')  return { from: fmt(new Date(today - 7  * 86400000)), to: fmt(today) }
  if (range === '30d') return { from: fmt(new Date(today - 30 * 86400000)), to: fmt(today) }
  return null
}

export default function AnalyticsPage({ wsData }) {
  const [source,      setSource]      = useState('live')
  const [parameter,   setParameter]   = useState('temperature')
  const [range,       setRange]       = useState('7d')
  const [customFrom,  setCustomFrom]  = useState('')
  const [customTo,    setCustomTo]    = useState('')
  const [csvRefresh,  setCsvRefresh]  = useState(0)
  const [showCsvPanel,  setShowCsvPanel]  = useState(false)
  const [predictions,   setPredictions]   = useState([])
  const [paramList,     setParamList]     = useState(DEFAULT_PARAMS)

  // Load approved company parameters and merge with defaults
  useEffect(() => {
    fetchCompanyParams().then(rows => {
      const extras = rows.map(p => ({
        value: p.name.toLowerCase(),
        label: p.name.charAt(0).toUpperCase() + p.name.slice(1),
        unit:  p.unit || '',
      }))
      const existing = new Set(DEFAULT_PARAMS.map(p => p.value))
      const merged = [
        ...DEFAULT_PARAMS,
        ...extras.filter(p => !existing.has(p.value)),
      ]
      setParamList(merged)
    })
  }, [])

  const dates = range === 'custom'
    ? { from: customFrom, to: customTo }
    : (rangeToDates(range) || {})

  const fromDate = dates.from || ''
  const toDate   = dates.to   || ''

  // Show CSV import panel when source includes csv and no data yet
  useEffect(() => {
    if (source === 'csv' || source === 'both') {
      setShowCsvPanel(true)
    } else {
      setShowCsvPanel(false)
    }
  }, [source])

  // Predictions — always use live source; refresh every 5 min
  useEffect(() => {
    const fetchPredictions = async () => {
      try {
        const data = await apiFetch(
          `/api/analytics/charts/predictions?parameter=${parameter}&source=live`
        )
        setPredictions(Array.isArray(data) ? data : [])
      } catch { setPredictions([]) }
    }
    fetchPredictions()
    const t = setInterval(fetchPredictions, 300_000)
    return () => clearInterval(t)
  }, [parameter])

  const exportCsv = async () => {
    const url = `/api/analytics/charts/daily-avg?parameter=${parameter}&source=${source}` +
      (fromDate ? `&from_date=${fromDate}` : '') + (toDate ? `&to_date=${toDate}` : '')
    try {
      const data = await apiFetch(url)
      const header = Object.keys(data[0] || {}).join(',')
      const rows   = data.map(r => Object.values(r).join(',')).join('\n')
      const blob   = new Blob([header + '\n' + rows], { type: 'text/csv' })
      const a      = document.createElement('a')
      a.href       = URL.createObjectURL(blob)
      a.download   = `analytics_${parameter}_${fromDate || 'all'}.csv`
      a.click()
    } catch { /* silent */ }
  }

  return (
    <div className="analytics-page">
      {/* ── Top bar ── */}
      <div className="analytics-topbar">
        <div className="analytics-title-block">
          <div className="analytics-title">
            <TrendingUp size={18} color={PURPLE} />
            Analytics
          </div>
          <div className="analytics-subtitle">Sensor data insights</div>
        </div>

        <div className="analytics-controls">
          {/* Source toggle */}
          <div className="toggle-group">
            {['live', 'csv', 'both'].map(s => (
              <button key={s} className={source === s ? 'active' : ''} onClick={() => setSource(s)}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>

          {/* Parameter */}
          <select className="analytics-select" value={parameter} onChange={e => setParameter(e.target.value)}>
            {paramList.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>

          {/* Date range */}
          <div className="toggle-group">
            {RANGES.map(r => (
              <button key={r.value} className={range === r.value ? 'active' : ''} onClick={() => setRange(r.value)}>
                {r.label}
              </button>
            ))}
          </div>

          {/* Custom date inputs */}
          {range === 'custom' && (
            <>
              <input type="date" className="date-input" value={customFrom}
                onChange={e => setCustomFrom(e.target.value)} />
              <input type="date" className="date-input" value={customTo}
                onChange={e => setCustomTo(e.target.value)} />
            </>
          )}

          <button className="btn-export" onClick={exportCsv}>
            <Download size={13} /> Export CSV
          </button>
        </div>
      </div>

      {/* ── 1. CSV import panel ── */}
      {showCsvPanel && (
        <CsvImportPanel onImported={() => setCsvRefresh(n => n + 1)} />
      )}

      {/* ── Predictions (live feed, auto-refresh 5 min) ── */}
      {predictions.length > 0 && (
        <div className="predictions-section">
          <div className="predictions-header">
            <AlertCircle size={16} />
            Breach Predictions
          </div>
          <div className="predictions-cards">
            {predictions.map((p, i) => (
              <div
                key={i}
                className={`prediction-card ${p.hours_to_breach < 1 ? 'prediction-urgent' : 'prediction-warning'}`}
              >
                <div className="prediction-param">
                  {p.parameter.charAt(0).toUpperCase() + p.parameter.slice(1)}
                  {p.unit && <span className="prediction-unit"> ({p.unit})</span>}
                </div>
                <div className="prediction-row">
                  <span className="prediction-label">Current</span>
                  <strong>{p.current_value}{p.unit}</strong>
                </div>
                <div className="prediction-row">
                  <span className="prediction-label">Threshold ({p.direction})</span>
                  <strong>{p.threshold}{p.unit}</strong>
                </div>
                <div className="prediction-time">
                  {p.hours_to_breach < 1
                    ? `Breach in ~${Math.round(p.hours_to_breach * 60)} min`
                    : `Breach in ~${p.hours_to_breach}h`}
                </div>
                <div className="prediction-confidence">
                  Confidence: {p.confidence_pct}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 2. Live Trend (full width) ── */}
      <LiveTrendChart
        source={source} parameter={parameter} fromDate={fromDate} toDate={toDate} wsData={wsData}
        unit={(paramList.find(p => p.value === parameter) || {}).unit || ''}
      />

      {/* ── 3. Daily Avg + Hourly Avg ── */}
      <div className="analytics-row">
        <DailyAvgChart  source={source} parameter={parameter} fromDate={fromDate} toDate={toDate} />
        <HourlyAvgChart source={source} parameter={parameter} fromDate={fromDate} toDate={toDate} />
      </div>

      {/* ── 4. Weekly Avg + Distribution ── */}
      <div className="analytics-row">
        <WeeklyAvgChart    source={source} parameter={parameter} fromDate={fromDate} toDate={toDate} />
        <DistributionChart source={source} parameter={parameter} fromDate={fromDate} toDate={toDate} />
      </div>

      {/* ── 5. Breach Frequency (full width) ── */}
      <BreachFrequencyChart fromDate={fromDate} toDate={toDate} />

      {/* ── 6. Alert Heatmap (full width) ── */}
      <AlertHeatmap fromDate={fromDate} toDate={toDate} />

      {/* ── 7. Subscriber Response + Channel Delivery ── */}
      <div className="analytics-row">
        <SubscriberResponseTable fromDate={fromDate} toDate={toDate} />
        <ChannelDeliveryChart    fromDate={fromDate} toDate={toDate} />
      </div>

      {/* ── 8. Summary Stats (full width) ── */}
      <SummaryStats source={source} parameter={parameter} fromDate={fromDate} toDate={toDate} />
    </div>
  )
}
