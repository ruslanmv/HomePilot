/**
 * Speak through the *runtime* text-to-speech path — the one live Voice uses.
 *
 * Why not call the provider directly
 * ----------------------------------
 * Assistant replies are spoken by `window.SpeechService.speak()`, which
 * `tts/shimSpeechService.ts` wraps so a non-default engine (Piper) is routed
 * through the plugin registry and the default engine keeps using the voice
 * stored in `homepilot_voice_config`.
 *
 * A Settings preview that calls `provider.speak()` directly bypasses both the
 * shim and that config, so it can pass while real assistant audio fails — and
 * fail while real audio works. Anything claiming to *test* text-to-speech has
 * to go through the same function the assistant does.
 *
 * Verifying that it worked
 * -----------------------
 * `speechSynthesis` reports no error when it produces no audio: a missing
 * voice, a muted output and a browser autoplay block all look like success. So
 * the only evidence a caller can rely on is whether `onStart` ever fired,
 * which is why this returns a verdict rather than a bare promise.
 */

import { microphoneDebug, microphoneDebugError } from './microphoneDebug';

/** How long to wait for `onStart` before calling the attempt a failure. */
export const RUNTIME_TTS_START_TIMEOUT_MS = 4000;

/** Upper bound on one utterance, so a stuck engine cannot hang the caller. */
export const RUNTIME_TTS_MAX_MS = 30_000;

export type RuntimeTtsFailure =
  | 'unavailable'
  | 'disabled'
  | 'never_started'
  | 'engine_error'
  | 'timeout';

