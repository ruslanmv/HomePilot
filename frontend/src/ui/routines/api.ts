import type { Routine, RoutineDraft, RoutineRun } from './types'

export type RoutineTargetProject = {
  id: string
  name: string
  description?: string
  project_type?: string
  is_example?: boolean
}

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

export async function listRoutineTargetProjects(
  backendUrl: string,
  apiKey?: string,
): Promise<RoutineTargetProject[]> {
  const response = await fetch(`${backendUrl}/projects`, {
    credentials: 'include',
    headers: headers(apiKey),
  })
  const body = await readJson(response)
  const projects = Array.isArray(body.projects) ? body.projects : []
  return projects.filter((project: RoutineTargetProject) => project?.id && !project.is_example)
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


export async function runRoutineNow(
  backendUrl: string,
  id: string,
  apiKey?: string,
): Promise<RoutineRun> {
  const response = await fetch(`${backendUrl}/v1/routines/${encodeURIComponent(id)}/run`, {
    method: 'POST',
    credentials: 'include',
    headers: headers(apiKey),
  })
  return readJson(response)
}

export async function listRoutineRuns(
  backendUrl: string,
  routineId?: string,
  apiKey?: string,
  limit = 50,
): Promise<RoutineRun[]> {
  const path = routineId
    ? `/v1/routines/${encodeURIComponent(routineId)}/runs?limit=${limit}`
    : `/v1/routines/runs?limit=${limit}`
  const response = await fetch(`${backendUrl}${path}`, {
    credentials: 'include',
    headers: headers(apiKey),
  })
  const body = await readJson(response)
  return Array.isArray(body.runs) ? body.runs : []
}

export async function listUnreadRoutineRuns(
  backendUrl: string,
  apiKey?: string,
): Promise<RoutineRun[]> {
  const response = await fetch(`${backendUrl}/v1/routines/runs?unseen_only=true&limit=20`, {
    credentials: 'include',
    headers: headers(apiKey),
  })
  const body = await readJson(response)
  return Array.isArray(body.runs) ? body.runs : []
}

export async function markRoutineRunSeen(
  backendUrl: string,
  runId: string,
  apiKey?: string,
  opened = false,
): Promise<RoutineRun> {
  const response = await fetch(
    `${backendUrl}/v1/routines/runs/${encodeURIComponent(runId)}/seen?opened=${opened ? 'true' : 'false'}`,
    {
      method: 'PATCH',
      credentials: 'include',
      headers: headers(apiKey),
    },
  )
  return readJson(response)
}
