import { useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import type { Job } from '@homepilot/types';
import { tokens } from '@homepilot/ui';

import { getComputeClient, toAbsoluteUrl } from '../lib/client';
import { sseEventTransport } from '../lib/eventTransport';

const TERMINAL = new Set(['succeeded', 'failed', 'canceled']);

export default function ImagineScreen() {
  const [prompt, setPrompt] = useState('');
  const [job, setJob] = useState<Job | null>(null);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    setJob(null);
    setProgress(0);
    const compute = getComputeClient();
    try {
      const created = await compute.createImageJob({ prompt });
      // Stream progress over SSE; on a terminal event fetch the final job.
      await new Promise<void>((resolve) => {
        const unsubscribe = compute.subscribeToJobEvents(
          created.id,
          (event) => {
            if (typeof event.progress === 'number') setProgress(event.progress);
            if (event.kind && TERMINAL.has(event.kind)) {
              unsubscribe();
              compute
                .getJobStatus(created.id)
                .then(setJob)
                .catch((e) => setError(String(e)))
                .finally(() => resolve());
            }
          },
          sseEventTransport,
        );
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const artifact = job?.output?.artifacts?.[0];
  const imageUri = artifact ? toAbsoluteUrl(artifact.url) : null;

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.input}
        placeholder="Describe an image…"
        placeholderTextColor={tokens.color.muted}
        value={prompt}
        onChangeText={setPrompt}
        editable={!busy}
      />
      <Pressable
        style={[styles.button, (busy || !prompt) && styles.buttonDisabled]}
        onPress={run}
        disabled={busy || !prompt}
      >
        <Text style={styles.buttonText}>{busy ? `Generating… ${progress}%` : 'Imagine'}</Text>
      </Pressable>

      {busy ? <ActivityIndicator color={tokens.color.primary} style={styles.spinner} /> : null}
      {imageUri ? <Image source={{ uri: imageUri }} style={styles.image} resizeMode="contain" /> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: tokens.space.lg,
    gap: tokens.space.md,
  },
  input: {
    backgroundColor: tokens.color.surface,
    borderRadius: tokens.radius.md,
    color: tokens.color.text,
    fontSize: tokens.font.size.md,
    padding: tokens.space.md,
  },
  button: {
    backgroundColor: tokens.color.primary,
    borderRadius: tokens.radius.pill,
    paddingVertical: tokens.space.md,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  buttonText: {
    color: '#fff',
    fontSize: tokens.font.size.md,
    fontWeight: '700',
  },
  spinner: {
    marginTop: tokens.space.sm,
  },
  image: {
    flex: 1,
    width: '100%',
    borderRadius: tokens.radius.md,
    backgroundColor: tokens.color.surface,
  },
  error: {
    color: tokens.color.danger,
    fontSize: tokens.font.size.sm,
  },
});
