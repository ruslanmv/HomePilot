import type { Routine, RoutineDraft } from './types'

function headers(apiKey?: string): HeadersInit {
  const out: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) out['X-API-Key'] = apiKey
  return out
}

async function readJson(response: Response) {
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(body?.detail || body?.message || `Request failed (${response.status})`)
  }
  return body
}

export async function listRoutines(backendUrl: string, apiKey?: string): Promise<Routine[]> {
  const response = await fetch(`${backendUrl}/v1/routines`, {
    credentials: 'include',
    headers: headers(apiKey),
  })
  const body = await readJson(response)
  return Array.isArray(body.routines) ? body.routines : []
}

export async function createRoutine(
  backendUrl: string,
  draft: RoutineDraft,
  apiKey?: string,
): Promise<Routine> {
  const response = await fetch(`${backendUrl}/v1/routines`, {
    method: 'POST',
    credentials: 'include',
    headers: headers(apiKey),
    body: JSON.stringify(draft),
  })
  return readJson(response)
}

export async function updateRoutine(
  backendUrl: string,
  id: string,
  patch: Partial<RoutineDraft>,
  apiKey?: string,
): Promise<Routine> {
  const response = await fetch(`${backendUrl}/v1/routines/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: headers(apiKey),
    body: JSON.stringify(patch),
  })
  return readJson(response)
}

export async function deleteRoutine(backendUrl: string, id: string, apiKey?: string): Promise<void> {
  const response = await fetch(`${backendUrl}/v1/routines/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: headers(apiKey),
  })
  await readJson(response)
}
