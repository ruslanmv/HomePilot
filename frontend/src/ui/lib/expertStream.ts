/**
 * The Expert stream, read the way ChatGPT and Claude read theirs: tokens as they arrive,
 * the pipeline's steps, "Searching the web…" chips for tool calls, numbered sources, the
 * validator's verdict — and the same for a Deep research job's events.
 *
 * Wire format (`POST /v1/expert/stream`, server-sent events):
 *   event: meta | step | step_end | tool | sources | reset | notice | verdict | final_answer | done | error
 *   data: <json>                       for the named events (final_answer's data is "start")
 *   data: <token with \n escaped>      a token (no event line); belongs to the active step,
 *                                      or to the answer after final_answer / in fast mode
 *   data: [DONE]                       end of stream
 */

export type ExpertStep = {
  step: string
  label: string
  role: 'work' | 'answer'
  status: 'running' | 'done'
  content: string
  provider?: string
}

export type ExpertToolChip = {
  id: string
  name: string
  label: string
  status: 'running' | 'done' | 'failed'
  summary?: string
  elapsed_ms?: number
  step?: string
}

export type ExpertSource = { n: number; title: string; url: string; domain?: string; snippet?: string; published?: string }

export type ExpertVerdict = {
  verdict: string
  note: string
  issues?: Array<{ severity: string; text: string }>
  method?: string
  limitations?: string
}

/** What a message keeps of the work behind it (rendered by ExpertSteps, persisted in media.expert). */
export type ExpertTrace = {
  mode?: string
  model?: string | null
  steps: ExpertStep[]
  tools: ExpertToolChip[]
  sources: ExpertSource[]
  notices: string[]
  verdict?: ExpertVerdict | null
  /** Deep research: the plan items, with their status. */
  plan?: Array<{ id: string; title: string; status: string; summary?: string; sources?: number[] }>
  status?: string
  elapsed_s?: number
  /** The project the turn ran inside, when any. */
  project?: { id: string; name?: string | null } | null
  /** How much of the mode this message spent, and why (policies.effort_for). */
  effort?: { level: string; reason: string } | null
  /** Set while the turn waits in line or waits out a rate limit ("The model provider is busy;
   *  retrying in 8 s…"); cleared by the next event of any other kind. Never persisted. */
  waiting?: string | null
  /** Set while the server summarizes the earlier conversation to fit the model's context
   *  ("Compacting the conversation: summarizing 8 earlier messages…"); cleared by the next
   *  event. The lasting record is the COMPACTED_NOTE notice. Never persisted. */
  compacting?: string | null
}

type ExpertEventBody =
  | { type: 'meta'; data: Record<string, unknown> }
  | { type: 'step'; step: string; label: string; role: 'work' | 'answer'; provider?: string }
  | { type: 'step_end'; step: string }
  | { type: 'tool'; phase: 'start' | 'end'; id: string; name: string; label: string; ok?: boolean; summary?: string; elapsed_ms?: number; step?: string }
  | { type: 'sources'; sources: ExpertSource[] }
  | { type: 'reset'; step?: string }
  | { type: 'notice'; text: string }
  | { type: 'wait'; text: string; retry_in?: number }
  | { type: 'compacting'; text: string; turns?: number }
  | { type: 'verdict'; verdict: string; note: string; detail?: Record<string, unknown> }
  | { type: 'final_answer' }
  | { type: 'token'; text: string }
  | { type: 'done'; data: Record<string, unknown> }
  | { type: 'error'; error: string }
  | { type: 'end' }
  // Deep research job events
  | { type: 'status'; status: string }
  | { type: 'plan'; items: Array<{ id: string; title: string; status: string }> }
  | { type: 'item'; id: string; status: string; title?: string; summary?: string; sources?: number[] }
  | { type: 'cancelled' }

/** Every event may carry the server's sequence number (`id:` line), used to resume a job. */
export type ExpertEvent = ExpertEventBody & { seq?: number }

const UNESCAPE = /\\n/g

/** Shown in the trace when the server summarized older turns (compaction.py). */
export const COMPACTED_NOTE = 'Earlier conversation summarized to fit the model’s context.'

function parseJson(payload: string): Record<string, unknown> | null {
  try {
    const v = JSON.parse(payload)
    return v && typeof v === 'object' ? (v as Record<string, unknown>) : null
  } catch {
    return null
  }
}

/** One SSE block (the lines between two blank lines) → an event, or null for noise. */
export function parseSseBlock(block: string): ExpertEvent | null {
  const body = parseSseBody(block)
  return body
}

