/**
 * Schema-driven Settings section for the active TTS engine.
 *
 * This component is deliberately self-contained so SettingsPanel can mount
 * it with one line and stay agnostic of which engines are installed.
 *
 * Behavior:
 *   - Dropdown to pick the active engine (only ``isAvailable()`` ones).
 *   - Below: controls rendered from the active provider's
 *     ``getSettingsSchema()`` — ``select`` / ``range`` / ``toggle``.
 *   - The Web Speech provider's ``voiceId`` schema has a placeholder
 *     options list; we merge in the browser's live voices at render
 *     time so the user sees their actual installed voices.
 *   - Every edit persists to the registry's per-user scoped settings
 *     bucket AND to ``value`` via ``onChangeDraft`` so the existing
 *     Voice Assistant code continues to read ``value.selectedVoice``.
 *
 * Purely additive: the existing System Voice select stays untouched
 * above this component, and this section only appears when the user
 * opts into it by picking a non-default engine (or leaves it on
 * ``web-speech-api`` where we render the same controls the old UI did).
 */

import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  getActiveTtsEngineId,
  listTtsProviders,
  onActiveTtsEngineChange,
  readTtsProviderSettings,
  setActiveTtsEngine,
  writeTtsProviderSettings,
} from '../tts'
import type { SettingsField, TtsProvider } from '../tts'
import { resolveAssistantVoiceId } from '../tts/resolveAssistantVoice'
import { TTS_START_TIMEOUT_MS } from '../media/voiceSelfTest'

interface Props {
  /** Optional: used by the Web Speech engine to populate its voice
   *  dropdown with the browser's live voices. Passing undefined is
   *  safe — we fall back to ``getVoices()``. */
  systemVoices?: readonly SpeechSynthesisVoice[]
}

function _fieldValue(schema: SettingsField, saved: Record<string, unknown>): string | number | boolean {
  const v = saved[schema.key]
  if (schema.kind === 'range') {
    return typeof v === 'number' ? v : schema.defaultValue
  }
  if (schema.kind === 'toggle') {
    return typeof v === 'boolean' ? v : schema.defaultValue
  }
  return typeof v === 'string' ? v : schema.defaultValue
}

function _mergeWebSpeechOptions(
  field: SettingsField,
  voices: readonly SpeechSynthesisVoice[],
): SettingsField {
  if (field.kind !== 'select' || field.key !== 'voiceId' || voices.length === 0) {
    return field
  }
  const live = voices.map((v) => ({
    value: v.voiceURI || v.name,
    label: `${v.name} (${v.lang})`,
  }))
  return { ...field, options: [...field.options, ...live] }
}

