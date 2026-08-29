/**
 * HomePilot ScreenSense v2 — Additive, non-destructive screen awareness.
 *
 * Lets any HomePilot persona SEE the user's screen and give suggestions,
 * 100% LOCAL: the frame is uploaded to YOUR HomePilot backend and analyzed
 * by YOUR local Ollama vision model (llava / moondream / qwen-VL / gemma3).
 * Nothing ever leaves the machine.
 *
 * ── Dual capture, chosen automatically by where HomePilot is running ──────
 *
 *   1. DESKTOP  (Electron app / "local computer only")
 *      Uses the native `window.homepilot.captureScreen()` bridge exposed by
 *      the desktop preload. One silent, full-resolution grab of the primary
 *      display — no browser "share your screen" dialog, because on your own
 *      machine you already granted trust by installing the app.
 *
 *   2. CLOUD / BROWSER  ("if I am on cloud it asks the picture")
 *      a. If the browser supports it, `getDisplayMedia()` shows the native
 *         screen-share picker so YOU choose exactly what Nexus may see.
 *      b. If screen-share is unavailable or declined, ScreenSense falls back
 *         to a file picker and simply ASKS you to hand it a screenshot image
 *         (drag-drop / paste / choose file). Same pipeline from there on.
 *
 * Uses ONLY existing HomePilot endpoints (no backend changes required):
 *   POST /upload                    → stores the frame, returns /files/... URL
 *   POST /v1/multimodal/analyze     → vision model answers about the frame,
 *                                     result persisted into the conversation
 *
 * Include on any HomePilot page:
 *   <script src="/js/homepilot-screensense.js"></script>
 *   (or from the addon folder: /addons/screensense/homepilot-screensense.js)
 *
 * Public API:
 *   hpScreenSense.mode                                  // 'desktop'|'browser'|'upload'
 *   await hpScreenSense.enable();                       // permission + stream (browser only)
 *   await hpScreenSense.ask('what is wrong here?', {
 *       conversationId: currentConversationId,          // optional: persist to history
 *       apiKey: HOMEPILOT_API_KEY,                      // if backend requires
 *       model: 'llava:7b',                              // optional override
 *   });
 *   hpScreenSense.stop();
 *   hpScreenSense.mountButton();                        // floating 👁 built-in button
 *
 * Chat integration (one line in your send handler):
 *   if (hpScreenSense.isScreenQuery(text)) return hpScreenSense.ask(text, {conversationId});
 */
