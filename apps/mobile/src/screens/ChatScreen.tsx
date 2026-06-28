import { useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { tokens } from '@homepilot/ui';

import { type ChatMessage, sendChat } from '../lib/chat';

export default function ChatScreen() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<FlatList<ChatMessage>>(null);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    const next: ChatMessage[] = [...messages, { role: 'user', content: text }];
    setMessages(next);
    setDraft('');
    setError(null);
    setBusy(true);
    try {
      const reply = await sendChat(next);
      setMessages([...next, { role: 'assistant', content: reply || '…' }]);
    } catch (e) {
      setError('Could not reach the assistant. Check Account → Connect.');
      setMessages(next);
    } finally {
      setBusy(false);
      requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Text style={styles.title}>Chat</Text>

      {messages.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyText}>Ask anything — it runs on your own GPU.</Text>
        </View>
      ) : (
        <FlatList
          ref={listRef}
          style={styles.list}
          data={messages}
          keyExtractor={(_, i) => String(i)}
          renderItem={({ item }) => (
            <View style={[styles.bubble, item.role === 'user' ? styles.user : styles.assistant]}>
              <Text style={styles.bubbleText}>{item.content}</Text>
            </View>
          )}
          onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
        />
      )}

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <View style={styles.composer}>
        <TextInput
          style={styles.input}
          placeholder="Message"
          placeholderTextColor={tokens.color.muted}
          value={draft}
          onChangeText={setDraft}
          onSubmitEditing={send}
          editable={!busy}
          returnKeyType="send"
        />
        <Pressable style={[styles.send, busy && styles.sendDisabled]} onPress={send} disabled={busy}>
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.sendText}>Send</Text>}
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: tokens.space.md, backgroundColor: tokens.color.bg },
  title: { color: tokens.color.text, fontSize: tokens.font.size.xl, fontWeight: '700', marginBottom: tokens.space.sm },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  emptyText: { color: tokens.color.muted, fontSize: tokens.font.size.md },
  list: { flex: 1 },
  bubble: { borderRadius: tokens.radius.md, padding: tokens.space.md, marginVertical: tokens.space.xs, maxWidth: '88%' },
  user: { alignSelf: 'flex-end', backgroundColor: tokens.color.primary },
  assistant: { alignSelf: 'flex-start', backgroundColor: tokens.color.surface },
  bubbleText: { color: tokens.color.text, fontSize: tokens.font.size.md },
  error: { color: '#ef4444', fontSize: tokens.font.size.sm, marginVertical: tokens.space.xs },
  composer: { flexDirection: 'row', gap: tokens.space.sm, alignItems: 'center', paddingTop: tokens.space.sm },
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
  sendDisabled: { opacity: 0.6 },
  sendText: { color: '#fff', fontWeight: '700', fontSize: tokens.font.size.md },
});
