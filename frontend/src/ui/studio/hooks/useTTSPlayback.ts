import { useEffect, useRef, useCallback, useState, useMemo } from "react";
import type { TVScene } from "../stores/tvModeStore";

// Use the existing Window.SpeechService declaration from other files
// Just define local types for what we need

interface VoiceConfig {
  voiceURI: string;
  rate: number;
  pitch: number;
  volume: number;
  enabled: boolean;
}

interface SpeakCallbacks {
  onStart?: () => void;
  onEnd?: () => void;
  onError?: (error: string) => void;
  onProgress?: (progress: SpeakProgress) => void;
}

interface SpeakProgress {
  charIndex: number;
  charLength: number;
  name: string;
  elapsedTime: number;
}

interface EpisodeCallbacks {
  onSceneStart?: (scene: TVScene, index: number) => void;
  onSceneEnd?: (scene: TVScene, index: number) => void;
  onProgress?: (progress: SpeakProgress & { sceneIndex?: number; scene?: TVScene }) => void;
  onEpisodeEnd?: () => void;
  onError?: (error: string, scene: TVScene, index: number) => void;
}

interface EpisodeState {
  isPlaying: boolean;
  isSpeaking: boolean;
  isPaused: boolean;
  currentSceneIndex: number;
  totalScenes: number;
}

interface UseTTSPlaybackOptions {
  /** Whether TV Mode is active */
  isActive: boolean;
  /** Whether TV Mode is playing */
  isPlaying: boolean;
  /** Current scene being displayed */
  currentScene: TVScene | undefined;
  /** Index of the current scene */
  currentSceneIndex: number;
  /** All scenes in the episode */
  scenes: TVScene[];
  /** Callback when scene finishes speaking */
  onSceneNarrationEnd?: () => void;
}

interface UseTTSPlaybackReturn {
  /** Whether TTS is enabled */
  ttsEnabled: boolean;
  /** Toggle TTS on/off */
  setTTSEnabled: (enabled: boolean) => void;
  /** Whether TTS is currently speaking */
  isSpeaking: boolean;
  /** Whether TTS is paused */
  isPaused: boolean;
  /** Whether browser supports TTS */
  isSupported: boolean;
  /** Available voices */
  voices: SpeechSynthesisVoice[];
  /** Current voice config */
  voiceConfig: VoiceConfig;
  /** Update voice config */
  setVoiceConfig: (config: Partial<VoiceConfig>) => void;
  /** Manually trigger speaking the current scene */
  speakCurrentScene: () => Promise<boolean>;
  /** Stop speaking */
  stopSpeaking: () => void;
  /** Pause speaking */
  pauseSpeaking: () => void;
  /** Resume speaking */
  resumeSpeaking: () => void;
}

const DEFAULT_VOICE_CONFIG: VoiceConfig = {
  voiceURI: "",
  rate: 1.0,
  pitch: 1.0,
  volume: 1.0,
  enabled: true,
};

/**
 * Hook for integrating TTS playback with TV Mode
 * Automatically speaks scene narration when scenes change
 */
