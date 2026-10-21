// ─────────────────────────────────────────────
//  SentinelEdge — WebSocket Hook
//  Auto-reconnect, exponential backoff, heartbeat,
//  AppState awareness
// ─────────────────────────────────────────────
import { useState, useEffect, useRef, useCallback } from 'react';
import { AppState } from 'react-native';
import { wsUrl } from '../config/config';
import { getSession } from '../services/auth';

const HEARTBEAT_INTERVAL = 30000;   // 30 seconds
const INITIAL_BACKOFF = 3000;       // 3 seconds
const MAX_BACKOFF = 30000;          // 30 seconds

export const useWebSocket = () => {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState(null);
  const [values, setValues] = useState({});      // latest live value per parameter: { ph: { value, timestamp } }
  const [alerts, setAlerts] = useState([]);       // alerts pushed live by the server (newest first)

  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const heartbeatTimerRef = useRef(null);
  const backoffRef = useRef(INITIAL_BACKOFF);
  const appStateRef = useRef(AppState.currentState);
  const isMountedRef = useRef(true);
  const manuallyDisconnectedRef = useRef(false);

  // ── Clear all timers ─────────────────────────
  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  }, []);

  // ── Send heartbeat ping ──────────────────────
  const startHeartbeat = useCallback(() => {
    clearInterval(heartbeatTimerRef.current);
    heartbeatTimerRef.current = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, HEARTBEAT_INTERVAL);
  }, []);

  // ── Handle incoming messages ─────────────────
  const handleMessage = useCallback((event) => {
    try {
      const data = JSON.parse(event.data);
      setLastMessage(data);

      if (data.type === 'pong' || data.type === 'heartbeat' || data.type === 'connected') return;

      // A live reading carries every parameter this company measures (temperature and/or extra_params)
      const got = {};
      if (data.temperature !== null && data.temperature !== undefined) got.temperature = Number(data.temperature);
      if (data.extra_params && typeof data.extra_params === 'object') {
        Object.entries(data.extra_params).forEach(([k, v]) => {
          if (v !== null && v !== undefined && !Number.isNaN(Number(v))) got[String(k).toLowerCase()] = Number(v);
        });
      }
      const stamp = data.timestamp || new Date().toISOString();
      if (Object.keys(got).length && data.is_valid !== false) {
        setValues((prev) => {
          const next = { ...prev };
          Object.entries(got).forEach(([k, v]) => { next[k] = { value: v, timestamp: stamp }; });
          return next;
        });
      }

      // Limits crossed: the server sends each breach with its alert number
      if (Array.isArray(data.breaches) && data.breaches.length) {
        const fresh = data.breaches
          .filter((b) => b && b.alert_id !== null && b.alert_id !== undefined)
          .map((b) => ({
            id: b.alert_id,
            parameter: b.parameter,
            value: b.value,
            threshold: b.threshold,
            direction: b.direction,
            severity: b.severity,
            timestamp: stamp,
            test: data.type === 'test_alert',
          }));
        if (fresh.length) {
          setAlerts((prev) => [...fresh.filter((f) => !prev.some((p) => p.id === f.id)), ...prev]);
        }
      }
    } catch (err) {
      console.warn('[WS] Failed to parse message:', err);
    }
  }, []);

  // ── Connect to WebSocket server ──────────────
  const connect = useCallback(() => {
    if (!isMountedRef.current || manuallyDisconnectedRef.current) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    getSession().then(({ token }) => {
      if (!isMountedRef.current || manuallyDisconnectedRef.current) return;
      const url = wsUrl(token);
      if (!token || !url) return;          // not signed in / no server yet
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;
      console.log(`[WS] Connecting (backoff=${backoffRef.current}ms)`);
      openSocket(url);
    });
  }, [handleMessage, startHeartbeat]);

  const openSocket = useCallback((url) => {
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!isMountedRef.current) return;
      console.log('[WS] Connected');
      setConnected(true);
      backoffRef.current = INITIAL_BACKOFF; // reset on success
      startHeartbeat();
    };

    ws.onmessage = handleMessage;

    ws.onerror = (error) => {
      console.warn('[WS] Error:', error.message);
    };

    ws.onclose = (event) => {
      if (!isMountedRef.current) return;
      console.log(`[WS] Closed (code=${event.code})`);
      setConnected(false);
      clearInterval(heartbeatTimerRef.current);

      if (!manuallyDisconnectedRef.current) {
        // Schedule reconnect with exponential backoff
        const delay = backoffRef.current;
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF);
        console.log(`[WS] Reconnecting in ${delay}ms`);
        reconnectTimerRef.current = setTimeout(() => {
          if (isMountedRef.current && !manuallyDisconnectedRef.current) {
            connect();
          }
        }, delay);
      }
    };
  }, [handleMessage, startHeartbeat]);

  // ── Disconnect cleanly ───────────────────────
  const disconnect = useCallback(() => {
    manuallyDisconnectedRef.current = true;
    clearTimers();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
  }, [clearTimers]);

  // ── AppState listener ────────────────────────
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      const prev = appStateRef.current;
      appStateRef.current = nextState;

      if (prev === 'active' && nextState.match(/inactive|background/)) {
        // Going to background — disconnect
        console.log('[WS] App moved to background — disconnecting');
        manuallyDisconnectedRef.current = true;
        clearTimers();
        if (wsRef.current) {
          wsRef.current.close();
          wsRef.current = null;
        }
        setConnected(false);
      } else if (prev.match(/inactive|background/) && nextState === 'active') {
        // Returning to foreground — reconnect
        console.log('[WS] App returned to foreground — reconnecting');
        manuallyDisconnectedRef.current = false;
        backoffRef.current = INITIAL_BACKOFF;
        connect();
      }
    });

    return () => subscription.remove();
  }, [connect, clearTimers]);

  // ── Initial connection ───────────────────────
  useEffect(() => {
    isMountedRef.current = true;
    manuallyDisconnectedRef.current = false;
    connect();

    return () => {
      isMountedRef.current = false;
      clearTimers();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect, clearTimers]);

  return { connected, lastMessage, values, alerts };
};
