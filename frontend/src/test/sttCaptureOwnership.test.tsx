/**
 * Hands-free Voice opens one capture, and it is the one the engine says.
 *
 * ── The bug ──────────────────────────────────────────────────────────────────────────────
 *
 * Hands-free used to start HomePilot's VAD unconditionally. The VAD opens — and holds, for
 * the whole session — the microphone selected in Audio & Video. On the browser engine it then
 * asked `SpeechRecognition` to transcribe the turn, and that opens *its own* capture on the
 * operating system's default input, because the Web Speech API takes no `deviceId` and
 * accepts no `MediaStream`. The trace looked like this, every turn:
 *
 *     [vad]   capture_opened
 *     [voice] stt_onstart
 *     [voice] stt_onend { hadResult: false, sawSpeechStart: false }
 *
 * The meter moved, the orb reacted, and nothing came out — because the recognizer was never
 * listening to the microphone the meter was reading. No warm-up window or stop-deferral could
 * have fixed it.
 *
 * These two tests are the fix stated as a property: on the browser engine HomePilot opens no
 * microphone at all, and on the local engine it starts no recognizer.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const capability = vi.fn();

vi.mock('../ui/media/sttService', () => ({
  getSttCapability: () => capability(),
  transcribeBlob: vi.fn(),
  openSelectedMicrophone: vi.fn(),
  resetSttCapabilityCache: vi.fn(),
  recordAndTranscribe: vi.fn(),
  SttUnavailableError: class SttUnavailableError extends Error {},
}));

import { useVoiceController } from '../ui/voice/useVoiceController';
import { resetSttRuntimeForTests } from '../ui/media/sttRuntime';
import { resetWebSpeechForTests } from '../ui/media/webSpeechSession';

const getUserMedia = vi.fn();
const startSTT = vi.fn(() => true);

type Callbacks = {
  onStart?: () => void;
  onEnd?: (diagnostics: Record<string, unknown>) => void;
  onInterim?: (text: string) => void;
  onResult?: (text: string) => void;
  onError?: (code: string) => void;
};

/** Whatever the one adapter installed on the shared recognizer. */
let callbacks: Callbacks = {};

/** Just enough Web Audio for the VAD to reach its first frame. */
function stubAudioContext() {
  class FakeAnalyser {
    fftSize = 1024;
    smoothingTimeConstant = 0.3;
    frequencyBinCount = 512;
    getByteTimeDomainData(data: Uint8Array) { data.fill(128); }
    connect() {}
  }
  class FakeAudioContext {
    state = 'running';
    createAnalyser() { return new FakeAnalyser(); }
    createMediaStreamSource() { return { connect() {} }; }
    close() { return Promise.resolve(); }
  }
  (window as unknown as { AudioContext: unknown }).AudioContext = FakeAudioContext;
}

function fakeStream(): MediaStream {
  const track = {
    label: 'Selected Microphone',
    readyState: 'live',
    enabled: true,
    muted: false,
    getSettings: () => ({ deviceId: 'selected-device' }),
    addEventListener: () => {},
    stop: () => {},
  };
  return {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  } as unknown as MediaStream;
}

beforeEach(() => {
  localStorage.clear();
  // Hands-free on: this is about what hands-free opens.
  localStorage.setItem('homepilot_voice_handsfree', 'true');
  resetSttRuntimeForTests();
  resetWebSpeechForTests();
  getUserMedia.mockReset();
  getUserMedia.mockResolvedValue(fakeStream());
  startSTT.mockClear();
  capability.mockResolvedValue({
    available: true, provider: 'whisper-local', remote: false, hint: null,
  });

  stubAudioContext();
  (window as unknown as { SpeechRecognition: unknown }).SpeechRecognition = class {};
  (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = class {
    state = 'inactive';
    start() {}
    stop() {}
  };
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  });

  callbacks = {};
  window.SpeechService = {
    setRecognitionCallbacks: (cb: Callbacks) => { callbacks = { ...callbacks, ...cb }; },
    getSttDiagnostics: () => ({}),
    getVoices: () => [],
    isSpeaking: false,
    isRecognizing: false,
    startSTT,
    stopSTT: () => {},
    abortSTT: () => {},
    stopSpeaking: () => {},
    setPreferredVoiceURI: () => {},
  };
});

afterEach(() => {
  delete (window as unknown as { SpeechService?: unknown }).SpeechService;
  vi.clearAllMocks();
});

async function mountHandsFree(preference: 'web-speech' | 'homepilot') {
  localStorage.setItem('homepilot_stt_preferences_v1', JSON.stringify({ chat: preference }));
  const hook = renderHook(() => useVoiceController(vi.fn()));
  await waitFor(() => expect(hook.result.current.sttEngine).not.toBeNull());
  // Let the capture effect settle after the engine lands.
  await act(async () => { await Promise.resolve(); });
  return hook;
}

