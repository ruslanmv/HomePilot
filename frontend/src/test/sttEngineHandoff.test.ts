/**
 * Changing the speech-to-text engine while something is already listening.
 *
 * ── The mechanism, and why it is a second subscription ───────────────────────────────────
 *
 * A surface that is merely *configured* by the engine reads it from the runtime state and
 * re-renders — `subscribeSttRuntime`, which is what the Voice capture effect keys on. A
 * surface that is **capturing right now** has a different problem: it is mid-turn on the old
 * engine, holding the microphone, with the user's half-dictated sentence in a draft. For it
 * the change is not a value to render, it is a hand-off to perform.
 *
 * `subscribeEffectiveEngine` is that signal, and it exists so the two cases a plain value
 * comparison gets wrong are filtered once rather than in every consumer:
 *
 *   - the **first** resolve of a session (`null → web-speech`) is the session starting, not a
 *     hand-off — firing there would interrupt a capture that has only just opened;
 *   - a refresh that lands the **same** engine must not interrupt a turn in progress at all.
 *
 * The consequence of not having it: the chat composer resolved the engine once, at the moment
 * the microphone button was pressed, and never looked again. Changing the engine in Settings
 * mid-dictation left it recording through the engine the user had just moved away from —
 * audio still going to the browser recognizer after they chose on-device transcription for
 * privacy, which is the one way this can be wrong that actually matters.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

vi.mock('../ui/media/sttService', () => ({
  getSttCapability: vi.fn(async () => ({
    available: true, provider: 'whisper-local', remote: false, hint: null,
  })),
  transcribeBlob: vi.fn(),
  resetSttCapabilityCache: vi.fn(),
  openSelectedMicrophone: vi.fn(),
  recordAndTranscribe: vi.fn(),
  SttUnavailableError: class SttUnavailableError extends Error {},
}));

import {
  applySttSessionOverride,
  describeEngineHandoff,
  ensureSttRuntimeResolved,
  resetSttRuntimeForTests,
  subscribeEffectiveEngine,
} from '../ui/media/sttRuntime';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const app = readFileSync(resolve(ROOT, 'frontend/src/ui/App.tsx'), 'utf8');

beforeEach(() => {
  localStorage.clear();
  resetSttRuntimeForTests();
  (window as unknown as { SpeechRecognition: unknown }).SpeechRecognition = class {};
  (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = class {};
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn(), enumerateDevices: vi.fn(async () => []) },
  });
});

describe('the engine hand-off signal', () => {
  it('stays quiet while the session is deciding its first engine', async () => {
    // `null → web-speech` is the session starting. A hand-off here would tear down a capture
    // that has only just opened, on behalf of a change that never happened.
    const seen: string[] = [];
    subscribeEffectiveEngine((next) => seen.push(next));
    await ensureSttRuntimeResolved();

    expect(seen).toEqual([]);
  });

  it('fires once when the engine really changes', async () => {
    await ensureSttRuntimeResolved();
    const seen: Array<[string, string]> = [];
    subscribeEffectiveEngine((next, previous) => seen.push([previous, next]));

    applySttSessionOverride('homepilot-backend', 'because', 'chat');

    expect(seen).toEqual([['web-speech', 'homepilot-backend']]);
  });

  it('does not fire when a change lands the same engine', async () => {
    await ensureSttRuntimeResolved();
    applySttSessionOverride('homepilot-backend', 'because', 'chat');

    const seen: string[] = [];
    subscribeEffectiveEngine((next) => seen.push(next));
    applySttSessionOverride('homepilot-backend', 'again', 'voice');

    // Re-announcing would restart a healthy capture for nothing.
    expect(seen).toEqual([]);
  });

  it('reaches every surface, not just the one that caused it', async () => {
    await ensureSttRuntimeResolved();
    const voice: string[] = [];
    const chat: string[] = [];
    subscribeEffectiveEngine((next) => voice.push(next));
    subscribeEffectiveEngine((next) => chat.push(next));

    applySttSessionOverride('homepilot-backend', 'because', 'chat');

    expect(voice).toEqual(['homepilot-backend']);
    expect(chat).toEqual(['homepilot-backend']);
  });

  it('keeps going when one subscriber throws', async () => {
    // A surface that fails to hand over must not strand the others on the old engine.
    await ensureSttRuntimeResolved();
    const survived: string[] = [];
    subscribeEffectiveEngine(() => { throw new Error('broken surface'); });
    subscribeEffectiveEngine((next) => survived.push(next));

    applySttSessionOverride('homepilot-backend', 'because', 'chat');

    expect(survived).toEqual(['homepilot-backend']);
  });

  it('stops firing once unsubscribed', async () => {
    await ensureSttRuntimeResolved();
    const seen: string[] = [];
    const off = subscribeEffectiveEngine((next) => seen.push(next));
    off();

    applySttSessionOverride('homepilot-backend', 'because', 'chat');

    expect(seen).toEqual([]);
  });
});

describe('what the user is told', () => {
  it('names where the audio goes now, both ways', () => {
    // The engine decides which service sees the audio — the browser recognizer sends it to
    // Google, HomePilot's own keeps it on the machine — so a hand-off is never silent.
    expect(describeEngineHandoff('homepilot-backend', 'whisper-local'))
      .toContain('on this computer');
    expect(describeEngineHandoff('homepilot-backend', 'whisper-local'))
      .toContain('whisper-local');
    expect(describeEngineHandoff('web-speech', null))
      .toContain('system default input');
  });

  it('reads as a confirmation rather than a fault report', () => {
    // The user asked for this in Settings. Repeating the paragraph that explains a deaf
    // recognizer would put a problem report in front of somebody who has just fixed one.
    const line = describeEngineHandoff('homepilot-backend', null);
    expect(line).toContain('Switched to');
    expect(line).not.toContain('could not');
    expect(line).not.toContain('found no speech');
  });
});

describe('the chat composer hands the microphone over', () => {
  /*
   * Source-level, because the behaviour lives in the ordering of two effects rather than in a
   * value: the stop is asynchronous, so reopening the microphone from inside the subscription
   * would race the teardown for the same device.
   */
  it('subscribes to the engine rather than resolving once at click time', () => {
    expect(app).toContain('subscribeEffectiveEngine');
    expect(app).toContain('composer_mic_engine_handoff');
  });

  it('stops the running turn in a way that keeps what was said', () => {
    // Stopping the backend path transcribes the clip rather than discarding it; stopping the
    // browser path lets its final result land. Either way the words already spoken reach the
    // draft, and `micBaseTextRef` means the restart appends to it.
    const handoff = app.slice(app.indexOf('subscribeEffectiveEngine((next)'));
    expect(handoff).toContain('setMicTranscribing(true)');
    expect(handoff).toContain('micStopRecordingRef.current()');
    // Suppresses the auto-resume, which would reopen the *old* engine as this stop lands.
    expect(handoff).toContain('micStoppingRef.current = true');
    expect(handoff).toContain("stopWebSpeech('chat', { reason: 'stt_engine_changed', force: true })");
  });

  it('restarts only after listening has actually stopped', () => {
    // The restart waits on `isListening` falling rather than running inside the subscription.
    expect(app).toContain('pendingEngineHandoffRef');
    const restart = app.slice(app.indexOf('const next = pendingEngineHandoffRef.current'));
    expect(restart.slice(0, 260)).toContain('if (!next || isListening) return');
    expect(restart.slice(0, 260)).toContain('startDictationOn(next)');
  });

  it('starts through the same path a click would', () => {
    // A second, subtly different start path is how the two diverge and only one gets fixed.
    expect(app).toContain('const startDictationOn = useCallback');
    expect(app).toContain('await startDictationOn(effectiveEngine)');
  });

  it('does nothing to a composer that is not listening', () => {
    // Changing the engine with the microphone closed is a preference change, not a hand-off.
    const handoff = app.slice(app.indexOf('subscribeEffectiveEngine((next)'));
    expect(handoff).toContain('if (!isListeningRef.current) return');
  });
});
