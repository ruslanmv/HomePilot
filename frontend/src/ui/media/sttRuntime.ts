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
import {
  getSttPreferences,
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
  /** HomePilot's own transcription can run here, so a recovery has somewhere to go. */
  backendUsable: boolean;
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
  backendUsable: false,
};

let state: SttRuntimeState = { ...INITIAL };
let listeners = new Set<(next: SttRuntimeState) => void>();
let inFlight: Promise<SttRuntimeState> | null = null;
let preferenceSubscription: (() => void) | null = null;

function emit(): void {
  const snapshot = state;
  listeners.forEach((listener) => {
    try {
      listener(snapshot);
    } catch {
      // One bad subscriber must never stop the others from learning the engine changed.
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
    // made on its own, in both surfaces at once.
    state = { ...state, sessionOverride: null, sessionOverrideMessage: null };
    void refreshSttRuntime({ force: true });
  });
}

function decide(capability: SttCapability, preference: SttEnginePreference): SttRuntimeState {
  const resolution = resolveSttEngine(preference, {
    backendAvailable: capability.available,
    mediaRecorderSupported: mediaRecorderSupported(),
    webSpeechSupported: webSpeechSupported(),
  });
  const backendUsable = capability.available && mediaRecorderSupported();
  const override = state.sessionOverride && backendUsable ? state.sessionOverride : null;

  const next = update({
    status: 'ready',
    preference,
    capability,
    resolution,
    backendUsable,
    sessionOverride: override,
    sessionOverrideMessage: override ? state.sessionOverrideMessage : null,
    effectiveEngine: override ?? resolution.engine,
  });

  microphoneDebug('settings', 'stt_runtime_resolved', {
    preference,
    engine: next.effectiveEngine,
    reason: override ? 'session-override' : resolution.reason,
    // A choice that was overridden has to be visible. Somebody who picked on-device
    // transcription for privacy and is quietly served the browser's — which ships audio to
    // Google — has been failed in a way no later message makes up for.
    fellBack: resolution.fellBack,
    usable: resolution.usable,
    provider: capability.provider,
    remote: capability.remote,
    usesOsDefaultInput: next.effectiveEngine === 'web-speech',
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
  inFlight = getSttCapability({ force: options.force })
    .then((capability) => decide(capability, preference))
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
    effectiveEngine: engine,
  });
}

export function clearSttSessionOverride(): SttRuntimeState {
  if (!state.sessionOverride) return state;
  return update({
    sessionOverride: null,
    sessionOverrideMessage: null,
    effectiveEngine: state.resolution?.engine ?? null,
  });
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
  inFlight = null;
  lease = null;
  preferenceSubscription?.();
  preferenceSubscription = null;
}
