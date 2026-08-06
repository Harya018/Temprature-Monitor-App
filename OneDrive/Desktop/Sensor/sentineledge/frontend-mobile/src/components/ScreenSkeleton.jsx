import React, { useEffect, useRef } from 'react';
import { View, Animated, StyleSheet } from 'react-native';

const SkeletonBlock = ({ style }) => {
  const opacity = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.65, duration: 850, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.3,  duration: 850, useNativeDriver: true }),
      ])
    ).start();
  }, [opacity]);

  return <Animated.View style={[styles.block, style, { opacity }]} />;
};

export const DashboardSkeleton = () => (
  <View style={styles.container}>
    {/* Header row */}
    <View style={styles.headerRow}>
      <View>
        <SkeletonBlock style={{ width: 140, height: 22, borderRadius: 6, marginBottom: 8 }} />
        <SkeletonBlock style={{ width: 100, height: 13, borderRadius: 4 }} />
      </View>
      <SkeletonBlock style={{ width: 82, height: 34, borderRadius: 17 }} />
    </View>

    {/* Temperature section */}
    <SkeletonBlock style={styles.tempBlock} />

    {/* Cards row */}
    <View style={styles.cardsRow}>
      <SkeletonBlock style={styles.card} />
      <SkeletonBlock style={styles.card} />
      <SkeletonBlock style={styles.card} />
    </View>

    {/* Threshold card */}
    <SkeletonBlock style={styles.thresholdBlock} />
  </View>
);

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: 20,
    paddingTop: 16,
  },
  block: {
    backgroundColor: 'rgba(255,255,255,0.15)',
    borderRadius: 8,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 32,
  },
  tempBlock: {
    height: 196,
    borderRadius: 24,
    marginBottom: 20,
  },
  cardsRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 20,
  },
  card: {
    flex: 1,
    height: 92,
    borderRadius: 16,
  },
  thresholdBlock: {
    height: 122,
    borderRadius: 16,
  },
});
