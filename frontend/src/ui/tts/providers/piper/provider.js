/**
 * Piper WASM provider — offline, in-browser Text-to-Speech plugin.
 *
 * Lazy-loads the @mintplex-labs/piper-tts-web runtime from jsDelivr on
 * first use (no npm dep, no WASM in the bundle). Models are fetched
 * from the upstream HuggingFace `rhasspy/piper-voices` catalog and
 * cached in OPFS; if the upstream fetch fails we retry once against
 * the HomePilot mirror (`ruslanmv/hp-piper-voices`).
 *
 * Capabilities: rate + voices + blobs supported.
 * Pitch is reported as NOT supported — the Piper runtime does not
 * expose a pitch knob; downstream code (e.g. the export renderer)
 * applies pitch shifts via ffmpeg instead.
 */
import { register } from '../../core/registry';
import { DEFAULT_PIPER_VOICE_ID, PIPER_VOICES, } from '../../piperVoices';
import { getSelectedVoiceId, isSupported as piperSupported, setSelectedVoiceId, speak as piperSpeak, stop as piperStop, synthesizeToBlob as piperSynthesize, } from '../../piperTts';
import { getFallbackBaseUrl, isNetworkyError } from './mirror';
const ID = 'piper-wasm';
async function _withMirrorFallback(first, retry) {
    try {
        return await first();
    }
    catch (err) {
        if (!isNetworkyError(err))
            throw err;
        // Upstream looked network-unhealthy; try the mirror once. If the
        // mirror also fails, throw the mirror's error since it's the most
        // recent (and most likely informative) failure.
        return retry(getFallbackBaseUrl());
    }
}
const PiperProvider = {
    id: ID,
    displayName: 'Piper (offline, no API key)',
    capabilities: {
        rate: true,
        pitch: false, // applied downstream (ffmpeg) rather than in-engine
        voices: true,
        blobs: true,
    },
    isAvailable() {
        return piperSupported();
    },
    async init() {
        // Intentionally do nothing: the adapter lazy-loads on first use.
        // Eagerly loading the CDN module on app start would push work
        // users who never touch voice features still have to pay for.
    },
    async listVoices() {
        return PIPER_VOICES.map((v) => ({
            id: v.id,
            name: v.name,
            lang: v.lang,
            gender: v.gender,
            quality: v.quality,
        }));
    },
    async speak(text, opts = {}) {
        const voiceId = opts.voiceId || getSelectedVoiceId();
        if (opts.voiceId)
            setSelectedVoiceId(opts.voiceId);
        // speak() plays through the speakers; the mirror fallback still
        // helps here because the underlying predict() call downloads the
        // voice model the first time.
        await _withMirrorFallback(() => piperSpeak(text, { voiceId, rate: opts.rate, onEnd: opts.onEnd, onError: opts.onError }), async (baseUrl) => {
            // synthesizeToBlob supports baseUrl; we re-use it for the retry
            // path so the mirror URL actually flows down into the library.
            const blob = await piperSynthesize(text, { voiceId, baseUrl });
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
            const source = ctx.createBufferSource();
            source.buffer = buf;
            if (typeof opts.rate === 'number') {
                source.playbackRate.value = Math.max(0.25, Math.min(4, opts.rate));
            }
            source.connect(ctx.destination);
            await new Promise((resolve) => {
                source.onended = () => {
                    try {
                        opts.onEnd?.();
                    }
                    catch { }
                    resolve();
                };
                source.start(0);
            });
        });
    },
    async synthesizeToBlob(text, opts = {}) {
        const voiceId = opts.voiceId || getSelectedVoiceId();
        return _withMirrorFallback(() => piperSynthesize(text, { voiceId }), (baseUrl) => piperSynthesize(text, { voiceId, baseUrl }));
    },
    stop() {
        piperStop();
    },
    getSettingsSchema() {
        return [
            {
                kind: 'select',
                key: 'voiceId',
                label: 'Piper voice',
                description: 'Voice model fetched from HuggingFace on first use (~20 MB) and cached in OPFS.',
                options: PIPER_VOICES.map((v) => ({
                    value: v.id,
                    label: `${v.name} — ${v.lang} · ${v.gender} · ${v.quality}`,
                })),
                defaultValue: DEFAULT_PIPER_VOICE_ID,
            },
            {
                kind: 'range',
                key: 'rate',
                label: 'Rate',
                description: 'Playback speed 0.5–2.0. Applied post-synthesis.',
                min: 0.5,
                max: 2.0,
                step: 0.05,
                defaultValue: 0.9,
            },
            // No "pitch" field — capabilities.pitch is false. The export
            // pipeline applies pitch shifts via ffmpeg when needed.
        ];
    },
};
register(PiperProvider);
export default PiperProvider;
