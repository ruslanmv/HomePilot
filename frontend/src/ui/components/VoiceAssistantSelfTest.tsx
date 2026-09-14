/**
 * Settings → Voice Assistant → "Check voice input and output".
 *
 * Three tests, each exercising the path production actually uses:
 *
 *   1. **Speech-to-text** — records the microphone selected in Audio & Video
 *      and transcribes it through HomePilot's own speech-to-text, then shows
 *      the text. Falls back to the browser recognizer only when the server has
 *      no speech provider, and says so, because that fallback records the OS
 *      default input rather than the selected device.
 *
 *   2. **Text-to-speech** — speaks through `window.SpeechService`, the same
 *      function that speaks assistant replies (including the Piper registry
 *      shim). A preview that called the provider directly could pass while
 *      real assistant audio failed.
 *
 *   3. **End-to-end** — record, transcribe, then read the recognized text back
 *      aloud. One button that proves the whole loop, which is the only check
 *      that can fail for a reason neither half-test would catch.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Mic2,
  RefreshCw,
  Repeat,
  Square,
  Volume2,
} from 'lucide-react'
import { getMediaPreferences } from '../media/mediaPreferences'
import { microphoneDebug, microphoneDebugError } from '../media/microphoneDebug'
import {
  getSttCapability,
  recordAndTranscribe,
  SttUnavailableError,
  type SttCapability,
} from '../media/sttService'
import {
  explainRuntimeTts,
  isRuntimeTtsAvailable,
  speakThroughRuntime,
  stopRuntimeTts,
} from '../media/runtimeTts'
import {
  TTS_TEST_SENTENCE,
  describeMicrophoneRouting,
  explainSttError,
  explainSttOutcome,
  getSpeechRecognitionCtor,
  type SttDiagnostics,
  type SttOutcome,
} from '../media/voiceSelfTest'
import {
  describeSttResolution,
  getSttPreferences,
  resolveSttEngine,
  subscribeSttPreferences,
} from '../media/sttPreferences'
import { acquireMicrophone, getMicrophoneLease, releaseMicrophone } from '../media/sttRuntime'
import {
  abortWebSpeech,
  isWebSpeechSupported,
  startWebSpeech,
  stopWebSpeech,
} from '../media/webSpeechSession'
import { getActiveTtsEngineId, readTtsProviderSettings } from '../tts'
import { describeAssistantVoice, resolveAssistantVoiceId } from '../tts/resolveAssistantVoice'

/** Ceiling on one recorded test turn. */
const RECORD_MAX_MS = 15_000

/**
 * Minimal shapes for the two recognition events read in the fallback path. The
 * bundled DOM lib declares neither `SpeechRecognitionEvent` nor
 * `SpeechRecognitionErrorEvent`, and only these fields are used.
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
      <div className="flex items-center gap-1.5 text-[11px] text-[#c8a7ff]" role="status">
        <RefreshCw size={12} className="animate-spin" /> {runningLabel}
      </div>
    )
  }
  if (phase === 'idle' || !outcome) return null
  const ok = phase === 'ok'
  return (
    <div
      role="status"
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

/** Input level meter, so a silent microphone is visible before the verdict. */
function LevelMeter({ level, active }: { level: number; active: boolean }) {
  return (
    <div
      className="h-1.5 rounded-full bg-white/10 overflow-hidden border border-white/[0.06]"
      aria-label={`Microphone input level ${Math.round(level * 100)}%`}
    >
      <div
        className="h-full bg-[#9b5cff] transition-[width] duration-75"
        style={{ width: `${active ? Math.max(2, level * 100) : 0}%` }}
      />
    </div>
  )
}

