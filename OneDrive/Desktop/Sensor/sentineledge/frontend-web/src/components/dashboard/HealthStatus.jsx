/**
 * src/components/dashboard/HealthStatus.jsx
 * System health card showing module status and DB stats.
 */
import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, Database, Mail, MessageSquare, Wifi, Thermometer, Server } from 'lucide-react'
import { fetchHealth, fetchDatabaseStats } from '../../services/api.js'
import Card from '../shared/Card.jsx'
import Badge from '../shared/Badge.jsx'

const MODULE_ICONS = {
  sensor:    <Thermometer  size={15} />,
  database:  <Database     size={15} />,
  email:     <Mail         size={15} />,
  sms:       <MessageSquare size={15} />,
  websocket: <Wifi         size={15} />,
}

function statusBadge(s) {
  // Unwrap { status: "..." } objects returned by the new health API
  const str = String((s && typeof s === 'object' ? s.status : s) || '')
  if (!str || str === 'not_built')    return { color:'gray',  label:'Not built' }
  if (str === 'ok')                   return { color:'green', label:'OK' }
  if (str === 'starting')             return { color:'amber', label:'Starting' }
  if (str.startsWith('configured'))   return { color:'green', label:'Configured' }
  if (str.startsWith('ok'))           return { color:'green', label:'OK' }
  if (str.startsWith('error'))        return { color:'red',   label:'Error' }
  return { color:'gray', label: str }
}

export default function HealthStatus() {
  const [health,  setHealth]  = useState(null)
  const [stats,   setStats]   = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [h, s] = await Promise.allSettled([fetchHealth(), fetchDatabaseStats()])
      if (h.status === 'fulfilled') setHealth(h.value)
      if (s.status === 'fulfilled') setStats(s.value)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [load])

  const modules  = health?.modules || {}
  const overall  = health?.status
  const uptime   = health?.uptime_seconds

  function humanUptime(s) {
    if (!s) return '—'
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
    return h > 0 ? `${h}h ${m}m` : `${m}m`
  }

  const overallBadge = overall === 'ok' ? { color:'green', label:'Healthy' }
                     : overall === 'degraded' ? { color:'amber', label:'Degraded' }
                     : { color:'gray', label:'Unknown' }

  return (
    <Card
      title="System Health"
      subtitle="Module status overview"
      headerRight={
        <div className="flex items-center gap-2">
          <Badge color={overallBadge.color} label={overallBadge.label} />
          <button onClick={load} disabled={loading} className="btn btn-ghost btn-sm">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      }
    >
      {/* Modules */}
      <div className="space-y-2 mb-4">
        {['sensor','database','email','sms','websocket'].map(mod => {
          const raw = modules[mod]
          // API returns modules as { status: "ok" } objects — unwrap .status for string ops
          const val = String((raw && typeof raw === 'object' ? raw.status : raw) || 'unknown')
          const sb  = statusBadge(val)
          return (
            <div key={mod} className="flex items-center justify-between py-1.5 px-3 rounded-lg bg-gray-50">
              <div className="flex items-center gap-2.5 text-gray-600">
                {MODULE_ICONS[mod]}
                <span className="text-sm font-medium capitalize">{mod}</span>
              </div>
              <div className="flex items-center gap-2">
                {sb.color === 'red' && (
                  <span className="text-xs text-red-500 max-w-[140px] truncate hidden md:block"
                        title={val}>
                    {val.replace('error: ', '')}
                  </span>
                )}
                <Badge color={sb.color} label={sb.label} small />
              </div>
            </div>
          )
        })}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'DB Size',   value: stats ? `${stats.database_size_mb} MB`   : '—' },
          { label: 'Readings',  value: stats ? `${stats.readings_count}`         : '—' },
          { label: 'Uptime',    value: humanUptime(uptime) },
          { label: 'Version',   value: health?.version || '1.0.0' },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-lg bg-gray-50 px-3 py-2">
            <p className="text-xs text-gray-500">{label}</p>
            <p className="text-sm font-semibold text-gray-800 mt-0.5">{value}</p>
          </div>
        ))}
      </div>
    </Card>
  )
}
