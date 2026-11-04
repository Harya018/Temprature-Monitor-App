/**
 * src/components/dashboard/UnmatchedValues.jsx
 *
 * "Also arriving": values a live source of this company sends (e.g. the Pro-face collector's humidity)
 * that are not one of the company's parameters. They are not stored or alerted on until the
 * parameter is approved; a main admin can request one here (opens Settings › Add Parameter with
 * the name filled in). Sub-admins only see the list.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PlusCircle } from 'lucide-react'
import { displayParamName } from './SensorCard.jsx'

const SOURCE = { proserver: 'Pro-face collector', live_collector_reading: 'Pro-face collector', excel: 'Excel file', opc: 'OPC', sensor: 'sensor' }

export default function UnmatchedValues({ role }) {
  const [rows, setRows] = useState([])
  const navigate = useNavigate()

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const token = sessionStorage.getItem('admin_token') || ''
        const r = await fetch('/api/admin/incoming-unmatched', { headers: { Authorization: `Bearer ${token}` } })
        if (r.ok && alive) setRows(await r.json())
      } catch { /* try again next round */ }
    }
    load()
    const t = setInterval(load, 30000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  if (!rows.length) return null
  const canRequest = role === 'main'
  return (
    <div className="card px-4 py-3 text-sm flex flex-col gap-2" style={{ borderLeft: '3px solid #7C3AED' }}>
      <p className="font-semibold text-gray-800">Also arriving from your live sources, not on the dashboard yet</p>
      <p className="text-xs text-gray-500">
        These values are not stored or alerted on until they are approved as parameters.
        {canRequest ? ' Request one and the Super Admin approves it.' : ' Ask your main admin to request them.'}
      </p>
      <div className="flex flex-wrap gap-2">
        {rows.map(r => (
          <div key={r.name} className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5">
            <span className="font-medium text-gray-800">{displayParamName(r.name)}</span>
            <span className="text-gray-500" style={{ fontVariantNumeric: 'tabular-nums' }}>{Number(r.value).toFixed(3).replace(/\.?0+$/, '')}</span>
            <span className="text-xs text-gray-400">{SOURCE[r.source] || r.source}</span>
            {r.requested
              ? <span className="text-xs font-semibold text-amber-600">Requested</span>
              : canRequest && (
                <button type="button" className="text-xs font-semibold text-purple-600 hover:text-purple-700 flex items-center gap-1"
                        onClick={() => navigate(`/settings?addParameter=${encodeURIComponent(r.name)}`)}>
                  <PlusCircle size={13} /> Request
                </button>
              )}
          </div>
        ))}
      </div>
    </div>
  )
}
