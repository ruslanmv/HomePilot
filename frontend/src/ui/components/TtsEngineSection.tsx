/**
 * Schema-driven Settings section for the active TTS engine.
 *
 * In addition to engine configuration this section owns two diagnostics:
 *  - Test voice: exercises the *same* window.SpeechService path Chat/Voice use.
 *  - Speech → text → voice: records the selected Settings microphone, transcribes that exact
 *    sample through HomePilot STT, then reads the recognized text back through the active TTS
 *    engine. This catches the class of bug where VAD hears one device while browser Web Speech
 *    listens to another.
 */

import React, { useEffect, useMemo, useState } from 'react'
import {
  getActiveTtsEngineId,
  listTtsProviders,
  onActiveTtsEngineChange,
  readTtsProviderSettings,
  setActiveTtsEngine,
  writeTtsProviderSettings,
} from '../tts'
import type { SettingsField, TtsProvider } from '../tts'
import { buildAudioConstraints, getMediaPreferences } from '../media/mediaPreferences'

interface Props {
  systemVoices?: readonly SpeechSynthesisVoice[]
}

type VoiceTestState = 'idle' | 'starting' | 'speaking' | 'ok' | 'error'
type PipelineState = 'idle' | 'requesting' | 'recording' | 'transcribing' | 'speaking' | 'ok' | 'error'

const PIPELINE_RECORD_MS = 4000
const PREVIEW_TEXT = 'Hello, this is a preview of your selected voice.'

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

function speechService(): any {
  return typeof window !== 'undefined' ? (window as any).SpeechService : null
}

function speechRuntime(): any {
  return typeof window !== 'undefined' ? (window as any).hpSpeechRuntime : null
}

function pickRecorderMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg']
  for (const candidate of candidates) {
    try {
      if (!MediaRecorder.isTypeSupported || MediaRecorder.isTypeSupported(candidate)) return candidate
    } catch {
      // Try the next browser-supported container.
    }
  }
  return undefined
}

function recordStream(stream: MediaStream, durationMs: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    if (typeof MediaRecorder === 'undefined') {
      reject(new Error('MediaRecorder is not supported by this browser.'))
      return
    }

    const mimeType = pickRecorderMimeType()
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
    const chunks: Blob[] = []
    let timer = 0

    const cleanup = () => {
      if (timer) window.clearTimeout(timer)
    }

    recorder.ondataavailable = (event) => {
      if (event.data?.size) chunks.push(event.data)
    }
    recorder.onerror = (event: any) => {
      cleanup()
      reject(event?.error || new Error('Microphone recording failed.'))
    }
    recorder.onstop = () => {
      cleanup()
      const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || 'audio/webm' })
      if (!blob.size) {
        reject(new Error('The microphone recording was empty.'))
        return
      }
      resolve(blob)
    }

    recorder.start(250)
    timer = window.setTimeout(() => {
      if (recorder.state !== 'inactive') recorder.stop()
    }, durationMs)
  })
}

