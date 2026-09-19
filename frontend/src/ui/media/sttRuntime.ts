/**
 * One speech-to-text session for the whole app: which engine is running, and who owns the
 * microphone right now.
 *
 * ── The bug this module exists to make impossible ────────────────────────────────────────
 *
 * Settings offers Browser / On this computer / Automatic as *one* choice shared by the chat
 * composer and the Voice tab, which is the right product model. The implementation did not
 * match it. Three separate copies of the decision existed:
 *
 *   - `useVoiceController` kept its own `sttEngine` state,
 *   - the chat composer kept `micEngineOverrideRef` plus a per-press resolution,
 *   - and each surface re-probed the capability independently.
 *
 * So a recovery in one surface was invisible to the other, and — far worse — hands-free Voice
 * would start HomePilot's VAD (which opens and *holds* the microphone selected in Audio &
 * Video) and then ask the browser's `SpeechRecognition` to transcribe. Web Speech takes no
 * `deviceId`; it opens the operating system's default input on its own. Two captures, two
 * devices, one turn:
 *
 *     [vad]  capture_opened            ← the selected microphone, held open all session
 *     [voice] stt_onstart              ← a *second* capture, on the OS default
 *     [voice] stt_onend { hadResult: false, sawSpeechStart: false }
 *
 * The meter moved, the orb reacted, and nothing came out. No timeout or grace period can fix
 * that, because the recognizer was never listening to the microphone the meter was reading.
 *
 * ── The rule ────────────────────────────────────────────────────────────────────────────
 *
 * The engine decides who owns the microphone, and only one owner exists at a time:
 *
 *   - `web-speech`        → the browser recognizer is the sole capture. No VAD, no recorder.
 *   - `homepilot-backend` → HomePilot's VAD/recorder is the sole capture. No recognizer.
 *
 * Everything here is deliberately free of React so both the decision and the ownership
 * hand-off can be tested directly, and so the two surfaces genuinely share one object rather
 * than two copies that agree by coincidence.
 */

import { getSttCapability, type SttCapability } from './sttService';
import { microphoneDebug } from './microphoneDebug';
import { getMediaPreferences } from './mediaPreferences';
import { describeMicrophoneRouting, type MicrophoneRoutingNotice } from './voiceSelfTest';
import {
  describeSttResolution,
  getSttPreferences,
  hasStoredSttPreferences,
  resolveSttEngine,
  subscribeSttPreferences,
  type ResolvedSttEngine,
  type SttEnginePreference,
  type SttResolution,
} from './sttPreferences';

/** Which surface is holding, or wants to hold, the microphone. */
export type MicrophoneOwner = 'chat' | 'voice' | 'settings';

export type SttRuntimeStatus =
  /** The capability probe has not answered yet. Nothing may open a capture. */
  | 'pending'
  /** `effectiveEngine` is decided. */
  | 'ready';

export interface SttRuntimeState {
  status: SttRuntimeStatus;
  preference: SttEnginePreference;
  capability: SttCapability | null;
  resolution: SttResolution | null;
  /**
   * The engine that actually runs, override included. `null` while `status` is `pending`.
   *
   * Deliberately not defaulted to `web-speech` during the probe. That default is what made
   * the first spoken sentence of a session run through the browser recognizer on a machine
   * whose preference was `homepilot` — the turn that matters most, taken by the engine the
   * user did not choose, purely because `/v1/voice/stt/status` was still in flight.
   */
  effectiveEngine: ResolvedSttEngine | null;
  /** Set by the deaf-recognizer recovery. Session-only: the stored preference stays the user's. */
  sessionOverride: ResolvedSttEngine | null;
  /** Why the override exists, in words, for whichever surface wants to show it. */
  sessionOverrideMessage: string | null;
  /** Identifies automatic routing overrides so surfaces can choose how prominently to show them. */
  sessionOverrideReason: 'routing-mismatch' | 'recognizer-deaf' | 'recovery' | null;
  /** HomePilot's own transcription can run here, so a recovery has somewhere to go. */
  backendUsable: boolean;
  /**
   * Whether the selected microphone and the OS default input are the same device.
   *
   * `null` until it has been looked at. `known: false` means the browser exposed no
   * `default` alias to compare against, which is not the same as "they agree".
   */
  routing: MicrophoneRoutingNotice | null;
}

