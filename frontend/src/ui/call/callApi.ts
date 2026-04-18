/**
 * callApi.ts — REST wrapper for the voice_call session endpoint.
 *
 * Thin on purpose. Two responsibilities:
 *   1. POST /v1/voice-call/sessions with the right shape
 *   2. Normalize "feature unavailable" (404/501) vs hard errors
 *      so the hook can gracefully fall back to the chat-REST path
 *      when the backend has VOICE_CALL_ENABLED=false.
 *
 * Anything richer (envelope codec, seq bookkeeping, heartbeat,
 * reconnect) lives in callSocket.ts — keeping those concerns out of
 * this file is deliberate; the REST handshake runs once per call,
 * the socket lifecycle runs for every envelope.
 */

import { resolveBackendUrl } from '../lib/backendUrl'

export interface CreateCallSessionRequest {
  /** Existing chat conversation id to link this call to. Optional.
   *  The backend will create an ephemeral conversation if omitted. */
  conversation_id?: string | null
  /** Persona to carry into the turn. Null = assistant default. */
  persona_id?: string | null
  /** How the call was initiated. Matches backend CreateSessionReq. */
  entry_mode?: 'voice' | 'call' | 'handoff'
  /** Free-form client fingerprint (tz, platform, ua family).
   *  Also carries Phase 2/3 capability declarations:
   *    - ``streaming``  client can consume assistant.partial
   *    - ``barge_in``   client can detect user speech-start during
   *                     TTS playback and send ``user.barge_in``
   *  The effective streaming mode for the session is
   *  ``min(client_declared, server_advertised)`` — both ends must
   *  agree or the turn runs in unary mode. Mismatches degrade
   *  gracefully without a hard error. */
  device_info?: Record<string, unknown>
}

/** Server-advertised capabilities. Fields are optional so older
 *  servers (which don't emit them) are parsed safely and treated
 *  as "no". Used by useCallSession to decide whether to subscribe
 *  to the Phase 2 streaming events. */
export interface CallCapabilities {
  /** Server supports assistant.partial / assistant.turn_end /
   *  assistant.cancel envelopes. */
  streaming?: boolean
  /** Server honours user.barge_in / transcript.partial as cancel
   *  signals. Only meaningful when ``streaming`` is also true. */
  barge_in?: boolean
  /** Legacy fields (pre-streaming). Kept in the interface so
   *  existing consumers don't need to widen the type. */
  interruptions?: boolean
  transcript_live?: boolean
  [k: string]: unknown
}

export interface CreateCallSessionResponse {
  session_id: string
  /** Absolute or root-relative WebSocket URL to connect to. */
  ws_url: string
  /** Short-lived token the WS handshake must echo in its query. */
  resume_token: string
  /** When the session expires if never connected (ISO or epoch ms). */
  expires_at: string | number
  /** Hard cap enforced by the server. */
  max_duration_sec: number
  /** Backend capability advertisement (§ 3.1 of the streaming design). */
  capabilities?: CallCapabilities
}

/** Error raised for any non-2xx from /v1/voice-call/sessions. The
 *  `isUnavailable` flag distinguishes "backend hasn't enabled this
 *  feature yet" from real failures the UI should surface. */
export class CallApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly bodyText: string,
  ) {
    super(`voice-call session api ${status}${bodyText ? `: ${bodyText}` : ''}`)
    this.name = 'CallApiError'
  }
  /** 404 = route not mounted (VOICE_CALL_ENABLED=false).
   *  501 = feature recognized but disabled at runtime.
   *  The hook treats both as "fall back to chat REST". */
  get isUnavailable(): boolean {
    return this.status === 404 || this.status === 501
  }
}

export async function createCallSession(
  backendUrl: string,
  req: CreateCallSessionRequest,
  authToken?: string | null,
): Promise<CreateCallSessionResponse> {
  // Defensive resolution: when the caller passes an empty or
  // whitespace-only backend URL (e.g. a stale settings load), a
  // naive ``replace(/\/+$/, '')`` leaves us with ``''`` and fetch
  // falls back to the current page origin. On the Vite dev server
  // (:3000) that silently routes to the SPA, which returns
  // index.html and the subsequent JSON parse fails; in prod it can
  // hit the wrong origin entirely. ``resolveBackendUrl`` ignores
  // empty overrides and falls through to the app-wide resolver
  // (localStorage → VITE_API_URL → origin → ``http://localhost:8000``),
  // so we never accidentally issue a relative request.
  const base = resolveBackendUrl(backendUrl)
  const res = await fetch(`${base}/v1/voice-call/sessions`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(authToken ? { authorization: `Bearer ${authToken}` } : {}),
    },
    body: JSON.stringify({
      conversation_id: req.conversation_id ?? null,
      persona_id: req.persona_id ?? null,
      entry_mode: req.entry_mode ?? 'call',
      device_info: req.device_info ?? {},
    }),
    credentials: 'include',
  })

  if (!res.ok) {
    const bodyText = await res.text().catch(() => '')
    throw new CallApiError(res.status, bodyText)
  }

  const json = (await res.json()) as CreateCallSessionResponse
  if (!json?.session_id || !json?.resume_token || !json?.ws_url) {
    throw new CallApiError(res.status, 'malformed session payload')
  }
  return json
}

/** Declare the client's Phase 2/3 capabilities into the
 *  ``device_info`` blob. Set both to true in build configurations
 *  that include streamTts + bargeIn modules; set to false to run
 *  the session in forced-unary mode even against a streaming server
 *  (useful for bisecting regressions). */
export function clientStreamingCapabilities(
  base: Record<string, unknown>,
  enabled: boolean,
): Record<string, unknown> {
  if (!enabled) return base
  return { ...base, streaming: true, barge_in: true }
}

/** Compute the effective streaming mode from the server's capability
 *  response and the client's declared support. Truth table in § 3.1
 *  of docs/analysis/voice-call-streaming-design.md. */
export function effectiveStreamingMode(
  serverCaps: CallCapabilities | undefined,
  clientStreaming: boolean,
): { streaming: boolean; barge_in: boolean } {
  const streaming = !!(serverCaps?.streaming && clientStreaming)
  const barge_in = streaming && !!serverCaps?.barge_in
  return { streaming, barge_in }
}

/** Resolve a potentially-relative ws_url against the current page
 *  and the backend URL. Backends sometimes return `/v1/voice-call/ws`
 *  (path only) so the client can pick the right scheme + host. */
export function resolveWsUrl(
  wsUrl: string,
  sessionId: string,
  resumeToken: string,
  authToken: string | null,
  backendUrl: string,
): string {
  let url: URL
  if (/^wss?:\/\//i.test(wsUrl)) {
    url = new URL(wsUrl)
  } else if (wsUrl.startsWith('//')) {
    url = new URL(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}${wsUrl}`)
  } else if (wsUrl.startsWith('/')) {
    // Root-relative — derive scheme + host from backendUrl.
    const backend = new URL(backendUrl)
    const scheme = backend.protocol === 'https:' ? 'wss:' : 'ws:'
    url = new URL(`${scheme}//${backend.host}${wsUrl}`)
  } else {
    url = new URL(wsUrl, backendUrl)
  }

  // Inject session_id if the server gave us a template (rare) or
  // appended nothing; the standard shape is
  // /v1/voice-call/ws/{session_id}.
  if (!url.pathname.endsWith(sessionId)) {
    url.pathname = url.pathname.replace(/\/+$/, '') + `/${sessionId}`
  }
  url.searchParams.set('resume_token', resumeToken)
  if (authToken) url.searchParams.set('token', authToken)
  return url.toString()
}
