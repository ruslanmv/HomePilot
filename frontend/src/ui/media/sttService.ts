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

import { setRecommendedSttDefault } from './sttPreferences';
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
  /** The server's suggestion for someone who has not chosen ("homepilot" on the web edition). */
  recommended?: 'homepilot' | null;
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
      recommended: body?.recommended_engine === 'homepilot' ? 'homepilot' : null,
    };
    // The hosted web edition recommends its own model to anyone who has not chosen.
    setRecommendedSttDefault(body?.recommended_engine === 'homepilot' && value.available ? 'homepilot' : null);
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

    // 503 is "no provider configured"; 502 is "the provider itself failed" — a model that
    // cannot load, a missing ffmpeg. They are different server-side facts and the same
    // client-side one: the backend cannot transcribe this turn, so fall back rather than
    // leave the user with a microphone button that does nothing.
    //
    // The cached capability is dropped either way, so the next turn re-probes instead of
    // being stuck on the fallback for the rest of the session. A server that recovers —
    // Whisper reloading on CPU after an unusable CUDA install, say — is picked straight
    // back up.
    if (response.status === 503 || response.status === 502) {
      resetSttCapabilityCache();
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
  /**
   * End the turn by itself: after speech, once the input has been quiet for ``silenceMs``;
   * with no speech at all, after ``noSpeechMs``. The threshold adapts to the room — it is
   * set from the noise heard in the first half second — so a fan does not count as speech.
   * Without it the recording runs until stopped or ``maxMs``, which is what the browser
   * recognizer's own end-of-speech used to spare people.
   */
  endOnSilence?: { silenceMs?: number; noSpeechMs?: number };
}

export type EndOfTurn = 'silence-after-speech' | 'no-speech';

/**
 * End-of-speech from a stream of 0..1 input levels (see ``endOnSilence``). The first half
 * second sets the room's noise floor; speech is anything clearly above it. Calls ``onEnd``
 * once: after speech followed by ``silenceMs`` of quiet, or after ``noSpeechMs`` of nothing.
 */
export function silenceWatcher(
  options: { silenceMs?: number; noSpeechMs?: number },
  onEnd: (why: EndOfTurn) => void,
  now: () => number = () => performance.now(),
): (level: number) => void {
  const silenceMs = options.silenceMs ?? 1200;
  const noSpeechMs = options.noSpeechMs ?? 8000;
  const startedAt = now();
  let noiseFloor = 1, heardSpeech = false, quietSince = 0, ended = false;
  return (level: number) => {
    if (ended) return;
    const t = now();
    const elapsed = t - startedAt;
    if (elapsed < 500) { noiseFloor = Math.min(noiseFloor, level); return; }
    const threshold = Math.max(0.05, Math.min(0.3, noiseFloor * 2.5));
    if (level > threshold) { heardSpeech = true; quietSince = 0; return; }
    if (!quietSince) quietSince = t;
    if (heardSpeech && t - quietSince >= silenceMs) { ended = true; onEnd('silence-after-speech'); }
    else if (!heardSpeech && elapsed >= noSpeechMs) { ended = true; onEnd('no-speech'); }
  };
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

  // Where the turn ends by itself (endOnSilence): fed by the same level meter.
  let onTurnEnd: ((why: EndOfTurn) => void) | null = null;
  const watchSilence = options.endOnSilence
    ? silenceWatcher(options.endOnSilence, (why) => onTurnEnd?.(why))
    : () => {};

  if (options.onLevel || options.endOnSilence) {
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
          const level = Math.min(1, Math.sqrt(sum / data.length) * 4.5);
          options.onLevel?.(level);
          watchSilence(level);
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
    onTurnEnd = (why) => {
      onTurnEnd = null;
      microphoneDebug(scope, 'stt_recorder_end_of_speech', { why, elapsedMs: Math.round(performance.now() - startedAt) });
      stop();
    };

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
