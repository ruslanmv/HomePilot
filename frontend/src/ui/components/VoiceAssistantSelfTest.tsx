/**
 * Settings → Voice Assistant → "Check voice input and output".
 *
 * Two end-to-end tests the user can run without leaving Settings:
 *
 *   1. **Speech-to-text** — runs one real recognition turn and shows the text
 *      it produced. When nothing comes back it says *which* of the three silent
 *      failure modes happened and what to do about it, instead of leaving the
 *      user with a microphone meter that moves and a chat box that stays empty.
 *
 *   2. **Text-to-speech** — speaks a sentence with the voice the assistant will
 *      actually use for replies, and fails the test when the engine never
 *      starts. `speechSynthesis` reports no error for a missing voice, a muted
 *      output, or a blocked autoplay, so absence of `onstart` is the only
 *      evidence available.
 *
 * The speech-to-text test runs its own recognizer rather than borrowing
 * `window.SpeechService`, so it never clobbers the recognition callbacks that
 * hands-free voice mode has installed.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Mic2, RefreshCw, Square, Volume2 } from 'lucide-react'
import { getMediaPreferences } from '../media/mediaPreferences'
import { microphoneDebug, microphoneDebugError } from '../media/microphoneDebug'
import {
  TTS_START_TIMEOUT_MS,
  TTS_TEST_SENTENCE,
  describeMicrophoneRouting,
  explainSttError,
  explainSttOutcome,
  getSpeechRecognitionCtor,
  isSpeechSynthesisSupported,
  type SttDiagnostics,
  type SttOutcome,
} from '../media/voiceSelfTest'
import { getActiveTtsEngineId, getTtsProvider, readTtsProviderSettings } from '../tts'
import { describeAssistantVoice, resolveAssistantVoiceId } from '../tts/resolveAssistantVoice'

/** Recognition is given this long before the test gives up on its own. */
const STT_TEST_TIMEOUT_MS = 12000

/**
 * Minimal shapes for the two recognition events we read. The bundled DOM lib
 * does not declare `SpeechRecognitionEvent` / `SpeechRecognitionErrorEvent`,
 * and only these fields are used.
 */
interface RecognitionResultEvent {
  resultIndex: number
  results: {
    length: number
    [index: number]: { isFinal: boolean; [index: number]: { transcript: string } }
  }
}

interface RecognitionErrorEvent {
  error?: string
}

const BUTTON_CLS =
  'h-9 px-3 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-[11px] text-white/80 ' +
  'hover:text-white font-semibold disabled:opacity-45 disabled:cursor-not-allowed transition-colors ' +
  'inline-flex items-center justify-center gap-2'

type Phase = 'idle' | 'running' | 'ok' | 'error'

