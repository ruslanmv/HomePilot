/**
 * Inventory API client — calls backend /v1/inventory/* REST endpoints.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type InventoryCategory = {
  type: 'outfit' | 'image' | 'file'
  label: string
  count?: number
  top_tags?: Array<{ tag: string; count: number }>
}

export type ViewAngle = 'front' | 'left' | 'right' | 'back'

export type ViewPack = Partial<Record<ViewAngle, string>>

export type InventoryItem = {
  id: string
  type: 'outfit' | 'image' | 'file'
  label: string
  tags: string[]
  sensitivity: 'safe' | 'sensitive' | 'explicit'
  // Outfit-specific
  preview_asset_id?: string
  asset_ids?: string[]
  description?: string
  // Image-specific
  url?: string
  // File-specific
  mime?: string
  size_bytes?: number
  // Active Look — persona_appearance set_id + image_id for wardrobe-style selection
  set_id?: string
  image_id?: string
  /** True when this item is the persona's current Active Look */
  is_active_look?: boolean
  // View Pack — outfit angle views (additive, all optional)
  equipped?: boolean
  interactive_preview?: boolean
  preview_mode?: 'static' | 'view_pack'
  hero_view?: ViewAngle
  available_views?: ViewAngle[]
  view_pack?: ViewPack
}

/** Response from the persona outfit-view resolver endpoint. */
export type ResolvedPersonaOutfitView = {
  ok: boolean
  persona_id: string
  project_id: string
  target_type: 'outfit'
  target_id: string
  target_label: string
  angle: ViewAngle
  image_url: string
  available_views: ViewAngle[]
  interactive_preview: boolean
  view_pack?: ViewPack
}

export type ResolvedMedia = {
  ok: boolean
  asset_id: string
  type: string
  label: string
  url: string
  url_path: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function authHeaders(apiKey?: string): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey && apiKey.trim().length > 0) h['x-api-key'] = apiKey
  // Additive: attach the logged-in user's bearer JWT when present so
  // inventory endpoints that now accept 'user session OR api key'
  // (see backend/app/auth.py::require_api_key) authenticate without
  // the shared API key. Silent no-op on anonymous / not-yet-logged-in
  // sessions.
  try {
    if (typeof window !== 'undefined') {
      const tok = window.localStorage.getItem('homepilot_auth_token') || ''
      if (tok && !h['Authorization']) h['Authorization'] = `Bearer ${tok}`
    }
  } catch {
    /* ignore storage errors */
  }
  return h
}

/** Fetch init used by every inventory call. ``credentials: 'include'``
 *  makes the browser attach the ``homepilot_session`` cookie so the
 *  backend's user-session fallback path (see ``require_api_key``) can
 *  authenticate even when a bearer token isn't held in localStorage
 *  (e.g. SSR-style browser session). */
const WITH_CREDS: Pick<RequestInit, 'credentials'> = { credentials: 'include' }

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export async function fetchInventoryCategories(
  backendUrl: string,
  projectId: string,
  opts?: { apiKey?: string; includeTags?: boolean; sensitivityMax?: string },
): Promise<{ categories: InventoryCategory[] }> {
  const params = new URLSearchParams({
    include_counts: 'true',
    include_tags: opts?.includeTags ? 'true' : 'false',
    sensitivity_max: opts?.sensitivityMax || 'safe',
  })
  const res = await fetch(
    `${backendUrl}/v1/inventory/${projectId}/categories?${params}`,
    { headers: authHeaders(opts?.apiKey), ...WITH_CREDS },
  )
  if (!res.ok) throw new Error(`Inventory categories failed: ${res.status}`)
  return res.json()
}

export async function searchInventory(
  backendUrl: string,
  projectId: string,
  opts?: {
    apiKey?: string
    query?: string
    types?: string[]
    limit?: number
    sensitivityMax?: string
    countOnly?: boolean
  },
): Promise<{ items: InventoryItem[]; total_count: number }> {
  const params = new URLSearchParams({
    sensitivity_max: opts?.sensitivityMax || 'safe',
  })
  if (opts?.query) params.set('query', opts.query)
  if (opts?.types && opts.types.length > 0) params.set('types', opts.types.join(','))
  if (opts?.limit) params.set('limit', String(opts.limit))
  if (opts?.countOnly) params.set('count_only', 'true')

  const res = await fetch(
    `${backendUrl}/v1/inventory/${projectId}/search?${params}`,
    { headers: authHeaders(opts?.apiKey), ...WITH_CREDS },
  )
  if (!res.ok) throw new Error(`Inventory search failed: ${res.status}`)
  return res.json()
}

