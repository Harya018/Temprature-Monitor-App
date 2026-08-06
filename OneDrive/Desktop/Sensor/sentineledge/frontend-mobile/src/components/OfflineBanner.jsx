// ─────────────────────────────────────────────
//  SentinelEdge — Offline Banner
//  Polls device network state via expo-network and
//  shows a red banner when the device has no internet.
//
//  Requires: npx expo install expo-network
// ─────────────────────────────────────────────
import React, { useState, useEffect } from 'react';
import { Animated, Text, StyleSheet, View, useRef } from 'react-native';
import * as Network from 'expo-network';

export default function OfflineBanner() {
  const [isOnline, setIsOnline] = useState(true);
  const fadeAnim = React.useRef(new Animated.Value(0)).current;

  useEffect(() => {
    let mounted = true;

    const check = async () => {
      try {
        const state = await Network.getNetworkStateAsync();
        if (mounted) {
          setIsOnline(state.isConnected && state.isInternetReachable !== false);
        }
      } catch {
        // ignore — stay optimistic
      }
    };

    check();
    const interval = setInterval(check, 8000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  useEffect(() => {
    Animated.timing(fadeAnim, {
      toValue: isOnline ? 0 : 1,
      duration: 350,
      useNativeDriver: true,
    }).start();
  }, [isOnline, fadeAnim]);

  return (
    <Animated.View
      style={[styles.banner, { opacity: fadeAnim }]}
      pointerEvents={isOnline ? 'none' : 'auto'}
    >
      <View style={styles.dot} />
      <Text style={styles.text}>No internet connection</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  banner: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 999,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#EF4444',
    paddingVertical: 8,
    paddingHorizontal: 16,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#FCA5A5',
    marginRight: 8,
  },
  text: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
});
