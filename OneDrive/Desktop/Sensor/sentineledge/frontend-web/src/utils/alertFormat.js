/** Format an alert's value/threshold with the right unit for its parameter. */
export function fmtAlertNumber(parameter, v) {
  if (v == null || isNaN(Number(v))) return '—'
  const isTemp = String(parameter ?? 'temperature').toLowerCase() === 'temperature'
  return `${Number(v).toFixed(isTemp ? 1 : 2)}${isTemp ? '°C' : ''}`
}
