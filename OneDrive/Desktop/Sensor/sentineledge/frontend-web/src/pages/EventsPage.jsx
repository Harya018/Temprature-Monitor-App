/**
 * src/pages/EventsPage.jsx — Audit trail timeline.
 */
import { useState, useEffect, useCallback } from 'react'
import { ClipboardList, RefreshCw, Download } from 'lucide-react'
import { fetchEvents } from '../services/api.js'
import { utcToIST, timeAgo } from '../utils/time.js'
import { SkeletonTable } from '../components/Skeleton'
import ErrorState from '../components/ErrorState'
import EmptyState from '../components/EmptyState'

const TYPE_CONFIG = {
  config:   { dot: '#7C3AED', icon: '🔵', label: 'Config Change' },
  alert:    { dot: '#F59E0B', icon: '🟡', label: 'Alert Fired' },
  backup:   { dot: '#10B981', icon: '⚪', label: 'Backup Created' },
  delivery: { dot: '#3B82F6', icon: '📨', label: 'Delivery' },
}

export default function EventsPage() {
  const [events,     setEvents]     = useState([])
  const [loading,    setLoading]    = useState(false)
  const [fetchError, setFetchError] = useState(null)
  const [filter,     setFilter]     = useState('all')

  const load = useCallback(async () => {
    setLoading(true)
    setFetchError(null)
    try { setEvents(await fetchEvents(200, filter === 'all' ? 'all' : filter)) }
    catch (err) { setFetchError(err?.message || 'Could not load events') }
    finally { setLoading(false) }
  }, [filter])

  useEffect(() => { load() }, [load])

  const handleExport = () => {
    const csv = ['timestamp,type,description', ...events.map(e =>
      `"${e.timestamp}","${e.type}","${e.description.replace(/"/g, '""')}"`
    )].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `audit-trail-${new Date().toISOString().slice(0,10)}.csv`
    a.click()
  }

  const TYPES = ['all', 'config', 'alert', 'backup']

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ClipboardList size={18} className="text-purple-600" />
          <h1 className="text-base font-bold text-gray-800">Audit Trail</h1>
          <span className="text-xs text-gray-400">({events.length} events)</span>
        </div>
        <div className="flex gap-2">
          <button onClick={handleExport} className="btn btn-ghost btn-sm"><Download size={13} /> Export CSV</button>
          <button onClick={load} disabled={loading} className="btn btn-ghost btn-sm">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Type filter */}
      <div className="flex gap-2">
        {TYPES.map(t => (
          <button
            key={t}
            onClick={() => setFilter(t)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              filter === t
                ? 'bg-purple-600 text-white'
                : 'bg-white border border-gray-200 text-gray-600 hover:border-purple-300'
            }`}
          >
            {t === 'all' ? 'All Events' : TYPE_CONFIG[t]?.icon + ' ' + TYPE_CONFIG[t]?.label}
          </button>
        ))}
      </div>

      {/* Timeline */}
      <div className="card p-5">
        {fetchError && !loading ? (
          <ErrorState message={fetchError} onRetry={load} />
        ) : loading && events.length === 0 ? (
          <SkeletonTable />
        ) : events.length === 0 ? (
          <EmptyState icon={ClipboardList} title="No events recorded yet" />
        ) : (
          <div className="relative">
            {/* Vertical line */}
            <div className="absolute left-6 top-0 bottom-0 w-0.5 bg-gray-100" />

            <div className="space-y-0">
              {events.map((evt, i) => {
                const tc = TYPE_CONFIG[evt.type] || TYPE_CONFIG.delivery
                return (
                  <div key={i} className="flex gap-4 py-3 relative">
                    {/* Dot */}
                    <div
                      className="w-3 h-3 rounded-full flex-shrink-0 mt-1 z-10 ml-[18px] border-2 border-white"
                      style={{ background: tc.dot }}
                    />

                    {/* Content */}
                    <div className="flex-1 min-w-0 ml-1">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-sm font-medium text-gray-800">{evt.description}</p>
                          {evt.details && (
                            <div className="flex gap-3 mt-1 flex-wrap">
                              {Object.entries(evt.details).map(([k, v]) => (
                                v != null && <span key={k} className="text-xs text-gray-400">
                                  <span className="font-medium text-gray-500">{k}:</span> {String(v)}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                        <div className="text-right flex-shrink-0">
                          <p className="text-xs text-gray-400">{timeAgo(evt.timestamp)}</p>
                          <p className="text-xs text-gray-300">{utcToIST(evt.timestamp)}</p>
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
