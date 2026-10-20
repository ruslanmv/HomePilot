/**
 * OllaBridge Local — browser-side client for the user's own OllaBridge gateway
 * (default http://localhost:11435, an OpenAI-compatible endpoint at /v1).
 *
 * Connecting checks `GET <root>/health` and then lists `GET <root>/v1/models`
 * straight from the browser. The gateway may run in "local-trust" mode (loopback
 * callers need no key) or "required" mode (Bearer / X-API-Key); an optional key
 * is sent only when the user entered one, and only to this gateway.
 *
 * When the browser is blocked by CORS (the gateway's CORS_ORIGINS does not list
 * this page) and the HomePilot backend runs on this same machine (loopback URL),
 * the listing falls back to HomePilot's existing `GET /models?provider=openai_compat`
 * route — the same server that will send the chat completions. It is never used
 * for a remote backend: that server's "localhost" is not the user's machine.
 */
import { normalizeLocalModels, type GatewayModel } from './models'

export const DEFAULT_LOCAL_GATEWAY = 'http://localhost:11435'

const LS_LOCAL_URL = 'homepilot_ollabridge_local_url'
const LS_LOCAL_CONNECTED = 'homepilot_ollabridge_local_connected'
const LS_LOCAL_KEY = 'homepilot_ollabridge_local_api_key'

const TIMEOUT_MS = 6000

// ── URLs ─────────────────────────────────────────────────────────────────────

/** `localhost:11435/v1/` → `http://localhost:11435` (the gateway root, no /v1). */
export function normalizeGatewayRoot(input: string): string {
  let s = (input || '').trim()
  if (!s) return ''
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = `http://${s}`
  return s.replace(/\/+$/, '').replace(/\/v1$/i, '').replace(/\/+$/, '')
}

/** Chat base URL HomePilot's openai_compat provider uses for this gateway. */
export function localChatBaseUrl(root: string): string {
  return `${normalizeGatewayRoot(root)}/v1`
}

export function isLoopbackHost(hostname: string): boolean {
  const h = hostname.replace(/^\[|\]$/g, '').toLowerCase()
  return h === 'localhost' || h.endsWith('.localhost') || h === '::1' || /^127\./.test(h)
}

function hostOf(url: string): string {
  try { return new URL(url).host } catch { return url }
}

function pageProtocol(): string {
  try { return window.location.protocol } catch { return 'http:' }
}

function pageOrigin(): string {
  try { return window.location.origin } catch { return '' }
}

// ── Persistence (localStorage, like the rest of HomePilot's chat settings) ────

export interface LocalSettings {
  url: string
  /** The user connected and has not disconnected — reconnect on load. */
  connected: boolean
  apiKey: string
}

export function loadLocalSettings(): LocalSettings {
  try {
    return {
      url: normalizeGatewayRoot(localStorage.getItem(LS_LOCAL_URL) || '') || DEFAULT_LOCAL_GATEWAY,
      connected: localStorage.getItem(LS_LOCAL_CONNECTED) === '1',
      apiKey: localStorage.getItem(LS_LOCAL_KEY) || '',
    }
  } catch {
    return { url: DEFAULT_LOCAL_GATEWAY, connected: false, apiKey: '' }
  }
}

export function saveLocalConnection(root: string, apiKey: string): void {
  try {
    localStorage.setItem(LS_LOCAL_URL, normalizeGatewayRoot(root))
    localStorage.setItem(LS_LOCAL_CONNECTED, '1')
    if (apiKey.trim()) localStorage.setItem(LS_LOCAL_KEY, apiKey.trim())
    else localStorage.removeItem(LS_LOCAL_KEY)
  } catch { /* ignore */ }
}

/** Disconnect: forget that we were connected; keep the URL (and key) for next time. */
export function clearLocalConnected(): void {
  try { localStorage.removeItem(LS_LOCAL_CONNECTED) } catch { /* ignore */ }
}

export function forgetLocalApiKey(): void {
  try { localStorage.removeItem(LS_LOCAL_KEY) } catch { /* ignore */ }
}

/**
 * The key to send with a chat request whose base URL is `baseUrl`: the Local
 * card's optional key, and only when `baseUrl` is exactly that gateway's /v1.
 * Every other URL (OllaBridge Cloud included) gets nothing from here.
 */
