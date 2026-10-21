// ─────────────────────────────────────────────
//  SentinelEdge — Alerts Screen
//  Lists today's alerts with pull-to-refresh
// ─────────────────────────────────────────────
import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  RefreshControl,
  StatusBar,
  TouchableOpacity,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { getAlerts, acknowledgeAlert } from '../services/api';
import { getSession } from '../services/auth';
import { unitFor, formatValue } from '../services/appConfig';

const AlertTypeConfig = {
  HIGH: { word: 'HIGH', color: '#EF4444', bg: 'rgba(239,68,68,0.15)', icon: 'arrow-up-circle-outline' },
  LOW:  { word: 'LOW',  color: '#F59E0B', bg: 'rgba(245,158,11,0.15)', icon: 'arrow-down-circle-outline' },
};

const AlertCard = ({ item, onAcknowledge, acking }) => {
  const dir = String(item.direction || '').toUpperCase();
  const typeCfg = AlertTypeConfig[dir] || { word: 'ALERT', color: '#F59E0B', bg: 'rgba(245,158,11,0.15)', icon: 'warning-outline' };
  const unit = unitFor(item.parameter);
  const label = `${typeCfg.word} ${String(item.parameter || '').toUpperCase()}`.trim();
  const timestamp = item.timestamp ? new Date(item.timestamp).toLocaleString() : 'Unknown time';
  const ackTime = item.acknowledged_at ? new Date(item.acknowledged_at).toLocaleString() : null;
  const temp = item.value != null ? `${formatValue(item.value)} ${unit}`.trim() : '--';

  return (
    <View style={[styles.alertCard, { borderLeftColor: typeCfg.color }]}>
      {/* Type Badge + Temp */}
      <View style={styles.cardHeader}>
        <View style={[styles.typeBadge, { backgroundColor: typeCfg.bg }]}>
          <Ionicons name={typeCfg.icon} size={14} color={typeCfg.color} />
          <Text style={[styles.typeBadgeText, { color: typeCfg.color }]}>{label}</Text>
        </View>
        <Text style={styles.tempValue}>{temp}</Text>
      </View>

      {item.threshold != null ? (
        <View style={styles.infoRow}>
          <Ionicons name="speedometer-outline" size={14} color="#9CA3AF" />
          <Text style={styles.infoText}>Limit: {formatValue(item.threshold)} {unit}</Text>
        </View>
      ) : null}

      {/* Timestamp */}
      <View style={styles.infoRow}>
        <Ionicons name="time-outline" size={14} color="#9CA3AF" />
        <Text style={styles.infoText}>{timestamp}</Text>
      </View>

      {/* Acknowledged */}
      {item.acknowledged || item.acknowledged_by ? (
        <View style={styles.ackRow}>
          <Ionicons name="checkmark-circle" size={14} color="#34D399" />
          <Text style={styles.ackText}>
            Acknowledged by <Text style={styles.ackName}>{item.acknowledged_by}</Text>
            {ackTime ? ` at ${ackTime}` : ''}
          </Text>
        </View>
      ) : (
        <View style={styles.ackRow}>
          <Ionicons name="ellipse-outline" size={14} color="#F87171" />
          <Text style={[styles.ackText, { color: '#F87171' }]}>Not yet acknowledged</Text>
          <TouchableOpacity
            onPress={() => onAcknowledge && onAcknowledge(item)}
            disabled={acking}
            style={{ marginLeft: 'auto', backgroundColor: '#6366F1', borderRadius: 10, paddingHorizontal: 12, paddingVertical: 6, opacity: acking ? 0.5 : 1 }}
          >
            <Text style={{ color: '#FFFFFF', fontSize: 12, fontWeight: '700' }}>{acking ? 'Sending…' : 'Acknowledge'}</Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
};

const EmptyState = () => (
  <View style={styles.emptyContainer}>
    <Ionicons name="checkmark-circle-outline" size={64} color="#374151" />
    <Text style={styles.emptyTitle}>All Clear</Text>
    <Text style={styles.emptySubtitle}>No alerts recorded today</Text>
  </View>
);

const AlertsScreen = () => {
  const [alerts, setAlerts] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [ackingId, setAckingId] = useState(null);

  const handleAcknowledge = async (item) => {
    setAckingId(item.id);
    try {
      const session = await getSession();
      await acknowledgeAlert(item.id, session.username || 'App user');
      setAlerts((prev) => prev.map((a) => (a.id === item.id ? { ...a, acknowledged: true, acknowledged_by: session.username || 'App user', acknowledged_at: new Date().toISOString() } : a)));
    } catch (err) {
      setError('Could not acknowledge. Check the connection and try again.');
    } finally {
      setAckingId(null);
    }
  };

  const fetchAlerts = useCallback(async () => {
    setError('');
    try {
      const data = await getAlerts();
      const today = new Date().toDateString();
      const todayAlerts = Array.isArray(data)
        ? data.filter((a) => new Date(a.timestamp).toDateString() === today || !a.acknowledged)   // today's, plus anything still open
        : [];
      // Sort newest first
      todayAlerts.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
      setAlerts(todayAlerts);
    } catch (err) {
      console.error('[Alerts] Fetch error:', err);
      setError('Failed to load alerts. Pull to retry.');
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      setLoading(true);
      fetchAlerts();
    }, [fetchAlerts])
  );

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchAlerts();
    setRefreshing(false);
  };

  return (
    <View style={styles.flex}>
      <StatusBar barStyle="light-content" backgroundColor="#0F0C29" />
      <LinearGradient colors={['#0F0C29', '#1E1B4B', '#24243E']} style={styles.flex}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Today's Alerts</Text>
          <View style={styles.countBadge}>
            <Text style={styles.countBadgeText}>{alerts.length}</Text>
          </View>
        </View>

        {error ? (
          <View style={styles.errorContainer}>
            <Ionicons name="alert-circle-outline" size={16} color="#F87171" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        <FlatList
          data={alerts}
          keyExtractor={(item, idx) => String(item.id ?? idx)}
          renderItem={({ item }) => <AlertCard item={item} onAcknowledge={handleAcknowledge} acking={ackingId === item.id} />}
          contentContainerStyle={[
            styles.listContent,
            alerts.length === 0 && styles.listContentEmpty,
          ]}
          ListEmptyComponent={!loading ? <EmptyState /> : null}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor="#818CF8"
              colors={['#818CF8']}
            />
          }
          showsVerticalScrollIndicator={false}
        />
      </LinearGradient>
    </View>
  );
};

const styles = StyleSheet.create({
  flex: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 12,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: '800',
    color: '#FFFFFF',
    flex: 1,
  },
  countBadge: {
    backgroundColor: '#6366F1',
    borderRadius: 14,
    minWidth: 28,
    height: 28,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 8,
  },
  countBadgeText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '700',
  },
  errorContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 20,
    marginBottom: 12,
    backgroundColor: 'rgba(248,113,113,0.12)',
    borderRadius: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: 'rgba(248,113,113,0.3)',
  },
  errorText: {
    color: '#F87171',
    fontSize: 13,
    marginLeft: 6,
    flex: 1,
  },
  listContent: {
    paddingHorizontal: 20,
    paddingBottom: 40,
  },
  listContentEmpty: {
    flexGrow: 1,
  },
  alertCard: {
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: 14,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
    borderLeftWidth: 4,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  typeBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: 20,
    gap: 4,
  },
  typeBadgeText: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  tempValue: {
    fontSize: 22,
    fontWeight: '800',
    color: '#FFFFFF',
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
    gap: 6,
  },
  infoText: {
    color: '#9CA3AF',
    fontSize: 13,
  },
  ackRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 6,
  },
  ackText: {
    color: '#9CA3AF',
    fontSize: 13,
    flex: 1,
  },
  ackName: {
    color: '#34D399',
    fontWeight: '700',
  },
  emptyContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 80,
  },
  emptyTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: '#6B7280',
    marginTop: 16,
  },
  emptySubtitle: {
    fontSize: 14,
    color: '#4B5563',
    marginTop: 6,
  },
});

export default AlertsScreen;
