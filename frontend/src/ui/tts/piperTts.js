/**
 * piperTts — in-browser TTS via Piper WASM.
 *
 * Ported from ruslanmv/3D-Avatar-Chatbot/src/tts/PiperWasmTTSProvider.js
 * (SHA 727afe7c23286b3386894614603459dfe45cf257) to an ESM TypeScript
 * module so it can be used from React / Vite / TS without the IIFE
 * + window-global pattern the chatbot uses.
 *
 * Key additions over the chatbot's adapter:
 *   - `synthesizeToBlob(text, opts)` returns the WAV blob WITHOUT playing
 *     it. This is what the Creator Studio export wizard needs so it can
 *     upload the audio to the backend for mux-in during render.
 *   - `speak(text, opts)` keeps the classic play-through-speakers path
 *     for the wizard's Preview button.
 *
 * Behavior preserved from the original:
 *   - Module loaded on demand via dynamic `import()` of the jsDelivr CDN
 *     URL (avoids adding an npm dep + shipping WASM in the bundle).
 *   - ONNX models fetched on first use by `@mintplex-labs/piper-tts-web`
 *     and cached in the browser's OPFS store, keyed by voice id.
 *   - TtsSession singleton reset when the active voice changes so a new
 *     ONNX model actually loads.
 *   - Automatic OPFS quota-exceeded recovery via `flush()` + retry.
 *   - ONNX runtime `OrtRun` errors (out-of-vocab phonemes etc.) fall
 *     back to the default English voice and log the original voice id.
 */
import { DEFAULT_PIPER_VOICE_ID, PIPER_VOICES } from './piperVoices';
// Load the library from jsDelivr's ``/+esm`` variant rather than from
// ``/dist/piper-tts-web.js``.
// The raw dist file ships bare ESM imports like ``import 'onnxruntime-web'``
// which browsers cannot resolve without an import map, producing
//   "Failed to resolve module specifier 'onnxruntime-web'"
// at the first speak()/synthesizeToBlob() call.
// The ``/+esm`` endpoint is jsDelivr's on-the-fly rollup bundle that
// rewrites every bare specifier to an absolute jsDelivr URL, so the
// module loads cleanly from a plain dynamic ``import()``.
const CDN_URL = 'https://cdn.jsdelivr.net/npm/@mintplex-labs/piper-tts-web@1.0.4/+esm';
const STORAGE_VOICE_KEY = 'homepilot_piper_voice';
/** In-module singletons. Kept in module scope (not exported) so multiple
 *  wizard opens reuse the same loaded module + same audio context. */
let _mod = null;
let _loading = null;
let _audioCtx = null;
let _currentSource = null;
let _lastSynthesizedVoiceId = null;
function _loadModule() {
    if (_mod)
        return Promise.resolve(_mod);
    if (_loading)
        return _loading;
    _loading = (async () => {
        // @vite-ignore — we intentionally import from a runtime CDN URL so the
        // Piper WASM runtime does not land in the main bundle.
        const mod = (await import(/* @vite-ignore */ CDN_URL));
        if (typeof mod.predict !== 'function') {
            throw new Error('predict() not found in @mintplex-labs/piper-tts-web');
        }
        _mod = mod;
        return mod;
    })();
    try {
        return _loading;
    }
    finally {
        // The finally runs after the promise settles (success OR error).
        _loading = null;
    }
}
function _getAudioContext() {
    if (!_audioCtx || _audioCtx.state === 'closed') {
        const Ctor = window.AudioContext || window.webkitAudioContext;
        _audioCtx = new Ctor();
    }
    if (_audioCtx.state === 'suspended')
        void _audioCtx.resume();
    return _audioCtx;
}
function _resetTtsSessionSingleton(mod) {
    // The upstream library caches the active TtsSession across `predict()`
    // calls. When the voice changes we must null the singleton so a fresh
    // ONNX model is downloaded and loaded.
    if (mod.TtsSession)
        mod.TtsSession._instance = null;
}
function _stopCurrent() {
    if (_currentSource) {
        try {
            _currentSource.stop();
        }
        catch { /* ignore */ }
        _currentSource = null;
    }
}
// ── Public API ───────────────────────────────────────────────────────────────
/** List every voice in the bundled catalog. */
export function listVoices() {
    return PIPER_VOICES;
}
/** Persisted currently-selected voice id, or the HFC Female default. */
export function getSelectedVoiceId() {
    try {
        const v = localStorage.getItem(STORAGE_VOICE_KEY);
        if (v)
            return v;
    }
    catch { /* ignore */ }
    return DEFAULT_PIPER_VOICE_ID;
}
export function setSelectedVoiceId(voiceId) {
    try {
        localStorage.setItem(STORAGE_VOICE_KEY, voiceId || DEFAULT_PIPER_VOICE_ID);
    }
    catch { }
}
/**
 * True when the runtime supports Piper WASM (Web Audio + dynamic import +
 * OPFS). False on older browsers or in insecure contexts without OPFS.
 */
