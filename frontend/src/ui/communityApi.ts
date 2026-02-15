/**
 * Community Gallery — API client (Phase 3)
 *
 * Talks to the backend proxy at /community/* which in turn
 * fetches from the Cloudflare Worker. The frontend never calls
 * external URLs directly.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CommunityPersonaItem = {
  id: string
  name: string
  short: string
  tags: string[]
  nsfw: boolean
  author: string
  downloads: number
  latest: {
    version: string
    package_url: string
    preview_url: string
    card_url: string
    sha256: string
    size_bytes: number
  }
}

export type CommunityRegistryResponse = {
  schema_version: number
  generated_at: string
  items: CommunityPersonaItem[]
  total: number
  filtered: number
  configured: boolean
}

export type CommunityStatusResponse = {
  configured: boolean
  url: string | null
  reachable?: boolean
  message?: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function authHeaders(apiKey?: string): Record<string, string> {
  const h: Record<string, string> = {}
  if (apiKey && apiKey.trim().length > 0) h['x-api-key'] = apiKey
  return h
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Check if the community gallery is configured and reachable.
 */
export async function communityStatus(params: {
  backendUrl: string
  apiKey?: string
}): Promise<CommunityStatusResponse> {
  const url = `${params.backendUrl.replace(/\/+$/, '')}/community/status`
  const res = await fetch(url, { headers: authHeaders(params.apiKey) })
  if (!res.ok) throw new Error(`Status check failed: HTTP ${res.status}`)
  return res.json()
}

/**
 * Fetch the community persona registry (with optional filtering).
 */
export async function communityRegistry(params: {
  backendUrl: string
  apiKey?: string
  search?: string
  tag?: string
  nsfw?: boolean
}): Promise<CommunityRegistryResponse> {
  const base = `${params.backendUrl.replace(/\/+$/, '')}/community/registry`
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  if (params.tag) query.set('tag', params.tag)
  if (params.nsfw !== undefined) query.set('nsfw', String(params.nsfw))
  const qs = query.toString()
  const url = qs ? `${base}?${qs}` : base

  const res = await fetch(url, { headers: authHeaders(params.apiKey) })
  if (!res.ok) throw new Error(`Registry fetch failed: HTTP ${res.status}`)
  return res.json()
}

/**
 * Fetch card metadata for a specific persona from the gallery.
 */
export async function communityCard(params: {
  backendUrl: string
  apiKey?: string
  personaId: string
  version: string
}): Promise<Record<string, any>> {
  const url = `${params.backendUrl.replace(/\/+$/, '')}/community/card/${params.personaId}/${params.version}`
  const res = await fetch(url, { headers: authHeaders(params.apiKey) })
  if (!res.ok) throw new Error(`Card fetch failed: HTTP ${res.status}`)
  return res.json()
}

/**
 * Download a .hpersona package from the community gallery via the backend proxy.
 * Returns a File object ready for the import flow.
 */
export async function communityDownloadPackage(params: {
  backendUrl: string
  apiKey?: string
  personaId: string
  version: string
}): Promise<File> {
  const url = `${params.backendUrl.replace(/\/+$/, '')}/community/download/${params.personaId}/${params.version}`
  const res = await fetch(url, { headers: authHeaders(params.apiKey) })
  if (!res.ok) throw new Error(`Download failed: HTTP ${res.status}`)

  const blob = await res.blob()
  return new File([blob], `${params.personaId}.hpersona`, {
    type: 'application/octet-stream',
  })
}
