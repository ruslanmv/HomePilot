/**
 * OllaBridge Cloud session — the one browser-side implementation of signing in
 * to OllaBridge Cloud and syncing the account's devices and models. Used by the
 * Cloud card (Model Management → Chat) and by the per-type OllaBridge list
 * (OllaBridgeModels), which this was extracted from unchanged:
 *
 *   POST {cloud}/v1/auth/login        → { token }
 *   GET  {cloud}/v1/devices           → linked machines (online, GPU)
 *   GET  {cloud}/ollama/v1/models     → models the relay exposes to this account
 *
 * Talks to the Cloud directly (CORS is open there). The token is kept in
 * localStorage unless the BFF session flag is on, in which case the HomePilot
 * backend holds it server-side and the browser keeps it in memory only.
 */
import { isBffSessionEnabled } from '../../account/featureFlags'
import type { CloudDevice, CloudModel } from './models'

export const LS_CLOUD_TOKEN = 'homepilot_cloud_token'
export const LS_CLOUD_URL = 'homepilot_cloud_url'
export const DEFAULT_CLOUD_URL = 'https://app.ollabridge.com'

export function getCloudUrl(): string {
  try {
    const saved = (localStorage.getItem(LS_CLOUD_URL) || '').trim().replace(/\/+$/, '')
    // Drop known-obsolete cloud URLs so the new default/env value takes over,
    // while preserving an intentional self-hosted URL. The raw Hugging Face
    // origin is superseded by the branded app.ollabridge.com host.
    const legacyUrls = new Set([
      'https://ruslanmv-ollabridge.hf.space',
      'https://ruslanmv-ollabridge-cloud.hf.space',
    ])
    if (saved && legacyUrls.has(saved)) {
      localStorage.removeItem(LS_CLOUD_URL)
    } else if (saved) {
      return saved
    }
  } catch { /* ignore */ }
  const env: Record<string, string | undefined> =
    ((import.meta as unknown as { env?: Record<string, string | undefined> }).env) || {}
  return ((env.VITE_OLLABRIDGE_CLOUD_URL || '').trim() || DEFAULT_CLOUD_URL).replace(/\/+$/, '')
}

export function getCloudToken(): string {
  try { return (localStorage.getItem(LS_CLOUD_TOKEN) || '').trim() } catch { return '' }
}

/** Chat base URL of the Cloud relay: inference runs on the account's own nodes. */
export function cloudChatBaseUrl(cloudUrl: string): string {
  return `${cloudUrl.replace(/\/+$/, '')}/ollama/v1`
}

/** `app.ollabridge.com/` → `https://app.ollabridge.com` (what a user types into the field). */
export function normalizeCloudUrl(input: string): string {
  let s = (input || '').trim()
  if (!s) return ''
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = `https://${s}`
  return s.replace(/\/+$/, '')
}

export type CloudLoginResult = { ok: true; token: string } | { ok: false; error: string }

export async function cloudLogin(cloudUrl: string, email: string, password: string): Promise<CloudLoginResult> {
  try {
    const r = await fetch(`${cloudUrl}/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim(), password }),
    })
    const data = await r.json().catch(() => ({}))
    if (!r.ok || !data.token) return { ok: false, error: data.detail || 'Invalid OllaBridge email or password' }
    return { ok: true, token: String(data.token) }
  } catch {
    return { ok: false, error: 'Could not reach OllaBridge Cloud.' }
  }
}

/** Remember the session after a successful sign-in (token only when BFF is off). */
export function saveCloudSession(cloudUrl: string, token: string): void {
  try {
    // Batch 7 (BFF): the token lives in component memory for the session; when
    // BFF is on we no longer persist it in browser storage.
    if (!isBffSessionEnabled()) localStorage.setItem(LS_CLOUD_TOKEN, token)
    localStorage.setItem(LS_CLOUD_URL, cloudUrl)
  } catch { /* ignore */ }
}

export function clearCloudSession(): void {
  try { localStorage.removeItem(LS_CLOUD_TOKEN) } catch { /* ignore */ }
}

export type CloudInventory =
  | {
      status: 'ok'
      devices: CloudDevice[]
      models: CloudModel[]
      /** HTTP status of each call — "ok" alone does not mean both answered. */
      devicesStatus: number
      modelsStatus: number
    }
  | { status: 'expired' }
  | { status: 'unreachable' }

/** One sync of the account's devices + models. 401 on either call = session expired. */
export async function fetchCloudInventory(cloudUrl: string, token: string): Promise<CloudInventory> {
  try {
    const auth = { Authorization: `Bearer ${token}` }
    const [devRes, modRes] = await Promise.all([
      fetch(`${cloudUrl}/v1/devices`, { headers: auth }),
      fetch(`${cloudUrl}/ollama/v1/models`, { headers: auth }),
    ])
    if (devRes.status === 401 || modRes.status === 401) return { status: 'expired' }
    const devs = devRes.ok ? await devRes.json() : []
    const mods = modRes.ok ? await modRes.json() : { data: [] }
    const list: CloudModel[] = Array.isArray(mods?.data) ? mods.data : []
    // Own-node models first (relay/shared_device), then the rest.
    list.sort((a, b) => Number(isShared(b)) - Number(isShared(a)))
    return {
      status: 'ok',
      devices: Array.isArray(devs) ? devs : [],
      models: list,
      devicesStatus: devRes.status,
      modelsStatus: modRes.status,
    }
  } catch {
    return { status: 'unreachable' }
  }
}

function isShared(m: CloudModel): boolean {
  return (m.x_source || m.source) === 'shared_device'
}