export default function TtsEngineSection({ systemVoices }: Props): JSX.Element {
  const [activeId, setActiveIdState] = useState<string>(() => getActiveTtsEngineId())
  // Re-render when another component swaps the active engine.
  useEffect(() => onActiveTtsEngineChange((id) => setActiveIdState(id)), [])

  const providers = useMemo<readonly TtsProvider[]>(
    () => listTtsProviders().filter((p) => p.isAvailable()),
    [activeId],
  )

  const active = useMemo<TtsProvider | undefined>(
    () => providers.find((p) => p.id === activeId),
    [providers, activeId],
  )

  // Saved settings blob for the active provider.
  const [settings, setSettings] = useState<Record<string, unknown>>(
    () => readTtsProviderSettings(activeId),
  )
  useEffect(() => {
    setSettings(readTtsProviderSettings(activeId))
  }, [activeId])

  // When the default engine is selected the host panel already renders
  // a dedicated "Assistant Voice" / "System Voice" dropdown above us
  // that covers voice + rate + pitch for Web Speech. Rendering our
  // schema-driven twin on top of it is pure duplication — skip it
  // unless the user has opted into a non-default engine (Piper etc.).
  const isDefaultEngine = activeId === 'web-speech-api'
  const schema = active && !isDefaultEngine ? active.getSettingsSchema() : []

  // Test-voice state: the button speaks through whichever engine is
  // active right now so the user can hear their pick without leaving
  // Settings. Mirrors the Preview button in the Creator Studio wizard.
  const [testing, setTesting] = useState(false)
  const [testError, setTestError] = useState<string | null>(null)
  // `speechSynthesis.speak()` can silently produce neither audio nor an error
  // (missing voice, blocked autoplay, muted output), which used to leave this
  // button stuck on "Stop" forever. The watchdog releases it.
  const startWatchdog = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clearWatchdog = () => {
    if (startWatchdog.current) {
      clearTimeout(startWatchdog.current)
      startWatchdog.current = null
    }
  }
  useEffect(() => clearWatchdog, [])

  const onTest = () => {
    setTestError(null)
    if (!active) return
    if (testing) {
      clearWatchdog()
      try { active.stop() } catch { /* ignore */ }
      setTesting(false)
      return
    }
    setTesting(true)
    // On the default engine this section renders no voice field, so
    // `settings.voiceId` is empty and previewing it would speak with the
    // browser default rather than the voice chosen in Assistant Voice above.
    // Resolve through the same keys the assistant itself reads.
    const resolvedVoiceId = resolveAssistantVoiceId(activeId, settings)
    const voiceId = resolvedVoiceId || undefined
    const rate = typeof settings.rate === 'number' ? settings.rate : undefined
    const pitch = typeof settings.pitch === 'number' ? settings.pitch : undefined
    let started = false
    startWatchdog.current = setTimeout(() => {
      startWatchdog.current = null
      if (started) return
      try { active.stop() } catch { /* ignore */ }
      setTesting(false)
      setTestError(
        'The engine accepted the text but never started speaking. Check your output device and volume, then try again.',
      )
    }, TTS_START_TIMEOUT_MS)

    active
      .speak('Hello, this is a preview of your selected voice.', {
        voiceId,
        rate,
        pitch,
        onStart: () => {
          started = true
          clearWatchdog()
        },
        onEnd: () => {
          clearWatchdog()
          setTesting(false)
        },
        onError: (err) => {
          clearWatchdog()
          setTestError(String(err?.message || err))
          setTesting(false)
        },
      })
      .catch((err) => {
        clearWatchdog()
        setTestError(String(err?.message || err))
        setTesting(false)
      })
  }

  const onChangeField = (key: string, value: string | number | boolean) => {
    const next = { ...settings, [key]: value }
    setSettings(next)
    writeTtsProviderSettings(activeId, { [key]: value })
  }

  return (
    <div className="border-t border-white/5 pt-3">
      <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">
        TTS Engine
      </div>

      <div className="space-y-3">
        <div>
          <label className="block text-[10px] text-white/50 mb-2">Engine</label>
          <select
            className="w-full bg-black border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
            value={activeId}
            onChange={(e) => setActiveTtsEngine(e.target.value)}
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.displayName}
              </option>
            ))}
          </select>
          {active?.id === 'piper-wasm' && (
            <div className="mt-1 text-[10px] text-white/40 leading-relaxed">
              Piper runs fully in-browser via WebAssembly. First use
              downloads a voice model (~20 MB, cached). Falls back to the
              HomePilot mirror when the upstream CDN is unreachable.
            </div>
          )}
        </div>

        {active && !isDefaultEngine ? (
          schema.map((field) => {
            const resolved =
              active.id === 'web-speech-api' && field.kind === 'select' && field.key === 'voiceId'
                ? _mergeWebSpeechOptions(
                    field,
                    systemVoices ??
                      (typeof window !== 'undefined' && 'speechSynthesis' in window
                        ? window.speechSynthesis.getVoices()
                        : []),
                  )
                : field
            const value = _fieldValue(resolved, settings)

            if (resolved.kind === 'select') {
              return (
                <div key={resolved.key}>
                  <label className="block text-[10px] text-white/50 mb-2">
                    {resolved.label}
                  </label>
                  <select
                    className="w-full bg-black border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
                    value={String(value)}
                    onChange={(e) => onChangeField(resolved.key, e.target.value)}
                  >
                    {resolved.options.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  {resolved.description ? (
                    <div className="mt-1 text-[10px] text-white/40">{resolved.description}</div>
                  ) : null}
                </div>
              )
            }

            if (resolved.kind === 'range') {
              return (
                <div key={resolved.key}>
                  <div className="flex items-center justify-between">
                    <label className="text-[10px] text-white/50">{resolved.label}</label>
                    <span className="text-[10px] text-white/60 font-mono">
                      {typeof value === 'number' ? value.toFixed(2) : value}
                    </span>
                  </div>
                  <input
                    type="range"
                    min={resolved.min}
                    max={resolved.max}
                    step={resolved.step}
                    value={typeof value === 'number' ? value : resolved.defaultValue}
                    onChange={(e) => onChangeField(resolved.key, Number(e.target.value))}
                    className="w-full accent-cyan-400"
                  />
                </div>
              )
            }

            // toggle
            return (
              <label key={resolved.key} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(value)}
                  onChange={(e) => onChangeField(resolved.key, e.target.checked)}
                  className="w-4 h-4 rounded"
                />
                <span className="text-xs text-white">{resolved.label}</span>
              </label>
            )
          })
        ) : !active ? (
          <div className="text-[10px] text-white/40">
            No TTS engine available in this environment.
          </div>
        ) : null}

        {active && !isDefaultEngine && !active.capabilities.pitch && (
          <div className="text-[10px] text-white/40 italic">
            The {active.displayName.split(' (')[0]} engine does not support a pitch control in
            playback. The Creator Studio export applies pitch post-synthesis via ffmpeg.
          </div>
        )}

        {/* Test voice button — positioned AFTER the voice + rate + pitch
            controls so users pick their voice first, then preview it
            (best-practice: action sits at the end of the configuration
            flow). Always visible; mirrors the "Preview voice" affordance
            in the Creator Studio export wizard. */}
        {active && (
          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={onTest}
              className="text-[11px] px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/15 border border-white/10 text-white/80"
              aria-pressed={testing}
            >
              {testing ? 'Stop' : 'Test voice'}
            </button>
            <span className="text-[10px] text-white/40">
              Hello, this is a preview of your selected voice.
            </span>
          </div>
        )}
        {testError ? (
          <div className="text-[10px] text-red-300/80">{testError}</div>
        ) : null}
      </div>
    </div>
  )
}
