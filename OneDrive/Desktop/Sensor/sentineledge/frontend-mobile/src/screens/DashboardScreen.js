// ─────────────────────────────────────────────
//  SentinelEdge — Dashboard Screen
//  Shows live temperature, color-coded status,
//  alert overlay integration, and connection banner
// ─────────────────────────────────────────────
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  StatusBar,
  Animated,
  TouchableOpacity,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';

import { useWebSocket } from '../hooks/useWebSocket';
import ConnectionBanner from '../components/ConnectionBanner';
import AlertOverlay from '../components/AlertOverlay';
import { DashboardSkeleton } from '../components/ScreenSkeleton';
import ErrorState from '../components/ErrorState';
import { getAlerts, getCurrentReading } from '../services/api';

// ── Temperature thresholds ───────────────────
const TEMP_DANGER  = 90;  // > 90°C → RED (DANGER)
const TEMP_NORMAL  = 42;  // 42–90°C → YELLOW (NORMAL)
// < 42°C → GREEN (READY — trigger alert)

const getTempStatus = (temp) => {
  if (temp === null || temp === undefined) return 'UNKNOWN';
  if (temp > TEMP_DANGER) return 'DANGER';
  if (temp >= TEMP_NORMAL) return 'NORMAL';
  return 'READY';
};

const STATUS_CONFIG = {
  DANGER:  { label: 'DANGER',  emoji: '🔴', colors: ['#7F1D1D', '#991B1B', '#B91C1C'], textColor: '#FCA5A5', badge: '#EF4444' },
  NORMAL:  { label: 'NORMAL',  emoji: '🟡', colors: ['#78350F', '#92400E', '#B45309'], textColor: '#FDE68A', badge: '#F59E0B' },
  READY:   { label: 'READY',   emoji: '🟢', colors: ['#064E3B', '#065F46', '#047857'], textColor: '#6EE7B7', badge: '#10B981' },
  UNKNOWN: { label: 'NO DATA', emoji: '⚪', colors: ['#111827', '#1F2937', '#374151'], textColor: '#9CA3AF', badge: '#6B7280' },
};

