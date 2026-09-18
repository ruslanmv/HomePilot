/**
 * Handing the one browser recognizer from turn to turn without dropping it.
 *
 * ── The bug ──────────────────────────────────────────────────────────────────────────────
 *
 * A call listened but never transcribed. The console said why, if you read the order:
 *
 *     stt_start_requested          ← a turn is already live
 *     abort_requested              ← the hand-off drops it
 *     web_speech_start_requested
 *     start_failed                 ← InvalidStateError
 *     recognition_audioend
 *     recognition_onend            ← the aborted session ends *after* the failed start
 *
 * Two faults, one symptom. The recognizer was cycled to replace a healthy session with an
 * identical one, and the restart assumed `abort()` had already finished when the browser had
 * only just been told. After the failed start nothing else restarted transcription: the
 * microphone stayed open, the input meter kept moving, and not one word reached the model.
 *
 * So: a repeat start on the same terms is the session that is already running, and a genuine
 * hand-off waits for `onend` before taking the microphone.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  abortWebSpeech,
  resetWebSpeechForTests,
  startWebSpeech,
} from '../ui/media/webSpeechSession';

type Win = typeof window & {
  SpeechService?: unknown;
  SpeechRecognition?: unknown;
  webkitSpeechRecognition?: unknown;
};

const win = window as Win;

afterEach(() => {
  resetWebSpeechForTests();
  delete win.SpeechService;
  delete win.SpeechRecognition;
  delete win.webkitSpeechRecognition;
  vi.clearAllMocks();
});

describe('the recognizer already running for this surface', () => {
  let startSTT: ReturnType<typeof vi.fn>;
  let abortSTT: ReturnType<typeof vi.fn>;
  /** What the module installed on the shared recognizer — the only way events arrive. */
  let installed: { onResult?: (text: string) => void } = {};

  beforeEach(() => {
    installed = {};
    const service = {
      isRecognizing: false,
      setRecognitionCallbacks: (cb: { onResult?: (text: string) => void }) => {
        installed = { ...installed, ...cb };
      },
      getSttDiagnostics: () => ({}),
      isRecognitionSupported: true,
      startSTT: vi.fn(async () => {
        service.isRecognizing = true;
        return true;
      }),
      abortSTT: vi.fn(() => {
        service.isRecognizing = false;
        return true;
      }),
      stopSTT: () => true,
    };
    startSTT = service.startSTT;
    abortSTT = service.abortSTT;
    win.SpeechService = service;
  });

  it('is left alone when the same surface asks again on the same terms', async () => {
    expect(await startWebSpeech('voice', {}, { continuous: true })).toBe(true);
    expect(startSTT).toHaveBeenCalledTimes(1);

    // The voice controller reaches this from several paths at once — a restart timer, the
    // capture effect, a turn lock releasing. Each one used to cycle the recognizer.
    const onStart = vi.fn();
    expect(await startWebSpeech('voice', { onStart }, { continuous: true })).toBe(true);

    expect(abortSTT).not.toHaveBeenCalled();
    expect(startSTT).toHaveBeenCalledTimes(1);
    // Resolving `true` means "you are listening" however it was reached, so the caller can
    // set its own state from one signal instead of guessing which path it took.
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it('delivers results to the newest handlers, not the ones it replaced', async () => {
    const stale = vi.fn();
    await startWebSpeech('voice', { onResult: stale }, { continuous: true });

    const fresh = vi.fn();
    await startWebSpeech('voice', { onResult: fresh }, { continuous: true });

    // Keeping the session must not mean keeping the caller that opened it: the surface
    // asking now is the one waiting for this turn's transcript.
    installed.onResult?.('turn the lights on');

    expect(fresh).toHaveBeenCalledWith('turn the lights on');
    expect(stale).not.toHaveBeenCalled();
  });

  it('still hands over when another surface asks', async () => {
    await startWebSpeech('voice', {}, { continuous: true });
    expect(await startWebSpeech('chat', {}, {})).toBe(true);

    expect(abortSTT).toHaveBeenCalled();
    expect(startSTT).toHaveBeenCalledTimes(2);
  });

  it('still restarts when the same surface changes the session terms', async () => {
    await startWebSpeech('voice', {}, { continuous: true });
    // Hands-free off: a one-shot turn is a different session, not the running one.
    expect(await startWebSpeech('voice', {}, { continuous: false })).toBe(true);

    expect(abortSTT).toHaveBeenCalled();
    expect(startSTT).toHaveBeenCalledTimes(2);
  });
});

describe('without window.SpeechService, on the native recognizer', () => {
  /** One live session per page, and `abort()` does not end it — exactly Chrome's rule. */
  class NativeRecognition {
    static instances: NativeRecognition[] = [];

    live = false;
    startCalls = 0;
    abortCalls = 0;
    continuous = false;
    interimResults = false;
    lang = '';
    onend: (() => void) | null = null;
    onstart: (() => void) | null = null;

    constructor() {
      NativeRecognition.instances.push(this);
    }

    start() {
      if (NativeRecognition.instances.some((r) => r !== this && r.live)) {
        const error = new Error('recognition has already started');
        error.name = 'InvalidStateError';
        throw error;
      }
      this.startCalls += 1;
      this.live = true;
      this.onstart?.();
    }

    abort() {
      this.abortCalls += 1;
      // Note what is *not* here: `onend`. The browser delivers it on a later task.
    }

    finishEnding() {
      this.live = false;
      this.onend?.();
    }
  }

  beforeEach(() => {
    NativeRecognition.instances = [];
    delete win.SpeechService;
    win.SpeechRecognition = NativeRecognition;
  });

  it('waits for the aborted session to end before starting the next', async () => {
    expect(await startWebSpeech('voice', {}, { continuous: true })).toBe(true);
    const first = NativeRecognition.instances[0];
    expect(first.startCalls).toBe(1);

    abortWebSpeech('handoff');
    expect(first.abortCalls).toBe(1);

    // The hand-off starts the next turn immediately, as the voice controller does.
    const next = startWebSpeech('chat', {}, {});
    await Promise.resolve();

    // Nothing new has been started: the browser has not finished with the old session.
    expect(NativeRecognition.instances).toHaveLength(1);

    first.finishEnding();

    expect(await next).toBe(true);
    expect(NativeRecognition.instances).toHaveLength(2);
    expect(NativeRecognition.instances[1].startCalls).toBe(1);
  });
});
