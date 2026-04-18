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

// Voice controller states
export type VoiceState = 'OFF' | 'IDLE' | 'LISTENING' | 'THINKING' | 'SPEAKING';

// Configuration options
export interface VoiceControllerConfig {
  vadConfig?: Partial<VADConfig>;
  ttsEndDelay?: number;        // Delay after TTS ends before resuming detection (ms)
  bargeInEnabled?: boolean;    // Allow interrupting TTS with speech
  /** Ignore mic-start events for this long after TTS ends. On phone
   *  speakers AEC can let an echo tail linger for a few hundred ms
   *  and that echo trips VAD → "user speech" → stale transcript.
   *  Default 650 ms is enough for laptop + most Bluetooth headsets. */
  postTtsMicGuardMs?: number;
}

// Controller interface
export interface VoiceController {
  // State
  state: VoiceState;
  isHandsFree: boolean;
  isTtsEnabled: boolean;
  interimText: string;
  audioLevel: number;
  noiseFloor: number;
  threshold: number;

  // STT Support & Diagnostics
  sttSupported: boolean;
  lastError: string | null;
  clearError: () => void;

  // Actions
  setHandsFree: (enabled: boolean) => void;
  setTtsEnabled: (enabled: boolean) => void;
  startManualListening: () => void;
  stopManualListening: () => void;
  stopSpeaking: () => void;
  /** Suppress VAD speech-start / speech-end dispatch while the call
   *  overlay's turn-lock says the AI has the floor. Leaves VAD
   *  running (no re-calibration cost) — just ignores events. The
   *  overlay wires this to ``turnLock === 'ai'``. Safe no-op when
   *  the overlay isn't mounted. */
  setListeningSuppressed: (suppressed: boolean, reason?: string) => void;

  // Voice selection
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

  // Detect STT support (Web Speech API)
  const sttSupported =
    typeof window !== 'undefined' &&
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (!!(window as any).SpeechRecognition || !!(window as any).webkitSpeechRecognition);

  // Core state
  const [state, setState] = useState<VoiceState>('OFF');
  const [isHandsFree, setIsHandsFree] = useState(() => {
    // Default to hands-free ON if no preference saved
    const saved = localStorage.getItem('homepilot_voice_handsfree');
    return saved === null || saved === 'true';
  });
  const [isTtsEnabled, setIsTtsEnabled] = useState(() => {
    return localStorage.getItem('homepilot_tts_enabled') !== 'false';
  });
  const [interimText, setInterimText] = useState('');

  // STT error tracking for diagnostics
  const [lastError, setLastError] = useState<string | null>(null);

  // Audio levels for visualization
  const [audioLevel, setAudioLevel] = useState(0);
  const [noiseFloor, setNoiseFloor] = useState(0);
  const [threshold, setThreshold] = useState(0);

  // Voice selection
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [selectedVoice, setSelectedVoiceState] = useState<string>(() => {
    return localStorage.getItem('homepilot_voice_uri') || '';
  });

  // Refs for stable callbacks
  const vadRef = useRef<VADInstance | null>(null);
  const stateRef = useRef<VoiceState>(state);
  const ttsEndTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const thinkingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingResultRef = useRef<boolean>(false); // Track if we sent a result to API
  const lastSttEndRef = useRef<number>(0); // Track last STT end time for cooldown
  // Timestamp (ms) below which VAD speech-start events are ignored.
  // Set by the TTS-end path so the echo tail can't self-trigger a
  // user-speech turn right after the AI finishes talking.
  const postTtsMicGuardUntilRef = useRef<number>(0);
  // Incremented each time the hands-free VAD effect re-runs. VAD's
  // ``.start()`` promise resolves asynchronously — if hands-free
  // was turned off while that promise was in flight, the then-
  // callback would otherwise set state='IDLE' on a stale generation
  // and leak a VAD instance. Callbacks check that the generation
  // they closed over still matches the current one before mutating.
  const handsFreeGenerationRef = useRef<number>(0);
  // Opt-in listening suppression (overlay's turn-lock wires this
  // to ``turnLock === 'ai'``). When true, VAD continues running
  // but speech-start / speech-end events short-circuit before any
  // state transition; a noisy environment or our own TTS bleed
  // can no longer drag the controller into LISTENING.
  const listeningSuppressedRef = useRef<boolean>(false);

