/**
 * One transcription path for the microphone the user actually selected.
 *
 * The problem this replaces
 * -------------------------
 * HomePilot had two microphone consumers that could not agree on a device:
 *
 *   - The VAD (and the Settings recording test) open `getUserMedia` with the
 *     `deviceId` chosen in Settings → Audio & Video.
 *   - The browser's `SpeechRecognition` accepts no `deviceId` at all. It always
 *     records the operating system's default input.
 *
 * When those are different microphones the level meter moves while a device
 * nobody is speaking into gets transcribed — and the browser reports no error,
 * so the turn just ends empty.
 *
 * What this does instead
 * ----------------------
 * Record the selected device with `MediaRecorder`, post the clip to HomePilot's
 * own `POST /v1/voice/transcribe`, and return the text. The bytes transcribed
 * are by construction the bytes captured from the selected input, so the split
 * cannot happen.
 *
 * Native Web Speech is kept only as a fallback for when backend speech-to-text
 * is unavailable (`GET /v1/voice/stt/status` reports `available: false`), which
 * is a real configuration — no local Whisper installed and no `STT_BASE_URL`.
 * In that mode the device caveat still applies, and callers are told so through
 * `engine: 'web-speech'` rather than left to assume.
 */

import { resolveBackendUrl } from '../lib/backendUrl';
import {
  buildAudioConstraints,
  getMediaPreferences,
  isDeviceSelectionError,
} from './mediaPreferences';
import { microphoneDebug, microphoneDebugError } from './microphoneDebug';

export type SttEngine = 'homepilot-backend' | 'web-speech';

export interface SttCapability {
  available: boolean;
  provider: string | null;
  /** True when the recording leaves this machine for a remote endpoint. */
  remote: boolean;
  hint: string | null;
}

export interface SttRecordingResult {
  text: string;
  engine: SttEngine;
  provider: string | null;
  remote: boolean;
  /** Label of the device actually captured, for the UI to show back. */
  deviceLabel: string;
  bytes: number;
  elapsedMs: number;
}

export class SttUnavailableError extends Error {
  constructor(message: string, readonly capability: SttCapability | null = null) {
    super(message);
    this.name = 'SttUnavailableError';
  }
}

const CAPABILITY_TTL_MS = 30_000;
let cachedCapability: { at: number; value: SttCapability } | null = null;

function endpoint(path: string): string {
  return `${resolveBackendUrl().replace(/\/+$/, '')}${path}`;
}

/**
 * Whether the server can transcribe, cached briefly.
 *
 * Cached because every voice turn would otherwise pay a round trip to learn
 * something that changes only when an operator edits configuration; short
 * enough that installing local speech is picked up without a reload.
 */
export async function getSttCapability(options: { force?: boolean } = {}): Promise<SttCapability> {
  if (!options.force && cachedCapability && Date.now() - cachedCapability.at < CAPABILITY_TTL_MS) {
    return cachedCapability.value;
  }

  const fallback: SttCapability = {
    available: false,
    provider: null,
    remote: false,
    hint: 'HomePilot speech-to-text could not be reached.',
  };

  try {
    const response = await fetch(endpoint('/v1/voice/stt/status'), {
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      microphoneDebug('settings', 'stt_capability_http_error', { status: response.status });
      cachedCapability = { at: Date.now(), value: fallback };
      return fallback;
    }
    const body = await response.json();
    const value: SttCapability = {
      available: Boolean(body?.available),
      provider: typeof body?.provider === 'string' ? body.provider : null,
      remote: Boolean(body?.remote),
      hint: typeof body?.hint === 'string' ? body.hint : null,
    };
    microphoneDebug('settings', 'stt_capability', value as unknown as Record<string, unknown>);
    cachedCapability = { at: Date.now(), value };
    return value;
  } catch (error) {
    microphoneDebugError('settings', 'stt_capability_failed', error);
    cachedCapability = { at: Date.now(), value: fallback };
    return fallback;
  }
}

/** Forget the cached capability, e.g. after the user changes the backend URL. */
export function resetSttCapabilityCache(): void {
  cachedCapability = null;
}

/**
 * Open the selected microphone, honouring the Audio & Video preferences and
 * falling back to the system default when the saved device has gone away.
 */
export async function openSelectedMicrophone(
  scope: 'chat' | 'voice' | 'settings' = 'settings',
): Promise<MediaStream> {
  const preferences = getMediaPreferences();
  const constraints = buildAudioConstraints(preferences);
  microphoneDebug(scope, 'stt_capture_request', {
    selectedDeviceId: preferences.microphoneDeviceId || 'system-default',
    constraints,
  });

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: false, audio: constraints });
  } catch (error) {
    if (!preferences.microphoneDeviceId || !isDeviceSelectionError(error)) throw error;
    microphoneDebugError(scope, 'stt_selected_device_unavailable_fallback_default', error, {
      selectedDeviceId: preferences.microphoneDeviceId,
    });
    stream = await navigator.mediaDevices.getUserMedia({
      video: false,
      audio: buildAudioConstraints(preferences, { ignoreDeviceId: true }),
    });
  }

  const track = stream.getAudioTracks()[0];
  if (!track || track.readyState !== 'live') {
    stream.getTracks().forEach((t) => t.stop());
    throw new Error('No live microphone track was returned.');
  }

  microphoneDebug(scope, 'stt_capture_opened', {
    label: track.label || 'unlabelled microphone',
    deviceId: track.getSettings().deviceId || 'browser-default',
    readyState: track.readyState,
  });
  return stream;
}

