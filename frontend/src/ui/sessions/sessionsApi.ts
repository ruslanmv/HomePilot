/**
 * Persona Sessions API Client — Companion-Grade
 *
 * Handles session lifecycle: create, resolve, end, list.
 * Also handles Long-Term Memory (LTM) queries.
 *
 * Additive: does not modify any existing API calls.
 */

export interface PersonaSession {
  id: string
  project_id: string
  conversation_id: string
  mode: 'voice' | 'text'
  title: string | null
  started_at: string
  ended_at: string | null
  message_count: number
  summary: string | null
}

export interface PersonaMemoryEntry {
  id: number
  project_id: string
  category: string
  key: string
  value: string
  confidence: number
  source_type: string
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function getBackendUrl(): string {
  return (localStorage.getItem('homepilot_backend_url') || 'http://localhost:8000').replace(/\/+$/, '')
}

function getAuthHeaders(): Record<string, string> {
  const apiKey = localStorage.getItem('homepilot_api_key') || ''
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
  return headers
}

// ---------------------------------------------------------------------------
// Session API
// ---------------------------------------------------------------------------

/**
 * Resolve the best session to resume (or create one if none exist).
 * This is the main entry point — bulletproof resume algorithm.
 */
export async function resolveSession(
  projectId: string,
  mode: 'voice' | 'text' = 'text'
): Promise<PersonaSession> {
  const res = await fetch(`${getBackendUrl()}/persona/sessions/resolve`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ project_id: projectId, mode }),
  })
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to resolve session')
  return data.session
}

/**
 * Create a brand new session for a persona project.
 */
export async function createSession(
  projectId: string,
  mode: 'voice' | 'text' = 'text',
  title?: string
): Promise<PersonaSession> {
  const res = await fetch(`${getBackendUrl()}/persona/sessions`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ project_id: projectId, mode, title }),
  })
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to create session')
  return data.session
}

/**
 * End a session (marks ended_at, triggers summary + memory extraction).
 */
export async function endSession(sessionId: string): Promise<void> {
  await fetch(`${getBackendUrl()}/persona/sessions/${sessionId}/end`, {
    method: 'POST',
    headers: getAuthHeaders(),
  })
}

/**
 * List all sessions for a persona project.
 */
export async function listSessions(
  projectId: string,
  limit = 50
): Promise<PersonaSession[]> {
  const res = await fetch(
    `${getBackendUrl()}/persona/sessions?project_id=${encodeURIComponent(projectId)}&limit=${limit}`,
    { headers: getAuthHeaders() }
  )
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to list sessions')
  return data.sessions
}

/**
 * Get a single session by ID.
 */
export async function getSession(sessionId: string): Promise<PersonaSession> {
  const res = await fetch(`${getBackendUrl()}/persona/sessions/${sessionId}`, {
    headers: getAuthHeaders(),
  })
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to get session')
  return data.session
}

// ---------------------------------------------------------------------------
// Long-Term Memory API
// ---------------------------------------------------------------------------

/**
 * Get all memories for a persona project ("What I know about you").
 */
export async function getMemories(
  projectId: string,
  category?: string
): Promise<{ memories: PersonaMemoryEntry[]; count: number }> {
  const params = new URLSearchParams({ project_id: projectId })
  if (category) params.set('category', category)

  const res = await fetch(`${getBackendUrl()}/persona/memory?${params}`, {
    headers: getAuthHeaders(),
  })
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to get memories')
  return { memories: data.memories, count: data.count }
}

/**
 * Manually add or update a memory entry.
 */
export async function upsertMemory(
  projectId: string,
  category: string,
  key: string,
  value: string,
  confidence = 1.0
): Promise<void> {
  await fetch(`${getBackendUrl()}/persona/memory`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({
      project_id: projectId,
      category,
      key,
      value,
      confidence,
      source_type: 'user_statement',
    }),
  })
}

/**
 * Delete a specific memory or forget all.
 */
export async function forgetMemory(
  projectId: string,
  category?: string,
  key?: string
): Promise<void> {
  await fetch(`${getBackendUrl()}/persona/memory`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
    body: JSON.stringify({ project_id: projectId, category, key }),
  })
}