  // Keep stateRef in sync
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  // THINKING state timeout — safety net for when the backend answers in
  // text-only (no TTS) and no SPEAKING transition ever fires. Previously
  // 30 s, which left the user unable to speak again for half a minute
  // after every text-only AI reply. 4 s matches human turn-taking: if
  // the AI hasn't started to speak within 4 s of receiving the user's
  // utterance we assume it is not going to, and return to IDLE so the
  // mic becomes available again. When TTS DOES start, the SPEAKING
  // transition below clears this timer, so it never interrupts real
  // speech playback — only the no-TTS corner case.
  useEffect(() => {
    if (state === 'THINKING' && isHandsFree) {
      thinkingTimeoutRef.current = setTimeout(() => {
        if (stateRef.current === 'THINKING') {
          console.warn('[VoiceController] THINKING timeout - returning to IDLE');
          setState('IDLE');
        }
      }, 4000);
    } else {
      // Clear timeout when leaving THINKING state
      if (thinkingTimeoutRef.current) {
        clearTimeout(thinkingTimeoutRef.current);
        thinkingTimeoutRef.current = null;
      }
    }

    return () => {
      if (thinkingTimeoutRef.current) {
        clearTimeout(thinkingTimeoutRef.current);
        thinkingTimeoutRef.current = null;
      }
    };
  }, [state, isHandsFree]);

  // Persist TTS enabled state
  useEffect(() => {
    localStorage.setItem('homepilot_tts_enabled', String(isTtsEnabled));
  }, [isTtsEnabled]);

