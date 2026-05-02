/**
 * callSocket.ts — typed transport for the voice_call WebSocket.
 *
 * Owns the connection, the envelope codec, monotonic sequence
 * tracking, the heartbeat, graceful shutdown, and reconnect-with-
 * backoff semantics. Exposes a narrow event surface that the React
 * hook (useCallSession) binds to; callers never touch the raw socket.
 *
 * Explicit state machine — the only transitions allowed are:
 *
 *     idle ──connect()──▶ connecting ──open───────▶ live
 *                             │                        │
 *                             │ (handshake failure)    │ (transient drop w/ resume window)
 *                             ▼                        ▼
 *                          closed                  reconnecting ──(give up / expired)──▶ closed
 *                                                      │
 *                                                      └─────(socket open)───────▶ live
 *
 *     live ──close('user_ended' | 'max_duration' | 'idle')───▶ closed
 *
 * Industry choices baked in:
 *   • Exponential backoff with full jitter (AWS / Cloudflare canonical
 *     implementation) — stops thundering herds on a shared-backend
 *     brown-out.
 *   • Heartbeat treats silence as liveness failure — we send a
 *     client-originated `call.control ping` every N seconds AND
 *     watch for server-side `ping` events; if BOTH are silent for
 *     2× the interval, the connection is considered dead and the
 *     backoff loop fires.
 *   • Outbound envelopes are queued while reconnecting. When the
 *     socket reopens within the resume window the queue is flushed
 *     in-order; otherwise it's dropped on shutdown.
 *   • Resume semantics honoured: one reconnect attempt carries the
 *     same session_id + resume_token; if the server returns
 *     1008 resume-expired we give up and surface 'resume_expired'.
 *   • Every event emitted by this module is typed; no `any`, no
 *     ad-hoc payload parsing inside listeners.
 */
