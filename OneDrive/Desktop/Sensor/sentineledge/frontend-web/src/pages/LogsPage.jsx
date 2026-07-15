/**
 * src/pages/LogsPage.jsx — Live terminal log viewer
 */
import { useState, useEffect, useRef } from 'react'
import { Terminal, Pause, Play, Trash2, Download, Search, Wifi, WifiOff } from 'lucide-react'
import useLogStream from '../hooks/useLogStream.js'

function getLogClass(line) {
  const up = line.toUpperCase()
  if (up.includes('CRITICAL')) return 'log-critical'
  if (up.includes('ERROR'))    return 'log-error'
  if (up.includes('WARNING') || up.includes('WARN')) return 'log-warning'
  if (up.includes('DEBUG'))   return 'log-debug'
  return 'log-info'
}

function getLogLevel(line) {
  const up = line.toUpperCase()
  if (up.includes('CRITICAL')) return 'CRITICAL'
  if (up.includes('ERROR'))    return 'ERROR'
  if (up.includes('WARNING') || up.includes('WARN')) return 'WARNING'
  if (up.includes('DEBUG'))   return 'DEBUG'
  return 'INFO'
}

export default function LogsPage() {
  const {
    lines, rawLines, isConnected, isPaused,
    filter, levelFilter, setFilter, setLevelFilter,
    togglePause, clearLines,
  } = useLogStream()

  const scrollRef     = useRef(null)
  const autoScroll    = useRef(true)
  const [newCount, setNewCount] = useState(0)

  // Auto-scroll when not paused and new lines arrive
  useEffect(() => {
    if (!isPaused && autoScroll.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
    if (isPaused) setNewCount(c => c + 1)
    else setNewCount(0)
  }, [lines, isPaused])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    autoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 50
  }

  const handleDownload = () => {
    const blob = new Blob([rawLines.join('\n')], { type: 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `sentineledge-logs-${new Date().toISOString().slice(0,10)}.txt`
    a.click()
  }

  const LEVELS = ['all', 'INFO', 'DEBUG', 'WARNING', 'ERROR', 'CRITICAL']

  return (
    <div className="flex flex-col h-full" style={{ height: 'calc(100vh - 64px - 48px)' }}>
      {/* Control bar */}
      <div className="card mb-4 px-4 py-3 flex flex-col gap-3">
        {/* Row 1: Live Logs label + status + filter — always horizontal */}
        <div className="flex flex-row items-center gap-4">
          {/* Label */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <Terminal size={16} className="text-purple-600" />
            <span className="text-sm font-semibold text-gray-800">Live Logs</span>
          </div>

          {/* Connection status */}
          <div className="flex-shrink-0">
            {isConnected
              ? <span className="flex items-center gap-1 text-xs text-emerald-600"><Wifi size={12} /> Connected</span>
              : <span className="flex items-center gap-1 text-xs text-red-500"><WifiOff size={12} /> Disconnected</span>
            }
          </div>

          {/* Keyword filter */}
          <div className="relative flex items-center flex-1 min-w-[160px]">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            <input
              className="form-input py-1.5 text-xs w-full"
              style={{ paddingLeft: '2rem' }}
              placeholder="Filter logs…"
              value={filter}
              onChange={e => setFilter(e.target.value)}
            />
          </div>
        </div>

        {/* Row 2: level filter + action buttons */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Level filter */}
          <div className="flex gap-1">
            {LEVELS.map(l => (
              <button
                key={l}
                onClick={() => setLevelFilter(l)}
                className={`px-2 py-1 rounded text-xs font-medium transition-all ${
                  levelFilter === l
                    ? 'bg-purple-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {l}
              </button>
            ))}
          </div>

          <div className="flex gap-2 ml-auto">
            <button onClick={togglePause} className="btn btn-ghost btn-sm">
              {isPaused ? <><Play size={13} /> Resume {newCount > 0 && <span className="ml-1 text-amber-600">+{newCount}</span>}</> : <><Pause size={13} /> Pause</>}
            </button>
            <button onClick={clearLines} className="btn btn-ghost btn-sm"><Trash2 size={13} /> Clear</button>
            <button onClick={handleDownload} className="btn btn-ghost btn-sm"><Download size={13} /> Download</button>
          </div>
        </div>
      </div>

      {/* Terminal */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="terminal-bg flex-1 rounded-xl p-4 overflow-y-auto"
        style={{ minHeight: 0 }}
      >
        {lines.length === 0 ? (
          <p className="log-info opacity-50">Waiting for log output… {isConnected ? 'Connected.' : 'Connecting…'}</p>
        ) : (
          lines.map((line, i) => (
            <div key={i} className={`${getLogClass(line)} leading-relaxed whitespace-pre-wrap break-all`}>
              {line}
            </div>
          ))
        )}
      </div>

      <div className="flex items-center justify-between mt-2 text-xs text-gray-400 px-1">
        <span>{lines.length} lines shown</span>
        <span>{isPaused ? '⏸ Paused' : '▶ Live'}</span>
      </div>
    </div>
  )
}