function parseSseBody(block: string): ExpertEvent | null {
  let name = ''
  let seq: number | undefined
  const data: string[] = []
  for (const rawLine of block.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (line.startsWith(':')) continue                       // keep-alive comment
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('id:')) { const n = Number(line.slice(3).trim()); if (Number.isFinite(n)) seq = n }
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
  }
  if (!data.length) return null
  const ev = parseNamed(name, data.join('\n'))
  return ev && seq !== undefined ? { ...ev, seq } : ev
}

function parseNamed(name: string, payload: string): ExpertEvent | null {
  if (!name) {
    if (payload === '[DONE]') return { type: 'end' }
    return { type: 'token', text: payload.replace(UNESCAPE, '\n') }
  }
  if (name === 'final_answer') return { type: 'final_answer' }
  const obj = parseJson(payload)
  if (!obj) return null
  switch (name) {
    case 'meta': return { type: 'meta', data: obj }
    case 'done': return { type: 'done', data: obj }
    case 'step': return { type: 'step', step: String(obj.step ?? ''), label: String(obj.label ?? ''), role: obj.role === 'answer' ? 'answer' : 'work', provider: obj.provider ? String(obj.provider) : undefined }
    case 'step_end': return { type: 'step_end', step: String(obj.step ?? '') }
    case 'tool': return {
      type: 'tool', phase: obj.phase === 'end' ? 'end' : 'start', id: String(obj.id ?? obj.name ?? ''), name: String(obj.name ?? ''),
      label: String(obj.label ?? obj.name ?? ''), ok: typeof obj.ok === 'boolean' ? obj.ok : undefined,
      summary: obj.summary ? String(obj.summary) : undefined, elapsed_ms: typeof obj.elapsed_ms === 'number' ? obj.elapsed_ms : undefined,
      step: obj.step ? String(obj.step) : undefined,
    }
    case 'sources': return { type: 'sources', sources: Array.isArray(obj.sources) ? (obj.sources as ExpertSource[]) : [] }
    case 'reset': return { type: 'reset', step: obj.step ? String(obj.step) : undefined }
    case 'notice': return { type: 'notice', text: String(obj.text ?? '') }
    case 'wait': return { type: 'wait', text: String(obj.text ?? ''), retry_in: typeof obj.retry_in === 'number' ? obj.retry_in : undefined }
    case 'compacting': return { type: 'compacting', text: String(obj.text ?? '') || 'Compacting the conversation…', turns: typeof obj.turns === 'number' ? obj.turns : undefined }
    case 'verdict': return { type: 'verdict', verdict: String(obj.verdict ?? ''), note: String(obj.note ?? ''), detail: obj.detail && typeof obj.detail === 'object' ? (obj.detail as Record<string, unknown>) : undefined }
    case 'error': return { type: 'error', error: String(obj.error ?? 'error') }
    case 'status': return { type: 'status', status: String(obj.status ?? '') }
    case 'plan': return { type: 'plan', items: Array.isArray(obj.items) ? (obj.items as Array<{ id: string; title: string; status: string }>) : [] }
    case 'item': return { type: 'item', id: String(obj.id ?? ''), status: String(obj.status ?? ''), title: obj.title ? String(obj.title) : undefined, summary: obj.summary ? String(obj.summary) : undefined, sources: Array.isArray(obj.sources) ? (obj.sources as number[]) : undefined }
    case 'token': return { type: 'token', text: String(obj.content ?? '') }
    case 'cancelled': return { type: 'cancelled' }
    default: return null
  }
}

/** Split a buffer into complete blocks; the remainder waits for more bytes. */
export function parseExpertSse(buffer: string): { events: ExpertEvent[]; rest: string } {
  const events: ExpertEvent[] = []
  let rest = buffer
  let idx: number
  while ((idx = rest.indexOf('\n\n')) >= 0) {
    const block = rest.slice(0, idx)
    rest = rest.slice(idx + 2)
    const ev = parseSseBlock(block)
    if (ev) events.push(ev)
  }
  return { events, rest }
}

export type ExpertStreamState = {
  /** The reply as it stands: fast-mode tokens, or the final answer once it arrives. */
  text: string
  trace: ExpertTrace
  /** Tokens go to the answer (fast mode, after final_answer) or to the active step. */
  answering: boolean
  activeStep: string | null
  done: boolean
  error: string | null
  final: Record<string, unknown> | null
  /** The last sequence number seen (Deep research jobs), for resuming without duplicates. */
  lastSeq: number
}

