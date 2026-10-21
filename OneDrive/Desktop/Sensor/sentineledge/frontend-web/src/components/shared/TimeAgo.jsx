/** src/components/shared/TimeAgo.jsx — "12s ago" that counts up live. */
import useNow from '../../hooks/useNow.js'
import { timeAgo } from '../../utils/time.js'

export default function TimeAgo({ ts }) {
  useNow()                       // re-render every second
  return <>{timeAgo(ts)}</>
}
