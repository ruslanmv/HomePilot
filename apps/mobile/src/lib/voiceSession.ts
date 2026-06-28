// MB3 — thin client for the MB2 backend voice session (WS /v1/voice/session).
// The server does the work (STT→LLM→TTS); the client just sends utterances and
// renders frames. Text mode works today; speech-in activates with no client
// change once the server reports `stt:true` (a backend STT provider). Audio
// playback (TTS) lands when a TTS engine is configured server-side.
import { getBaseUrl } from './client';

export type VoiceServerEvent =
  | { type: 'ready'; tts: boolean; stt: boolean }
  | { type: 'transcript'; text: string }
  | { type: 'configured'; persona_id: string | null; label: string | null }
  | { type: 'reply'; text: string; audio?: { format: string; data_b64: string } }
  | { type: 'interrupted' }
  | { type: 'pong' }
  | { type: 'error'; error: string };

export interface VoiceSession {
  sendText(text: string): void;
  /** push-to-talk: send a recorded clip for server-side transcription */
  sendAudio(b64: string, format: string): void;
  /** pick a persona/voice companion (MB4) */
  sendConfig(personaId: string): void;
  interrupt(): void;
  close(): void;
}

function wsUrl(base: string): string {
  return base.replace(/^http/i, 'ws').replace(/\/+$/, '') + '/v1/voice/session';
}

/** Open a voice session. `onEvent` receives server frames; `onClose` fires when
 *  the socket ends (unreachable backend, server disabled, or normal close). */
export function openVoiceSession(
  onEvent: (e: VoiceServerEvent) => void,
  onClose?: (reason: string) => void,
): VoiceSession {
  const ws = new WebSocket(wsUrl(getBaseUrl()));

  ws.onmessage = (e) => {
    try {
      onEvent(JSON.parse(String((e as { data: unknown }).data)) as VoiceServerEvent);
    } catch {
      /* ignore a malformed frame */
    }
  };
  ws.onerror = () => onClose?.('connection error');
  ws.onclose = () => onClose?.('closed');

  const send = (payload: unknown) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  };

  return {
    sendText: (text: string) => send({ type: 'text', text }),
    sendAudio: (b64: string, format: string) => send({ type: 'audio', format, data_b64: b64 }),
    sendConfig: (personaId: string) => send({ type: 'config', persona_id: personaId }),
    interrupt: () => send({ type: 'interrupt' }),
    close: () => ws.close(),
  };
}
