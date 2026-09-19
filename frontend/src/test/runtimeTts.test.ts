/**
 * Speaking through the runtime path (`window.SpeechService.speak`).
 *
 * Settings used to preview a voice by calling the TTS provider directly, while
 * live Voice goes through `window.SpeechService` — which `shimSpeechService`
 * wraps to route non-default engines through the registry. Those are different
 * functions, so the preview could pass while real assistant audio failed. The
 * tests below pin the runtime call and, just as importantly, pin that silence
 * is reported as a failure: `speechSynthesis` raises no error for a missing
 * voice, a muted output, or a blocked autoplay.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  RUNTIME_TTS_START_TIMEOUT_MS,
  explainRuntimeTts,
  isRuntimeTtsAvailable,
  isRuntimeTtsEnabled,
  speakThroughRuntime,
  stopRuntimeTts,
  type RuntimeTtsResult,
} from '../ui/media/runtimeTts';

/** Stands in for `window.SpeechService` with scriptable behaviour. */
function makeService(behaviour: 'speaks' | 'silent' | 'errors' | 'refuses') {
  const service: Record<string, unknown> = {
    calls: [] as string[],
    stopped: 0,
    voiceConfig: { enabled: true },
    stopSpeaking() {
      (service.stopped as number) += 1;
    },
    speak(text: string, callbacks: Record<string, () => void> = {}) {
      (service.calls as string[]).push(text);
      if (behaviour === 'refuses') return Promise.resolve(false);
      if (behaviour === 'errors') {
        setTimeout(() => (callbacks.onError as unknown as (e: unknown) => void)?.(
          new Error('synthesis-failed'),
        ), 0);
        return new Promise(() => {});
      }
      if (behaviour === 'silent') {
        // Neither onStart nor onEnd, and no rejection: exactly how a missing
        // voice or a muted output behaves.
        return new Promise(() => {});
      }
      setTimeout(() => {
        callbacks.onStart?.();
        callbacks.onEnd?.();
      }, 0);
      return new Promise((resolve) => setTimeout(() => resolve(true), 1));
    },
  };
  return service;
}

describe('runtime text-to-speech', () => {
  afterEach(() => {
    vi.useRealTimers();
    delete (window as unknown as { SpeechService?: unknown }).SpeechService;
  });

  it('calls the same function that speaks assistant replies', async () => {
    const service = makeService('speaks');
    const result = await speakThroughRuntime('hello', { scope: { SpeechService: service } });

    expect(result.ok).toBe(true);
    expect(result.started).toBe(true);
    expect(result.ended).toBe(true);
    expect(service.calls).toEqual(['hello']);
  });

  it('reports silence as a failure instead of a pass', async () => {
    // The whole point: a promise that never settles and no error raised is the
    // signature of a voice that produced no audio.
    const service = makeService('silent');
    const result = await speakThroughRuntime('hello', {
      scope: { SpeechService: service },
      startTimeoutMs: 20,
    });

    expect(result.ok).toBe(false);
    expect(result.failure).toBe('never_started');
    expect(result.started).toBe(false);
    // It also stops the stuck utterance rather than leaving it queued.
    expect(service.stopped).toBe(1);
  });

  it('surfaces an engine error with its message', async () => {
    const result = await speakThroughRuntime('hello', {
      scope: { SpeechService: makeService('errors') },
      startTimeoutMs: 500,
    });

    expect(result.failure).toBe('engine_error');
    expect(result.error).toContain('synthesis-failed');
  });

  it('tells a refusal apart from a fault', async () => {
    // SpeechService resolves false when TTS is switched off. That is a setting,
    // not a broken engine, and has to read differently to the user.
    const result = await speakThroughRuntime('hello', {
      scope: { SpeechService: makeService('refuses') },
      startTimeoutMs: 500,
    });

    expect(result.failure).toBe('disabled');
  });

  it('reports a missing speech service rather than throwing', async () => {
    const result = await speakThroughRuntime('hello', { scope: {} });
    expect(result.ok).toBe(false);
    expect(result.failure).toBe('unavailable');
  });

  it('respects the text-to-speech toggle before speaking at all', async () => {
    const service = makeService('speaks');
    (service.voiceConfig as { enabled: boolean }).enabled = false;

    const result = await speakThroughRuntime('hello', { scope: { SpeechService: service } });

    expect(result.failure).toBe('disabled');
    expect(service.calls).toEqual([]);
  });

  it('prefers isTTSEnabled() when the service exposes it', () => {
    expect(isRuntimeTtsEnabled({ SpeechService: { speak() {}, isTTSEnabled: () => false } }))
      .toBe(false);
    expect(isRuntimeTtsEnabled({ SpeechService: { speak() {}, isTTSEnabled: () => true } }))
      .toBe(true);
  });

  it('detects availability from the speak function, not merely the object', () => {
    expect(isRuntimeTtsAvailable({})).toBe(false);
    expect(isRuntimeTtsAvailable({ SpeechService: {} })).toBe(false);
    expect(isRuntimeTtsAvailable({ SpeechService: { speak() {} } })).toBe(true);
  });

  it('stops without throwing when nothing is loaded', () => {
    expect(() => stopRuntimeTts({})).not.toThrow();
  });

  it('keeps a start deadline, because a silent engine reports nothing', () => {
    expect(RUNTIME_TTS_START_TIMEOUT_MS).toBeGreaterThan(0);
  });
});

describe('explainRuntimeTts', () => {
  const result = (over: Partial<RuntimeTtsResult>): RuntimeTtsResult => ({
    ok: false,
    failure: 'never_started',
    started: false,
    ended: false,
    error: null,
    elapsedMs: 0,
    ...over,
  });

  it('names the voice on success and says it used the assistant path', () => {
    const verdict = explainRuntimeTts(
      result({ ok: true, failure: null, started: true, ended: true }),
      'Google US English (en-US)',
    );
    expect(verdict.ok).toBe(true);
    expect(verdict.detail).toContain('Google US English (en-US)');
    expect(verdict.detail).toContain('same path the assistant uses');
  });

  it('points at the toggle when TTS is off', () => {
    const verdict = explainRuntimeTts(result({ failure: 'disabled' }), 'any');
    expect(verdict.headline).toContain('switched off');
    expect(verdict.detail).toContain('Enable Text-to-Speech');
  });

  it('mentions the autoplay block for a silent engine', () => {
    const verdict = explainRuntimeTts(result({ failure: 'never_started' }), 'any');
    expect(verdict.detail).toContain('click once in the page');
  });

  it('says the script failed to load when the service is missing', () => {
    const verdict = explainRuntimeTts(result({ failure: 'unavailable' }), 'any');
    expect(verdict.detail).toContain('speech-service.js');
  });

  it('repeats the engine error verbatim', () => {
    const verdict = explainRuntimeTts(
      result({ failure: 'engine_error', error: 'voice-unavailable' }),
      'any',
    );
    expect(verdict.detail).toContain('voice-unavailable');
  });
});
