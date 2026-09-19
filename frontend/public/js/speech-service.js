/**
 * Speech Service Module
 * Handles speech-to-text (recognition) and text-to-speech (synthesis)
 * Extended with queue-based speaking for TV Mode / Play Story integration
 */

/**
 * Minimum time a recognition session must stay open before a caller-requested
 * stop is honoured.
 *
 * Chrome does not start streaming audio the instant `recognition.start()`
 * resolves — it opens its own capture, connects to the recognizer, and only then
 * begins emitting `audiostart` / `speechstart` / results. HomePilot's VAD, by
 * contrast, fires as soon as the waveform crosses the threshold, so a short
 * utterance can reach `vad_silence` while the recognizer is still warming up.
 * Stopping there finalizes an empty session: no result, and not even a
 * `no-speech` error, because `stop()` ends cleanly.
 *
 * So a stop arriving before this deadline is deferred rather than dropped.
 */
const STT_MIN_LISTEN_MS = 1600;

/**
 * How long to wait for an aborted recognizer to reach `onend` before starting the next turn.
 *
 * Chrome tears a session down in a few milliseconds, so this is a ceiling, not a delay: the
 * wait ends the moment `onend` arrives. It exists only so a browser that never delivers the
 * event cannot strand voice input forever.
 */
const RECOGNITION_END_TIMEOUT_MS = 1500;

/**
 * How long to keep a recognizer open that has captured audio but heard no speech at all.
 *
 * HomePilot's VAD decides the turn is over from *its* microphone, which is not the one the
 * browser recognizer is recording. When the recognizer has not heard a syllable, that verdict
 * says nothing about this turn, and honouring it immediately guarantees an empty one. Five
 * seconds is past the point where Chrome's own endpointer would have fired on real speech, so
 * a turn that reaches it was never going to produce text — and now says so with evidence
 * rather than with a stop we chose.
 */
const STT_NO_SPEECH_GRACE_MS = 5000;

/**
 * Hard ceiling for a deferred stop, so a recognizer that never reports audio
 * cannot hold the turn open forever.
 */
const STT_MAX_LISTEN_MS = 12000;

/**
 * Mirror of `microphoneDebug()` from `src/ui/media/microphoneDebug.ts`.
 *
 * This file is a plain classic script served from `public/`, so it cannot
 * import the TypeScript module. It appends to the same ring buffer with the
 * same entry shape and the same console prefix, so one DevTools filter on
 * `HomePilot:Mic` still shows Settings, chat, Voice, VAD and this service
 * interleaved in real order.
 *
 * Metadata only — never audio bytes and never recognized transcript text.
 */
function micTrace(event, details) {
    const entry = {
        seq: (micTrace._seq = (micTrace._seq || 0) + 1),
        at: new Date().toISOString(),
        scope: 'speech-service',
        event,
        details: details || {},
    };
    try {
        const history = window.__HOMEPILOT_MIC_DEBUG__ || [];
        history.push(entry);
        if (history.length > 200) history.splice(0, history.length - 200);
        window.__HOMEPILOT_MIC_DEBUG__ = history;
        window.dispatchEvent(new CustomEvent('homepilot:microphone-debug', { detail: entry }));
    } catch (e) {
        // Diagnostics must never interfere with microphone capture.
    }
    console.info(`[HomePilot:Mic][speech-service] ${event}`, entry.details);
    return entry;
}

