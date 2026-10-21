// ─────────────────────────────────────────────
//  SentinelEdge — Dashboard Screen
//  One card per parameter THIS company measures (the server says which), coloured by that
//  parameter's own limits. Live values arrive over the websocket; the latest stored value is
//  shown straight away when the screen opens.
// ─────────────────────────────────────────────
import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  StatusBar,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';

import { useWebSocket } from '../hooks/useWebSocket';
import ConnectionBanner from '../components/ConnectionBanner';
import AlertOverlay from '../components/AlertOverlay';
import { DashboardSkeleton } from '../components/ScreenSkeleton';
import ErrorState from '../components/ErrorState';
import { getAlerts, getLatest } from '../services/api';
import { loadAppConfig, statusFor, formatValue } from '../services/appConfig';

const STALE_AFTER_S = 10 * 60; // no new value for 10 minutes: say so instead of showing an old figure as live

const ago = (iso, now) => {
  if (!iso) return 'No data yet';
  const secs = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
};

const DashboardScreen = () => {
  const { connected, values: wsValues, alerts: wsAlerts } = useWebSocket();

  const [config, setConfig] = useState(null);           // { company, parameters }
  const [latest, setLatest] = useState({});             // { "pH": { value, timestamp } } from the server
  const [todayAlertCount, setTodayAlertCount] = useState(0);
  const [openAlerts, setOpenAlerts] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [activeAlert, setActiveAlert] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);
  const [now, setNow] = useState(Date.now());

  // tick once a second so "x seconds ago" counts live
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // a new alert from the server opens the overlay
  useEffect(() => {
    if (wsAlerts && wsAlerts.length > 0 && !activeAlert) setActiveAlert(wsAlerts[0]);
  }, [wsAlerts, activeAlert]);

  const fetchData = useCallback(async () => {
    setFetchError(null);
    try {
      const cfg = await loadAppConfig();
      setConfig(cfg);
      const [lat, alertsData] = await Promise.allSettled([getLatest(), getAlerts()]);
      if (lat.status === 'fulfilled' && lat.value) {
        setLatest(lat.value.values || {});
        setOpenAlerts(lat.value.open_alerts || 0);
      }
      if (alertsData.status === 'fulfilled' && Array.isArray(alertsData.value)) {
        const today = new Date().toDateString();
        setTodayAlertCount(alertsData.value.filter((a) => new Date(a.timestamp).toDateString() === today).length);
      }
    } catch (err) {
      console.warn('[Dashboard] Fetch error:', err);
      setFetchError(err.response && err.response.status === 401
        ? 'Your sign-in is no longer valid. Open Settings and sign out, then sign in again.'
        : 'Could not reach the server. Check your connection and the server address.');
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { fetchData(); }, [fetchData]));

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
  };

  // value of a parameter: the newer of the live one and the stored one
  const readingFor = (p) => {
    const k = String(p.name).toLowerCase();
    const live = wsValues[k];
    const stored = Object.entries(latest).find(([n]) => n.toLowerCase() === k);
    const s = stored ? stored[1] : null;
    if (live && (!s || new Date(live.timestamp) >= new Date(s.timestamp))) return live;
    return s;
  };

  if (loading && !config) {
    return (
      <View style={styles.flex}>
        <StatusBar barStyle="light-content" backgroundColor="#0F0C29" />
        <LinearGradient colors={['#111827', '#1F2937', '#374151']} style={styles.flex}>
          <ConnectionBanner connected={connected} />
          <DashboardSkeleton />
        </LinearGradient>
      </View>
    );
  }
  if (fetchError && !config) {
    return (
      <View style={styles.flex}>
        <StatusBar barStyle="light-content" backgroundColor="#0F0C29" />
        <LinearGradient colors={['#111827', '#1F2937', '#374151']} style={styles.flex}>
          <ConnectionBanner connected={connected} />
          <ErrorState message={fetchError} onRetry={fetchData} />
        </LinearGradient>
      </View>
    );
  }

  const params = (config && config.parameters) || [];
  return (
    <View style={styles.flex}>
      <StatusBar barStyle="light-content" backgroundColor="#0F0C29" />
      <AlertOverlay visible={!!activeAlert} alertData={activeAlert} onDismiss={() => setActiveAlert(null)} />

      <LinearGradient colors={['#111827', '#1F2937', '#374151']} style={styles.flex}>
        <ConnectionBanner connected={connected} />
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FFFFFF" />}
        >
          <View style={styles.header}>
            <View style={{ flexShrink: 1 }}>
              <Text style={styles.headerTitle}>{(config && config.company && config.company.name) || 'SentinelEdge'}</Text>
              <Text style={styles.headerSubtitle}>Live monitoring</Text>
            </View>
            <View style={[styles.liveBadge, { backgroundColor: connected ? '#065F46' : '#7F1D1D' }]}>
              <Text style={styles.liveBadgeText}>{connected ? '● LIVE' : '○ OFFLINE'}</Text>
            </View>
          </View>

          {params.length === 0 ? (
            <View style={styles.emptyBox}>
              <Ionicons name="information-circle-outline" size={40} color="#9CA3AF" />
              <Text style={styles.emptyTitle}>No parameters yet</Text>
              <Text style={styles.emptyText}>Your company has no approved parameters. Ask your administrator.</Text>
            </View>
          ) : (
            params.map((p) => {
              const r = readingFor(p);
              const secs = r ? (now - new Date(r.timestamp).getTime()) / 1000 : null;
              const stale = r && secs > STALE_AFTER_S;
              const st = stale ? { label: 'NO RECENT DATA', color: '#6B7280' } : statusFor(p, r ? r.value : null);
              return (
                <View key={p.name} style={[styles.paramCard, { borderLeftColor: st.color }]}>
                  <View style={styles.paramHeader}>
                    <Text style={styles.paramName}>{p.name}</Text>
                    <View style={[styles.statusChip, { backgroundColor: st.color }]}>
                      <Text style={styles.statusChipText}>{st.label}</Text>
                    </View>
                  </View>
                  <View style={styles.valueRow}>
                    <Text style={[styles.paramValue, stale && { opacity: 0.45 }]}>{r ? formatValue(r.value) : '--'}</Text>
                    <Text style={styles.paramUnit}>{p.unit}</Text>
                  </View>
                  <Text style={styles.rangeText}>
                    Allowed range: {p.min !== null && p.min !== undefined ? formatValue(p.min) : '—'} to {p.max !== null && p.max !== undefined ? formatValue(p.max) : '—'} {p.unit}
                    {p.alerts_enabled === false ? '  ·  alerts off' : ''}
                  </Text>
                  <Text style={styles.agoText}>{r ? `Updated ${ago(r.timestamp, now)}` : 'No reading received yet'}</Text>
                </View>
              );
            })
          )}

          <View style={styles.cardsRow}>
            <View style={styles.card}>
              <Ionicons name="warning-outline" size={22} color="#FBBF24" />
              <Text style={styles.cardValue}>{todayAlertCount}</Text>
              <Text style={styles.cardLabel}>Alerts Today</Text>
            </View>
            <View style={styles.card}>
              <Ionicons name="alert-circle-outline" size={22} color={openAlerts ? '#F87171' : '#34D399'} />
              <Text style={[styles.cardValue, { color: openAlerts ? '#F87171' : '#34D399' }]}>{openAlerts}</Text>
              <Text style={styles.cardLabel}>Not Acknowledged</Text>
            </View>
          </View>
        </ScrollView>
      </LinearGradient>
    </View>
  );
};

