import { Audio } from 'expo-av';
import { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { tokens } from '@homepilot/ui';

import { ensureMicPermission, startRecording, stopRecording } from '../lib/audio';
import { type Persona, listPersonas } from '../lib/personas';
import {
  type VoiceServerEvent,
  type VoiceSession,
  openVoiceSession,
} from '../lib/voiceSession';

type Turn = { role: 'user' | 'assistant'; text: string; audio?: boolean };
type Status = 'connecting' | 'ready' | 'unavailable';

export default function VoiceScreen() {
  const [status, setStatus] = useState<Status>('connecting');
  const [caps, setCaps] = useState<{ tts: boolean; stt: boolean }>({ tts: false, stt: false });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [recording, setRecording] = useState(false);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [persona, setPersona] = useState<string | null>(null);
  const sessionRef = useRef<VoiceSession | null>(null);
  const recordingRef = useRef<Audio.Recording | null>(null);

  useEffect(() => {
    const session = openVoiceSession(onEvent, () => setStatus('unavailable'));
    sessionRef.current = session;
    void listPersonas().then(setPersonas);
    return () => session.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectPersona(id: string) {
    setPersona(id);
    sessionRef.current?.sendConfig(id);
  }

  function onEvent(e: VoiceServerEvent) {
    if (e.type === 'ready') {
      setStatus('ready');
      setCaps({ tts: e.tts, stt: e.stt });
    } else if (e.type === 'transcript') {
      setTurns((t) => [...t, { role: 'user', text: e.text }]);
    } else if (e.type === 'reply') {
      setTurns((t) => [...t, { role: 'assistant', text: e.text, audio: !!e.audio }]);
    } else if (e.type === 'error') {
      setStatus((s) => (s === 'connecting' ? 'unavailable' : s));
    }
  }

  async function beginRecord() {
    if (!caps.stt || recording || status !== 'ready') return;
    if (!(await ensureMicPermission())) return;
    try {
      recordingRef.current = await startRecording();
      setRecording(true);
    } catch {
      setRecording(false);
    }
  }

  async function endRecord() {
    const rec = recordingRef.current;
    recordingRef.current = null;
    setRecording(false);
    if (!rec) return;
    try {
      const clip = await stopRecording(rec);
      if (clip) sessionRef.current?.sendAudio(clip.b64, clip.format);
    } catch {
      /* ignore — a failed clip just produces no turn */
    }
  }

  function sendText() {
    const text = draft.trim();
    if (!text || status !== 'ready') return;
    setTurns((t) => [...t, { role: 'user', text }]);
    sessionRef.current?.sendText(text);
    setDraft('');
  }

  const micHint = !caps.stt ? 'Voice input coming soon' : recording ? 'Listening…' : 'Hold to talk';

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Voice</Text>
      <Text style={styles.status}>
        {status === 'connecting' && 'Connecting…'}
        {status === 'ready' && '🟢 Ready — on your own GPU'}
        {status === 'unavailable' && '⚪ Voice backend not reachable (enable it in Account → Connect)'}
      </Text>

      {personas.length > 0 ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.chips}
          contentContainerStyle={styles.chipsContent}
        >
          {personas.map((p) => (
            <Pressable
              key={p.id}
              style={[styles.chip, persona === p.id && styles.chipActive]}
              onPress={() => selectPersona(p.id)}
            >
              <Text style={[styles.chipText, persona === p.id && styles.chipTextActive]}>
                {p.label}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : null}

      <ScrollView style={styles.convo} contentContainerStyle={styles.convoContent}>
        {turns.map((t, i) => (
          <View key={i} style={[styles.bubble, t.role === 'user' ? styles.user : styles.assistant]}>
            <Text style={styles.bubbleText}>
              {t.text}
              {t.audio ? '  🔊' : ''}
            </Text>
          </View>
        ))}
      </ScrollView>

      {/* The headline control. Disabled until the server reports an STT provider
          (stt:true) — then push-to-talk activates with no other change. */}
      <View style={styles.micWrap}>
        <Pressable
          style={[styles.mic, !caps.stt && styles.micDisabled, recording && styles.micActive]}
          disabled={!caps.stt}
          onPressIn={beginRecord}
          onPressOut={endRecord}
        >
          <Text style={styles.micGlyph}>🎙️</Text>
        </Pressable>
        <Text style={styles.micHint}>{micHint}</Text>
      </View>

      {/* Text fallback — works today via the backend voice session (text mode). */}
      <View style={styles.composer}>
        <TextInput
          style={styles.input}
          placeholder="Or type a message"
          placeholderTextColor={tokens.color.muted}
          value={draft}
          onChangeText={setDraft}
          onSubmitEditing={sendText}
          editable={status === 'ready'}
          returnKeyType="send"
        />
        <Pressable
          style={[styles.send, status !== 'ready' && styles.sendDisabled]}
          onPress={sendText}
          disabled={status !== 'ready'}
        >
          <Text style={styles.sendText}>Send</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: tokens.space.md, backgroundColor: tokens.color.bg },
  title: { color: tokens.color.text, fontSize: tokens.font.size.xl, fontWeight: '700' },
  status: { color: tokens.color.muted, fontSize: tokens.font.size.sm, marginTop: tokens.space.xs, marginBottom: tokens.space.sm },
  chips: { flexGrow: 0, marginBottom: tokens.space.xs },
  chipsContent: { gap: tokens.space.xs, paddingVertical: tokens.space.xs },
  chip: {
    borderRadius: tokens.radius.pill,
    borderWidth: 1,
    borderColor: tokens.color.surface,
    backgroundColor: tokens.color.surface,
    paddingHorizontal: tokens.space.md,
    paddingVertical: tokens.space.xs,
  },
  chipActive: { borderColor: tokens.color.primary, backgroundColor: tokens.color.primary },
  chipText: { color: tokens.color.muted, fontSize: tokens.font.size.sm, fontWeight: '600' },
  chipTextActive: { color: '#fff' },
  convo: { flex: 1 },
  convoContent: { paddingVertical: tokens.space.sm },
  bubble: { borderRadius: tokens.radius.md, padding: tokens.space.md, marginVertical: tokens.space.xs, maxWidth: '88%' },
  user: { alignSelf: 'flex-end', backgroundColor: tokens.color.primary },
  assistant: { alignSelf: 'flex-start', backgroundColor: tokens.color.surface },
  bubbleText: { color: tokens.color.text, fontSize: tokens.font.size.md },
  micWrap: { alignItems: 'center', gap: tokens.space.xs, paddingVertical: tokens.space.md },
  mic: {
    width: 76,
    height: 76,
    borderRadius: 999,
    backgroundColor: tokens.color.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  micDisabled: { opacity: 0.4 },
  micActive: { backgroundColor: '#ef4444', transform: [{ scale: 1.08 }] },
  micGlyph: { fontSize: 30 },
  micHint: { color: tokens.color.muted, fontSize: tokens.font.size.sm },
  composer: { flexDirection: 'row', gap: tokens.space.sm, alignItems: 'center' },
  input: {
    flex: 1,
    backgroundColor: tokens.color.surface,
    borderRadius: tokens.radius.pill,
    color: tokens.color.text,
    fontSize: tokens.font.size.md,
    paddingHorizontal: tokens.space.md,
    paddingVertical: tokens.space.sm,
  },
  send: { backgroundColor: tokens.color.primary, borderRadius: tokens.radius.pill, paddingHorizontal: tokens.space.lg, paddingVertical: tokens.space.sm },
  sendDisabled: { opacity: 0.5 },
  sendText: { color: '#fff', fontWeight: '700', fontSize: tokens.font.size.md },
});
