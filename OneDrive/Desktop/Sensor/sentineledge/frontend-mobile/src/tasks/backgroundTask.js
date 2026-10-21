// ─────────────────────────────────────────────
//  SentinelEdge — Background Task
//  Uses expo-task-manager + expo-background-fetch
//  to keep app alive with a persistent notification
// ─────────────────────────────────────────────
import * as TaskManager from 'expo-task-manager';
import * as BackgroundFetch from 'expo-background-fetch';
import * as Notifications from 'expo-notifications';

export const BACKGROUND_WEBSOCKET_TASK = 'SENTINELEDGE_BACKGROUND_MONITORING';

// ── Define the background task ───────────────
TaskManager.defineTask(BACKGROUND_WEBSOCKET_TASK, async () => {
  try {
    // Keep ONE quiet status notification (same identifier = replaced, never stacked). It must
    // never make a sound or vibrate: only real alerts may ring the phone.
    await Notifications.scheduleNotificationAsync({
      identifier: 'sentineledge-monitoring',
      content: {
        title: 'SentinelEdge Monitoring Active',
        body: 'Monitoring is running in the background.',
        sticky: true,
        sound: false,
        priority: Notifications.AndroidNotificationPriority.LOW,
        data: { type: 'background_service' },
      },
      trigger: { channelId: 'monitoring' },   // silent channel, created in App.js
    });

    return BackgroundFetch.BackgroundFetchResult.NewData;
  } catch (error) {
    console.error('[BackgroundTask] Error:', error);
    return BackgroundFetch.BackgroundFetchResult.Failed;
  }
});

/**
 * registerBackgroundTask — register the background fetch task
 */
export const registerBackgroundTask = async () => {
  try {
    const isRegistered = await TaskManager.isTaskRegisteredAsync(BACKGROUND_WEBSOCKET_TASK);
    if (!isRegistered) {
      await BackgroundFetch.registerTaskAsync(BACKGROUND_WEBSOCKET_TASK, {
        minimumInterval: 60, // seconds — minimum 60s on Android
        stopOnTerminate: false,
        startOnBoot: true,
      });
      console.log('[BackgroundTask] Registered:', BACKGROUND_WEBSOCKET_TASK);
    } else {
      console.log('[BackgroundTask] Already registered:', BACKGROUND_WEBSOCKET_TASK);
    }
  } catch (error) {
    console.error('[BackgroundTask] Registration failed:', error);
  }
};

/**
 * unregisterBackgroundTask — unregister the background fetch task
 */
export const unregisterBackgroundTask = async () => {
  try {
    const isRegistered = await TaskManager.isTaskRegisteredAsync(BACKGROUND_WEBSOCKET_TASK);
    if (isRegistered) {
      await BackgroundFetch.unregisterTaskAsync(BACKGROUND_WEBSOCKET_TASK);
      console.log('[BackgroundTask] Unregistered:', BACKGROUND_WEBSOCKET_TASK);
    }
  } catch (error) {
    console.error('[BackgroundTask] Unregistration failed:', error);
  }
};
