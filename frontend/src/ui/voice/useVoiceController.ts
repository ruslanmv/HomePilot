/**
 * Unified Voice Controller Hook
 *
 * Industry-standard state machine for voice interaction:
 * - OFF: Voice features disabled
 * - IDLE: Waiting for speech
 * - LISTENING: The user is speaking (a turn is being captured)
 * - THINKING: Processing user input (waiting for LLM)
 * - SPEAKING: TTS playing response
 *
 * ── The engine owns transcription ──────────────────────────────────────────────────────
 *
 * There are two transcription architectures here and they are mutually exclusive. Running
 * both as turn owners was the bug:
 *
 *   - `homepilot-backend` — HomePilot's VAD opens the microphone selected in Audio & Video,
 *     `MediaRecorder` borrows *that exact stream*, and the clip goes to
 *     `POST /v1/voice/transcribe`. Detection and transcription cannot disagree about the
 *     device, and the level meter is reading the same audio that gets transcribed.
 *   - `web-speech` — the browser's recognizer opens its own opaque capture, on the operating
 *     system's default input, and accepts neither a `deviceId` nor a `MediaStream`. It streams
 *     interim words, which is the one thing the local path cannot do. HomePilot may also open
 *     a read-only default-input monitor stream for the visual meter; that stream never runs
 *     VAD, never records a turn and is never transcribed.
 *
 * Hands-free used to start the VAD *and* then ask the browser recognizer to transcribe. Two
 * turn owners on two different devices, one turn, no error from either:
 *
 *     [vad]   capture_opened          ← the selected microphone, held open all session
 *     [voice] stt_onstart             ← a second capture, on the OS default
 *     [voice] stt_onend { hadResult: false, sawSpeechStart: false }
 *
 * So the orb tracked the speaker and nothing came out. No warm-up window or grace period can
 * fix that; the recognizer was never listening to the microphone the VAD was using. Now the
 * resolved engine decides who owns turns and transcription. The optional Web Speech meter is
 * deliberately observation-only, so it cannot start/stop a turn or send different audio to STT.
 *
 * Barge-in belongs to the VAD path for the same reason: the Web Speech meter is intentionally
 * not a second speech detector, and leaving the recognizer running while TTS plays would feed
 * the assistant's own voice back in as the next turn. There, listening stops while TTS plays
 * and resumes after — reported through `bargeInSupported` rather than silently absent.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { createVAD, VADInstance, VADConfig } from './vad';
import { microphoneDebug, microphoneDebugError } from '../media/microphoneDebug';
import {
  openSelectedMicrophone,
  SttUnavailableError,
  transcribeBlob,
} from '../media/sttService';
import type { ResolvedSttEngine, SttResolution } from '../media/sttPreferences';
import {
  acquireMicrophone,
  applySttSessionOverride,
  getMicrophoneLease,
  releaseMicrophone,
  describeEngineHandoff,
  rememberRecognizerIsDeaf,
  subscribeEffectiveEngine,
  systemDefaultMicrophoneLabel,
} from '../media/sttRuntime';
import { useSttRuntime } from '../media/useSttRuntime';
import {
  abortWebSpeech,
  isWebSpeechSupported,
  startWebSpeech,
  stopWebSpeech,
} from '../media/webSpeechSession';
import { isDeafTurn, planSttRecovery } from '../media/sttTurnHealth';
import {
  browserInputMeterAvailable,
  startBrowserInputMeter,
  type BrowserInputMeter,
} from './browserInputMeter';

export type VoiceState = 'OFF' | 'IDLE' | 'LISTENING' | 'THINKING' | 'SPEAKING';

export interface VoiceControllerConfig {
  vadConfig?: Partial<VADConfig>;
  ttsEndDelay?: number;
  bargeInEnabled?: boolean;
  /** Ignore mic-start events for this long after TTS ends. */
  postTtsMicGuardMs?: number;
}

export interface VoiceController {
  state: VoiceState;
  isHandsFree: boolean;
  isTtsEnabled: boolean;
  interimText: string;
  audioLevel: number;
  noiseFloor: number;
  threshold: number;

  sttSupported: boolean;
  lastError: string | null;
  clearError: () => void;

  /**
   * Which transcription path owns the microphone this session, or `null` while the
   * capability probe is still in flight.
   *
   * `null` is deliberate and must be respected by callers: nothing may open a capture before
   * it resolves. Defaulting to the browser during the probe is what sent the first sentence
   * of a session — the one that matters most — through an engine the user did not choose.
   */
  sttEngine: ResolvedSttEngine | null;
  /** False while the engine is still being decided. */
  sttReady: boolean;
  /** Name of the server-side provider when one is in use. */
  sttProvider: string | null;
  /** How the engine was arrived at, including whether the user's choice was overridden. */
  sttResolution: SttResolution | null;
  /**
   * A change HomePilot made to the transcription path on its own, in words for the user.
   *
   * Set when a run of turns proves the browser recognizer is recording a silent device —
   * see `media/sttTurnHealth`. `null` the rest of the time.
   */
  sttNotice: string | null;
  dismissSttNotice: () => void;

  /** True when Voice has a real audio source for the visual input meter. */
  micMeterSupported: boolean;
  /**
   * Which device the meter is reading, on the browser engine only.
   *
   * There the meter and the recognizer both get the OS default input — not the microphone
   * chosen in Audio & Video — so a bar that never moves is the honest rendering of a silent
   * default rather than a broken meter. Naming the device is what lets the user tell those
   * apart without reading a log.
   */
  micMeterDeviceLabel: string | null;
  /** Words appear while you speak only on the browser engine. */
  liveTranscriptSupported: boolean;
  /** Speaking over the assistant needs the VAD, so only the local engine can do it. */
  bargeInSupported: boolean;

  setHandsFree: (enabled: boolean) => void;
  setTtsEnabled: (enabled: boolean) => void;
  startManualListening: () => Promise<boolean>;
  stopManualListening: () => void;
  stopSpeaking: () => void;
  setListeningSuppressed: (suppressed: boolean, reason?: string) => void;

  voices: SpeechSynthesisVoice[];
  selectedVoice: string;
  setSelectedVoice: (voiceURI: string) => void;
}

const DEFAULT_CONFIG: VoiceControllerConfig = {
  ttsEndDelay: 300,
  bargeInEnabled: true,
  postTtsMicGuardMs: 650,
  vadConfig: {
    baseThreshold: 0.035,
    hysteresisHigh: 1.8,
    hysteresisLow: 0.9,
    minSpeechMs: 200,
    silenceMs: 800,
  },
};

/** Gap between a hands-free browser turn ending and the next one opening. */
const BROWSER_RESTART_MS = 400;
/**
 * How often the hands-free loop re-checks a microphone another surface is holding.
 *
 * Slow on purpose: while the chat composer or the Settings test has the recognizer, this loop
 * has nothing to do, and polling it faster would only make the moment of release a race.
 */
