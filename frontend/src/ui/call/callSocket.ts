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

// ── Typed envelope contracts ───────────────────────────────────────
// Mirror the backend ws.py contract. Keep in sync with
// docs/analysis/voice-call-human-simulation-design.md § 6.

export type CallLifecycleStatus =
  | 'idle'
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'draining'
  | 'closed'

export type CallCloseReason =
  | 'user_ended'
  | 'max_duration'
  | 'idle_timeout'
  | 'resume_expired'
  | 'bad_resume_token'
  | 'session_not_found'
  | 'session_ended'
  | 'websocket_disabled'
  | 'network_error'
  | 'unmounted'
  | 'unknown'

export interface ServerEnvelope<
  T extends string = string,
  P extends Record<string, unknown> = Record<string, unknown>,
> {
  type: T
  seq: number
  ts: number
  payload: P
}

// Server → client event payloads. One type per server `type`; if
// the backend ever adds a new event, it lands in `unknown` and is
// dropped — not a runtime crash.

export interface CallStatePayload {
  status: 'live' | 'ending' | 'ended'
  reason?: 'user_ended' | 'idle' | 'max_duration'
  since?: number
}
export interface AssistantTranscriptPayload {
  role: 'assistant'
  text: string
}
export interface AssistantFillerPayload {
  token: string
  ts?: number
  session_id?: string
}
export interface AssistantBackchannelPayload {
  token: string
  volume_db?: number
  ts?: number
}
export interface ServerErrorPayload {
  code: string
  message: string
}

// Client → server. Keep the types literal so the compiler catches
// typos at the send() call site.

export interface UiStatePayload {
  muted?: boolean
  speaker_on?: boolean
  backgrounded?: boolean
}
export interface TranscriptFinalPayload {
  text: string
  model?: string
  lang?: string
}
export type CallControlAction = 'end' | 'ping'

// ── Typed event bus for callers ────────────────────────────────────

export interface CallSocketEventMap {
  statusChange: CallLifecycleStatus
  callState: CallStatePayload
  assistantTranscript: AssistantTranscriptPayload
  assistantFiller: AssistantFillerPayload
  assistantBackchannel: AssistantBackchannelPayload
  serverError: ServerErrorPayload
  safetyNotice: Record<string, unknown>
  pong: void
  closed: { reason: CallCloseReason; code?: number; detail?: string }
}

type Listener<E extends keyof CallSocketEventMap> = (
  payload: CallSocketEventMap[E],
) => void

// ── Backoff helper (AWS-style full jitter) ─────────────────────────

function backoffMs(attempt: number, baseMs = 500, capMs = 10_000): number {
  const exp = Math.min(capMs, baseMs * 2 ** attempt)
  return Math.floor(Math.random() * exp)
}

// ── Close-code → reason mapping ────────────────────────────────────

const POLICY_VIOLATION = 1008
const NORMAL_CLOSURE = 1000

function closeReasonFrom(code: number | undefined, text: string): CallCloseReason {
  const reason = (text || '').toLowerCase()
  if (code === POLICY_VIOLATION) {
    if (reason.includes('resume-expired')) return 'resume_expired'
    if (reason.includes('bad-resume-token')) return 'bad_resume_token'
    if (reason.includes('session-not-found')) return 'session_not_found'
    if (reason.includes('session-ended')) return 'session_ended'
    if (reason.includes('websocket-disabled')) return 'websocket_disabled'
  }
  if (code === NORMAL_CLOSURE && reason.includes('max-duration')) return 'max_duration'
  if (reason.includes('idle')) return 'idle_timeout'
  return 'unknown'
}

// ── Construction options ───────────────────────────────────────────

export interface CallSocketOptions {
  /** Fully-resolved WS URL including ?resume_token=… and ?token=…. */
  url: string
  /** How long the backend will honour a resume. Used to decide when to
   *  give up reconnecting. Default 20 s (matches VOICE_CALL_RESUME_WINDOW_SEC). */
  resumeWindowSec?: number
  /** How often we send a client-originated ping. Default 15 s. */
  heartbeatIntervalMs?: number
  /** Dependency injection for tests — defaults to global WebSocket. */
  webSocketImpl?: typeof WebSocket
  /** Structured log sink. Defaults to console.{info,warn,error} with
   *  any `resume_token`, `token`, or `jwt` fields redacted by the
   *  caller. Keep string-typed; don't pass raw envelopes in. */
  log?: {
    info: (msg: string, extra?: Record<string, unknown>) => void
    warn: (msg: string, extra?: Record<string, unknown>) => void
    error: (msg: string, extra?: Record<string, unknown>) => void
  }
}

// ── CallSocket class ───────────────────────────────────────────────

export class CallSocket {
  private ws: WebSocket | null = null
  private status: CallLifecycleStatus = 'idle'
  private lastServerSeq = 0
  private outboundQueue: string[] = []
  private heartbeatTimer: number | null = null
  private lastServerActivityMs = 0
  private deadPeerTimer: number | null = null
  private reconnectAttempt = 0
  private reconnectTimer: number | null = null
  private connectedAtMs = 0
  private shuttingDown = false