const styles = StyleSheet.create({
  flex: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 },
  headerTitle: { fontSize: 22, fontWeight: '800', color: '#FFFFFF' },
  headerSubtitle: { fontSize: 12, color: '#9CA3AF', marginTop: 2 },
  liveBadge: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 14 },
  liveBadgeText: { color: '#FFFFFF', fontSize: 11, fontWeight: '700' },
  paramCard: {
    backgroundColor: 'rgba(255,255,255,0.07)', borderRadius: 16, padding: 16, marginBottom: 14, borderLeftWidth: 5,
  },
  paramHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  paramName: { fontSize: 14, fontWeight: '700', color: '#D1D5DB', letterSpacing: 0.5 },
  statusChip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 10 },
  statusChipText: { color: '#FFFFFF', fontSize: 10, fontWeight: '800', letterSpacing: 0.5 },
  valueRow: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 8 },
  paramValue: { fontSize: 46, fontWeight: '800', color: '#FFFFFF' },
  paramUnit: { fontSize: 16, color: '#9CA3AF', marginLeft: 8, marginBottom: 8 },
  rangeText: { fontSize: 12, color: '#9CA3AF', marginTop: 4 },
  agoText: { fontSize: 11, color: '#6B7280', marginTop: 2 },
  cardsRow: { flexDirection: 'row', gap: 12, marginTop: 6 },
  card: { flex: 1, backgroundColor: 'rgba(255,255,255,0.07)', borderRadius: 14, padding: 14, alignItems: 'center' },
  cardValue: { fontSize: 22, fontWeight: '800', color: '#FFFFFF', marginTop: 6 },
  cardLabel: { fontSize: 11, color: '#9CA3AF', marginTop: 2 },
  emptyBox: { alignItems: 'center', padding: 30 },
  emptyTitle: { fontSize: 16, fontWeight: '700', color: '#E5E7EB', marginTop: 10 },
  emptyText: { fontSize: 13, color: '#9CA3AF', textAlign: 'center', marginTop: 4 },
});

export default DashboardScreen;
