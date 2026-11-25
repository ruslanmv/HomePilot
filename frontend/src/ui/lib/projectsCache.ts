/**
 * projectsCache — one in-memory copy of the signed-in account's /projects list,
 * shared by every page that needs it (Projects, Teams, Routines, Voice…).
 *
 * Pages are created fresh on every visit, so each one used to download the
 * whole list again (and some without the sign-in, which returns an empty list
 * because projects are private). Now:
 *   - the list is fetched with the sign-in (authFetch),
 *   - concurrent callers share one request,
 *   - a copy younger than `maxAgeMs` is reused without a request,
 *   - the copy is per backend + account, so switching accounts never shows
 *     another account's projects.
 */
import { authFetch } from './authFetch'
import { getCurrentUserId } from './userScopedStorage'

type Entry = { key: string; projects: any[]; fetchedAt: number }

let entry: Entry | null = null
let inflight: { key: string; promise: Promise<any[]> } | null = null

/** How long a fetched list is reused before pages refresh it. */
export const PROJECTS_FRESH_MS = 30_000

function keyFor(backendUrl: string): string {
  return `${(backendUrl || '').replace(/\/+$/, '')}|${getCurrentUserId()}`
}

/** The cached list for this backend + account, or null. Never fetches. */
export function peekProjects(backendUrl: string): { projects: any[]; fetchedAt: number } | null {
  const key = keyFor(backendUrl)
  return entry && entry.key === key ? { projects: entry.projects, fetchedAt: entry.fetchedAt } : null
}

/** Replace the cached list after a local change (create/edit/delete).
 *  Keeps the time of the last server fetch unless `fetched` is true. */
export function setCachedProjects(backendUrl: string, projects: any[], fetched = false): void {
  const key = keyFor(backendUrl)
  const fetchedAt = fetched ? Date.now() : entry && entry.key === key ? entry.fetchedAt : 0
  entry = { key, projects, fetchedAt }
}

export function clearProjectsCache(): void {
  entry = null
  inflight = null
}

/** Download the list now (sharing an in-flight request) and cache it. */
export function fetchProjects(backendUrl: string, apiKey?: string): Promise<any[]> {
  const key = keyFor(backendUrl)
  if (inflight && inflight.key === key) return inflight.promise
  const base = (backendUrl || '').replace(/\/+$/, '')
  const headers: Record<string, string> = {}
  if (apiKey) headers['x-api-key'] = apiKey
  const promise = authFetch(`${base}/projects`, { headers })
    .then(async (r) => {
      if (!r.ok) throw new Error(`projects HTTP ${r.status}`)
      const data = await r.json()
      const list: any[] = Array.isArray(data) ? data : data?.projects || []
      entry = { key, projects: list, fetchedAt: Date.now() }
      return list
    })
    .finally(() => {
      if (inflight && inflight.promise === promise) inflight = null
    })
  inflight = { key, promise }
  return promise
}

/** The list, from the cache when it is younger than `maxAgeMs`, else fetched. */
export async function getProjects(
  backendUrl: string,
  opts: { apiKey?: string; maxAgeMs?: number } = {},
): Promise<any[]> {
  const cached = peekProjects(backendUrl)
  const maxAge = opts.maxAgeMs ?? PROJECTS_FRESH_MS
  if (cached && Date.now() - cached.fetchedAt < maxAge) return cached.projects
  return fetchProjects(backendUrl, opts.apiKey)
}
