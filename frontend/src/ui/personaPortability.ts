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

export type DependencyStatus =
  | 'available'      // server running, tools registered       (green)
  | 'installable'    // bundle present locally, not started     (blue)
  | 'downloadable'   // git URL known, can be auto-fetched      (yellow)
  | 'missing'        // no source info, can't auto-resolve      (red)
  | 'degraded'       // partially working                       (amber)
  | 'unknown'        // can't determine                         (gray)

export type DependencyItem = {
  name: string
  kind: 'model' | 'tool' | 'mcp_server' | 'a2a_agent'
  status: DependencyStatus
  description: string
  detail: string
  source_type: string
  required: boolean
  fallback: string | null
  /** Forge registry server ID — used for auto-install from Discover tab */
  registry_id?: string
  /** Auth type for registry servers (open, api_key, oauth2.1, etc.) */
  auth_type?: string
  /** Endpoint URL for registry servers */
  url?: string
  /** Community bundle ID for auto-install */
  bundle_id?: string
  /** Allocated port for the server */
  port?: number
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
    memory_mode?: string
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
  avatar_preview_data_url?: string | null
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
 * Atomic import — install MCP servers + create persona project in one call.
 * This is the recommended flow for community gallery imports.
 */
export async function importPersonaAtomic(params: {
  backendUrl: string
  apiKey?: string
  file: File
  autoInstallServers?: boolean
  forceReinstall?: boolean
}): Promise<{ ok: boolean; project: Record<string, any>; install_plan: McpInstallPlan | null }> {
  const formData = new FormData()
  formData.append('file', params.file)

  const headers: Record<string, string> = {}
  if (params.apiKey) headers['x-api-key'] = params.apiKey

  const autoInstall = params.autoInstallServers !== false
  const qs = `auto_install_servers=${autoInstall}&force_reinstall=${!!params.forceReinstall}`
  const res = await fetch(
    `${params.backendUrl}/persona/import/atomic?${qs}`,
    { method: 'POST', headers, body: formData },
  )

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `Atomic import failed: ${res.status}`)
  }

  return await res.json()
}

// ---------------------------------------------------------------------------
// MCP Dependency Resolution & Auto-Install
// ---------------------------------------------------------------------------

export type McpInstallPhase =
  | 'analyzing' | 'cloning' | 'registering' | 'starting'
  | 'discovering' | 'syncing' | 'complete' | 'failed' | 'skipped'

export type ServerInstallStatus = {
  server_name: string
  phase: McpInstallPhase
  progress_pct: number
  message: string
  error: string | null
  port: number | null
  tools_discovered: number
  tools_registered: number
  source_type: string
  git_url: string
  install_path: string
  elapsed_ms: number
}

export type McpInstallPlan = {
  persona_name: string
  servers_needed: Record<string, any>[]
  servers_already_available: Record<string, any>[]
  servers_to_install: {
    name: string
    description: string
    source: Record<string, any>
    tools_provided: string[]
    git_url: string
  }[]
  servers_unresolvable: Record<string, any>[]
  install_statuses: ServerInstallStatus[]
  all_satisfied: boolean
  summary: string
}

/**
 * Resolve MCP dependencies for a .hpersona — returns an install plan.
 * Does NOT install anything.
 */
export async function resolvePersonaDeps(params: {
  backendUrl: string
  apiKey?: string
  file: File
}): Promise<McpInstallPlan> {
  const formData = new FormData()
  formData.append('file', params.file)

  const headers: Record<string, string> = {}
  if (params.apiKey) headers['x-api-key'] = params.apiKey

  const res = await fetch(`${params.backendUrl}/persona/import/resolve-deps`, {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `Dependency check failed: ${res.status}`)
  }

  const data = await res.json()
  return data.plan
}

/**
 * Auto-install missing MCP servers — clones from git, starts, registers in Forge.
 */
export async function installPersonaDeps(params: {
  backendUrl: string
  apiKey?: string
  file: File
}): Promise<McpInstallPlan> {
  const formData = new FormData()
  formData.append('file', params.file)

  const headers: Record<string, string> = {}
  if (params.apiKey) headers['x-api-key'] = params.apiKey

  const res = await fetch(`${params.backendUrl}/persona/import/install-deps`, {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `Installation failed: ${res.status}`)
  }

  const data = await res.json()
  return data.plan
}

/**
 * Commit an avatar to durable project storage.
 *
 * Supports three modes (provide exactly one):
 *   - sourceFilename: file already in UPLOAD_PATH (legacy)
 *   - sourceUrl: ComfyUI /view?... URL (downloads first, then commits)
 *   - auto: true — resolve from persona_appearance.sets (repair mode)
 */
export async function commitPersonaAvatar(params: {
  backendUrl: string
  apiKey?: string
  projectId: string
  sourceFilename?: string
  sourceUrl?: string
  auto?: boolean
}): Promise<Record<string, any>> {
  const body: Record<string, unknown> = {}
  if (params.auto) {
    body.auto = true
  } else if (params.sourceUrl) {
    body.source_url = params.sourceUrl
  } else if (params.sourceFilename) {
    body.source_filename = params.sourceFilename
  }

  const res = await fetch(
    `${params.backendUrl}/projects/${params.projectId}/persona/avatar/commit`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(params.apiKey),
      },
      body: JSON.stringify(body),
    }
  )

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `Commit failed: ${res.status}`)
  }

  return await res.json()
}
