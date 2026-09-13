/**
 * The stop guard in `public/js/speech-service.js`.
 *
 * This is the fix for the reported symptom: hands-free voice logged
 *
 *   stt_onstart
 *   speech_ended  speechMs: 1389  silenceMs: 805
 *   stt_stop_requested { reason: 'vad_silence' }
 *   stt_onend { hadResult: false }
 *
 * with no interim, no result and no error. HomePilot's VAD reaches its silence
 * window on a short utterance before Chrome's recognizer has streamed enough
 * audio to finalize anything, and honouring that stop immediately ends the
 * session empty — cleanly, so not even a `no-speech` error is raised.
 *
 * `speech-service.js` is a classic script served from `public/`, so the suite
 * evaluates it the way the browser does rather than importing it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const SOURCE = readFileSync(resolve(ROOT, 'frontend/public/js/speech-service.js'), 'utf8');

/** Stand-in for the browser's SpeechRecognition, with no audio pipeline. */
class FakeRecognition {
  constructor() {
    this.continuous = false;
    this.interimResults = false;
    this.lang = '';
    this.startCalls = 0;
    this.stopCalls = 0;
    this.abortCalls = 0;
    FakeRecognition.last = this;
  }

  start() {
    this.startCalls += 1;
    this.onstart?.();
  }

  stop() {
    this.stopCalls += 1;
  }

  abort() {
    this.abortCalls += 1;
  }

  /** Deliver a final transcript the way Chrome's `onresult` does. */
  emitFinal(transcript) {
    this.onresult?.({
      resultIndex: 0,
      results: { length: 1, 0: { isFinal: true, 0: { transcript } } },
    });
  }

  emitInterim(transcript) {
    this.onresult?.({
      resultIndex: 0,
      results: { length: 1, 0: { isFinal: false, 0: { transcript } } },
    });
  }

  /** The capture opened — the recognizer is receiving samples, whatever is in them. */
  emitAudioStart() {
    this.onaudiostart?.();
  }

  /** The recognizer's own detector found speech in those samples. */
  emitSpeechStart() {
    this.onspeechstart?.();
  }
}

function loadSpeechService() {
  window.SpeechRecognition = FakeRecognition;
  delete window.SpeechService;
  window.__HOMEPILOT_MIC_DEBUG__ = [];
  // eslint-disable-next-line no-new-func
  new Function(SOURCE)();
  return window.SpeechService;
}

const traceEvents = () => (window.__HOMEPILOT_MIC_DEBUG__ || []).map((entry) => entry.event);

