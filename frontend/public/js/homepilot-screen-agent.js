/**
 * HomePilot Screen Agent — answering "take a screenshot of my PC" without a new permission
 * (batch RS1, path A). Additive: this file adds behaviour, it changes none.
 *
 * A browser tab cannot be called. It has no address, and nothing on the network can reach
 * into it and ask for a frame. So it calls out: while — and only while — this tab holds a
 * screen share the user granted and can see in their own browser bar, it long-polls
 * HomePilot for a capture request, grabs one frame off the stream ScreenSense already owns,
 * and posts it back.
 *
 * That ordering is the whole point of the file. HomePilot can also photograph the desktop
 * directly, but only behind a local flag, because that path has no indicator of its own.
 * This one is free of that cost: the picture comes off a stream the user is watching
 * themselves share, through the single module that owns every getDisplayMedia call.
 *
 * ## What it will not do
 *
 * It does not start a share. It does not ask for one. If nothing is being shared it simply
 * does not poll — which the server reads as "no tab is listening", so a capture request
 * falls through to the desktop path or is refused in words, instead of hanging.
 *
 * Desktop (Electron) mode captures silently by design, on the user's own installed app. That
 * is fine for a button the user just pressed and not obviously fine for a request arriving
 * from somewhere else, so it stays off here unless the host opts in with
 * `window.HOMEPILOT_REMOTE_AGENT_DESKTOP = true`.
 *
 * Load after homepilot-screensense.js:
 *   <script src="/js/homepilot-screen-agent.js"></script>
 *
 * Exposes: window.hpScreenAgent — { serving(), start(), stop(), tick() }
 */
(function () {
    'use strict';

    const API_BASE = window.HOMEPILOT_API_BASE || '';

    /** Seconds the server holds a poll open. Anything under its own freshness window works. */
    const POLL_WAIT_S = 25;
    /** How often to re-check whether a share appeared, while none has. */
    const IDLE_RECHECK_MS = 4000;
    /** After a transport error, wait this long before trying again — a down backend is not
     *  a reason to make a request every 15ms for as long as the tab is open. */
    const ERROR_BACKOFF_MS = 8000;

    function sense() {
        return window.hpScreenSense || null;
    }

    /**
     * Can this tab honour a request right now?
     *
     * Deliberately strict, and re-asked before every poll rather than cached: a share ends
     * from the browser's own bar, in a tab nobody is looking at, and a cached yes would keep
     * this tab claiming it can take pictures it can no longer take.
     */
    function serving() {
        const s = sense();
        if (!s) return false;
        if (s.mode === 'desktop') return window.HOMEPILOT_REMOTE_AGENT_DESKTOP === true;
        if (s.mode !== 'browser') return false;
        // `enabled` is ScreenSense's own live check on the stream, not a flag it set once.
        return Boolean(s.enabled);
    }

    class ScreenAgent {
        constructor() {
            this._running = false;
            this._timer = null;
            this._inflight = false;
        }

        start() {
            if (this._running) return this;
            this._running = true;
            this._loop();
            return this;
        }

        stop() {
            this._running = false;
            if (this._timer) {
                clearTimeout(this._timer);
                this._timer = null;
            }
            return this;
        }

        _later(ms) {
            if (!this._running) return;
            this._timer = setTimeout(() => this._loop(), ms);
        }

        async _loop() {
            if (!this._running) return;
            let delay = 0;
            try {
                delay = await this.tick();
            } catch (_) {
                delay = ERROR_BACKOFF_MS;
            }
            this._later(delay);
        }

        /**
         * One turn of the loop. Returns how long to wait before the next one.
         *
         * Split out from `_loop` so a test can drive it a step at a time without a timer,
         * which is the only way the "share ended between two polls" case is checkable.
         */
        async tick() {
            if (this._inflight) return IDLE_RECHECK_MS;
            if (!serving()) return IDLE_RECHECK_MS;
            this._inflight = true;
            try {
                const res = await fetch(
                    API_BASE + '/v1/screensense/agent/poll?wait=' + POLL_WAIT_S,
                    { method: 'GET', credentials: 'include' }
                );
                if (!res.ok) return ERROR_BACKOFF_MS;
                const out = await res.json();
                const job = out && out.request;
                if (!job || !job.request_id) return 0; // poll timed out; go straight round again
                await this._answer(job);
                return 0;
            } finally {
                this._inflight = false;
            }
        }

        /** Grab one frame and post it back against the request it answers. */
        async _answer(job) {
            const s = sense();
            if (!s) return false;
            // Re-checked after the poll returns, not only before it: the poll blocks for up
            // to 25 seconds, and a share can end inside that window. Sending nothing lets
            // the capture time out and fall through, which is the honest outcome.
            if (!serving()) return false;
            let blob = null;
            try {
                blob = await s.captureFrame(1600);
            } catch (_) {
                blob = null;
            }
            if (!blob) return false;
            const fd = new FormData();
            fd.append('request_id', job.request_id);
            fd.append('file', blob, 'screen-' + Date.now() + '.jpg');
            try {
                await fetch(API_BASE + '/v1/screensense/agent/frame', {
                    method: 'POST',
                    body: fd,
                    credentials: 'include',
                });
            } catch (_) {
                return false;
            }
            return true;
        }
    }

    const agent = new ScreenAgent();
    window.hpScreenAgent = Object.assign(agent, { serving });

    if (!window.HOMEPILOT_SCREEN_AGENT_NOAUTO) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => agent.start());
        } else {
            agent.start();
        }
    }
})();
