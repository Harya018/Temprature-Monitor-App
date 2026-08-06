// ─────────────────────────────────────────────
//  SentinelEdge — App.js (Root)
//  Session check, permission requests, navigation,
//  background task registration, global AlertOverlay
// ─────────────────────────────────────────────
import React, { useEffect, useState, useRef } from 'react';
import { View, StyleSheet, Platform, Alert, StatusBar } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Notifications from 'expo-notifications';
import * as IntentLauncher from 'expo-intent-launcher';

import LoginScreen from './src/screens/LoginScreen';
import DashboardScreen from './src/screens/DashboardScreen';
import AlertsScreen from './src/screens/AlertsScreen';
import SettingsScreen from './src/screens/SettingsScreen';
import AlertOverlay from './src/components/AlertOverlay';
import OfflineBanner from './src/components/OfflineBanner';
import { verifySession } from './src/services/auth';
import { registerBackgroundTask } from './src/tasks/backgroundTask';
import { useWebSocket } from './src/hooks/useWebSocket';

// ── Notification handler ─────────────────────
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

// ── Bottom Tab Navigator ─────────────────────
const MainTabs = ({ globalAlert, onAlertDismiss }) => (
  <View style={{ flex: 1 }}>
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: {
          backgroundColor: '#0F0C29',
          borderTopColor: 'rgba(255,255,255,0.08)',
          borderTopWidth: 1,
          paddingBottom: 8,
          paddingTop: 6,
          height: 62,
        },
        tabBarActiveTintColor: '#818CF8',
        tabBarInactiveTintColor: '#4B5563',
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: '600',
          letterSpacing: 0.3,
        },
        tabBarIcon: ({ focused, color, size }) => {
          let iconName;
          if (route.name === 'Dashboard') {
            iconName = focused ? 'speedometer' : 'speedometer-outline';
          } else if (route.name === 'Alerts') {
            iconName = focused ? 'warning' : 'warning-outline';
          } else if (route.name === 'Settings') {
            iconName = focused ? 'settings' : 'settings-outline';
          }
          return <Ionicons name={iconName} size={size} color={color} />;
        },
      })}
    >
      <Tab.Screen name="Dashboard" component={DashboardScreen} />
      <Tab.Screen name="Alerts" component={AlertsScreen} />
      <Tab.Screen name="Settings" component={SettingsScreen} />
    </Tab.Navigator>

    {/* Global AlertOverlay — renders over all tab screens */}
    <AlertOverlay
      visible={!!globalAlert}
      alertData={globalAlert}
      onDismiss={onAlertDismiss}
    />
  </View>
);

// ── Alert listener wrapper ───────────────────
const MainTabsWrapper = ({ navigation }) => {
  const { alerts } = useWebSocket();
  const [globalAlert, setGlobalAlert] = useState(null);
  const seenAlertsRef = useRef(new Set());

  useEffect(() => {
    if (alerts && alerts.length > 0) {
      const newest = alerts[0];
      const alertId = newest.id ?? newest.timestamp;
      if (!seenAlertsRef.current.has(alertId)) {
        seenAlertsRef.current.add(alertId);
        setGlobalAlert(newest);
      }
    }
  }, [alerts]);

  return (
    <MainTabs
      globalAlert={globalAlert}
      onAlertDismiss={() => setGlobalAlert(null)}
    />
  );
};

// ── Root App ─────────────────────────────────
export default function App() {
  const [initialRoute, setInitialRoute] = useState(null); // null = loading

  // ── On mount: check session + request permissions ──
  useEffect(() => {
    const init = async () => {
      // 1. Check existing session
      const isLoggedIn = await verifySession();
      setInitialRoute(isLoggedIn ? 'Main' : 'Login');

      // 2. Request notification permissions
      const { status: existingStatus } = await Notifications.getPermissionsAsync();
      if (existingStatus !== 'granted') {
        const { status } = await Notifications.requestPermissionsAsync();
        if (status !== 'granted') {
          console.warn('[App] Notification permission denied');
        }
      }

      // 2b. Create the high-priority alert channel (Android only).
      // Must be done programmatically — plugin config only handles build-time assets.
      // Channel settings are user-owned after first creation; this is a no-op on re-runs
      // unless the channel was deleted.
      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('critical-alerts', {
          name: 'Critical Alerts',
          importance: Notifications.AndroidImportance.MAX,
          vibrationPattern: [0, 500, 200, 500, 200, 500],
          enableVibrate: true,
          bypassDnd: true,
          lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
          showBadge: true,
        });
      }

      // 3. Register background task
      try {
        await registerBackgroundTask();
      } catch (err) {
        console.warn('[App] Background task registration failed:', err);
      }

      // 4. Request battery optimization exemption (Android only)
      if (Platform.OS === 'android') {
        try {
          // Prompt user to disable battery optimisation
          Alert.alert(
            'Battery Optimization',
            'For reliable monitoring, please disable battery optimization for SentinelEdge.',
            [
              { text: 'Later', style: 'cancel' },
              {
                text: 'Open Settings',
                onPress: () => {
                  IntentLauncher.startActivityAsync(
                    IntentLauncher.ActivityAction.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    { data: 'package:com.sentineledge.app' }
                  ).catch(() => {
                    // Fallback — open general battery settings
                    IntentLauncher.startActivityAsync(
                      'android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS'
                    ).catch(console.warn);
                  });
                },
              },
            ]
          );
        } catch (err) {
          console.warn('[App] Battery optimization request failed:', err);
        }
      }
    };

    init();
  }, []);

  // Still loading session
  if (initialRoute === null) {
    return <View style={styles.loadingContainer} />;
  }

  return (
    <SafeAreaProvider>
      <StatusBar barStyle="light-content" backgroundColor="#0F0C29" />
      <OfflineBanner />
      <NavigationContainer>
        <Stack.Navigator
          initialRouteName={initialRoute}
          screenOptions={{ headerShown: false, animation: 'fade' }}
        >
          <Stack.Screen name="Login" component={LoginScreen} />
          <Stack.Screen name="Main" component={MainTabsWrapper} />
        </Stack.Navigator>
      </NavigationContainer>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    backgroundColor: '#0F0C29',
  },
});