export interface RuntimeTtsResult {
  ok: boolean;
  /** Set when `ok` is false. */
  failure: RuntimeTtsFailure | null;
  /** Whether the engine reported that it began speaking. */
  started: boolean;
  /** Whether it reported finishing. */
  ended: boolean;
  /** Raw engine error text, when there was one. */
  error: string | null;
  elapsedMs: number;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function runtimeService(scope: any = typeof window !== 'undefined' ? window : undefined): any {
  return scope?.SpeechService ?? null;
}

/** Whether the runtime speech path exists at all. */
export function isRuntimeTtsAvailable(scope?: any): boolean {
  const svc = runtimeService(scope);
  return Boolean(svc && typeof svc.speak === 'function');
}

/**
 * Whether the user has text-to-speech switched on.
 *
 * `SpeechService.speak()` resolves `false` immediately when this is off, with
 * no error and no audio — which is a legitimate setting, not a fault, and has
 * to be reported as such rather than as "the voice never started".
 */
export function isRuntimeTtsEnabled(scope?: any): boolean {
  const svc = runtimeService(scope);
  if (!svc) return false;
  if (typeof svc.isTTSEnabled === 'function') {
    try { return Boolean(svc.isTTSEnabled()); } catch { /* fall through */ }
  }
  return svc.voiceConfig?.enabled !== false;
}

/**
 * Speak `text` through the runtime path and report what actually happened.
 *
 * Never rejects: every outcome, including "the engine went silent", comes back
 * as a verdict the caller can render.
 */
export async function speakThroughRuntime(
  text: string,
  options: {
    startTimeoutMs?: number;
    maxMs?: number;
    scope?: any;
    onStart?: () => void;
  } = {},
): Promise<RuntimeTtsResult> {
  const {
    startTimeoutMs = RUNTIME_TTS_START_TIMEOUT_MS,
    maxMs = RUNTIME_TTS_MAX_MS,
    scope,
  } = options;

  const base: RuntimeTtsResult = {
    ok: false,
    failure: null,
    started: false,
    ended: false,
    error: null,
    elapsedMs: 0,
  };

  const svc = runtimeService(scope);
  if (!isRuntimeTtsAvailable(scope)) {
    microphoneDebug('settings', 'runtime_tts_unavailable');
    return { ...base, failure: 'unavailable' };
  }
  if (!isRuntimeTtsEnabled(scope)) {
    microphoneDebug('settings', 'runtime_tts_disabled');
    return { ...base, failure: 'disabled' };
  }

  const startedAt = Date.now();
  let started = false;
  let ended = false;
  let error: string | null = null;

  const settle = (failure: RuntimeTtsFailure | null): RuntimeTtsResult => ({
    ok: failure === null,
    failure,
    started,
    ended,
    error,
    elapsedMs: Date.now() - startedAt,
  });

  microphoneDebug('settings', 'runtime_tts_speak_requested', {
    characters: text.length,
    startTimeoutMs,
  });

  return new Promise<RuntimeTtsResult>((resolve) => {
    let done = false;
    let startTimer: ReturnType<typeof setTimeout> | null = null;
    let maxTimer: ReturnType<typeof setTimeout> | null = null;

    const clearTimers = () => {
      if (startTimer) clearTimeout(startTimer);
      if (maxTimer) clearTimeout(maxTimer);
      startTimer = null;
      maxTimer = null;
    };

    const finish = (failure: RuntimeTtsFailure | null) => {
      if (done) return;
      done = true;
      clearTimers();
      const result = settle(failure);
      microphoneDebug('settings', 'runtime_tts_result', {
        ok: result.ok,
        failure: result.failure,
        started: result.started,
        ended: result.ended,
        elapsedMs: result.elapsedMs,
      });
      resolve(result);
    };

    startTimer = setTimeout(() => {
      if (started) return;
      try { svc.stopSpeaking?.(); } catch { /* ignore */ }
      finish('never_started');
    }, startTimeoutMs);

    maxTimer = setTimeout(() => {
      try { svc.stopSpeaking?.(); } catch { /* ignore */ }
      finish(started ? null : 'timeout');
    }, maxMs);

    try {
      const outcome = svc.speak(text, {
        onStart: () => {
          started = true;
          if (startTimer) {
            clearTimeout(startTimer);
            startTimer = null;
          }
          try { options.onStart?.(); } catch { /* ignore */ }
        },
        onEnd: () => {
          ended = true;
          finish(started ? null : 'never_started');
        },
        onError: (engineError: unknown) => {
          error = String((engineError as { message?: string })?.message || engineError || 'error');
          finish('engine_error');
        },
      });

      // The legacy service resolves `false` when it refused to speak at all;
      // treat that as the refusal it is instead of waiting out the timeout.
      Promise.resolve(outcome)
        .then((value) => {
          if (value === false && !started) finish('disabled');
          else if (!started && !done) finish('never_started');
          else if (!done) finish(null);
        })
        .catch((engineError) => {
          error = String(engineError?.message || engineError);
          finish('engine_error');
        });
    } catch (thrown) {
      microphoneDebugError('settings', 'runtime_tts_threw', thrown);
      error = String((thrown as Error)?.message || thrown);
      finish('engine_error');
    }
  });
}

/** Stop whatever the runtime path is currently saying. */
export function stopRuntimeTts(scope?: any): void {
  const svc = runtimeService(scope);
  try { svc?.stopSpeaking?.(); } catch { /* ignore */ }
}
/* eslint-enable @typescript-eslint/no-explicit-any */

/** Human-readable verdict for a runtime speech attempt. */
export function explainRuntimeTts(
  result: RuntimeTtsResult,
  voiceLabel: string,
): { ok: boolean; headline: string; detail: string } {
  if (result.ok) {
    return {
      ok: true,
      headline: 'Text-to-speech is working',
      detail: `Spoken with ${voiceLabel} through the same path the assistant uses for replies. If you heard nothing, raise the output volume and check the speaker selected in Audio & Video.`,
    };
  }

  switch (result.failure) {
    case 'unavailable':
      return {
        ok: false,
        headline: 'The speech service did not load',
        detail:
          'HomePilot\'s speech service is not available on this page, so replies cannot be spoken. Reload the page; if it persists, the /js/speech-service.js script failed to load.',
      };
    case 'disabled':
      return {
        ok: false,
        headline: 'Text-to-speech is switched off',
        detail: 'Turn on "Enable Text-to-Speech" above, then run this test again.',
      };
    case 'engine_error':
      return {
        ok: false,
        headline: 'The speech engine reported an error',
        detail: `${result.error || 'Unknown engine error'}. Try the System Voice engine, or pick a different voice.`,
      };
    case 'timeout':
      return {
        ok: false,
        headline: 'The voice never finished speaking',
        detail:
          'The engine started but did not finish within the time limit. This usually means the selected engine is stuck — switch engines and try again.',
      };
    case 'never_started':
    default:
      return {
        ok: false,
        headline: 'The voice never started speaking',
        detail:
          'The engine accepted the text but produced no audio. Check the output device and volume in Audio & Video, confirm the selected voice is still installed, and click once in the page before retesting — browsers block audio until the page has been interacted with.',
      };
  }
}
