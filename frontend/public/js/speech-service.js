/**
 * Speech Service Module
 * Handles speech-to-text (recognition) and text-to-speech (synthesis)
 * Extended with queue-based speaking for TV Mode / Play Story integration
 */

class SpeechService {
    constructor() {
        // Speech Recognition (Speech-to-Text)
        this.recognition = null;
        this.isRecognitionSupported = false;
        this.isRecognizing = false;
        this.micPermissionGranted = false;
        this.micStream = null;
        this.lastProcessedFinalIndex = -1; // Track last processed final result to prevent duplicates
        this.recognitionCallbacks = {
            onResult: null,
            onInterim: null,
            onError: null,
            onStart: null,
            onEnd: null,
        };

        // Speech Synthesis (Text-to-Speech)
        this.synthesis = window.speechSynthesis;
        this.isSynthesisSupported = 'speechSynthesis' in window;
        this.voices = [];
        this.isSpeaking = false;
        this.isPaused = false;
        this.currentUtterance = null;

        // Voice config - load from localStorage
        this.voiceConfig = this.loadVoiceConfig();

        // Episode/Queue playback state
        this.episodeQueue = [];
        this.currentQueueIndex = -1;
        this.isPlayingEpisode = false;
        this.episodeCallbacks = {
            onSceneStart: null,
            onSceneEnd: null,
            onProgress: null,
            onEpisodeEnd: null,
            onError: null,
        };

        this.initializeSpeechRecognition();
        this.initializeSpeechSynthesis();
    }

    /**
     * Load voice configuration from localStorage
     */
    loadVoiceConfig() {
        const defaults = {
            voiceURI: "",
            rate: 1.0,      // 0.5 - 2.0
            pitch: 1.0,     // 0 - 2
            volume: 1.0,    // 0 - 1
            enabled: true,
        };

        try {
            const stored = localStorage.getItem("homepilot_voice_config");
            if (stored) {
                const parsed = JSON.parse(stored);
                return { ...defaults, ...parsed };
            }
            // Also check legacy key
            const legacyVoice = localStorage.getItem("homepilot_voice_uri");
            if (legacyVoice) {
                defaults.voiceURI = legacyVoice;
            }
        } catch (e) {
            console.warn('[SpeechService] Failed to load voice config:', e);
        }
        return defaults;
    }

    /**
     * Save voice configuration to localStorage
     */
    saveVoiceConfig() {
        try {
            localStorage.setItem("homepilot_voice_config", JSON.stringify(this.voiceConfig));
            // Also update legacy key for backwards compatibility
            localStorage.setItem("homepilot_voice_uri", this.voiceConfig.voiceURI || "");
            console.log('[SpeechService] Voice config saved:', this.voiceConfig);
        } catch (e) {
            console.warn('[SpeechService] Failed to save voice config:', e);
        }
    }

    /**
     * Get current voice configuration
     */
    getVoiceConfig() {
        return { ...this.voiceConfig };
    }

    /**
     * Update voice configuration
     * @param {Object} config - Partial config to merge
     */
    setVoiceConfig(config) {
        this.voiceConfig = { ...this.voiceConfig, ...config };
        this.saveVoiceConfig();
    }

    // Legacy compatibility
    get preferredVoiceURI() {
        return this.voiceConfig.voiceURI;
    }

    initializeSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            this.isRecognitionSupported = true;
            this.recognition = new SpeechRecognition();
            this.recognition.continuous = false;
            this.recognition.interimResults = true;
            this.recognition.lang = 'en-US';

            this.recognition.onstart = () => {
                this.isRecognizing = true;
                this.lastProcessedFinalIndex = -1; // Reset tracking for new recognition session
                if (this.recognitionCallbacks.onStart) this.recognitionCallbacks.onStart();
            };

