/**
 * useCallSession — React hook that owns the voice_call lifecycle.
 *
 * One instance per mounted `CallOverlayInner`. Composes callApi +
 * callSocket into a single, cleanup-safe React surface:
 *
 *   const session = useCallSession({ enabled, backendUrl, authToken,
 *                                    conversationId, personaId,
 *                                    deviceInfo })
 *
 *   session.status                → 'idle' | 'creating' | 'connecting'
 *                                  | 'live' | 'reconnecting'
 *                                  | 'unavailable' | 'error' | 'closed'
 *   session.sendTranscript(text)  → route STT capture to the backend
 *   session.end()                 → graceful user-initiated close
 *   session.onAssistantTranscript → subscribe to assistant replies
 *   session.onAssistantFiller     → subscribe to "hmm…" events
 *   session.onAssistantBackchannel → subscribe to "mm-hm" events
 *   session.lastError             → surface for the UI
 *
 * When `enabled` flips to true we:
 *   1. POST /v1/voice-call/sessions  (via callApi)
 *   2. Open the WebSocket             (via callSocket)
 *   3. Wire status + event forwarding into React state
 *
 * Critically, if the POST returns 404/501 (backend has
 * VOICE_CALL_ENABLED=false) we surface `status='unavailable'` and
 * stop — the caller then falls back to the chat-REST path. That
 * graceful-degradation path is what lets us ship this module
 * independent of the backend flag rollout.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createCallSession, resolveWsUrl, CallApiError, } from './callApi';
import { CallSocket, } from './callSocket';
// When the backend returns 404/501 for voice_call (VOICE_CALL_ENABLED=false)
// we remember the miss per-backend and short-circuit future session creates
// for UNAVAILABLE_BACKOFF_MS. Without this, every CallOverlay mount posts a
// fresh 404 against the same flag, spamming the console and delaying the
// fallback path by a full network round-trip.
//
// Industry practice: the backend feature-flag rarely flips mid-session, so
// the backoff is long-lived (10 min) and persisted to sessionStorage so it
// survives React 18 StrictMode's double-invoke of passive effects + in-tab
// navigations that tear the CallOverlay down and re-mount it. Clearing
// sessionStorage ( or calling clearVoiceCallUnavailable ) forces a re-probe.
const UNAVAILABLE_BACKOFF_MS = 10 * 60 * 1000;
const BACKOFF_STORAGE_KEY = 'homepilot_voice_call_unavailable_until';
const unavailableUntilByBackend = new Map();
// In-flight dedupe — StrictMode's double-invoke of the mount effect fires
// two parallel POSTs before either resolves, so the backoff is useless in
// that window. Share a single Promise per (backendUrl, authToken) so the
// two invokes observe the same network result instead of racing two probes.
const inflightByBackend = new Map();
function _readPersistedBackoff(backendUrl) {
    if (typeof window === 'undefined')
        return 0;
    try {
        const raw = window.sessionStorage.getItem(BACKOFF_STORAGE_KEY);
        if (!raw)
            return 0;
        const map = JSON.parse(raw);
        const until = Number(map[backendUrl] ?? 0);
        return Number.isFinite(until) ? until : 0;
    }
    catch {
        return 0;
    }
}
function _writePersistedBackoff(backendUrl, until) {
    if (typeof window === 'undefined')
        return;
    try {
        const raw = window.sessionStorage.getItem(BACKOFF_STORAGE_KEY);
        const map = (raw ? JSON.parse(raw) : {});
        map[backendUrl] = until;
        window.sessionStorage.setItem(BACKOFF_STORAGE_KEY, JSON.stringify(map));
    }
    catch {
        /* ignore quota / private-mode errors */
    }
}
function _clearPersistedBackoff(backendUrl) {
    if (typeof window === 'undefined')
        return;
    try {
        const raw = window.sessionStorage.getItem(BACKOFF_STORAGE_KEY);
        if (!raw)
            return;
        const map = JSON.parse(raw);
        delete map[backendUrl];
        window.sessionStorage.setItem(BACKOFF_STORAGE_KEY, JSON.stringify(map));
    }
    catch {
        /* ignore */
    }
}
/** Resolve the active backoff deadline for a backend. Checks the in-memory
 *  cache first, falls through to sessionStorage. Expired entries return 0. */
function _backoffUntil(backendUrl) {
    const mem = unavailableUntilByBackend.get(backendUrl) ?? 0;
    const persisted = _readPersistedBackoff(backendUrl);
    const until = Math.max(mem, persisted);
    if (until && until <= Date.now()) {
        unavailableUntilByBackend.delete(backendUrl);
        _clearPersistedBackoff(backendUrl);
        return 0;
    }
    return until;
}
/** Force a re-probe of the voice_call backend on the next CallOverlay mount.
 *  Exposed for future "retry now" UI affordances. Non-destructive: no-op if
 *  no backoff was set. */