  private readonly listeners: {
    [K in keyof CallSocketEventMap]?: Set<Listener<K>>
  } = {}

  private readonly url: string
  private readonly resumeWindowMs: number
  private readonly heartbeatIntervalMs: number
  private readonly WebSocketImpl: typeof WebSocket
  private readonly log: NonNullable<CallSocketOptions['log']>

  constructor(opts: CallSocketOptions) {
    this.url = opts.url
    this.resumeWindowMs = (opts.resumeWindowSec ?? 20) * 1000
    this.heartbeatIntervalMs = opts.heartbeatIntervalMs ?? 15_000
    this.WebSocketImpl = opts.webSocketImpl ?? WebSocket
    this.log = opts.log ?? {
      info: (m, e) => console.info(`[callSocket] ${m}`, e ?? ''),
      warn: (m, e) => console.warn(`[callSocket] ${m}`, e ?? ''),
      error: (m, e) => console.error(`[callSocket] ${m}`, e ?? ''),
    }
  }

  // Public API ----------------------------------------------------

  getStatus(): CallLifecycleStatus { return this.status }

  on<E extends keyof CallSocketEventMap>(evt: E, fn: Listener<E>): () => void {
    let set = this.listeners[evt] as Set<Listener<E>> | undefined
    if (!set) {
      set = new Set<Listener<E>>()
      // Narrow through `as unknown` — TS can't track the generic
      // discriminant through the indexed property set.
      ;(this.listeners as Record<string, unknown>)[evt] = set
    }
    set.add(fn)
    return () => set!.delete(fn)
  }

  /** Open the socket. Safe to call exactly once per instance. */
  connect(): void {
    if (this.status !== 'idle') {
      this.log.warn('connect() called in non-idle state', { status: this.status })
      return
    }
    this.openSocket()
  }

  /** Send the captured user transcript as a chat turn. Queued if the
   *  socket is currently mid-reconnect. */
  sendTranscript(p: TranscriptFinalPayload): void {
    this.enqueueLine({ type: 'transcript.final', ts: Date.now(), payload: p })
  }

  /** Bookkeeping — muted, speaker on/off, app backgrounded. */
  sendUiState(p: UiStatePayload): void {
    this.enqueueLine({ type: 'ui.state', ts: Date.now(), payload: p })
  }

  /** Control channel — 'ping' requests a pong; 'end' terminates. */
  sendControl(action: CallControlAction): void {
    this.enqueueLine({ type: 'call.control', ts: Date.now(), payload: { action } })
  }

  /** Graceful user-initiated end. Sends control 'end', then closes. */
  end(): void {
    if (this.shuttingDown) return
    this.shuttingDown = true
    this.transition('draining')
    this.sendControl('end')
    // Give the server ~400 ms to echo call.state {status:'ended'}
    // before we force-close; prevents the socket from looking
    // orphaned in backend logs.
    window.setTimeout(() => this.dispose('user_ended'), 400)
  }

  /** Teardown without a control 'end' — used when the component
   *  unmounts, the user navigates away, or a terminal error occurs. */
  dispose(reason: CallCloseReason = 'unmounted', code = NORMAL_CLOSURE): void {
    if (this.status === 'closed') return
    this.shuttingDown = true
    this.clearTimers()
    try { this.ws?.close(code, reason) } catch { /* already closed */ }
    this.ws = null
    this.outboundQueue = []
    this.transition('closed')
    this.emit('closed', { reason, code })
  }

  // Socket lifecycle ----------------------------------------------

  private openSocket(): void {
    this.transition(this.reconnectAttempt === 0 ? 'connecting' : 'reconnecting')
    let ws: WebSocket
    try {
      ws = new this.WebSocketImpl(this.url)
    } catch (err) {
      this.log.error('WebSocket constructor threw', { err: String(err) })
      this.scheduleReconnect()
      return
    }
    this.ws = ws
    this.lastServerActivityMs = Date.now()

    ws.addEventListener('open', () => {
      this.reconnectAttempt = 0
      this.connectedAtMs = Date.now()
      this.transition('live')
      this.startHeartbeat()
      this.flushQueue()
    })

    ws.addEventListener('message', (ev) => this.onMessage(ev))

    ws.addEventListener('close', (ev) => this.onClose(ev))

    ws.addEventListener('error', () => {
      // The browser fires `error` right before `close` on network
      // failures. We don't transition here — onClose() decides
      // reconnect vs terminal based on the code.
      this.log.warn('socket error event')
    })
  }

  private onMessage(ev: MessageEvent): void {
    this.lastServerActivityMs = Date.now()
    if (typeof ev.data !== 'string') return

    let env: ServerEnvelope | null = null
    try {
      env = JSON.parse(ev.data) as ServerEnvelope
    } catch {
      this.log.warn('non-JSON frame dropped')
      return
    }
    if (!env || typeof env.type !== 'string') return

    // Monotonic seq validation. If the server ever ships out-of-order
    // frames we log once and keep going — correctness trumps strictness.
    if (typeof env.seq === 'number' && env.seq <= this.lastServerSeq) {
      this.log.warn('non-monotonic seq', {
        got: env.seq, last: this.lastServerSeq, type: env.type,
      })
    } else if (typeof env.seq === 'number') {
      this.lastServerSeq = env.seq
    }

    this.dispatch(env)
  }