export function localGatewayApiKeyFor(baseUrl?: string): string | undefined {
  if (!baseUrl) return undefined
  try {
    const savedUrl = localStorage.getItem(LS_LOCAL_URL) || ''
    const key = (localStorage.getItem(LS_LOCAL_KEY) || '').trim()
    if (!savedUrl || !key) return undefined
    return normalizeGatewayRoot(baseUrl) === normalizeGatewayRoot(savedUrl) && /\/v1\/*$/i.test(baseUrl.trim())
      ? key
      : undefined
  } catch {
    return undefined
  }
}

// ── Connecting ───────────────────────────────────────────────────────────────

export type LocalErrorKind =
  | 'invalid_url' | 'mixed_content' | 'cors' | 'unreachable' | 'timeout' | 'auth' | 'http' | 'bad_response'

export interface LocalError {
  kind: LocalErrorKind
  message: string
}

export interface LocalFallback {
  /** HomePilot backend base URL — the fallback is used only when it is loopback. */
  backendUrl?: string
  backendApiKey?: string
}

export type LocalVia = 'browser' | 'server'

export type LocalResult =
  | { ok: true; via: LocalVia; models: GatewayModel[]; authMode?: string }
  | { ok: false; error: LocalError }

async function timedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  const timer = ctl ? setTimeout(() => ctl.abort(), TIMEOUT_MS) : null
  try {
    return await fetch(url, ctl ? { ...init, signal: ctl.signal } : init)
  } finally {
    if (timer) clearTimeout(timer)
  }
}

function isAbort(e: unknown): boolean {
  return !!e && typeof e === 'object' && (e as { name?: string }).name === 'AbortError'
}

function authHeaders(apiKey: string): Record<string, string> {
  const key = apiKey.trim()
  const h: Record<string, string> = { Accept: 'application/json' }
  if (key) {
    h.Authorization = `Bearer ${key}`
    h['X-API-Key'] = key
  }
  return h
}

function serverFallbackAllowed(fb?: LocalFallback): boolean {
  if (!fb?.backendUrl) return false
  try { return isLoopbackHost(new URL(fb.backendUrl).hostname) } catch { return false }
}

function validate(root: string): LocalError | null {
  try {
    const u = new URL(root)
    if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new Error('scheme')
  } catch {
    return { kind: 'invalid_url', message: 'Enter the gateway URL, for example http://localhost:11435.' }
  }
  if (pageProtocol() === 'https:' && root.startsWith('http:') && !isLoopbackHost(new URL(root).hostname)) {
    return {
      kind: 'mixed_content',
      message: `HomePilot is open over HTTPS, so your browser blocks plain-HTTP calls to ${hostOf(root)}. ` +
        'Serve the gateway over HTTPS, or open HomePilot over http:// on this machine.',
    }
  }
  return null
}

/** Did *anything* answer at `root`? An opaque no-cors response still proves the gateway is up. */
async function reachableIgnoringCors(root: string): Promise<boolean> {
  try {
    await timedFetch(`${root}/health`, { mode: 'no-cors' })
    return true
  } catch {
    return false
  }
}

function unreachableMessage(root: string): string {
  const base = `Can't reach an OllaBridge gateway at ${root}. Start it (\`ollabridge start\`) and check the URL.`
  return pageProtocol() === 'https:'
    ? `${base} This page is served over HTTPS — your browser may also need permission to reach local-network devices.`
    : base
}

function corsMessage(root: string): string {
  const origin = pageOrigin()
  return `The gateway at ${root} is running but blocks requests from this page${origin ? ` (${origin})` : ''}. ` +
    `Add ${origin || 'this page’s origin'} to CORS_ORIGINS in OllaBridge's .env and restart the gateway.`
}

function authMessage(apiKey: string, authMode?: string): string {
  if (apiKey.trim()) return 'The gateway rejected this API key. Check it in the OllaBridge dashboard.'
  return `The gateway requires an API key${authMode ? ` (auth mode: ${authMode})` : ''}. ` +
    'Enter one below, or switch the gateway to local-trust in its dashboard.'
}