export function initialExpertState(mode?: string): ExpertStreamState {
  return {
    text: '',
    trace: { mode, steps: [], tools: [], sources: [], notices: [], verdict: null },
    answering: mode === 'fast' || mode === undefined,
    activeStep: null,
    done: false,
    error: null,
    final: null,
    lastSeq: 0,
  }
}

/** Pure: the state after one event. The app renders the message from this. A `wait` event
 *  sets the transient waiting line; any other event means the wait is over and clears it. */
export function applyExpertEvent(previous: ExpertStreamState, ev: ExpertEvent): ExpertStreamState {
  if (ev.type === 'wait' || ev.type === 'compacting') {
    const state = typeof ev.seq === 'number' && ev.seq > previous.lastSeq ? { ...previous, lastSeq: ev.seq } : previous
    return ev.type === 'wait'
      ? { ...state, trace: { ...state.trace, waiting: ev.text || null } }
      : { ...state, trace: { ...state.trace, compacting: ev.text || 'Compacting the conversation…' } }
  }
  const next = applyEvent(previous, ev)
  return next.trace.waiting || next.trace.compacting
    ? { ...next, trace: { ...next.trace, waiting: null, compacting: null } }
    : next
}

function applyEvent(previous: ExpertStreamState, ev: ExpertEvent): ExpertStreamState {
  const state = typeof ev.seq === 'number' && ev.seq > previous.lastSeq ? { ...previous, lastSeq: ev.seq } : previous
  const trace = state.trace
  switch (ev.type) {
    case 'meta': {
      const mode = typeof ev.data.thinking_mode === 'string' ? ev.data.thinking_mode : trace.mode
      const notices = Array.isArray(ev.data.notices) ? [...(ev.data.notices as string[])] : []
      if (ev.data.compacted === true) notices.push(COMPACTED_NOTE)
      const effortRaw = ev.data.effort && typeof ev.data.effort === 'object' ? (ev.data.effort as Record<string, unknown>) : null
      const projectRaw = ev.data.project && typeof ev.data.project === 'object' ? (ev.data.project as Record<string, unknown>) : null
      // A direct answer in Expert or Heavy is one generation: tokens are the answer.
      const direct = effortRaw?.level === 'direct'
      return {
        ...state,
        answering: mode === 'fast' || direct,
        trace: {
          ...trace, mode,
          model: typeof ev.data.model === 'string' ? ev.data.model : trace.model,
          notices: uniq([...trace.notices, ...notices]),
          effort: effortRaw ? { level: String(effortRaw.level ?? ''), reason: String(effortRaw.reason ?? '') } : trace.effort ?? null,
          project: projectRaw && typeof projectRaw.id === 'string' ? { id: projectRaw.id, name: typeof projectRaw.name === 'string' ? projectRaw.name : null } : trace.project ?? null,
        },
      }
    }
    case 'step': {
      const steps = trace.steps.map((s) => (s.status === 'running' ? { ...s, status: 'done' as const } : s))
      steps.push({ step: ev.step, label: ev.label, role: ev.role, status: 'running', content: '', provider: ev.provider })
      return { ...state, activeStep: ev.step, answering: false, trace: { ...trace, steps } }
    }
    case 'step_end':
      return {
        ...state,
        activeStep: state.activeStep === ev.step ? null : state.activeStep,
        trace: { ...trace, steps: trace.steps.map((s) => (s.step === ev.step ? { ...s, status: 'done' } : s)) },
      }
    case 'token': {
      if (state.answering || !state.activeStep) return { ...state, text: state.text + ev.text }
      const steps = trace.steps.map((s) => (s.step === state.activeStep ? { ...s, content: s.content + ev.text } : s))
      return { ...state, trace: { ...trace, steps } }
    }
    case 'reset': {
      if (state.answering || !state.activeStep) return { ...state, text: '' }
      const steps = trace.steps.map((s) => (s.step === state.activeStep ? { ...s, content: '' } : s))
      return { ...state, trace: { ...trace, steps } }
    }
    case 'tool': {
      const tools = [...trace.tools]
      const at = tools.findIndex((t) => t.id === ev.id)
      const chip: ExpertToolChip = {
        id: ev.id, name: ev.name, label: ev.label, step: ev.step ?? state.activeStep ?? undefined,
        status: ev.phase === 'start' ? 'running' : ev.ok === false ? 'failed' : 'done',
        summary: ev.summary, elapsed_ms: ev.elapsed_ms,
      }
      if (at >= 0) tools[at] = { ...tools[at], ...chip, label: tools[at].label || chip.label }
      else tools.push(chip)
      return { ...state, trace: { ...trace, tools } }
    }
    case 'sources':
      return { ...state, trace: { ...trace, sources: ev.sources } }
    case 'notice':
      return { ...state, trace: { ...trace, notices: uniq([...trace.notices, ev.text]) } }
    case 'verdict': {
      const d = ev.detail ?? {}
      const issues = Array.isArray(d.issues)
        ? (d.issues as Array<Record<string, unknown>>).map((i) => ({ severity: String(i.severity ?? 'medium'), text: String(i.text ?? '') })).filter((i) => i.text)
        : undefined
      return { ...state, trace: { ...trace, verdict: {
        verdict: ev.verdict, note: ev.note, issues,
        method: typeof d.method === 'string' ? d.method : undefined,
        limitations: typeof d.limitations === 'string' && d.limitations ? d.limitations : undefined,
      } } }
    }
    case 'final_answer':
      return { ...state, text: '', answering: true, activeStep: null }
    case 'done': {
      const content = typeof ev.data.content === 'string' ? ev.data.content : null
      const sources = Array.isArray(ev.data.sources) ? (ev.data.sources as ExpertSource[]) : trace.sources
      const notices = Array.isArray(ev.data.notices) ? (ev.data.notices as string[]) : trace.notices
      const verdict = typeof ev.data.verdict === 'string' ? { ...(trace.verdict ?? { note: '' }), verdict: ev.data.verdict } : trace.verdict
      const elapsed_s = typeof ev.data.latency_ms === 'number' ? Math.round(ev.data.latency_ms / 100) / 10 : trace.elapsed_s
      return {
        ...state, done: true, final: ev.data,
        text: content !== null && content !== '' ? content : state.text,
        trace: { ...trace, sources, notices: uniq(notices), verdict, elapsed_s, steps: trace.steps.map((s) => ({ ...s, status: 'done' as const })) },
      }
    }
    case 'error':
      return { ...state, error: ev.error, done: true }
    case 'end':
      return { ...state, done: true }
    // Deep research job events
    case 'status':
      return { ...state, answering: ev.status === 'writing', trace: { ...trace, status: ev.status } }
    case 'plan':
      return { ...state, trace: { ...trace, plan: ev.items.map((i) => ({ ...i })) } }
    case 'item': {
      const plan = (trace.plan ?? []).map((p) => (p.id === ev.id ? { ...p, status: ev.status, summary: ev.summary ?? p.summary, sources: ev.sources ?? p.sources } : p))
      if (!plan.some((p) => p.id === ev.id) && ev.title) plan.push({ id: ev.id, title: ev.title, status: ev.status, summary: ev.summary, sources: ev.sources })
      return { ...state, trace: { ...trace, plan } }
    }
    case 'cancelled':
      return { ...state, done: true, error: 'Cancelled', trace: { ...trace, status: 'cancelled' } }
    default:
      return state
  }
}