describe('SpeechService speech-to-text', () => {
  let service;
  let nowMs = 0;
  let realPerformanceNow;

  /** Move both clocks together — the timer queue and the one the service reads. */
  const advance = (ms) => {
    nowMs += ms;
    vi.advanceTimersByTime(ms);
  };

  beforeEach(() => {
    vi.useFakeTimers();
    // The service measures a turn with `performance.now()`, and the fake clock does not reach
    // it inside the evaluated classic script: every elapsed reading came back 0, so every stop
    // looked like it arrived during warm-up and the threshold tests below never reached the
    // threshold they name. Driving the clock by hand is the only way this file tests the
    // guards rather than the number zero.
    // Patched on `window` specifically: the service is evaluated as a classic script, so it
    // resolves `performance` off the global object, which is not necessarily the binding this
    // module sees. Spying on the module-scope one left the service reading a clock that never
    // moved.
    nowMs = 0;
    realPerformanceNow = window.performance.now;
    window.performance.now = () => nowMs;
    localStorage.clear();
    service = loadSpeechService();
  });

  afterEach(() => {
    window.performance.now = realPerformanceNow;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('defers a stop that would cut recognition off during warm-up', async () => {
    await service.startSTT();
    const recognition = FakeRecognition.last;
    expect(recognition.startCalls).toBe(1);

    // The VAD's silence window on a ~1.4s utterance lands well inside warm-up.
    advance(600);
    service.stopSTT({ reason: 'vad_silence' });

    expect(recognition.stopCalls).toBe(0);
    expect(traceEvents()).toContain('stop_deferred_warming_up');

    // Once the minimum listen window has passed, the stop is applied for real.
    advance(service.STT_MIN_LISTEN_MS);
    expect(recognition.stopCalls).toBe(1);
    expect(traceEvents()).toContain('stop_applied_after_defer');
  });

  it('stops immediately once a result has landed', async () => {
    await service.startSTT();
    const recognition = FakeRecognition.last;

    advance(300);
    recognition.emitFinal('turn the lights on');

    service.stopSTT({ reason: 'vad_silence' });
    expect(recognition.stopCalls).toBe(1);
    expect(traceEvents()).not.toContain('stop_deferred_warming_up');
  });

  it('cancels a deferred stop when a result arrives while waiting', async () => {
    await service.startSTT();
    const recognition = FakeRecognition.last;

    advance(200);
    service.stopSTT({ reason: 'vad_silence' });
    expect(recognition.stopCalls).toBe(0);

    recognition.emitFinal('play some music');
    advance(5000);

    // The turn ended on its own terms; the deferred stop must not fire late
    // and cut off the *next* session.
    expect(recognition.stopCalls).toBe(0);
  });

  describe('a recognizer that has captured audio but heard no speech', () => {
    /**
     * The reported failure. HomePilot's VAD hears the selected microphone and calls time on
     * the turn; the browser recognizer is on a different device and has heard nothing. The
     * VAD's verdict is evidence about its own microphone, not about this recognizer's, so
     * honouring it guarantees an empty turn — and leaves "was it deaf, or did we cut it off?"
     * unanswerable, which is exactly the question the diagnosis turns on.
     */
    it('keeps listening past warm-up rather than guaranteeing an empty turn', async () => {
      await service.startSTT();
      const recognition = FakeRecognition.last;
      recognition.emitAudioStart();

      // Past the warm-up guard, so only the new one can be holding it open.
      advance(2400);
      service.stopSTT({ reason: 'vad_silence' });

      expect(recognition.stopCalls).toBe(0);
      const deferral = (window.__HOMEPILOT_MIC_DEBUG__ || []).find(
        (entry) => entry.event === 'stop_deferred_warming_up',
      );
      expect(deferral?.details?.deferredBy).toBe('no_speech_yet');
    });

    it('gives up at the grace window, so a deaf device still ends the turn', async () => {
      await service.startSTT();
      const recognition = FakeRecognition.last;
      recognition.emitAudioStart();

      advance(2400);
      service.stopSTT({ reason: 'vad_silence' });
      advance(service.STT_NO_SPEECH_GRACE_MS);

      expect(recognition.stopCalls).toBe(1);
      expect(traceEvents()).toContain('stop_applied_after_defer');
    });

    it('does not delay a turn the recognizer actually heard', async () => {
      // The whole point is to cost nothing when the recognizer is working: once it has heard
      // speech, the VAD's silence window is a perfectly good endpoint and waiting would make
      // every successful turn slower.
      await service.startSTT();
      const recognition = FakeRecognition.last;
      recognition.emitAudioStart();
      recognition.emitSpeechStart();

      advance(2400);
      service.stopSTT({ reason: 'vad_silence' });

      expect(recognition.stopCalls).toBe(1);
    });

    it('does not delay when interim words came back without a speechstart event', async () => {
      await service.startSTT();
      const recognition = FakeRecognition.last;
      recognition.emitAudioStart();
      recognition.emitInterim('hello');

      advance(2400);
      service.stopSTT({ reason: 'vad_silence' });

      expect(recognition.stopCalls).toBe(1);
    });

    it('still yields to a forced stop', async () => {
      // A turn lock, a teardown or the user pressing stop must never wait on a grace window.
      await service.startSTT();
      const recognition = FakeRecognition.last;
      recognition.emitAudioStart();

      advance(2400);
      service.stopSTT({ reason: 'manual_button', force: true });

      expect(recognition.stopCalls).toBe(1);
    });

    it('never holds a turn past the hard ceiling', async () => {
      await service.startSTT();
      const recognition = FakeRecognition.last;
      recognition.emitAudioStart();

      advance(service.STT_MAX_LISTEN_MS - 100);
      service.stopSTT({ reason: 'vad_silence' });
      advance(200);

      expect(recognition.stopCalls).toBe(1);
    });
  });

  it('honours a forced stop without waiting', async () => {
    await service.startSTT();
    const recognition = FakeRecognition.last;

    service.stopSTT({ reason: 'manual_button', force: true });

    expect(recognition.stopCalls).toBe(1);
    expect(service.getSttDiagnostics().stoppedBy).toBe('manual_button:forced');
  });

  it('never holds a silent session open past the maximum', async () => {
    await service.startSTT();
    const recognition = FakeRecognition.last;

    service.stopSTT({ reason: 'vad_silence' });
    advance(service.STT_MAX_LISTEN_MS);

    expect(recognition.stopCalls).toBe(1);
  });

  it('records which lifecycle events the browser actually reported', async () => {
    await service.startSTT();
    const recognition = FakeRecognition.last;

    recognition.onaudiostart?.();
    recognition.onspeechstart?.();
    recognition.emitInterim('turn the');
    recognition.emitFinal('turn the lights on');
    recognition.onend?.();

    const diagnostics = service.getSttDiagnostics();
    expect(diagnostics.sawAudioStart).toBe(true);
    expect(diagnostics.sawSpeechStart).toBe(true);
    expect(diagnostics.sawInterim).toBe(true);
    expect(diagnostics.sawResult).toBe(true);
  });

  it('distinguishes a session that captured audio but heard no speech', async () => {
    await service.startSTT();
    const recognition = FakeRecognition.last;

    recognition.onaudiostart?.();
    recognition.onend?.();

    const diagnostics = service.getSttDiagnostics();
    expect(diagnostics.sawAudioStart).toBe(true);
    expect(diagnostics.sawSpeechStart).toBe(false);
    expect(diagnostics.sawResult).toBe(false);
  });

  it('traces to the shared HomePilot:Mic buffer without recording transcript text', async () => {
    await service.startSTT();
    FakeRecognition.last.emitFinal('a secret sentence');

    const entries = window.__HOMEPILOT_MIC_DEBUG__;
    expect(entries.every((entry) => entry.scope === 'speech-service')).toBe(true);
    expect(JSON.stringify(entries)).not.toContain('a secret sentence');

    const final = entries.find((entry) => entry.event === 'recognition_final');
    expect(final.details.characters).toBe('a secret sentence'.length);
  });

  it('surfaces the real reason when start() throws', async () => {
    const error = new Error('already started');
    error.name = 'InvalidStateError';
    vi.spyOn(FakeRecognition.prototype, 'start').mockImplementation(() => { throw error; });

    const onError = vi.fn();
    const started = await service.startSTT({ onError });

    expect(started).toBe(false);
    expect(onError).toHaveBeenCalledWith('InvalidStateError');
    expect(service.getSttDiagnostics().error).toBe('InvalidStateError');
  });

  it('aborts on demand so another surface can take the microphone', async () => {
    await service.startSTT();
    const recognition = FakeRecognition.last;

    expect(service.abortSTT('chat_composer_mic')).toBe(true);
    expect(recognition.abortCalls).toBe(1);
    expect(service.isRecognizing).toBe(false);
  });

  it('uses the configured recognition language instead of hard-coded en-US', async () => {
    service.setRecognitionLang('es-ES');
    await service.startSTT();

    expect(FakeRecognition.last.lang).toBe('es-ES');
    expect(localStorage.getItem('homepilot_stt_lang')).toBe('es-ES');
  });
});