export function clearVoiceCallUnavailable(backendUrl) {
    unavailableUntilByBackend.delete(backendUrl);
    _clearPersistedBackoff(backendUrl);
}
export function useCallSession(args) {
    const { enabled, backendUrl, authToken, request } = args;
    const [status, setStatus] = useState('idle');
    const [callState, setCallState] = useState(null);
    const [closeReason, setCloseReason] = useState(null);
    const [lastError, setLastError] = useState(null);
    const socketRef = useRef(null);
    const sessionRef = useRef(null);
    // Stable subscribe surface. Keep listener sets here so they survive
    // socket reconnects — the old socket's listeners are torn down with
    // it, but user subscriptions persist across reconnects and are
    // re-attached when a new socket comes up.
    const txListeners = useRef(new Set());
    const fillerListeners = useRef(new Set());
    const bcListeners = useRef(new Set());
    // Phase 2/3 listener sets. Kept separate so an old subscribe set
    // doesn't churn when a new one mounts (stream wire-up rebinds often
    // during CallOverlay renders).
    const partialListeners = useRef(new Set());
    const turnEndListeners = useRef(new Set());
    const cancelListeners = useRef(new Set());
    // Negotiated modes — re-derived on session create, stashed here so
    // every render reads the same value without re-running the effect.
    const [streamingNegotiated, setStreamingNegotiated] = useState(false);
    const [bargeInNegotiated, setBargeInNegotiated] = useState(false);
    // Ref'd primitive so the session-create effect doesn't re-trigger
    // when the request object identity changes every render.
    const requestRef = useRef(request);
    useEffect(() => { requestRef.current = request; }, [request]);
    // Main lifecycle. Runs once per (enabled, backendUrl, authToken)
    // triple — which is what we want: flipping enabled true/false
    // drives open/close; swapping backendUrl or re-auth reconnects.
    useEffect(() => {
        if (!enabled)
            return;
        let disposed = false;
        const teardown = () => {
            disposed = true;
            socketRef.current?.dispose('unmounted');
            socketRef.current = null;
            sessionRef.current = null;
        };
        const run = async () => {
            setStatus('creating');
            setLastError(null);
            setCloseReason(null);
            setCallState(null);
            // Skip the POST entirely if this backend has been 404/501-ing
            // recently. _backoffUntil() consults the in-memory map + the
            // sessionStorage mirror so StrictMode double-invokes + page
            // reloads share the verdict. Expired entries self-clear.
            const skipUntil = _backoffUntil(backendUrl);
            if (skipUntil) {
                // eslint-disable-next-line no-console
                console.info('[useCallSession] skipping createCallSession — backend flagged unavailable', { backendUrl, resumesAt: new Date(skipUntil).toISOString() });
                setStatus('unavailable');
                return;
            }
            // Share the handshake Promise across concurrent callers so
            // React 18 StrictMode's two parallel mount effects can't fire
            // two POSTs (the backoff is written only after the response
            // lands, so a second probe racing the first would otherwise
            // get through before the first writes its verdict).
            let handshake;
            try {
                let inflight = inflightByBackend.get(backendUrl);
                if (!inflight) {
                    inflight = createCallSession(backendUrl, requestRef.current, authToken)
                        .finally(() => {
                        inflightByBackend.delete(backendUrl);
                    });
                    inflightByBackend.set(backendUrl, inflight);
                }
                handshake = await inflight;
            }
            catch (err) {
                if (disposed)
                    return;
                if (err instanceof CallApiError && err.isUnavailable) {
                    const until = Date.now() + UNAVAILABLE_BACKOFF_MS;
                    unavailableUntilByBackend.set(backendUrl, until);
                    _writePersistedBackoff(backendUrl, until);
                    // eslint-disable-next-line no-console
                    console.info('[useCallSession] voice_call unavailable — falling back to chat REST until', new Date(until).toISOString());
                    setStatus('unavailable');
                    return;
                }
                // eslint-disable-next-line no-console
                console.error('[useCallSession] createCallSession failed', err);
                setStatus('error');
                setLastError(err instanceof Error ? err.message : String(err));
                return;
            }
            if (disposed)
                return;
            // Handshake worked — clear any prior backoff so new flag flips
            // take effect immediately instead of waiting out the window.
            unavailableUntilByBackend.delete(backendUrl);
            _clearPersistedBackoff(backendUrl);
            sessionRef.current = handshake;
            const url = resolveWsUrl(handshake.ws_url, handshake.session_id, handshake.resume_token, authToken, backendUrl);
            const sock = new CallSocket({ url });
            socketRef.current = sock;
            // Translate socket lifecycle → hook status.
            sock.on('statusChange', (s) => {
                if (disposed)
                    return;
                setStatus(s === 'idle' ? 'idle' : s);
            });
            sock.on('callState', (p) => {
                if (disposed)
                    return;
                setCallState(p.status);
            });
            sock.on('closed', ({ reason }) => {
                if (disposed)
                    return;
                setStatus('closed');
                setCloseReason(reason);
            });
            sock.on('serverError', (p) => {
                // Non-terminal by contract; surface for the UI but keep the
                // socket open. The server will close explicitly if fatal.
                if (disposed)
                    return;
                setLastError(`${p.code}: ${p.message}`);
            });
            sock.on('assistantTranscript', (p) => {
                for (const fn of txListeners.current)
                    fn(p);
            });
            sock.on('assistantFiller', (p) => {
                for (const fn of fillerListeners.current)
                    fn(p);
            });
            sock.on('assistantBackchannel', (p) => {
                for (const fn of bcListeners.current)
                    fn(p);
            });
            // Phase 2/3 event fan-outs.
            sock.on('assistantPartial', (p) => {
                for (const fn of partialListeners.current)
                    fn(p);
            });
            sock.on('assistantTurnEnd', (p) => {
                for (const fn of turnEndListeners.current)
                    fn(p);
            });
            sock.on('assistantCancel', (p) => {
                for (const fn of cancelListeners.current)
                    fn(p);
            });
            // Reflect negotiated modes from the session-create response.
            const caps = handshake.capabilities;
            setStreamingNegotiated(!!caps?.streaming);
            setBargeInNegotiated(!!caps?.streaming && !!caps?.barge_in);
            sock.connect();
        };
        void run();
        return teardown;
    }, [enabled, backendUrl, authToken]);
    // Public actions. Guarded against stale-socket calls. --------------
    const sendTranscript = useCallback((text) => {
        const sock = socketRef.current;
        if (!sock)
            return;
        const trimmed = text.trim();
        if (!trimmed)
            return;
        sock.sendTranscript({ text: trimmed });
    }, []);
    const end = useCallback(() => {
        socketRef.current?.end();
    }, []);
    const sendUiState = useCallback((p) => {
        socketRef.current?.sendUiState(p);
    }, []);
    const sendTranscriptPartial = useCallback((p) => {
        socketRef.current?.sendTranscriptPartial(p);
    }, []);
    const sendBargeIn = useCallback((turn_id) => {
        socketRef.current?.sendBargeIn(turn_id);
    }, []);
    const onAssistantTranscript = useCallback((fn) => {
        txListeners.current.add(fn);
        return () => { txListeners.current.delete(fn); };
    }, []);
    const onAssistantFiller = useCallback((fn) => {
        fillerListeners.current.add(fn);
        return () => { fillerListeners.current.delete(fn); };
    }, []);
    const onAssistantBackchannel = useCallback((fn) => {
        bcListeners.current.add(fn);
        return () => { bcListeners.current.delete(fn); };
    }, []);
    const onAssistantPartial = useCallback((fn) => {
        partialListeners.current.add(fn);
        return () => { partialListeners.current.delete(fn); };
    }, []);
    const onAssistantTurnEnd = useCallback((fn) => {
        turnEndListeners.current.add(fn);
        return () => { turnEndListeners.current.delete(fn); };
    }, []);
    const onAssistantCancel = useCallback((fn) => {
        cancelListeners.current.add(fn);
        return () => { cancelListeners.current.delete(fn); };
    }, []);
    return useMemo(() => ({
        status,
        callState,
        closeReason,
        lastError,
        sendTranscript,
        end,
        sendUiState,
        sendTranscriptPartial,
        sendBargeIn,
        streamingNegotiated,
        bargeInNegotiated,
        onAssistantTranscript,
        onAssistantFiller,
        onAssistantBackchannel,
        onAssistantPartial,
        onAssistantTurnEnd,
        onAssistantCancel,
    }), [
        status, callState, closeReason, lastError,
        sendTranscript, end, sendUiState,
        sendTranscriptPartial, sendBargeIn,
        streamingNegotiated, bargeInNegotiated,
        onAssistantTranscript, onAssistantFiller, onAssistantBackchannel,
        onAssistantPartial, onAssistantTurnEnd, onAssistantCancel,
    ]);
}
