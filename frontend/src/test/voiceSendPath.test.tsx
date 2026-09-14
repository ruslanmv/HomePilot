/**
 * The link the bug report was about: speech becomes text, and the text reaches the assistant.
 *
 * "It recognizes my voice however does not send ... and the AI is not receiving my
 * instructions." Everything else in the voice stack is upstream plumbing; this is the join
 * that decides whether any of it produced anything. It had no test, on either engine.
 *
 * `onSendText` is the whole contract. `VoiceModeGrok` forwards it to `App`'s
 * `sendTextOrIntent`, which is what posts to the backend, so a transcript arriving here is a
 * transcript arriving at the model.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const capability = vi.fn();
const transcribeBlob = vi.fn();
const openSelectedMicrophone = vi.fn();

vi.mock('../ui/media/sttService', () => ({
  getSttCapability: () => capability(),
  transcribeBlob: (...args: unknown[]) => transcribeBlob(...args),
  openSelectedMicrophone: (...args: unknown[]) => openSelectedMicrophone(...args),
  resetSttCapabilityCache: vi.fn(),
  recordAndTranscribe: vi.fn(),
  SttUnavailableError: class SttUnavailableError extends Error {},
}));

import { useVoiceController } from '../ui/voice/useVoiceController';
import { resetSttRuntimeForTests } from '../ui/media/sttRuntime';
import { resetWebSpeechForTests } from '../ui/media/webSpeechSession';

type Callbacks = {
  onStart?: () => void;
  onEnd?: () => void;
  onInterim?: (text: string) => void;
  onResult?: (text: string) => void;
  onError?: (message: string) => void;
};

let callbacks: Callbacks = {};

/** A MediaRecorder that hands back one chunk when told to stop. */
class FakeMediaRecorder {
  static last: FakeMediaRecorder | null = null;
  state = 'inactive';
  mimeType = 'audio/webm';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public stream: MediaStream) {
    FakeMediaRecorder.last = this;
  }

  start() { this.state = 'recording'; }

  stop() {
    this.state = 'inactive';
    this.ondataavailable?.({ data: new Blob(['audio-bytes']) });
    this.onstop?.();
  }
}

const stopTrack = vi.fn();
const fakeStream = () => ({
  getTracks: () => [{ stop: stopTrack, readyState: 'live' }],
  getAudioTracks: () => [{ stop: stopTrack, readyState: 'live' }],
} as unknown as MediaStream);

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('homepilot_voice_handsfree', 'false');
  // The engine decision and the page's one recognizer are session-scoped singletons, which
  // is the point of them. A test file is a new session.
  resetSttRuntimeForTests();
  resetWebSpeechForTests();
  callbacks = {};
  FakeMediaRecorder.last = null;
  stopTrack.mockClear();
  capability.mockResolvedValue({ available: true, provider: 'whisper-local', remote: false });
  openSelectedMicrophone.mockResolvedValue(fakeStream());

  (window as unknown as { SpeechRecognition: unknown }).SpeechRecognition = class {};
  (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = FakeMediaRecorder;
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn() },
  });

  window.SpeechService = {
    setRecognitionCallbacks: (cb: Callbacks) => { callbacks = { ...callbacks, ...cb }; },
    getSttDiagnostics: () => ({}),
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

async function mountVoice(preference: 'web-speech' | 'homepilot') {
  localStorage.setItem('homepilot_stt_preferences_v1', JSON.stringify({ chat: preference }));
  const onSendText = vi.fn();
  const hook = renderHook(() => useVoiceController(onSendText));
  await waitFor(() => expect(hook.result.current.sttResolution).not.toBeNull());
  return { ...hook, onSendText };
}

describe('the browser engine', () => {
  it('sends a recognized sentence to the assistant', async () => {
    const { onSendText, result } = await mountVoice('web-speech');
    expect(result.current.sttEngine).toBe('web-speech');

    // The recognizer only speaks to whoever owns the turn, so there has to be one.
    await act(async () => { await result.current.startManualListening(); });
    act(() => { callbacks.onResult?.('  turn on the kitchen lights  '); });

    // Trimmed, and nothing else changed: this text is what the model is asked.
    expect(onSendText).toHaveBeenCalledWith('turn on the kitchen lights');
  });

  it('shows words as they are recognized, before the turn ends', async () => {
    // The live transcript is the browser engine's one real advantage over transcribing on
    // this computer, and what tells the user a turn is working rather than silent.
    const { result } = await mountVoice('web-speech');
    await act(async () => { await result.current.startManualListening(); });

    act(() => { callbacks.onInterim?.('turn on the'); });
    expect(result.current.interimText).toBe('turn on the');
    expect(result.current.liveTranscriptSupported).toBe(true);
  });

  it('sends nothing when the recognizer returns an empty string', async () => {
    const { onSendText, result } = await mountVoice('web-speech');
    await act(async () => { await result.current.startManualListening(); });
    act(() => { callbacks.onResult?.('   '); });
    expect(onSendText).not.toHaveBeenCalled();
  });

  it('opens no recorder and no VAD capture', async () => {
    // The whole bug: a second capture, on a device nobody transcribes.
    const { result } = await mountVoice('web-speech');
    await act(async () => { await result.current.startManualListening(); });

    expect(openSelectedMicrophone).not.toHaveBeenCalled();
    expect(FakeMediaRecorder.last).toBeNull();
    expect(result.current.micMeterSupported).toBe(false);
  });
});

describe('the on-device engine', () => {
  it('sends what the server transcribed', async () => {
    transcribeBlob.mockResolvedValue({ text: 'what is on my calendar', provider: 'whisper-local' });
    const { onSendText, result } = await mountVoice('homepilot');
    expect(result.current.sttEngine).toBe('homepilot-backend');

    await act(async () => { await result.current.startManualListening(); });
    await act(async () => { FakeMediaRecorder.last?.stop(); });

    await waitFor(() => expect(onSendText).toHaveBeenCalledWith('what is on my calendar'));
  });

  it('opens the selected microphone itself when the VAD is not running', async () => {
    // The manual listen button outside hands-free mode. There is no VAD capture to borrow
    // there, and giving up was a dead button for everybody on the local engine — including
    // anyone the deaf-recognizer recovery had just moved onto it.
    transcribeBlob.mockResolvedValue({ text: 'hello', provider: 'whisper-local' });
    const { result } = await mountVoice('homepilot');

    await act(async () => { await result.current.startManualListening(); });

    expect(openSelectedMicrophone).toHaveBeenCalledWith('voice');
    expect(FakeMediaRecorder.last).not.toBeNull();
  });

  it('closes a capture it opened, so the recording indicator does not stay on', async () => {
    transcribeBlob.mockResolvedValue({ text: 'hello', provider: 'whisper-local' });
    const { result } = await mountVoice('homepilot');

    await act(async () => { await result.current.startManualListening(); });
    expect(stopTrack).not.toHaveBeenCalled();
    await act(async () => { FakeMediaRecorder.last?.stop(); });

    expect(stopTrack).toHaveBeenCalled();
  });

  it('says so rather than sending when the transcription is silence', async () => {
    // Empty text is a successful transcription of nothing, and must not reach the model as
    // an empty turn.
    transcribeBlob.mockResolvedValue({ text: '', provider: 'whisper-local' });
    const { onSendText, result } = await mountVoice('homepilot');

    await act(async () => { await result.current.startManualListening(); });
    await act(async () => { FakeMediaRecorder.last?.stop(); });

    await waitFor(() => expect(result.current.lastError).toBe('no_speech_detected'));
    expect(onSendText).not.toHaveBeenCalled();
  });
});