export default function TtsEngineSection({ systemVoices }: Props): JSX.Element {
  const [activeId, setActiveIdState] = useState<string>(() => getActiveTtsEngineId())
  useEffect(() => onActiveTtsEngineChange((id) => setActiveIdState(id)), [])

  const providers = useMemo<readonly TtsProvider[]>(
    () => listTtsProviders().filter((p) => p.isAvailable()),
    [activeId],
  )

  const active = useMemo<TtsProvider | undefined>(
    () => providers.find((p) => p.id === activeId),
    [providers, activeId],
  )

  const [settings, setSettings] = useState<Record<string, unknown>>(
    () => readTtsProviderSettings(activeId),
  )
  useEffect(() => {
    setSettings(readTtsProviderSettings(activeId))
  }, [activeId])

  const isDefaultEngine = activeId === 'web-speech-api'
  const schema = active && !isDefaultEngine ? active.getSettingsSchema() : []

  const [voiceTestState, setVoiceTestState] = useState<VoiceTestState>('idle')
  const [voiceTestMessage, setVoiceTestMessage] = useState<string | null>(null)
  const [pipelineState, setPipelineState] = useState<PipelineState>('idle')
  const [pipelineMessage, setPipelineMessage] = useState<string | null>(null)
  const [pipelineTranscript, setPipelineTranscript] = useState<string>('')

  const speakThroughRuntime = async (text: string): Promise<void> => {
    const svc = speechService()
    if (!svc?.speak) throw new Error('HomePilot Text-to-Speech runtime is not available.')

    let didStart = false
    let callbackError: unknown = null
    const result = await Promise.resolve(
      svc.speak(text, {
        onStart: () => {
          didStart = true
          setVoiceTestState('speaking')
        },
        onError: (error: unknown) => {
          callbackError = error
        },
      }),
    )

    if (callbackError) {
      throw callbackError instanceof Error ? callbackError : new Error(String(callbackError))
    }
    if (result === false || (!didStart && result !== true && result !== undefined)) {
      throw new Error('Text-to-Speech did not start. Make sure Enable Text-to-Speech is on.')
    }
  }

  const onTest = async () => {
    setVoiceTestMessage(null)
    if (voiceTestState === 'starting' || voiceTestState === 'speaking') {
      try { speechService()?.stopSpeaking?.() } catch { /* best effort */ }
      setVoiceTestState('idle')
      setVoiceTestMessage('Voice test stopped.')
      return
    }

    setVoiceTestState('starting')
    try {
      await speakThroughRuntime(PREVIEW_TEXT)
      setVoiceTestState('ok')
      setVoiceTestMessage('Voice test passed — HomePilot completed playback through the active TTS runtime.')
    } catch (error) {
      setVoiceTestState('error')
      setVoiceTestMessage(error instanceof Error ? error.message : String(error))
    }
  }

  const runPipelineTest = async () => {
    if (pipelineState === 'requesting' || pipelineState === 'recording' || pipelineState === 'transcribing' || pipelineState === 'speaking') {
      return
    }

    setPipelineState('requesting')
    setPipelineMessage('Opening the microphone selected in Audio & Video…')
    setPipelineTranscript('')
    let stream: MediaStream | null = null

    try {
      const runtime = speechRuntime()
      if (!runtime?.transcribeBlob) {
        throw new Error('HomePilot speech diagnostics runtime is not loaded. Reload the page and try again.')
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('This browser does not support microphone capture.')
      }

      const preferences = getMediaPreferences()
      stream = await navigator.mediaDevices.getUserMedia({
        video: false,
        audio: buildAudioConstraints(preferences),
      })
      const track = stream.getAudioTracks()[0]
      if (!track || track.readyState !== 'live') {
        throw new Error('The selected microphone did not return a live audio track.')
      }

      setPipelineState('recording')
      setPipelineMessage('Recording for 4 seconds — say a short sentence normally.')
      const blob = await recordStream(stream, PIPELINE_RECORD_MS)

      // Never play TTS while the capture stream is still open; stop first so the test cannot
      // feed the assistant voice back into the microphone and create a false pass.
      stream.getTracks().forEach((mediaTrack) => mediaTrack.stop())
      stream = null

      setPipelineState('transcribing')
      setPipelineMessage('Transcribing the recorded sample with HomePilot STT…')
      const result = await runtime.transcribeBlob(blob, 'settings')
      const text = String(result?.text || '').trim()
      if (!text) throw new Error('STT returned no speech. Check the microphone playback test, then try again.')
      setPipelineTranscript(text)

      setPipelineState('speaking')
      setPipelineMessage(`Transcription passed (${result?.provider || 'configured STT'}). Testing TTS playback…`)
      setVoiceTestState('starting')
      await speakThroughRuntime(`I heard: ${text}`)
      setVoiceTestState('ok')

      setPipelineState('ok')
      setPipelineMessage('Voice pipeline passed — selected microphone → transcription → Text-to-Speech all completed.')
    } catch (error) {
      setPipelineState('error')
      setPipelineMessage(error instanceof Error ? error.message : String(error))
    } finally {
      stream?.getTracks().forEach((track) => track.stop())
    }
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
              Piper runs fully in-browser via WebAssembly. First use downloads a voice model
              (~20 MB, cached). Falls back to the HomePilot mirror when the upstream CDN is unreachable.
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
                  <label className="block text-[10px] text-white/50 mb-2">{resolved.label}</label>
                  <select
                    className="w-full bg-black border border-white/10 rounded-lg px-3 py-2 text-xs text-white"
                    value={String(value)}
                    onChange={(e) => onChangeField(resolved.key, e.target.value)}
                  >
                    {resolved.options.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
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
          <div className="text-[10px] text-white/40">No TTS engine available in this environment.</div>
        ) : null}

        {active && !isDefaultEngine && !active.capabilities.pitch && (
          <div className="text-[10px] text-white/40 italic">
            The {active.displayName.split(' (')[0]} engine does not support pitch during playback.
          </div>
        )}

        {active && (
          <div className="space-y-2 pt-1">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void onTest()}
                className="text-[11px] px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/15 border border-white/10 text-white/80 disabled:opacity-50"
                aria-pressed={voiceTestState === 'starting' || voiceTestState === 'speaking'}
              >
                {voiceTestState === 'starting' ? 'Starting…' : voiceTestState === 'speaking' ? 'Stop voice test' : 'Test voice'}
              </button>
              <span className="text-[10px] text-white/40">{PREVIEW_TEXT}</span>
            </div>
            {voiceTestMessage ? (
              <div className={voiceTestState === 'error' ? 'text-[10px] text-red-300/80' : voiceTestState === 'ok' ? 'text-[10px] text-emerald-300/80' : 'text-[10px] text-white/45'}>
                {voiceTestMessage}
              </div>
            ) : null}
          </div>
        )}

        <div className="border-t border-white/[0.07] pt-3 space-y-2">
          <div>
            <div className="text-[11px] text-white/80 font-semibold">Speech → text → voice check</div>
            <div className="text-[10px] text-white/40 leading-relaxed mt-0.5">
              Records the microphone selected in Audio &amp; Video for 4 seconds, transcribes that
              recording with HomePilot STT, then reads the recognized sentence back through the
              active TTS engine. The sample is not stored.
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => void runPipelineTest()}
              disabled={pipelineState === 'requesting' || pipelineState === 'recording' || pipelineState === 'transcribing' || pipelineState === 'speaking'}
              className="text-[11px] px-3 py-1.5 rounded-lg bg-[#9b5cff]/15 hover:bg-[#9b5cff]/25 border border-[#9b5cff]/30 text-white/85 disabled:opacity-50"
            >
              {pipelineState === 'requesting' ? 'Opening mic…' :
                pipelineState === 'recording' ? 'Recording…' :
                  pipelineState === 'transcribing' ? 'Transcribing…' :
                    pipelineState === 'speaking' ? 'Testing TTS…' :
                      pipelineState === 'ok' ? 'Run again' : 'Run voice pipeline test'}
            </button>
            {pipelineState === 'ok' ? <span className="text-[10px] text-emerald-300">Passed</span> : null}
            {pipelineState === 'error' ? <span className="text-[10px] text-red-300">Needs attention</span> : null}
          </div>
          {pipelineMessage ? (
            <div className={pipelineState === 'error' ? 'text-[10px] text-red-300/80' : pipelineState === 'ok' ? 'text-[10px] text-emerald-300/80' : 'text-[10px] text-white/45'}>
              {pipelineMessage}
            </div>
          ) : null}
          {pipelineTranscript ? (
            <div className="rounded-lg border border-white/[0.07] bg-black/25 px-3 py-2 text-[10px] text-white/65">
              <span className="text-white/35">Transcribed: </span>{pipelineTranscript}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