function Verdict({ phase, outcome, runningLabel }: {
  phase: Phase
  outcome: SttOutcome | null
  runningLabel: string
}) {
  if (phase === 'running') {
    return (
      <div className="flex items-center gap-1.5 text-[11px] text-[#c8a7ff]">
        <RefreshCw size={12} className="animate-spin" /> {runningLabel}
      </div>
    )
  }
  if (phase === 'idle' || !outcome) return null
  const ok = phase === 'ok'
  return (
    <div
      className={[
        'rounded-xl border px-3 py-2.5 space-y-1',
        ok
          ? 'border-emerald-500/25 bg-emerald-500/[0.07]'
          : 'border-amber-500/25 bg-amber-500/[0.07]',
      ].join(' ')}
    >
      <div
        className={[
          'flex items-center gap-1.5 text-[11px] font-semibold',
          ok ? 'text-emerald-300' : 'text-amber-200',
        ].join(' ')}
      >
        {ok ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
        {outcome.headline}
      </div>
      <p className="text-[10px] leading-relaxed text-white/50">{outcome.detail}</p>
    </div>
  )
}

export default function VoiceAssistantSelfTest(): JSX.Element {
  // ── Speech-to-text ──────────────────────────────────────────────────────
  const [sttPhase, setSttPhase] = useState<Phase>('idle')
  const [sttOutcome, setSttOutcome] = useState<SttOutcome | null>(null)
  const [heard, setHeard] = useState('')
  const [interim, setInterim] = useState('')

  /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
  const recognitionRef = useRef<any>(null)
  const diagnosticsRef = useRef<SttDiagnostics>({})
  const transcriptRef = useRef('')
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Text-to-speech ──────────────────────────────────────────────────────
  const [ttsPhase, setTtsPhase] = useState<Phase>('idle')
  const [ttsOutcome, setTtsOutcome] = useState<SttOutcome | null>(null)
  const ttsWatchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])

  const sttSupported = useMemo(() => Boolean(getSpeechRecognitionCtor()), [])
  const ttsSupported = useMemo(() => isSpeechSynthesisSupported(), [])

  useEffect(() => {
    if (!ttsSupported) return
    const load = () => setVoices(window.speechSynthesis.getVoices() || [])
    load()
    window.speechSynthesis.addEventListener?.('voiceschanged', load)
    return () => window.speechSynthesis.removeEventListener?.('voiceschanged', load)
  }, [ttsSupported])

  useEffect(() => {
    if (!navigator.mediaDevices?.enumerateDevices) return
    let cancelled = false
    navigator.mediaDevices
      .enumerateDevices()
      .then((list) => { if (!cancelled) setDevices(list) })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  const routing = useMemo(
    () => describeMicrophoneRouting(devices, getMediaPreferences().microphoneDeviceId),
    [devices],
  )

  const activeEngineId = getActiveTtsEngineId()
  const engineSettings = readTtsProviderSettings(activeEngineId)
  const resolvedVoiceId = resolveAssistantVoiceId(activeEngineId, engineSettings)
  const voiceLabel =
    activeEngineId === 'web-speech-api'
      ? describeAssistantVoice(resolvedVoiceId, voices)
      : resolvedVoiceId || 'engine default'

  const clearSttTimers = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  const finishSttTest = useCallback(() => {
    clearSttTimers()
    const outcome = explainSttOutcome(diagnosticsRef.current, transcriptRef.current)
    setSttOutcome(outcome)
    setSttPhase(outcome.ok ? 'ok' : 'error')
    setInterim('')
    microphoneDebug('settings', 'stt_test_finished', {
      ok: outcome.ok,
      headline: outcome.headline,
      characters: transcriptRef.current.trim().length,
      sawAudioStart: diagnosticsRef.current.sawAudioStart ?? null,
      sawSpeechStart: diagnosticsRef.current.sawSpeechStart ?? null,
      sawNoMatch: diagnosticsRef.current.sawNoMatch ?? null,
      error: diagnosticsRef.current.error ?? null,
    })
    recognitionRef.current = null
  }, [clearSttTimers])

  const stopSttTest = useCallback(() => {
    const recognition = recognitionRef.current
    if (!recognition) return
    microphoneDebug('settings', 'stt_test_stop_requested')
    try { recognition.stop() } catch { /* already ending */ }
  }, [])

  const startSttTest = useCallback(() => {
    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor) {
      setSttPhase('error')
      setSttOutcome({
        ok: false,
        headline: 'Speech recognition is not available',
        detail:
          'This browser does not implement the Web Speech API. Chrome, Edge, or another Chromium browser is required for voice input.',
      })
      microphoneDebug('settings', 'stt_test_unsupported')
      return
    }

    // A page can hold only one recognition session. Release any session that
    // hands-free voice mode or the chat microphone is holding, or this test
    // would fail with InvalidStateError through no fault of the device.
    /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
    const shared = (window as any).SpeechService
    try { shared?.abortSTT?.('settings_stt_test') } catch { /* best effort */ }

    diagnosticsRef.current = {
      sawAudioStart: false,
      sawSpeechStart: false,
      sawInterim: false,
      sawResult: false,
      sawNoMatch: false,
      error: null,
      lang: shared?.recognitionLang || navigator.language || 'en-US',
    }
    transcriptRef.current = ''
    setHeard('')
    setInterim('')
    setSttOutcome(null)
    setSttPhase('running')

    const recognition = new Ctor()
    recognition.continuous = false
    recognition.interimResults = true
    recognition.lang = diagnosticsRef.current.lang
    recognitionRef.current = recognition

    recognition.onaudiostart = () => { diagnosticsRef.current.sawAudioStart = true }
    recognition.onspeechstart = () => { diagnosticsRef.current.sawSpeechStart = true }
    recognition.onnomatch = () => { diagnosticsRef.current.sawNoMatch = true }

    recognition.onresult = (event: RecognitionResultEvent) => {
      let final = ''
      let partial = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const text = event.results[i][0].transcript
        if (event.results[i].isFinal) final += `${text} `
        else partial += text
      }
      if (partial) {
        diagnosticsRef.current.sawInterim = true
        setInterim(partial)
      }
      if (final) {
        diagnosticsRef.current.sawResult = true
        transcriptRef.current = `${transcriptRef.current} ${final}`.trim()
        // The transcript is shown to the user who just spoke it; the mic trace
        // deliberately records only its length.
        setHeard(transcriptRef.current)
      }
    }

    recognition.onerror = (event: RecognitionErrorEvent) => {
      diagnosticsRef.current.error = event.error || 'unknown'
      microphoneDebugError('settings', 'stt_test_error', new Error(event.error || 'unknown'))
    }

    recognition.onend = () => finishSttTest()

    timeoutRef.current = setTimeout(() => {
      timeoutRef.current = null
      microphoneDebug('settings', 'stt_test_timeout', { timeoutMs: STT_TEST_TIMEOUT_MS })
      try { recognition.stop() } catch { /* already ending */ }
    }, STT_TEST_TIMEOUT_MS)

    microphoneDebug('settings', 'stt_test_started', {
      lang: recognition.lang,
      selectedDeviceId: getMediaPreferences().microphoneDeviceId || 'system-default',
      recognitionDevice: 'browser-managed-web-speech',
      routingMismatch: routing.mismatch,
    })

    try {
      recognition.start()
    } catch (error) {
      clearSttTimers()
      recognitionRef.current = null
      const name = (error as { name?: string })?.name || 'start_failed'
      microphoneDebugError('settings', 'stt_test_start_failed', error)
      setSttPhase('error')
      setSttOutcome(explainSttError(name))
    }
  }, [clearSttTimers, finishSttTest, routing.mismatch])

  const clearTtsWatchdog = useCallback(() => {
    if (ttsWatchdogRef.current) {
      clearTimeout(ttsWatchdogRef.current)
      ttsWatchdogRef.current = null
    }
  }, [])

  const startTtsTest = useCallback(() => {
    const provider = getTtsProvider(activeEngineId)
    if (!provider || !provider.isAvailable()) {
      setTtsPhase('error')
      setTtsOutcome({
        ok: false,
        headline: 'No text-to-speech engine available',
        detail: 'This browser exposes no usable speech synthesis engine, so replies cannot be spoken.',
      })
      return
    }

    setTtsPhase('running')
    setTtsOutcome(null)
    let started = false

    // `speak()` neither resolves nor errors when it produces no audio, so the
    // test needs its own deadline to call that a failure.
    ttsWatchdogRef.current = setTimeout(() => {
      ttsWatchdogRef.current = null
      if (started) return
      try { provider.stop() } catch { /* ignore */ }
      setTtsPhase('error')
      setTtsOutcome({
        ok: false,
        headline: 'The voice never started speaking',
        detail:
          'The engine accepted the text but produced no audio. Check the output device and volume in Audio & Video, confirm the selected voice is still installed, and click once in the page before retesting — browsers block audio until the page has been interacted with.',
      })
      microphoneDebug('settings', 'tts_test_never_started', {
        engineId: activeEngineId,
        timeoutMs: TTS_START_TIMEOUT_MS,
      })
    }, TTS_START_TIMEOUT_MS)

    microphoneDebug('settings', 'tts_test_started', {
      engineId: activeEngineId,
      voiceId: resolvedVoiceId || 'system-default',
    })

    const fail = (message: string) => {
      clearTtsWatchdog()
      setTtsPhase('error')
      setTtsOutcome({
        ok: false,
        headline: 'Text-to-speech failed',
        detail: message,
      })
    }

    provider
      .speak(TTS_TEST_SENTENCE, {
        voiceId: resolvedVoiceId || undefined,
        onStart: () => {
          started = true
          clearTtsWatchdog()
        },
        onEnd: () => {
          clearTtsWatchdog()
          setTtsPhase('ok')
          setTtsOutcome({
            ok: true,
            headline: 'Text-to-speech is working',
            detail: `Spoken with ${voiceLabel}. If you heard nothing, raise the output volume and check the speaker selected in Audio & Video.`,
          })
          microphoneDebug('settings', 'tts_test_completed', { engineId: activeEngineId })
        },
        onError: (error) => fail(String(error?.message || error)),
      })
      .catch((error) => fail(String(error?.message || error)))
  }, [activeEngineId, clearTtsWatchdog, resolvedVoiceId, voiceLabel])

  const stopTtsTest = useCallback(() => {
    clearTtsWatchdog()
    const provider = getTtsProvider(activeEngineId)
    try { provider?.stop() } catch { /* ignore */ }
    setTtsPhase('idle')
    setTtsOutcome(null)
  }, [activeEngineId, clearTtsWatchdog])

  useEffect(() => () => {
    clearSttTimers()
    clearTtsWatchdog()
    try { recognitionRef.current?.abort?.() } catch { /* ignore */ }
  }, [clearSttTimers, clearTtsWatchdog])

  return (
    <div className="border-t border-white/5 pt-3" data-testid="voice-self-test">
      <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">
        Check voice input and output
      </div>
      <p className="text-[10px] text-white/40 leading-relaxed mb-3">
        Verify the whole path end to end: that your speech becomes text, and that replies are spoken
        with the voice selected above.
      </p>

      {routing.message ? (
        <div className="mb-3 rounded-xl border border-amber-500/25 bg-amber-500/[0.07] px-3 py-2.5 text-[10px] leading-relaxed text-amber-200/90">
          <span className="font-semibold">Microphone routing: </span>
          {routing.message}
        </div>
      ) : null}

      <div className="space-y-4">
        {/* ── Speech-to-text ── */}
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {sttPhase === 'running' ? (
              <button type="button" className={BUTTON_CLS} onClick={stopSttTest}>
                <Square size={13} /> Stop and check
              </button>
            ) : (
              <button
                type="button"
                className={BUTTON_CLS}
                onClick={startSttTest}
                disabled={!sttSupported}
              >
                <Mic2 size={13} /> {sttOutcome ? 'Test speech-to-text again' : 'Test speech-to-text'}
              </button>
            )}
            <span className="text-[10px] text-white/40">
              {sttPhase === 'running'
                ? 'Say a full sentence out loud.'
                : 'Records one turn and shows the text it produced.'}
            </span>
          </div>

          <Verdict phase={sttPhase} outcome={sttOutcome} runningLabel="Listening — speak now…" />

          {heard || interim ? (
            <div className="rounded-xl border border-white/10 bg-black/40 px-3 py-2.5">
              <div className="text-[10px] uppercase tracking-wider text-white/35 mb-1">
                Recognized text
              </div>
              <p className="text-xs text-white/85 leading-relaxed break-words">
                {heard}
                {interim ? <span className="text-white/40">{heard ? ' ' : ''}{interim}</span> : null}
              </p>
            </div>
          ) : null}
        </div>

        {/* ── Text-to-speech ── */}
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {ttsPhase === 'running' ? (
              <button type="button" className={BUTTON_CLS} onClick={stopTtsTest}>
                <Square size={13} /> Stop
              </button>
            ) : (
              <button
                type="button"
                className={BUTTON_CLS}
                onClick={startTtsTest}
                disabled={!ttsSupported}
              >
                <Volume2 size={13} /> {ttsOutcome ? 'Test text-to-speech again' : 'Test text-to-speech'}
              </button>
            )}
            <span className="text-[10px] text-white/40">Voice: {voiceLabel}</span>
          </div>

          <Verdict phase={ttsPhase} outcome={ttsOutcome} runningLabel="Speaking…" />
        </div>
      </div>

      <div className="mt-3 text-[10px] leading-relaxed text-white/30">
        Both tests write to the shared microphone trace. Open DevTools and filter the console for{' '}
        <span className="font-mono text-white/45">HomePilot:Mic</span> to see the full capture
        lifecycle; it records device and recognition state, never audio bytes or transcript text.
      </div>
    </div>
  )
}