/**
 * Read the device list and decide whether the browser recognizer can hear the selected
 * microphone at all.
 *
 * Never throws and never blocks a decision: a machine that refuses to enumerate devices gets
 * "cannot tell", and "cannot tell" changes nothing.
 */
async function readRouting(): Promise<MicrophoneRoutingNotice> {
  const unknown: MicrophoneRoutingNotice = {
    mismatch: false,
    known: false,
    defaultLabel: null,
    message: null,
  };
  try {
    if (!navigator.mediaDevices?.enumerateDevices) return unknown;
    const devices = await navigator.mediaDevices.enumerateDevices();
    return describeMicrophoneRouting(devices, getMediaPreferences().microphoneDeviceId);
  } catch {
    return unknown;
  }
}

const ROUTING_OVERRIDE_MESSAGE =
  'The microphone you selected in Audio & Video is not your system default input, and the '
  + 'browser’s speech recognition can only record the system default — so it would have '
  + 'captured a device you are not speaking into. HomePilot is transcribing on this computer '
  + 'for this session instead, which records the microphone you chose. Change this in '
  + 'Settings → Voice Assistant → Speech Recognition.';

const REMEMBERED_OVERRIDE_MESSAGE =
  'Transcribing on this computer, because the browser’s speech recognition could not hear '
  + 'this microphone last time. Change this in Settings → Voice Assistant → Speech Recognition.';

/**
 * Which microphone the browser recognizer has already been proven unable to hear.
 *
 * ── Why this is remembered across reloads ────────────────────────────────────────────────
 *
 * The preflight below compares the selected device against the browser's `default` alias, and
 * on a great many machines — Chrome on Windows among them — there is no such alias to compare
 * against. There the split is real and undetectable, so the only thing that establishes it is
 * a turn: the user presses record, speaks, and the recognizer reports that it opened a
 * capture and heard nothing.
 *
 * Paying for that discovery once is reasonable. Paying for it on every page load is not, and
 * that is what was happening: each reload started a fresh session, offered the browser
 * recognizer again, and burned the user's first sentence proving the same fact over again.
 *
 * So the verdict is kept, keyed by the device it was reached about. A different microphone is
 * a different question and re-evaluated; and choosing an engine in Settings clears it, because
 * a user who insists on the browser after being told twice has decided.
 */
const DEAF_RECOGNIZER_STORAGE_KEY = 'homepilot_stt_deaf_recognizer_v1';

function selectedMicrophoneKey(): string {
  return getMediaPreferences().microphoneDeviceId || 'system-default';
}

/** Record that the browser recognizer could not hear the microphone in use right now. */
export function rememberRecognizerIsDeaf(): void {
  try {
    window.localStorage?.setItem(
      DEAF_RECOGNIZER_STORAGE_KEY,
      JSON.stringify({ deviceId: selectedMicrophoneKey(), at: Date.now() }),
    );
  } catch {
    // A locked-down context still gets the session-scoped override; it just re-learns later.
  }
}

export function forgetRecognizerIsDeaf(): void {
  try {
    window.localStorage?.removeItem(DEAF_RECOGNIZER_STORAGE_KEY);
  } catch {
    // Nothing to clean up that matters.
  }
}

/** Whether *this* microphone is the one already proven inaudible to the recognizer. */
export function recognizerKnownDeaf(): boolean {
  try {
    const saved = window.localStorage?.getItem(DEAF_RECOGNIZER_STORAGE_KEY);
    if (!saved) return false;
    const parsed = JSON.parse(saved);
    return parsed?.deviceId === selectedMicrophoneKey();
  } catch {
    return false;
  }
}

function webSpeechSupported(): boolean {
  if (typeof window === 'undefined') return false;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const scope = window as any;
  return Boolean(scope.SpeechRecognition || scope.webkitSpeechRecognition);
}

function mediaRecorderSupported(): boolean {
  return (
    typeof window !== 'undefined'
    && typeof MediaRecorder !== 'undefined'
    && Boolean(navigator.mediaDevices?.getUserMedia)
  );
}

