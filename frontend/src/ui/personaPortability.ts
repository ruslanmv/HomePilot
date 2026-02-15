/**
 * Persona Portability — Phase 3 v2
 *
 * Types and API helpers for .hpersona export/import:
 *   - Export a persona project as a downloadable .hpersona file
 *   - Preview a .hpersona package (parse + dependency check)
 *   - Import a .hpersona and create a new persona project
 */

// ---------------------------------------------------------------------------
// Dependency check types
// ---------------------------------------------------------------------------

export type DependencyStatus = 'available' | 'missing' | 'degraded' | 'unknown'

export type DependencyItem = {
  name: string
  kind: 'model' | 'tool' | 'mcp_server' | 'a2a_agent'
  status: DependencyStatus
  description: string
  detail: string
  source_type: string
  required: boolean
  fallback: string | null
}

export type DependencyReport = {
  models: DependencyItem[]
  tools: DependencyItem[]
  mcp_servers: DependencyItem[]
  a2a_agents: DependencyItem[]
  all_satisfied: boolean
  summary: string
}

// ---------------------------------------------------------------------------
// Preview result (from POST /persona/import/preview)
// ---------------------------------------------------------------------------

export type PersonaPreview = {
  ok: boolean
  manifest: {
    package_version: number
    schema_version: number
    kind: string
    content_rating: string
    source_homepilot_version?: string
    created_at?: string
    contents?: {
      has_avatar: boolean
      has_outfits: boolean
      outfit_count: number
      has_tool_dependencies: boolean
      has_mcp_servers: boolean
      has_a2a_agents: boolean
      has_model_requirements: boolean
    }
    capability_summary?: {
      personality_tools: string[]
      capabilities: string[]
      mcp_servers_count: number
      a2a_agents_count: number
    }
  }
  persona_agent: Record<string, any>
  persona_appearance: Record<string, any>
  agentic: Record<string, any>
  dependencies: Record<string, any>
  has_avatar: boolean
  asset_names: string[]
  dependency_check: DependencyReport
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

function authHeaders(apiKey?: string): Record<string, string> {
  const h: Record<string, string> = {}
  if (apiKey && apiKey.trim().length > 0) h['x-api-key'] = apiKey
  return h
}

/**
 * Export a persona project — triggers a browser download of the .hpersona file.
 *
 * Uses mode='full' by default so avatar images are included as real files
 * inside the ZIP's assets/ folder, making the package fully portable.
 * The .hpersona ZIP structure:
 *   manifest.json
 *   blueprint/persona_agent.json
 *   blueprint/persona_appearance.json
 *   preview/card.json
 *   assets/avatar.png          <- main portrait (real image, not base64)
 *   assets/outfit_*.png        <- outfit images if any
 */
export async function exportPersona(params: {
  backendUrl: string
  apiKey?: string
  projectId: string
  mode?: 'blueprint' | 'full'
}): Promise<void> {
  const mode = params.mode || 'full'
  const url = `${params.backendUrl}/projects/${params.projectId}/persona/export?mode=${mode}`

  const res = await fetch(url, { headers: authHeaders(params.apiKey) })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `Export failed: ${res.status}`)
  }

  // Get filename from Content-Disposition header
  const disposition = res.headers.get('Content-Disposition') || ''
  const filenameMatch = disposition.match(/filename="?([^"]+)"?/)
  const filename = filenameMatch?.[1] || 'persona.hpersona'

  // Trigger download
  const blob = await res.blob()
  const blobUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(blobUrl)
}

/**
 * Preview a .hpersona file — parse + dependency check, no project created.
 */
export async function previewPersonaPackage(params: {
  backendUrl: string
  apiKey?: string
  file: File
}): Promise<PersonaPreview> {
  const formData = new FormData()
  formData.append('file', params.file)

  const headers: Record<string, string> = {}
  if (params.apiKey) headers['x-api-key'] = params.apiKey

  const res = await fetch(`${params.backendUrl}/persona/import/preview`, {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `Preview failed: ${res.status}`)
  }

  return await res.json()
}

/**
 * Import a .hpersona file — creates a new persona project.
 */
export async function importPersonaPackage(params: {
  backendUrl: string
  apiKey?: string
  file: File
}): Promise<{ ok: boolean; project: Record<string, any> }> {
  const formData = new FormData()
  formData.append('file', params.file)

  const headers: Record<string, string> = {}
  if (params.apiKey) headers['x-api-key'] = params.apiKey

  const res = await fetch(`${params.backendUrl}/persona/import`, {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `Import failed: ${res.status}`)
  }

  return await res.json()
}

/**
 * Commit an avatar to durable project storage.
 */
export async function commitPersonaAvatar(params: {
  backendUrl: string
  apiKey?: string
  projectId: string
  sourceFilename: string
}): Promise<Record<string, any>> {
  const res = await fetch(
    `${params.backendUrl}/projects/${params.projectId}/persona/avatar/commit`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(params.apiKey),
      },
      body: JSON.stringify({ source_filename: params.sourceFilename }),
    }
  )

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `Commit failed: ${res.status}`)
  }

  return await res.json()
}