describe('hands-free on the browser engine', () => {
  it('opens no HomePilot capture at all', async () => {
    const { result } = await mountHandsFree('web-speech');

    expect(result.current.sttEngine).toBe('web-speech');
    // The recognizer owns the microphone alone. A `getUserMedia` here is the second capture.
    expect(getUserMedia).not.toHaveBeenCalled();
    await waitFor(() => expect(startSTT).toHaveBeenCalled());
  });

  it('says the level meter is unavailable rather than animating a lie', async () => {
    // There is no stream to measure, and opening one purely to draw a bar is precisely the
    // second capture that caused the bug.
    const { result } = await mountHandsFree('web-speech');

    expect(result.current.micMeterSupported).toBe(false);
    expect(result.current.liveTranscriptSupported).toBe(true);
    expect(result.current.bargeInSupported).toBe(false);
  });
});

describe('the live caption on the browser engine', () => {
  /*
   * What the user asked for, in their words: "behave like Grok, displaying what I am saying
   * in real time".
   *
   * A one-shot recognition session ends at the first pause, so hands-free was a series of
   * short recognitions with a restart between each — the caption died at exactly the moment
   * somebody was mid-sentence, and Chrome raised `no-speech` every few seconds of a quiet
   * room, which surfaced as a red banner under the orb. One continuous session streams
   * interim words the whole time and hands back each finished phrase as it completes.
   */
  it('listens continuously, so the words keep arriving', async () => {
    await mountHandsFree('web-speech');
    await waitFor(() => expect(startSTT).toHaveBeenCalled());

    expect(startSTT.mock.calls[0][1]).toMatchObject({ continuous: true });
  });

  it('shows the words while they are still being said', async () => {
    const { result } = await mountHandsFree('web-speech');
    await waitFor(() => expect(startSTT).toHaveBeenCalled());

    act(() => { callbacks.onInterim?.('turn on the kitchen'); });

    expect(result.current.interimText).toBe('turn on the kitchen');
    // And it reads as listening, not as idle, while they are arriving.
    expect(result.current.state).toBe('LISTENING');
  });

  it('does not caption the assistant’s own voice', async () => {
    // The recognizer cannot tell HomePilot's speaker output from the user, so anything
    // arriving while it is talking is either its own voice or a barge-in it has mangled.
    const { result } = await mountHandsFree('web-speech');
    await waitFor(() => expect(startSTT).toHaveBeenCalled());
    act(() => { callbacks.onInterim?.('hello'); });

    window.SpeechService.isSpeaking = true;
    await act(async () => { await new Promise((r) => setTimeout(r, 80)); });
    act(() => { callbacks.onInterim?.('I can help with that'); });

    expect(result.current.interimText).not.toBe('I can help with that');
  });

  it('treats a quiet room as quiet, not as an error', async () => {
    // `no-speech` is Chrome saying nobody said anything — the normal state of waiting. It
    // used to put a red banner under the orb every few seconds of a working session.
    const { result } = await mountHandsFree('web-speech');
    await waitFor(() => expect(startSTT).toHaveBeenCalled());

    act(() => { callbacks.onError?.('no-speech'); });
    expect(result.current.lastError).toBeNull();

    // And our own hand-off for TTS is not a fault either.
    act(() => { callbacks.onError?.('aborted'); });
    expect(result.current.lastError).toBeNull();
  });

  it('still reports a fault that is one', async () => {
    const { result } = await mountHandsFree('web-speech');
    await waitFor(() => expect(startSTT).toHaveBeenCalled());

    act(() => { callbacks.onError?.('not-allowed'); });
    expect(result.current.lastError).toBe('not-allowed');
  });

  it('keeps a manual turn one-shot', async () => {
    // A press has a Stop button behind it; a session that outlived the turn would hold the
    // microphone after the user thought they had released it.
    localStorage.setItem('homepilot_voice_handsfree', 'false');
    const { result } = await mountHandsFree('web-speech');
    startSTT.mockClear();

    await act(async () => { await result.current.startManualListening(); });

    expect(startSTT.mock.calls[0][1]).toMatchObject({ continuous: false });
  });
});

describe('hands-free on the local engine', () => {
  it('starts no browser recognizer', async () => {
    const { result } = await mountHandsFree('homepilot');

    expect(result.current.sttEngine).toBe('homepilot-backend');
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    expect(startSTT).not.toHaveBeenCalled();
  });

  it('reads the same microphone it transcribes, so a meter is honest', async () => {
    const { result } = await mountHandsFree('homepilot');

    await waitFor(() => expect(result.current.micMeterSupported).toBe(true));
    // No interim words exist on this engine: the text arrives when the turn ends.
    expect(result.current.liveTranscriptSupported).toBe(false);
  });
});

describe('switching engines mid-session', () => {
  it('releases the browser recognizer before opening HomePilot’s capture', async () => {
    const abortSTT = vi.fn();
    window.SpeechService.abortSTT = abortSTT;
    const { result, rerender } = await mountHandsFree('web-speech');
    expect(getUserMedia).not.toHaveBeenCalled();

    const { applySttSessionOverride } = await import('../ui/media/sttRuntime');
    await act(async () => {
      applySttSessionOverride('homepilot-backend', 'switched', 'voice');
      rerender();
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.sttEngine).toBe('homepilot-backend'));
    // The recognizer is dropped, and only then does a microphone open. Never both.
    expect(abortSTT).toHaveBeenCalled();
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
  });
});
