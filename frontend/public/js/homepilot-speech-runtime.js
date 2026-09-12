/*
 * HomePilot speech runtime bridge.
 *
 * Why this exists:
 *   Browser SpeechRecognition does not accept a MediaStream or deviceId. HomePilot's VAD can
 *   therefore hear the microphone selected in Settings while Web Speech silently listens to a
 *   different OS/browser default device. The visible symptom is exactly:
 *     VAD speech_detected -> SpeechRecognition onstart -> onend with no result.
 *
 * This bridge keeps the SpeechRecognition-shaped API used by both Chat and Voice, but when the
 * HomePilot STT backend is available it records the selected Settings microphone with
 * MediaRecorder and transcribes that exact audio through /v1/voice/transcribe. Native Web Speech
 * remains a fallback when HomePilot STT is unavailable.
 *
 * The file also patches the shared SpeechService TTS instance after it loads so Settings and
 * Voice exercise the same runtime path and emit useful start/end/error diagnostics.
 */
(function () {
  'use strict';

  const NativeSpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  const MAX_DEBUG_ENTRIES = 200;
  const PREFS_KEY = 'homepilot_media_preferences_v1';
  const STATUS_TTL_MS = 5000;
  let cachedStatus = null;
  let cachedStatusAt = 0;

  function debug(scope, event, details) {
    const history = window.__HOMEPILOT_MIC_DEBUG__ || [];
    const lastSeq = history.length ? Number(history[history.length - 1].seq || 0) : 0;
    const entry = {
      seq: lastSeq + 1,
      at: new Date().toISOString(),
      scope,
      event,
      details: details || {},
    };
    history.push(entry);
    if (history.length > MAX_DEBUG_ENTRIES) {
      history.splice(0, history.length - MAX_DEBUG_ENTRIES);
    }
    window.__HOMEPILOT_MIC_DEBUG__ = history;
    try {
      window.dispatchEvent(new CustomEvent('homepilot:microphone-debug', { detail: entry }));
    } catch (_) {}
    console.info(`[HomePilot:Mic][${scope}] ${event}`, entry.details);
    return entry;
  }

  function debugError(scope, event, error, details) {
    const payload = Object.assign({}, details || {}, {
      errorName: error && error.name ? error.name : 'Error',
      errorMessage: error && error.message ? error.message : String(error || 'Unknown error'),
    });
    debug(scope, event, payload);
    console.error(`[HomePilot:Mic][${scope}] ${event}`, payload);
  }

  function ttsDebug(event, details) {
    console.info(`[HomePilot:TTS] ${event}`, details || {});
  }

  function getPreferences() {
    const defaults = {
      microphoneDeviceId: '',
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    };
    try {
      const raw = localStorage.getItem(PREFS_KEY);
      if (!raw) return defaults;
      return Object.assign({}, defaults, JSON.parse(raw));
    } catch (_) {
      return defaults;
    }
  }

  function audioConstraints(preferences) {
    const audio = {
      echoCancellation: preferences.echoCancellation !== false,
      noiseSuppression: preferences.noiseSuppression !== false,
      autoGainControl: preferences.autoGainControl !== false,
    };
    if (preferences.microphoneDeviceId) {
      audio.deviceId = { exact: preferences.microphoneDeviceId };
    }
    return audio;
  }

  function chooseMimeType() {
    if (typeof MediaRecorder === 'undefined') return '';
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/ogg',
    ];
    for (const candidate of candidates) {
      try {
        if (!MediaRecorder.isTypeSupported || MediaRecorder.isTypeSupported(candidate)) return candidate;
      } catch (_) {}
    }
    return '';
  }

  function formatForMime(mime) {
    const normalized = String(mime || '').toLowerCase();
    if (normalized.includes('ogg')) return 'ogg';
    if (normalized.includes('wav')) return 'wav';
    if (normalized.includes('mp4') || normalized.includes('m4a')) return 'mp4';
    return 'webm';
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    let binary = '';
    for (let i = 0; i < bytes.length; i += chunkSize) {
      const chunk = bytes.subarray(i, Math.min(i + chunkSize, bytes.length));
      binary += String.fromCharCode.apply(null, Array.from(chunk));
    }
    return btoa(binary);
  }

  async function getSttStatus(force) {
    if (!force && cachedStatus && Date.now() - cachedStatusAt < STATUS_TTL_MS) return cachedStatus;
    try {
      const response = await fetch('/v1/voice/stt/status', { cache: 'no-store' });
      if (!response.ok) throw new Error(`STT status HTTP ${response.status}`);
      const data = await response.json();
      cachedStatus = {
        available: Boolean(data && data.available),
        provider: (data && data.provider) || 'unknown',
      };
    } catch (error) {
      cachedStatus = { available: false, provider: 'unreachable', error: String(error && error.message || error) };
    }
    cachedStatusAt = Date.now();
    return cachedStatus;
  }

  async function transcribeBlob(blob, scope, traceId) {
    const startedAt = performance.now();
    const buffer = await blob.arrayBuffer();
    if (!buffer.byteLength) throw new Error('Recorded audio was empty');
    const format = formatForMime(blob.type);
    debug(scope, 'stt_upload_start', {
      traceId,
      bytes: buffer.byteLength,
      mimeType: blob.type || 'unknown',
      format,
    });
    const response = await fetch('/v1/voice/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        format,
        data_b64: arrayBufferToBase64(buffer),
      }),
    });
    let data = null;
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      const detail = data && data.detail ? data.detail : `HTTP ${response.status}`;
      throw new Error(detail);
    }
    const text = String(data && data.text || '').trim();
    debug(scope, 'stt_upload_complete', {
      traceId,
      provider: data && data.provider || 'unknown',
      transcriptChars: text.length,
      elapsedMs: Math.round(performance.now() - startedAt),
    });
    return {
      text,
      provider: data && data.provider || 'unknown',
      audioBytes: data && data.audio_bytes || buffer.byteLength,
    };
  }

  function makeResultEvent(text) {
    const alternative = { transcript: text, confidence: 1 };
    const result = [alternative];
    result.isFinal = true;
    result.item = function (index) { return this[index] || null; };
    const results = [result];
    results.item = function (index) { return this[index] || null; };
    return { resultIndex: 0, results };
  }

  function inferScope() {
    try {
      const stack = String(new Error().stack || '');
      if (stack.includes('speech-service.js')) return 'speech-service';
    } catch (_) {}
    return 'chat';
  }

  class HomePilotSpeechRecognition extends EventTarget {
    constructor() {
      super();
      this.continuous = false;
      this.interimResults = false;
      this.lang = 'en-US';
      this.maxAlternatives = 1;
      this.onstart = null;
      this.onend = null;
      this.onerror = null;
      this.onresult = null;
      this.onspeechstart = null;
      this.onspeechend = null;
      this._scope = inferScope();
      this._traceId = null;
      this._mode = null;
      this._native = null;
      this._stream = null;
      this._recorder = null;
      this._chunks = [];
      this._starting = false;
      this._active = false;
      this._stopRequested = false;
      this._aborted = false;
    }

    _emit(name, event) {
      const handler = this[`on${name}`];
      if (typeof handler === 'function') {
        try { handler.call(this, event || new Event(name)); } catch (error) { console.error(error); }
      }
      try { this.dispatchEvent(event instanceof Event ? event : new Event(name)); } catch (_) {}
    }

    _emitError(code, error) {
      const ev = new Event('error');
      try {
        Object.defineProperty(ev, 'error', { value: code, enumerable: true });
        Object.defineProperty(ev, 'message', { value: error && error.message || String(error || code), enumerable: true });
      } catch (_) {
        ev.error = code;
        ev.message = error && error.message || String(error || code);
      }
      this._emit('error', ev);
    }

    start() {
      if (this._starting || this._active) {
        const err = new Error('Speech recognition has already started');
        err.name = 'InvalidStateError';
        throw err;
      }
      this._traceId = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      this._starting = true;
      this._stopRequested = false;
      this._aborted = false;
      debug(this._scope, 'recognition_start_requested', {
        traceId: this._traceId,
        language: this.lang,
        engine: 'homepilot-stt-preferred',
      });
      void this._begin();
    }

    async _begin() {
      const status = await getSttStatus(false);
      if (!status.available || typeof MediaRecorder === 'undefined' || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this._starting = false;
        this._startNative(status.available ? 'media-recorder-unavailable' : `backend-stt-unavailable:${status.provider}`);
        return;
      }

      const preferences = getPreferences();
      const constraints = audioConstraints(preferences);
      this._mode = 'backend';
      debug(this._scope, 'capture_request', {
        traceId: this._traceId,
        selectedDeviceId: preferences.microphoneDeviceId || 'system-default',
        constraints,
        sttProvider: status.provider,
      });

      try {
        this._stream = await navigator.mediaDevices.getUserMedia({ audio: constraints, video: false });
        if (this._aborted) {
          this._cleanupStream();
          this._starting = false;
          this._finishEnd();
          return;
        }
        const track = this._stream.getAudioTracks()[0];
        if (!track) throw new Error('No microphone audio track was returned');
        const settings = track.getSettings ? track.getSettings() : {};
        debug(this._scope, 'capture_opened', {
          traceId: this._traceId,
          label: track.label || 'unlabelled microphone',
          readyState: track.readyState,
          deviceId: settings.deviceId || 'browser-default',
          sampleRate: settings.sampleRate,
          channelCount: settings.channelCount,
          echoCancellation: settings.echoCancellation,
          noiseSuppression: settings.noiseSuppression,
          autoGainControl: settings.autoGainControl,
        });
        track.addEventListener('mute', () => debug(this._scope, 'track_muted', { traceId: this._traceId }));
        track.addEventListener('unmute', () => debug(this._scope, 'track_unmuted', { traceId: this._traceId }));
        track.addEventListener('ended', () => debug(this._scope, 'track_ended', { traceId: this._traceId }));

        const mimeType = chooseMimeType();
        this._chunks = [];
        this._recorder = mimeType ? new MediaRecorder(this._stream, { mimeType }) : new MediaRecorder(this._stream);
        this._recorder.ondataavailable = (event) => {
          if (event.data && event.data.size > 0) this._chunks.push(event.data);
        };
        this._recorder.onerror = (event) => {
          const error = event && event.error ? event.error : new Error('MediaRecorder failed');
          debugError(this._scope, 'media_recorder_error', error, { traceId: this._traceId });
          this._emitError('audio-capture', error);
        };
        this._recorder.onstop = () => { void this._finalizeBackendRecording(); };
        this._recorder.start(250);
        this._starting = false;
        this._active = true;
        debug(this._scope, 'media_recorder_started', {
          traceId: this._traceId,
          mimeType: this._recorder.mimeType || mimeType || 'browser-default',
        });
        this._emit('start', new Event('start'));
        if (this._stopRequested) this.stop();
      } catch (error) {
        this._starting = false;
        this._active = false;
        this._cleanupStream();
        debugError(this._scope, 'capture_start_failed', error, { traceId: this._traceId });
        this._emitError(error && error.name === 'NotAllowedError' ? 'not-allowed' : 'audio-capture', error);
        this._finishEnd();
      }
    }

    _startNative(reason) {
      if (!NativeSpeechRecognition) {
        const error = new Error('No speech recognition engine is available');
        debugError(this._scope, 'native_fallback_unavailable', error, { traceId: this._traceId, reason });
        this._emitError('not-supported', error);
        this._finishEnd();
        return;
      }
      this._mode = 'native';
      debug(this._scope, 'native_web_speech_fallback', {
        traceId: this._traceId,
        reason,
        microphone: 'browser-managed-default',
      });
      const native = new NativeSpeechRecognition();
      this._native = native;
      native.continuous = this.continuous;
      native.interimResults = this.interimResults;
      native.lang = this.lang;
      native.maxAlternatives = this.maxAlternatives;
      native.onstart = (event) => {
        this._active = true;
        debug(this._scope, 'native_onstart', { traceId: this._traceId });
        this._emit('start', event);
        if (this._stopRequested) this.stop();
      };
      native.onresult = (event) => {
        let finalChars = 0;
        try {
          for (let i = event.resultIndex; i < event.results.length; i++) {
            if (event.results[i].isFinal) finalChars += String(event.results[i][0].transcript || '').length;
          }
        } catch (_) {}
        debug(this._scope, 'native_onresult', { traceId: this._traceId, finalChars });
        if (typeof this.onresult === 'function') this.onresult.call(this, event);
      };
      native.onerror = (event) => {
        debug(this._scope, 'native_onerror', { traceId: this._traceId, error: event && event.error || 'unknown' });
        if (typeof this.onerror === 'function') this.onerror.call(this, event);
      };
      native.onend = (event) => {
        this._active = false;
        this._native = null;
        debug(this._scope, 'native_onend', { traceId: this._traceId });
        if (typeof this.onend === 'function') this.onend.call(this, event);
      };
      try {
        native.start();
      } catch (error) {
        debugError(this._scope, 'native_start_failed', error, { traceId: this._traceId });
        this._emitError('audio-capture', error);
        this._finishEnd();
      }
    }

    stop() {
      this._stopRequested = true;
      debug(this._scope, 'recognition_stop_requested', { traceId: this._traceId, mode: this._mode });
      if (this._mode === 'native' && this._native) {
        try { this._native.stop(); } catch (_) {}
        return;
      }
      if (this._recorder && this._recorder.state !== 'inactive') {
        try { this._recorder.stop(); } catch (error) {
          debugError(this._scope, 'media_recorder_stop_failed', error, { traceId: this._traceId });
        }
      }
    }

    abort() {
      this._aborted = true;
      debug(this._scope, 'recognition_abort_requested', { traceId: this._traceId, mode: this._mode });
      if (this._mode === 'native' && this._native) {
        try { this._native.abort(); } catch (_) {}
        return;
      }
      if (this._recorder && this._recorder.state !== 'inactive') {
        this._recorder.onstop = () => {
          this._cleanupStream();
          this._finishEnd();
        };
        try { this._recorder.stop(); } catch (_) { this._finishEnd(); }
      } else if (!this._starting) {
        this._cleanupStream();
        this._finishEnd();
      }
    }

    async _finalizeBackendRecording() {
      const mimeType = this._recorder && this._recorder.mimeType || chooseMimeType() || 'audio/webm';
      const blob = new Blob(this._chunks, { type: mimeType });
      this._active = false;
      this._cleanupStream();
      debug(this._scope, 'media_recorder_stopped', {
        traceId: this._traceId,
        bytes: blob.size,
        mimeType: blob.type,
      });
      if (this._aborted) {
        this._finishEnd();
        return;
      }
      try {
        const result = await transcribeBlob(blob, this._scope, this._traceId);
        if (result.text) {
          debug(this._scope, 'transcript_ready', {
            traceId: this._traceId,
            provider: result.provider,
            transcriptChars: result.text.length,
          });
          if (typeof this.onresult === 'function') {
            this.onresult.call(this, makeResultEvent(result.text));
          }
        } else {
          debug(this._scope, 'no_speech_detected', { traceId: this._traceId, provider: result.provider });
          this._emitError('no-speech', new Error('No speech detected'));
        }
      } catch (error) {
        debugError(this._scope, 'transcription_failed', error, { traceId: this._traceId });
        this._emitError('network', error);
      } finally {
        this._finishEnd();
      }
    }

    _cleanupStream() {
      if (this._stream) {
        for (const track of this._stream.getTracks()) {
          try { track.stop(); } catch (_) {}
        }
      }
      this._stream = null;
      this._recorder = null;
      this._chunks = [];
      debug(this._scope, 'capture_cleanup_complete', { traceId: this._traceId });
    }

    _finishEnd() {
      this._starting = false;
      this._active = false;
      const event = new Event('end');
      if (typeof this.onend === 'function') {
        try { this.onend.call(this, event); } catch (error) { console.error(error); }
      }
      debug(this._scope, 'recognition_end', { traceId: this._traceId, mode: this._mode });
    }
  }

  // Prefer HomePilot-selected-mic STT for every existing SpeechRecognition consumer. The native
  // constructor is retained above and used transparently when the backend STT provider is absent.
  try {
    window.SpeechRecognition = HomePilotSpeechRecognition;
    window.webkitSpeechRecognition = HomePilotSpeechRecognition;
  } catch (error) {
    console.warn('[HomePilot:Mic] Could not install SpeechRecognition bridge; native Web Speech remains active.', error);
  }

  window.hpSpeechRuntime = {
    getSttStatus,
    transcribeBlob: function (blob, scope) {
      const traceId = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      return transcribeBlob(blob, scope || 'settings', traceId);
    },
    nativeSpeechRecognitionAvailable: Boolean(NativeSpeechRecognition),
  };

  function patchSpeechService() {
    const svc = window.SpeechService;
    if (!svc || svc.__homepilotRuntimePatched) return false;
    svc.__homepilotRuntimePatched = true;

    const originalGetSelectedVoice = typeof svc.getSelectedVoice === 'function'
      ? svc.getSelectedVoice.bind(svc)
      : null;
    if (originalGetSelectedVoice) {
      svc.getSelectedVoice = function () {
        try {
          const stored = localStorage.getItem('homepilot_voice_uri');
          if (stored !== null) this.voiceConfig.voiceURI = stored;
        } catch (_) {}
        const voices = this.getVoices ? this.getVoices() : [];
        const wanted = String(this.voiceConfig && this.voiceConfig.voiceURI || '');
        if (wanted && voices && voices.length) {
          const exact = voices.find((voice) => voice.voiceURI === wanted || voice.name === wanted);
          if (exact) return exact;
        }
        return originalGetSelectedVoice();
      };
    }

    const originalSpeak = typeof svc.speak === 'function' ? svc.speak.bind(svc) : null;
    if (originalSpeak) {
      svc.speak = function (text, callbacks) {
        try {
          const enabled = localStorage.getItem('homepilot_tts_enabled');
          if (enabled !== null) this.voiceConfig.enabled = enabled !== 'false';
          const storedVoice = localStorage.getItem('homepilot_voice_uri');
          if (storedVoice !== null) this.voiceConfig.voiceURI = storedVoice;
        } catch (_) {}
        const userCallbacks = callbacks || {};
        const startedAt = performance.now();
        ttsDebug('speak_requested', {
          chars: String(text || '').length,
          enabled: Boolean(this.voiceConfig && this.voiceConfig.enabled),
          voiceURI: this.voiceConfig && this.voiceConfig.voiceURI || 'system-default',
          rate: this.voiceConfig && this.voiceConfig.rate,
          pitch: this.voiceConfig && this.voiceConfig.pitch,
        });
        return originalSpeak(text, {
          ...userCallbacks,
          onStart: () => {
            ttsDebug('speak_started', { elapsedMs: Math.round(performance.now() - startedAt) });
            try { userCallbacks.onStart && userCallbacks.onStart(); } catch (_) {}
          },
          onEnd: () => {
            ttsDebug('speak_completed', { elapsedMs: Math.round(performance.now() - startedAt) });
            try { userCallbacks.onEnd && userCallbacks.onEnd(); } catch (_) {}
          },
          onError: (error) => {
            ttsDebug('speak_error', { error: String(error && error.message || error || 'unknown') });
            try { userCallbacks.onError && userCallbacks.onError(error); } catch (_) {}
          },
          onProgress: userCallbacks.onProgress,
        }).then((success) => {
          if (!success) ttsDebug('speak_not_started', { enabled: Boolean(this.voiceConfig && this.voiceConfig.enabled) });
          return success;
        });
      };
    }

    ttsDebug('runtime_patched', {
      synthesisSupported: Boolean(svc.isSynthesisSupported),
      voices: svc.getVoices ? svc.getVoices().length : 0,
    });
    return true;
  }

  // speech-service.js is the next synchronous script in index.html. A timer runs after parser
  // scripts, and load is a second safety net for slow browser startup.
  setTimeout(patchSpeechService, 0);
  window.addEventListener('load', patchSpeechService, { once: true });
})();