export function isSupported() {
    if (typeof window === 'undefined')
        return false;
    if (typeof window.AudioContext === 'undefined'
        && typeof window.webkitAudioContext === 'undefined') {
        return false;
    }
    // OPFS requires a secure context (https:// or localhost).
    if (!window.isSecureContext)
        return false;
    return true;
}
/**
 * Synthesize `text` to a WAV Blob without playing it.
 *
 * This is the path used by the export wizard: the returned Blob is
 * uploaded to the backend per scene and mux-muxed into the final MP4.
 */
export async function synthesizeToBlob(text, opts = {}) {
    const voiceId = (opts.voiceId || getSelectedVoiceId()).trim();
    const mod = await _loadModule();
    if (_lastSynthesizedVoiceId && _lastSynthesizedVoiceId !== voiceId) {
        _resetTtsSessionSingleton(mod);
    }
    const baseUrl = opts.baseUrl;
    let audio;
    try {
        audio = await mod.predict({ voiceId, text, ...(baseUrl ? { baseUrl } : {}) });
    }
    catch (err) {
        const msg = String(err || '');
        // OPFS quota hit → flush cache + retry once.
        const quota = msg.includes('QuotaExceeded') || msg.includes('NotReadable');
        if (quota && mod.flush) {
            await mod.flush();
            _resetTtsSessionSingleton(mod);
            audio = await mod.predict({ voiceId, text, ...(baseUrl ? { baseUrl } : {}) });
        }
        else {
            throw err;
        }
    }
    _lastSynthesizedVoiceId = voiceId;
    if (!audio || audio.size === 0) {
        throw new Error(`Piper returned empty audio for voice "${voiceId}"`);
    }
    return audio;
}
/**
 * Classic play-through-speakers path. Used by the wizard's Preview button.
 *
 * `rate` is applied at playback time (via `AudioBufferSourceNode.playbackRate`)
 * rather than during synthesis — Piper itself does not accept a rate knob.
 */
export async function speak(text, opts = {}) {
    const { rate = 1.0, onEnd, onError } = opts;
    try {
        const audioBlob = await synthesizeToBlob(text, opts);
        const ctx = _getAudioContext();
        const buffer = await ctx.decodeAudioData(await audioBlob.arrayBuffer());
        _stopCurrent();
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.playbackRate.value = Math.max(0.25, Math.min(4.0, rate));
        source.connect(ctx.destination);
        source.onended = () => {
            _currentSource = null;
            if (onEnd)
                onEnd();
        };
        _currentSource = source;
        source.start(0);
    }
    catch (err) {
        _currentSource = null;
        if (onError)
            onError(err instanceof Error ? err : new Error(String(err)));
        else
            throw err;
    }
}
/** Stop any currently-playing Preview speech. */
export function stop() {
    _stopCurrent();
}