class SpeechService {
    constructor() {
        // Speech Recognition (Speech-to-Text)
        this.recognition = null;
        this.isRecognitionSupported = false;
        this.isRecognizing = false;
        /**
         * A session that has been aborted or stopped but has not yet reached `onend`.
         *
         * `abort()` and `stop()` return immediately; the browser keeps the session alive
         * until it has torn its capture down, and `start()` before that throws
         * `InvalidStateError` on the very same recognizer object. Clearing `isRecognizing`
         * at the call site made the window invisible, so a hand-off — the assistant stops
         * talking, listening restarts — aborted a live turn and then failed to start the
         * next one. The microphone stayed open and nothing was ever transcribed again.
         */
        this.recognitionEnding = false;
        this.recognitionEndWaiters = [];
        this.micPermissionGranted = false;
        this.micStream = null;
        this.recognitionCallbacks = {
            onResult: null,
            onInterim: null,
            onError: null,
            onStart: null,
            onEnd: null,
        };

        // Language used for recognition. Overridable so a non-English user is
        // not silently transcribed as English (a very common "it hears nothing"
        // report that is really "it heard the wrong language").
        this.recognitionLang = this.loadRecognitionLang();

        /**
         * What the browser actually reported during the most recent recognition
         * session. This is the evidence needed to tell the three failure modes
         * apart, which are indistinguishable from `hadResult: false` alone:
         *
         *   - `sawAudioStart === false` → the recognizer never opened a capture
         *     (permission, or another consumer holds the default input).
         *   - `sawAudioStart && !sawSpeechStart` → it captured, but from a
         *     silent device — typically the OS default while HomePilot's VAD
         *     watches a different, explicitly selected microphone.
         *   - `sawSpeechStart && !sawResult` → it heard speech but produced no
         *     transcript (cut off too early, wrong language, or `nomatch`).
         */
        this.lastSttDiagnostics = this.emptySttDiagnostics();

        /** `performance.now()` when the current turn opened, or `null` between turns. */
        this.sttStartedAt = null;
        this.pendingStopTimer = null;
        this.stopRequested = false;

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

    emptySttDiagnostics() {
        return {
            startedAt: 0,
            elapsedMs: 0,
            sawAudioStart: false,
            sawSoundStart: false,
            sawSpeechStart: false,
            sawInterim: false,
            sawResult: false,
            sawNoMatch: false,
            error: null,
            lang: this.recognitionLang || 'en-US',
            stoppedBy: null,
        };
    }

    /**
     * Snapshot of the last recognition session, for the Settings self-test and
     * for anyone reading `window.SpeechService.getSttDiagnostics()` in DevTools.
     */
    getSttDiagnostics() {
        return { ...this.lastSttDiagnostics };
    }

    loadRecognitionLang() {
        try {
            const saved = localStorage.getItem('homepilot_stt_lang');
            if (saved) return saved;
        } catch (e) {
            // Storage can be unavailable in locked-down contexts.
        }
        return (typeof navigator !== 'undefined' && navigator.language) || 'en-US';
    }

    /**
     * Change the recognition language. Takes effect on the next session.
     */
    setRecognitionLang(lang) {
        this.recognitionLang = lang || 'en-US';
        if (this.recognition) this.recognition.lang = this.recognitionLang;
        try {
            localStorage.setItem('homepilot_stt_lang', this.recognitionLang);
        } catch (e) {
            // Non-fatal: the language still applies for this session.
        }
        micTrace('recognition_lang_set', { lang: this.recognitionLang });
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
            this.recognition.lang = this.recognitionLang;

            this.recognition.onstart = () => {
                this.isRecognizing = true;
                micTrace('recognition_onstart', { lang: this.recognition.lang });
                if (this.recognitionCallbacks.onStart) this.recognitionCallbacks.onStart();
            };

            // The four lifecycle events below are what make a silent failure
            // diagnosable. Without them `onend` with no result looks identical
            // whether the recognizer never got audio, got audio from a silent
            // device, or heard speech it could not transcribe.
            this.recognition.onaudiostart = () => {
                this.lastSttDiagnostics.sawAudioStart = true;
                micTrace('recognition_audiostart', {
                    elapsedMs: this.sttElapsedMs(),
                });
            };

            this.recognition.onsoundstart = () => {
                this.lastSttDiagnostics.sawSoundStart = true;
                micTrace('recognition_soundstart', { elapsedMs: this.sttElapsedMs() });
            };

            this.recognition.onspeechstart = () => {
                this.lastSttDiagnostics.sawSpeechStart = true;
                micTrace('recognition_speechstart', { elapsedMs: this.sttElapsedMs() });
            };

            this.recognition.onspeechend = () => {
                micTrace('recognition_speechend', { elapsedMs: this.sttElapsedMs() });
            };

            this.recognition.onaudioend = () => {
                micTrace('recognition_audioend', { elapsedMs: this.sttElapsedMs() });
            };

            this.recognition.onnomatch = () => {
                this.lastSttDiagnostics.sawNoMatch = true;
                micTrace('recognition_nomatch', { elapsedMs: this.sttElapsedMs() });
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

                if (interimTranscript) {
                    // Recorded whether or not anyone is subscribed: "the browser
                    // produced an interim" is evidence about the *device*, and a
                    // caller with no onInterim handler must not erase it.
                    this.lastSttDiagnostics.sawInterim = true;
                    // Character count only — the trace never carries transcript text.
                    micTrace('recognition_interim', {
                        characters: interimTranscript.trim().length,
                        elapsedMs: this.sttElapsedMs(),
                    });
                    if (this.recognitionCallbacks.onInterim) {
                        this.recognitionCallbacks.onInterim(interimTranscript.trim());
                    }
                }

                if (finalTranscript) {
                    this.lastSttDiagnostics.sawResult = true;
                    micTrace('recognition_final', {
                        characters: finalTranscript.trim().length,
                        elapsedMs: this.sttElapsedMs(),
                    });
                    // A result makes any deferred stop moot: the turn is over.
                    this.clearPendingStop();
                    if (this.recognitionCallbacks.onResult) {
                        this.recognitionCallbacks.onResult(finalTranscript.trim());
                    }
                }
            };

            this.recognition.onerror = (event) => {
                this.isRecognizing = false;
                this.clearPendingStop();
                this.lastSttDiagnostics.error = event.error || 'unknown';
                this.lastSttDiagnostics.elapsedMs = this.sttElapsedMs();
                micTrace('recognition_onerror', {
                    error: event.error || 'unknown',
                    elapsedMs: this.lastSttDiagnostics.elapsedMs,
                    sawAudioStart: this.lastSttDiagnostics.sawAudioStart,
                    sawSpeechStart: this.lastSttDiagnostics.sawSpeechStart,
                });
                if (this.recognitionCallbacks.onError) {
                    this.recognitionCallbacks.onError(event.error);
                }
            };

            this.recognition.onend = () => {
                this.isRecognizing = false;
                this.settleRecognitionEnd();
                this.clearPendingStop();
                this.lastSttDiagnostics.elapsedMs = this.sttElapsedMs();
                micTrace('recognition_onend', {
                    elapsedMs: this.lastSttDiagnostics.elapsedMs,
                    sawAudioStart: this.lastSttDiagnostics.sawAudioStart,
                    sawSpeechStart: this.lastSttDiagnostics.sawSpeechStart,
                    sawInterim: this.lastSttDiagnostics.sawInterim,
                    sawResult: this.lastSttDiagnostics.sawResult,
                    sawNoMatch: this.lastSttDiagnostics.sawNoMatch,
                    stoppedBy: this.lastSttDiagnostics.stoppedBy,
                    error: this.lastSttDiagnostics.error,
                });
                if (this.recognitionCallbacks.onEnd) this.recognitionCallbacks.onEnd();
            };
        }
    }

