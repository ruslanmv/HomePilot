/**
 * Which speech-to-text engine each surface uses.
 *
 * ── Why this is a choice and not a detection ─────────────────────────────────────────────
 *
 * HomePilot has two transcription paths with genuinely different trade-offs, and neither one
 * is better everywhere:
 *
 *   - **The browser's Web Speech API.** Instant, streams interim words as you speak, nothing
 *     to install. But it records the operating system's *default* input — it accepts no
 *     `deviceId` — and on Chrome it sends your audio to a Google service, so it needs the
 *     internet and is not private.
 *   - **HomePilot's own transcription.** Records the microphone you actually selected and
 *     runs on this computer, so it is private and works offline. But it needs a model
 *     installed, costs CPU or GPU per turn, and returns a whole turn at once rather than
 *     streaming words.
 *
 * Preferring the local one automatically turned out to be the wrong default: a machine whose
 * CUDA runtime is present but incomplete reported the provider as available and then failed
 * every single turn, so chat speech-to-text broke on a setup where the browser path would
 * have worked fine. Availability is not the same question as suitability, and only the user
 * can answer the second one.
 *
 * So the browser path is the default — it is what HomePilot shipped with and what works
 * without setup — and the local path is something you opt into.
 *
 * ── Meetings are deliberately absent ─────────────────────────────────────────────────────
 *
 * MeetingSense does not go through this. It streams over its own WebSocket to
 * `get_meeting_stt_provider()`, which is local-first and never crosses to a remote endpoint
 * on its own, and the browser recognizer cannot do what it needs anyway: two channels, hours
 * of continuous audio, and speaker labels. There is exactly one engine there, so there is
 * nothing to choose — Settings reports it rather than offering it.
 */

export type SttScenario = 'chat';

/**
 * What the user asked for, which is not necessarily what runs — see
 * {@link resolveSttEngine}.
 */
export type SttEnginePreference =
  /** The browser's recognizer. Default: no setup, instant, streams interim words. */
  | 'web-speech'
  /** Transcribe on this computer, on the selected microphone. Private, offline, needs a model. */
  | 'homepilot'
  /** HomePilot's when it is genuinely usable, the browser's otherwise. */
  | 'auto';

/** The engine that actually ends up running. */
export type ResolvedSttEngine = 'web-speech' | 'homepilot-backend';

export interface SttPreferences {
  /** Chat composer and the Voice tab. They share one setting because they are one workflow. */
  chat: SttEnginePreference;
}

export const STT_PREFERENCES_STORAGE_KEY = 'homepilot_stt_preferences_v1';
export const STT_PREFERENCES_EVENT = 'homepilot:stt-preferences-changed';

/**
 * Browser speech recognition, because it is what HomePilot behaved like before local
 * transcription existed and it needs nothing installed. Restoring a working default matters
 * more than defaulting to the better engine on the machines that have it.
 */
export const DEFAULT_STT_PREFERENCES: SttPreferences = {
  chat: 'web-speech',
};

const VALID: readonly SttEnginePreference[] = ['web-speech', 'homepilot', 'auto'];

function safeStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

function sanitize(raw: unknown): SttPreferences {
  const value = raw && typeof raw === 'object' ? raw as Partial<SttPreferences> : {};
  const chat = value.chat;
  return {
    chat: VALID.includes(chat as SttEnginePreference)
      ? chat as SttEnginePreference
      : DEFAULT_STT_PREFERENCES.chat,
  };
}

export function getSttPreferences(): SttPreferences {
  const storage = safeStorage();
  if (!storage) return { ...DEFAULT_STT_PREFERENCES };
  try {
    const saved = storage.getItem(STT_PREFERENCES_STORAGE_KEY);
    return saved ? sanitize(JSON.parse(saved)) : { ...DEFAULT_STT_PREFERENCES };
  } catch {
    return { ...DEFAULT_STT_PREFERENCES };
  }
}

export function setSttPreferences(next: SttPreferences): SttPreferences {
  const sanitized = sanitize(next);
  try {
    safeStorage()?.setItem(STT_PREFERENCES_STORAGE_KEY, JSON.stringify(sanitized));
  } catch {
    // Locked-down or private contexts still get the value for this session.
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(STT_PREFERENCES_EVENT, { detail: sanitized }));
  }
  return sanitized;
}

/** Fires on a change from this tab or another one, so every surface agrees. */
export function subscribeSttPreferences(
  listener: (preferences: SttPreferences) => void,
): () => void {
  if (typeof window === 'undefined') return () => {};

  const onCustom = (event: Event) => {
    const detail = (event as CustomEvent<SttPreferences>).detail;
    listener(detail ? sanitize(detail) : getSttPreferences());
  };
  const onStorage = (event: StorageEvent) => {
    if (event.key === STT_PREFERENCES_STORAGE_KEY) listener(getSttPreferences());
  };

  window.addEventListener(STT_PREFERENCES_EVENT, onCustom);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(STT_PREFERENCES_EVENT, onCustom);
    window.removeEventListener('storage', onStorage);
  };
}