/** The Deep research `done` event carries the report and the plan. */
export function applyDeepDone(state: ExpertStreamState, data: Record<string, unknown>): ExpertStreamState {
  const next = applyExpertEvent(state, { type: 'done', data: { ...data, content: data.report } })
  const plan = Array.isArray(data.plan) ? (data.plan as ExpertTrace['plan']) : next.trace.plan
  return { ...next, trace: { ...next.trace, plan, status: 'done', elapsed_s: typeof data.elapsed_s === 'number' ? data.elapsed_s : undefined } }
}

function uniq(items: string[]): string[] {
  return items.filter((x, i) => x && items.indexOf(x) === i)
}

/** Sources as the chat's WebSources component shows them (same shape as web_search.py). */
export function sourcesAsWeb(trace: ExpertTrace): { status: 'ok'; query: string; sources: ExpertSource[] } | null {
  if (!trace.sources.length) return null
  const search = trace.tools.find((t) => /search/i.test(t.label) && /web/i.test(t.label))
  const query = search ? search.label.replace(/^Searching the web(?: for)?\s*/i, '').replace(/^[“"]|[”"]$/g, '') : ''
  return { status: 'ok', query, sources: trace.sources }
}

/** Whether the trace has anything to show yet (a stage, a tool, a plan). Before that, the
 *  bubble keeps its thinking skeleton so there is never a silent gap before the first token. */
