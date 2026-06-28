import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { tokens } from '@homepilot/ui';

import { signIn } from '../lib/auth';
import { DEFAULT_CLOUD_URL, getBaseUrl, setBaseUrl } from '../lib/client';
import { type ConnectResult, linkWithToken, testConnection } from '../lib/pairing';
import { getStoredBaseUrl, secureTokenStorage, setStoredBaseUrl } from '../lib/storage';

export default function AccountScreen() {
  const [url, setUrl] = useState(DEFAULT_CLOUD_URL);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [token, setToken] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<ConnectResult | null>(null);
  const [signedIn, setSignedIn] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const storedUrl = await getStoredBaseUrl();
      if (storedUrl) {
        setUrl(storedUrl);
        setBaseUrl(storedUrl);
      } else if (getBaseUrl() && getBaseUrl() !== 'http://localhost:8000') {
        setUrl(getBaseUrl());
      }
      const storedKey = await secureTokenStorage.get();
      if (storedKey) setToken(storedKey);
    })();
  }, []);

  async function doSignIn() {
    setBusy(true);
    setStatus(null);
    try {
      const { email: e } = await signIn(email, password, url);
      setSignedIn(e);
      setPassword('');
      setStatus(await testConnection(url));
    } catch (err) {
      setStatus({ reachable: true, authed: false, detail: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function connectWithToken() {
    setBusy(true);
    setStatus(null);
    try {
      await linkWithToken(token, url);
      setStatus(await testConnection(url, token));
    } finally {
      setBusy(false);
    }
  }

  const statusColor = !status
    ? tokens.color.muted
    : status.authed === true
      ? '#22c55e'
      : status.authed === false || !status.reachable
        ? '#ef4444'
        : tokens.color.muted;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Account</Text>
      {signedIn ? (
        <Text style={styles.subtitle}>Signed in as {signedIn}</Text>
      ) : (
        <Text style={styles.subtitle}>Sign in to use your GPU from anywhere.</Text>
      )}

      <Text style={styles.field}>Email</Text>
      <TextInput
        style={styles.input}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        placeholder="you@example.com"
        placeholderTextColor={tokens.color.muted}
        value={email}
        onChangeText={setEmail}
      />
      <Text style={styles.field}>Password</Text>
      <TextInput
        style={styles.input}
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry
        placeholder="••••••••"
        placeholderTextColor={tokens.color.muted}
        value={password}
        onChangeText={setPassword}
        onSubmitEditing={doSignIn}
      />

      <Pressable style={[styles.button, busy && styles.buttonDisabled]} onPress={doSignIn} disabled={busy}>
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Sign in</Text>}
      </Pressable>
      <Text style={styles.helper}>No account? Create one at the OllaBridge Cloud website.</Text>

      {status ? <Text style={[styles.status, { color: statusColor }]}>{status.detail}</Text> : null}

      <Pressable onPress={() => setShowAdvanced((v) => !v)} hitSlop={8}>
        <Text style={styles.advancedToggle}>{showAdvanced ? '▾ Advanced' : '▸ Advanced (token / URL)'}</Text>
      </Pressable>
      {showAdvanced ? (
        <>
          <Text style={styles.field}>Backend URL</Text>
          <TextInput
            style={styles.input}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            placeholder={DEFAULT_CLOUD_URL}
            placeholderTextColor={tokens.color.muted}
            value={url}
            onChangeText={setUrl}
          />
          <Text style={styles.field}>Access token</Text>
          <TextInput
            style={styles.input}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
            placeholder="Paste a Cloud access token"
            placeholderTextColor={tokens.color.muted}
            value={token}
            onChangeText={setToken}
          />
          <Pressable style={[styles.buttonOutline, busy && styles.buttonDisabled]} onPress={connectWithToken} disabled={busy}>
            <Text style={styles.buttonOutlineText}>Connect with token</Text>
          </Pressable>
        </>
      ) : null}

      <Text style={styles.hint}>
        Stored securely in the device keychain. Generation runs on whatever GPU your
        account routes to — your own PC, or a cloud GPU.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: tokens.space.lg, gap: tokens.space.sm },
  title: { color: tokens.color.text, fontSize: tokens.font.size.xl, fontWeight: '700' },
  subtitle: { color: tokens.color.muted, fontSize: tokens.font.size.sm, marginBottom: tokens.space.sm },
  field: { color: tokens.color.muted, fontSize: tokens.font.size.sm, marginTop: tokens.space.sm },
  input: {
    backgroundColor: tokens.color.surface,
    borderRadius: tokens.radius.md,
    color: tokens.color.text,
    fontSize: tokens.font.size.md,
    padding: tokens.space.md,
  },
  helper: { color: tokens.color.muted, fontSize: tokens.font.size.sm },
  advancedToggle: { color: tokens.color.primary, fontSize: tokens.font.size.sm, marginTop: tokens.space.md },
  button: {
    backgroundColor: tokens.color.primary,
    borderRadius: tokens.radius.pill,
    paddingVertical: tokens.space.md,
    alignItems: 'center',
    marginTop: tokens.space.md,
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: '#fff', fontSize: tokens.font.size.md, fontWeight: '700' },
  buttonOutline: {
    borderColor: tokens.color.primary,
    borderWidth: 1,
    borderRadius: tokens.radius.pill,
    paddingVertical: tokens.space.sm,
    alignItems: 'center',
    marginTop: tokens.space.sm,
  },
  buttonOutlineText: { color: tokens.color.primary, fontSize: tokens.font.size.md, fontWeight: '700' },
  status: { fontSize: tokens.font.size.sm, marginTop: tokens.space.sm, fontWeight: '600' },
  hint: { color: tokens.color.muted, fontSize: tokens.font.size.sm, marginTop: tokens.space.md },
});