  // Load available voices
  useEffect(() => {
    if (!svc) return;

    const loadVoices = () => {
      const availableVoices = svc.getVoices?.() || [];
      setVoices(availableVoices);

      if (!selectedVoice && availableVoices.length > 0) {
        // Prefer natural-sounding voices
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

  // Update speech service when voice changes
  useEffect(() => {
    if (!svc || !selectedVoice) return;
    svc.setPreferredVoiceURI?.(selectedVoice);
  }, [svc, selectedVoice]);

  const setSelectedVoice = useCallback((voiceURI: string) => {
    setSelectedVoiceState(voiceURI);
    localStorage.setItem('homepilot_voice_uri', voiceURI);
  }, []);

  // TTS state monitoring (event-driven) - runs in ALL modes for glow effect
  // CRITICAL: Pauses VAD during TTS to prevent speaker audio from triggering
  //           false barge-in (mic picks up speaker output → VAD fires → TTS killed)
  useEffect(() => {
    if (!svc) return;

    let lastTTSState = false;

    const checkTTSState = () => {
      const isSpeaking = svc.isSpeaking || false;

      if (isSpeaking !== lastTTSState) {
        lastTTSState = isSpeaking;

        if (isSpeaking) {
          // TTS started - set SPEAKING state for glow effect
          console.log('[VoiceController] TTS started - state: SPEAKING');
          setState('SPEAKING');

          // Pause VAD to prevent speaker audio from triggering false barge-in
          if (vadRef.current?.isRunning() && !vadRef.current.isPaused()) {
            vadRef.current.pause();
            // Reset the published audio level so any consumer reading
            // voice.audioLevel (e.g. the overlay's barge-in tap) doesn't
            // see a stale pre-pause peak and misread it as user speech.
            setAudioLevel(0);
            console.log('[VoiceController] VAD paused during TTS');
          }

          // Clear any pending resume timeout
          if (ttsEndTimeoutRef.current) {
            clearTimeout(ttsEndTimeoutRef.current);
            ttsEndTimeoutRef.current = null;
          }
        } else {
          // TTS ended - wait before transitioning and resuming VAD
          console.log('[VoiceController] TTS ended - waiting before state transition');
          ttsEndTimeoutRef.current = setTimeout(() => {
            // Arm the post-TTS mic guard — see ref declaration. Echo
            // tail can linger ~200-500 ms after TTS ended = true, so
            // even though VAD is about to resume, speech-start events
            // it fires inside this window are dropped rather than
            // starting a stale user turn.
            postTtsMicGuardUntilRef.current =
              Date.now() + (cfg.postTtsMicGuardMs ?? 0);

            // Resume VAD now that TTS audio has stopped
            if (vadRef.current?.isRunning() && vadRef.current.isPaused()) {
              vadRef.current.resume();
              // Same reason as the pause path — don't let a stale peak
              // from the pre-pause buffer re-publish through audioLevel.
              setAudioLevel(0);
              console.log('[VoiceController] VAD resumed after TTS');
            }

            if (stateRef.current === 'SPEAKING') {
              // In hands-free mode, go to IDLE to continue listening
              // In manual mode, go to OFF
              const nextState = isHandsFree ? 'IDLE' : 'OFF';
              setState(nextState);
              console.log(`[VoiceController] Transitioned to ${nextState} after TTS`);
            }
            ttsEndTimeoutRef.current = null;
          }, cfg.ttsEndDelay);
        }
      }
    };

    // Poll TTS state (most reliable across browsers)
    const interval = setInterval(checkTTSState, 50);

    return () => {
      clearInterval(interval);
      if (ttsEndTimeoutRef.current) {
        clearTimeout(ttsEndTimeoutRef.current);
        ttsEndTimeoutRef.current = null;
      }
    };
  }, [svc, isHandsFree, cfg.ttsEndDelay, cfg.postTtsMicGuardMs]);

  // Setup STT callbacks
  useEffect(() => {
    if (!svc) return;

    svc.setRecognitionCallbacks({
      onStart: () => {
        console.log('[VoiceController] STT started - state: LISTENING');
        setLastError(null); // Clear any previous error
        pendingResultRef.current = false; // Reset pending result flag
        setState('LISTENING');
      },
      onEnd: () => {
        console.log('[VoiceController] STT ended, hadResult:', pendingResultRef.current);
        // Record end time for cooldown tracking
        lastSttEndRef.current = Date.now();
        // Only go to THINKING if we actually sent text to the API
        if (stateRef.current === 'LISTENING') {
          if (isHandsFree) {
            // If we sent a result, go to THINKING to wait for response
            // Otherwise, go back to IDLE - no speech was recognized
            const nextState = pendingResultRef.current ? 'THINKING' : 'IDLE';
            console.log(`[VoiceController] STT ended -> ${nextState}`);
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
          console.log('[VoiceController] STT result:', finalText.trim());
          pendingResultRef.current = true; // Mark that we're sending a result
          onSendText(finalText.trim());
          // After sending, wait for response (THINKING state)
          if (isHandsFree) {
            setState('THINKING');
          }
        }
      },
      onError: (msg: string) => {
        console.warn('[VoiceController] STT error:', msg);
        setLastError(msg || 'stt_error');
        pendingResultRef.current = false;
        if (isHandsFree) {
          setState('IDLE');
        } else {
          setState('OFF');
        }
      },
    });
  }, [svc, onSendText, isHandsFree]);

  // VAD management for hands-free mode
  useEffect(() => {
    // Each effect-run gets a fresh generation number. Async VAD-start
    // callbacks capture it and bail out if the generation has moved
    // on while they were in-flight (e.g. user toggled hands-free off,
    // re-mounted the call overlay, etc.).
    const generation = ++handsFreeGenerationRef.current;

    if (!isHandsFree || !svc) {
      // Clean up VAD when not in hands-free mode
      if (vadRef.current) {
        vadRef.current.stop();
        vadRef.current = null;
      }
      if (!isHandsFree) {
        setState('OFF');
      }
      return;
    }

    // Check STT support before starting VAD
    if (!sttSupported) {
      setLastError('stt_not_supported');
      setState('OFF');
      return;
    }

    // Create VAD instance. Capture the local handle so async callbacks
    // (.then / .catch below) reference THIS VAD even if a later
    // effect-run has overwritten ``vadRef.current`` — under React 18
    // StrictMode the mount effect runs twice, so a stale .then that
    // reads vadRef.current would stop the VAD of the NEW effect run
    // (root cause of the 'first click does nothing, second click
    // works' bug when entering Voice mode).
    const vad = createVAD(
      // onSpeechStart
      () => {
        // Stale event from a previous hands-free generation — ignore.
        if (!isHandsFree || generation !== handsFreeGenerationRef.current) {
          return;
        }
        const currentState = stateRef.current;
        console.log('[VoiceController] VAD speech start, current state:', currentState);

        // Overlay's turn-lock holds the floor — drop the event.
        if (listeningSuppressedRef.current) {
          console.log('[VoiceController] VAD speech start suppressed (turn lock)');
          return;
        }

        // Post-TTS echo-tail window — TTS just finished, mic might
        // still be picking up our own voice. Skip this spurious start.
        if (Date.now() < postTtsMicGuardUntilRef.current) {
          console.log('[VoiceController] Ignoring speech start during post-TTS mic guard');
          return;
        }

        // Barge-in: if TTS is speaking, stop it
        if (currentState === 'SPEAKING' && cfg.bargeInEnabled) {
          console.log('[VoiceController] Barge-in detected - stopping TTS');
          svc.stopSpeaking?.();
        }

        // Cooldown check: don't start STT too quickly after previous session
        const timeSinceLastEnd = Date.now() - lastSttEndRef.current;
        const cooldownMs = 300; // 300ms cooldown between STT sessions
        if (timeSinceLastEnd < cooldownMs) {
          console.log('[VoiceController] STT cooldown active, waiting...');
          // Schedule a delayed start after cooldown
          setTimeout(() => {
            if (stateRef.current === 'IDLE') {
              console.log('[VoiceController] Starting STT after cooldown');
              try {
                svc.startSTT?.({});
              } catch (e: unknown) {
                const msg = e instanceof Error ? e.message : 'stt_start_failed';
                setLastError(msg);
                setState('OFF');
              }
            }
          }, cooldownMs - timeSinceLastEnd);
          return;
        }

        // Only start STT if we're in IDLE or SPEAKING (barge-in)
        if (currentState === 'IDLE' || currentState === 'SPEAKING') {
          try {
            svc.startSTT?.({});
          } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : 'stt_start_failed';
            setLastError(msg);
            setState('OFF');
          }
        }
      },
      // onSpeechEnd
      () => {
        if (!isHandsFree || generation !== handsFreeGenerationRef.current) {
          return;
        }
        const currentState = stateRef.current;
        console.log('[VoiceController] VAD speech end, current state:', currentState);

        // Suppression applies symmetrically — if we dropped the
        // start because the AI had the floor, dropping the end is
        // the consistent thing to do (the STT session we chose not
        // to start also doesn't need to be told to stop).
        if (listeningSuppressedRef.current) {
          console.log('[VoiceController] VAD speech end suppressed (turn lock)');
          return;
        }

        // Only stop STT if we're actively listening
        // Add 400ms delay to give STT time to finalize any pending recognition
        if (currentState === 'LISTENING') {
          setTimeout(() => {
            // Double-check we're still in LISTENING state (might have changed)
            if (stateRef.current === 'LISTENING') {
              try {
                console.log('[VoiceController] Stopping STT after delay');
                svc.stopSTT?.();
              } catch (e: unknown) {
                const msg = e instanceof Error ? e.message : 'stt_stop_failed';
                setLastError(msg);
              }
            }
          }, 400);
        }
      },
      cfg.vadConfig
    );
    vadRef.current = vad;

    // Start VAD
    vad.start()
      .then(() => {
        // Reject results from stale effect-runs — see generation doc.
        if (!isHandsFree || generation !== handsFreeGenerationRef.current) {
          vad.stop();
          return;
        }
        console.log('[VoiceController] VAD started, transitioning to IDLE');
        setLastError(null);
        setState('IDLE');
      })
      .catch((err) => {
        // Stale generation — don't overwrite state with OFF for a
        // VAD run the user has since torn down.
        if (generation !== handsFreeGenerationRef.current) return;
        console.error('[VoiceController] VAD start failed:', err);
        setLastError(err?.message || 'vad_start_failed');
        setState('OFF');
      });

    return () => {
      if (vadRef.current) {
        vadRef.current.stop();
        vadRef.current = null;
      }
    };
  }, [isHandsFree, svc, sttSupported, cfg.vadConfig, cfg.bargeInEnabled]);

  // Update audio levels for visualization
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

  // Clear error helper
  const clearError = useCallback(() => {
    setLastError(null);
  }, []);

  // Manual listening controls
  const startManualListening = useCallback(() => {
    if (!svc) return;

    // Check STT support first
    if (!sttSupported) {
      setLastError('stt_not_supported');
      setState('OFF');
      return;
    }

    svc.stopSpeaking?.();
    try {
      svc.startSTT?.({});
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'stt_start_failed';
      setLastError(msg);
      setState('OFF');
    }
  }, [svc, sttSupported]);

  const stopManualListening = useCallback(() => {
    if (!svc) return;
    try {
      svc.stopSTT?.();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'stt_stop_failed';
      setLastError(msg);
    }
  }, [svc]);

  const stopSpeaking = useCallback(() => {
    if (!svc) return;
    svc.stopSpeaking?.();
    // Resume VAD if it was paused during TTS
    if (vadRef.current?.isRunning() && vadRef.current.isPaused()) {
      vadRef.current.resume();
    }
    // Transition to appropriate state based on mode
    setState(isHandsFree ? 'IDLE' : 'OFF');
  }, [svc, isHandsFree]);

  const setHandsFree = useCallback((enabled: boolean) => {
    setIsHandsFree(enabled);
    localStorage.setItem('homepilot_voice_handsfree', String(enabled));
    if (!enabled) {
      setState('OFF');
    }
  }, []);

  const setTtsEnabled = useCallback((enabled: boolean) => {
    setIsTtsEnabled(enabled);
  }, []);

  /** Overlay-driven suppression of VAD speech events. When the
   *  overlay's turn-lock says the AI has the floor, we set this to
   *  true — VAD keeps running (no re-calibration latency on release)
   *  but the speech-start / speech-end callbacks bail out before
   *  any state change. On suppression-enable, if we were mid-LISTENING
   *  we also eject STT cleanly so a stale session doesn't linger.
   *
   *  ``reason`` is logged for traceability — e.g. 'turn_lock:speak:start'
   *  vs 'turn_lock:cleanup' explain two very different code paths that
   *  both end up calling this setter. */
  const setListeningSuppressed = useCallback(
    (suppressed: boolean, reason: string = 'unspecified') => {
      listeningSuppressedRef.current = suppressed;
      console.log(
        `[VoiceController] Listening suppression ${suppressed ? 'enabled' : 'disabled'} (reason=${reason})`,
      );
      if (suppressed && stateRef.current === 'LISTENING') {
        try { svc?.stopSTT?.(); } catch { /* no-op */ }
        setState(isHandsFree ? 'IDLE' : 'OFF');
      }
    },
    [svc, isHandsFree],
  );

  return {
    // State
    state,
    isHandsFree,
    isTtsEnabled,
    interimText,
    audioLevel,
    noiseFloor,
    threshold,

    // STT Support & Diagnostics
    sttSupported,
    lastError,
    clearError,

    // Actions
    setHandsFree,
    setTtsEnabled,
    startManualListening,
    stopManualListening,
    stopSpeaking,
    setListeningSuppressed,

    // Voice selection
    voices,
    selectedVoice,
    setSelectedVoice,
  };
}