const INITIAL: SttRuntimeState = {
  status: 'pending',
  preference: 'web-speech',
  capability: null,
  resolution: null,
  effectiveEngine: null,
  sessionOverride: null,
  sessionOverrideMessage: null,
  sessionOverrideReason: null,
  backendUsable: false,
  routing: null,
};

let state: SttRuntimeState = { ...INITIAL };
let listeners = new Set<(next: SttRuntimeState) => void>();
let inFlight: Promise<SttRuntimeState> | null = null;
let preferenceSubscription: (() => void) | null = null;
/**
 * Whether the routing preflight may still move this session off the browser recognizer.
 *
 * It applies once, unasked, because the alternative is knowingly recording a device the user
 * is not speaking into. But re-picking an engine in Settings is the user insisting, and an
 * override that cannot be overridden is not a session default — it is the choice being taken
 * away. So a preference change disarms it for the rest of the session.
 */
let routingPreflightArmed = true;

/**
 * Watchers of the engine *changing*, as opposed to watchers of the state.
 *
 * ── Why this is a second subscription and not a `useEffect` on the state ─────────────────
 *
 * A surface that is merely *configured* by the engine can read it from the state and re-render;
 * that is what `subscribeSttRuntime` is for, and the Voice capture effect keys on it directly.
 * A surface that is **capturing right now** has a different problem: it is mid-turn on the old
 * engine, holding the microphone, with the user's half-dictated sentence in a draft. For it,
 * the change is not a new value to render — it is a hand-off to perform.
 *
 * Those two need different signals, because the interesting cases are exactly the ones a value
 * comparison gets wrong: a re-resolve that lands the *same* engine must not interrupt a turn in
 * progress, and the first resolve of a session (`null → web-speech`) is the session starting
 * rather than a hand-off, so it must not either. Both are filtered here, once, instead of in
 * every consumer.
 */
type EngineHandoffListener = (
  next: ResolvedSttEngine,
  previous: ResolvedSttEngine,
) => void;

let engineListeners = new Set<EngineHandoffListener>();

/**
 * The engine the hand-off listeners have already been told about.
 *
 * Deliberately separate from `state.effectiveEngine`: the state is replaced wholesale by every
 * refresh, and comparing a snapshot against the one before it inside a subscriber is how each
 * surface would end up with its own — differently wrong — idea of what counts as a change.
 */
let announcedEngine: ResolvedSttEngine | null = null;

/**
 * Be told when the engine actually changes under an active capture.
 *
 * Fires only for engine → *different* engine. Never for the first resolve of a session, and
 * never for a refresh that lands the same engine.
 */
export function subscribeEffectiveEngine(listener: EngineHandoffListener): () => void {
  engineListeners.add(listener);
  ensurePreferenceSubscription();
  return () => { engineListeners.delete(listener); };
}

function emit(): void {
  const snapshot = state;
  listeners.forEach((listener) => {
    try {
      listener(snapshot);
    } catch {
      // One bad subscriber must never stop the others from learning the engine changed.
    }
  });

  if (snapshot.effectiveEngine === announcedEngine) return;
  const previous = announcedEngine;
  announcedEngine = snapshot.effectiveEngine;
  if (!previous || !snapshot.effectiveEngine) return;

  microphoneDebug('settings', 'stt_engine_handoff', {
    from: previous,
    to: snapshot.effectiveEngine,
    reason: snapshot.sessionOverride ? 'session-override' : snapshot.resolution?.reason ?? null,
    holder: lease?.owner ?? null,
  });
  engineListeners.forEach((listener) => {
    try {
      listener(snapshot.effectiveEngine as ResolvedSttEngine, previous);
    } catch {
      // A surface that fails to hand over must not strand the others on the old engine.
    }
  });
}

function update(patch: Partial<SttRuntimeState>): SttRuntimeState {
  state = { ...state, ...patch };
  emit();
  return state;
}

export function getSttRuntime(): SttRuntimeState {
  return state;
}

/**
 * What the OS default input — the only device the browser recognizer can record — is called.
 *
 * Read from the routing preflight, which has been enumerating devices all along; this simply
 * stops throwing the label away. `null` on a browser that exposes no `default` alias, and
 * every caller has to read correctly without it.
 */
