/**
 * Unified Voice Controller Hook
 *
 * Industry-standard state machine for voice interaction:
 * - OFF: Voice features disabled
 * - IDLE: Waiting for speech (VAD running)
 * - LISTENING: User is speaking (STT active)
 * - THINKING: Processing user input (waiting for LLM)
 * - SPEAKING: TTS playing response
 *
 * Key features:
 * - VAD never stops during TTS (true barge-in)
 * - Event-driven TTS monitoring
 * - Proper state transitions
 * - Browser AEC/NS/AGC enabled
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { createVAD, VADInstance, VADConfig } from './vad';
import { microphoneDebug, microphoneDebugError } from '../media/microphoneDebug';
import { getSttCapability, transcribeBlob, type SttEngine } from '../media/sttService';

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
   * Which transcription path this session resolved to.
   *
   * `homepilot-backend` records the microphone selected in Audio & Video and
   * transcribes it server-side. `web-speech` is the fallback for servers with
   * no speech provider configured, and carries the browser's device caveat:
   * it records the OS default input regardless of that selection.
   */
  sttEngine: SttEngine;
  /** Name of the server-side provider when one is in use. */
  sttProvider: string | null;

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

  const webSpeechSupported =
    typeof window !== 'undefined' &&
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (!!(window as any).SpeechRecognition || !!(window as any).webkitSpeechRecognition);

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

  // Backend transcription is preferred and resolved once per session. Until the
  // capability answers, the Web Speech fallback stands in, so voice is never
  // dead while the probe is in flight.
  const [sttEngine, setSttEngine] = useState<SttEngine>('web-speech');
  const [sttProvider, setSttProvider] = useState<string | null>(null);
  const sttEngineRef = useRef<SttEngine>('web-speech');

  /**
   * Whether *some* path can transcribe.
   *
   * Deliberately not "does this browser implement the Web Speech API": with
   * backend transcription the browser only has to be able to record, so gating
   * voice on Web Speech would refuse a perfectly working setup (Firefox, or a
   * Chromium build without the recognizer).
   */
  const sttSupported =
    (sttEngine === 'homepilot-backend' && mediaRecorderSupported) || webSpeechSupported;

  const vadRef = useRef<VADInstance | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recorderChunksRef = useRef<Blob[]>([]);
  const recorderDiscardRef = useRef(false);
  const stateRef = useRef<VoiceState>(state);
  const ttsEndTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const thinkingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingResultRef = useRef<boolean>(false);
  const lastSttEndRef = useRef<number>(0);
  const postTtsMicGuardUntilRef = useRef<number>(0);
  const handsFreeGenerationRef = useRef<number>(0);
  const listeningSuppressedRef = useRef<boolean>(false);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    sttEngineRef.current = sttEngine;
  }, [sttEngine]);

  // Resolve the transcription path once. Preferring the backend removes the
  // device split at its root: the clip posted for transcription is recorded
  // from the VAD's own stream, which is the selected microphone.
  useEffect(() => {
    let cancelled = false;
    void getSttCapability().then((capability) => {
      if (cancelled) return;
      const engine: SttEngine = capability.available ? 'homepilot-backend' : 'web-speech';
      setSttEngine(engine);
      setSttProvider(capability.provider);
      microphoneDebug('voice', 'stt_engine_resolved', {
        engine,
        provider: capability.provider,
        remote: capability.remote,
        // The caveat only applies to the fallback, and saying which is in force
        // is the difference between a working mic and a silent one.
        usesOsDefaultInput: engine === 'web-speech',
      });
    });
    return () => { cancelled = true; };
  }, []);

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
              const nextState = isHandsFree ? 'IDLE' : 'OFF';
              setState(nextState);
              console.log(`[VoiceController] Transitioned to ${nextState} after TTS`);
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
  }, [svc, isHandsFree, cfg.ttsEndDelay, cfg.postTtsMicGuardMs]);

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
   * Record this turn from the VAD's own capture, so detection and
   * transcription cannot disagree about the device.
   */
  const startRecordingTurn = useCallback((reason: string): boolean => {
    if (recorderRef.current) {
      microphoneDebug('voice', 'recorder_start_skipped_active', { reason });
      return true;
    }
    if (typeof MediaRecorder === 'undefined') {
      microphoneDebug('voice', 'recorder_unavailable_mediarecorder', { reason });
      setLastError('mediarecorder_unavailable');
      return false;
    }

    const stream = vadRef.current?.getStream?.() || null;
    if (!stream) {
      microphoneDebug('voice', 'recorder_start_no_stream', { reason });
      setLastError('microphone_not_open');
      return false;
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

    recorder.onerror = (event) => {
      const error = (event as Event & { error?: DOMException }).error;
      microphoneDebugError('voice', 'recorder_error', error || new Error('recorder_failed'));
      recorderRef.current = null;
      recorderChunksRef.current = [];
      setLastError('recorder_failed');
      setState(isHandsFree ? 'IDLE' : 'OFF');
    };

    recorder.onstop = () => {
      const chunks = recorderChunksRef.current;
      const discarded = recorderDiscardRef.current;
      recorderChunksRef.current = [];
      recorderRef.current = null;
      recorderDiscardRef.current = false;

      if (discarded) return;

      const blob = new Blob(chunks, {
        type: recorder.mimeType || chunks[0]?.type || 'audio/webm',
      });
      if (!blob.size) {
        microphoneDebug('voice', 'recorder_empty_turn');
        setLastError('no_audio_recorded');
        setState(isHandsFree ? 'IDLE' : 'OFF');
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
            onSendText(result.text);
            // `onSendText` drives the reply; SPEAKING follows from TTS.
            return;
          }
          // Empty text is a successful transcription of silence, and a
          // different fact from a failure. Report it as such.
          microphoneDebug('voice', 'stt_no_speech', { provider: result.provider });
          setLastError('no_speech_detected');
          setState(isHandsFree ? 'IDLE' : 'OFF');
        })
        .catch((error) => {
          microphoneDebugError('voice', 'stt_transcribe_failed', error);
          setLastError(error instanceof Error ? error.message : 'transcription_failed');
          setState(isHandsFree ? 'IDLE' : 'OFF');
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
  }, [isHandsFree, onSendText]);

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

  /**
   * Start browser SpeechRecognition and await its actual boolean result.
   *
   * Web Speech does not expose a deviceId constraint. The selected microphone is used by
   * HomePilot's VAD stream, while recognition itself is browser-managed. Logging that fact is
   * critical when the VAD meter moves but recognition is listening to a different OS default.
   */
  const startRecognition = useCallback(async (reason: string): Promise<boolean> => {
    if (!svc?.startSTT) {
      microphoneDebug('voice', 'stt_start_unavailable', { reason, state: stateRef.current });
      setLastError('stt_start_unavailable');
      setState(isHandsFree ? 'IDLE' : 'OFF');
      return false;
    }

    microphoneDebug('voice', 'stt_start_requested', {
      reason,
      state: stateRef.current,
      handsFree: isHandsFree,
      alreadyRecognizing: Boolean(svc.isRecognizing),
      recognitionDevice: 'browser-managed-web-speech',
    });

    try {
      const started = await Promise.resolve(svc.startSTT({}));
      const recognizing = Boolean(svc.isRecognizing);
      if (started || recognizing) {
        microphoneDebug('voice', started ? 'stt_start_accepted' : 'stt_already_active', {
          reason,
          started: Boolean(started),
          recognizing,
        });
        setLastError(null);
        return true;
      }

      microphoneDebug('voice', 'stt_start_rejected', {
        reason,
        started: Boolean(started),
        recognizing,
      });
      setLastError('stt_start_failed');
      setState(isHandsFree ? 'IDLE' : 'OFF');
      return false;
    } catch (error) {
      microphoneDebugError('voice', 'stt_start_failed', error, { reason });
      const msg = error instanceof Error ? error.message : 'stt_start_failed';
      setLastError(msg);
      setState(isHandsFree ? 'IDLE' : 'OFF');
      return false;
    }
  }, [svc, isHandsFree]);

  useEffect(() => {
    if (!svc) return;

    svc.setRecognitionCallbacks({
      onStart: () => {
        microphoneDebug('voice', 'stt_onstart', {
          handsFree: isHandsFree,
          recognitionDevice: 'browser-managed-web-speech',
        });
        setLastError(null);
        pendingResultRef.current = false;
        setState('LISTENING');
      },
      onEnd: () => {
        // The SpeechService diagnostics distinguish "never captured audio" from
        // "captured silence" from "heard speech but produced no transcript".
        // Without them a bare `hadResult: false` cannot be acted on.
        const diagnostics = svc.getSttDiagnostics?.() || {};
        microphoneDebug('voice', 'stt_onend', {
          hadResult: pendingResultRef.current,
          state: stateRef.current,
          handsFree: isHandsFree,
          sawAudioStart: diagnostics.sawAudioStart ?? null,
          sawSpeechStart: diagnostics.sawSpeechStart ?? null,
          sawInterim: diagnostics.sawInterim ?? null,
          sawNoMatch: diagnostics.sawNoMatch ?? null,
          stoppedBy: diagnostics.stoppedBy ?? null,
          elapsedMs: diagnostics.elapsedMs ?? null,
          lang: diagnostics.lang ?? null,
        });
        lastSttEndRef.current = Date.now();
        if (stateRef.current === 'LISTENING') {
          if (isHandsFree) {
            const nextState = pendingResultRef.current ? 'THINKING' : 'IDLE';
            setState(nextState);
          } else {
            setState('OFF');
          }
        }
        pendingResultRef.current = false;
      },
      onInterim: (text: string) => {
        setInterimText(text);
      },
      onResult: (finalText: string) => {
        setInterimText('');
        if (finalText?.trim()) {
          // Do not put recognized speech in diagnostics. Length is enough to prove a result.
          microphoneDebug('voice', 'stt_result', { characters: finalText.trim().length });
          pendingResultRef.current = true;
          onSendText(finalText.trim());
          if (isHandsFree) setState('THINKING');
        }
      },
      onError: (msg: string) => {
        microphoneDebug('voice', 'stt_error', {
          error: msg || 'stt_error',
          state: stateRef.current,
          handsFree: isHandsFree,
        });
        setLastError(msg || 'stt_error');
        pendingResultRef.current = false;
        setState(isHandsFree ? 'IDLE' : 'OFF');
      },
    });
  }, [svc, onSendText, isHandsFree]);

  useEffect(() => {
    const generation = ++handsFreeGenerationRef.current;

    if (!isHandsFree || !svc) {
      if (vadRef.current) {
        vadRef.current.stop();
        vadRef.current = null;
      }
      if (!isHandsFree) setState('OFF');
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

    const vad = createVAD(
      () => {
        if (!isHandsFree || generation !== handsFreeGenerationRef.current) return;
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
          svc.stopSpeaking?.();
        }

        // Backend transcription records the VAD's own stream, so there is no
        // recognizer to warm up and no cooldown to respect.
        if (sttEngineRef.current === 'homepilot-backend') {
          if (currentState === 'IDLE' || currentState === 'SPEAKING') {
            startRecordingTurn('vad_speech_start');
          }
          return;
        }

        const timeSinceLastEnd = Date.now() - lastSttEndRef.current;
        const cooldownMs = 300;
        if (timeSinceLastEnd < cooldownMs) {
          const waitMs = cooldownMs - timeSinceLastEnd;
          microphoneDebug('voice', 'stt_cooldown', { waitMs });
          setTimeout(() => {
            if (stateRef.current === 'IDLE') void startRecognition('vad_after_cooldown');
          }, waitMs);
          return;
        }

        if (currentState === 'IDLE' || currentState === 'SPEAKING') {
          void startRecognition('vad_speech_start');
        }
      },
      () => {
        if (!isHandsFree || generation !== handsFreeGenerationRef.current) return;
        const currentState = stateRef.current;
        microphoneDebug('voice', 'vad_speech_end', {
          state: currentState,
          suppressed: listeningSuppressedRef.current,
        });

        if (listeningSuppressedRef.current) return;

        if (sttEngineRef.current === 'homepilot-backend') {
          // A short trailing pad keeps the last word out of the cut, which the
          // recognizer-based path got from Chrome's own endpointer.
          setTimeout(() => {
            if (stateRef.current === 'LISTENING') finishRecordingTurn('vad_silence');
          }, 250);
          return;
        }

        if (currentState === 'LISTENING') {
          setTimeout(() => {
            if (stateRef.current === 'LISTENING') {
              try {
                microphoneDebug('voice', 'stt_stop_requested', { reason: 'vad_silence' });
                // Not forced: SpeechService defers a stop that would cut the
                // recognizer off during warm-up, which is what silently
                // produced empty turns for short utterances.
                svc.stopSTT?.({ reason: 'vad_silence' });
              } catch (error) {
                microphoneDebugError('voice', 'stt_stop_failed', error, { reason: 'vad_silence' });
                const msg = error instanceof Error ? error.message : 'stt_stop_failed';
                setLastError(msg);
              }
            }
          }, 400);
        }
      },
      cfg.vadConfig
    );
    vadRef.current = vad;

    microphoneDebug('voice', 'handsfree_vad_start_requested', { generation });
    vad.start()
      .then(() => {
        if (!isHandsFree || generation !== handsFreeGenerationRef.current) {
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
      if (vadRef.current) {
        microphoneDebug('voice', 'handsfree_vad_cleanup', { generation });
        // Drop the recorder before the stream it is attached to goes away;
        // transcribing a half-turn nobody is waiting for wastes a round trip.
        discardRecording('handsfree_cleanup');
        vadRef.current.stop();
        vadRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    isHandsFree,
    svc,
    sttSupported,
    JSON.stringify(cfg.vadConfig),
    cfg.bargeInEnabled,
    startRecognition,
    // The VAD callbacks close over these, so a stale copy would record a turn
    // and hand the transcript to a previous `onSendText`.
    startRecordingTurn,
    finishRecordingTurn,
    discardRecording,
  ]);

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
  }, [isHandsFree]);

  const clearError = useCallback(() => {
    setLastError(null);
  }, []);

  const startManualListening = useCallback(async (): Promise<boolean> => {
    microphoneDebug('voice', 'manual_listen_button', {
      state: stateRef.current,
      handsFree: isHandsFree,
      sttSupported,
    });
    if (!svc) {
      microphoneDebug('voice', 'manual_listen_no_speech_service');
      setLastError('speech_service_unavailable');
      return false;
    }

    if (!sttSupported) {
      microphoneDebug('voice', 'manual_listen_not_supported');
      setLastError('stt_not_supported');
      setState('OFF');
      return false;
    }

    svc.stopSpeaking?.();

    if (sttEngineRef.current === 'homepilot-backend') {
      return startRecordingTurn('manual_button');
    }
    return startRecognition('manual_button');
  }, [svc, sttSupported, isHandsFree, startRecognition, startRecordingTurn]);

  const stopManualListening = useCallback(() => {
    microphoneDebug('voice', 'manual_stop_button', {
      state: stateRef.current,
      recognizing: Boolean(svc?.isRecognizing),
    });
    // An explicit Stop on the backend path means "transcribe what I said", not
    // "throw it away" — the user finished their sentence.
    if (recorderRef.current) {
      finishRecordingTurn('manual_button');
      return;
    }
    if (!svc) return;
    try {
      // An explicit press of Stop must stop now, not after the warm-up guard.
      svc.stopSTT?.({ reason: 'manual_button', force: true });
    } catch (error) {
      microphoneDebugError('voice', 'manual_stop_failed', error);
      const msg = error instanceof Error ? error.message : 'stt_stop_failed';
      setLastError(msg);
    }
  }, [svc, finishRecordingTurn]);

  const stopSpeaking = useCallback(() => {
    if (!svc) return;
    svc.stopSpeaking?.();
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
        try { svc?.stopSTT?.({ reason: 'turn_lock', force: true }); } catch { /* no-op */ }
        setState(isHandsFree ? 'IDLE' : 'OFF');
      }
    },
    [svc, isHandsFree, discardRecording],
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
    sttProvider,
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
