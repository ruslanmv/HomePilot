/**
 * The one browser speech recognizer, with an owner.
 *
 * ── Why this is a module and not two copies ──────────────────────────────────────────────
 *
 * A page can run exactly one `SpeechRecognition` session at a time. HomePilot had two
 * independent ones: the Voice tab drove the global `window.SpeechService`, while the chat
 * composer constructed `new SpeechRecognition()` itself. The composer knew this was a
 * problem — it aborted the shared session before taking its turn — but nothing did the
 * reverse, so a recognizer started in chat could outlive the composer that started it and
 * make the next Voice turn fail with a bare `InvalidStateError`.
 *
 * That is ownership being coordinated at the edges. Here it is coordinated in one place:
 * whoever calls {@link startWebSpeech} becomes the owner, the previous owner's session is
 * dropped first, and events are delivered only to the owner that is current when they
 * arrive. One recognizer, one lifecycle, one diagnostic record, one place to abort.
 *
 * ── The device caveat, stated once ──────────────────────────────────────────────────────
 *
 * `SpeechRecognition` accepts no `deviceId`. It records the operating system's default
 * input, never the microphone selected in Audio & Video, and it opens that capture itself —
 * it cannot be handed a `MediaStream`. That is precisely why nothing else may hold a
 * microphone while this runs; see `media/sttRuntime`.
 */

import { microphoneDebug, microphoneDebugError } from './microphoneDebug';
import { getSpeechRecognitionCtor, type SttDiagnostics } from './voiceSelfTest';
import type { MicrophoneOwner } from './sttRuntime';

export interface WebSpeechHandlers {
  onStart?: () => void;
  /** Words as they are being recognized — the live transcript surfaces show. */
  onInterim?: (text: string) => void;
  onResult?: (text: string) => void;
  /** Always fires once per turn, with the evidence about what the capture heard. */
  onEnd?: (diagnostics: SttDiagnostics) => void;
  onError?: (code: string) => void;
}