export default function VoiceAssistantSelfTest(): JSX.Element {
  // ── Speech-to-text ──────────────────────────────────────────────────────
  const [sttPhase, setSttPhase] = useState<Phase>('idle')
  const [sttOutcome, setSttOutcome] = useState<SttOutcome | null>(null)
  const [sttRunningLabel, setSttRunningLabel] = useState('Listening — speak now…')
  const [heard, setHeard] = useState('')
  const [interim, setInterim] = useState('')
  const [level, setLevel] = useState(0)

  const stopRecordingRef = useRef<(() => void) | null>(null)

  const diagnosticsRef = useRef<SttDiagnostics>({})
  const transcriptRef = useRef('')
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Text-to-speech ──────────────────────────────────────────────────────
  const [ttsPhase, setTtsPhase] = useState<Phase>('idle')
  const [ttsOutcome, setTtsOutcome] = useState<SttOutcome | null>(null)

  // ── End-to-end ──────────────────────────────────────────────────────────
  const [loopPhase, setLoopPhase] = useState<Phase>('idle')
  const [loopOutcome, setLoopOutcome] = useState<SttOutcome | null>(null)
  const [loopLabel, setLoopLabel] = useState('Listening — speak now…')

  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [capability, setCapability] = useState<SttCapability | null>(null)
  const [preference, setPreference] = useState(() => getSttPreferences().chat)

  const webSpeechSupported = useMemo(() => Boolean(getSpeechRecognitionCtor()), [])
  const ttsSupported = useMemo(() => isRuntimeTtsAvailable(), [])
  const recorderSupported =
    typeof MediaRecorder !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia)

  // The engine the *preference* resolves to, so these tests exercise what chat and Voice
  // will really use. Testing the backend merely because it is available would pass while the
  // path the user chose stayed broken — the exact trap this whole split exists to avoid.
  const resolution = useMemo(
    () => resolveSttEngine(preference, {
      backendAvailable: Boolean(capability?.available),
      mediaRecorderSupported: typeof MediaRecorder !== 'undefined'
        && Boolean(navigator.mediaDevices?.getUserMedia),
      webSpeechSupported,
    }),
    [preference, capability, webSpeechSupported],
  )
  const backendStt = resolution.engine === 'homepilot-backend'
  const sttSupported = (backendStt && recorderSupported) || webSpeechSupported

  useEffect(() => {
    if (!('speechSynthesis' in window)) return
    const load = () => setVoices(window.speechSynthesis.getVoices() || [])
    load()
    window.speechSynthesis.addEventListener?.('voiceschanged', load)
    return () => window.speechSynthesis.removeEventListener?.('voiceschanged', load)
  }, [])

  useEffect(() => {
    if (!navigator.mediaDevices?.enumerateDevices) return
    let cancelled = false
    navigator.mediaDevices
      .enumerateDevices()
      .then((list) => { if (!cancelled) setDevices(list) })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    void getSttCapability().then((value) => { if (!cancelled) setCapability(value) })
    return () => { cancelled = true }
  }, [])

  // Changing the engine in the card above re-aims these tests immediately.
  useEffect(() => subscribeSttPreferences((next) => setPreference(next.chat)), [])

  // The routing caveat applies only to the browser recognizer: the backend path
  // transcribes the very bytes captured from the selected device.
  const routing = useMemo(() => {
    if (backendStt) return { mismatch: false, known: true, message: null }
    return describeMicrophoneRouting(devices, getMediaPreferences().microphoneDeviceId)
  }, [devices, backendStt])

  const activeEngineId = getActiveTtsEngineId()
  const engineSettings = readTtsProviderSettings(activeEngineId)
  const resolvedVoiceId = resolveAssistantVoiceId(activeEngineId, engineSettings)
  const voiceLabel =
    activeEngineId === 'web-speech-api'
      ? describeAssistantVoice(resolvedVoiceId, voices)
      : `${activeEngineId}${resolvedVoiceId ? ` · ${resolvedVoiceId}` : ''}`

  const clearSttTimers = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  /* ── Browser-recognizer fallback ─────────────────────────────────────── */

  const finishFallbackTest = useCallback(() => {
    clearSttTimers()
    const outcome = explainSttOutcome(diagnosticsRef.current, transcriptRef.current)
    setSttOutcome(outcome)
    setSttPhase(outcome.ok ? 'ok' : 'error')
    setInterim('')
    microphoneDebug('settings', 'stt_test_finished', {
      engine: 'web-speech',
      ok: outcome.ok,
      headline: outcome.headline,
      characters: transcriptRef.current.trim().length,
      sawAudioStart: diagnosticsRef.current.sawAudioStart ?? null,
      sawSpeechStart: diagnosticsRef.current.sawSpeechStart ?? null,
      sawNoMatch: diagnosticsRef.current.sawNoMatch ?? null,
      sawInterim: diagnosticsRef.current.sawInterim ?? null,
      sawResult: diagnosticsRef.current.sawResult ?? null,
      stoppedBy: diagnosticsRef.current.stoppedBy ?? null,
      elapsedMs: diagnosticsRef.current.elapsedMs ?? null,
      lang: diagnosticsRef.current.lang ?? null,
      error: diagnosticsRef.current.error ?? null,
    })
  }, [clearSttTimers])

  const startFallbackTest = useCallback(async () => {
    if (!isWebSpeechSupported()) {
      setSttPhase('error')
      setSttOutcome({
        ok: false,
        headline: 'No speech-to-text available',
        detail:
          'This server has no speech provider configured and this browser does not implement the Web Speech API. Install local speech on the server, or use a Chromium browser.',
      })
      microphoneDebug('settings', 'stt_test_unsupported')
      return
    }

    /*
     * Take the microphone properly rather than aborting whoever has it.
     *
     * A page holds one recognition session, and this test used to grab it with a bare
     * `abortSTT`. That worked in one direction only: the Voice tab's hands-free loop restarts
     * itself every 400 ms, so it took the recognizer straight back and this test died with a
     * bare `aborted` before the user had finished the word they were saying —
     *
     *     [settings]       start_requested
     *     [settings]       stt_test_error {errorMessage: 'aborted'}
     *     [voice]          stt_onstart
     *
     * Acquiring the lease is what makes that impossible: the Voice loop checks the lease
     * before restarting and waits, and picks up again when this test releases.
     */
    /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
    const shared = (window as any).SpeechService
    await acquireMicrophone('settings', 'web-speech', () => abortWebSpeech('microphone_handoff'))

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
    setSttRunningLabel('Listening via browser recognizer — speak now…')
    setSttPhase('running')

    timeoutRef.current = setTimeout(() => {
      timeoutRef.current = null
      microphoneDebug('settings', 'stt_test_timeout', { timeoutMs: RECORD_MAX_MS })
      stopWebSpeech('settings', { reason: 'stt_test_timeout', force: true })
    }, RECORD_MAX_MS)

    // Everything known before the capture opens, so a turn that produces nothing can be read
    // against what was expected of it rather than guessed at afterwards.
    microphoneDebug('settings', 'stt_test_started', {
      engine: 'web-speech',
      lang: diagnosticsRef.current.lang,
      selectedDeviceId: getMediaPreferences().microphoneDeviceId || 'system-default',
      selectedDeviceLabel:
        devices.find((d) => d.deviceId === getMediaPreferences().microphoneDeviceId)?.label
        || 'system default',
      recognitionDevice: 'browser-managed-web-speech',
      // The prediction. When this is `true` the turn is expected to hear nothing, and a turn
      // that then hears nothing has confirmed the routing split rather than discovered a
      // new fault.
      routingMismatch: routing.mismatch,
      routingKnown: routing.known,
      sessionEngine: backendStt ? 'homepilot-backend' : 'web-speech',
      preference,
      backendAvailable: Boolean(capability?.available),
      timeoutMs: RECORD_MAX_MS,
    })

    const started = await startWebSpeech('settings', {
      onStart: () => microphoneDebug('settings', 'stt_test_recognition_started', {
        lang: diagnosticsRef.current.lang,
      }),
      onInterim: (text) => {
        diagnosticsRef.current.sawInterim = true
        setInterim(text)
      },
      onResult: (text) => {
        diagnosticsRef.current.sawResult = true
        transcriptRef.current = `${transcriptRef.current} ${text}`.trim()
        // Shown to the user who just spoke it; the mic trace records only length.
        setHeard(transcriptRef.current)
      },
      onEnd: (diagnostics) => {
        // The adapter's record is the browser's own; merge it over the local copy so the
        // verdict is built from what the recognizer reported, not from what reached a
        // handler this component happened to subscribe to.
        diagnosticsRef.current = { ...diagnosticsRef.current, ...diagnostics }
        void releaseMicrophone('settings')
        finishFallbackTest()
      },
      onError: (code) => {
        diagnosticsRef.current.error = code || 'unknown'
        microphoneDebugError('settings', 'stt_test_error', new Error(code || 'unknown'), {
          // `aborted` used to mean "the Voice tab took the microphone back". It should now
          // only appear when the user navigated away mid-test, so record who held it.
          microphoneOwner: getMicrophoneLease()?.owner ?? 'none',
        })
      },
    })

    if (!started) {
      clearSttTimers()
      void releaseMicrophone('settings')
      microphoneDebug('settings', 'stt_test_start_failed', {
        microphoneOwner: getMicrophoneLease()?.owner ?? 'none',
      })
      setSttPhase('error')
      setSttOutcome(explainSttError('start_failed'))
    }
  }, [
    clearSttTimers,
    finishFallbackTest,
    routing.mismatch,
    routing.known,
    devices,
    backendStt,
    preference,
    capability?.available,
  ])

  /* ── Backend path: record the selected device, transcribe server-side ── */

  const runBackendTest = useCallback(async () => {
    setHeard('')
    setInterim('')
    setSttOutcome(null)
    setSttRunningLabel('Listening — speak now, then press Stop and check.')
    setSttPhase('running')

    microphoneDebug('settings', 'stt_test_started', {
      engine: 'homepilot-backend',
      provider: capability?.provider ?? null,
      selectedDeviceId: getMediaPreferences().microphoneDeviceId || 'system-default',
    })

    try {
      const result = await recordAndTranscribe({
        scope: 'settings',
        maxMs: RECORD_MAX_MS,
        onRecording: ({ stop }) => { stopRecordingRef.current = stop },
        onLevel: setLevel,
      })
      stopRecordingRef.current = null
      setLevel(0)
      setHeard(result.text)

      const outcome: SttOutcome = result.text
        ? {
            ok: true,
            headline: 'Speech-to-text is working',
            detail: `Transcribed ${result.text.length} character${result.text.length === 1 ? '' : 's'} from ${result.deviceLabel} using ${result.provider || 'HomePilot speech-to-text'}${result.remote ? ' (remote service)' : ''}.`,
          }
        : {
            ok: false,
            headline: 'No speech found in the recording',
            detail: `The recording from ${result.deviceLabel} reached ${result.provider || 'the transcriber'} but contained no speech. Watch the level meter while you speak — if it does not move, the wrong input is selected in Audio & Video.`,
          }
      setSttOutcome(outcome)
      setSttPhase(outcome.ok ? 'ok' : 'error')
      microphoneDebug('settings', 'stt_test_finished', {
        engine: 'homepilot-backend',
        ok: outcome.ok,
        headline: outcome.headline,
        characters: result.text.length,
        provider: result.provider,
      })
    } catch (error) {
      stopRecordingRef.current = null
      setLevel(0)
      microphoneDebugError('settings', 'stt_test_backend_failed', error)

      if (error instanceof SttUnavailableError) {
        // The server lost its provider since the capability probe; fall back
        // rather than reporting a failure the user cannot act on.
        microphoneDebug('settings', 'stt_test_fallback_web_speech')
        setCapability({ available: false, provider: null, remote: false, hint: error.message })
        startFallbackTest()
        return
      }
      setSttPhase('error')
      setSttOutcome({
        ok: false,
        headline: 'Speech-to-text failed',
        detail: error instanceof Error ? error.message : 'The recording could not be transcribed.',
      })
    }
  }, [capability?.provider, startFallbackTest])

  const startSttTest = useCallback(() => {
    if (backendStt && recorderSupported) {
      void runBackendTest()
      return
    }
    startFallbackTest()
  }, [backendStt, recorderSupported, runBackendTest, startFallbackTest])

  const stopSttTest = useCallback(() => {
    microphoneDebug('settings', 'stt_test_stop_requested')
    // Stopping means "transcribe what I said", not "discard it".
    if (stopRecordingRef.current) {
      setSttRunningLabel('Transcribing…')
      stopRecordingRef.current()
      return
    }
    // An explicit press of Stop must stop now, not after the recognizer's warm-up guard.
    stopWebSpeech('settings', { reason: 'stt_test_stop_requested', force: true })
  }, [])

  /* ── Text-to-speech through the runtime path ─────────────────────────── */

  const startTtsTest = useCallback(async () => {
    setTtsPhase('running')
    setTtsOutcome(null)
    const result = await speakThroughRuntime(TTS_TEST_SENTENCE)
    const outcome = explainRuntimeTts(result, voiceLabel)
    setTtsOutcome(outcome)
    setTtsPhase(outcome.ok ? 'ok' : 'error')
  }, [voiceLabel])

  const stopTtsTest = useCallback(() => {
    stopRuntimeTts()
    setTtsPhase('idle')
    setTtsOutcome(null)
  }, [])

  /* ── End-to-end: speech → text → voice ──────────────────────────────── */

  const startLoopTest = useCallback(async () => {
    setLoopOutcome(null)
    setLoopLabel('Listening — say a short sentence, then press Stop and check.')
    setLoopPhase('running')
    setHeard('')

    microphoneDebug('settings', 'voice_loop_test_started', {
      // Always the local engine: this check exists to prove the selected microphone reaches
      // a transcriber and comes back as speech, and only that path records the selected
      // device. The session's own engine is recorded alongside so the trace says when the
      // two differ rather than leaving it to be inferred.
      engine: 'homepilot-backend',
      sessionEngine: backendStt ? 'homepilot-backend' : 'web-speech',
      preference,
      provider: capability?.provider ?? null,
      remote: Boolean(capability?.remote),
      selectedDeviceId: getMediaPreferences().microphoneDeviceId || 'system-default',
      voiceId: resolvedVoiceId || 'system-default',
      ttsEngine: activeEngineId,
    })

    /*
     * Gated on whether this check *can run*, not on which engine the preference resolved to.
     *
     * It used to refuse whenever the session was on the browser recognizer — which is the
     * default — and then tell the user to install a speech model. On a server that already
     * had one, that instruction was simply false, and it sent people to install software
     * they were already running. The end-to-end check needs a recorder and a server that can
     * transcribe; the preference decides what *chat and Voice* use, which is a different
     * question and not this one.
     */
    const loopCanRun = Boolean(capability?.available) && recorderSupported
    if (!loopCanRun) {
      setLoopPhase('error')
      setLoopOutcome({
        ok: false,
        headline: recorderSupported
          ? 'The end-to-end check needs HomePilot speech-to-text'
          : 'This browser cannot record audio',
        detail: recorderSupported
          ? (capability?.hint
            || 'This check records the selected microphone and transcribes it on the server, so it needs a speech model there. Install local speech (pip install -r requirements/speech-cpu.txt) or configure STT_BASE_URL, then try again.')
          : 'MediaRecorder is unavailable here, so the selected microphone cannot be recorded. Use a Chromium or Firefox build that supports it.',
      })
      microphoneDebug('settings', 'voice_loop_test_unavailable', {
        backendAvailable: Boolean(capability?.available),
        recorderSupported,
        provider: capability?.provider ?? null,
      })
      return
    }

    try {
      const result = await recordAndTranscribe({
        scope: 'settings',
        maxMs: RECORD_MAX_MS,
        onRecording: ({ stop }) => { stopRecordingRef.current = stop },
        onLevel: setLevel,
      })
      stopRecordingRef.current = null
      setLevel(0)
      setHeard(result.text)

      if (!result.text) {
        setLoopPhase('error')
        setLoopOutcome({
          ok: false,
          headline: 'Nothing was transcribed, so there is nothing to read back',
          detail: `The recording from ${result.deviceLabel} contained no speech. Fix the input first, then run this check again.`,
        })
        return
      }

      setLoopLabel('Reading it back…')
      const spoken = await speakThroughRuntime(`I heard: ${result.text}`)
      if (!spoken.ok) {
        const ttsVerdict = explainRuntimeTts(spoken, voiceLabel)
        setLoopPhase('error')
        setLoopOutcome({
          ok: false,
          headline: `Transcribed, but could not speak it back: ${ttsVerdict.headline.toLowerCase()}`,
          detail: ttsVerdict.detail,
        })
        return
      }

      setLoopPhase('ok')
      setLoopOutcome({
        ok: true,
        headline: 'The whole voice loop is working',
        detail: `Recorded ${result.deviceLabel}, transcribed it with ${result.provider || 'HomePilot speech-to-text'}, and read it back with ${voiceLabel}.`
          // Said out loud rather than left to be discovered: this check passing does not mean
          // the engine chat and Voice are using works, and on a machine where the browser
          // recognizer is deaf that difference is the whole problem.
          + (backendStt
            ? ''
            : ' Note that chat and Voice are set to the browser’s speech recognition, which'
              + ' records your system default input rather than this microphone — this check'
              + ' does not exercise that path.'),
      })
      microphoneDebug('settings', 'voice_loop_test_completed', {
        characters: result.text.length,
        provider: result.provider,
        remote: result.remote,
        deviceLabel: result.deviceLabel,
        bytes: result.bytes,
        elapsedMs: result.elapsedMs,
        sessionEngine: backendStt ? 'homepilot-backend' : 'web-speech',
      })
    } catch (error) {
      stopRecordingRef.current = null
      setLevel(0)
      microphoneDebugError('settings', 'voice_loop_test_failed', error)
      setLoopPhase('error')
      setLoopOutcome({
        ok: false,
        headline: 'The end-to-end check could not finish',
        detail: error instanceof Error ? error.message : 'Recording or transcription failed.',
      })
    }
  }, [backendStt, recorderSupported, capability?.hint, resolvedVoiceId, voiceLabel])

  const stopLoopTest = useCallback(() => {
    if (stopRecordingRef.current) {
      setLoopLabel('Transcribing…')
      stopRecordingRef.current()
      return
    }
    stopRuntimeTts()
    setLoopPhase('idle')
  }, [])

  useEffect(() => () => {
    clearSttTimers()
    stopRuntimeTts()
    // Leaving Settings gives the microphone back, so the Voice tab's hands-free loop — which
    // has been waiting on the lease rather than fighting for it — resumes on its next tick.
    abortWebSpeech('settings_unmount')
    void releaseMicrophone('settings')
    try { stopRecordingRef.current?.() } catch { /* ignore */ }
  }, [clearSttTimers])

  const engineLine = capability === null
    ? 'Checking which speech-to-text engine is in use…'
    : `Speech-to-text: ${describeSttResolution(resolution, capability.provider)}${
      capability.remote && backendStt ? ' Recordings leave this computer.' : ''}`

  const recording = sttPhase === 'running' || loopPhase === 'running'

  return (
    <div className="border-t border-white/5 pt-3" data-testid="voice-self-test">
      <div className="text-[11px] uppercase tracking-wider text-white/40 mb-2 font-semibold">
        Check voice input and output
      </div>
      <p className="text-[10px] text-white/40 leading-relaxed mb-1">
        Each test runs the same path the assistant uses, so a pass here means voice works in chat.
      </p>
      <p className="text-[10px] text-white/35 leading-relaxed mb-3">{engineLine}</p>

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
                disabled={!sttSupported || loopPhase === 'running'}
              >
                <Mic2 size={13} /> {sttOutcome ? 'Test speech-to-text again' : 'Test speech-to-text'}
              </button>
            )}
            <span className="text-[10px] text-white/40">
              Records one turn and shows the text it produced.
            </span>
          </div>

          <LevelMeter level={level} active={recording} />
          <Verdict phase={sttPhase} outcome={sttOutcome} runningLabel={sttRunningLabel} />
        </div>

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
                onClick={() => void startTtsTest()}
                disabled={!ttsSupported}
              >
                <Volume2 size={13} /> {ttsOutcome ? 'Test text-to-speech again' : 'Test text-to-speech'}
              </button>
            )}
            <span className="text-[10px] text-white/40">Voice: {voiceLabel}</span>
          </div>

          <Verdict phase={ttsPhase} outcome={ttsOutcome} runningLabel="Speaking…" />
        </div>

        {/* ── End-to-end ── */}
        <div className="space-y-2 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
          <div className="flex flex-wrap items-center gap-2">
            {loopPhase === 'running' ? (
              <button type="button" className={BUTTON_CLS} onClick={stopLoopTest}>
                <Square size={13} /> Stop and check
              </button>
            ) : (
              <button
                type="button"
                className={BUTTON_CLS}
                onClick={() => void startLoopTest()}
                disabled={sttPhase === 'running' || !recorderSupported}
              >
                <Repeat size={13} /> {loopOutcome ? 'Run the full check again' : 'Test speech → text → voice'}
              </button>
            )}
            <span className="text-[10px] text-white/40">
              Records you, transcribes it, then reads it back aloud.
            </span>
          </div>

          <Verdict phase={loopPhase} outcome={loopOutcome} runningLabel={loopLabel} />
        </div>
      </div>

      <div className="mt-3 text-[10px] leading-relaxed text-white/30">
        All three tests write to the shared microphone trace. Open DevTools and filter the console
        for <span className="font-mono text-white/45">HomePilot:Mic</span> to see the full capture
        lifecycle; it records device and recognition state, never audio bytes or transcript text.
      </div>
    </div>
  )
}
