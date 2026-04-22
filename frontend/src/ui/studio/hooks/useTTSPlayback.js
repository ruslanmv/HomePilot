import { useEffect, useRef, useCallback, useState, useMemo } from "react";
const DEFAULT_VOICE_CONFIG = {
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
export function useTTSPlayback({ isActive, isPlaying, currentScene, currentSceneIndex, scenes, onSceneNarrationEnd, }) {
    const svc = useMemo(() => window.SpeechService, []);
    const [ttsEnabled, setTtsEnabledState] = useState(() => {
        return svc?.isTTSEnabled?.() ?? true;
    });
    const [isSpeaking, setIsSpeaking] = useState(false);
    const [isPaused, setIsPaused] = useState(false);
    const [isSupported, setIsSupported] = useState(false);
    const [voices, setVoices] = useState([]);
    const [voiceConfig, setVoiceConfigState] = useState(() => svc?.getVoiceConfig?.() ?? DEFAULT_VOICE_CONFIG);
    const lastSpokenSceneRef = useRef(-1);
    const speakingPromiseRef = useRef(null);
    // Use ref to always call the latest callback (avoids stale closure issues)
    const onSceneNarrationEndRef = useRef(onSceneNarrationEnd);
    useEffect(() => {
        onSceneNarrationEndRef.current = onSceneNarrationEnd;
    }, [onSceneNarrationEnd]);
    // Initialize and load voices
    useEffect(() => {
        if (!svc)
            return;
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
    const setTTSEnabled = useCallback((enabled) => {
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
    const setVoiceConfig = useCallback((config) => {
        const newConfig = { ...voiceConfig, ...config };
        setVoiceConfigState(newConfig);
        if (svc?.setVoiceConfig) {
            svc.setVoiceConfig(config);
        }
    }, [svc, voiceConfig]);
    // Speak the current scene's narration
    const speakCurrentScene = useCallback(async () => {
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
                    // Use ref to always call the latest callback (avoids stale closure)
                    onSceneNarrationEndRef.current?.();
                },
                onError: (error) => {
                    console.warn("[TTS] Speech error:", error);
                    setIsSpeaking(false);
                    setIsPaused(false);
                },
            });
            return success;
        }
        catch (error) {
            console.warn("[TTS] Failed to speak:", error);
            setIsSpeaking(false);
            return false;
        }
    }, [svc, currentScene?.narration, ttsEnabled]);
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
        if (!svc || !isActive)
            return;
        if (isPlaying && isPaused) {
            // TV Mode resumed, resume TTS
            resumeSpeaking();
        }
        else if (!isPlaying && isSpeaking && !isPaused) {
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