const DashboardScreen = () => {
  const { connected, temperature: wsTemperature, alerts: wsAlerts } = useWebSocket();

  const [displayTemp, setDisplayTemp] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [todayAlertCount, setTodayAlertCount] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [activeAlert, setActiveAlert] = useState(null);
  const [secondsAgo, setSecondsAgo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);

  const pulseAnim = useRef(new Animated.Value(1)).current;
  const secondsTimerRef = useRef(null);

  // ── Pulse the temperature display ───────────
  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 1.04, duration: 1200, useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 1, duration: 1200, useNativeDriver: true }),
      ])
    ).start();
  }, [pulseAnim]);

  // ── Update temperature from WebSocket ───────
  useEffect(() => {
    if (wsTemperature !== null && wsTemperature !== undefined) {
      setDisplayTemp(wsTemperature);
      setLastUpdated(new Date());
    }
  }, [wsTemperature]);

  // ── Watch for new alerts from WebSocket ─────
  useEffect(() => {
    if (wsAlerts && wsAlerts.length > 0) {
      const newest = wsAlerts[0];
      if (!activeAlert) {
        setActiveAlert(newest);
      }
    }
  }, [wsAlerts]);

  // ── "X seconds ago" counter ─────────────────
  useEffect(() => {
    if (secondsTimerRef.current) clearInterval(secondsTimerRef.current);
    if (lastUpdated) {
      secondsTimerRef.current = setInterval(() => {
        const secs = Math.floor((Date.now() - lastUpdated.getTime()) / 1000);
        setSecondsAgo(secs);
      }, 1000);
    }
    return () => clearInterval(secondsTimerRef.current);
  }, [lastUpdated]);

  // ── Fetch initial data when screen is focused
  const fetchData = useCallback(async () => {
    setFetchError(null);
    try {
      const [currentData, alertsData] = await Promise.allSettled([
        getCurrentReading(),
        getAlerts(),
      ]);

      if (currentData.status === 'fulfilled' && currentData.value) {
        const t = currentData.value.temperature ?? currentData.value.temp;
        if (t !== undefined) {
          setDisplayTemp(t);
          setLastUpdated(new Date());
        }
      }

      if (alertsData.status === 'fulfilled' && Array.isArray(alertsData.value)) {
        const today = new Date().toDateString();
        const todayCount = alertsData.value.filter(
          (a) => new Date(a.timestamp).toDateString() === today
        ).length;
        setTodayAlertCount(todayCount);
      }

      if (currentData.status === 'rejected' && alertsData.status === 'rejected') {
        setFetchError('Could not reach server. Check your connection.');
      }
    } catch (err) {
      console.warn('[Dashboard] Fetch error:', err);
      setFetchError('Could not reach server. Check your connection.');
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchData();
    }, [fetchData])
  );

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
  };

  const handleAlertDismiss = () => {
    setActiveAlert(null);
  };

  const status = getTempStatus(displayTemp);
  const cfg = STATUS_CONFIG[status];

  const lastUpdatedLabel =
    secondsAgo === null ? 'Never' :
    secondsAgo < 60 ? `${secondsAgo}s ago` :
    `${Math.floor(secondsAgo / 60)}m ago`;

  // ── Loading skeleton (initial fetch only, not shown during pull-to-refresh)
  if (loading && displayTemp === null) {
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

  // ── Error state (HTTP failed and WS has no data yet either)
  if (fetchError && displayTemp === null) {
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

  return (
    <View style={styles.flex}>
      <StatusBar barStyle="light-content" backgroundColor="#0F0C29" />

      {/* Alert Overlay — mounts at root of this screen too as fallback */}
      <AlertOverlay
        visible={!!activeAlert}
        alertData={activeAlert}
        onDismiss={handleAlertDismiss}
      />

      <LinearGradient colors={cfg.colors} style={styles.flex}>
        {/* Connection Banner */}
        <ConnectionBanner connected={connected} />

        <ScrollView
          contentContainerStyle={styles.scrollContent}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FFFFFF" />
          }
        >
          {/* Header */}
          <View style={styles.header}>
            <View>
              <Text style={styles.headerTitle}>SentinelEdge</Text>
              <Text style={styles.headerSubtitle}>Live Temperature Monitor</Text>
            </View>
            <View style={[styles.statusBadge, { backgroundColor: cfg.badge }]}>
              <Text style={styles.statusBadgeText}>{cfg.emoji} {cfg.label}</Text>
            </View>
          </View>

          {/* Main Temperature Display */}
          <View style={styles.tempSection}>
            <Text style={[styles.tempLabel, { color: cfg.textColor }]}>CURRENT TEMPERATURE</Text>
            <Animated.View style={{ transform: [{ scale: pulseAnim }] }}>
              <Text style={styles.tempValue}>
                {displayTemp !== null ? `${Number(displayTemp).toFixed(1)}°` : '--°'}
              </Text>
              <Text style={[styles.tempUnit, { color: cfg.textColor }]}>Celsius</Text>
            </Animated.View>
          </View>

          {/* Status Cards Row */}
          <View style={styles.cardsRow}>
            {/* Last Updated */}
            <View style={styles.card}>
              <Ionicons name="time-outline" size={22} color={cfg.textColor} />
              <Text style={[styles.cardValue, { color: '#FFFFFF' }]}>{lastUpdatedLabel}</Text>
              <Text style={styles.cardLabel}>Last Updated</Text>
            </View>

            {/* Today's Alerts */}
            <View style={styles.card}>
              <Ionicons name="warning-outline" size={22} color={cfg.textColor} />
              <Text style={[styles.cardValue, { color: '#FFFFFF' }]}>{todayAlertCount}</Text>
              <Text style={styles.cardLabel}>Alerts Today</Text>
            </View>

            {/* Connection Status */}
            <View style={styles.card}>
              <Ionicons
                name={connected ? 'wifi' : 'wifi-outline'}
                size={22}
                color={connected ? '#34D399' : '#F87171'}
              />
              <Text style={[styles.cardValue, { color: connected ? '#34D399' : '#F87171' }]}>
                {connected ? 'Live' : 'Off'}
              </Text>
              <Text style={styles.cardLabel}>WebSocket</Text>
            </View>
          </View>

          {/* Threshold Guide */}
          <View style={styles.thresholdCard}>
            <Text style={styles.thresholdTitle}>Temperature Thresholds</Text>
            <View style={styles.thresholdRow}>
              <View style={[styles.thresholdDot, { backgroundColor: '#EF4444' }]} />
              <Text style={styles.thresholdText}>DANGER  — above 90°C</Text>
            </View>
            <View style={styles.thresholdRow}>
              <View style={[styles.thresholdDot, { backgroundColor: '#F59E0B' }]} />
              <Text style={styles.thresholdText}>NORMAL  — 42°C to 90°C</Text>
            </View>
            <View style={styles.thresholdRow}>
              <View style={[styles.thresholdDot, { backgroundColor: '#10B981' }]} />
              <Text style={styles.thresholdText}>READY   — below 42°C (Alert triggered)</Text>
            </View>
          </View>

          {/* Refresh hint */}
          <TouchableOpacity style={styles.refreshHint} onPress={onRefresh}>
            <Ionicons name="refresh-outline" size={16} color="rgba(255,255,255,0.5)" />
            <Text style={styles.refreshHintText}>Pull down to refresh</Text>
          </TouchableOpacity>
        </ScrollView>
      </LinearGradient>
    </View>
  );
};

