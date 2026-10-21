/**
 * src/components/dashboard/MiniAlertLog.jsx
 * Compact alert list — used on the Dashboard overview page.
 */
import { useState, useEffect, useCallback } from 'react'
import { CheckCircle } from 'lucide-react'
import { fetchAlerts, acknowledgeAlert } from '../../services/api.js'
import { getSeverityColor, getSeverityLabel, getDirectionLabel } from '../../utils/severity.js'
import { timeAgo, utcToIST } from '../../utils/time.js'
import Badge from '../shared/Badge.jsx'
import TimeAgo from '../shared/TimeAgo.jsx'

const SEV_BADGE = { WARNING:'amber', CRITICAL:'orange', EMERGENCY:'red' }

export default function MiniAlertLog({ limit = 5, onCountChange }) {
  const [alerts, setAlerts] = useState([])

  const load = useCallback(async () => {
    try {
      const data = await fetchAlerts(limit)
      setAlerts(data)
      onCountChange?.(data.filter(a => !a.acknowledged).length)
    } catch { /* silent */ }
  }, [limit, onCountChange])

  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [load])

  const handleAck = async (alert) => {
    try {
      await acknowledgeAlert(alert.id)        // recorded under your own sign-in name
      load()
    } catch { /* silent */ }
  }

  if (alerts.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-6 text-gray-400">
        <CheckCircle size={24} className="text-emerald-400" />
        <p className="text-sm text-gray-500">No recent alerts</p>
      </div>
    )
  }

  return (
    <div className="divide-y divide-gray-100">
      {alerts.map(alert => {
        const sc = getSeverityColor(alert.severity)
        return (
          <div key={alert.id} className="flex items-center gap-3 py-3">
            <span className="status-dot flex-shrink-0" style={{ background: sc.dot }} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-gray-800">
                  {alert.value?.toFixed(1)}°C
                </span>
                <Badge color={SEV_BADGE[alert.severity?.toUpperCase()] || 'gray'}
                       label={getSeverityLabel(alert.severity)} small />
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                {getDirectionLabel(alert.direction)} · <TimeAgo ts={alert.timestamp} />
              </p>
            </div>
            {!alert.acknowledged ? (
              <button onClick={() => handleAck(alert)} className="btn btn-ghost btn-xs flex-shrink-0">
                Seen
              </button>
            ) : (
              <span className="text-xs text-emerald-600 flex-shrink-0">✓ Seen</span>
            )}
          </div>
        )
      })}
    </div>
  )
}