export async function getInventoryItem(
  backendUrl: string,
  projectId: string,
  itemId: string,
  opts?: { apiKey?: string; sensitivityMax?: string },
): Promise<{ item: InventoryItem }> {
  const params = new URLSearchParams({
    sensitivity_max: opts?.sensitivityMax || 'safe',
  })
  const res = await fetch(
    `${backendUrl}/v1/inventory/${projectId}/items/${encodeURIComponent(itemId)}?${params}`,
    { headers: authHeaders(opts?.apiKey), ...WITH_CREDS },
  )
  if (!res.ok) throw new Error(`Inventory get failed: ${res.status}`)
  return res.json()
}

export async function resolveInventoryMedia(
  backendUrl: string,
  projectId: string,
  assetId: string,
  opts?: { apiKey?: string; sensitivityMax?: string },
): Promise<ResolvedMedia> {
  const res = await fetch(`${backendUrl}/v1/inventory/resolve`, {
    method: 'POST',
    headers: authHeaders(opts?.apiKey),
    ...WITH_CREDS,
    body: JSON.stringify({
      project_id: projectId,
      asset_id: assetId,
      sensitivity_max: opts?.sensitivityMax || 'safe',
    }),
  })
  if (!res.ok) throw new Error(`Inventory resolve failed: ${res.status}`)
  return res.json()
}

export async function resolvePersonaOutfitView(
  backendUrl: string,
  projectId: string,
  opts: {
    apiKey?: string
    angle: ViewAngle
    target?: 'current_outfit'
    sensitivityMax?: string
  },
): Promise<ResolvedPersonaOutfitView> {
  const res = await fetch(`${backendUrl}/v1/inventory/${projectId}/persona/outfit-view`, {
    method: 'POST',
    headers: authHeaders(opts.apiKey),
    ...WITH_CREDS,
    body: JSON.stringify({
      target: opts.target || 'current_outfit',
      angle: opts.angle,
      sensitivity_max: opts.sensitivityMax || 'safe',
    }),
  })
  if (!res.ok) throw new Error(`Resolve persona outfit view failed: ${res.status}`)
  return res.json()
}

export async function saveViewPackToOutfit(
  backendUrl: string,
  opts: {
    apiKey?: string
    projectId: string
    outfitId?: string
    viewPack: ViewPack
    equipped?: boolean
  },
): Promise<{ ok: boolean; project_id: string; outfit_id: string; outfit_label: string; view_pack: ViewPack; available_views: ViewAngle[] }> {
  const res = await fetch(`${backendUrl}/v1/viewpack/save-to-outfit`, {
    method: 'POST',
    headers: authHeaders(opts.apiKey),
    ...WITH_CREDS,
    body: JSON.stringify({
      project_id: opts.projectId,
      outfit_id: opts.outfitId,
      view_pack: opts.viewPack,
      equipped: opts.equipped,
    }),
  })
  if (!res.ok) throw new Error(`Save view pack to outfit failed: ${res.status}`)
  return res.json()
}