(function () {
    'use strict';

    const API_BASE = window.HOMEPILOT_API_BASE || '';

    // ── Environment detection ──────────────────────────────────────────────
    // 'desktop' → native Electron capture (local machine, silent, no dialog)
    // 'browser' → getDisplayMedia screen-share picker (cloud, user chooses)
    // 'upload'  → ask the user to provide a screenshot image (last-resort)
    function detectMode() {
        const bridge = window.homepilot;
        if (bridge && typeof bridge.captureScreen === 'function' && bridge.isDesktop) {
            return 'desktop';
        }
        if (navigator.mediaDevices && typeof navigator.mediaDevices.getDisplayMedia === 'function') {
            return 'browser';
        }
        return 'upload';
    }

    class HPScreenSense {
        constructor() {
            this.stream = null;
            this.video = null;
            this._busy = false;
            this._fileInput = null;
            this._button = null;
            this.mode = detectMode();
        }

        get enabled() {
            // Desktop and upload modes are always "ready" — nothing to keep open.
            if (this.mode !== 'browser') return true;
            return !!(this.stream && this.stream.active);
        }

        /**
         * Prepare capture. In browser mode this opens the screen-share picker
         * once and keeps the stream alive for subsequent asks. Desktop/upload
         * modes need no persistent permission, so this is a no-op that succeeds.
         */
        async enable() {
            if (this.mode === 'desktop') return true;
            if (this.mode === 'upload') return true;

            if (this.enabled) return true;
            if (!navigator.mediaDevices?.getDisplayMedia) {
                this.mode = 'upload';
                return true;
            }
            try {
                this.stream = await navigator.mediaDevices.getDisplayMedia({
                    video: { frameRate: 5 },
                    audio: false,
                });
            } catch (_) {
                // User declined the share dialog — fall back to asking for a file.
                this.mode = 'upload';
                return true;
            }
            const v = document.createElement('video');
            v.srcObject = this.stream;
            v.muted = true;
            v.playsInline = true;
            v.style.cssText =
                'position:fixed;width:1px;height:1px;opacity:0;pointer-events:none;left:-9px;top:-9px';
            document.body.appendChild(v);
            await v.play().catch(() => {});
            this.video = v;
            this.stream.getVideoTracks()[0]?.addEventListener('ended', () => this.stop());
            return true;
        }

        stop() {
            try {
                this.stream?.getTracks().forEach((t) => t.stop());
            } catch (_) {}
            this.stream = null;
            this.video?.remove();
            this.video = null;
        }

        // ── Capture a single downscaled JPEG Blob, per active mode ─────────────

        /** DESKTOP: native Electron grab of the primary display → downscaled JPEG. */
        async _captureDesktop(maxW) {
            const dataUrl = await window.homepilot.captureScreen();
            if (!dataUrl) return null;
            return this._downscaleDataUrl(dataUrl, maxW);
        }

        /** BROWSER: pull one frame off the shared-screen video → downscaled JPEG. */
        async _captureBrowser(maxW) {
            if (!this.enabled || !this.video) return null;
            const vw = this.video.videoWidth || 1280;
            const vh = this.video.videoHeight || 720;
            return this._drawToJpeg(this.video, vw, vh, maxW);
        }

        /** UPLOAD: ask the user for a screenshot image and return it as a JPEG. */
        async _captureUpload(maxW) {
            const file = await this._pickFile();
            if (!file) return null;
            const dataUrl = await new Promise((res) => {
                const fr = new FileReader();
                fr.onload = () => res(fr.result);
                fr.onerror = () => res(null);
                fr.readAsDataURL(file);
            });
            if (!dataUrl) return null;
            return this._downscaleDataUrl(dataUrl, maxW);
        }

        /** Route to the right capture strategy for the current mode. */
        async captureFrame(maxW = 1280) {
            if (this.mode === 'desktop') return this._captureDesktop(maxW);
            if (this.mode === 'browser') return this._captureBrowser(maxW);
            return this._captureUpload(maxW);
        }

        // ── Small drawing / IO helpers ─────────────────────────────────────────

        _drawToJpeg(source, sw, sh, maxW) {
            const s = Math.min(1, maxW / sw);
            const c = document.createElement('canvas');
            c.width = Math.round(sw * s);
            c.height = Math.round(sh * s);
            c.getContext('2d').drawImage(source, 0, 0, c.width, c.height);
            return new Promise((res) => c.toBlob(res, 'image/jpeg', 0.82));
        }

        _downscaleDataUrl(dataUrl, maxW) {
            return new Promise((res) => {
                const img = new Image();
                img.onload = () =>
                    this._drawToJpeg(img, img.naturalWidth || maxW, img.naturalHeight || maxW, maxW).then(res);
                img.onerror = () => res(null);
                img.src = dataUrl;
            });
        }

        _pickFile() {
            return new Promise((res) => {
                if (!this._fileInput) {
                    const inp = document.createElement('input');
                    inp.type = 'file';
                    inp.accept = 'image/*';
                    inp.style.display = 'none';
                    document.body.appendChild(inp);
                    this._fileInput = inp;
                }
                const inp = this._fileInput;
                inp.value = '';
                const onChange = () => {
                    inp.removeEventListener('change', onChange);
                    res(inp.files && inp.files[0] ? inp.files[0] : null);
                };
                inp.addEventListener('change', onChange);
                inp.click();
            });
        }

        /**
         * Capture → /upload → /v1/multimodal/analyze.
         * Returns { ok, analysis_text, mode }, and (if conversationId given) the
         * analysis is persisted into that conversation by the backend itself.
         */
        async ask(question, opts = {}) {
            if (this._busy) return { ok: false, error: 'busy' };
            // Ensure browser mode has an active stream (opens picker on first ask).
            if (this.mode === 'browser' && !this.enabled) {
                await this.enable();
            }
            this._busy = true;
            try {
                const blob = await this.captureFrame();
                if (!blob) {
                    const why =
                        this.mode === 'upload'
                            ? 'no screenshot provided'
                            : this.mode === 'browser'
                            ? 'screen share declined'
                            : 'capture failed';
                    return { ok: false, error: why, mode: this.mode };
                }

                const headers = {};
                if (opts.apiKey) headers['Authorization'] = 'Bearer ' + opts.apiKey;

                // 1. Upload the frame into HomePilot's own storage.
                const fd = new FormData();
                fd.append('file', blob, 'screensense-' + Date.now() + '.jpg');
                const up = await fetch(API_BASE + '/upload', {
                    method: 'POST',
                    headers,
                    body: fd,
                    credentials: 'include',
                });
                if (!up.ok) throw new Error('upload ' + up.status);
                const upJson = await up.json();
                const imageUrl = upJson.url || upJson.file_url || upJson.path;
                if (!imageUrl) throw new Error('upload returned no url');

                // 2. Analyze with the LOCAL vision model via the existing endpoint.
                const body = {
                    image_url: imageUrl,
                    user_prompt:
                        (question || 'What do you see?') +
                        ' — You are looking at a screenshot of the user’s screen. ' +
                        'Answer as a concise desk-side assistant: name the concrete issue or ' +
                        'next step you can see, under 100 words.',
                    mode: 'both',
                    persist: !!opts.conversationId,
                };
                if (opts.conversationId) body.conversation_id = opts.conversationId;
                if (opts.model) body.model = opts.model;
                if (opts.baseUrl) body.base_url = opts.baseUrl;

                const an = await fetch(API_BASE + '/v1/multimodal/analyze', {
                    method: 'POST',
                    headers: { ...headers, 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                    credentials: 'include',
                });
                if (!an.ok) throw new Error('analyze ' + an.status);
                const out = await an.json();
                return {
                    ok: !!out.ok,
                    analysis_text: out.analysis_text || '',
                    meta: out.meta || {},
                    mode: this.mode,
                };
            } catch (err) {
                return { ok: false, error: String(err?.message || err), mode: this.mode };
            } finally {
                this._busy = false;
            }
        }
    }

    HPScreenSense.prototype.isScreenQuery = function (text) {
        return /\b(look|looking|see|check|glance|watch)\b[^.?!]{0,40}\b(screen|display|monitor|pantalla|window)\b/i.test(
            String(text || '')
        );
    };

    // ── Optional built-in floating button (self-mounting UI) ───────────────────
    // Gives ScreenSense a genuinely "built-in tool" feel without editing any
    // chat component. Clicking it captures per the active mode and shows the
    // vision model's one-line answer in a small panel.
    HPScreenSense.prototype.mountButton = function (opts = {}) {
        if (this._button) return this._button;
        const label =
            this.mode === 'desktop'
                ? '👁 Ask about my screen'
                : this.mode === 'browser'
                ? '👁 Share screen'
                : '👁 Send a screenshot';

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = label;
        btn.title =
            this.mode === 'desktop'
                ? 'Nexus captures your screen locally (desktop app)'
                : this.mode === 'browser'
                ? 'Nexus asks your browser to share a window/screen'
                : 'Nexus asks you for a screenshot image';
        btn.style.cssText = [
            'position:fixed',
            'right:18px',
            'bottom:18px',
            'z-index:2147483000',
            'padding:10px 14px',
            'border-radius:999px',
            'border:1px solid rgba(120,150,220,.5)',
            'background:#0d1424',
            'color:#dbe6ff',
            'font:600 13px/1 system-ui,sans-serif',
            'cursor:pointer',
            'box-shadow:0 6px 20px rgba(0,0,0,.45)',
        ].join(';');

        const panel = document.createElement('div');
        panel.style.cssText = [
            'position:fixed',
            'right:18px',
            'bottom:64px',
            'z-index:2147483000',
            'max-width:320px',
            'display:none',
            'padding:12px 14px',
            'border-radius:12px',
            'border:1px solid rgba(90,110,160,.4)',
            'background:#0a0f1e',
            'color:#c9d4ea',
            'font:400 13px/1.5 system-ui,sans-serif',
            'box-shadow:0 8px 28px rgba(0,0,0,.5)',
        ].join(';');

        const say = (t) => {
            panel.textContent = t;
            panel.style.display = 'block';
        };

        btn.addEventListener('click', async () => {
            const question =
                (typeof opts.getQuestion === 'function' && opts.getQuestion()) ||
                'Look at my screen — what is the single most useful thing you notice?';
            say('Looking…');
            btn.disabled = true;
            try {
                const cid =
                    (typeof opts.getConversationId === 'function' && opts.getConversationId()) ||
                    window.HOMEPILOT_CONVERSATION_ID ||
                    undefined;
                const r = await this.ask(question, {
                    conversationId: cid,
                    apiKey: opts.apiKey || window.HOMEPILOT_API_KEY,
                    model: opts.model,
                });
                say(r.ok ? r.analysis_text || '(no answer)' : 'ScreenSense: ' + (r.error || 'failed'));
                if (r.ok && typeof opts.onResult === 'function') opts.onResult(r);
            } finally {
                btn.disabled = false;
            }
        });

        document.body.appendChild(btn);
        document.body.appendChild(panel);
        this._button = btn;
        this._panel = panel;
        return btn;
    };

    window.hpScreenSense = new HPScreenSense();

    // Auto-mount the floating button unless the host opts out with
    // window.HOMEPILOT_SCREENSENSE_NO_AUTOBUTTON = true before this script loads.
    if (!window.HOMEPILOT_SCREENSENSE_NO_AUTOBUTTON) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => window.hpScreenSense.mountButton());
        } else {
            window.hpScreenSense.mountButton();
        }
    }
})();