const styles = StyleSheet.create({
  flex: { flex: 1 },
  scrollContent: {
    paddingHorizontal: 20,
    paddingBottom: 40,
    paddingTop: 16,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 32,
  },
  headerTitle: {
    fontSize: 22,
    fontWeight: '800',
    color: '#FFFFFF',
    letterSpacing: 0.5,
  },
  headerSubtitle: {
    fontSize: 12,
    color: 'rgba(255,255,255,0.6)',
    marginTop: 2,
  },
  statusBadge: {
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 20,
  },
  statusBadgeText: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 13,
    letterSpacing: 0.5,
  },
  tempSection: {
    alignItems: 'center',
    marginBottom: 36,
    paddingVertical: 24,
    backgroundColor: 'rgba(0,0,0,0.2)',
    borderRadius: 24,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  tempLabel: {
    fontSize: 12,
    letterSpacing: 3,
    marginBottom: 8,
    fontWeight: '600',
  },
  tempValue: {
    fontSize: 100,
    fontWeight: '900',
    color: '#FFFFFF',
    textAlign: 'center',
    lineHeight: 110,
  },
  tempUnit: {
    fontSize: 18,
    textAlign: 'center',
    letterSpacing: 2,
    marginTop: -4,
  },
  cardsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 20,
    gap: 10,
  },
  card: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.25)',
    borderRadius: 16,
    padding: 14,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  cardValue: {
    fontSize: 18,
    fontWeight: '800',
    marginTop: 6,
    marginBottom: 2,
  },
  cardLabel: {
    fontSize: 10,
    color: 'rgba(255,255,255,0.5)',
    letterSpacing: 0.5,
    textAlign: 'center',
  },
  thresholdCard: {
    backgroundColor: 'rgba(0,0,0,0.25)',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    marginBottom: 20,
  },
  thresholdTitle: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 12,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom: 12,
    fontWeight: '600',
  },
  thresholdRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  thresholdDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 10,
  },
  thresholdText: {
    color: 'rgba(255,255,255,0.75)',
    fontSize: 13,
  },
  refreshHint: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 6,
    marginTop: 4,
  },
  refreshHintText: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 12,
  },
});

export default DashboardScreen;
