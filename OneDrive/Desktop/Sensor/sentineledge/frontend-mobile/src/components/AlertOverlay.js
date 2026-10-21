// ─────────────────────────────────────────────
//  SentinelEdge — Alert Overlay Component
//  Full-screen blocking overlay triggered by WebSocket alerts.
//  Cannot be dismissed without acknowledging.
// ─────────────────────────────────────────────
import React, { useEffect, useRef, useState } from 'react';
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Animated,
  TextInput,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Vibration,
} from 'react-native';
import { Audio } from 'expo-av';
import * as Haptics from 'expo-haptics';
import { acknowledgeAlert } from '../services/api';
import { unitFor, formatValue } from '../services/appConfig';

const VIBRATION_PATTERN = [0, 500, 1000]; // on 500ms, off 1000ms, loop

const AlertOverlay = ({ visible, alertData, onDismiss }) => {
  const [workerName, setWorkerName] = useState('');
  const [showNameInput, setShowNameInput] = useState(false);
  const [acknowledging, setAcknowledging] = useState(false);
  const [error, setError] = useState('');

  const soundRef = useRef(null);
  const hapticIntervalRef = useRef(null);
  const pulseAnim = useRef(new Animated.Value(1)).current;

  // ── Pulse animation for overlay ──────────────
  useEffect(() => {
    if (visible) {
      Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {
            toValue: 0.85,
            duration: 600,
            useNativeDriver: true,
          }),
          Animated.timing(pulseAnim, {
            toValue: 1,
            duration: 600,
            useNativeDriver: true,
          }),
        ])
      ).start();
    } else {
      pulseAnim.stopAnimation();
      pulseAnim.setValue(1);
    }
  }, [visible, pulseAnim]);

  // ── Start alarm sound and vibration ─────────
  useEffect(() => {
    if (visible) {
      startAlarm();
      startVibration();
    } else {
      stopAlarm();
      stopVibration();
      setWorkerName('');
      setShowNameInput(false);
      setError('');
    }

    return () => {
      stopAlarm();
      stopVibration();
    };
  }, [visible]);

  const startAlarm = async () => {
    try {
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: false,
        playsInSilentModeIOS: true,
        shouldDuckAndroid: false,
        playThroughEarpieceAndroid: false,
      });
      const { sound } = await Audio.Sound.createAsync(
        require('../../assets/alarm.mp3'),
        { isLooping: true, volume: 1.0 }
      );
      soundRef.current = sound;
      await sound.playAsync();
    } catch (err) {
      console.warn('[AlertOverlay] Could not play alarm sound:', err.message);
      // Alarm sound is optional — continue without it
    }
  };

  const stopAlarm = async () => {
    try {
      if (soundRef.current) {
        await soundRef.current.stopAsync();
        await soundRef.current.unloadAsync();
        soundRef.current = null;
      }
    } catch (err) {
      console.warn('[AlertOverlay] Error stopping sound:', err.message);
    }
  };

  const startVibration = () => {
    // Vibrate every 1500ms using expo-haptics
    hapticIntervalRef.current = setInterval(async () => {
      try {
        await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      } catch {
        Vibration.vibrate(500);
      }
    }, 1500);
  };

  const stopVibration = () => {
    if (hapticIntervalRef.current) {
      clearInterval(hapticIntervalRef.current);
      hapticIntervalRef.current = null;
    }
    Vibration.cancel();
  };

  // ── Acknowledge button pressed ───────────────
  const handleAcknowledgePress = () => {
    setShowNameInput(true);
    setError('');
  };

  // ── Submit worker name and call API ─────────
  const handleSubmitAcknowledge = async () => {
    const trimmedName = workerName.trim();
    if (!trimmedName) {
      setError('Please enter your name to acknowledge.');
      return;
    }
    if (!alertData?.id) {
      setError('Alert data is missing. Cannot acknowledge.');
      return;
    }

    setAcknowledging(true);
    setError('');

    try {
      await acknowledgeAlert(alertData.id, trimmedName);
      stopAlarm();
      stopVibration();
      onDismiss && onDismiss();
    } catch (err) {
      console.error('[AlertOverlay] Acknowledge failed:', err);
      setError('Failed to acknowledge. Check connection and try again.');
    } finally {
      setAcknowledging(false);
    }
  };

  if (!visible) return null;

  const paramName = alertData?.parameter ? String(alertData.parameter) : 'Value';
  const unit = unitFor(alertData?.parameter);
  const dirWord = String(alertData?.direction || '').toLowerCase() === 'low' ? 'below' : 'above';
  const alertMessage = alertData?.message
    || (alertData?.threshold != null
      ? `${paramName.toUpperCase()} is ${dirWord} the limit of ${formatValue(alertData.threshold)} ${unit}`.trim()
      : `${paramName.toUpperCase()} ALERT DETECTED`);
  const alertTemp = alertData?.value != null ? `${formatValue(alertData.value)} ${unit}`.trim() : '--';
  const alertTime = alertData?.timestamp
    ? new Date(alertData.timestamp).toLocaleString()
    : new Date().toLocaleString();

  return (
    <Modal
      visible={visible}
      transparent={false}
      animationType="fade"
      statusBarTranslucent
      onRequestClose={() => {}} // Prevent hardware back button dismissal
    >
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        {/* Pulsing background */}
        <Animated.View style={[styles.pulseBackground, { opacity: pulseAnim }]} />

        <View style={styles.content}>
          {/* Alert Icon */}
          <Text style={styles.alertIcon}>🚨</Text>

          {/* Alert Title */}
          <Text style={styles.alertTitle}>{alertData?.test ? 'TEST ALERT' : 'ALERT TRIGGERED'}</Text>

          {/* Temperature */}
          <View style={styles.tempContainer}>
            <Text style={styles.tempLabel}>{paramName}</Text>
            <Text style={styles.tempValue}>{alertTemp}</Text>
          </View>

          {/* Message */}
          <Text style={styles.alertMessage}>{alertMessage}</Text>

          {/* Timestamp */}
          <Text style={styles.timestamp}>{alertTime}</Text>

          <View style={styles.divider} />

          {/* Name input or Acknowledge button */}
          {!showNameInput ? (
            <TouchableOpacity
              style={styles.acknowledgeButton}
              onPress={handleAcknowledgePress}
              activeOpacity={0.8}
            >
              <Text style={styles.acknowledgeButtonText}>Acknowledge Alert</Text>
            </TouchableOpacity>
          ) : (
            <View style={styles.nameInputSection}>
              <Text style={styles.namePrompt}>Enter your name to confirm:</Text>
              <TextInput
                style={styles.nameInput}
                placeholder="Your name..."
                placeholderTextColor="#ff9999"
                value={workerName}
                onChangeText={setWorkerName}
                autoFocus
                returnKeyType="done"
                onSubmitEditing={handleSubmitAcknowledge}
              />
              {error ? <Text style={styles.errorText}>{error}</Text> : null}
              <TouchableOpacity
                style={[styles.confirmButton, acknowledging && styles.confirmButtonDisabled]}
                onPress={handleSubmitAcknowledge}
                disabled={acknowledging}
                activeOpacity={0.8}
              >
                <Text style={styles.confirmButtonText}>
                  {acknowledging ? 'Confirming...' : 'Confirm Acknowledgement'}
                </Text>
              </TouchableOpacity>
            </View>
          )}

          <Text style={styles.warningNote}>
            ⚠ This alert cannot be dismissed without acknowledgement
          </Text>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#8B0000',
    justifyContent: 'center',
    alignItems: 'center',
  },
  pulseBackground: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: '#CC0000',
  },
  content: {
    width: '90%',
    alignItems: 'center',
    padding: 24,
    backgroundColor: 'rgba(0,0,0,0.35)',
    borderRadius: 20,
    borderWidth: 2,
    borderColor: 'rgba(255,100,100,0.6)',
  },
  alertIcon: {
    fontSize: 72,
    marginBottom: 8,
  },
  alertTitle: {
    fontSize: 32,
    fontWeight: '900',
    color: '#FFFFFF',
    letterSpacing: 3,
    textAlign: 'center',
    marginBottom: 16,
    textShadowColor: '#FF0000',
    textShadowRadius: 10,
    textShadowOffset: { width: 0, height: 0 },
  },
  tempContainer: {
    alignItems: 'center',
    marginBottom: 12,
  },
  tempLabel: {
    fontSize: 14,
    color: '#FFB3B3',
    letterSpacing: 2,
    textTransform: 'uppercase',
  },
  tempValue: {
    fontSize: 56,
    fontWeight: '900',
    color: '#FFFFFF',
  },
  alertMessage: {
    fontSize: 16,
    color: '#FFD0D0',
    textAlign: 'center',
    marginBottom: 8,
    paddingHorizontal: 8,
  },
  timestamp: {
    fontSize: 12,
    color: '#FFB3B3',
    marginBottom: 16,
  },
  divider: {
    width: '100%',
    height: 1,
    backgroundColor: 'rgba(255,255,255,0.25)',
    marginBottom: 20,
  },
  acknowledgeButton: {
    backgroundColor: '#FFFFFF',
    paddingVertical: 16,
    paddingHorizontal: 40,
    borderRadius: 12,
    marginBottom: 16,
    shadowColor: '#FF0000',
    shadowRadius: 20,
    shadowOpacity: 0.8,
    elevation: 10,
  },
  acknowledgeButtonText: {
    color: '#8B0000',
    fontSize: 18,
    fontWeight: '800',
    letterSpacing: 1,
  },
  nameInputSection: {
    width: '100%',
    alignItems: 'center',
  },
  namePrompt: {
    color: '#FFD0D0',
    fontSize: 15,
    marginBottom: 10,
  },
  nameInput: {
    width: '100%',
    backgroundColor: 'rgba(255,255,255,0.15)',
    borderRadius: 10,
    padding: 14,
    color: '#FFFFFF',
    fontSize: 16,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.4)',
    marginBottom: 8,
  },
  errorText: {
    color: '#FFD700',
    fontSize: 13,
    marginBottom: 8,
    textAlign: 'center',
  },
  confirmButton: {
    backgroundColor: '#FFFFFF',
    paddingVertical: 14,
    paddingHorizontal: 32,
    borderRadius: 12,
    marginTop: 4,
    marginBottom: 12,
  },
  confirmButtonDisabled: {
    backgroundColor: '#CCCCCC',
  },
  confirmButtonText: {
    color: '#8B0000',
    fontSize: 16,
    fontWeight: '700',
  },
  warningNote: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 12,
    textAlign: 'center',
    marginTop: 4,
  },
});

export default AlertOverlay;