export function systemDefaultMicrophoneLabel(): string | null {
  return state.routing?.defaultLabel ?? null;
}

/**
 * Watch the shared engine decision.
 *
 * Every surface subscribes rather than caching its own copy, which is the whole point: a
 * recovery, a preference change or a capability refresh reaches chat and Voice at the same
 * moment and with the same value.
 */
export function subscribeSttRuntime(listener: (next: SttRuntimeState) => void): () => void {
  listeners.add(listener);
  ensurePreferenceSubscription();
  return () => { listeners.delete(listener); };
}

function ensurePreferenceSubscription(): void {
  if (preferenceSubscription || typeof window === 'undefined') return;
  preferenceSubscription = subscribeSttPreferences(() => {
    // Choosing an engine in Settings is a deliberate act and outranks a recovery HomePilot
    // made on its own, in both surfaces at once — including the routing preflight, which
    // would otherwise re-apply on the next resolve and make "Browser" unselectable on a
    // machine whose default input differs. Insisting has to mean something.
    state = {
      ...state,
      sessionOverride: null,
      sessionOverrideMessage: null,
      sessionOverrideReason: null,
    };
    routingPreflightArmed = false;
    // Across reloads too. A user who picks the browser again after being told the recognizer
    // cannot hear their microphone has decided, and a remembered verdict that survives that
    // is not a memory — it is the choice being refused.
    forgetRecognizerIsDeaf();
    void refreshSttRuntime({ force: true });
  });
}

function decide(
  capability: SttCapability,
  preference: SttEnginePreference,
  routing: MicrophoneRoutingNotice,
): SttRuntimeState {
  const resolution = resolveSttEngine(preference, {
    backendAvailable: capability.available,
    mediaRecorderSupported: mediaRecorderSupported(),
    webSpeechSupported: webSpeechSupported(),
  });
  const backendUsable = capability.available && mediaRecorderSupported();
  let override = state.sessionOverride && backendUsable ? state.sessionOverride : null;
  let overrideMessage = override ? state.sessionOverrideMessage : null;
  let sessionOverrideReason = override ? state.sessionOverrideReason : null;
  let overrideReason = override ? 'session-override' : null;

  /*
   * The preflight. `SpeechRecognition` records the operating system's default input and
   * accepts no `deviceId`, so when the microphone chosen in Audio & Video is a *different*
   * device, a browser turn is recording a microphone nobody is speaking into. That produces
   * no error — the recognizer faithfully transcribes a silent room — and the only trace of it
   * is `sawAudioStart: true, sawSpeechStart: false` after the turn is already lost.
   *
   * This was detectable the whole time: `describeMicrophoneRouting` compares the selected
   * device against the browser's `default` alias, and Settings has been *warning* about it
   * for several batches while chat and Voice went on opening the capture anyway. Learning it
   * from two failed turns, when the device list said so before the first one, is a worse
   * product than simply not starting a capture we can already tell will be deaf.
   *
   * Gated on `known`, because "the browser exposes no default alias" is not evidence of
   * agreement, and on `backendUsable`, because there is no point moving a session to an
   * engine that cannot run. Announced, never silent — it changes which service sees the audio.
   */
  const remembered = recognizerKnownDeaf();
  if (
    !override
    && routingPreflightArmed
    // A stored selection is an instruction, not a default for HomePilot to improve. Keeping
    // this distinction across reloads is what makes all three Settings choices persistent.
    && !hasStoredSttPreferences()
    && backendUsable
    && resolution.engine === 'web-speech'
    && ((routing.known && routing.mismatch) || remembered)
  ) {
    override = 'homepilot-backend';
    // A remembered verdict needs no re-explanation of the mechanism — it was explained when
    // it was discovered, and repeating a paragraph every load is its own kind of noise.
    overrideMessage = remembered && !(routing.known && routing.mismatch)
      ? REMEMBERED_OVERRIDE_MESSAGE
      : ROUTING_OVERRIDE_MESSAGE;
    overrideReason = remembered && !(routing.known && routing.mismatch)
      ? 'recognizer-known-deaf'
      : 'routing-mismatch-preflight';
    sessionOverrideReason = remembered && !(routing.known && routing.mismatch)
      ? 'recognizer-deaf'
      : 'routing-mismatch';
  }

  const next = update({
    status: 'ready',
    preference,
    capability,
    resolution,
    backendUsable,
    routing,
    sessionOverride: override,
    sessionOverrideMessage: overrideMessage,
    sessionOverrideReason,
    effectiveEngine: override ?? resolution.engine,
  });

  microphoneDebug('settings', 'stt_runtime_resolved', {
    preference,
    engine: next.effectiveEngine,
    reason: overrideReason ?? resolution.reason,
    // A choice that was overridden has to be visible. Somebody who picked on-device
    // transcription for privacy and is quietly served the browser's — which ships audio to
    // Google — has been failed in a way no later message makes up for.
    fellBack: resolution.fellBack,
    usable: resolution.usable,
    provider: capability.provider,
    remote: capability.remote,
    usesOsDefaultInput: next.effectiveEngine === 'web-speech',
    // The evidence behind a preflight switch, and the reason one did not happen.
    selectedDeviceId: getMediaPreferences().microphoneDeviceId || 'system-default',
    routingMismatch: routing.mismatch,
    routingKnown: routing.known,
    routingPreflightArmed,
    recognizerKnownDeaf: remembered,
  });
  return next;
}

