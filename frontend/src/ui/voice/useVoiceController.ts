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

  // Actions
  setHandsFree: (enabled: boolean) => void;
  setTtsEnabled: (enabled: boolean) => void;
  startManualListening: () => void;
  stopManualListening: () => void;
  stopSpeaking: () => void;

  // Voice selection
  voices: SpeechSynthesisVoice[];
  selectedVoice: string;
  setSelectedVoice: (voiceURI: string) => void;
}

const DEFAULT_CONFIG: VoiceControllerConfig = {
  ttsEndDelay: 300,
  bargeInEnabled: true,
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

  // Core state
  const [state, setState] = useState<VoiceState>('OFF');
  const [isHandsFree, setIsHandsFree] = useState(false);
  const [isTtsEnabled, setIsTtsEnabled] = useState(() => {
    return localStorage.getItem('homepilot_tts_enabled') !== 'false';
  });
  const [interimText, setInterimText] = useState('');

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

  // Keep stateRef in sync
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

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

  // TTS state monitoring (event-driven)
  useEffect(() => {
    if (!svc || !isHandsFree) return;

    let lastTTSState = false;

    const checkTTSState = () => {
      const isSpeaking = svc.isSpeaking || false;

      if (isSpeaking !== lastTTSState) {
        lastTTSState = isSpeaking;

        if (isSpeaking) {
          // TTS started
          console.log('[VoiceController] TTS started - state: SPEAKING');
          setState('SPEAKING');

          // Clear any pending resume timeout
          if (ttsEndTimeoutRef.current) {
            clearTimeout(ttsEndTimeoutRef.current);
            ttsEndTimeoutRef.current = null;
          }
        } else {
          // TTS ended - wait before transitioning to IDLE
          console.log('[VoiceController] TTS ended - waiting before IDLE');
          ttsEndTimeoutRef.current = setTimeout(() => {
            if (stateRef.current === 'SPEAKING' && isHandsFree) {
              setState('IDLE');
              console.log('[VoiceController] Transitioned to IDLE after TTS');
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
  }, [svc, isHandsFree, cfg.ttsEndDelay]);

  // Setup STT callbacks
  useEffect(() => {
    if (!svc) return;

    svc.setRecognitionCallbacks({
      onStart: () => {
        console.log('[VoiceController] STT started - state: LISTENING');
        setState('LISTENING');
      },
      onEnd: () => {
        console.log('[VoiceController] STT ended');
        // Transition to THINKING if we had speech, otherwise back to IDLE
        if (stateRef.current === 'LISTENING') {
          if (isHandsFree) {
            setState('THINKING');
          } else {
            setState('OFF');
          }
        }
      },
      onInterim: (text: string) => {
        setInterimText(text);
      },
      onResult: (finalText: string) => {
        setInterimText('');
        if (finalText?.trim()) {
          console.log('[VoiceController] STT result:', finalText.trim());
          onSendText(finalText.trim());
          // After sending, wait for response (THINKING state)
          if (isHandsFree) {
            setState('THINKING');
          }
        }
      },
      onError: (msg: string) => {
        console.warn('[VoiceController] STT error:', msg);
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

    // Create VAD instance
    vadRef.current = createVAD(
      // onSpeechStart
      () => {
        const currentState = stateRef.current;
        console.log('[VoiceController] VAD speech start, current state:', currentState);

        // Barge-in: if TTS is speaking, stop it
        if (currentState === 'SPEAKING' && cfg.bargeInEnabled) {
          console.log('[VoiceController] Barge-in detected - stopping TTS');
          svc.stopSpeaking?.();
        }

        // Only start STT if we're in IDLE or SPEAKING (barge-in)
        if (currentState === 'IDLE' || currentState === 'SPEAKING') {
          svc.startSTT?.({});
        }
      },
      // onSpeechEnd
      () => {
        const currentState = stateRef.current;
        console.log('[VoiceController] VAD speech end, current state:', currentState);

        // Only stop STT if we're actively listening
        if (currentState === 'LISTENING') {
          svc.stopSTT?.();
        }
      },
      cfg.vadConfig
    );

    // Start VAD
    vadRef.current.start()
      .then(() => {
        console.log('[VoiceController] VAD started, transitioning to IDLE');
        setState('IDLE');
      })
      .catch((err) => {
        console.error('[VoiceController] VAD start failed:', err);
        setState('OFF');
      });

    return () => {
      if (vadRef.current) {
        vadRef.current.stop();
        vadRef.current = null;
      }
    };
  }, [isHandsFree, svc, cfg.vadConfig, cfg.bargeInEnabled]);

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

  // Manual listening controls
  const startManualListening = useCallback(() => {
    if (!svc) return;
    svc.stopSpeaking?.();
    svc.startSTT?.({});
  }, [svc]);

  const stopManualListening = useCallback(() => {
    if (!svc) return;
    svc.stopSTT?.();
  }, [svc]);

  const stopSpeaking = useCallback(() => {
    if (!svc) return;
    svc.stopSpeaking?.();
    if (isHandsFree) {
      setState('IDLE');
    }
  }, [svc, isHandsFree]);

  const setHandsFree = useCallback((enabled: boolean) => {
    setIsHandsFree(enabled);
    if (!enabled) {
      setState('OFF');
    }
  }, []);

  const setTtsEnabled = useCallback((enabled: boolean) => {
    setIsTtsEnabled(enabled);
  }, []);

  return {
    // State
    state,
    isHandsFree,
    isTtsEnabled,
    interimText,
    audioLevel,
    noiseFloor,
    threshold,

    // Actions
    setHandsFree,
    setTtsEnabled,
    startManualListening,
    stopManualListening,
    stopSpeaking,

    // Voice selection
    voices,
    selectedVoice,
    setSelectedVoice,
  };
}
