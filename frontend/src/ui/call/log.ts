/**
 * Structured call-lifecycle logger + shared TTS ownership.
 *
 * Three pieces, shipped together because they're tightly coupled:
 *
 *   clog(evt)                Namespaced, grep-friendly console log
 *                             for every call-related event. Format
 *                             ``[Call+<ms>] {e:…, …}`` so
 *                             ``grep "\\[Call\\]"`` surfaces a
 *                             chronological trace of any session.
 *
 *   speakOwned(source, text)  Single-owner TTS dispatch. Both the
 *                             overlay's fallback opener and the
 *                             App-level assistant-reply effect route
 *                             through this function, which guards
 *                             on ``window.__hp_tts_owner__`` so
 *                             duplicate sources don't double-speak
 *                             the same turn. First to call wins;
 *                             the second sees ``owner !== source``
 *                             and drops cleanly (emits an
 *                             ``tts: dedupe`` log so the drop is
 *                             auditable).
 *
 *   isCallFullDuplexEnabled() Feature flag gate. Defaults to ON; a
 *                             user can force-off via
 *                             ``localStorage.homepilot_call_full_duplex``
 *                             or a build-time ``VITE_CALL_FULL_DUPLEX_ENABLED``.
 *                             With the flag off every consumer keeps
 *                             its pre-flag behaviour — lets us flip
 *                             the full-duplex fix on/off during
 *                             dogfood without editing code.
 *
 * No runtime DOM setup; safe to import from SSR contexts — the
 * speakOwned path guards on ``typeof window``.
 */

export type CallLogEvent =
  | { e: 'lifecycle'; phase: 'open' | 'ready' | 'greet' | 'hangup' | 'close'; sid?: string }
  | { e: 'tts'; action: 'start' | 'end' | 'dedupe'; source: 'overlay' | 'app-level'; textLen: number }
  | { e: 'vad'; action: 'speech_start' | 'speech_end' | 'suppressed'; level?: number; state: string }
  | { e: 'turn'; action: 'user_out' | 'assistant_in' | 'barge_in'; route: 'ws' | 'chat_rest'; latencyMs?: number }
  | { e: 'state'; from: string; to: string; trigger: string }
  | { e: 'error'; where: string; message: string }

declare global {
  interface Window {
    __hp_tts_owner__?: 'overlay' | 'app-level' | null
  }
}

export function clog(evt: CallLogEvent): void {
  if (typeof performance === 'undefined') return
  const ts = Math.floor(performance.now())
  // console.info so DevTools 'Info' filter can hide it in prod if
  // needed; keeps the log present for debug without noise.
  // eslint-disable-next-line no-console
  console.info(`[Call+${ts}]`, evt)
}

/** Resolve the feature-flag state. Priority:
 *    1. ``localStorage.homepilot_call_full_duplex`` override
 *    2. build-time ``VITE_CALL_FULL_DUPLEX_ENABLED`` (default 'true')
 *  Falls through to ``true`` on any read error. */
export function isCallFullDuplexEnabled(): boolean {
  if (typeof window === 'undefined') return true
  try {
    const override = window.localStorage.getItem('homepilot_call_full_duplex')
    if (override === 'true') return true
    if (override === 'false') return false
  } catch {
    /* ignore storage errors */
  }
  const envVal = (import.meta as unknown as {
    env?: Record<string, string | undefined>
  }).env?.VITE_CALL_FULL_DUPLEX_ENABLED
  return String(envVal ?? 'true') !== 'false'
}

export interface SpeakOwnedHooks {
  onStart?: () => void
  onEnd?: () => void
  onError?: (message: string) => void
}

/**
 * Speak ``text`` via ``window.SpeechService`` with a shared owner
 * lock. Returns ``true`` if this call owns the utterance, ``false``
 * if another owner was already speaking (dedupe). Hooks fire on
 * the owning path only.
 *
 * Fallback when the shim isn't available: emits the ``tts.start``
 * log + an estimated ``tts.end`` timer anyway, so callers still
 * get their ``onEnd`` hook (used by the mic-gate release in
 * ``CallOverlay``) even with no TTS engine present.
 */
export function speakOwned(
  source: 'overlay' | 'app-level',
  text: string,
  hooks?: SpeakOwnedHooks,
): boolean {
  if (typeof window === 'undefined') return false
  const t = (text ?? '').trim()
  if (!t) return false
  const owner = window.__hp_tts_owner__
  if (owner && owner !== source) {
    clog({ e: 'tts', action: 'dedupe', source, textLen: t.length })
    return false
  }
  window.__hp_tts_owner__ = source
  try {
    hooks?.onStart?.()
    clog({ e: 'tts', action: 'start', source, textLen: t.length })
    const svc = (window as unknown as {
      SpeechService?: { speak?: (text: string) => void }
    }).SpeechService
    svc?.speak?.(t)
    // Length-estimate for the onEnd release — the SpeechService shim
    // in this repo doesn't expose an explicit onend hook, so we
    // guesstimate from text length + cap it so a runaway payload
    // can't permanently hold the owner lock. ~12 chars/s typical;
    // [800 ms, 10 s] clamp.
    const estimateMs = Math.max(800, Math.min(10_000, t.length * 80))
    window.setTimeout(() => {
      if (window.__hp_tts_owner__ === source) {
        window.__hp_tts_owner__ = null
      }
      hooks?.onEnd?.()
      clog({ e: 'tts', action: 'end', source, textLen: t.length })
    }, estimateMs)
    return true
  } catch (err) {
    if (window.__hp_tts_owner__ === source) {
      window.__hp_tts_owner__ = null
    }
    const message = err instanceof Error ? err.message : String(err)
    hooks?.onError?.(message)
    clog({ e: 'error', where: 'speakOwned', message })
    return false
  }
}
