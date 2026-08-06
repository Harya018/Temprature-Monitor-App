// ─────────────────────────────────────────────
//  SentinelEdge — Settings Screen
//  Server info, app version, WS status, logout
// ─────────────────────────────────────────────
import React, { useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  Alert,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';

import { API_BASE, WS_URL } from '../config/config';
import { clearSession, getSession } from '../services/auth';
import { deregisterPushToken } from '../services/pushTokenService';
import { useWebSocket } from '../hooks/useWebSocket';

const SettingsRow = ({ icon, label, value, valueColor, iconColor = '#818CF8' }) => (
  <View style={styles.settingsRow}>
    <View style={[styles.rowIconWrap, { backgroundColor: `${iconColor}20` }]}>
      <Ionicons name={icon} size={20} color={iconColor} />
    </View>
    <View style={styles.rowContent}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, valueColor && { color: valueColor }]}>{value}</Text>
    </View>
  </View>
);

const SettingsScreen = ({ navigation }) => {
  const { connected } = useWebSocket();
  const [username, setUsername] = React.useState('');

  useFocusEffect(
    useCallback(() => {
      (async () => {
        const session = await getSession();
        setUsername(session.username || 'Unknown');
      })();
    }, [])
  );

  const handleLogout = () => {
    Alert.alert(
      'Sign Out',
      'Are you sure you want to sign out?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Sign Out',
          style: 'destructive',
          onPress: async () => {
            const session = await getSession();
            if (session?.token) {
              deregisterPushToken(session.token, API_BASE.replace('/api', '')).catch(() => {});
            }
            await clearSession();
            navigation.replace('Login');
          },
        },
      ],
      { cancelable: true }
    );
  };

  return (
    <View style={styles.flex}>
      <StatusBar barStyle="light-content" backgroundColor="#0F0C29" />
      <LinearGradient colors={['#0F0C29', '#1E1B4B', '#24243E']} style={styles.flex}>
        <ScrollView contentContainerStyle={styles.scrollContent}>
          {/* Header */}
          <Text style={styles.screenTitle}>Settings</Text>

          {/* Account Section */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>ACCOUNT</Text>
            <View style={styles.card}>
              <View style={styles.avatarRow}>
                <View style={styles.avatar}>
                  <Ionicons name="person" size={28} color="#818CF8" />
                </View>
                <View>
                  <Text style={styles.usernameText}>{username}</Text>
                  <Text style={styles.roleText}>Authorized Worker</Text>
                </View>
              </View>
            </View>
          </View>

          {/* Server Section */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>SERVER CONNECTION</Text>
            <View style={styles.card}>
              <SettingsRow
                icon="server-outline"
                label="API Server"
                value={API_BASE}
                iconColor="#6366F1"
              />
              <View style={styles.divider} />
              <SettingsRow
                icon="wifi-outline"
                label="WebSocket URL"
                value={WS_URL}
                iconColor="#6366F1"
              />
              <View style={styles.divider} />
              <SettingsRow
                icon={connected ? 'radio-button-on' : 'radio-button-off'}
                label="WebSocket Status"
                value={connected ? 'Connected' : 'Disconnected'}
                valueColor={connected ? '#34D399' : '#F87171'}
                iconColor={connected ? '#34D399' : '#F87171'}
              />
            </View>
          </View>

          {/* App Info Section */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>APP INFORMATION</Text>
            <View style={styles.card}>
              <SettingsRow
                icon="shield-checkmark-outline"
                label="Application"
                value="SentinelEdge"
                iconColor="#818CF8"
              />
              <View style={styles.divider} />
              <SettingsRow
                icon="code-slash-outline"
                label="Version"
                value="1.0.0"
                iconColor="#818CF8"
              />
              <View style={styles.divider} />
              <SettingsRow
                icon="phone-portrait-outline"
                label="Platform"
                value="Android (React Native Expo)"
                iconColor="#818CF8"
              />
            </View>
          </View>

          {/* Logout Button */}
          <TouchableOpacity
            style={styles.logoutButton}
            onPress={handleLogout}
            activeOpacity={0.8}
          >
            <Ionicons name="log-out-outline" size={20} color="#F87171" style={{ marginRight: 8 }} />
            <Text style={styles.logoutButtonText}>Sign Out</Text>
          </TouchableOpacity>

          <Text style={styles.footer}>SentinelEdge • Industrial IoT Monitor</Text>
        </ScrollView>
      </LinearGradient>
    </View>
  );
};

const styles = StyleSheet.create({
  flex: { flex: 1 },
  scrollContent: {
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 60,
  },
  screenTitle: {
    fontSize: 28,
    fontWeight: '800',
    color: '#FFFFFF',
    marginBottom: 24,
  },
  section: {
    marginBottom: 20,
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: '700',
    color: '#6B7280',
    letterSpacing: 1.5,
    marginBottom: 10,
    marginLeft: 4,
  },
  card: {
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: 16,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
  },
  settingsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
  },
  rowIconWrap: {
    width: 38,
    height: 38,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 14,
  },
  rowContent: {
    flex: 1,
  },
  rowLabel: {
    color: '#9CA3AF',
    fontSize: 12,
    marginBottom: 2,
  },
  rowValue: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  divider: {
    height: 1,
    backgroundColor: 'rgba(255,255,255,0.06)',
    marginLeft: 68,
  },
  avatarRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    gap: 14,
  },
  avatar: {
    width: 54,
    height: 54,
    borderRadius: 27,
    backgroundColor: 'rgba(129,140,248,0.15)',
    borderWidth: 2,
    borderColor: 'rgba(129,140,248,0.3)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  usernameText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: '700',
  },
  roleText: {
    color: '#9CA3AF',
    fontSize: 13,
    marginTop: 2,
  },
  logoutButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(248,113,113,0.1)',
    borderRadius: 16,
    paddingVertical: 16,
    borderWidth: 1,
    borderColor: 'rgba(248,113,113,0.3)',
    marginTop: 8,
    marginBottom: 32,
  },
  logoutButtonText: {
    color: '#F87171',
    fontSize: 16,
    fontWeight: '700',
  },
  footer: {
    color: '#374151',
    fontSize: 12,
    textAlign: 'center',
  },
});

export default SettingsScreen;