interface Session {
  owner: MicrophoneOwner;
  generation: number;
  handlers: WebSpeechHandlers;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type SpeechService = any;

function speechService(): SpeechService | null {
  return typeof window !== 'undefined' ? (window as any).SpeechService ?? null : null;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

let session: Session | null = null;
let generation = 0;
let dispatcherInstalled = false;
/** Only used when `window.SpeechService` is absent — see {@link startNativeRecognition}. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let nativeRecognition: any = null;
let nativeDiagnostics: SttDiagnostics = {};

export function isWebSpeechSupported(): boolean {
  const svc = speechService();
  if (svc?.isRecognitionSupported) return true;
  return Boolean(getSpeechRecognitionCtor());
}

export function getWebSpeechOwner(): MicrophoneOwner | null {
  return session?.owner ?? null;
}

export function isWebSpeechActive(): boolean {
  const svc = speechService();
  if (svc) return Boolean(svc.isRecognizing);
  return Boolean(nativeRecognition);
}

export function getWebSpeechDiagnostics(): SttDiagnostics {
  const svc = speechService();
  if (svc?.getSttDiagnostics) return svc.getSttDiagnostics() || {};
  return nativeDiagnostics;
}

/**
 * Route a recognizer event to the session that is current *now*.
 *
 * The generation check is what makes a hand-off clean: a recognizer aborted mid-turn still
 * emits its `onend`, and delivering that to the surface that has since taken over would end
 * a turn that just started.
 */
function deliver(
  event: keyof WebSpeechHandlers,
  gen: number,
  apply: (handlers: WebSpeechHandlers) => void,
): void {
  const current = session;
  if (!current || current.generation !== gen) return;
  const handler = current.handlers[event];
  if (!handler) return;
  apply(current.handlers);
}

function installDispatcher(svc: SpeechService): void {
  if (dispatcherInstalled) return;
  dispatcherInstalled = true;
  svc.setRecognitionCallbacks({
    onStart: () => deliver('onStart', session?.generation ?? -1, (h) => h.onStart?.()),
    onInterim: (text: string) =>
      deliver('onInterim', session?.generation ?? -1, (h) => h.onInterim?.(text)),
    onResult: (text: string) =>
      deliver('onResult', session?.generation ?? -1, (h) => h.onResult?.(text)),
    onError: (code: string) =>
      deliver('onError', session?.generation ?? -1, (h) => h.onError?.(code || 'stt_error')),
    onEnd: () => {
      const diagnostics: SttDiagnostics = svc.getSttDiagnostics?.() || {};
      const ending = session;
      deliver('onEnd', ending?.generation ?? -1, (h) => h.onEnd?.(diagnostics));
      if (session && ending && session.generation === ending.generation) session = null;
    },
  });
}

/**
 * Take the recognizer for one surface.
 *
 * Resolves `true` when a session is genuinely live. Anything else is reported rather than
 * swallowed: a button that silently does nothing is the failure this whole area has been
 * chasing.
 */
export async function startWebSpeech(
  owner: MicrophoneOwner,
  handlers: WebSpeechHandlers,
): Promise<boolean> {
  if (!isWebSpeechSupported()) {
    microphoneDebug(owner === 'voice' ? 'voice' : 'chat', 'web_speech_unsupported', { owner });
    handlers.onError?.('not-supported');
    return false;
  }

  // One recognizer means the previous turn ends before this one starts — never two live
  // sessions, and never a stale `onend` landing on the new owner.
  if (session || isWebSpeechActive()) abortWebSpeech('handoff');

  const gen = ++generation;
  session = { owner, generation: gen, handlers };

  const svc = speechService();
  const scope = owner === 'voice' ? 'voice' : 'chat';
  microphoneDebug(scope, 'web_speech_start_requested', {
    owner,
    via: svc ? 'speech-service' : 'native',
    recognitionDevice: 'browser-managed-web-speech',
  });

  if (svc) {
    installDispatcher(svc);
    try {
      const started = await Promise.resolve(svc.startSTT({}));
      if (started || svc.isRecognizing) return true;
      microphoneDebug(scope, 'web_speech_start_rejected', { owner, started: Boolean(started) });
      session = null;
      handlers.onError?.('start_failed');
      return false;
    } catch (error) {
      microphoneDebugError(scope, 'web_speech_start_failed', error, { owner });
      session = null;
      handlers.onError?.(
        (error as { name?: string })?.name || 'start_failed',
      );
      return false;
    }
  }

  return startNativeRecognition(owner, gen, handlers);
}

/**
 * The same lifecycle without `window.SpeechService`.
 *
 * The global script is served from `public/` and is normally present; this keeps voice input
 * working if it is not, rather than reintroducing a second recognizer implementation that
 * happens to be reachable only in that case. Same ownership, same diagnostics, same events.
 */
function startNativeRecognition(
  owner: MicrophoneOwner,
  gen: number,
  handlers: WebSpeechHandlers,
): boolean {
  const Ctor = getSpeechRecognitionCtor();
  if (!Ctor) {
    session = null;
    handlers.onError?.('not-supported');
    return false;
  }

  const lang =
    (typeof navigator !== 'undefined' && navigator.language) || 'en-US';
  nativeDiagnostics = {
    sawAudioStart: false,
    sawSpeechStart: false,
    sawInterim: false,
    sawResult: false,
    sawNoMatch: false,
    error: null,
    lang,
  };

  const recognition = new Ctor();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = lang;
  nativeRecognition = recognition;

  recognition.onstart = () => deliver('onStart', gen, (h) => h.onStart?.());
  recognition.onaudiostart = () => { nativeDiagnostics.sawAudioStart = true; };
  recognition.onspeechstart = () => { nativeDiagnostics.sawSpeechStart = true; };
  recognition.onnomatch = () => { nativeDiagnostics.sawNoMatch = true; };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  recognition.onerror = (event: any) => {
    nativeDiagnostics.error = event?.error || 'unknown';
    deliver('onError', gen, (h) => h.onError?.(nativeDiagnostics.error || 'stt_error'));
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  recognition.onresult = (event: any) => {
    let final = '';
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) final += `${transcript} `;
      else interim += transcript;
    }
    if (interim) {
      nativeDiagnostics.sawInterim = true;
      deliver('onInterim', gen, (h) => h.onInterim?.(interim.trim()));
    }
    if (final.trim()) {
      nativeDiagnostics.sawResult = true;
      deliver('onResult', gen, (h) => h.onResult?.(final.trim()));
    }
  };
  recognition.onend = () => {
    nativeRecognition = null;
    const ending = session;
    deliver('onEnd', gen, (h) => h.onEnd?.(nativeDiagnostics));
    if (session && ending && session.generation === ending.generation) session = null;
  };

  try {
    recognition.start();
    return true;
  } catch (error) {
    nativeRecognition = null;
    session = null;
    microphoneDebugError(owner === 'voice' ? 'voice' : 'chat', 'web_speech_start_failed', error);
    handlers.onError?.((error as { name?: string })?.name || 'start_failed');
    return false;
  }
}

/**
 * Ask the current turn to finish and produce its transcript.
 *
 * A stop from anyone but the owner is ignored — that is a stale timer from a surface that
 * has already handed the microphone on, and honouring it would cut the new owner's turn.
 */
export function stopWebSpeech(
  owner: MicrophoneOwner,
  options: { reason?: string; force?: boolean } = {},
): boolean {
  if (!session || session.owner !== owner) return false;
  const reason = options.reason || 'unspecified';
  const svc = speechService();
  if (svc?.stopSTT) {
    // Not forced by default: `SpeechService` defers a stop that would cut the recognizer off
    // during warm-up, which is what silently produced empty turns for short utterances.
    return Boolean(svc.stopSTT({ reason, force: Boolean(options.force) }));
  }
  if (!nativeRecognition) return false;
  try {
    nativeRecognition.stop();
    return true;
  } catch {
    return false;
  }
}

/** Drop the current turn now, transcript or not. Used for hand-offs and teardown. */
export function abortWebSpeech(reason = 'abort'): void {
  const ending = session;
  session = null;
  const svc = speechService();
  if (svc?.abortSTT) {
    try { svc.abortSTT(reason); } catch { /* already gone */ }
  }
  if (nativeRecognition) {
    try { nativeRecognition.abort(); } catch { /* already gone */ }
    nativeRecognition = null;
  }
  if (ending) {
    microphoneDebug(ending.owner === 'voice' ? 'voice' : 'chat', 'web_speech_aborted', {
      owner: ending.owner,
      reason,
    });
  }
}

/** Test seam: forget the page-scoped recognizer state between files. */
export function resetWebSpeechForTests(): void {
  session = null;
  generation = 0;
  dispatcherInstalled = false;
  nativeRecognition = null;
  nativeDiagnostics = {};
}