const BROWSER_YIELD_POLL_MS = 1000;
/**
 * A turn shorter than this never listened to anything — the recognizer refused and ended
 * immediately. Backing off stops a refusal from becoming a hot loop of `start()` calls.
 */
const BROWSER_MIN_HEALTHY_TURN_MS = 300;
const BROWSER_MAX_CONSECUTIVE_FAILURES = 5;

/** Recognizer errors that will not fix themselves; restarting only repeats them. */
const FATAL_RECOGNITION_ERRORS = new Set([
  'not-allowed',
  'service-not-allowed',
  'audio-capture',
  'not-supported',
]);

/**
 * Recognizer outcomes that are not faults, and must never reach the user as one.
 *
 * A hands-free session is listening to a room, and a room is mostly quiet. `no-speech` is
 * Chrome saying "nobody said anything", which is the normal state of waiting; `aborted` is
 * HomePilot itself taking the microphone back for TTS or a hand-off. Reporting either as an
 * error puts a red banner under the orb every few seconds of an otherwise perfect session.
 */
const BENIGN_RECOGNITION_ERRORS = new Set(['no-speech', 'aborted']);

declare global {
  interface Window {
    SpeechService?: any;
  }
}

export function useVoiceController(
  onSendText: (text: string) => void,
  config?: VoiceControllerConfig
): VoiceController {
  const cfg = { ...DEFAULT_CONFIG, ...config };
  const svc = window.SpeechService;

  const mediaRecorderSupported =
    typeof window !== 'undefined' &&
    typeof MediaRecorder !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia;

  const [state, setState] = useState<VoiceState>('OFF');
  const [isHandsFree, setIsHandsFree] = useState(() => {
    const saved = localStorage.getItem('homepilot_voice_handsfree');
    return saved === null || saved === 'true';
  });
  const [isTtsEnabled, setIsTtsEnabled] = useState(() => {
    return localStorage.getItem('homepilot_tts_enabled') !== 'false';
  });
  const [interimText, setInterimText] = useState('');
  const [lastError, setLastError] = useState<string | null>(null);
  const [audioLevel, setAudioLevel] = useState(0);
  const [noiseFloor, setNoiseFloor] = useState(0);
  const [threshold, setThreshold] = useState(0);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [selectedVoice, setSelectedVoiceState] = useState<string>(() => {
    return localStorage.getItem('homepilot_voice_uri') || '';
  });
  const [sttNotice, setSttNotice] = useState<string | null>(null);
  const [browserMeterSupported, setBrowserMeterSupported] = useState(() => browserInputMeterAvailable());
  /**
   * The device the browser meter is reading, when it is the one open.
   *
   * Only ever set on the Web Speech path. On the local engine the meter reads the microphone
   * chosen in Audio & Video, which Settings already shows and which cannot disagree with what
   * gets transcribed — so there is nothing to disclose and a label would be clutter.
   */
  const [micMeterDeviceLabel, setMicMeterDeviceLabel] = useState<string | null>(null);

  /**
   * The engine decision, shared with the chat composer rather than duplicated.
   *
   * Both surfaces read one object, so a recovery made here is the engine there too — the
   * inconsistency that made "Settings says one choice for Chat and Voice" only half true.
   */
  const runtime = useSttRuntime();
  const sttEngine = runtime.effectiveEngine;
  const sttProvider = runtime.capability?.provider ?? null;
  const sttResolution = runtime.resolution;

  const sttEngineRef = useRef<ResolvedSttEngine | null>(null);
  const backendUsableRef = useRef(false);

  /**
   * Evidence that the browser recognizer is listening to a device that hears nothing.
   *
   * The count is consecutive and any turn that produces words resets it: a microphone that
   * works once works.
   */
  const deafTurnsRef = useRef(0);

  /**
   * Turns completed since this Voice session started listening.
   *
   * ── Why the first one is never evidence ──────────────────────────────────────────────────
   *
   * Opening Voice and pressing the listen button is how people *check* that Voice is there.
   * They press it, look at the orb, and often say nothing at all — there is nothing to say
   * yet, the session has only just opened. That turn ends exactly like a deaf one: a capture
   * opened, stayed open, and heard no speech, because none was spoken.
   *
   * Since a deliberate turn recovers on the very first one, that ordinary first press was
   * enough to move the whole session onto another engine and put a paragraph on screen
   * explaining a fault that had not happened. "The first time we click on Voice is normal, we
   * don't have voice" is that, exactly.
   *
   * So the first turn of a session is a warm-up: counted, never used as evidence. It costs one
   * turn to reach a verdict that was never trustworthy on its own, and it removes the only
   * case where the detector fires at somebody whose microphone is fine.
   */
  const turnsThisSessionRef = useRef(0);
  /** The provider name, reachable from a subscription that must not re-run when it changes. */
  const capabilityProviderRef = useRef<string | null>(null);

  /**
   * Whether *some* path can transcribe with the engine that is actually running.
   *
   * Deliberately not "does this browser implement the Web Speech API": with backend
   * transcription the browser only has to be able to record, so gating voice on Web Speech
   * would refuse a perfectly working setup (Firefox, or a Chromium build without the
   * recognizer).
   */
  const webSpeechSupported = isWebSpeechSupported();
  const sttSupported =
    sttEngine === 'homepilot-backend'
      ? mediaRecorderSupported
      : sttEngine === 'web-speech'
        ? webSpeechSupported
        : mediaRecorderSupported || webSpeechSupported;

  const vadRef = useRef<VADInstance | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recorderChunksRef = useRef<Blob[]>([]);
  const recorderDiscardRef = useRef(false);
  /** Set while a turn is opening its own capture — an async window the recorder ref cannot cover. */
  const recorderStartingRef = useRef(false);
  const stateRef = useRef<VoiceState>(state);
  const ttsEndTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const thinkingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingResultRef = useRef<boolean>(false);
  const lastSttEndRef = useRef<number>(0);
  const postTtsMicGuardUntilRef = useRef<number>(0);
  const handsFreeGenerationRef = useRef<number>(0);
  const listeningSuppressedRef = useRef<boolean>(false);
  const browserRestartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const browserTurnStartedAtRef = useRef<number>(0);
  const browserFailuresRef = useRef(0);
  /** Whether the open turn was started by a press rather than by the hands-free loop. */
  const turnWasDeliberateRef = useRef(false);
  /** Read-only meter stream used only while Web Speech owns transcription. */
  const browserMeterRef = useRef<BrowserInputMeter | null>(null);
  const browserMeterGenerationRef = useRef(0);
  const browserMeterStartingRef = useRef<number | null>(null);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    sttEngineRef.current = sttEngine;
  }, [sttEngine]);

  useEffect(() => {
    backendUsableRef.current = runtime.backendUsable;
  }, [runtime.backendUsable]);

  /**
   * A recovery started anywhere in the session is said out loud here too — **and taken back
   * when it stops being true.**
   *
   * The chat composer can be the surface that discovers the recognizer is deaf. The user is
   * one person with one microphone, so the explanation belongs wherever they look next.
   *
   * The clearing half was missing, and it is what made this notice feel permanent. Choosing an
   * engine in Settings drops the session override and its message — that is the whole point of
   * a deliberate choice outranking a recovery — but Voice only ever *set* the text, so the
   * paragraph explaining that HomePilot had switched engines stayed on screen after the user
   * had switched them back by hand. Assigning the value, rather than assigning it when truthy,
   * is the entire fix.
   */
  useEffect(() => {
    setSttNotice(runtime.sessionOverrideMessage);
  }, [runtime.sessionOverrideMessage]);

  /**
   * The engine changed while Voice was open, so say what it changed to.
   *
   * Short and factual. The capture effect below already performs the hand-off — it is keyed on
   * the engine, so it tears the old capture down and opens the new one — but a change of where
   * the audio *goes* must never be silent, and the recovery paragraph is the wrong text for a
   * change the user asked for.
   */
  useEffect(() => subscribeEffectiveEngine((next) => {
    setSttNotice(describeEngineHandoff(next, capabilityProviderRef.current));
    // A new engine is a new question. Evidence gathered about the old one says nothing about
    // this one, and carrying it over is how one deaf browser turn could switch an engine the
    // user had just chosen.
    deafTurnsRef.current = 0;
    turnsThisSessionRef.current = 0;
  }), []);

  /**
   * The newest `onSendText` and hands-free flag, reachable without depending on them.
   *
   * Callers pass `onSendText` as a plain function declared in their component body, so its
   * identity changes on every render — `VoiceModeGrok` does exactly that. A `useCallback`
   * that lists it therefore also changes every render, and anything listing *that* in an
   * effect restarts on every render. When the effect in question is the one that opens the
   * microphone, the restart calls `setState`, which renders, which restarts it again: the
   * capture tears down and reopens in a loop and Voice never becomes usable.
   *
   * Reading through a ref keeps the turn handlers stable, so the capture effect restarts only
   * when the capture configuration genuinely changes.
   */
  const onSendTextRef = useRef(onSendText);
  const isHandsFreeRef = useRef(isHandsFree);
  useEffect(() => { onSendTextRef.current = onSendText; }, [onSendText]);
  useEffect(() => { isHandsFreeRef.current = isHandsFree; }, [isHandsFree]);
  useEffect(() => { capabilityProviderRef.current = sttProvider; }, [sttProvider]);

  /**
   * A session begins when listening is switched on, and its warm-up turn comes with it.
   *
   * Keyed on `isHandsFree` rather than on mount: leaving Voice and coming back is a new
   * session to the user whether or not the component was destroyed in between, and the first
   * press after returning is the same "is this thing on?" press as the first press ever.
   */
  useEffect(() => {
    if (!isHandsFree) return;
    turnsThisSessionRef.current = 0;
    deafTurnsRef.current = 0;
  }, [isHandsFree]);

  useEffect(() => {
    if (state === 'THINKING' && isHandsFree) {
      thinkingTimeoutRef.current = setTimeout(() => {
        if (stateRef.current === 'THINKING') {
          console.warn('[VoiceController] THINKING timeout - returning to IDLE');
          setState('IDLE');
        }
      }, 4000);
    } else if (thinkingTimeoutRef.current) {
      clearTimeout(thinkingTimeoutRef.current);
      thinkingTimeoutRef.current = null;
    }

    return () => {
      if (thinkingTimeoutRef.current) {
        clearTimeout(thinkingTimeoutRef.current);
        thinkingTimeoutRef.current = null;
      }
    };
  }, [state, isHandsFree]);

  useEffect(() => {
    localStorage.setItem('homepilot_tts_enabled', String(isTtsEnabled));
  }, [isTtsEnabled]);

  useEffect(() => {
    if (!svc) return;

    const loadVoices = () => {
      const availableVoices = svc.getVoices?.() || [];
      setVoices(availableVoices);

      if (!selectedVoice && availableVoices.length > 0) {
        const defaultVoice = availableVoices.find((v: SpeechSynthesisVoice) =>
          v.name.toLowerCase().includes('google') && v.lang.startsWith('en')
        ) || availableVoices.find((v: SpeechSynthesisVoice) => v.default)
          || availableVoices[0];

        const voiceURI = defaultVoice.voiceURI;
        setSelectedVoiceState(voiceURI);
        localStorage.setItem('homepilot_voice_uri', voiceURI);
      }
    };

    loadVoices();
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }
  }, [svc, selectedVoice]);

  useEffect(() => {
    if (!svc || !selectedVoice) return;
    svc.setPreferredVoiceURI?.(selectedVoice);
  }, [svc, selectedVoice]);

  const setSelectedVoice = useCallback((voiceURI: string) => {
    setSelectedVoiceState(voiceURI);
    localStorage.setItem('homepilot_voice_uri', voiceURI);
  }, []);

  /**
   * Stop and discard any in-flight recorder without transcribing it.
   *
   * Used for barge-in, turn locks and teardown — cases where the audio is no
   * longer wanted, so paying for a transcription would be wrong.
   */
  const discardRecording = useCallback((reason: string) => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    recorderDiscardRef.current = true;
    microphoneDebug('voice', 'recorder_discarded', { reason });
    try { if (recorder.state !== 'inactive') recorder.stop(); } catch { /* already stopping */ }
    recorderRef.current = null;
  }, []);

  /**
   * Record this turn, preferring the VAD's own capture so detection and transcription cannot
   * disagree about the device.
   *
   * When the VAD is not running there is no such capture to borrow, and this used to give up
   * with `microphone_not_open`. That is every press of the manual listen button on the local
   * engine — the VAD exists only in hands-free mode — so "press to talk" was a dead button
   * for anyone on `homepilot-backend`, including anyone the deaf-recognizer recovery had just
   * moved there. It opens the selected microphone itself in that case, and closes it again
   * when the turn ends: a capture this function opened is a capture it owns, and leaving one
   * live would hold the recording indicator on between turns.
   */
  const startRecordingTurn = useCallback(async (reason: string): Promise<boolean> => {
    if (recorderRef.current || recorderStartingRef.current) {
      microphoneDebug('voice', 'recorder_start_skipped_active', { reason });
      return true;
    }
    if (typeof MediaRecorder === 'undefined') {
      microphoneDebug('voice', 'recorder_unavailable_mediarecorder', { reason });
      setLastError('mediarecorder_unavailable');
      return false;
    }

    let stream = vadRef.current?.getStream?.() || null;
    let ownedStream: MediaStream | null = null;
    if (!stream) {
      // Opening a device is async, so the guard above cannot cover this window on its own:
      // a second trigger arriving mid-open would start a competing recorder.
      recorderStartingRef.current = true;
      try {
        microphoneDebug('voice', 'recorder_opening_own_capture', { reason });
        ownedStream = await openSelectedMicrophone('voice');
        stream = ownedStream;
      } catch (error) {
        microphoneDebugError('voice', 'recorder_open_capture_failed', error, { reason });
        setLastError(error instanceof Error ? error.message : 'microphone_not_open');
        return false;
      } finally {
        recorderStartingRef.current = false;
      }
    }

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream);
    } catch (error) {
      microphoneDebugError('voice', 'recorder_construct_failed', error, { reason });
      setLastError(error instanceof Error ? error.message : 'recorder_failed');
      return false;
    }

    recorderRef.current = recorder;
    recorderChunksRef.current = [];
    recorderDiscardRef.current = false;

    recorder.ondataavailable = (event) => {
      if (event.data?.size) recorderChunksRef.current.push(event.data);
    };

    // Only a capture this turn opened. The VAD's own stream is borrowed and must outlive the
    // turn, so releasing it here would shut down speech detection after the first sentence.
    const releaseOwnedStream = () => {
      if (!ownedStream) return;
      ownedStream.getTracks().forEach((track) => track.stop());
      microphoneDebug('voice', 'recorder_released_own_capture');
      ownedStream = null;
    };

    recorder.onerror = (event) => {
      const error = (event as Event & { error?: DOMException }).error;
      microphoneDebugError('voice', 'recorder_error', error || new Error('recorder_failed'));
      recorderRef.current = null;
      recorderChunksRef.current = [];
      releaseOwnedStream();
      setLastError('recorder_failed');
      setState(isHandsFreeRef.current ? 'IDLE' : 'OFF');
    };

    recorder.onstop = () => {
      const chunks = recorderChunksRef.current;
      const discarded = recorderDiscardRef.current;
      recorderChunksRef.current = [];
      recorderRef.current = null;
      recorderDiscardRef.current = false;
      releaseOwnedStream();

      if (discarded) return;

      const blob = new Blob(chunks, {
        type: recorder.mimeType || chunks[0]?.type || 'audio/webm',
      });
      if (!blob.size) {
        microphoneDebug('voice', 'recorder_empty_turn');
        setLastError('no_audio_recorded');
        setState(isHandsFreeRef.current ? 'IDLE' : 'OFF');
        return;
      }

      // Transcription is a round trip, so the turn is genuinely THINKING here
      // rather than still listening. Saying so is what keeps the UI honest.
      setState('THINKING');
      void transcribeBlob(blob, 'voice')
        .then((result) => {
          setInterimText('');
          if (result.text) {
            microphoneDebug('voice', 'stt_result', {
              characters: result.text.length,
              engine: 'homepilot-backend',
              provider: result.provider,
            });
            setLastError(null);
            onSendTextRef.current(result.text);
            // `onSendText` drives the reply; SPEAKING follows from TTS.
            return;
          }
          // Empty text is a successful transcription of silence, and a
          // different fact from a failure. Report it as such.
          microphoneDebug('voice', 'stt_no_speech', { provider: result.provider });
          setLastError('no_speech_detected');
          setState(isHandsFreeRef.current ? 'IDLE' : 'OFF');
        })
        .catch((error) => {
          microphoneDebugError('voice', 'stt_transcribe_failed', error);
          if (error instanceof SttUnavailableError) {
            // The server cannot transcribe — no provider, or one that failed to load. Drop
            // to the browser recognizer rather than leaving hands-free voice deaf for the
            // rest of the session, and say so: it records the OS default input instead of
            // the selected microphone, which is worse but is not nothing.
            applySttSessionOverride(
              'web-speech',
              'HomePilot could not transcribe on this computer, so this session has moved to '
              + 'the browser’s speech recognition. It records your system default input, not '
              + 'the microphone selected in Audio & Video.',
              'voice',
            );
          }
          setLastError(error instanceof Error ? error.message : 'transcription_failed');
          setState(isHandsFreeRef.current ? 'IDLE' : 'OFF');
        });
    };

    try {
      recorder.start(250);
    } catch (error) {
      microphoneDebugError('voice', 'recorder_start_failed', error, { reason });
      recorderRef.current = null;
      setLastError('recorder_failed');
      return false;
    }

    microphoneDebug('voice', 'recorder_started', {
      reason,
      mimeType: recorder.mimeType || 'browser-selected',
      label: vadRef.current?.getDeviceLabel?.() || 'unlabelled microphone',
      engine: 'homepilot-backend',
    });
    setState('LISTENING');
    return true;
    // Deliberately no dependencies: everything render-scoped is read through a ref above, so
    // this stays identity-stable and the capture effect below does not restart on every render.
  }, []);

  /** End the turn and let `onstop` transcribe what was captured. */
  const finishRecordingTurn = useCallback((reason: string) => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    microphoneDebug('voice', 'recorder_stop_requested', { reason });
    try {
      if (recorder.state !== 'inactive') recorder.stop();
    } catch (error) {
      microphoneDebugError('voice', 'recorder_stop_failed', error, { reason });
    }
  }, []);

  /** Stop the observation-only meter used beside Web Speech. */
  const stopBrowserInputMeter = useCallback((reason: string) => {
    browserMeterGenerationRef.current += 1;
    browserMeterStartingRef.current = null;
    const meter = browserMeterRef.current;
    browserMeterRef.current = null;
    meter?.stop(reason);
    setMicMeterDeviceLabel(null);
    if (sttEngineRef.current === 'web-speech') {
      setAudioLevel(0);
      setNoiseFloor(0);
      setThreshold(0);
    }
  }, []);

  /**
   * Open a level-only stream on the browser/default input.
   *
   * This is intentionally independent of turn ownership. SpeechRecognition remains the only
   * component that decides what was said; these samples only animate the meter. Failure is
   * non-fatal — voice recognition continues and the UI falls back to its unavailable copy.
   */
  const ensureBrowserInputMeter = useCallback(async (reason: string): Promise<boolean> => {
    if (browserMeterRef.current) return true;
    if (browserMeterStartingRef.current !== null) return true;
    if (!browserInputMeterAvailable()) {
      setBrowserMeterSupported(false);
      return false;
    }

    const generation = ++browserMeterGenerationRef.current;
    browserMeterStartingRef.current = generation;
    microphoneDebug('voice', 'browser_input_meter_start_requested', { reason, generation });
    try {
      const meter = await startBrowserInputMeter((level) => {
        if (sttEngineRef.current !== 'web-speech') return;
        // Keep speaker output from painting itself as microphone activity while TTS is live.
        setAudioLevel(stateRef.current === 'SPEAKING' ? 0 : level);
      });
      if (
        generation !== browserMeterGenerationRef.current
        || sttEngineRef.current !== 'web-speech'
      ) {
        meter.stop('stale_start');
        return false;
      }
      browserMeterRef.current = meter;
      setBrowserMeterSupported(true);
      setMicMeterDeviceLabel(meter.deviceLabel);
      setNoiseFloor(0);
      setThreshold(0);
      return true;
    } catch (error) {
      if (generation === browserMeterGenerationRef.current) {
        setBrowserMeterSupported(false);
        setMicMeterDeviceLabel(null);
        setAudioLevel(0);
      }
      microphoneDebugError('voice', 'browser_input_meter_failed', error, { reason, generation });
      return false;
    } finally {
      if (browserMeterStartingRef.current === generation) {
        browserMeterStartingRef.current = null;
      }
    }
  }, []);

  /* ── The browser engine ───────────────────────────────────────────────────────────────
   *
   * No VAD here, deliberately. The recognizer opens its own capture and cannot be handed
   * one. The separate meter stream above is observation-only: it never gates or records a
   * turn, so the recognizer remains the single source of truth for browser STT. Hands-free is
   * therefore a restart loop around the recognizer's own endpointing, which is what decides
   * when a turn is over on this engine.
   * ─────────────────────────────────────────────────────────────────────────────────── */

  const startBrowserTurnRef = useRef<(reason: string) => Promise<boolean>>(
    async () => false,
  );

  const clearBrowserRestart = useCallback(() => {
    if (browserRestartTimerRef.current) {
      clearTimeout(browserRestartTimerRef.current);
      browserRestartTimerRef.current = null;
    }
  }, []);

  const scheduleBrowserRestart = useCallback((delayMs: number) => {
    if (!isHandsFreeRef.current || sttEngineRef.current !== 'web-speech') return;
    if (browserRestartTimerRef.current) return;
    browserRestartTimerRef.current = setTimeout(() => {
      browserRestartTimerRef.current = null;
      if (!isHandsFreeRef.current || sttEngineRef.current !== 'web-speech') return;
      // Somebody else is using the microphone — the chat composer, or the Settings
      // speech-to-text test. There is one recognizer on the page, so restarting here would
      // abort theirs mid-turn: the Settings test failed with a bare `aborted` for exactly
      // this reason, because this loop woke up 400 ms after the test pressed start.
      //
      // Wait rather than give up. Hands-free is supposed to still be listening when they are
      // done, and polling the lease is what lets it resume without the capture effect
      // re-running.
      const holder = getMicrophoneLease();
      if (holder && holder.owner !== 'voice') {
        microphoneDebug('voice', 'handsfree_browser_yielded', {
          to: holder.owner,
          engine: holder.engine,
        });
        scheduleBrowserRestart(BROWSER_YIELD_POLL_MS);
        return;
      }
      // A turn lock, the assistant still talking, or the guard right after it: all mean
      // "not yet", never "give up". Re-arm rather than dropping the loop on the floor.
      if (listeningSuppressedRef.current || stateRef.current === 'SPEAKING') {
        scheduleBrowserRestart(BROWSER_RESTART_MS);
        return;
      }
      const guardMs = postTtsMicGuardUntilRef.current - Date.now();
      if (guardMs > 0) {
        scheduleBrowserRestart(guardMs);
        return;
      }
      void startBrowserTurnRef.current('handsfree_restart');
    }, Math.max(0, delayMs));
    // `scheduleBrowserRestart` recurses through its own identity, which empty deps keep
    // stable; everything else is read from a ref for the same reason as the turn handlers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startBrowserTurn = useCallback(async (reason: string): Promise<boolean> => {
    clearBrowserRestart();
    // Only a press carries the assertion "I just said something", which is what makes an
    // empty turn evidence of a fault rather than of a pause.
    turnWasDeliberateRef.current = reason === 'manual_button';
    microphoneDebug('voice', 'stt_start_requested', {
      reason,
      state: stateRef.current,
      handsFree: isHandsFreeRef.current,
      deliberate: turnWasDeliberateRef.current,
      recognitionDevice: 'browser-managed-web-speech',
    });

    browserTurnStartedAtRef.current = Date.now();
    /*
     * Hands-free listens continuously; a manual press is one turn.
     *
     * A one-shot session ends at the first pause, so hands-free became a series of short
     * recognitions with a restart between each — and the live caption died at exactly the
     * moment somebody was mid-sentence. It also meant Chrome raised `no-speech` every few
     * seconds of a quiet room. One long session streams interim words the whole time and
     * hands back each finished phrase as it completes, which is what reads like a caption.
     */
    const continuous = isHandsFreeRef.current;
    const started = await startWebSpeech('voice', {
      onStart: () => {
        microphoneDebug('voice', 'stt_onstart', {
          handsFree: isHandsFreeRef.current,
          recognitionDevice: 'browser-managed-web-speech',
        });
        browserFailuresRef.current = 0;
        setLastError(null);
        pendingResultRef.current = false;
        setState('LISTENING');
      },
      // The live transcript. This is the browser engine's one real advantage over
      // transcribing on this computer, and it is what makes a turn visibly working rather
      // than a silence the user has to guess about.
      // The live caption. Suppressed while the assistant is talking: anything arriving then
      // is either its own voice or a barge-in the recognizer cannot separate from it.
      onInterim: (text: string) => {
        if (stateRef.current === 'SPEAKING') return;
        setInterimText(text);
        if (stateRef.current === 'IDLE') setState('LISTENING');
      },
      onResult: (finalText: string) => {
        setInterimText('');
        const trimmed = finalText?.trim();
        if (!trimmed) return;
        // Do not put recognized speech in diagnostics. Length is enough to prove a result.
        microphoneDebug('voice', 'stt_result', {
          characters: trimmed.length,
          engine: 'web-speech',
        });
        pendingResultRef.current = true;
        deafTurnsRef.current = 0;
        onSendTextRef.current(trimmed);
        if (isHandsFreeRef.current) setState('THINKING');
      },
      onEnd: (diagnostics) => {
        const elapsedMs = Date.now() - browserTurnStartedAtRef.current;
        microphoneDebug('voice', 'stt_onend', {
          hadResult: pendingResultRef.current,
          state: stateRef.current,
          handsFree: isHandsFreeRef.current,
          sawAudioStart: diagnostics.sawAudioStart ?? null,
          sawSpeechStart: diagnostics.sawSpeechStart ?? null,
          sawInterim: diagnostics.sawInterim ?? null,
          sawNoMatch: diagnostics.sawNoMatch ?? null,
          stoppedBy: diagnostics.stoppedBy ?? null,
          elapsedMs: diagnostics.elapsedMs ?? elapsedMs,
          lang: diagnostics.lang ?? null,
        });
        lastSttEndRef.current = Date.now();
        setInterimText('');

        // The turn that produced nothing is the one worth reading: the capture opened,
        // stayed open and heard not one syllable. Nothing in the Web Speech API reports
        // that, because from the recognizer's point of view it recorded a silent room.
        //
        // But only a turn somebody deliberately started is evidence of a *fault*. A
        // hands-free browser turn is opened by the restart loop whether or not anybody is
        // talking, and no VAD runs on this engine to say that somebody was — so "the
        // recognizer heard nothing" there is the ordinary sound of a quiet room, and
        // counting it would switch engines under a user who simply stopped speaking for
        // eight hundred milliseconds.
        //
        // And the *first* turn of a session is never evidence either, however deliberate it
        // was: opening Voice and pressing listen is how people check that Voice is there, and
        // they often say nothing into it. See `turnsThisSessionRef`.
        const deliberate = turnWasDeliberateRef.current;
        const warmUp = turnsThisSessionRef.current === 0;
        turnsThisSessionRef.current += 1;
        const deaf = deliberate && !warmUp && isDeafTurn({
          hadResult: pendingResultRef.current,
          sawAudioStart: diagnostics.sawAudioStart,
          sawSpeechStart: diagnostics.sawSpeechStart,
          sawInterim: diagnostics.sawInterim,
          error: diagnostics.error,
        });
        if (warmUp && deliberate) {
          microphoneDebug('voice', 'stt_first_turn_not_evidence', {
            hadResult: pendingResultRef.current,
            sawSpeechStart: diagnostics.sawSpeechStart ?? null,
          });
        }
        deafTurnsRef.current = deaf ? deafTurnsRef.current + 1 : 0;
        if (deaf) {
          const recovery = planSttRecovery(deafTurnsRef.current, {
            backendUsable: backendUsableRef.current,
            turnWasDeliberate: true,
            /*
             * True whenever HomePilot itself has a capture open — which, since the input
             * meter arrived, includes browser turns.
             *
             * That comment used to say this was "always false during a browser turn". It
             * stopped being true the moment the meter started opening the default input, and
             * the distinction is the whole reason the field exists: some drivers (Windows
             * DSP-backed inputs among them) hand a *second* recorder on the same endpoint a
             * live but silent track. The meter and the recognizer now want the same device,
             * so contention is a real second explanation for a deaf turn, with an identical
             * trace and a different fix. Asserting the routing split as the sole cause would
             * send the user to rearrange their operating system for nothing.
             */
            homepilotHoldsMicrophone:
              Boolean(browserMeterRef.current)
              || getMicrophoneLease()?.engine === 'homepilot-backend',
            // The device the recognizer was actually recording. The routing preflight has been
            // reading the device list all along; this stops discarding the one label that
            // makes "change your system default input" an instruction rather than a topic.
            systemDefaultLabel: systemDefaultMicrophoneLabel(),
          });
          if (recovery.action !== 'none') {
            microphoneDebug('voice', 'stt_deaf_recognizer_recovery', {
              action: recovery.action,
              deafTurns: deafTurnsRef.current,
              backendUsable: backendUsableRef.current,
              // Which of the two explanations the advice was written for.
              meterHeldMicrophone: Boolean(browserMeterRef.current),
            });
            // Counted from zero either way: after a switch the next run of deaf turns is
            // about the new engine, and after advice the user needs room to act on it
            // before being told again.
            deafTurnsRef.current = 0;
            setSttNotice(recovery.message);
            if (recovery.action === 'switch-to-backend') {
              // Remembered across reloads, keyed by this microphone, so the next session
              // starts on the working engine instead of re-proving this.
              rememberRecognizerIsDeaf();
              // Shared, so the chat composer moves with it. The capture effect sees the new
              // engine and hands the microphone over; nothing restarts the recognizer.
              applySttSessionOverride('homepilot-backend', recovery.message, 'voice');
              pendingResultRef.current = false;
              setState(isHandsFreeRef.current ? 'IDLE' : 'OFF');
              return;
            }
          }
        }

        if (stateRef.current === 'LISTENING') {
          setState(isHandsFreeRef.current
            ? (pendingResultRef.current ? 'THINKING' : 'IDLE')
            : 'OFF');
        }
        pendingResultRef.current = false;

        // A manual Web Speech turn has no ongoing hands-free session to keep visualising.
        if (!isHandsFreeRef.current) stopBrowserInputMeter('manual_turn_end');

        // A session that ends the instant it starts never listened to anything. Backing off
        // keeps a refusal from turning the hands-free loop into a hot `start()` loop.
        if (elapsedMs < BROWSER_MIN_HEALTHY_TURN_MS) browserFailuresRef.current += 1;
        else browserFailuresRef.current = 0;

        if (browserFailuresRef.current >= BROWSER_MAX_CONSECUTIVE_FAILURES) {
          microphoneDebug('voice', 'handsfree_browser_loop_stopped', {
            failures: browserFailuresRef.current,
          });
          setLastError('stt_start_failed');
          setState('OFF');
          return;
        }
        scheduleBrowserRestart(
          BROWSER_RESTART_MS * (browserFailuresRef.current ? 2 ** browserFailuresRef.current : 1),
        );
      },
      onError: (code: string) => {
        microphoneDebug('voice', 'stt_error', {
          error: code || 'stt_error',
          benign: BENIGN_RECOGNITION_ERRORS.has(code),
          state: stateRef.current,
          handsFree: isHandsFreeRef.current,
        });
        if (BENIGN_RECOGNITION_ERRORS.has(code)) {
          // Silence, or our own hand-off. `onEnd` follows and restarts the loop; saying
          // anything here would be an error message about nothing having gone wrong.
          setInterimText('');
          return;
        }
        setLastError(code || 'stt_error');
        pendingResultRef.current = false;
        setInterimText('');
        if (FATAL_RECOGNITION_ERRORS.has(code)) {
          // Permission, a missing device, a blocked service: restarting repeats the error
          // forever and buries the one message that would let the user fix it.
          clearBrowserRestart();
          browserFailuresRef.current = BROWSER_MAX_CONSECUTIVE_FAILURES;
          if (!isHandsFreeRef.current) stopBrowserInputMeter('manual_turn_error');
          setState('OFF');
          return;
        }
        if (!isHandsFreeRef.current) stopBrowserInputMeter('manual_turn_error');
        setState(isHandsFreeRef.current ? 'IDLE' : 'OFF');
      },
    }, { continuous });

    if (!started) {
      microphoneDebug('voice', 'stt_start_rejected', { reason });
      if (!isHandsFreeRef.current) stopBrowserInputMeter('manual_start_rejected');
      setState(isHandsFreeRef.current ? 'IDLE' : 'OFF');
    }
    return started;
  }, [clearBrowserRestart, scheduleBrowserRestart, stopBrowserInputMeter]);

  // Declared before the capture effect so the loop can recurse through this ref by the time
  // the first restart timer fires.
  useEffect(() => {
    startBrowserTurnRef.current = startBrowserTurn;
  }, [startBrowserTurn]);

  /**
   * Everything this surface might be holding, dropped. Idempotent, because it is called by
   * the effect's own cleanup, by a hand-off to another surface, and by an engine change.
   */
  const releaseVoiceCapture = useCallback((reason: string) => {
    clearBrowserRestart();
    abortWebSpeech(reason);
    stopBrowserInputMeter(reason);
    // Drop the recorder before the stream it is attached to goes away; transcribing a
    // half-turn nobody is waiting for wastes a round trip.
    discardRecording(reason);
    if (vadRef.current) {
      vadRef.current.stop();
      vadRef.current = null;
    }
    setAudioLevel(0);
    setInterimText('');
  }, [clearBrowserRestart, discardRecording, stopBrowserInputMeter]);

  useEffect(() => {
    if (!svc) return;

    let lastTTSState = false;

    const checkTTSState = () => {
      const isSpeaking = svc.isSpeaking || false;

      if (isSpeaking !== lastTTSState) {
        lastTTSState = isSpeaking;

        if (isSpeaking) {
          console.log('[VoiceController] TTS started - state: SPEAKING');
          setState('SPEAKING');

          if (vadRef.current?.isRunning() && !vadRef.current.isPaused()) {
            vadRef.current.pause();
            setAudioLevel(0);
            console.log('[VoiceController] VAD paused during TTS');
          }

          if (sttEngineRef.current === 'web-speech') {
            // The recognizer has its own capture and no way to tell HomePilot's voice from
            // the user's, so leaving it open feeds the assistant's own words back in as the
            // next turn. Stop, and resume when it has finished speaking. The meter stays open
            // but its callback paints zero while SPEAKING, so speaker leakage is not visualised
            // as user input.
            setAudioLevel(0);
            clearBrowserRestart();
            abortWebSpeech('tts_started');
          }

          if (ttsEndTimeoutRef.current) {
            clearTimeout(ttsEndTimeoutRef.current);
            ttsEndTimeoutRef.current = null;
          }
        } else {
          console.log('[VoiceController] TTS ended - waiting before state transition');
          ttsEndTimeoutRef.current = setTimeout(() => {
            postTtsMicGuardUntilRef.current = Date.now() + (cfg.postTtsMicGuardMs ?? 0);

            if (vadRef.current?.isRunning() && vadRef.current.isPaused()) {
              vadRef.current.resume();
              setAudioLevel(0);
              console.log('[VoiceController] VAD resumed after TTS');
            }

            if (stateRef.current === 'SPEAKING') {
              const nextState = isHandsFreeRef.current ? 'IDLE' : 'OFF';
              setState(nextState);
              console.log(`[VoiceController] Transitioned to ${nextState} after TTS`);
            }
            if (sttEngineRef.current === 'web-speech' && isHandsFreeRef.current) {
              scheduleBrowserRestart(cfg.postTtsMicGuardMs ?? 0);
            }
            ttsEndTimeoutRef.current = null;
          }, cfg.ttsEndDelay);
        }
      }
    };

    const interval = setInterval(checkTTSState, 50);

    return () => {
      clearInterval(interval);
      if (ttsEndTimeoutRef.current) {
        clearTimeout(ttsEndTimeoutRef.current);
        ttsEndTimeoutRef.current = null;
      }
    };
  }, [
    svc,
    cfg.ttsEndDelay,
    cfg.postTtsMicGuardMs,
    clearBrowserRestart,
    scheduleBrowserRestart,
  ]);

  /**
   * Open exactly one capture, chosen by the engine.
   *
   * On Web Speech a tiny read-only meter stream may coexist with the recognizer, but it has no
   * VAD/MediaRecorder callbacks and therefore cannot own a turn. Re-running this effect *is*
   * the engine transition: React tears the previous run down before starting the next.
   */
  useEffect(() => {
    const generation = ++handsFreeGenerationRef.current;

    if (!isHandsFree) {
      releaseVoiceCapture('handsfree_off');
      void releaseMicrophone('voice');
      setState('OFF');
      return;
    }

    // Nothing may open a capture before the engine is known. A "temporary" default here is
    // what sent the first sentence of a session through an engine the user did not pick.
    if (!sttEngine) {
      microphoneDebug('voice', 'handsfree_waiting_for_engine', { generation });
      return;
    }

    if (!sttSupported) {
      microphoneDebug('voice', 'handsfree_unavailable_no_stt', {
        engine: sttEngine,
        webSpeechSupported,
        mediaRecorderSupported,
      });
      setLastError('stt_not_supported');
      setState('OFF');
      return;
    }

    void acquireMicrophone('voice', sttEngine, () => releaseVoiceCapture('microphone_handoff'));

    if (sttEngine === 'web-speech') {
      microphoneDebug('voice', 'handsfree_browser_start_requested', { generation });
      browserFailuresRef.current = 0;
      setLastError(null);
      setState('IDLE');
      // Ask for the visual monitor first so the same permission gesture can cover both. A
      // meter failure never blocks recognition; the `finally` always starts the recognizer.
      void ensureBrowserInputMeter('handsfree_browser').finally(() => {
        if (
          generation === handsFreeGenerationRef.current
          && isHandsFreeRef.current
          && sttEngineRef.current === 'web-speech'
        ) {
          scheduleBrowserRestart(0);
        }
      });
      return () => {
        microphoneDebug('voice', 'handsfree_browser_cleanup', { generation });
        releaseVoiceCapture('handsfree_browser_cleanup');
      };
    }

    const vad = createVAD(
      () => {
        if (!isHandsFreeRef.current || generation !== handsFreeGenerationRef.current) return;
        const currentState = stateRef.current;
        microphoneDebug('voice', 'vad_speech_start', {
          state: currentState,
          suppressed: listeningSuppressedRef.current,
        });

        if (listeningSuppressedRef.current) {
          microphoneDebug('voice', 'vad_speech_start_ignored_turn_lock');
          return;
        }

        if (Date.now() < postTtsMicGuardUntilRef.current) {
          microphoneDebug('voice', 'vad_speech_start_ignored_post_tts_guard');
          return;
        }

        if (currentState === 'SPEAKING' && cfg.bargeInEnabled) {
          microphoneDebug('voice', 'barge_in_stop_tts');
          svc?.stopSpeaking?.();
        }

        // Backend transcription records the VAD's own stream, so there is no
        // recognizer to warm up and no cooldown to respect.
        if (currentState === 'IDLE' || currentState === 'SPEAKING') {
          void startRecordingTurn('vad_speech_start');
        }
      },
      () => {
        if (!isHandsFreeRef.current || generation !== handsFreeGenerationRef.current) return;
        microphoneDebug('voice', 'vad_speech_end', {
          state: stateRef.current,
          suppressed: listeningSuppressedRef.current,
        });

        if (listeningSuppressedRef.current) return;

        // A short trailing pad keeps the last word out of the cut, which the
        // recognizer-based path got from Chrome's own endpointer.
        setTimeout(() => {
          if (stateRef.current === 'LISTENING') finishRecordingTurn('vad_silence');
        }, 250);
      },
      cfg.vadConfig
    );
    vadRef.current = vad;

    microphoneDebug('voice', 'handsfree_vad_start_requested', { generation });
    vad.start()
      .then(() => {
        if (!isHandsFreeRef.current || generation !== handsFreeGenerationRef.current) {
          vad.stop();
          return;
        }
        microphoneDebug('voice', 'handsfree_vad_ready', { generation });
        setLastError(null);
        setState('IDLE');
      })
      .catch((err) => {
        if (generation !== handsFreeGenerationRef.current) return;
        microphoneDebugError('voice', 'handsfree_vad_failed', err, { generation });
        setLastError(err?.message || 'vad_start_failed');
        setState('OFF');
      });

    return () => {
      microphoneDebug('voice', 'handsfree_vad_cleanup', { generation });
      releaseVoiceCapture('handsfree_vad_cleanup');
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    isHandsFree,
    sttEngine,
    svc,
    sttSupported,
    JSON.stringify(cfg.vadConfig),
    cfg.bargeInEnabled,
    // Listed because the callbacks close over them, and safe to list because all of them are
    // identity-stable: they read the caller's handler through a ref. An unstable one here
    // restarts the capture on every render, and since the restart sets state, that is an
    // endless teardown/reopen loop rather than a slow one.
    startRecordingTurn,
    finishRecordingTurn,
    releaseVoiceCapture,
    ensureBrowserInputMeter,
    scheduleBrowserRestart,
  ]);

  /** Give the microphone back when Voice unmounts, whatever it was holding. */
  useEffect(() => () => {
    releaseVoiceCapture('voice_unmount');
    void releaseMicrophone('voice');
  }, [releaseVoiceCapture]);

  useEffect(() => {
    if (!vadRef.current || !isHandsFree) return;

    const updateLevels = () => {
      if (vadRef.current) {
        setAudioLevel(vadRef.current.getCurrentLevel());
        setNoiseFloor(vadRef.current.getNoiseFloor());
        setThreshold(vadRef.current.getThreshold());
      }
    };

    const interval = setInterval(updateLevels, 100);
    return () => clearInterval(interval);
  }, [isHandsFree, sttEngine]);

  const clearError = useCallback(() => {
    setLastError(null);
  }, []);

  const startManualListening = useCallback(async (): Promise<boolean> => {
    microphoneDebug('voice', 'manual_listen_button', {
      state: stateRef.current,
      handsFree: isHandsFree,
      engine: sttEngine,
      sttSupported,
    });

    if (!sttEngine) {
      // The probe is still in flight. Saying so beats opening the wrong engine's capture and
      // hoping, which is what the old "assume the browser until it answers" did.
      microphoneDebug('voice', 'manual_listen_engine_pending');
      setLastError('stt_engine_pending');
      return false;
    }

    if (!sttSupported) {
      microphoneDebug('voice', 'manual_listen_not_supported');
      setLastError('stt_not_supported');
      setState('OFF');
      return false;
    }

    svc?.stopSpeaking?.();

    await acquireMicrophone('voice', sttEngine, () =>
      releaseVoiceCapture('microphone_handoff'));

    if (sttEngine === 'homepilot-backend') return startRecordingTurn('manual_button');
    // Manual browser turns get the same Grok-style live input meter; failure to open the
    // monitor never blocks the recognizer itself.
    await ensureBrowserInputMeter('manual_browser');
    return startBrowserTurn('manual_button');
  }, [
    svc,
    sttEngine,
    sttSupported,
    isHandsFree,
    startBrowserTurn,
    startRecordingTurn,
    releaseVoiceCapture,
    ensureBrowserInputMeter,
  ]);

  const stopManualListening = useCallback(() => {
    microphoneDebug('voice', 'manual_stop_button', { state: stateRef.current });
    // An explicit Stop means "transcribe what I said", not "throw it away" — the user
    // finished their sentence.
    if (recorderRef.current) {
      finishRecordingTurn('manual_button');
      return;
    }
    // An explicit press of Stop must stop now, not after the warm-up guard.
    stopWebSpeech('voice', { reason: 'manual_button', force: true });
  }, [finishRecordingTurn]);

  const stopSpeaking = useCallback(() => {
    svc?.stopSpeaking?.();
    if (vadRef.current?.isRunning() && vadRef.current.isPaused()) {
      vadRef.current.resume();
    }
    setState(isHandsFree ? 'IDLE' : 'OFF');
  }, [svc, isHandsFree]);

  const setHandsFree = useCallback((enabled: boolean) => {
    microphoneDebug('voice', 'handsfree_changed', { enabled, state: stateRef.current });
    setIsHandsFree(enabled);
    localStorage.setItem('homepilot_voice_handsfree', String(enabled));
    if (!enabled) setState('OFF');
  }, []);

  const setTtsEnabled = useCallback((enabled: boolean) => {
    setIsTtsEnabled(enabled);
  }, []);

  const dismissSttNotice = useCallback(() => setSttNotice(null), []);

  const setListeningSuppressed = useCallback(
    (suppressed: boolean, reason: string = 'unspecified') => {
      listeningSuppressedRef.current = suppressed;
      console.log(
        `[VoiceController] Listening suppression ${suppressed ? 'enabled' : 'disabled'} (reason=${reason})`,
      );
      if (suppressed && stateRef.current === 'LISTENING') {
        // A turn lock releases the microphone immediately; waiting on a
        // transcript here would let the locked turn keep recording.
        discardRecording('turn_lock');
        clearBrowserRestart();
        abortWebSpeech('turn_lock');
        setState(isHandsFree ? 'IDLE' : 'OFF');
      }
      if (!suppressed && isHandsFreeRef.current && sttEngineRef.current === 'web-speech') {
        scheduleBrowserRestart(BROWSER_RESTART_MS);
      }
    },
    [isHandsFree, discardRecording, clearBrowserRestart, scheduleBrowserRestart],
  );

  return {
    state,
    isHandsFree,
    isTtsEnabled,
    interimText,
    audioLevel,
    noiseFloor,
    threshold,
    sttSupported,
    lastError,
    clearError,
    sttEngine,
    sttReady: runtime.status === 'ready',
    sttProvider,
    sttResolution,
    sttNotice,
    dismissSttNotice,
    micMeterSupported: sttEngine === 'homepilot-backend'
      || (sttEngine === 'web-speech' && browserMeterSupported),
    micMeterDeviceLabel: sttEngine === 'web-speech' ? micMeterDeviceLabel : null,
    liveTranscriptSupported: sttEngine === 'web-speech',
    bargeInSupported: sttEngine === 'homepilot-backend' && Boolean(cfg.bargeInEnabled),
    setHandsFree,
    setTtsEnabled,
    startManualListening,
    stopManualListening,
    stopSpeaking,
    setListeningSuppressed,
    voices,
    selectedVoice,
    setSelectedVoice,
  };
}
