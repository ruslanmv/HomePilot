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

export interface CreateCallSessionRequest {
  /** Existing chat conversation id to link this call to. Optional.
   *  The backend will create an ephemeral conversation if omitted. */
  conversation_id?: string | null
  /** Persona to carry into the turn. Null = assistant default. */
  persona_id?: string | null
  /** How the call was initiated. Matches backend CreateSessionReq. */
  entry_mode?: 'voice' | 'call' | 'handoff'
  /** Free-form client fingerprint (tz, platform, ua family). */
  device_info?: Record<string, unknown>
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
  /** Optional backend capability advertisement. */
  capabilities?: Record<string, unknown>
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
  const base = backendUrl.replace(/\/+$/, '')
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