    /**
     * The recognizer has reached `onend` — release anyone waiting to start the next turn.
     *
     * Called from `onend` only. `onerror` is not enough: Chrome raises `aborted` and *then*
     * ends, and a start issued between the two hits the same `InvalidStateError` this exists
     * to prevent.
     */
    settleRecognitionEnd() {
        this.recognitionEnding = false;
        const waiters = this.recognitionEndWaiters;
        this.recognitionEndWaiters = [];
        waiters.forEach((resolve) => {
            try { resolve(true); } catch (e) { /* a waiter that throws is not our problem */ }
        });
    }

    /**
     * Resolve once no session is winding down, so `start()` can be called safely.
     *
     * Bounded: a browser that never delivers `onend` must not strand voice input forever.
     * Falling through after the timeout is deliberate — `start()` then either works or
     * reports a real error, which is better evidence than a promise that never settles.
     */
    whenRecognitionIdle(timeoutMs = RECOGNITION_END_TIMEOUT_MS) {
        if (!this.recognitionEnding) return Promise.resolve(true);
        return new Promise((resolve) => {
            let settled = false;
            const finish = (ended) => {
                if (settled) return;
                settled = true;
                this.recognitionEndWaiters = this.recognitionEndWaiters.filter((w) => w !== finish);
                resolve(ended);
            };
            this.recognitionEndWaiters.push(finish);
            setTimeout(() => {
                if (settled) return;
                micTrace('recognition_end_wait_timeout', { timeoutMs });
                finish(false);
            }, timeoutMs);
        });
    }