// ── Backoff helper (AWS-style full jitter) ─────────────────────────
function backoffMs(attempt, baseMs = 500, capMs = 10_000) {
    const exp = Math.min(capMs, baseMs * 2 ** attempt);
    return Math.floor(Math.random() * exp);
}
// ── Close-code → reason mapping ────────────────────────────────────
const POLICY_VIOLATION = 1008;
const NORMAL_CLOSURE = 1000;
function closeReasonFrom(code, text) {
    const reason = (text || '').toLowerCase();
    if (code === POLICY_VIOLATION) {
        if (reason.includes('resume-expired'))
            return 'resume_expired';
        if (reason.includes('bad-resume-token'))
            return 'bad_resume_token';
        if (reason.includes('session-not-found'))
            return 'session_not_found';
        if (reason.includes('session-ended'))
            return 'session_ended';
        if (reason.includes('websocket-disabled'))
            return 'websocket_disabled';
    }
    if (code === NORMAL_CLOSURE && reason.includes('max-duration'))
        return 'max_duration';
    if (reason.includes('idle'))
        return 'idle_timeout';
    return 'unknown';
}
// ── CallSocket class ───────────────────────────────────────────────
export class CallSocket {
    constructor(opts) {
        this.ws = null;
        this.status = 'idle';
        this.lastServerSeq = 0;
        this.outboundQueue = [];
        this.heartbeatTimer = null;
        this.lastServerActivityMs = 0;
        this.deadPeerTimer = null;
        this.reconnectAttempt = 0;
        this.reconnectTimer = null;
        this.connectedAtMs = 0;
        this.shuttingDown = false;
        this.listeners = {};
        this.url = opts.url;
        this.resumeWindowMs = (opts.resumeWindowSec ?? 20) * 1000;
        this.heartbeatIntervalMs = opts.heartbeatIntervalMs ?? 15_000;
        this.WebSocketImpl = opts.webSocketImpl ?? WebSocket;
        this.log = opts.log ?? {
            info: (m, e) => console.info(`[callSocket] ${m}`, e ?? ''),
            warn: (m, e) => console.warn(`[callSocket] ${m}`, e ?? ''),
            error: (m, e) => console.error(`[callSocket] ${m}`, e ?? ''),
        };
    }
    // Public API ----------------------------------------------------
    getStatus() { return this.status; }
    on(evt, fn) {
        let set = this.listeners[evt];
        if (!set) {
            set = new Set();
            this.listeners[evt] = set;
        }
        set.add(fn);
        return () => set.delete(fn);
    }
    /** Open the socket. Safe to call exactly once per instance. */
    connect() {
        if (this.status !== 'idle') {
            this.log.warn('connect() called in non-idle state', { status: this.status });
            return;
        }
        this.openSocket();
    }
    /** Send the captured user transcript as a chat turn. Queued if the
     *  socket is currently mid-reconnect. */
    sendTranscript(p) {
        this.enqueueLine({ type: 'transcript.final', ts: Date.now(), payload: p });
    }
    /** Bookkeeping — muted, speaker on/off, app backgrounded. */
    sendUiState(p) {
        this.enqueueLine({ type: 'ui.state', ts: Date.now(), payload: p });
    }
    /** Control channel — 'ping' requests a pong; 'end' terminates. */
    sendControl(action) {
        this.enqueueLine({ type: 'call.control', ts: Date.now(), payload: { action } });
    }
    /** Phase 2 — interim STT output while the user is still speaking.
     *  Server uses it as a secondary barge-in trigger and, in a
     *  future phase, for semantic endpointing. Safe no-op against a
     *  non-streaming server (unknown type is dropped). */
    sendTranscriptPartial(p) {
        this.enqueueLine({
            type: 'transcript.partial',
            ts: Date.now(),
            payload: p,
        });
    }
    /** Phase 3 — explicit interrupt. Fired the instant the client's
     *  VAD trips above threshold while an assistant turn is in-flight.
     *  ``turn_id`` disambiguates against a stale signal racing a new
     *  turn; the server compares ids and silently drops mismatches. */
    sendBargeIn(turn_id) {
        this.enqueueLine({
            type: 'user.barge_in',
            ts: Date.now(),
            payload: { turn_id },
        });
    }
    /** Graceful user-initiated end. Sends control 'end', then closes. */
    end() {
        if (this.shuttingDown)
            return;
        this.shuttingDown = true;
        this.transition('draining');
        this.sendControl('end');
        // Give the server ~400 ms to echo call.state {status:'ended'}
        // before we force-close; prevents the socket from looking
        // orphaned in backend logs.
        window.setTimeout(() => this.dispose('user_ended'), 400);
    }
    /** Teardown without a control 'end' — used when the component
     *  unmounts, the user navigates away, or a terminal error occurs. */
    dispose(reason = 'unmounted', code = NORMAL_CLOSURE) {
        if (this.status === 'closed')
            return;
        this.shuttingDown = true;
        this.clearTimers();
        try {
            this.ws?.close(code, reason);
        }
        catch { /* already closed */ }
        this.ws = null;
        this.outboundQueue = [];
        this.transition('closed');
        this.emit('closed', { reason, code });
    }
    // Socket lifecycle ----------------------------------------------
    openSocket() {
        this.transition(this.reconnectAttempt === 0 ? 'connecting' : 'reconnecting');
        let ws;
        try {
            ws = new this.WebSocketImpl(this.url);
        }
        catch (err) {
            this.log.error('WebSocket constructor threw', { err: String(err) });
            this.scheduleReconnect();
            return;
        }
        this.ws = ws;
        this.lastServerActivityMs = Date.now();
        ws.addEventListener('open', () => {
            this.reconnectAttempt = 0;
            this.connectedAtMs = Date.now();
            this.transition('live');
            this.startHeartbeat();
            this.flushQueue();
        });
        ws.addEventListener('message', (ev) => this.onMessage(ev));
        ws.addEventListener('close', (ev) => this.onClose(ev));
        ws.addEventListener('error', () => {
            // The browser fires `error` right before `close` on network
            // failures. We don't transition here — onClose() decides
            // reconnect vs terminal based on the code.
            this.log.warn('socket error event');
        });
    }
    onMessage(ev) {
        this.lastServerActivityMs = Date.now();
        if (typeof ev.data !== 'string')
            return;
        let env = null;
        try {
            env = JSON.parse(ev.data);
        }
        catch {
            this.log.warn('non-JSON frame dropped');
            return;
        }
        if (!env || typeof env.type !== 'string')
            return;
        // Monotonic seq validation. If the server ever ships out-of-order
        // frames we log once and keep going — correctness trumps strictness.
        if (typeof env.seq === 'number' && env.seq <= this.lastServerSeq) {
            this.log.warn('non-monotonic seq', {
                got: env.seq, last: this.lastServerSeq, type: env.type,
            });
        }
        else if (typeof env.seq === 'number') {
            this.lastServerSeq = env.seq;
        }
        this.dispatch(env);
    }
    dispatch(env) {
        const raw = env.payload;
        switch (env.type) {
            case 'call.state': {
                const p = raw;
                this.emit('callState', p);
                if (p.status === 'ended')
                    this.dispose('user_ended');
                return;
            }
            case 'transcript.final':
                this.emit('assistantTranscript', raw);
                return;
            case 'assistant.partial':
                this.emit('assistantPartial', raw);
                return;
            case 'assistant.turn_end':
                this.emit('assistantTurnEnd', raw);
                return;
            case 'assistant.cancel':
                this.emit('assistantCancel', raw);
                return;
            case 'assistant.filler':
                this.emit('assistantFiller', raw);
                return;
            case 'assistant.backchannel':
                this.emit('assistantBackchannel', raw);
                return;
            case 'safety.notice':
                this.emit('safetyNotice', env.payload);
                return;
            case 'error':
                this.emit('serverError', raw);
                return;
            case 'pong':
                this.emit('pong', undefined);
                return;
            case 'ping':
                // Server heartbeat — immediately echo to keep the liveness
                // counters tight on both ends.
                this.sendControl('ping');
                return;
            default:
                // Forward-compat: unknown event types are no-ops.
                this.log.info(`unknown server event: ${env.type}`);
        }
    }
    onClose(ev) {
        const reason = closeReasonFrom(ev.code, ev.reason);
        this.clearTimers();
        // Terminal close codes: don't reconnect.
        const terminal = new Set([
            'user_ended',
            'max_duration',
            'resume_expired',
            'bad_resume_token',
            'session_not_found',
            'session_ended',
            'websocket_disabled',
        ]);
        if (this.shuttingDown || terminal.has(reason)) {
            this.ws = null;
            this.transition('closed');
            this.emit('closed', { reason, code: ev.code, detail: ev.reason });
            return;
        }
        // Transient — try to reconnect within the resume window.
        this.log.warn('socket dropped; scheduling reconnect', {
            code: ev.code, reason: ev.reason,
        });
        this.ws = null;
        this.scheduleReconnect();
    }
    scheduleReconnect() {
        if (this.shuttingDown)
            return;
        const sinceLiveMs = this.connectedAtMs > 0 ? Date.now() - this.connectedAtMs : 0;
        if (sinceLiveMs > this.resumeWindowMs) {
            this.log.warn('resume window elapsed; giving up');
            this.dispose('resume_expired', POLICY_VIOLATION);
            return;
        }
        const delay = backoffMs(this.reconnectAttempt);
        this.reconnectAttempt += 1;
        this.transition('reconnecting');
        this.reconnectTimer = window.setTimeout(() => {
            this.reconnectTimer = null;
            this.openSocket();
        }, delay);
    }
    // Queue + heartbeat ---------------------------------------------
    enqueueLine(env) {
        const line = JSON.stringify(env);
        if (this.status === 'live' && this.ws?.readyState === this.WebSocketImpl.OPEN) {
            try {
                this.ws.send(line);
            }
            catch (err) {
                this.log.warn('send failed; queueing', { err: String(err) });
                this.outboundQueue.push(line);
            }
        }
        else {
            this.outboundQueue.push(line);
        }
    }
    flushQueue() {
        if (!this.ws || this.ws.readyState !== this.WebSocketImpl.OPEN)
            return;
        const q = this.outboundQueue;
        this.outboundQueue = [];
        for (const line of q) {
            try {
                this.ws.send(line);
            }
            catch (err) {
                this.log.error('flush failed; re-queueing remaining', { err: String(err) });
                this.outboundQueue.push(line);
                return;
            }
        }
    }
    startHeartbeat() {
        this.clearHeartbeat();
        this.heartbeatTimer = window.setInterval(() => {
            this.sendControl('ping');
        }, this.heartbeatIntervalMs);
        // Dead-peer watchdog — if we haven't heard from the server in
        // 2× the heartbeat interval, force a reconnect. Avoids hanging
        // forever on half-open TCP sockets (mobile NAT rebinds).
        this.deadPeerTimer = window.setInterval(() => {
            if (Date.now() - this.lastServerActivityMs > this.heartbeatIntervalMs * 2) {
                this.log.warn('peer silent; forcing reconnect');
                try {
                    this.ws?.close();
                }
                catch { /* ignore */ }
            }
        }, this.heartbeatIntervalMs);
    }
    clearHeartbeat() {
        if (this.heartbeatTimer !== null) {
            window.clearInterval(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
        if (this.deadPeerTimer !== null) {
            window.clearInterval(this.deadPeerTimer);
            this.deadPeerTimer = null;
        }
    }
    clearTimers() {
        this.clearHeartbeat();
        if (this.reconnectTimer !== null) {
            window.clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }
    // Emit + state transition ---------------------------------------
    emit(evt, payload) {
        const set = this.listeners[evt];
        if (!set)
            return;
        for (const fn of set) {
            try {
                fn(payload);
            }
            catch (err) {
                this.log.error('listener threw', { evt, err: String(err) });
            }
        }
    }
    transition(next) {
        if (this.status === next)
            return;
        this.status = next;
        this.emit('statusChange', next);
    }
}