  private dispatch(env: ServerEnvelope): void {
    const raw = env.payload as unknown
    switch (env.type) {
      case 'call.state': {
        const p = raw as CallStatePayload
        this.emit('callState', p)
        if (p.status === 'ended') this.dispose('user_ended')
        return
      }
      case 'transcript.final':
        this.emit('assistantTranscript', raw as AssistantTranscriptPayload)
        return
      case 'assistant.filler':
        this.emit('assistantFiller', raw as AssistantFillerPayload)
        return
      case 'assistant.backchannel':
        this.emit('assistantBackchannel', raw as AssistantBackchannelPayload)
        return
      case 'safety.notice':
        this.emit('safetyNotice', env.payload)
        return
      case 'error':
        this.emit('serverError', raw as ServerErrorPayload)
        return
      case 'pong':
        this.emit('pong', undefined as void)
        return
      case 'ping':
        // Server heartbeat — immediately echo to keep the liveness
        // counters tight on both ends.
        this.sendControl('ping')
        return
      default:
        // Forward-compat: unknown event types are no-ops.
        this.log.info(`unknown server event: ${env.type}`)
    }
  }

  private onClose(ev: CloseEvent): void {
    const reason = closeReasonFrom(ev.code, ev.reason)
    this.clearTimers()

    // Terminal close codes: don't reconnect.
    const terminal: ReadonlySet<CallCloseReason> = new Set([
      'user_ended',
      'max_duration',
      'resume_expired',
      'bad_resume_token',
      'session_not_found',
      'session_ended',
      'websocket_disabled',
    ])
    if (this.shuttingDown || terminal.has(reason)) {
      this.ws = null
      this.transition('closed')
      this.emit('closed', { reason, code: ev.code, detail: ev.reason })
      return
    }

    // Transient — try to reconnect within the resume window.
    this.log.warn('socket dropped; scheduling reconnect', {
      code: ev.code, reason: ev.reason,
    })
    this.ws = null
    this.scheduleReconnect()
  }

  private scheduleReconnect(): void {
    if (this.shuttingDown) return
    const sinceLiveMs = this.connectedAtMs > 0 ? Date.now() - this.connectedAtMs : 0
    if (sinceLiveMs > this.resumeWindowMs) {
      this.log.warn('resume window elapsed; giving up')
      this.dispose('resume_expired', POLICY_VIOLATION)
      return
    }
    const delay = backoffMs(this.reconnectAttempt)
    this.reconnectAttempt += 1
    this.transition('reconnecting')
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.openSocket()
    }, delay)
  }

  // Queue + heartbeat ---------------------------------------------

  private enqueueLine(env: { type: string; ts: number; payload: unknown }): void {
    const line = JSON.stringify(env)
    if (this.status === 'live' && this.ws?.readyState === this.WebSocketImpl.OPEN) {
      try { this.ws.send(line) } catch (err) {
        this.log.warn('send failed; queueing', { err: String(err) })
        this.outboundQueue.push(line)
      }
    } else {
      this.outboundQueue.push(line)
    }
  }

  private flushQueue(): void {
    if (!this.ws || this.ws.readyState !== this.WebSocketImpl.OPEN) return
    const q = this.outboundQueue
    this.outboundQueue = []
    for (const line of q) {
      try { this.ws.send(line) } catch (err) {
        this.log.error('flush failed; re-queueing remaining', { err: String(err) })
        this.outboundQueue.push(line)
        return
      }
    }
  }

  private startHeartbeat(): void {
    this.clearHeartbeat()
    this.heartbeatTimer = window.setInterval(() => {
      this.sendControl('ping')
    }, this.heartbeatIntervalMs)

    // Dead-peer watchdog — if we haven't heard from the server in
    // 2× the heartbeat interval, force a reconnect. Avoids hanging
    // forever on half-open TCP sockets (mobile NAT rebinds).
    this.deadPeerTimer = window.setInterval(() => {
      if (Date.now() - this.lastServerActivityMs > this.heartbeatIntervalMs * 2) {
        this.log.warn('peer silent; forcing reconnect')
        try { this.ws?.close() } catch { /* ignore */ }
      }
    }, this.heartbeatIntervalMs)
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
    if (this.deadPeerTimer !== null) {
      window.clearInterval(this.deadPeerTimer)
      this.deadPeerTimer = null
    }
  }

  private clearTimers(): void {
    this.clearHeartbeat()
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  // Emit + state transition ---------------------------------------

  private emit<E extends keyof CallSocketEventMap>(
    evt: E, payload: CallSocketEventMap[E],
  ): void {
    const set = this.listeners[evt] as Set<Listener<E>> | undefined
    if (!set) return
    for (const fn of set) {
      try { fn(payload) } catch (err) {
        this.log.error('listener threw', { evt, err: String(err) })
      }
    }
  }

  private transition(next: CallLifecycleStatus): void {
    if (this.status === next) return
    this.status = next
    this.emit('statusChange', next)
  }
}
