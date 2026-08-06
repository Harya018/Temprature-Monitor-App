/**
 * dateRangeHelper.js — Shared date-range utilities for analytics views.
 */

/** Convert a preset range string to { from, to } ISO date strings (YYYY-MM-DD). */
export function rangeToDates(range) {
  const to   = new Date()
  const from = new Date(to)
  switch (range) {
    case '7d':  from.setDate(to.getDate() - 7);   break
    case '30d': from.setDate(to.getDate() - 30);  break
    case '90d': from.setDate(to.getDate() - 90);  break
    case '1d':
    default:    from.setDate(to.getDate() - 1);   break
  }
  return { from: toYMD(from), to: toYMD(to) }
}

/** Format a Date as YYYY-MM-DD. */
export function toYMD(date) {
  return date.toISOString().slice(0, 10)
}

/** Build a query-string fragment like "from_date=…&to_date=…". */
export function dateQS(from, to) {
  const parts = []
  if (from) parts.push(`from_date=${from}`)
  if (to)   parts.push(`to_date=${to}`)
  return parts.length ? '?' + parts.join('&') : ''
}

/** Append date params to an existing URL (which may already have '?'). */
export function withDates(url, from, to) {
  const sep = url.includes('?') ? '&' : '?'
  const parts = []
  if (from) parts.push(`from_date=${from}`)
  if (to)   parts.push(`to_date=${to}`)
  return parts.length ? url + sep + parts.join('&') : url
}

export const RANGE_OPTIONS = [
  { value: '1d',  label: 'Last 24 h' },
  { value: '7d',  label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
]