    sttElapsedMs() {
        // `null`, not falsy: `performance.now()` can legitimately return 0, and treating that
        // as "no turn in progress" pins the elapsed reading at 0 for the whole session — which
        // makes every stop look like it arrived during warm-up and every guard below unreachable.
        if (this.sttStartedAt === null) return 0;
        return Math.max(0, Math.round(performance.now() - this.sttStartedAt));
    }

    clearPendingStop() {
        if (this.pendingStopTimer) {
            clearTimeout(this.pendingStopTimer);
            this.pendingStopTimer = null;
        }
        this.stopRequested = false;
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

    /**
     * Begin one recognition session.
     *
     * `options.continuous` keeps the session open across utterances instead of ending at the
     * first pause. That is what makes a hands-free transcript read like a live caption: the
     * recognizer streams interim words the whole time, and each finished phrase arrives as its
     * own `onResult` without the session tearing down in between.
     *
     * One-shot remains the default, and is right for the chat composer and the Settings test:
     * both are a single turn with a Stop button, and a session that outlived the turn would
     * hold the microphone after the user thought they had released it.
     */
    async startSTT(callbacks = {}, options = {}) {
        if (!this.isRecognitionSupported) {
            micTrace('start_unsupported');
            if (callbacks.onError) callbacks.onError('Speech recognition not supported');
            return false;
        }

        if (this.isRecognizing) {
            micTrace('start_skipped_already_recognizing');
            return false;
        }

        // The previous turn was aborted or stopped microseconds ago and the browser has not
        // finished with it. Starting now throws `InvalidStateError` and the turn is lost, so
        // wait for `onend` — normally a few milliseconds — instead of racing it.
        if (this.recognitionEnding) {
            micTrace('start_waiting_for_previous_end', {
                elapsedMs: this.sttElapsedMs(),
            });
            const ended = await this.whenRecognitionIdle();
            micTrace('start_previous_end_settled', { ended });
        }

        this.recognitionCallbacks = { ...this.recognitionCallbacks, ...callbacks };

        this.clearPendingStop();
        this.sttStartedAt = performance.now();
        this.lastSttDiagnostics = this.emptySttDiagnostics();
        this.lastSttDiagnostics.startedAt = Date.now();
        this.recognition.lang = this.recognitionLang;
        // Set per session, not once at construction: the same recognizer object serves the
        // composer's single turn and Voice's running caption.
        this.recognition.continuous = Boolean(options.continuous);
        this.recognition.interimResults = true;

        micTrace('start_requested', {
            lang: this.recognition.lang,
            continuous: this.recognition.continuous,
        });

        try {
            this.recognition.start();
            return true;
        } catch (error) {
            // `start()` throws InvalidStateError when a session is already live
            // on this page — including one owned by a *different* recognizer
            // object. Reporting the real reason beats the old generic message.
            const errorName = (error && error.name) || 'start_failed';
            // One retry, and only when a session we know about is still winding down: the
            // wait above timed out, but the recognizer is ending and will be usable in a
            // moment. Giving up here is what left the microphone open with nothing
            // transcribing it. An `InvalidStateError` with nothing ending is a different
            // fault and is reported as one, and no other error is retried at all — a retry
            // loop on a permission denial helps nobody.
            if (errorName === 'InvalidStateError' && this.recognitionEnding) {
                micTrace('start_retry_after_invalid_state', {
                    elapsedMs: this.sttElapsedMs(),
                });
                await this.whenRecognitionIdle();
                try {
                    this.recognition.start();
                    micTrace('start_recovered_after_invalid_state');
                    return true;
                } catch (retryError) {
                    this.lastSttDiagnostics.error =
                        (retryError && retryError.name) || 'start_failed';
                    micTrace('start_failed', {
                        errorName: this.lastSttDiagnostics.error,
                        errorMessage: (retryError && retryError.message) || String(retryError),
                        afterRetry: true,
                    });
                    if (callbacks.onError) callbacks.onError(this.lastSttDiagnostics.error);
                    return false;
                }
            }
            this.lastSttDiagnostics.error = errorName;
            micTrace('start_failed', {
                errorName: (error && error.name) || 'Error',
                errorMessage: (error && error.message) || String(error),
            });
            if (callbacks.onError) callbacks.onError(this.lastSttDiagnostics.error);
            return false;
        }
    }

    /**
     * Ask the recognizer to finish the current turn.
     *
     * A stop that arrives before `STT_MIN_LISTEN_MS` while nothing has been
     * recognized yet is *deferred*, not dropped. Honouring it immediately is
     * what produced the classic `stt_onend { hadResult: false }` with no
     * interim and no error: HomePilot's VAD reaches its silence window before
     * Chrome's recognizer has streamed enough audio to finalize anything.
     *
     * Pass `{ force: true }` to stop right now (an explicit user action, a
     * teardown, or a turn lock — none of which should wait for a transcript).
     */
    stopSTT(options = {}) {
        const force = Boolean(options.force);
        const reason = options.reason || 'unspecified';

        if (!this.isRecognizing || !this.recognition) {
            micTrace('stop_ignored_not_recognizing', { reason, force });
            return false;
        }

        const elapsedMs = this.sttElapsedMs();
        const settled = this.lastSttDiagnostics.sawResult;
        const warmingUp = elapsedMs < STT_MIN_LISTEN_MS && !settled;
        // The recognizer has been listening and has not heard a syllable. Our caller's silence
        // window is evidence about *its own* microphone, and this recognizer is on a different
        // one — so it is not evidence that this turn is over. Stopping now can only produce an
        // empty turn, where waiting costs nothing that was going to become text anyway.
        //
        // On a marginal device (a quiet or distant input) the extra window is sometimes all it
        // needs. On a genuinely silent one it buys the thing the trace could not previously
        // claim: `sawSpeechStart: false` after the recognizer was given every chance, rather
        // than after we cut it off at 2.4 s. That difference decides whether "the browser
        // recognizer is deaf here" is a diagnosis or a guess.
        const heardNothingYet = !settled
            && this.lastSttDiagnostics.sawAudioStart
            && !this.lastSttDiagnostics.sawSpeechStart
            && !this.lastSttDiagnostics.sawInterim
            && elapsedMs < STT_NO_SPEECH_GRACE_MS;

        if (!force && (warmingUp || heardNothingYet)) {
            if (this.pendingStopTimer) {
                micTrace('stop_already_deferred', { reason, elapsedMs });
                return false;
            }
            const target = heardNothingYet ? STT_NO_SPEECH_GRACE_MS : STT_MIN_LISTEN_MS;
            const waitMs = Math.min(
                target - elapsedMs,
                Math.max(0, STT_MAX_LISTEN_MS - elapsedMs),
            );
            this.stopRequested = true;
            micTrace('stop_deferred_warming_up', {
                reason,
                elapsedMs,
                waitMs,
                // Which guard held it, so a longer turn does not read as a hang.
                deferredBy: heardNothingYet && !warmingUp ? 'no_speech_yet' : 'warming_up',
                minListenMs: STT_MIN_LISTEN_MS,
                sawAudioStart: this.lastSttDiagnostics.sawAudioStart,
                sawSpeechStart: this.lastSttDiagnostics.sawSpeechStart,
            });
            this.pendingStopTimer = setTimeout(() => {
                this.pendingStopTimer = null;
                this.stopRequested = false;
                if (!this.isRecognizing) return;
                // A result may have landed while we waited; `onresult` already
                // cleared the timer in that case, so reaching here means the
                // turn is genuinely over.
                this.lastSttDiagnostics.stoppedBy = `${reason}:deferred`;
                micTrace('stop_applied_after_defer', {
                    reason,
                    elapsedMs: this.sttElapsedMs(),
                });
                try {
                    this.recognition.stop();
                    this.recognitionEnding = true;
                } catch (e) { /* already ending */ }
            }, waitMs);
            return false;
        }

        this.lastSttDiagnostics.stoppedBy = force ? `${reason}:forced` : reason;
        micTrace('stop_applied', { reason, force, elapsedMs });
        try {
            this.recognition.stop();
        } catch (e) {
            micTrace('stop_failed', { reason, errorName: (e && e.name) || 'Error' });
            return false;
        }
        // Same as abort: stopped is not ended, and the next turn has to wait for `onend`.
        this.recognitionEnding = true;
        return true;
    }

    /**
     * Drop the current session immediately without waiting for a transcript.
     * Used when another surface needs the microphone right now.
     */
    abortSTT(reason = 'abort') {
        this.clearPendingStop();
        if (!this.recognition) return false;
        this.lastSttDiagnostics.stoppedBy = `${reason}:aborted`;
        micTrace('abort_requested', { reason, elapsedMs: this.sttElapsedMs() });
        const wasRecognizing = this.isRecognizing;
        try {
            this.recognition.abort();
        } catch (e) {
            return false;
        }
        // `isRecognizing` goes false now because no *result* can arrive any more, but the
        // recognizer itself is not finished until `onend`. Anyone about to call `start()`
        // waits on `recognitionEnding`, not on this flag.
        this.isRecognizing = false;
        if (wasRecognizing) this.recognitionEnding = true;
        return true;
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

    // ============================================================================
    // Per-Persona Voice (Additive — does NOT modify existing speak() behavior)
    // ============================================================================

    /**
     * Speak using an explicit voiceURI + optional overrides WITHOUT
     * modifying the global voiceConfig. This enables per-persona voices
     * for Teams meetings while keeping the existing global voice intact.
     *
     * @param {string} text - Text to speak
     * @param {string} voiceURI - Explicit voiceURI to use (fallback to current selected)
     * @param {Object} overrides - Optional { rate, pitch, volume } overrides
     * @param {Object} callbacks - Event callbacks { onStart, onEnd, onError, onProgress }
     * @returns {Promise<boolean>} - Whether speaking completed successfully
     */
    speakWithVoice(text, voiceURI, overrides = {}, callbacks = {}) {
        return new Promise((resolve) => {
            if (!this.isSynthesisSupported || !this.voiceConfig.enabled) {
                resolve(false);
                return;
            }

            this.stopSpeaking();

            const utterance = new SpeechSynthesisUtterance(text);

            // Choose voice by explicit voiceURI, fallback to current selected
            const voices = this.getVoices();
            const explicit = voiceURI ? voices.find(v => v.voiceURI === voiceURI) : null;
            const voice = explicit || this.getSelectedVoice();

            if (voice) {
                utterance.voice = voice;
                utterance.lang = voice.lang || 'en-US';
            } else {
                utterance.lang = 'en-US';
            }

            // Use current config as base, apply overrides without persisting
            utterance.rate = overrides.rate ?? this.voiceConfig.rate ?? 1.0;
            utterance.pitch = overrides.pitch ?? this.voiceConfig.pitch ?? 1.0;
            utterance.volume = overrides.volume ?? this.voiceConfig.volume ?? 1.0;

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

            utterance.onboundary = (event) => {
                if (callbacks.onProgress) {
                    callbacks.onProgress({
                        charIndex: event.charIndex,
                        charLength: event.charLength || 0,
                        name: event.name,
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
     * Convenience wrapper: speak using a config object.
     * Useful for per-persona voice configurations stored in localStorage.
     *
     * @param {string} text - Text to speak
     * @param {Object} cfg - Voice config { voiceURI, rate, pitch, volume }
     * @param {Object} callbacks - Event callbacks
     * @returns {Promise<boolean>}
     */
    speakWithConfig(text, cfg = {}, callbacks = {}) {
        return this.speakWithVoice(text, cfg.voiceURI || "", cfg, callbacks);
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
speechService.STT_MIN_LISTEN_MS = STT_MIN_LISTEN_MS;
speechService.STT_NO_SPEECH_GRACE_MS = STT_NO_SPEECH_GRACE_MS;
speechService.STT_MAX_LISTEN_MS = STT_MAX_LISTEN_MS;
speechService.RECOGNITION_END_TIMEOUT_MS = RECOGNITION_END_TIMEOUT_MS;
window.SpeechService = speechService;
