/**
 * Web Speech API provider — the default, always-on plugin.
 *
 * Wraps ``window.speechSynthesis`` so the existing "System Voice" path
 * (Google US English / 22 system voices available) stays working
 * exactly as before. No behavior change for users on the default.
 *
 * Capabilities: rate + pitch + voices supported, blobs NOT supported.
 * (The Web Speech API does not expose synthesized audio as a Blob —
 * use the Piper provider for the Creator Studio export pipeline.)
 */
import { register } from '../../core/registry';
const ID = 'web-speech-api';
function _voicesNative() {
    if (typeof window === 'undefined' || !('speechSynthesis' in window))
        return [];
    try {
        return window.speechSynthesis.getVoices() || [];
    }
    catch {
        return [];
    }
}
function _toTtsVoice(v) {
    return {
        id: v.voiceURI || v.name,
        name: v.name + (v.localService ? '' : ' (network)'),
        lang: v.lang || '',
    };
}
const WebSpeechProvider = {
    id: ID,
    displayName: 'System Voice (Web Speech API, built-in)',
    capabilities: {
        rate: true,
        pitch: true,
        voices: true,
        blobs: false, // Web Speech has no exportable audio
    },
    isAvailable() {
        return typeof window !== 'undefined' && 'speechSynthesis' in window;
    },
    async init() {
        // Voices populate asynchronously in Chromium. Trigger a load and
        // wait for the onvoiceschanged event, but never block longer than
        // 1 s — a cold cache with 0 voices is still a valid state.
        if (!this.isAvailable())
            return;
        const syn = window.speechSynthesis;
        if (syn.getVoices().length > 0)
            return;
        await new Promise((resolve) => {
            let settled = false;
            const done = () => {
                if (settled)
                    return;
                settled = true;
                resolve();
            };
            const prev = syn.onvoiceschanged;
            syn.onvoiceschanged = () => {
                try {
                    prev?.call(syn, new Event('voiceschanged'));
                }
                catch { }
                done();
            };
            window.setTimeout(done, 1000);
        });
    },
    async listVoices() {
        return _voicesNative().map(_toTtsVoice);
    },
    async speak(text, opts = {}) {
        if (!this.isAvailable())
            throw new Error('Web Speech API not available');
        const syn = window.speechSynthesis;
        // Stop anything in-flight from this engine before starting a new
        // utterance — matches the behavior SpeechSynthesisUtterance expects.
        try {
            syn.cancel();
        }
        catch { }
        const utter = new SpeechSynthesisUtterance(text);
        if (typeof opts.rate === 'number') {
            // speechSynthesis caps rate at 0.1–10; pick a sensible 0.25–4 to
            // match the Piper provider so the UI slider has a single range.
            utter.rate = Math.max(0.25, Math.min(4, opts.rate));
        }
        if (typeof opts.pitch === 'number') {
            utter.pitch = Math.max(0, Math.min(2, opts.pitch));
        }
        if (opts.voiceId) {
            const voice = _voicesNative().find((v) => v.voiceURI === opts.voiceId || v.name === opts.voiceId);
            if (voice)
                utter.voice = voice;
        }
        return new Promise((resolve, reject) => {
            utter.onstart = () => { try {
                opts.onStart?.();
            }
            catch { } };
            utter.onend = () => {
                try {
                    opts.onEnd?.();
                }
                catch { }
                resolve();
            };
            utter.onerror = (ev) => {
                const err = new Error(`speechSynthesis error: ${ev.error || 'unknown'}`);
                try {
                    opts.onError?.(err);
                }
                catch { }
                reject(err);
            };
            syn.speak(utter);
        });
    },
    stop() {
        if (this.isAvailable()) {
            try {
                window.speechSynthesis.cancel();
            }
            catch { }
        }
    },
    getSettingsSchema() {
        // Options list is populated at render time by SettingsPanel because
        // it depends on the async speechSynthesis voice list; we provide a
        // placeholder default so the panel can merge live options in.
        return [
            {
                kind: 'select',
                key: 'voiceId',
                label: 'System Voice',
                description: 'Browser-installed voices. Quality and language depend on the OS.',
                options: [{ value: '', label: 'System Default' }],
                defaultValue: '',
            },
            {
                kind: 'range',
                key: 'rate',
                label: 'Rate',
                min: 0.5,
                max: 2.0,
                step: 0.05,
                defaultValue: 1.0,
            },
            {
                kind: 'range',
                key: 'pitch',
                label: 'Pitch',
                min: 0.5,
                max: 2.0,
                step: 0.05,
                defaultValue: 1.0,
            },
        ];
    },
};
register(WebSpeechProvider);
export default WebSpeechProvider;
