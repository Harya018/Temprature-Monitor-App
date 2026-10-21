// ─────────────────────────────────────────────
//  SentinelEdge — Axios API Service
//  Talks to the server the person typed in (see config/config.js) with the token of whoever is
//  signed in. Everything returned is already limited to that person's company.
// ─────────────────────────────────────────────
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { apiBase } from '../config/config';

const apiClient = axios.create({
  timeout: 8000,
  headers: { 'Content-Type': 'application/json' },
});

// ─── Request interceptor — server address + the right token header ───
apiClient.interceptors.request.use(
  async (config) => {
    config.baseURL = apiBase();
    try {
      const pairs = await AsyncStorage.multiGet(['@sentineledge_token', '@sentineledge_kind']);
      const token = pairs[0][1];
      const kind = pairs[1][1] || 'subscriber';
      if (token) {
        if (kind === 'admin') config.headers.Authorization = `Bearer ${token}`;
        else config.headers['X-Auth-Token'] = token;
      }
    } catch (error) {
      console.warn('Failed to read auth token from storage:', error);
    }
    return config;
  },
  (error) => Promise.reject(error)
);

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      console.error(`API Error [${error.response.status}]:`, error.response.data);
    } else if (error.request) {
      console.error('API Error: No response received');
    } else {
      console.error('API Error:', error.message);
    }
    return Promise.reject(error);
  }
);

const isAdmin = async () => (await AsyncStorage.getItem('@sentineledge_kind')) === 'admin';

/** GET /health — server health check (no sign-in needed) */
export const checkHealth = async () => (await apiClient.get('/health')).data;

/** GET /app/config — the company's name and ITS parameters (name, unit, min, max) */
export const getAppConfig = async () => (await apiClient.get('/app/config')).data;

/** GET /app/latest — latest value of each parameter of this company + open alert count */
export const getLatest = async () => (await apiClient.get('/app/latest')).data;

/** The company's alerts (newest first) */
export const getAlerts = async () => {
  const path = (await isAdmin()) ? '/alerts?limit=100' : '/subscriber/alerts?limit=100';
  return (await apiClient.get(path)).data;
};

/** Acknowledge one alert (the server records who did it) */
export const acknowledgeAlert = async (alertId, workerName) => {
  const path = (await isAdmin()) ? `/alerts/${alertId}/acknowledge` : `/subscriber/alerts/${alertId}/acknowledge`;
  try {
    return (await apiClient.post(path, { acknowledged_by: workerName, timestamp: new Date().toISOString() })).data;
  } catch (e) {
    // 409 = another admin acknowledged it first: not an error, the alert is handled
    if (e?.response?.status === 409) return { already: true, ...(e.response.data || {}) };
    throw e;
  }
};

export default apiClient;
