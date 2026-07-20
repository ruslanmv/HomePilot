/**
 * MirrorClient — the single typed entry point to the cloud mirror, via the
 * HomePilot Web BFF (Batch 1) at ``/v1/account/mirror/*``.
 *
 * It calls ONLY the same-origin BFF routes with the existing HomePilot auth
 * token. It never constructs a cloud relay URL and never touches a cloud token
 * — that stays server-side (design §11: "Do not let individual UI components
 * construct cloud relay URLs or read cloud tokens.").
 */
import { resolveBackendUrl } from '../lib/backendUrl'
import type { MirrorNode, MirrorStatus, NodeManifest } from './types'

const LS_TOKEN_KEY = 'homepilot_auth_token'

/** Error that preserves the BFF/upstream status so callers can branch on it
 *  (e.g. 409 → node_offline, 503 → cloud not linked). */
export class MirrorError extends Error {
  status: number
  code?: string
  body?: unknown
  constructor(status: number, body: unknown) {
    const b = (body ?? {}) as { error?: string; message?: string }
    super(b.message || b.error || `Mirror request failed (${status})`)
    this.name = 'MirrorError'
    this.status = status
    this.code = b.error
    this.body = body
  }
  /** The owning computer is offline (honest offline signal, design §8). */
  get isNodeOffline(): boolean {
    return this.status === 409 && this.code === 'node_offline'
  }
  /** No server-side cloud credential is available for this account yet. */
  get isNotLinked(): boolean {
    return this.status === 503
  }
}

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  try {
    const tok = localStorage.getItem(LS_TOKEN_KEY) || ''
    if (tok) h['Authorization'] = `Bearer ${tok}`
  } catch {
    /* storage unavailable */
  }
  return h
}

async function safeJson(res: Response): Promise<unknown> {
  try {
    return await res.json()
  } catch {
    return null
  }
}

async function request<T>(
  method: string,
  path: string,
  opts: { body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const base = resolveBackendUrl()
  const res = await fetch(`${base}/v1/account/mirror${path}`, {
    method,
    headers: authHeaders(),
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
    // BFF is same-origin in the web deployment; include cookies so the
    // homepilot_session cookie authenticates even without a Bearer token.
    credentials: 'include',
  })
  if (!res.ok) {
    throw new MirrorError(res.status, await safeJson(res))
  }
  return (await res.json()) as T
}

const enc = encodeURIComponent

export const mirrorClient = {
  /** Is the feature usable and is a cloud credential linked server-side? */
  status(signal?: AbortSignal): Promise<MirrorStatus> {
    return request<MirrorStatus>('GET', '/status', { signal })
  },

  /** The account's computers with live online state. */
  listNodes(signal?: AbortSignal): Promise<MirrorNode[]> {
    return request<MirrorNode[]>('GET', '/nodes', { signal })
  },

  /** A node's full manifest (GPU/VRAM/models/projects/capabilities). */
  getManifest(nodeId: string, signal?: AbortSignal): Promise<NodeManifest> {
    return request<NodeManifest>('GET', `/nodes/${enc(nodeId)}/manifest`, { signal })
  },

  /** Invoke one read-only, allow-listed RPC operation on a node. */
  rpc<T = unknown>(nodeId: string, operation: string, params: Record<string, unknown> = {}): Promise<T> {
    return request<T>('POST', `/nodes/${enc(nodeId)}/rpc`, { body: { operation, params } })
  },

  /** Create a durable job (chat/image/video) on a node. */
  createJob<T = unknown>(
    nodeId: string,
    operation: string,
    params: Record<string, unknown> = {},
    resourceUri?: string,
  ): Promise<T> {
    return request<T>('POST', `/nodes/${enc(nodeId)}/jobs`, {
      body: { operation, params, ...(resourceUri ? { resource_uri: resourceUri } : {}) },
    })
  },

  getJob<T = unknown>(jobId: string, nodeId: string): Promise<T> {
    return request<T>('GET', `/jobs/${enc(jobId)}?node_id=${enc(nodeId)}`)
  },

  cancelJob<T = unknown>(jobId: string, nodeId: string): Promise<T> {
    return request<T>('POST', `/jobs/${enc(jobId)}/cancel?node_id=${enc(nodeId)}`)
  },
}

export type MirrorClient = typeof mirrorClient
