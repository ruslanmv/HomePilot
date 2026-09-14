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

  window.SpeechService = {
    setRecognitionCallbacks: () => {},
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