export function useTTSPlayback({
  isActive,
  isPlaying,
  currentScene,
  currentSceneIndex,
  scenes,
  onSceneNarrationEnd,
}: UseTTSPlaybackOptions): UseTTSPlaybackReturn {
  const svc = useMemo(() => window.SpeechService, []);

  const [ttsEnabled, setTtsEnabledState] = useState<boolean>(() => {
    return svc?.isTTSEnabled?.() ?? true;
  });
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [isSupported, setIsSupported] = useState(false);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceConfig, setVoiceConfigState] = useState<VoiceConfig>(
    () => svc?.getVoiceConfig?.() ?? DEFAULT_VOICE_CONFIG
  );

  const lastSpokenSceneRef = useRef<number>(-1);
  const speakingPromiseRef = useRef<Promise<boolean> | null>(null);

  // Initialize and load voices
  useEffect(() => {
    if (!svc) return;

    setIsSupported(svc.isSynthesisSupported ?? false);
    setTtsEnabledState(svc.isTTSEnabled?.() ?? true);
    setVoiceConfigState(svc.getVoiceConfig?.() ?? DEFAULT_VOICE_CONFIG);

    const loadVoices = () => {
      const availableVoices = svc.getVoices?.() ?? [];
      setVoices(availableVoices);
    };

    loadVoices();

    // Voices might load asynchronously
    if (window.speechSynthesis?.onvoiceschanged !== undefined) {
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }
  }, [svc]);

  // Set TTS enabled
  const setTTSEnabled = useCallback((enabled: boolean) => {
    setTtsEnabledState(enabled);
    if (svc?.setTTSEnabled) {
      svc.setTTSEnabled(enabled);
    }
    if (!enabled) {
      svc?.stopSpeaking?.();
      setIsSpeaking(false);
      setIsPaused(false);
    }
  }, [svc]);

  // Update voice config
  const setVoiceConfig = useCallback((config: Partial<VoiceConfig>) => {
    const newConfig = { ...voiceConfig, ...config };
    setVoiceConfigState(newConfig);
    if (svc?.setVoiceConfig) {
      svc.setVoiceConfig(config);
    }
  }, [svc, voiceConfig]);

  // Speak the current scene's narration
  const speakCurrentScene = useCallback(async (): Promise<boolean> => {
    if (!svc || !currentScene?.narration || !ttsEnabled) {
      return false;
    }

    // Stop any ongoing speech
    svc.stopSpeaking?.();

    setIsSpeaking(true);
    setIsPaused(false);

    try {
      const success = await svc.speak(currentScene.narration, {
        onStart: () => {
          setIsSpeaking(true);
          setIsPaused(false);
        },
        onEnd: () => {
          setIsSpeaking(false);
          setIsPaused(false);
          onSceneNarrationEnd?.();
        },
        onError: (error: string) => {
          console.warn("[TTS] Speech error:", error);
          setIsSpeaking(false);
          setIsPaused(false);
        },
      });
      return success;
    } catch (error) {
      console.warn("[TTS] Failed to speak:", error);
      setIsSpeaking(false);
      return false;
    }
  }, [svc, currentScene?.narration, ttsEnabled, onSceneNarrationEnd]);

  // Stop speaking
  const stopSpeaking = useCallback(() => {
    svc?.stopSpeaking?.();
    setIsSpeaking(false);
    setIsPaused(false);
  }, [svc]);

  // Pause speaking
  const pauseSpeaking = useCallback(() => {
    svc?.pauseSpeaking?.();
    setIsPaused(true);
  }, [svc]);

  // Resume speaking
  const resumeSpeaking = useCallback(() => {
    svc?.resumeSpeaking?.();
    setIsPaused(false);
  }, [svc]);

  // Auto-speak when scene changes
  useEffect(() => {
    if (!isActive || !isPlaying || !ttsEnabled || !svc) {
      return;
    }

    // Only speak if we haven't spoken this scene yet
    if (currentSceneIndex === lastSpokenSceneRef.current) {
      return;
    }

    if (!currentScene?.narration) {
      lastSpokenSceneRef.current = currentSceneIndex;
      return;
    }

    console.log(`[TTS] Scene ${currentSceneIndex + 1} changed, speaking narration...`);
    lastSpokenSceneRef.current = currentSceneIndex;

    // Speak the scene narration
    speakingPromiseRef.current = speakCurrentScene();
  }, [isActive, isPlaying, ttsEnabled, currentSceneIndex, currentScene?.narration, speakCurrentScene, svc]);

  // Sync with play/pause state
  useEffect(() => {
    if (!svc || !isActive) return;

    if (isPlaying && isPaused) {
      // TV Mode resumed, resume TTS
      resumeSpeaking();
    } else if (!isPlaying && isSpeaking && !isPaused) {
      // TV Mode paused, pause TTS
      pauseSpeaking();
    }
  }, [isPlaying, isActive, isSpeaking, isPaused, pauseSpeaking, resumeSpeaking, svc]);

  // Stop TTS when TV Mode exits
  useEffect(() => {
    if (!isActive && svc) {
      svc.stopSpeaking?.();
      setIsSpeaking(false);
      setIsPaused(false);
      lastSpokenSceneRef.current = -1;
    }
  }, [isActive, svc]);

  // Reset spoken scene tracking when scenes change significantly
  useEffect(() => {
    if (scenes.length === 0) {
      lastSpokenSceneRef.current = -1;
    }
  }, [scenes.length]);

  return {
    ttsEnabled,
    setTTSEnabled,
    isSpeaking,
    isPaused,
    isSupported,
    voices,
    voiceConfig,
    setVoiceConfig,
    speakCurrentScene,
    stopSpeaking,
    pauseSpeaking,
    resumeSpeaking,
  };
}

export default useTTSPlayback;
