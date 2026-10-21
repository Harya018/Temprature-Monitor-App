/**
 * src/components/dashboard/AlertLog.jsx
 * Scrollable alert log with acknowledge, delivery status, severity, IST timestamps.
 */
import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, Mail, MessageSquare, CheckCircle, XCircle, CheckCheck } from 'lucide-react'
import { fetchAlerts, acknowledgeAlert } from '../../services/api.js'
import { getSeverityColor, getDirectionLabel, getSeverityLabel } from '../../utils/severity.js'
import { utcToIST, timeAgo } from '../../utils/time.js'
import Card from '../shared/Card.jsx'
import Badge from '../shared/Badge.jsx'
import TimeAgo from '../shared/TimeAgo.jsx'

function sev2badge(s) {
  const m = { NORMAL:'green', WARNING:'amber', CRITICAL:'orange', EMERGENCY:'red' }
  return m[s?.toUpperCase()] || 'gray'
}

export default function AlertLog({ onCountChange }) {
  const [alerts,   setAlerts]   = useState([])
  const [loading,  setLoading]  = useState(false)
  const [ackMap,   setAckMap]   = useState({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchAlerts(30)
      setAlerts(data)
      const unread = data.filter(a => !a.acknowledged).length
      onCountChange?.(unread)
    } catch { /* silently retry */ }
    finally { setLoading(false) }
  }, [onCountChange])

  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])

  const handleAck = async (alert) => {
    try {
      const r = await acknowledgeAlert(alert.id)     // recorded under your own sign-in name
      const by = r?.acknowledged_by || sessionStorage.getItem('admin_username') || 'admin'
      if (r?.already) window.alert(`Already acknowledged by ${by}`)
      setAlerts(prev =>
        prev.map(a => a.id === alert.id
          ? { ...a, acknowledged: true, acknowledged_by: by }
          : a
        )
      )
      setAckMap(prev => ({ ...prev, [alert.id]: by }))
    } catch (e) {
      window.alert('Failed to acknowledge: ' + e.message)
    }
  }

  const sevBadgeMap = { WARNING:'amber', CRITICAL:'orange', EMERGENCY:'red' }

  const headerRight = (
    <>
      <span className="text-xs font-semibold bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
        {alerts.length} total
      </span>
      <button onClick={load} disabled={loading} className="btn btn-ghost btn-sm">
        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
      </button>
    </>
  )

  return (
    <Card title="Alert History" subtitle="Last 30 events" headerRight={headerRight} noPadding>
      {alerts.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-12 text-gray-400">
          <CheckCircle size={32} className="text-emerald-400" />
          <p className="text-sm font-medium text-gray-500">No alerts today</p>
          <p className="text-xs">System is operating normally</p>
        </div>
      ) : (
        <div className="overflow-auto max-h-96">
          <table className="data-table w-full">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Reading</th>
                <th>Time</th>
                <th>Delivery</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {alerts.slice(0, 30).map(alert => {
                const sc = getSeverityColor(alert.severity)
                const ds = alert.delivery_status || {}
                return (
                  <tr key={alert.id}>
                    {/* Severity */}
                    <td>
                      <div className="flex items-center gap-2">
                        <span className="status-dot flex-shrink-0" style={{ background: sc.dot }} />
                        <Badge color={sev2badge(alert.severity)} label={getSeverityLabel(alert.severity)} small />
                      </div>
                    </td>
                    {/* Reading */}
                    <td>
                      <p className="font-semibold text-gray-800">
                        {alert.value?.toFixed(1)}°C
                        <span className="text-gray-400 font-normal"> / </span>
                        <span className="text-gray-500">{alert.threshold?.toFixed(1)}°C</span>
                      </p>
                      <p className="text-xs text-gray-400">{getDirectionLabel(alert.direction)}</p>
                    </td>
                    {/* Time */}
                    <td>
                      <p className="text-xs text-gray-700"><TimeAgo ts={alert.timestamp} /></p>
                      <p className="text-xs text-gray-400">{utcToIST(alert.timestamp)}</p>
                    </td>
                    {/* Delivery */}
                    <td>
                      <div className="flex items-center gap-2">
                        {ds.email === 'sent'
                          ? <CheckCircle size={13} className="text-emerald-500" title="Email sent" />
                          : <XCircle    size={13} className="text-red-400"     title="Email failed" />
                        }
                        <Mail size={11} className="text-gray-400" />
                        {ds.sms === 'sent'
                          ? <CheckCircle  size={13} className="text-emerald-500" title="SMS sent" />
                          : <XCircle      size={13} className="text-red-400"     title="SMS failed" />
                        }
                        <MessageSquare size={11} className="text-gray-400" />
                      </div>
                    </td>
                    {/* Escalation level — removed */}
                    {/* Acknowledge */}
                    <td>
                      {alert.acknowledged ? (
                        <div className="flex items-center gap-1 text-emerald-600 text-xs">
                          <CheckCheck size={13} />
                          <span className="truncate max-w-[80px]" title={alert.acknowledged_by}>
                            {alert.acknowledged_by || 'Seen'}
                          </span>
                        </div>
                      ) : (
                        <button onClick={() => handleAck(alert)} className="btn btn-ghost btn-xs">
                          Mark as Seen
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