export interface SttEngineSupport {
  /** The server has a speech provider that can actually transcribe. */
  backendAvailable: boolean;
  /** This browser can record audio at all (`MediaRecorder` + `getUserMedia`). */
  mediaRecorderSupported: boolean;
  /** This browser implements the Web Speech API. */
  webSpeechSupported: boolean;
}

export type SttResolutionReason =
  /** The chosen engine is the one running. */
  | 'preferred'
  /** `auto` found the local path usable. */
  | 'auto-backend'
  /** `auto` found it unusable and took the browser's. */
  | 'auto-web-speech'
  /** HomePilot was chosen but the server has no usable provider. */
  | 'backend-unavailable'
  /** HomePilot was chosen but this browser cannot record. */
  | 'recorder-unsupported'
  /** The browser was chosen but does not implement the API; the local path stood in. */
  | 'web-speech-unsupported'
  /** Neither path can run here. */
  | 'none';

export interface SttResolution {
  engine: ResolvedSttEngine;
  reason: SttResolutionReason;
  /** Whether the user's choice was overridden. The UI must say so rather than pretend. */
  fellBack: boolean;
  /** Whether *anything* can transcribe. `false` means voice input is genuinely unavailable. */
  usable: boolean;
}

/**
 * Turn a preference plus what is actually possible into the engine that will run.
 *
 * Pure, because this is the one piece of the decision worth testing exhaustively: every
 * combination of "what the user asked for" and "what this machine can do" has to produce a
 * defined answer, and silently doing something other than what was asked is precisely the
 * failure this whole split exists to stop.
 *
 * A fallback is always *reported*, never hidden. A user who picked HomePilot transcription
 * for privacy and is quietly served the browser's — which ships audio to Google — has been
 * failed in a way no error message would later make up for.
 */
export function resolveSttEngine(
  preference: SttEnginePreference,
  support: SttEngineSupport,
): SttResolution {
  const backendUsable = support.backendAvailable && support.mediaRecorderSupported;

  if (preference === 'auto') {
    if (backendUsable) {
      return { engine: 'homepilot-backend', reason: 'auto-backend', fellBack: false, usable: true };
    }
    return {
      engine: 'web-speech',
      reason: 'auto-web-speech',
      fellBack: false, // `auto` choosing is not a fallback; choosing is what it was asked to do.
      usable: support.webSpeechSupported,
    };
  }

  if (preference === 'homepilot') {
    if (backendUsable) {
      return { engine: 'homepilot-backend', reason: 'preferred', fellBack: false, usable: true };
    }
    // Fall back rather than leave the microphone dead, and name which wall was hit: "install
    // a model" and "this browser cannot record" need different actions from the user.
    return {
      engine: 'web-speech',
      reason: support.mediaRecorderSupported ? 'backend-unavailable' : 'recorder-unsupported',
      fellBack: true,
      usable: support.webSpeechSupported,
    };
  }

  // 'web-speech'
  if (support.webSpeechSupported) {
    return { engine: 'web-speech', reason: 'preferred', fellBack: false, usable: true };
  }
  if (backendUsable) {
    // Firefox and Safari implement no recognizer. The local path is the only way voice input
    // works there at all, so standing in for the default is right — and is still a fallback.
    return {
      engine: 'homepilot-backend',
      reason: 'web-speech-unsupported',
      fellBack: true,
      usable: true,
    };
  }
  return { engine: 'web-speech', reason: 'none', fellBack: true, usable: false };
}

/** One sentence for the UI, naming the engine and — when it matters — why. */
export function describeSttResolution(
  resolution: SttResolution,
  provider: string | null,
): string {
  if (!resolution.usable) {
    return 'No speech-to-text is available: this browser has no recognizer and this server has no speech model installed.';
  }

  const local = `HomePilot on this computer${provider ? ` (${provider})` : ''}, using the microphone selected in Audio & Video`;
  const browser = 'the browser’s speech recognition, which records your system default input';

  switch (resolution.reason) {
    case 'auto-backend':
      return `Automatic chose ${local}.`;
    case 'auto-web-speech':
      return `Automatic chose ${browser}, because no speech model is installed on this server.`;
    case 'backend-unavailable':
      return `You chose HomePilot transcription, but this server has no speech model installed — using ${browser} instead.`;
    case 'recorder-unsupported':
      return `You chose HomePilot transcription, but this browser cannot record audio — using ${browser} instead.`;
    case 'web-speech-unsupported':
      return `This browser has no speech recognition, so ${local} is being used instead.`;
    case 'preferred':
    default:
      return resolution.engine === 'homepilot-backend'
        ? `Using ${local}.`
        : `Using ${browser}.`;
  }
}
