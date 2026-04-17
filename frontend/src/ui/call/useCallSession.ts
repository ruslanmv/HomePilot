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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createCallSession,
  resolveWsUrl,
  CallApiError,
  type CreateCallSessionRequest,
  type CreateCallSessionResponse,
} from './callApi'
import {
  CallSocket,
  type AssistantBackchannelPayload,
  type AssistantFillerPayload,
  type AssistantTranscriptPayload,
  type CallCloseReason,
  type CallLifecycleStatus,
} from './callSocket'

export type CallSessionStatus =
  | 'idle'
  | 'creating'
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'draining'
  | 'closed'
  | 'unavailable'
  | 'error'

export interface UseCallSessionArgs {
  /** The hook is inert until this flips to true. Flipping back to
   *  false triggers a graceful dispose. */
  enabled: boolean
  /** Resolved HomePilot backend URL (scheme + host). */
  backendUrl: string
  /** Bearer JWT for the REST handshake + WS query param. */
  authToken: string | null
  /** Session-creation request fields. */
  request: CreateCallSessionRequest
}

export interface CallSessionHandle {
  status: CallSessionStatus
  /** Server-side canonical status last seen (live / ending / ended). */
  callState: 'live' | 'ending' | 'ended' | null
  /** Raw close reason once the session terminates. Useful for
   *  differentiating user-end vs timeout vs backend-disabled. */
  closeReason: CallCloseReason | null
  /** Any terminal error. 'unavailable' is NOT an error — it's a
   *  legitimate graceful-degradation signal. */
  lastError: string | null
  /** Route a final STT transcript into the call turn. No-op outside
   *  the 'live' | 'reconnecting' states. */
  sendTranscript: (text: string) => void
  /** Graceful end — sends call.control end, closes the socket. */
  end: () => void
  /** Bookkeeping. Server persists the *type* of the event only. */
  sendUiState: (p: { muted?: boolean; speaker_on?: boolean; backgrounded?: boolean }) => void
  /** Subscribe helpers — each returns an unsubscribe fn. Stable
   *  identities via useRef-backed implementation so the caller can
   *  pass them to useEffect deps without re-subscription storms. */
  onAssistantTranscript: (fn: (p: AssistantTranscriptPayload) => void) => () => void
  onAssistantFiller: (fn: (p: AssistantFillerPayload) => void) => () => void
  onAssistantBackchannel: (fn: (p: AssistantBackchannelPayload) => void) => () => void
}

export function useCallSession(args: UseCallSessionArgs): CallSessionHandle {
  const { enabled, backendUrl, authToken, request } = args

  const [status, setStatus] = useState<CallSessionStatus>('idle')
  const [callState, setCallState] = useState<'live' | 'ending' | 'ended' | null>(null)
  const [closeReason, setCloseReason] = useState<CallCloseReason | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)

  const socketRef = useRef<CallSocket | null>(null)
  const sessionRef = useRef<CreateCallSessionResponse | null>(null)

  // Stable subscribe surface. Keep listener sets here so they survive
  // socket reconnects — the old socket's listeners are torn down with
  // it, but user subscriptions persist across reconnects and are
  // re-attached when a new socket comes up.
  const txListeners = useRef(new Set<(p: AssistantTranscriptPayload) => void>())
  const fillerListeners = useRef(new Set<(p: AssistantFillerPayload) => void>())
  const bcListeners = useRef(new Set<(p: AssistantBackchannelPayload) => void>())

  // Ref'd primitive so the session-create effect doesn't re-trigger
  // when the request object identity changes every render.
  const requestRef = useRef(request)
  useEffect(() => { requestRef.current = request }, [request])

  // Main lifecycle. Runs once per (enabled, backendUrl, authToken)
  // triple — which is what we want: flipping enabled true/false
  // drives open/close; swapping backendUrl or re-auth reconnects.
  useEffect(() => {
    if (!enabled) return

    let disposed = false
    const teardown = () => {
      disposed = true
      socketRef.current?.dispose('unmounted')
      socketRef.current = null
      sessionRef.current = null
    }

    const run = async () => {
      setStatus('creating')
      setLastError(null)
      setCloseReason(null)
      setCallState(null)

      let handshake: CreateCallSessionResponse
      try {
        handshake = await createCallSession(backendUrl, requestRef.current, authToken)
      } catch (err) {
        if (disposed) return
        if (err instanceof CallApiError && err.isUnavailable) {
          setStatus('unavailable')
          return
        }
        setStatus('error')
        setLastError(err instanceof Error ? err.message : String(err))
        return
      }
      if (disposed) return

      sessionRef.current = handshake
      const url = resolveWsUrl(
        handshake.ws_url,
        handshake.session_id,
        handshake.resume_token,
        authToken,
        backendUrl,
      )

      const sock = new CallSocket({ url })
      socketRef.current = sock

      // Translate socket lifecycle → hook status.
      sock.on('statusChange', (s: CallLifecycleStatus) => {
        if (disposed) return
        setStatus(s === 'idle' ? 'idle' : s)
      })
      sock.on('callState', (p) => {
        if (disposed) return
        setCallState(p.status)
      })
      sock.on('closed', ({ reason }) => {
        if (disposed) return
        setStatus('closed')
        setCloseReason(reason)
      })
      sock.on('serverError', (p) => {
        // Non-terminal by contract; surface for the UI but keep the
        // socket open. The server will close explicitly if fatal.
        if (disposed) return
        setLastError(`${p.code}: ${p.message}`)
      })
      sock.on('assistantTranscript', (p) => {
        for (const fn of txListeners.current) fn(p)
      })
      sock.on('assistantFiller', (p) => {
        for (const fn of fillerListeners.current) fn(p)
      })
      sock.on('assistantBackchannel', (p) => {
        for (const fn of bcListeners.current) fn(p)
      })

      sock.connect()
    }

    void run()
    return teardown
  }, [enabled, backendUrl, authToken])

  // Public actions. Guarded against stale-socket calls. --------------

  const sendTranscript = useCallback((text: string) => {
    const sock = socketRef.current
    if (!sock) return
    const trimmed = text.trim()
    if (!trimmed) return
    sock.sendTranscript({ text: trimmed })
  }, [])

  const end = useCallback(() => {
    socketRef.current?.end()
  }, [])

  const sendUiState = useCallback(
    (p: { muted?: boolean; speaker_on?: boolean; backgrounded?: boolean }) => {
      socketRef.current?.sendUiState(p)
    },
    [],
  )

  const onAssistantTranscript = useCallback(
    (fn: (p: AssistantTranscriptPayload) => void) => {
      txListeners.current.add(fn)
      return () => { txListeners.current.delete(fn) }
    }, [],
  )
  const onAssistantFiller = useCallback(
    (fn: (p: AssistantFillerPayload) => void) => {
      fillerListeners.current.add(fn)
      return () => { fillerListeners.current.delete(fn) }
    }, [],
  )
  const onAssistantBackchannel = useCallback(
    (fn: (p: AssistantBackchannelPayload) => void) => {
      bcListeners.current.add(fn)
      return () => { bcListeners.current.delete(fn) }
    }, [],
  )

  return useMemo<CallSessionHandle>(() => ({
    status,
    callState,
    closeReason,
    lastError,
    sendTranscript,
    end,
    sendUiState,
    onAssistantTranscript,
    onAssistantFiller,
    onAssistantBackchannel,
  }), [
    status, callState, closeReason, lastError,
    sendTranscript, end, sendUiState,
    onAssistantTranscript, onAssistantFiller, onAssistantBackchannel,
  ])
}
