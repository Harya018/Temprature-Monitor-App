/** src/components/dashboard/AlertsTodayCard.jsx */
import { Bell } from 'lucide-react'
import DashTile from './DashTile.jsx'
import Badge from '../shared/Badge.jsx'

export default function AlertsTodayCard({ count }) {
  const hasAlerts = count > 0
  const color = hasAlerts ? '#F59E0B' : '#10B981'

  return (
    <DashTile
      icon={Bell}
      iconColor={color}
      label="Alerts Today"
      badge={<Badge color={hasAlerts ? 'amber' : 'green'} label={hasAlerts ? 'ACTIVE' : 'ALL CLEAR'} />}
      value={count ?? null}
      valueColor={color}
      caption={hasAlerts ? `${count} alert${count !== 1 ? 's' : ''} fired` : 'No alerts today'}
      footerLeft={hasAlerts ? 'Breach events today' : 'All clear today'}
      footerRight="Today"
    />
  )
}
