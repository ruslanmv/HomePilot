/**
 * Client for the backend's model discovery + resolution API
 * (`/v1/models/resolution`, `/v1/models/pull`, …). See
 * docs/design/LOCAL_MODEL_RESOLUTION.md.
 */
import { fetchApiJson } from './apiFetch'

export type ResolutionSource = 'configured' | 'fallback' | 'none'
export type RemedyKind = 'pull' | 'start' | 'connect' | 'wsl_bridge'

export interface SuggestedModel {
  name: string
  size_gb: number
  roles: string[]
  why: string
  installed?: boolean
}

export interface Remedy {
  kind: RemedyKind
  message: string
  command?: string
  runtime_url?: string
  probed?: string[]
  suggested?: SuggestedModel[]
}

export interface RoleResolution {
  role: string
  configured: string
  model: string
  runtime_url: string
  source: ResolutionSource
  reason: string
  installed: string[]
  alternatives: string[]
  remedy: Remedy | null
  configured_installed: boolean | null
}

export interface RuntimeProbe {
  url: string
  label: string
  reachable: boolean
  models: string[]
  error: string
  latency_ms: number
}

export interface PullJob {
  name: string
  runtime_url: string
  status: 'queued' | 'running' | 'completed' | 'error'
  message: string
  total: number
  completed: number
  pct: number
  error: string
}

export interface ModelResolutionSnapshot {
  ok: boolean
  chat: RoleResolution
  vision: RoleResolution
  fast: RoleResolution
  runtimes: RuntimeProbe[]
  runtime_url: string
  suggested: SuggestedModel[]
  fingerprint: string
  environment: { wsl: boolean; docker: boolean }
  pulls: PullJob[]
}

function q(params: Record<string, string | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => typeof v === 'string' && v.length > 0)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v as string)}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

export async function fetchModelResolution(
  backendUrl: string,
  opts: { configured?: string; vision?: string; baseUrl?: string; refresh?: boolean } = {},
): Promise<ModelResolutionSnapshot> {
  const base = backendUrl.replace(/\/+$/, '')
  const query = q({ configured: opts.configured, vision: opts.vision, base_url: opts.baseUrl })
  if (opts.refresh) {
    const res = await fetch(`${base}/v1/models/refresh${query}`, { method: 'POST' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }
  return fetchApiJson(`${base}/v1/models/resolution${query}`)
}

export async function startModelPull(backendUrl: string, name: string, baseUrl?: string): Promise<PullJob> {
  const base = backendUrl.replace(/\/+$/, '')
  const res = await fetch(`${base}/v1/models/pull`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, base_url: baseUrl || undefined }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok || !data?.ok) {
    throw new Error(data?.message || `HTTP ${res.status}`)
  }
  return data.job as PullJob
}

export async function getModelPull(backendUrl: string, name: string): Promise<PullJob | null> {
  const base = backendUrl.replace(/\/+$/, '')
  const res = await fetch(`${base}/v1/models/pull/${encodeURIComponent(name)}`)
  if (res.status === 404) return null
  const data = await res.json().catch(() => ({}))
  if (!res.ok || !data?.ok) throw new Error(data?.message || `HTTP ${res.status}`)
  return data.job as PullJob
}

export function formatGb(gb: number): string {
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(gb * 1000)} MB`
}

/** One line a human can read: "deepseek-r1:latest (auto, Ollama on 172.20.16.1)". */
export function describeResolution(r: RoleResolution | null | undefined): string {
  if (!r) return ''
  if (!r.model) return r.reason
  let host = ''
  try {
    host = new URL(r.runtime_url).hostname
  } catch {
    host = r.runtime_url
  }
  const how = r.source === 'configured' ? 'configured' : 'auto'
  return `${r.model} (${how}, Ollama on ${host})`
}
