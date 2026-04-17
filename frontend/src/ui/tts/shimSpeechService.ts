/**
 * Non-destructive monkey-patch that lets the legacy
 * ``window.SpeechService`` (see /public/js/speech-service.js, called from
 * App.tsx:4012 on every assistant message) honor the TTS plugin
 * registry.
 *
 * Problem this fixes
 * ------------------
 * The in-app chat TTS goes through ``window.SpeechService.speak(text)``,
 * which calls ``speechSynthesis`` directly. Our plugin registry was
 * only read by the Settings UI and the Creator Studio export wizard —
 * so picking Piper in the engine dropdown did not change what the user
 * heard when an assistant message played. The chat path always used
 * the Web Speech API regardless of the engine setting.
 *
 * How this fixes it
 * -----------------
 * When ``./tts/index`` is imported (which SettingsPanel and the voice
 * settings modal both do on mount), this module is pulled in and
 * ``install()`` runs once. It swaps ``window.SpeechService.speak`` and
 * ``window.SpeechService.stopSpeaking`` for thin wrappers that:
 *
 *   - Look up the active engine id via the registry.
 *   - If the active engine is NOT ``web-speech-api`` AND the provider
 *     is available, route speak()/stop() to ``provider.speak()`` /
 *     ``provider.stop()``. The provider supplies its own voice model,
 *     rate, etc. — no contact with ``speechSynthesis`` happens.
 *   - Otherwise, call the original ``SpeechService`` function
 *     unchanged. This is the fast path for users who never touched
 *     the engine picker.
 *
 * The original functions are held in closure so a second install is a
 * no-op, and uninstall() restores them if ever needed (e.g. tests).
 */

import { getActiveTtsEngineId, getTtsProvider, readTtsProviderSettings } from './index'

type AnyFn = (...args: unknown[]) => unknown

// NB: we intentionally do NOT `declare global` augment Window.SpeechService
// here. Other files (useVoiceController, teams TTS) already declare it as
// `any` to reach methods we do not touch — widening back to `any` would
// conflict in strict declaration-merge mode. Local `any` cast is enough
// for the two methods we swap.

let _installed = false
let _originalSpeak: AnyFn | null = null
let _originalStop: AnyFn | null = null

/** Install the shim. Safe to call repeatedly. */
export function install(): void {
  if (_installed) return
  if (typeof window === 'undefined') return
  const svc = (window as unknown as { SpeechService?: Record<string, AnyFn> }).SpeechService
  if (!svc) {
    // SpeechService loads from /public/js via a <script> tag. In dev
    // it may appear slightly after the TS bundle; retry up to 2 s.
    let tries = 0
    const tick = () => {
      tries += 1
      if (window.SpeechService) {
        install()
      } else if (tries < 20) {
        window.setTimeout(tick, 100)
      }
    }
    window.setTimeout(tick, 100)
    return
  }

  _originalSpeak = svc.speak ? svc.speak.bind(svc) : null
  _originalStop = svc.stopSpeaking ? svc.stopSpeaking.bind(svc) : null
  _installed = true

  svc.speak = ((text: string, callbacks: Record<string, unknown> = {}) => {
    const engineId = getActiveTtsEngineId()
    if (engineId === 'web-speech-api') {
      return _originalSpeak ? _originalSpeak(text, callbacks) : undefined
    }

    const provider = getTtsProvider(engineId)
    if (!provider || !provider.isAvailable()) {
      // Fall back silently so the user always hears something.
      return _originalSpeak ? _originalSpeak(text, callbacks) : undefined
    }

    // Pull the voice / rate the user saved in Settings for this engine.
    const saved = readTtsProviderSettings(engineId)
    const voiceId = typeof saved.voiceId === 'string' ? saved.voiceId : undefined
    const rate = typeof saved.rate === 'number' ? saved.rate : undefined
    const pitch = typeof saved.pitch === 'number' ? saved.pitch : undefined

    // speech-service.js accepts a callbacks object with onStart/onEnd/onError.
    // Forward the subset our providers understand so existing caller
    // wiring (transcript highlighting, mouth-animation) keeps working.
    const cb = callbacks as {
      onStart?: () => void
      onEnd?: () => void
      onError?: (err: unknown) => void
    }
    return provider
      .speak(text, {
        voiceId,
        rate,
        pitch,
        onStart: cb.onStart,
        onEnd: cb.onEnd,
        onError: (err) => cb.onError?.(err),
      })
      .catch((err) => {
        // Last-resort fallback: if the provider blows up mid-synthesis
        // (e.g. Piper model download failure), speak through the
        // browser engine so the user still hears the message.
        try { cb.onError?.(err) } catch { /* ignore */ }
        if (_originalSpeak) return _originalSpeak(text, callbacks)
      })
  }) as AnyFn

  svc.stopSpeaking = (() => {
    const engineId = getActiveTtsEngineId()
    if (engineId !== 'web-speech-api') {
      const provider = getTtsProvider(engineId)
      try { provider?.stop() } catch { /* ignore */ }
    }
    return _originalStop ? _originalStop() : undefined
  }) as AnyFn
}

/** Revert the patch. Tests / diagnostics only. */
export function uninstall(): void {
  if (!_installed || typeof window === 'undefined') return
  const svc = (window as unknown as { SpeechService?: Record<string, AnyFn> }).SpeechService
  if (!svc) return
  if (_originalSpeak) svc.speak = _originalSpeak
  if (_originalStop) svc.stopSpeaking = _originalStop
  _installed = false
  _originalSpeak = null
  _originalStop = null
}

// Auto-install on import. ``./tts`` barrels this file so any feature
// that touches the registry automatically gets runtime wiring.
install()
