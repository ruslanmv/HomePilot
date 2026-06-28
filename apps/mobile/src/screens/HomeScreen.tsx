import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { ComputeStatus } from '@homepilot/types';
import { tokens } from '@homepilot/ui';

import { getComputeClient } from '../lib/client';

export default function HomeScreen() {
  const [status, setStatus] = useState<ComputeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStatus(await getComputeClient().getComputeStatus());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={
        <RefreshControl refreshing={loading} onRefresh={load} tintColor={tokens.color.text} />
      }
    >
      <Text style={styles.title}>HomePilot</Text>

      {loading && !status ? <ActivityIndicator color={tokens.color.primary} /> : null}

      {status ? (
        <View style={styles.card}>
          <Text style={styles.label}>{status.label}</Text>
          <Text style={styles.message}>{status.message}</Text>
        </View>
      ) : null}

      {error ? (
        <Text style={styles.error}>
          Can&apos;t reach the backend. Set its address in the Account tab.
        </Text>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    padding: tokens.space.lg,
    gap: tokens.space.md,
  },
  title: {
    color: tokens.color.text,
    fontSize: tokens.font.size.xl,
    fontWeight: '700',
  },
  card: {
    backgroundColor: tokens.color.surface,
    borderRadius: tokens.radius.md,
    padding: tokens.space.lg,
    gap: tokens.space.sm,
  },
  label: {
    color: tokens.color.primary,
    fontSize: tokens.font.size.md,
    fontWeight: '700',
  },
  message: {
    color: tokens.color.text,
    fontSize: tokens.font.size.md,
  },
  error: {
    color: tokens.color.danger,
    fontSize: tokens.font.size.sm,
  },
});
