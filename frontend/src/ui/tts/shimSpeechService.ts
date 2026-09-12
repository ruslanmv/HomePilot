/**
 * Non-destructive monkey-patch that lets the legacy `window.SpeechService`
 * honor the active TTS plugin registry.
 *
 * This is also the final runtime diagnostic boundary for TTS: regardless of
 * whether the public speech runtime wrapped SpeechService before or after this
 * module installs, every engine selection and provider lifecycle emits a
 * metadata-only `[HomePilot:TTS]` trace. Spoken text itself is never logged.
 */

import { getActiveTtsEngineId, getTtsProvider, readTtsProviderSettings } from './index'

type AnyFn = (...args: unknown[]) => unknown

let _installed = false
let _originalSpeak: AnyFn | null = null
let _originalStop: AnyFn | null = null

function trace(event: string, details: Record<string, unknown> = {}): void {
  console.info(`[HomePilot:TTS] ${event}`, details)
}

/** Install the shim. Safe to call repeatedly. */
export function install(): void {
  if (_installed) return
  if (typeof window === 'undefined') return
  const svc = (window as unknown as { SpeechService?: Record<string, AnyFn> }).SpeechService
  if (!svc) {
    // SpeechService loads from /public/js via a <script> tag. In dev it may
    // appear slightly after the TS bundle; retry for up to 2 seconds.
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
  trace('registry_shim_installed')

  svc.speak = ((text: string, callbacks: Record<string, unknown> = {}) => {
    const engineId = getActiveTtsEngineId()
    trace('engine_selected', { engineId, chars: String(text || '').length })

    // System Voice uses the legacy SpeechService/Web Speech runtime. If the
    // public diagnostic wrapper is installed it will emit the detailed
    // speak_requested/start/completed/error events around this call.
    if (engineId === 'web-speech-api') {
      trace('system_voice_delegate', { engineId })
      return _originalSpeak ? _originalSpeak(text, callbacks) : undefined
    }

    const provider = getTtsProvider(engineId)
    if (!provider || !provider.isAvailable()) {
      trace('provider_unavailable_fallback', { engineId })
      // Fall back to system voice so a provider/model failure does not make
      // assistant replies silently disappear.
      return _originalSpeak ? _originalSpeak(text, callbacks) : undefined
    }

    const saved = readTtsProviderSettings(engineId)
    const voiceId = typeof saved.voiceId === 'string' ? saved.voiceId : undefined
    const rate = typeof saved.rate === 'number' ? saved.rate : undefined
    const pitch = typeof saved.pitch === 'number' ? saved.pitch : undefined

    const cb = callbacks as {
      onStart?: () => void
      onEnd?: () => void
      onError?: (err: unknown) => void
    }

    // VoiceController polls this legacy flag to drive SPEAKING -> IDLE.
    const markSpeaking = (v: boolean) => {
      try {
        svc.isSpeaking = v as unknown as AnyFn
      } catch {
        // Best effort: some tests/frozen implementations may reject writes.
      }
    }
    markSpeaking(true)
    trace('provider_requested', { engineId, voiceId: voiceId || 'default', rate, pitch })

    const clearFlag = () => markSpeaking(false)
    return provider
      .speak(text, {
        voiceId,
        rate,
        pitch,
        onStart: () => {
          trace('provider_started', { engineId })
          try { cb.onStart?.() } catch { /* caller callback must not break TTS */ }
        },
        onEnd: () => {
          clearFlag()
          trace('provider_completed', { engineId })
          try { cb.onEnd?.() } catch { /* ignore caller callback failure */ }
        },
        onError: (err) => {
          clearFlag()
          trace('provider_error', {
            engineId,
            error: err instanceof Error ? err.message : String(err || 'unknown'),
          })
          try { cb.onError?.(err) } catch { /* ignore caller callback failure */ }
        },
      })
      .then(
        () => {
          // Providers that resolve without firing onEnd must still release the
          // legacy speaking state.
          clearFlag()
          trace('provider_promise_resolved', { engineId })
        },
        (err) => {
          clearFlag()
          trace('provider_rejected_fallback', {
            engineId,
            error: err instanceof Error ? err.message : String(err || 'unknown'),
          })
          try { cb.onError?.(err) } catch { /* ignore */ }
          if (_originalSpeak) return _originalSpeak(text, callbacks)
        },
      )
  }) as AnyFn

  svc.stopSpeaking = (() => {
    const engineId = getActiveTtsEngineId()
    trace('stop_requested', { engineId })
    if (engineId !== 'web-speech-api') {
      const provider = getTtsProvider(engineId)
      try { provider?.stop() } catch { /* ignore */ }
      try { svc.isSpeaking = false as unknown as AnyFn } catch { /* ignore */ }
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

install()
