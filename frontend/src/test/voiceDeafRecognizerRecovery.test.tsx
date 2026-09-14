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
import { getSttRuntime, resetSttRuntimeForTests } from '../ui/media/sttRuntime';
import { resetWebSpeechForTests } from '../ui/media/webSpeechSession';

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
  // Session-scoped singletons by design — see `media/sttRuntime`. A test file is a session.
  resetSttRuntimeForTests();
  resetWebSpeechForTests();
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

/**
 * One complete browser turn: take the recognizer, then let it end.
 *
 * The recognizer only speaks to the surface that owns the turn now, so a verdict cannot be
 * reached on an `onEnd` nobody asked for — which is exactly the protection that stops a
 * stale event from a handed-off session ending somebody else's turn.
 */
async function endTurn(result: { current: { startManualListening: () => Promise<boolean> } }) {
  await act(async () => { await result.current.startManualListening(); });
  act(() => { callbacks.onEnd?.(); });
}

describe('a recognizer that opens a silent device', () => {
  it('lets the first turn of a session go', async () => {
    /*
     * Opening Voice and pressing listen is how people check that Voice is *there*. They press
     * it, look at the orb, and very often say nothing — there is nothing to say yet. That turn
     * ends exactly like a deaf one: a capture opened, stayed open, and heard no speech, because
     * none was spoken.
     *
     * Acting on it moved the whole session onto another engine and put a paragraph on screen
     * explaining a fault that had not happened, to a user whose microphone was fine. One turn
     * is what it costs to stop doing that, and the verdict was never trustworthy on one turn
     * alone.
     */
    const { result } = await mountVoice();
    await endTurn(result);

    expect(result.current.sttEngine).toBe('web-speech');
    expect(result.current.sttNotice).toBeNull();
  });

  it('acts on the next one, without waiting for a third', async () => {
    // Past the warm-up, a turn the user started and stopped themselves is a person asserting
    // they said something. A further empty turn would only cost them another turn to learn
    // what this one proved.
    const { result } = await mountVoice();
    await endTurn(result);
    await endTurn(result);

    expect(result.current.sttEngine).toBe('homepilot-backend');
    expect(result.current.sttNotice).toContain('Speech Recognition');
  });

  it('starts a fresh warm-up each time listening is switched on', async () => {
    // Leaving Voice and coming back is a new session to the user whether or not the component
    // survived, and the first press after returning is the same "is this thing on?" press.
    const { result } = await mountVoice();
    await endTurn(result);
    act(() => result.current.setHandsFree(false));
    act(() => result.current.setHandsFree(true));
    await endTurn(result);

    expect(result.current.sttEngine).toBe('web-speech');
  });

  it('moves the session onto HomePilot transcription once the pattern is established', async () => {
    const { result } = await mountVoice();
    await endTurn(result); // warm-up
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY; i++) await endTurn(result);

    expect(result.current.sttEngine).toBe('homepilot-backend');
    expect(result.current.sttNotice).toContain('Speech Recognition');
  });

  it('moves the whole session, so the chat composer goes with it', async () => {
    // The recovery used to be per-surface: Voice switched, the composer did not, and the
    // same deaf microphone had to be rediscovered from scratch on the other tab. It is one
    // person with one microphone, so it is one decision.
    const { result } = await mountVoice();
    await endTurn(result); // warm-up: the first turn of a session is never evidence
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY; i++) await endTurn(result);

    expect(getSttRuntime().effectiveEngine).toBe('homepilot-backend');
    expect(getSttRuntime().sessionOverride).toBe('homepilot-backend');
    // The stored preference is the user's and stays theirs; Settings goes on showing it.
    expect(getSttRuntime().preference).toBe('web-speech');
  });

  it('never makes that switch silently', async () => {
    // Changing which service sees the user's audio without telling them is the failure the
    // engine split exists to prevent; a recovery is not exempt from it.
    const { result } = await mountVoice();
    await endTurn(result); // warm-up: the first turn of a session is never evidence
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY; i++) await endTurn(result);

    expect(result.current.sttNotice).toBeTruthy();
    act(() => result.current.dismissSttNotice());
    expect(result.current.sttNotice).toBeNull();
  });

  it('blames the device rather than a second capture, because there is not one', async () => {
    // While the engines ran together, "HomePilot's own capture is blocking the browser's"
    // was an equally good explanation for an identical trace, so the message had to name
    // both. Exclusive ownership settles it: nothing else held the microphone.
    const { result } = await mountVoice();
    await endTurn(result); // warm-up: the first turn of a session is never evidence
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY; i++) await endTurn(result);

    expect(result.current.sttNotice).toContain('system default input');
    expect(result.current.sttNotice).not.toContain('preventing the browser from opening');
  });

  it('forgets the run as soon as one turn produces words', async () => {
    // A microphone that works once works. A turn with words clears the count, so a later
    // empty one starts from zero instead of adding to a stale run.
    const { result } = await mountVoice();
    await act(async () => { await result.current.startManualListening(); });
    act(() => { callbacks.onResult?.('hello there'); });
    act(() => { callbacks.onEnd?.(); });

    expect(result.current.sttEngine).toBe('web-speech');
    expect(result.current.sttNotice).toBeNull();
  });

  it('never counts a turn the user did not start', async () => {
    /*
     * The hands-free browser loop opens a turn every 400 ms whether or not anybody is
     * talking, and no VAD runs on this engine to say that somebody was. So "the recognizer
     * heard nothing" there is the ordinary sound of a quiet room — counting it would switch
     * engines under a user who simply stopped speaking, which is every user, constantly.
     *
     * This is the guarantee that makes the hands-free restart loop safe to run at all.
     */
    localStorage.setItem('homepilot_voice_handsfree', 'true');
    const { result } = await mountVoice();
    await waitFor(() => expect(window.SpeechService.startSTT).toBeDefined());

    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY + 4; i++) {
      act(() => { callbacks.onEnd?.(); });
    }

    expect(result.current.sttEngine).toBe('web-speech');
    expect(result.current.sttNotice).toBeNull();
  });

  it('advises rather than switching when there is no other engine', async () => {
    capability.mockResolvedValue({ available: false, provider: null, remote: false } as never);
    const { result } = await mountVoice();
    await endTurn(result); // warm-up: the first turn of a session is never evidence
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY; i++) await endTurn(result);

    expect(result.current.sttEngine).toBe('web-speech');
    expect(result.current.sttNotice).toContain('system default input');
  });

  it('leaves a turn that heard speech alone', async () => {
    // Speech heard and nothing matched is the wrong language or an early stop. Switching
    // engines fixes neither, and would bury both.
    diagnostics = { sawAudioStart: true, sawSpeechStart: true, sawInterim: false, error: null };
    const { result } = await mountVoice();
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY + 2; i++) await endTurn(result);

    expect(result.current.sttEngine).toBe('web-speech');
    expect(result.current.sttNotice).toBeNull();
  });

  it('leaves a reported error alone', async () => {
    diagnostics = { sawAudioStart: true, sawSpeechStart: false, error: 'not-allowed' };
    const { result } = await mountVoice();
    for (let i = 0; i < DEAF_TURNS_BEFORE_RECOVERY + 2; i++) await endTurn(result);

    expect(result.current.sttNotice).toBeNull();
  });
});
