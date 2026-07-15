/**
 * src/pages/SubscriberProfilesPage.jsx
 *
 * List view of all subscribers with their profile fields.
 * Clicking a subscriber NAME navigates to /subscribers/profiles/:id
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Users2, RefreshCw } from 'lucide-react'
import { fetchSubscribers } from '../services/api.js'

// ── Helpers ───────────────────────────────────────────────────────────────────
// Returns value if truthy, otherwise a dim dash placeholder
const val = (v) => v || null
const dash = (v) => v || '—'

// ── Loading spinner ───────────────────────────────────────────────────────────
function Spinner() {
  return (
    <div className="flex items-center justify-center h-48">
      <div className="w-8 h-8 border-4 border-violet-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

// ── Table cell: renders value in dark color, or dim dash for empty ─────────────
function Cell({ value, className = '', mono = false }) {
  const isEmpty = !value
  return (
    <span
      className={`${mono ? 'font-mono text-xs' : ''} ${className}`}
      style={{ color: isEmpty ? '#9CA3AF' : '#111827' }}
    >
      {isEmpty ? '—' : value}
    </span>
  )
}

// ── Main ─────────────────────────────────────────────────────────────────────
export default function SubscriberProfilesPage() {
  const navigate = useNavigate()
  const [subs,    setSubs]    = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [query,   setQuery]   = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchSubscribers()
      setSubs(data)
    } catch (e) {
      setError('Failed to load subscribers. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Client-side filter by name or employee_id
  const filtered = subs.filter((s) => {
    const q = query.toLowerCase().trim()
    if (!q) return true
    return (
      s.name?.toLowerCase().includes(q) ||
      s.employee_id?.toLowerCase().includes(q)
    )
  })

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center"
            style={{ background: '#7C3AED' }}
          >
            <Users2 size={20} className="text-white" />
          </div>
          <div>
            {/* Section 8: page title */}
            <h1 className="text-xl font-bold" style={{ color: '#111827' }}>Subscriber Profiles</h1>
            {/* Section 9: subtext */}
            <p className="text-xs" style={{ color: '#4B5563' }}>
              {subs.length} registered subscriber{subs.length !== 1 ? 's' : ''}
            </p>
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all hover:bg-white/10"
          style={{ color: '#4B5563' }}
        >
          <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Search bar */}
      <div className="relative">
        <Search
          size={15}
          className="absolute left-3 top-1/2 -translate-y-1/2"
          style={{ color: '#6B7280' }}
        />
        <input
          type="text"
          placeholder="Search by name or employee ID…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full pl-9 pr-4 py-2 rounded-lg text-sm placeholder-gray-400 border border-white/10 focus:outline-none focus:border-violet-500 transition-colors"
          style={{ background: 'rgba(255,255,255,0.05)', color: '#111827' }}
        />
      </div>

      {/* Table card */}
      <div
        className="rounded-2xl border border-white/10 overflow-hidden"
        style={{ background: 'rgba(255,255,255,0.04)' }}
      >
        {loading ? (
          <Spinner />
        ) : error ? (
          <div className="p-8 text-center text-red-400 text-sm">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="p-10 text-center">
            <Users2 size={36} className="mx-auto mb-3" style={{ color: '#6B7280' }} />
            {/* Section 9: empty state text */}
            <p className="text-sm" style={{ color: '#4B5563' }}>
              {query ? 'No subscribers match your search.' : 'No subscribers registered yet.'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                {/* Section 2: table headers — text-gray-700 font-semibold */}
                <tr
                  className="border-b border-white/10 text-xs uppercase tracking-wider font-semibold"
                  style={{ color: '#374151' }}
                >
                  <th className="px-4 py-3 text-left">Employee ID</th>
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-left">Department</th>
                  <th className="px-4 py-3 text-left">Designation</th>
                  <th className="px-4 py-3 text-left">Shift</th>
                  <th className="px-4 py-3 text-left">Mobile</th>
                  <th className="px-4 py-3 text-left">Address</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {filtered.map((s) => (
                  <tr
                    key={s.id}
                    className="transition-colors hover:bg-white/5"
                  >
                    {/* Employee ID — dark text, dim dash for empty */}
                    <td className="px-4 py-3">
                      <Cell value={s.employee_id} mono />
                    </td>

                    {/* Name — clickable, always dark */}
                    <td className="px-4 py-3">
                      <button
                        onClick={() => navigate(`/subscribers/profiles/${s.id}`)}
                        className="font-semibold hover:underline hover:text-violet-700 transition-colors text-left"
                        style={{ color: '#111827' }}
                      >
                        {s.name}
                      </button>
                    </td>

                    {/* Section 3: table body values — text-gray-900 */}
                    <td className="px-4 py-3">
                      <Cell value={s.department} />
                    </td>
                    <td className="px-4 py-3">
                      <Cell value={s.designation} />
                    </td>
                    <td className="px-4 py-3">
                      <Cell value={s.shift_timing} />
                    </td>
                    <td className="px-4 py-3">
                      <Cell value={s.phone} mono />
                    </td>
                    <td className="px-4 py-3 max-w-xs truncate" title={s.address || ''}>
                      <Cell value={s.address} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Footer count — Section 9: helper text min text-gray-600 */}
      {!loading && !error && filtered.length > 0 && (
        <p className="text-xs text-right" style={{ color: '#4B5563' }}>
          Showing {filtered.length} of {subs.length} subscriber{subs.length !== 1 ? 's' : ''}
        </p>
      )}
    </div>
  )
}
