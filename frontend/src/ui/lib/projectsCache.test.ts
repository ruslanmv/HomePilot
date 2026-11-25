import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearProjectsCache, getProjects, peekProjects } from './projectsCache'

function json(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response
}

let calls: { url: string; auth: string | null }[] = []
beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('homepilot_auth_token', 'tok')
  localStorage.setItem('homepilot_auth_user', JSON.stringify({ id: 'u1' }))
  clearProjectsCache()
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), auth: new Headers(init?.headers).get('Authorization') })
    return json({ projects: [{ id: 'p1', project_type: 'persona' }] })
  }))
})
afterEach(() => vi.unstubAllGlobals())

describe('projectsCache', () => {
  it('sends the sign-in, shares one request, then reuses the copy', async () => {
    const [a, b] = await Promise.all([getProjects('http://b'), getProjects('http://b/')])
    expect(a).toEqual(b)
    expect(calls).toHaveLength(1)
    expect(calls[0].auth).toBe('Bearer tok')
    await getProjects('http://b')
    expect(calls).toHaveLength(1)
    expect(peekProjects('http://b')?.projects[0].id).toBe('p1')
  })

  it('keeps accounts apart', async () => {
    await getProjects('http://b')
    localStorage.setItem('homepilot_auth_user', JSON.stringify({ id: 'u2' }))
    expect(peekProjects('http://b')).toBeNull()
    await getProjects('http://b')
    expect(calls).toHaveLength(2)
  })
})
