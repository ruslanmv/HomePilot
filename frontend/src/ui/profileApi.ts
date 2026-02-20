/**
 * Profile API client — additive module (v1).
 *
 * Talks to /v1/profile, /v1/profile/secrets, and /v1/memory endpoints.
 * NSFW on/off is NOT managed here — it remains global in SettingsPanel.
 */

export type UserProfile = {
  display_name: string
  email: string
  linkedin: string
  website: string
  company: string
  role: string
  country: string
  locale: string
  timezone: string
  bio: string

  personalization_enabled: boolean
  likes: string[]
  dislikes: string[]
  favorite_persona_tags: string[]
  preferred_tone: 'neutral' | 'friendly' | 'formal'
  allow_usage_for_recommendations: boolean

  // Companion
  companion_mode_enabled: boolean
  affection_level: 'friendly' | 'affectionate' | 'romantic'
  preferred_name: string
  preferred_pronouns: string
  preferred_terms_of_endearment: string[]
  hard_boundaries: string[]
  sensitive_topics: string[]
  consent_notes: string

  // Content preferences (NSFW is global)
  default_spicy_strength: number // 0..1
  allowed_content_tags: string[]
  blocked_content_tags: string[]
}

export type SecretListItem = {
  key: string
  masked: string
  description?: string
}

export type MemoryItem = {
  id: string
  text: string
  category: 'general' | 'likes' | 'dislikes' | 'relationship' | 'work' | 'health' | 'other'
  importance: number // 1..5
  last_confirmed_iso?: string
  source?: 'user' | 'inferred'
  pinned: boolean
}

function headers(apiKey: string) {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) h['X-API-Key'] = apiKey
  return h
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------

export async function fetchProfile(backendUrl: string, apiKey: string) {
  const res = await fetch(`${backendUrl}/v1/profile`, { headers: headers(apiKey) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to load profile')
  return data.profile as UserProfile
}

export async function saveProfile(backendUrl: string, apiKey: string, profile: UserProfile) {
  const res = await fetch(`${backendUrl}/v1/profile`, {
    method: 'PUT',
    headers: headers(apiKey),
    body: JSON.stringify(profile),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => '')
    throw new Error(txt || `HTTP ${res.status}`)
  }
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to save profile')
}

// ---------------------------------------------------------------------------
// Secrets
// ---------------------------------------------------------------------------

export async function listSecrets(backendUrl: string, apiKey: string) {
  const res = await fetch(`${backendUrl}/v1/profile/secrets`, { headers: headers(apiKey) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to load secrets')
  return data.secrets as SecretListItem[]
}

export async function upsertSecret(
  backendUrl: string,
  apiKey: string,
  body: { key: string; value: string; description?: string }
) {
  const res = await fetch(`${backendUrl}/v1/profile/secrets`, {
    method: 'PUT',
    headers: headers(apiKey),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to save secret')
}

export async function deleteSecret(backendUrl: string, apiKey: string, key: string) {
  const res = await fetch(`${backendUrl}/v1/profile/secrets/${encodeURIComponent(key)}`, {
    method: 'DELETE',
    headers: headers(apiKey),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to delete secret')
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export async function fetchMemory(backendUrl: string, apiKey: string) {
  const res = await fetch(`${backendUrl}/v1/memory`, { headers: headers(apiKey) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to load memory')
  return (data.memory?.items || []) as MemoryItem[]
}

export async function saveMemory(backendUrl: string, apiKey: string, items: MemoryItem[]) {
  const res = await fetch(`${backendUrl}/v1/memory`, {
    method: 'PUT',
    headers: headers(apiKey),
    body: JSON.stringify({ items }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to save memory')
}

export async function deleteMemoryItem(backendUrl: string, apiKey: string, id: string) {
  const res = await fetch(`${backendUrl}/v1/memory/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    headers: headers(apiKey),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!data.ok) throw new Error(data.message || 'Failed to delete memory item')
}
