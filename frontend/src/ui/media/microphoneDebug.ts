export type MicrophoneDebugScope = 'settings' | 'chat' | 'voice' | 'vad' | 'speech-service';

export interface MicrophoneDebugEntry {
  seq: number;
  at: string;
  scope: MicrophoneDebugScope;
  event: string;
  details?: Record<string, unknown>;
}

declare global {
  interface Window {
    /**
     * Small in-memory ring buffer for microphone diagnostics.
     *
     * It intentionally contains metadata only — no audio bytes and no recognized transcript.
     * A user can inspect it in DevTools after reproducing a microphone problem:
     *   window.__HOMEPILOT_MIC_DEBUG__
     */
    __HOMEPILOT_MIC_DEBUG__?: MicrophoneDebugEntry[];
  }
}

const MAX_ENTRIES = 200;
let sequence = 0;

function safeDetails(details?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (!details) return undefined;
  const next: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(details)) {
    if (value instanceof Error) {
      next[key] = { name: value.name, message: value.message };
    } else {
      next[key] = value;
    }
  }
  return next;
}

/**
 * Emit one structured microphone trace.
 *
 * Keep this deliberately boring and grep-friendly. The exact prefix is shared by Settings,
 * chat, Voice, VAD and the browser SpeechService so one DevTools filter shows the complete
 * capture lifecycle in order.
 */
export function microphoneDebug(
  scope: MicrophoneDebugScope,
  event: string,
  details?: Record<string, unknown>,
): MicrophoneDebugEntry {
  const entry: MicrophoneDebugEntry = {
    seq: ++sequence,
    at: new Date().toISOString(),
    scope,
    event,
    details: safeDetails(details),
  };

  if (typeof window !== 'undefined') {
    const history = window.__HOMEPILOT_MIC_DEBUG__ || [];
    history.push(entry);
    if (history.length > MAX_ENTRIES) history.splice(0, history.length - MAX_ENTRIES);
    window.__HOMEPILOT_MIC_DEBUG__ = history;
    try {
      window.dispatchEvent(new CustomEvent('homepilot:microphone-debug', { detail: entry }));
    } catch {
      // Diagnostics must never interfere with microphone capture.
    }
  }

  console.info(`[HomePilot:Mic][${scope}] ${event}`, entry.details || {});
  return entry;
}

export function microphoneDebugError(
  scope: MicrophoneDebugScope,
  event: string,
  error: unknown,
  details?: Record<string, unknown>,
): MicrophoneDebugEntry {
  const err = error as { name?: string; message?: string } | null;
  const payload = {
    ...details,
    errorName: err?.name || 'Error',
    errorMessage: err?.message || String(error || 'Unknown microphone error'),
  };
  const entry = microphoneDebug(scope, event, payload);
  console.error(`[HomePilot:Mic][${scope}] ${event}`, payload);
  return entry;
}