            this.recognition.onresult = (event) => {
                let interimTranscript = '';
                let newFinalTranscript = '';

                for (let i = event.resultIndex; i < event.results.length; i++) {
                    const transcript = event.results[i][0].transcript;
                    if (event.results[i].isFinal) {
                        // Only process this final result if we haven't seen it before
                        if (i > this.lastProcessedFinalIndex) {
                            newFinalTranscript += transcript + ' ';
                            this.lastProcessedFinalIndex = i;
                        }
                    } else {
                        interimTranscript += transcript;
                    }
                }

                if (interimTranscript && this.recognitionCallbacks.onInterim) {
                    this.recognitionCallbacks.onInterim(interimTranscript.trim());
                }

                // Only call onResult if there are NEW final results
                if (newFinalTranscript && this.recognitionCallbacks.onResult) {
                    this.recognitionCallbacks.onResult(newFinalTranscript.trim());
                }
            };

            this.recognition.onerror = (event) => {
                this.isRecognizing = false;
                if (this.recognitionCallbacks.onError) {
                    this.recognitionCallbacks.onError(event.error);
                }
            };

            this.recognition.onend = () => {
                this.isRecognizing = false;
                this.lastProcessedFinalIndex = -1; // Reset for next session
                if (this.recognitionCallbacks.onEnd) this.recognitionCallbacks.onEnd();
            };
        }
    }

    initializeSpeechSynthesis() {
        if (this.isSynthesisSupported) {
            this.loadVoices();
            if (speechSynthesis.onvoiceschanged !== undefined) {
                speechSynthesis.onvoiceschanged = () => this.loadVoices();
            }
        }
    }

    loadVoices() {
        this.voices = this.synthesis.getVoices();
        // Re-validate preferred voice exists after voices load
        if (this.voiceConfig.voiceURI && this.voices.length > 0) {
            const exists = this.voices.find(v => v.voiceURI === this.voiceConfig.voiceURI);
            if (!exists) {
                console.log('[SpeechService] Preferred voice not found, will use fallback');
            }
        }
    }

    getVoices() {
        return this.voices;
    }

    /**
     * Get the selected voice object based on config
     */
    getSelectedVoice() {
        const voices = this.getVoices();
        if (voices.length === 0) return null;

        // Try to find the user's preferred voice by URI
        if (this.voiceConfig.voiceURI) {
            const preferred = voices.find(v => v.voiceURI === this.voiceConfig.voiceURI);
            if (preferred) return preferred;
        }

        // Fallback: find a natural-sounding English voice
        const googleVoice = voices.find(v =>
            v.name.toLowerCase().includes('google') && v.lang.startsWith('en')
        );
        if (googleVoice) return googleVoice;

        // Fallback: any English voice
        const englishVoice = voices.find(v => v.lang.startsWith('en'));
        if (englishVoice) return englishVoice;

        // Last resort: first available
        return voices[0];
    }

    /**
     * Set the preferred voice URI for TTS
     * @param {string} uri - The voiceURI to use for speech synthesis
     */
    setPreferredVoiceURI(uri) {
        this.voiceConfig.voiceURI = uri || "";
        this.saveVoiceConfig();
        console.log('[SpeechService] Preferred voice set to:', uri);
    }

    /**
     * Get the current preferred voice URI
     * @returns {string} The preferred voice URI
     */
    getPreferredVoiceURI() {
        return this.voiceConfig.voiceURI;
    }

    setRecognitionCallbacks(callbacks = {}) {
        this.recognitionCallbacks = { ...this.recognitionCallbacks, ...callbacks };
    }

    async startSTT(callbacks = {}) {
        if (!this.isRecognitionSupported) {
            if (callbacks.onError) callbacks.onError('Speech recognition not supported');
            return false;
        }

        if (this.isRecognizing) return false;

        this.recognitionCallbacks = { ...this.recognitionCallbacks, ...callbacks };

        try {
            this.recognition.start();
            return true;
        } catch (error) {
            if (callbacks.onError) callbacks.onError('Failed to start recognition');
            return false;
        }
    }

    stopSTT() {
        if (this.isRecognizing && this.recognition) {
            this.recognition.stop();
        }
    }

    /**
     * Speak a single text with current voice configuration
     * @param {string} text - Text to speak
     * @param {Object} callbacks - Event callbacks
     * @returns {Promise<boolean>} - Whether speaking completed successfully
     */
    speak(text, callbacks = {}) {
        return new Promise((resolve) => {
            if (!this.isSynthesisSupported || !this.voiceConfig.enabled) {
                resolve(false);
                return;
            }

            this.stopSpeaking();

            const utterance = new SpeechSynthesisUtterance(text);
            const voice = this.getSelectedVoice();

            if (voice) {
                utterance.voice = voice;
                utterance.lang = voice.lang || 'en-US';
            } else {
                utterance.lang = 'en-US';
            }

            utterance.rate = this.voiceConfig.rate || 1.0;
            utterance.pitch = this.voiceConfig.pitch || 1.0;
            utterance.volume = this.voiceConfig.volume || 1.0;

            this.currentUtterance = utterance;

            utterance.onstart = () => {
                this.isSpeaking = true;
                this.isPaused = false;
                if (callbacks.onStart) callbacks.onStart();
            };

            utterance.onend = () => {
                this.isSpeaking = false;
                this.isPaused = false;
                if (callbacks.onEnd) callbacks.onEnd();
                resolve(true);
            };

            utterance.onerror = (event) => {
                this.isSpeaking = false;
                this.isPaused = false;
                if (event.error !== 'interrupted' && callbacks.onError) {
                    callbacks.onError(event.error);
                }
                resolve(event.error === 'interrupted');
            };

            // Progress tracking via boundary events (Chrome/Edge support)
            utterance.onboundary = (event) => {
                if (callbacks.onProgress) {
                    callbacks.onProgress({
                        charIndex: event.charIndex,
                        charLength: event.charLength || 0,
                        name: event.name, // "word" or "sentence"
                        elapsedTime: event.elapsedTime,
                    });
                }
            };

            try {
                this.synthesis.speak(utterance);
            } catch (error) {
                if (callbacks.onError) callbacks.onError('Failed to speak');
                resolve(false);
            }
        });
    }

    /**
     * Speak text and wait for completion (async/await friendly)
     */
    async speakAsync(text, callbacks = {}) {
        return this.speak(text, callbacks);
    }

    /**
     * Pause current speech
     */
    pauseSpeaking() {
        if (this.isSpeaking && !this.isPaused) {
            try {
                this.synthesis.pause();
                this.isPaused = true;
                console.log('[SpeechService] Speech paused');
            } catch (e) {
                console.warn('[SpeechService] Failed to pause:', e);
            }
        }
    }

    /**
     * Resume paused speech
     */
    resumeSpeaking() {
        if (this.isPaused) {
            try {
                this.synthesis.resume();
                this.isPaused = false;
                console.log('[SpeechService] Speech resumed');
            } catch (e) {
                console.warn('[SpeechService] Failed to resume:', e);
            }
        }
    }

    /**
     * Stop current speech
     */
    stopSpeaking() {
        try {
            if (this.isSpeaking || this.synthesis.speaking) {
                this.synthesis.cancel();
                this.isSpeaking = false;
                this.isPaused = false;
            }
        } catch (e) {
            this.isSpeaking = false;
            this.isPaused = false;
        }
    }

    // ============================================================================
    // Episode/Scene Queue Playback (for TV Mode / Play Story)
    // ============================================================================

    /**
     * Start playing an episode (array of scenes with narration)
     * @param {Array<{idx: number, narration: string, duration_s?: number}>} scenes - Scenes to play
     * @param {Object} callbacks - Episode callbacks
     * @param {number} startIndex - Starting scene index (default 0)
     */
    startEpisode(scenes, callbacks = {}, startIndex = 0) {
        if (!this.isSynthesisSupported || !this.voiceConfig.enabled) {
            console.log('[SpeechService] TTS not enabled or not supported');
            return false;
        }

        this.stopEpisode(); // Stop any existing playback

        this.episodeQueue = scenes.map((scene, i) => ({
            idx: scene.idx ?? i,
            narration: scene.narration || "",
            duration_s: scene.duration_s || 5,
        }));

        this.currentQueueIndex = startIndex - 1; // Will increment on first playNext
        this.isPlayingEpisode = true;
        this.episodeCallbacks = { ...this.episodeCallbacks, ...callbacks };

        console.log(`[SpeechService] Starting episode with ${scenes.length} scenes`);

        // Don't auto-advance - let TV Mode control scene transitions
        return true;
    }

    /**
     * Speak the current scene in the episode
     * Called by TV Mode when scene changes
     * @param {number} sceneIndex - Scene index to speak
     * @returns {Promise<boolean>} - Whether speaking completed
     */
    async speakScene(sceneIndex) {
        if (!this.isPlayingEpisode || sceneIndex >= this.episodeQueue.length) {
            return false;
        }

        const scene = this.episodeQueue[sceneIndex];
        if (!scene || !scene.narration) {
            return true; // No narration to speak
        }

        this.currentQueueIndex = sceneIndex;

        // Notify scene start
        if (this.episodeCallbacks.onSceneStart) {
            this.episodeCallbacks.onSceneStart(scene, sceneIndex);
        }

        console.log(`[SpeechService] Speaking scene ${sceneIndex + 1}: "${scene.narration.substring(0, 50)}..."`);

        // Speak the scene narration
        const success = await this.speak(scene.narration, {
            onProgress: (progress) => {
                if (this.episodeCallbacks.onProgress) {
                    this.episodeCallbacks.onProgress({
                        ...progress,
                        sceneIndex,
                        scene,
                    });
                }
            },
            onEnd: () => {
                if (this.episodeCallbacks.onSceneEnd) {
                    this.episodeCallbacks.onSceneEnd(scene, sceneIndex);
                }
            },
            onError: (error) => {
                if (this.episodeCallbacks.onError) {
                    this.episodeCallbacks.onError(error, scene, sceneIndex);
                }
            },
        });

        return success;
    }

    /**
     * Speak a scene by providing scene data directly
     * @param {Object} scene - Scene object with narration
     * @returns {Promise<boolean>}
     */
    async speakSceneNarration(scene) {
        if (!scene?.narration || !this.voiceConfig.enabled) {
            return true; // Nothing to speak
        }

        console.log(`[SpeechService] Speaking narration: "${scene.narration.substring(0, 50)}..."`);

        return this.speak(scene.narration, {
            onProgress: (progress) => {
                if (this.episodeCallbacks.onProgress) {
                    this.episodeCallbacks.onProgress({
                        ...progress,
                        scene,
                    });
                }
            },
        });
    }

    /**
     * Pause episode playback
     */
    pauseEpisode() {
        this.pauseSpeaking();
    }

    /**
     * Resume episode playback
     */
    resumeEpisode() {
        this.resumeSpeaking();
    }

    /**
     * Stop episode playback
     */
    stopEpisode() {
        this.stopSpeaking();
        this.isPlayingEpisode = false;
        this.episodeQueue = [];
        this.currentQueueIndex = -1;

        if (this.episodeCallbacks.onEpisodeEnd) {
            this.episodeCallbacks.onEpisodeEnd();
        }
    }

    /**
     * Check if TTS is enabled
     */
    isTTSEnabled() {
        return this.voiceConfig.enabled && this.isSynthesisSupported;
    }

    /**
     * Enable or disable TTS
     */
    setTTSEnabled(enabled) {
        this.voiceConfig.enabled = enabled;
        this.saveVoiceConfig();

        if (!enabled) {
            this.stopSpeaking();
        }
    }

    /**
     * Get current episode playback state
     */
    getEpisodeState() {
        return {
            isPlaying: this.isPlayingEpisode,
            isSpeaking: this.isSpeaking,
            isPaused: this.isPaused,
            currentSceneIndex: this.currentQueueIndex,
            totalScenes: this.episodeQueue.length,
        };
    }
}

const speechService = new SpeechService();
window.SpeechService = speechService;
