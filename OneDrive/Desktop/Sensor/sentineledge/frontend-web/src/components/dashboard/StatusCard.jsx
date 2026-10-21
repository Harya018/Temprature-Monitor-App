/** src/components/dashboard/StatusCard.jsx */
import { Wifi, WifiOff } from 'lucide-react'
import DashTile from './DashTile.jsx'
import Badge from '../shared/Badge.jsx'

export default function StatusCard({ isConnected, connectionStatus }) {
  const color   = isConnected ? '#10B981' : '#EF4444'
  const expired = connectionStatus === 'SESSION EXPIRED'

  return (
    <DashTile
      icon={isConnected ? Wifi : WifiOff}
      iconColor={color}
      label="Connection"
      badge={<Badge color={isConnected ? 'green' : 'red'} label={isConnected ? 'ONLINE' : 'OFFLINE'} pulse={!isConnected && !expired} />}
      value={expired ? 'EXPIRED' : (connectionStatus || 'CONNECTING')}
      valueColor={color}
      caption={isConnected ? 'Receiving live readings'
        : expired ? 'Login session expired — log in again'
        : 'Attempting to reconnect…'}
      footerLeft="WebSocket stream"
      footerRight="Real-time"
    />
  )
}
