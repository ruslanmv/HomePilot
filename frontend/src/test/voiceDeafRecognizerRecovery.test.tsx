/**
 * Voice mode recovering from a recognizer that hears nothing.
 *
 * The reported symptom was "it recognizes my voice however does not send": the orb tracked
 * the speaker, the turn ended, and nothing came out — no text, no error, no message. The
 * browser recognizer had opened the operating system's default input, which was silent,
 * while HomePilot's VAD was listening to the microphone the user selected.
 *
 * `media/sttTurnHealth` decides; this is about the wiring, which is where the value is. A
 * detector nobody calls fixes nothing, and the previous version of this failure was invisible
 * precisely because the signal existed and no code read it.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const capability = vi.fn(async () => ({
  available: true,
  provider: 'whisper-local',
  remote: false,
}));

vi.mock('../ui/media/sttService', () => ({
  getSttCapability: (...args: unknown[]) => capability(...(args as [])),
  transcribeBlob: vi.fn(),
  resetSttCapabilityCache: vi.fn(),
  openSelectedMicrophone: vi.fn(),
  recordAndTranscribe: vi.fn(),
  SttUnavailableError: class SttUnavailableError extends Error {},
}));

import { useVoiceController } from '../ui/voice/useVoiceController';
import { DEAF_TURNS_BEFORE_RECOVERY } from '../ui/media/sttTurnHealth';

type Callbacks = {
  onStart?: () => void;
  onEnd?: () => void;
  onInterim?: (text: string) => void;
  onResult?: (text: string) => void;
  onError?: (message: string) => void;
};

let callbacks: Callbacks = {};
let diagnostics: Record<string, unknown> = {};

const DEAF = { sawAudioStart: true, sawSpeechStart: false, sawInterim: false, error: null };

beforeEach(() => {
  localStorage.clear();
  // Hands-free off: this is about the turn verdict, and leaving it on would open a real VAD
  // capture that jsdom cannot provide.
  localStorage.setItem('homepilot_voice_handsfree', 'false');
  callbacks = {};
  diagnostics = { ...DEAF };
  capability.mockResolvedValue({ available: true, provider: 'whisper-local', remote: false });

  // Web Speech has to look supported, or the engine resolves to the backend up front and
  // there is no deaf recognizer to recover from.
  (window as unknown as { SpeechRecognition: unknown }).SpeechRecognition = class {};
  (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = class {};
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn() },
  });

  window.SpeechService = {
    setRecognitionCallbacks: (cb: Callbacks) => { callbacks = { ...callbacks, ...cb }; },
    getSttDiagnostics: () => diagnostics,
    getVoices: () => [],
    isSpeaking: false,
    isRecognizing: false,
    startSTT: () => true,
    stopSTT: () => {},
    stopSpeaking: () => {},
    setPreferredVoiceURI: () => {},
  };
});

afterEach(() => {
  delete (window as unknown as { SpeechService?: unknown }).SpeechService;
  vi.clearAllMocks();
});

async function mountVoice() {
  const onSend = vi.fn();
  const hook = renderHook(() => useVoiceController(onSend));
  // The capability probe is a promise; the engine is not resolved until it lands.
  await waitFor(() => expect(hook.result.current.sttEngine).toBe('web-speech'));
  return { ...hook, onSend };
}

function endTurn() {
  act(() => { callbacks.onEnd?.(); });
}

describe('a recognizer that opens a silent device', () => {
  it('says nothing after a single empty turn', async () => {
    // One empty turn is a cough or a false trigger. Reacting to it would change where a
    // healthy user's audio goes on the strength of no evidence.
    const { result } = await mountVoice();
    endTurn();

    expect(result.current.sttNotice).toBeNull();
    expect(result.current.sttEngine).toBe('web-speech');
  });

  it('moves the session onto HomePilot transcription once the pattern is established', async () => {
    const { result } = await mountVoice();
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY; i++) endTurn();

    expect(result.current.sttEngine).toBe('homepilot-backend');
    expect(result.current.sttNotice).toContain('Speech Recognition');
  });

  it('never makes that switch silently', async () => {
    // Changing which service sees the user's audio without telling them is the failure the
    // engine split exists to prevent; a recovery is not exempt from it.
    const { result } = await mountVoice();
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY; i++) endTurn();

    expect(result.current.sttNotice).toBeTruthy();
    act(() => result.current.dismissSttNotice());
    expect(result.current.sttNotice).toBeNull();
  });

  it('forgets the run as soon as one turn produces words', async () => {
    // A microphone that works once works. Counting non-consecutive empty turns would
    // eventually switch engines under everybody.
    const { result } = await mountVoice();
    endTurn();
    act(() => { callbacks.onResult?.('hello there'); });
    endTurn();
    endTurn();

    expect(result.current.sttEngine).toBe('web-speech');
    expect(result.current.sttNotice).toBeNull();
  });

  it('advises rather than switching when there is no other engine', async () => {
    capability.mockResolvedValue({ available: false, provider: null, remote: false } as never);
    const { result } = await mountVoice();
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY; i++) endTurn();

    expect(result.current.sttEngine).toBe('web-speech');
    expect(result.current.sttNotice).toContain('system default input');
  });

  it('leaves a turn that heard speech alone', async () => {
    // Speech heard and nothing matched is the wrong language or an early stop. Switching
    // engines fixes neither, and would bury both.
    diagnostics = { sawAudioStart: true, sawSpeechStart: true, sawInterim: false, error: null };
    const { result } = await mountVoice();
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY + 2; i++) endTurn();

    expect(result.current.sttEngine).toBe('web-speech');
    expect(result.current.sttNotice).toBeNull();
  });

  it('leaves a reported error alone', async () => {
    diagnostics = { sawAudioStart: true, sawSpeechStart: false, error: 'not-allowed' };
    const { result } = await mountVoice();
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY + 2; i++) endTurn();

    expect(result.current.sttNotice).toBeNull();
  });
});
