// ─────────────────────────────────────────────
//  SentinelEdge — the company's parameters, as told by the server
//  Every screen builds itself from this list, so a company with only pH, one with temperature and
//  pressure, and one with five parameters all get their own screens from the same app.
// ─────────────────────────────────────────────
import { getAppConfig } from './api';

let cache = null; // { company, user, parameters:[{name,unit,min,max,alerts_enabled}] }

export const loadAppConfig = async () => {
  cache = await getAppConfig();
  return cache;
};

export const getCachedConfig = () => cache;
export const clearAppConfig = () => { cache = null; };

const key = (n) => String(n || '').toLowerCase();

/** The unit of a parameter (e.g. "C", "pH", "bar") or "" if unknown. */
export const unitFor = (name) => {
  const p = cache && cache.parameters.find((x) => key(x.name) === key(name));
  return p ? p.unit || '' : '';
};

/** { label, color } of a value against the parameter's own limits. */
export const statusFor = (param, value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return { label: 'NO DATA', color: '#6B7280' };
  }
  const v = Number(value);
  if (param.max !== null && param.max !== undefined && v > param.max) return { label: 'HIGH', color: '#EF4444' };
  if (param.min !== null && param.min !== undefined && v < param.min) return { label: 'LOW', color: '#F59E0B' };
  return { label: 'NORMAL', color: '#10B981' };
};

/** "42.5" / "7.31" — enough digits to read, no more. */
export const formatValue = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  const v = Number(value);
  return Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(2);
};
