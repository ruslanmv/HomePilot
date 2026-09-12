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

  const sttSupported =
    typeof window !== 'undefined' &&
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (!!(window as any).SpeechRecognition || !!(window as any).webkitSpeechRecognition);

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

  const vadRef = useRef<VADInstance | null>(null);
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
      microphoneDebug('voice', 'handsfree_unavailable_no_web_speech');
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
        vadRef.current.stop();
        vadRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isHandsFree, svc, sttSupported, JSON.stringify(cfg.vadConfig), cfg.bargeInEnabled, startRecognition]);

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
    return startRecognition('manual_button');
  }, [svc, sttSupported, isHandsFree, startRecognition]);

  const stopManualListening = useCallback(() => {
    microphoneDebug('voice', 'manual_stop_button', {
      state: stateRef.current,
      recognizing: Boolean(svc?.isRecognizing),
    });
    if (!svc) return;
    try {
      // An explicit press of Stop must stop now, not after the warm-up guard.
      svc.stopSTT?.({ reason: 'manual_button', force: true });
    } catch (error) {
      microphoneDebugError('voice', 'manual_stop_failed', error);
      const msg = error instanceof Error ? error.message : 'stt_stop_failed';
      setLastError(msg);
    }
  }, [svc]);

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
        try { svc?.stopSTT?.({ reason: 'turn_lock', force: true }); } catch { /* no-op */ }
        setState(isHandsFree ? 'IDLE' : 'OFF');
      }
    },
    [svc, isHandsFree],
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
