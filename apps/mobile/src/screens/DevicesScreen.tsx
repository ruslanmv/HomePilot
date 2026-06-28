import { useCallback, useEffect, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';

import type { Device, SupplierPolicy } from '@homepilot/types';
import { tokens } from '@homepilot/ui';

import { getComputeClient } from '../lib/client';

type Row = { device: Device; policy: SupplierPolicy };
type ToggleField = 'allowFamily' | 'allowOrg' | 'paused';

export default function DevicesScreen() {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const compute = getComputeClient();
      const devices = await compute.listUserDevices();
      const withPolicy = await Promise.all(
        devices.map(async (device) => ({ device, policy: await compute.getDevicePolicy(device.id) })),
      );
      setRows(withPolicy);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(deviceId: string, field: ToggleField, value: boolean) {
    // Optimistic update, reconcile with the server response.
    setRows((prev) =>
      prev.map((r) => (r.device.id === deviceId ? { ...r, policy: { ...r.policy, [field]: value } } : r)),
    );
    try {
      const updated = await getComputeClient().setDevicePolicy(deviceId, {
        [field]: value,
      } as Partial<SupplierPolicy>);
      setRows((prev) => prev.map((r) => (r.device.id === deviceId ? { ...r, policy: updated } : r)));
    } catch (e) {
      setError(String(e));
      void load();
    }
  }

  return (
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={tokens.color.text} />}
    >
      <Text style={styles.title}>Devices</Text>
      <Text style={styles.muted}>
        Let your family or org use a device&apos;s GPU when you&apos;re not.
      </Text>

      {rows.length === 0 && !loading ? <Text style={styles.muted}>No paired devices yet.</Text> : null}

      {rows.map(({ device, policy }) => (
        <View key={device.id} style={styles.card}>
          <Text style={styles.name}>
            {device.name}
            {device.online ? ' · online' : ''}
          </Text>
          <Text style={styles.muted}>{device.gpuName ?? 'GPU unknown'}</Text>
          <Row label="Share with my family" value={policy.allowFamily} onChange={(v) => toggle(device.id, 'allowFamily', v)} />
          <Row label="Share with my org" value={policy.allowOrg} onChange={(v) => toggle(device.id, 'allowOrg', v)} />
          <Row label="Pause sharing" value={policy.paused} onChange={(v) => toggle(device.id, 'paused', v)} />
        </View>
      ))}

      {error ? <Text style={styles.error}>{error}</Text> : null}
    </ScrollView>
  );
}

function Row({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Switch value={value} onValueChange={onChange} trackColor={{ true: tokens.color.primary, false: tokens.color.surface }} />
    </View>
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
    gap: tokens.space.xs,
  },
  name: {
    color: tokens.color.text,
    fontSize: tokens.font.size.lg,
    fontWeight: '700',
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: tokens.space.sm,
  },
  rowLabel: {
    color: tokens.color.text,
    fontSize: tokens.font.size.md,
  },
  muted: {
    color: tokens.color.muted,
    fontSize: tokens.font.size.sm,
  },
  error: {
    color: tokens.color.danger,
    fontSize: tokens.font.size.sm,
  },
});
