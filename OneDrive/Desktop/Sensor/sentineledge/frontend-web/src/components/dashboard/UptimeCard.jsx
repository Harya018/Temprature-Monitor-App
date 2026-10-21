/** src/components/dashboard/UptimeCard.jsx */
import { Clock } from 'lucide-react'
import DashTile from './DashTile.jsx'
import Badge from '../shared/Badge.jsx'
import { useLiveSeconds } from '../../hooks/useNow.js'

function humanUptime(seconds) {
  if (!seconds && seconds !== 0) return null
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export default function UptimeCard({ uptimeSeconds }) {
  const live  = useLiveSeconds(uptimeSeconds)      // counts every second between health checks
  const known = uptimeSeconds != null
  return (
    <DashTile
      icon={Clock}
      iconColor="#10B981"
      label="Server Uptime"
      badge={<Badge color={known ? 'green' : 'gray'} label={known ? 'RUNNING' : 'UNKNOWN'} />}
      value={humanUptime(live)}
      valueColor="#059669"
      caption={known ? 'Server running normally' : 'Waiting for health check'}
      footerLeft="Since last restart"
      footerRight="Health check"
    />
  )
}
