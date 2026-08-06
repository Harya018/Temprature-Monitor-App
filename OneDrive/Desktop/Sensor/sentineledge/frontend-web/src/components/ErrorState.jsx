import './ErrorState.css'
import { AlertTriangle, RefreshCw } from 'lucide-react'

export default function ErrorState({ message = 'Something went wrong', onRetry }) {
  return (
    <div className="error-state">
      <AlertTriangle className="error-state-icon" size={32} />
      <p className="error-state-title">Failed to load data</p>
      <p className="error-state-message">{message}</p>
      {onRetry && (
        <button className="error-state-retry" onClick={onRetry}>
          <RefreshCw size={13} />
          Try again
        </button>
      )}
    </div>
  )
}