export async function deleteInventoryItem(
  backendUrl: string,
  projectId: string,
  itemId: string,
  opts?: { apiKey?: string },
): Promise<{ ok: boolean; deleted_id: string; deleted_label: string; deleted_type: string }> {
  const res = await fetch(
    `${backendUrl}/v1/inventory/${projectId}/items/${encodeURIComponent(itemId)}`,
    { method: 'DELETE', headers: authHeaders(opts?.apiKey), ...WITH_CREDS },
  )
  if (!res.ok) throw new Error(`Inventory delete failed: ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Persona Document Attachment API
// ---------------------------------------------------------------------------

export type PersonaDocument = {
  attachment_id: string
  mode: 'indexed' | 'pinned' | 'excluded'
  attachment_updated_at: string
  // project_items fields
  id: string
  project_id: string
  name: string
  description: string
  category: string
  item_type: string
  tags: string[]
  properties: {
    index_status?: 'not_indexed' | 'indexing' | 'ready' | 'error'
    chunk_count?: number
    last_indexed_at?: number
    error_message?: string
  }
  asset_id: string
  file_url: string
  mime: string
  size_bytes: number
  original_name: string
}

export async function listPersonaDocuments(
  backendUrl: string,
  projectId: string,
  opts?: { apiKey?: string },
): Promise<{ ok: boolean; documents: PersonaDocument[] }> {
  const res = await fetch(
    `${backendUrl}/projects/${projectId}/persona/documents`,
    { headers: authHeaders(opts?.apiKey), ...WITH_CREDS },
  )
  if (!res.ok) throw new Error(`List persona documents failed: ${res.status}`)
  return res.json()
}

export async function attachPersonaDocument(
  backendUrl: string,
  projectId: string,
  itemId: string,
  mode: string = 'indexed',
  opts?: { apiKey?: string },
): Promise<{ ok: boolean; attachment: any }> {
  const res = await fetch(
    `${backendUrl}/projects/${projectId}/persona/documents/attach`,
    {
      method: 'POST',
      headers: authHeaders(opts?.apiKey),
      ...WITH_CREDS,
      body: JSON.stringify({ item_id: itemId, mode }),
    },
  )
  if (!res.ok) throw new Error(`Attach document failed: ${res.status}`)
  return res.json()
}

export async function setPersonaDocumentMode(
  backendUrl: string,
  projectId: string,
  itemId: string,
  mode: string,
  opts?: { apiKey?: string },
): Promise<{ ok: boolean; attachment: any }> {
  const res = await fetch(
    `${backendUrl}/projects/${projectId}/persona/documents/mode`,
    {
      method: 'POST',
      headers: authHeaders(opts?.apiKey),
      ...WITH_CREDS,
      body: JSON.stringify({ item_id: itemId, mode }),
    },
  )
  if (!res.ok) throw new Error(`Set document mode failed: ${res.status}`)
  return res.json()
}

export async function detachPersonaDocument(
  backendUrl: string,
  projectId: string,
  itemId: string,
  opts?: { apiKey?: string },
): Promise<{ ok: boolean; removed: boolean }> {
  const res = await fetch(
    `${backendUrl}/projects/${projectId}/persona/documents/${encodeURIComponent(itemId)}`,
    { method: 'DELETE', headers: authHeaders(opts?.apiKey), ...WITH_CREDS },
  )
  if (!res.ok) throw new Error(`Detach document failed: ${res.status}`)
  return res.json()
}

export async function deletePersonaDocumentPermanently(
  backendUrl: string,
  projectId: string,
  itemId: string,
  opts?: { apiKey?: string },
): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(
    `${backendUrl}/projects/${projectId}/persona/documents/${encodeURIComponent(itemId)}/permanent`,
    { method: 'DELETE', headers: authHeaders(opts?.apiKey), ...WITH_CREDS },
  )
  if (!res.ok) throw new Error(`Delete document permanently failed: ${res.status}`)
  return res.json()
}

export async function uploadProjectItem(
  backendUrl: string,
  projectId: string,
  file: File,
  opts?: { apiKey?: string; name?: string; description?: string; category?: string; tags?: string },
): Promise<{ ok: boolean; item: any; chunks_added: number; file_url: string }> {
  const form = new FormData()
  form.append('file', file)
  if (opts?.name) form.append('name', opts.name)
  if (opts?.description) form.append('description', opts.description)
  if (opts?.category) form.append('category', opts.category || 'file')
  if (opts?.tags) form.append('tags', opts.tags)

  const headers: Record<string, string> = {}
  if (opts?.apiKey) headers['x-api-key'] = opts.apiKey
  const tok = (() => { try { return localStorage.getItem('homepilot_auth_token') || '' } catch { return '' } })()
  if (tok) headers['authorization'] = `Bearer ${tok}`

  const res = await fetch(
    `${backendUrl}/projects/${projectId}/items/upload`,
    { method: 'POST', headers, body: form, ...WITH_CREDS },
  )
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
  return res.json()
}