export function traceHasWork(trace?: ExpertTrace | null): boolean {
  return Boolean(trace && (trace.steps.length || trace.tools.length || (trace.plan && trace.plan.length)))
}

/** A trace as persisted in a message's media (reload), or null when it is not one. */
export function parseExpertTrace(raw: unknown): ExpertTrace | null {
  if (!raw || typeof raw !== 'object') return null
  const t = raw as Record<string, unknown>
  if (!Array.isArray(t.steps) || !Array.isArray(t.tools)) return null
  return {
    mode: typeof t.mode === 'string' ? t.mode : undefined,
    model: typeof t.model === 'string' ? t.model : null,
    steps: t.steps as ExpertStep[],
    tools: t.tools as ExpertToolChip[],
    sources: Array.isArray(t.sources) ? (t.sources as ExpertSource[]) : [],
    notices: Array.isArray(t.notices) ? (t.notices as string[]) : [],
    verdict: t.verdict && typeof t.verdict === 'object' ? (t.verdict as ExpertTrace['verdict']) : null,
    plan: Array.isArray(t.plan) ? (t.plan as ExpertTrace['plan']) : undefined,
    status: typeof t.status === 'string' ? t.status : undefined,
    elapsed_s: typeof t.elapsed_s === 'number' ? t.elapsed_s : undefined,
    project: t.project && typeof t.project === 'object' ? (t.project as ExpertTrace['project']) : null,
    effort: t.effort && typeof t.effort === 'object' ? (t.effort as ExpertTrace['effort']) : null,
  }
}

export type StreamOptions = { signal?: AbortSignal; headers?: Record<string, string> }

/** Read an SSE response body, calling onEvent per event. Resolves when the stream ends. */
export async function readSse(res: Response, onEvent: (ev: ExpertEvent) => void): Promise<void> {
  if (!res.body) throw new Error(`HTTP ${res.status} ${res.statusText}: no body`)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const { events, rest } = parseExpertSse(buffer)
    buffer = rest
    for (const ev of events) onEvent(ev)
  }
  const { events } = parseExpertSse(buffer + '\n\n')
  for (const ev of events) onEvent(ev)
}

async function postStream(baseUrl: string, path: string, body: unknown, opts: StreamOptions): Promise<Response> {
  const res = await fetch(`${baseUrl.replace(/\/+$/, '')}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...(opts.headers || {}) },
    credentials: 'include',
    body: JSON.stringify(body),
    signal: opts.signal,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return res
}

/** POST /v1/expert/stream and feed the events to onEvent. Throws on an HTTP error (so the
 *  caller can tell a missing route from a stream that failed midway). */
export async function streamExpert(baseUrl: string, body: unknown, onEvent: (ev: ExpertEvent) => void, opts: StreamOptions = {}): Promise<void> {
  const res = await postStream(baseUrl, '/v1/expert/stream', body, opts)
  await readSse(res, onEvent)
}

export type DeepJobStart = { job_id: string; model?: string; notices?: string[] }

/** Start a Deep research job (POST /v1/expert/deep) and follow its events. `onStarted` gets
 *  the job id at once, so a Stop can cancel the job on the server as well. */
export async function streamDeepResearch(
  baseUrl: string,
  body: unknown,
  onEvent: (ev: ExpertEvent) => void,
  opts: StreamOptions & { onStarted?: (job: DeepJobStart) => void } = {},
): Promise<DeepJobStart> {
  const startRes = await postStream(baseUrl, '/v1/expert/deep', body, opts)
  const job = (await startRes.json()) as DeepJobStart
  opts.onStarted?.(job)
  await resumeDeepResearch(baseUrl, job.job_id, onEvent, opts)
  return job
}

/** Follow a Deep research job's events from `after` (0 = from the start). The server replays
 *  what was missed and then streams live; a finished job replays to its `done` at once. */
export async function resumeDeepResearch(
  baseUrl: string,
  jobId: string,
  onEvent: (ev: ExpertEvent) => void,
  opts: StreamOptions & { after?: number } = {},
): Promise<void> {
  const after = Math.max(0, Math.floor(opts.after ?? 0))
  const res = await fetch(
    `${baseUrl.replace(/\/+$/, '')}/v1/expert/deep/${encodeURIComponent(jobId)}/events${after ? `?after=${after}` : ''}`,
    {
      headers: { Accept: 'text/event-stream', ...(opts.headers || {}) },
      credentials: 'include',
      signal: opts.signal,
    },
  )
  if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`)
  await readSse(res, onEvent)
}