async function listDirect(root: string, apiKey: string, authMode?: string): Promise<LocalResult> {
  const r = await timedFetch(`${root}/v1/models`, { headers: authHeaders(apiKey) })
  if (r.status === 401 || r.status === 403) return { ok: false, error: { kind: 'auth', message: authMessage(apiKey, authMode) } }
  if (!r.ok) return { ok: false, error: { kind: 'http', message: `The gateway answered HTTP ${r.status} when listing models.` } }
  const body = await r.json().catch(() => null)
  if (!body || !Array.isArray(body.data)) {
    return { ok: false, error: { kind: 'bad_response', message: `${root}/v1/models did not return an OpenAI model list.` } }
  }
  return { ok: true, via: 'browser', models: normalizeLocalModels(body), authMode }
}

/** The backend's existing model lister for openai_compat (ids only, no key forwarded). */
async function listViaServer(root: string, fb: LocalFallback): Promise<LocalResult> {
  const backend = (fb.backendUrl || '').replace(/\/+$/, '')
  const q = new URLSearchParams({ provider: 'openai_compat', base_url: localChatBaseUrl(root) })
  try {
    const r = await timedFetch(`${backend}/models?${q.toString()}`, {
      headers: fb.backendApiKey ? { 'x-api-key': fb.backendApiKey } : {},
    })
    if (!r.ok) return { ok: false, error: { kind: 'http', message: `HomePilot's server answered HTTP ${r.status}.` } }
    const body = await r.json().catch(() => null)
    if (!body || !Array.isArray(body.models)) {
      return { ok: false, error: { kind: 'bad_response', message: 'HomePilot’s server returned an unexpected model list.' } }
    }
    if (body.error) {
      const err = String(body.error)
      return /\b(401|403)\b|unauthori[sz]ed|forbidden/i.test(err)
        ? { ok: false, error: { kind: 'auth', message: authMessage('') } }
        : { ok: false, error: { kind: 'unreachable', message: unreachableMessage(root) } }
    }
    // `models_detail` carries what each model is (base model or assistant) — the same
    // metadata the browser would have read directly; older servers send ids only.
    const listed = Array.isArray(body.models_detail) ? body.models_detail : body.models
    return { ok: true, via: 'server', models: normalizeLocalModels(listed) }
  } catch (e) {
    return { ok: false, error: { kind: isAbort(e) ? 'timeout' : 'unreachable', message: unreachableMessage(root) } }
  }
}

/** The browser could not talk to the gateway: work out why, and try the same-machine server. */
async function afterNetworkFailure(root: string, e: unknown, fb?: LocalFallback): Promise<LocalResult> {
  if (isAbort(e)) {
    return { ok: false, error: { kind: 'timeout', message: `The gateway at ${root} did not answer within ${TIMEOUT_MS / 1000} s.` } }
  }
  if (serverFallbackAllowed(fb)) {
    const viaServer = await listViaServer(root, fb as LocalFallback)
    if (viaServer.ok || viaServer.error.kind === 'auth') return viaServer
  }
  return (await reachableIgnoringCors(root))
    ? { ok: false, error: { kind: 'cors', message: corsMessage(root) } }
    : { ok: false, error: { kind: 'unreachable', message: unreachableMessage(root) } }
}

/** Connect: health check, then the model list. Never throws. */
export async function connectLocalGateway(rootInput: string, apiKey: string, fb?: LocalFallback): Promise<LocalResult> {
  const root = normalizeGatewayRoot(rootInput)
  const invalid = validate(root)
  if (invalid) return { ok: false, error: invalid }
  let authMode: string | undefined
  try {
    // A plain GET with no custom headers: no CORS preflight, no key needed.
    const r = await timedFetch(`${root}/health`, { headers: { Accept: 'application/json' } })
    if (!r.ok) {
      return { ok: false, error: { kind: 'http', message: `${root}/health answered HTTP ${r.status} — is this an OllaBridge gateway?` } }
    }
    const health = await r.json().catch(() => null)
    if (health && typeof health.auth_mode === 'string') authMode = health.auth_mode
  } catch (e) {
    return afterNetworkFailure(root, e, fb)
  }
  try {
    return await listDirect(root, apiKey, authMode)
  } catch (e) {
    return afterNetworkFailure(root, e, fb)
  }
}

/** Refresh the model list over the path that worked when connecting. */
export async function fetchLocalModels(rootInput: string, apiKey: string, via: LocalVia, fb?: LocalFallback): Promise<LocalResult> {
  const root = normalizeGatewayRoot(rootInput)
  if (via === 'server' && fb) return listViaServer(root, fb)
  try {
    return await listDirect(root, apiKey)
  } catch (e) {
    return afterNetworkFailure(root, e, fb)
  }
}