/**
 * Resolve the engine, probing the server if needed.
 *
 * Concurrent callers join one probe: chat and Voice mounting together must not race to two
 * different answers, and `getSttCapability` caches anyway, so this costs a round trip once
 * per session rather than once per surface.
 */
export function ensureSttRuntimeResolved(
  options: { force?: boolean } = {},
): Promise<SttRuntimeState> {
  ensurePreferenceSubscription();
  if (!options.force && state.status === 'ready') return Promise.resolve(state);
  if (inFlight) return inFlight;

  const preference = getSttPreferences().chat;
  inFlight = Promise.all([getSttCapability({ force: options.force }), readRouting()])
    .then(([capability, routing]) => decide(capability, preference, routing))
    .finally(() => { inFlight = null; });
  return inFlight;
}

/** Re-probe and re-decide, e.g. after the backend URL or the preference changed. */
export function refreshSttRuntime(options: { force?: boolean } = {}): Promise<SttRuntimeState> {
  inFlight = null;
  return ensureSttRuntimeResolved({ force: options.force ?? true });
}

/**
 * Move this session onto another engine without touching the stored preference.
 *
 * Used by the deaf-recognizer recovery. It applies to *both* surfaces, because it is one
 * session: a recognizer that cannot hear the user in Voice cannot hear them in chat either,
 * and a recovery only one surface knows about is the inconsistency this module removes.
 */
export function applySttSessionOverride(
  engine: ResolvedSttEngine,
  message: string,
  origin: MicrophoneOwner,
): SttRuntimeState {
  if (engine === 'homepilot-backend' && !state.backendUsable) return state;
  microphoneDebug(origin === 'voice' ? 'voice' : 'chat', 'stt_session_override', {
    engine,
    previous: state.effectiveEngine,
  });
  return update({
    sessionOverride: engine,
    sessionOverrideMessage: message,
    sessionOverrideReason: 'recovery',
    effectiveEngine: engine,
  });
}

export function clearSttSessionOverride(): SttRuntimeState {
  if (!state.sessionOverride) return state;
  return update({
    sessionOverride: null,
    sessionOverrideMessage: null,
    sessionOverrideReason: null,
    effectiveEngine: state.resolution?.engine ?? null,
  });
}

/**
 * One sentence naming the engine that is really running, override included.
 *
 * `describeSttResolution` describes the *resolution*, which is the engine the preference
 * resolves to — and that is not the engine in use once a session override is in force. Every
 * surface that reported the resolution while the runtime had already moved was telling the
 * user something that had stopped being true, which is how Settings came to say "Using the
 * browser's speech recognition" about a session that was transcribing on this computer.
 */
