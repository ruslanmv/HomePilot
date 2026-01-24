/**
 * Speech Service Module
 * Handles speech-to-text (recognition) and text-to-speech (synthesis)
 */

class SpeechService {
    constructor() {
        // Speech Recognition (Speech-to-Text)
        this.recognition = null;
        this.isRecognitionSupported = false;
        this.isRecognizing = false;
        this.micPermissionGranted = false;
        this.micStream = null;
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
        this.currentUtterance = null;

        // Preferred voice settings - load from localStorage
        this.preferredVoiceURI = localStorage.getItem("homepilot_voice_uri") || "";

        this.initializeSpeechRecognition();
        this.initializeSpeechSynthesis();
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
                if (this.recognitionCallbacks.onStart) this.recognitionCallbacks.onStart();
            };

            this.recognition.onresult = (event) => {
                let interimTranscript = '';
                let finalTranscript = '';

                for (let i = event.resultIndex; i < event.results.length; i++) {
                    const transcript = event.results[i][0].transcript;
                    if (event.results[i].isFinal) {
                        finalTranscript += transcript + ' ';
                    } else {
                        interimTranscript += transcript;
                    }
                }

                if (interimTranscript && this.recognitionCallbacks.onInterim) {
                    this.recognitionCallbacks.onInterim(interimTranscript.trim());
                }

                if (finalTranscript && this.recognitionCallbacks.onResult) {
                    this.recognitionCallbacks.onResult(finalTranscript.trim());
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
        if (this.preferredVoiceURI && this.voices.length > 0) {
            const exists = this.voices.find(v => v.voiceURI === this.preferredVoiceURI);
            if (!exists) {
                console.log('[SpeechService] Preferred voice not found, will use fallback');
            }
        }
    }

    getVoices() {
        return this.voices;
    }

    /**
     * Set the preferred voice URI for TTS
     * @param {string} uri - The voiceURI to use for speech synthesis
     */
    setPreferredVoiceURI(uri) {
        this.preferredVoiceURI = uri || "";
        try {
            localStorage.setItem("homepilot_voice_uri", this.preferredVoiceURI);
            console.log('[SpeechService] Preferred voice set to:', this.preferredVoiceURI);
        } catch (e) {
            console.warn('[SpeechService] Failed to save voice preference:', e);
        }
    }

    /**
     * Get the current preferred voice URI
     * @returns {string} The preferred voice URI
     */
    getPreferredVoiceURI() {
        return this.preferredVoiceURI;
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

    async speak(text, callbacks = {}) {
        if (!this.isSynthesisSupported) return false;

        this.stopSpeaking();

        this.currentUtterance = new SpeechSynthesisUtterance(text);
        this.currentUtterance.lang = 'en-US';
        this.currentUtterance.rate = 0.9;
        this.currentUtterance.pitch = 1.0;
        this.currentUtterance.volume = 1.0;

        const voices = this.getVoices();
        if (voices.length > 0) {
            // Try to find the user's preferred voice by URI
            let selectedVoice = null;

            if (this.preferredVoiceURI) {
                selectedVoice = voices.find(v => v.voiceURI === this.preferredVoiceURI);
            }

            // Fallback: find an English voice or use the first available
            if (!selectedVoice) {
                selectedVoice = voices.find(v => v.lang.startsWith('en')) || voices[0];
            }

            this.currentUtterance.voice = selectedVoice;

            // Update language to match voice
            if (selectedVoice && selectedVoice.lang) {
                this.currentUtterance.lang = selectedVoice.lang;
            }
        }

        this.currentUtterance.onstart = () => {
            this.isSpeaking = true;
            if (callbacks.onStart) callbacks.onStart();
        };

        this.currentUtterance.onend = () => {
            this.isSpeaking = false;
            if (callbacks.onEnd) callbacks.onEnd();
        };

        this.currentUtterance.onerror = (event) => {
            this.isSpeaking = false;
            if (event.error !== 'interrupted' && callbacks.onError) {
                callbacks.onError(event.error);
            }
        };

        try {
            this.synthesis.speak(this.currentUtterance);
            return true;
        } catch (error) {
            if (callbacks.onError) callbacks.onError('Failed to speak');
            return false;
        }
    }

    stopSpeaking() {
        try {
            if (this.isSpeaking || this.synthesis.speaking) {
                this.synthesis.cancel();
                this.isSpeaking = false;
            }
        } catch (e) {
            this.isSpeaking = false;
        }
    }
}

const speechService = new SpeechService();
window.SpeechService = speechService;