/** Send one recorded clip to HomePilot for transcription. */
export async function transcribeBlob(
  blob: Blob,
  scope: 'chat' | 'voice' | 'settings' = 'settings',
): Promise<{ text: string; provider: string | null; remote: boolean; elapsedMs: number }> {
  const form = new FormData();
  // The server derives the container from this MIME type, because MediaRecorder
  // picks its own per browser (webm on Chromium, mp4 on Safari).
  form.append('audio', blob, 'recording');
  if (blob.type) form.append('format', blob.type.split(';')[0].split('/').pop() || '');

  microphoneDebug(scope, 'stt_transcribe_request', { bytes: blob.size, mimeType: blob.type });

  const response = await fetch(endpoint('/v1/voice/transcribe'), { method: 'POST', body: form });
  const body = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = body?.detail;
    const message =
      (typeof detail === 'object' && detail && (detail.hint || detail.error)) ||
      (typeof detail === 'string' ? detail : null) ||
      `Transcription failed with HTTP ${response.status}.`;
    microphoneDebug(scope, 'stt_transcribe_rejected', {
      status: response.status,
      // The message is a server hint, never transcript text.
      message,
    });
    if (response.status === 503) {
      throw new SttUnavailableError(String(message), detail?.capability ?? null);
    }
    throw new Error(String(message));
  }

  const text = typeof body?.text === 'string' ? body.text.trim() : '';
  microphoneDebug(scope, 'stt_transcribe_result', {
    characters: text.length,
    provider: body?.provider ?? null,
    remote: Boolean(body?.remote),
    elapsedMs: body?.elapsed_ms ?? null,
  });

  return {
    text,
    provider: body?.provider ?? null,
    remote: Boolean(body?.remote),
    elapsedMs: Number(body?.elapsed_ms) || 0,
  };
}

export interface RecordAndTranscribeOptions {
  /** Hard stop for the recording. */
  maxMs?: number;
  scope?: 'chat' | 'voice' | 'settings';
  /** Called once capture is live, with the device label and a stop function. */
  onRecording?: (info: { deviceLabel: string; stop: () => void }) => void;
  /** Called with the smoothed 0..1 input level while recording. */
  onLevel?: (level: number) => void;
}

/**
 * Record the selected microphone until stopped, then transcribe it.
 *
 * Resolves with empty `text` when the clip contained no speech: that is a
 * successful transcription of silence and a different fact from a failure,
 * which is exactly the distinction the old path could not report.
 */
export async function recordAndTranscribe(
  options: RecordAndTranscribeOptions = {},
): Promise<SttRecordingResult> {
  const { maxMs = 15_000, scope = 'settings' } = options;

  if (typeof MediaRecorder === 'undefined') {
    throw new Error('This browser cannot record audio because MediaRecorder is unavailable.');
  }

  const stream = await openSelectedMicrophone(scope);
  const track = stream.getAudioTracks()[0];
  const deviceLabel = track.label || 'the selected microphone';

  let audioContext: AudioContext | null = null;
  let levelFrame = 0;
  const releaseLevels = () => {
    if (levelFrame) cancelAnimationFrame(levelFrame);
    levelFrame = 0;
    if (audioContext && audioContext.state !== 'closed') audioContext.close().catch(() => {});
    audioContext = null;
  };

  if (options.onLevel) {
    try {
      const Ctor =
        window.AudioContext ||
        (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Ctor) {
        audioContext = new Ctor();
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.65;
        audioContext.createMediaStreamSource(stream).connect(analyser);
        const data = new Uint8Array(analyser.fftSize);
        const read = () => {
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i += 1) {
            const sample = (data[i] - 128) / 128;
            sum += sample * sample;
          }
          options.onLevel?.(Math.min(1, Math.sqrt(sum / data.length) * 4.5));
          levelFrame = requestAnimationFrame(read);
        };
        read();
      }
    } catch {
      // A missing level meter must never stop a transcription.
    }
  }

  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  const startedAt = performance.now();

  const blob = await new Promise<Blob>((resolve, reject) => {
    let stopTimer: ReturnType<typeof setTimeout> | null = null;

    const cleanup = () => {
      if (stopTimer) clearTimeout(stopTimer);
      stopTimer = null;
      releaseLevels();
      stream.getTracks().forEach((t) => t.stop());
    };

    const stop = () => {
      if (recorder.state !== 'inactive') {
        try { recorder.stop(); } catch { /* already stopping */ }
      }
    };

    recorder.ondataavailable = (event) => {
      if (event.data?.size) chunks.push(event.data);
    };
    recorder.onerror = (event) => {
      cleanup();
      reject((event as Event & { error?: DOMException }).error || new Error('Recording failed.'));
    };
    recorder.onstop = () => {
      cleanup();
      resolve(new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || 'audio/webm' }));
    };

    recorder.start(250);
    microphoneDebug(scope, 'stt_recorder_started', {
      mimeType: recorder.mimeType || 'browser-selected',
      label: deviceLabel,
      maxMs,
    });

    stopTimer = setTimeout(() => {
      microphoneDebug(scope, 'stt_recorder_auto_stop', { maxMs });
      stop();
    }, maxMs);

    options.onRecording?.({ deviceLabel, stop });
  });

  options.onLevel?.(0);

  if (!blob.size) {
    microphoneDebug(scope, 'stt_recording_empty', {
      elapsedMs: Math.round(performance.now() - startedAt),
    });
    throw new Error(
      'The browser returned an empty recording. Check the selected microphone in Audio & Video.',
    );
  }

  const transcription = await transcribeBlob(blob, scope);
  return {
    text: transcription.text,
    engine: 'homepilot-backend',
    provider: transcription.provider,
    remote: transcription.remote,
    deviceLabel,
    bytes: blob.size,
    elapsedMs: Math.round(performance.now() - startedAt),
  };
}
