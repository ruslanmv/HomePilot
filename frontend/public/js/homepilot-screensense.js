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

    /**
     * Tell the backend a screen share started, stopped, or was looked at (MS29).
     *
     * This is the whole of the fix for "can you see my screen?" → "No, I can't." The capture
     * always worked; the chat model was simply never told, so from where it sat that answer
     * was true. Now the persona's prompt carries a [LIVE SCREEN] block while sharing is on.
     *
     * Fire-and-forget on purpose: a presence ping that fails must never delay a capture or
     * surface an error. The server expires a share it stops hearing about.
     */
    /** The user's own switch (Settings → Multimodal). Off means nothing is ever sent. */
    let awareness = true;

    /**
     * The vision provider the user picked in Settings (V1).
     *
     * Settings has always stored `homepilot_provider_multimodal`, `homepilot_base_url_multimodal`
     * and `homepilot_model_multimodal`, and `/v1/multimodal/analyze` has always accepted all
     * three — but nothing carried them from one to the other. The floating button auto-mounts
     * with no options, so `opts.model` was `undefined`, the field was omitted, and the backend
     * auto-detected instead. The user's choice was read, stored, and dropped.
     *
     * Held here rather than read from storage on each ask: this file has no opinion about
     * where the host app keeps its settings, and a host that keeps them somewhere else needs
     * only to call `setVision`.
     */
    let vision = { provider: '', baseUrl: '', model: '' };

    function tellBackend(action, conversationId, extra) {
        // Checked here rather than at each call site, so a future caller cannot forget it.
        // "stop" is always allowed through: turning the setting off mid-share must retract
        // what the server already knows, not merely stop adding to it.
        if (!awareness && action !== 'stop') return;
        const cid = String(conversationId || '').trim();
        if (!cid) return;
        try {
            fetch(API_BASE + '/v1/meetingsense/screen/' + encodeURIComponent(cid), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(Object.assign({ action: action }, extra || {})),
            }).catch(function () {});
        } catch (_) {
            // An install without MeetingSense answers 404 and nothing here cares.
        }
    }

    /**
     * Refusal openings a vision model uses when it cannot answer. Same list MS9's
     * `clean_caption` keeps server-side, for the same reason: a refusal shown as an answer
     * reads as the product being broken rather than the model declining.
     */
    const REFUSALS = [
        "i'm sorry", "i am sorry", "sorry,", "i cannot", "i can't", "i am unable",
        "i'm unable", "as an ai", "i do not have", "i don't have", "unable to",
    ];

    /**
     * Is this worth showing a person? (`""` when not.)
     *
     * A small vision model asked an open question about a screenshot will sometimes return a
     * word or two of noise — "ersatz", "erset up lngreck aggr;" — and printing that verbatim
     * makes the product look broken when the truth is that the model is too small for the job.
     *
     * The test is deliberately blunt: a real answer to "what is on my screen" is a sentence.
     * Five words and twenty characters is under any genuine answer and over both kinds of
     * noise, and it is a rule a reader can check, which a cleverer gibberish detector is not —
     * that would eventually reject "npm ERR! ENOENT: no such file or directory", which is
     * exactly the answer somebody most needs.
     */
    function usableAnswer(text) {
        const body = String(text || '').replace(/\s+/g, ' ').trim();
        if (!body) return '';
        const lowered = body.toLowerCase();
        for (const mark of REFUSALS) {
            if (lowered.startsWith(mark)) return '';
        }
        if (body.length < 20) return '';
        if (body.split(' ').filter(Boolean).length < 5) return '';
        return body;
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
            // MS29. The share is live the moment the picker is accepted — before any frame is
            // captured — so a persona asked "can you see my screen?" straight afterwards
            // answers yes rather than denying something that is already true.
            if (this._conversationId) {
                tellBackend('start', this._conversationId, { mode: this.mode });
            }
            const v = document.createElement('video');
            v.srcObject = this.stream;
            v.muted = true;
            v.playsInline = true;
            v.style.cssText =
                'position:fixed;width:1px;height:1px;opacity:0;pointer-events:none;left:-9px;top:-9px';
            document.body.appendChild(v);
            // `play()` returns a Promise in current browsers and `undefined` in older ones —
            // and in jsdom, which is why this path could not be tested before. Wrapping makes
            // it true in all three rather than throwing on the ones that predate the Promise.
            await Promise.resolve(v.play()).catch(() => {});
            this.video = v;
            this.stream.getVideoTracks()[0]?.addEventListener('ended', () => this.stop());
            return true;
        }

        /**
         * Is the share this object believes in still real? Repairs the belief if not.
         *
         * The browser's own "Stop sharing" bar fires `ended` on the track, and `enable()` has
         * always listened for that — so the ordinary way a share ends was already handled.
         * This covers the ways it is not: a stream that goes inactive without firing, a tab
         * restored from the back/forward cache, a window that went away with the page hidden.
         *
         * Called when the tab becomes visible again, which on a single screen is exactly when
         * the answer is most likely to have changed and least likely to have been noticed —
         * sharing means leaving this tab, so the interesting transitions all happen where
         * nobody is looking.
         *
         * Teardown goes through `stop()` rather than a second path of its own: two ways to end
         * a share is two places to forget to tell the backend, and the duplicate is what made
         * an earlier version of this send the stop twice.
         */
        verifyShare() {
            if (this.mode !== 'browser') return true;
            if (this.stream && this.stream.active) return true;
            // No guard on `this.stream`: `stop()` nulls `_conversationId` as it announces, so
            // calling it twice sends one stop. Restating that here would be a second copy of a
            // rule `stop()` already keeps.
            this.stop();
            return false;
        }

        stop() {
            try {
                this.stream?.getTracks().forEach((t) => t.stop());
            } catch (_) {}
            this.stream = null;
            this.video?.remove();
            this.video = null;
            // The persona must stop believing it can see the screen the moment the user stops
            // showing it. Everything the server held about the share, including the last
            // caption, goes with this.
            if (this._conversationId) {
                tellBackend('stop', this._conversationId);
                this._conversationId = null;
            }
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
                // An explicit option wins; otherwise whatever the user chose in Settings.
                // Empty strings are not choices — they fall through to the backend's own
                // detection rather than being sent as a provider named "".
                const model = opts.model || vision.model;
                const baseUrl = opts.baseUrl || vision.baseUrl;
                const provider = opts.provider || vision.provider;
                if (model) body.model = model;
                if (baseUrl) body.base_url = baseUrl;
                if (provider) body.provider = provider;

                const an = await fetch(API_BASE + '/v1/multimodal/analyze', {
                    method: 'POST',
                    headers: { ...headers, 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                    credentials: 'include',
                });
                // V3. A vision model that returned nothing is now a 422 with a typed code
                // rather than a 200 with empty text. Read the body before deciding it is a
                // transport failure: `analyze 422` would be a worse message than the one the
                // panel already knows how to show, and would throw away the model's name.
                const out = await an.json().catch(() => null);
                if (!an.ok) {
                    if (out && out.error_code === 'empty_model_response') {
                        return { ok: false, error: '', empty: true, meta: out.meta || {}, mode: this.mode };
                    }
                    throw new Error((out && out.error) || 'analyze ' + an.status);
                }
                // MS29. Two facts the chat needs: a screen is being shared, and this is the
                // most recent thing read off it. Sent after the answer rather than before, so
                // a failed capture never leaves the persona claiming to see a screen it did
                // not manage to look at.
                if (opts.conversationId && this.enabled) {
                    this._conversationId = opts.conversationId;
                    tellBackend('start', opts.conversationId, { mode: this.mode });
                    if (out.analysis_text) {
                        tellBackend('seen', opts.conversationId, { caption: out.analysis_text });
                    }
                }
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

    /**
     * Name the conversation a share belongs to (MS29).
     *
     * `ask()` already carries one, but `enable()` runs first when the user presses the button
     * before typing anything — and that is the moment the persona needs to stop denying it can
     * see the screen. A host app calls this once, when the conversation changes.
     */
    HPScreenSense.prototype.bindConversation = function (conversationId) {
        const next = String(conversationId || '').trim() || null;
        if (next === this._conversationId) return;
        // A share belongs to the conversation it was started in. Moving it would put one
        // person's screen into another thread's prompt.
        if (this._conversationId) tellBackend('stop', this._conversationId);
        this._conversationId = next;
        if (next && this.enabled) tellBackend('start', next, { mode: this.mode });
    };

    /**
     * The user's switch (MS29). `false` retracts any live share immediately.
     *
     * Retracting rather than merely muting: somebody who turns this off mid-share is asking
     * for the screen to stop being in the prompt *now*, not from the next frame onwards.
     */
    HPScreenSense.prototype.setAwareness = function (on) {
        const next = on !== false;
        if (next === awareness) return next;
        if (!next && this._conversationId) {
            tellBackend('stop', this._conversationId);
        }
        awareness = next;
        if (next && this._conversationId && this.enabled) {
            tellBackend('start', this._conversationId, { mode: this.mode });
        }
        return next;
    };

    /**
     * Tell ScreenSense which vision model the user chose (V1).
     *
     * Called by the host app when Settings change. Partial updates are merged, so a host that
     * only knows the model does not have to invent a provider — and passing nothing at all
     * clears nothing, which keeps a mount-time call from wiping a later one.
     */
    HPScreenSense.prototype.setVision = function (next) {
        const patch = next || {};
        vision = {
            provider: String(patch.provider === undefined ? vision.provider : patch.provider || '').trim(),
            baseUrl: String(patch.baseUrl === undefined ? vision.baseUrl : patch.baseUrl || '').trim(),
            model: String(patch.model === undefined ? vision.model : patch.model || '').trim(),
        };
        return Object.assign({}, vision);
    };

    /** What ScreenSense will ask for, for a host that wants to show it. */
    HPScreenSense.prototype.getVision = function () {
        return Object.assign({}, vision);
    };

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

        // A titled panel with a close button rather than bare text. Floating prose beside a
        // button reads as part of the page — which is how "ersatz" came to look like a bug in
        // HomePilot instead of a small model saying nothing useful.
        const head = document.createElement('div');
        head.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px';
        const title = document.createElement('strong');
        title.style.cssText = 'font:600 11px/1 system-ui,sans-serif;letter-spacing:.04em;'
            + 'text-transform:uppercase;color:#7f8dab;flex:1';
        title.textContent = 'What I can see';
        const close = document.createElement('button');
        close.type = 'button';
        close.setAttribute('aria-label', 'Dismiss');
        close.textContent = '×';
        close.style.cssText = 'border:0;background:none;color:#7f8dab;cursor:pointer;'
            + 'font:400 16px/1 system-ui,sans-serif;padding:0 2px';
        close.addEventListener('click', () => { panel.style.display = 'none'; });
        head.appendChild(title);
        head.appendChild(close);

        const body = document.createElement('div');
        panel.appendChild(head);
        panel.appendChild(body);

        const say = (t, tone) => {
            body.textContent = t;
            body.style.color = tone === 'weak' ? '#8b96ad' : '#c9d4ea';
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
                // Two ways the model can fail to describe the screen, and they read the
                // same to a person: it returned nothing (V3's typed `empty`), or it returned
                // something `usableAnswer` will not print. Same sentence for both.
                const answer = r.ok ? usableAnswer(r.analysis_text) : '';
                if (!r.ok && !r.empty) {
                    say(r.error || 'The screen could not be captured.', 'weak');
                } else if (answer) {
                    say(answer);
                } else {
                    // Naming the model is the useful part: this outcome nearly always
                    // means the configured vision model is too small for the question,
                    // and the fix is to change it rather than to press the button again.
                    const model = (r.meta && (r.meta.model || r.meta.name)) || 'the vision model';
                    say(
                        'No usable answer from ' + model + '. It returned nothing that '
                        + 'reads as a description of your screen — try a larger vision '
                        + 'model (Settings → Multimodal).',
                        'weak',
                    );
                }
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

    // Coming back to the tab is the moment to re-check, and it costs one property read. On a
    // single screen it is *the* moment: sharing means leaving this tab, and the share is
    // usually ended from the browser's own bar while the tab is hidden.
    if (typeof document !== 'undefined' && document.addEventListener) {
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                try {
                    window.hpScreenSense.verifyShare();
                } catch (_) {
                    // Never worth breaking a page over.
                }
            }
        });
    }

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