export function describeSttRuntime(state: SttRuntimeState): string {
  if (state.status !== 'ready' || !state.resolution) {
    return 'Working out which speech-to-text engine to use…';
  }
  if (state.sessionOverride === 'homepilot-backend') {
    const provider = state.capability?.provider;
    return `Transcribing on this computer${provider ? ` (${provider})` : ''}, using the `
      + 'microphone selected in Audio & Video — not the engine chosen in Settings. '
      + `${state.sessionOverrideMessage || ''}`.trim();
  }
  if (state.sessionOverride === 'web-speech') {
    return 'Using the browser’s speech recognition, which records your system default input '
      + `— not the engine chosen in Settings. ${state.sessionOverrideMessage || ''}`.trim();
  }
  return describeSttResolution(state.resolution, state.capability?.provider ?? null);
}

/**
 * What to say when the engine changed under a capture that was already running.
 *
 * A confirmation, not a warning, and short enough to read without stopping. The engine decides
 * **where the audio goes** — the browser recognizer sends it to Google, HomePilot's own keeps
 * it on the machine — so a hand-off is never silent. But it is also not a fault: the user
 * asked for it in Settings, and repeating the paragraph that explains a deaf recognizer here
 * would put a problem report in front of somebody who has just fixed the problem.
 */
export function describeEngineHandoff(next: ResolvedSttEngine, provider?: string | null): string {
  if (next === 'homepilot-backend') {
    return `Switched to transcribing on this computer${provider ? ` (${provider})` : ''}, `
      + 'using the microphone selected in Audio & Video.';
  }
  return 'Switched to the browser’s speech recognition, which records your system default '
    + 'input rather than the microphone selected in Audio & Video.';
}

/* ────────────────────────────────────────────────────────────────────────────────────────
 * Microphone ownership
 *
 * One holder at a time, and a hand-off is a release *then* an acquire — never both captures
 * live at once, however briefly. Doing it centrally is what removes the coordination the
 * surfaces were previously doing at their edges: the chat composer used to abort the shared
 * recognizer before taking its turn, and Voice had no equivalent for the reverse direction,
 * so a recognizer started by chat could outlive the panel that started it.
 * ──────────────────────────────────────────────────────────────────────────────────────── */

interface Lease {
  owner: MicrophoneOwner;
  engine: ResolvedSttEngine;
  release: () => void | Promise<void>;
}

let lease: Lease | null = null;

export function getMicrophoneLease(): { owner: MicrophoneOwner; engine: ResolvedSttEngine } | null {
  return lease ? { owner: lease.owner, engine: lease.engine } : null;
}

/**
 * Take the microphone for one surface and engine, releasing whoever held it first.
 *
 * `release` must be idempotent: it is called on a hand-off, on an engine change, and by the
 * owner's own teardown, and any of those can happen twice.
 */
export async function acquireMicrophone(
  owner: MicrophoneOwner,
  engine: ResolvedSttEngine,
  release: () => void | Promise<void>,
): Promise<void> {
  if (lease && (lease.owner !== owner || lease.engine !== engine)) {
    const previous = lease;
    lease = null;
    microphoneDebug('settings', 'microphone_handoff', {
      from: previous.owner,
      fromEngine: previous.engine,
      to: owner,
      toEngine: engine,
    });
    try {
      await previous.release();
    } catch {
      // A failed teardown must not block the next surface; the engines are exclusive by
      // construction and the stale one is already unreachable.
    }
  }
  lease = { owner, engine, release };
  microphoneDebug('settings', 'microphone_acquired', { owner, engine });
}

/** Give the microphone up. Releasing a lease somebody else now holds is a no-op. */
export async function releaseMicrophone(owner: MicrophoneOwner): Promise<void> {
  if (!lease || lease.owner !== owner) return;
  const previous = lease;
  lease = null;
  microphoneDebug('settings', 'microphone_released', {
    owner: previous.owner,
    engine: previous.engine,
  });
  try {
    await previous.release();
  } catch {
    // Same reasoning as above: the lease is gone either way.
  }
}

/** Test seam. The runtime is a session-scoped singleton; a test file is a new session. */
export function resetSttRuntimeForTests(): void {
  state = { ...INITIAL };
  listeners = new Set();
  engineListeners = new Set();
  announcedEngine = null;
  inFlight = null;
  lease = null;
  routingPreflightArmed = true;
  preferenceSubscription?.();
  preferenceSubscription = null;
}
