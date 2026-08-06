/**
 * src/services/pushTokenService.js — SentinelEdge push token registration.
 *
 * NEW FILE — does NOT touch api.js, auth.js, or any existing service.
 *
 * Registers the device's Expo push token (or raw FCM token) with the
 * SentinelEdge backend so the server can send out-of-network alerts
 * to this device when it is backgrounded or killed.
 *
 * Usage (call once after a successful subscriber login):
 *
 *   import { registerPushToken, deregisterPushToken } from './pushTokenService';
 *
 *   // After login:
 *   await registerPushToken(authToken, serverBaseUrl);
 *
 *   // After logout:
 *   await deregisterPushToken(authToken, serverBaseUrl);
 *
 * The backend endpoint used:
 *   POST   /api/notifications/push-token   (bearer = X-Auth-Token from subscriber login)
 *   DELETE /api/notifications/push-token
 *
 * The token is stored in the backend's subscribers.expo_push_token column
 * and is picked up automatically by core/escalation.py on the next alert.
 */

import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import AsyncStorage from '@react-native-async-storage/async-storage';

const PUSH_TOKEN_KEY = '@sentineledge_push_token';

/**
 * Request push notification permissions, retrieve the Expo push token,
 * and register it with the backend.
 *
 * @param {string} authToken  — X-Auth-Token from the subscriber login response
 * @param {string} serverBaseUrl — e.g. "http://192.168.1.5:5000"
 * @returns {Promise<string|null>} The registered push token, or null on failure
 */
export async function registerPushToken(authToken, serverBaseUrl) {
  try {
    // Push notifications only work on physical devices
    if (!Device.isDevice) {
      console.log('[PushToken] Skipping — not a physical device');
      return null;
    }

    // Request permissions
    const { status: existingStatus } = await Notifications.getPermissionsAsync();
    let finalStatus = existingStatus;

    if (existingStatus !== 'granted') {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }

    if (finalStatus !== 'granted') {
      console.warn('[PushToken] Push notification permission denied');
      return null;
    }

    // Get the Expo push token
    const tokenData = await Notifications.getExpoPushTokenAsync();
    const pushToken = tokenData.data;

    // Cache locally
    await AsyncStorage.setItem(PUSH_TOKEN_KEY, pushToken);

    // Register with backend
    const res = await fetch(`${serverBaseUrl}/api/notifications/push-token`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Auth-Token': authToken,
      },
      body: JSON.stringify({ token: pushToken, type: 'expo' }),
    });

    if (!res.ok) {
      const text = await res.text();
      console.error(`[PushToken] Backend registration failed: ${res.status} ${text}`);
      return null;
    }

    console.log('[PushToken] Registered successfully:', pushToken);
    return pushToken;

  } catch (err) {
    // Never crash the app — push registration is best-effort
    console.error('[PushToken] registerPushToken error:', err);
    return null;
  }
}

/**
 * Deregister the push token from the backend (call on subscriber logout).
 * Also clears the locally cached token.
 *
 * @param {string} authToken  — X-Auth-Token from the subscriber login response
 * @param {string} serverBaseUrl — e.g. "http://192.168.1.5:5000"
 */
export async function deregisterPushToken(authToken, serverBaseUrl) {
  try {
    await AsyncStorage.removeItem(PUSH_TOKEN_KEY);

    const res = await fetch(`${serverBaseUrl}/api/notifications/push-token`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'X-Auth-Token': authToken,
      },
    });

    if (!res.ok) {
      console.warn(`[PushToken] Backend deregistration returned ${res.status}`);
    } else {
      console.log('[PushToken] Deregistered successfully');
    }

  } catch (err) {
    console.error('[PushToken] deregisterPushToken error:', err);
  }
}

/**
 * Read the cached push token from AsyncStorage (useful to check
 * whether the device is already registered without hitting the network).
 *
 * @returns {Promise<string|null>}
 */
export async function getCachedPushToken() {
  try {
    return await AsyncStorage.getItem(PUSH_TOKEN_KEY);
  } catch {
    return null;
  }
}

/**
 * Subscribe to Expo push token refresh events and re-register the new
 * token with the backend automatically.  Call once after login and
 * store the returned subscription to remove it on logout.
 *
 * @param {string} authToken
 * @param {string} serverBaseUrl
 * @returns {import('expo-notifications').Subscription}
 */
export function setupTokenRefresh(authToken, serverBaseUrl) {
  return Notifications.addPushTokenListener(async ({ data: newToken }) => {
    try {
      await AsyncStorage.setItem(PUSH_TOKEN_KEY, newToken);
      await fetch(`${serverBaseUrl}/api/notifications/push-token`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Auth-Token': authToken,
        },
        body: JSON.stringify({ token: newToken, type: 'expo' }),
      });
      console.log('[PushToken] Token refreshed and re-registered:', newToken);
    } catch (err) {
      console.warn('[PushToken] Token refresh re-registration failed:', err);
    }
  });
}
