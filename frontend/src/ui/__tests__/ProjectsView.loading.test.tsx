import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import ProjectsView, { clearProjectsCache } from '../ProjectsView'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  clearProjectsCache()
})

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

describe('ProjectsView loading state', () => {
  it('shows a loading message, not "No projects yet", while projects load', async () => {
    let releaseProjects: (r: Response) => void = () => {}
    const projectsReply = new Promise<Response>((resolve) => { releaseProjects = resolve })

    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (String(url).endsWith('/projects')) return projectsReply
      return Promise.resolve(jsonResponse({}))
    }))

    render(<ProjectsView backendUrl="http://b" />)

    expect(screen.getByText('Loading your projects…')).toBeTruthy()
    expect(screen.queryByText('No projects yet')).toBeNull()

    await act(async () => {
      releaseProjects(jsonResponse({ projects: [] }))
      await projectsReply
    })

    expect(await screen.findByText('No projects yet')).toBeTruthy()
    expect(screen.queryByText('Loading your projects…')).toBeNull()
  })

  it('shows the cached list at once when the page is opened again', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (String(url).endsWith('/projects')) {
        return Promise.resolve(jsonResponse({ projects: [{ id: 'p1', name: 'Cached Project', updated_at: 1 }] }))
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ProjectsView backendUrl="http://b" />)
    expect(await screen.findByText('Cached Project')).toBeTruthy()
    cleanup()

    // Second visit: no loading screen, the project is there on the first render.
    render(<ProjectsView backendUrl="http://b" />)
    expect(screen.getByText('Cached Project')).toBeTruthy()
    expect(screen.queryByText('Loading your projects…')).toBeNull()
    // Opened again within a few seconds: no second download.
    const projectCalls = fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/projects'))
    expect(projectCalls.length).toBe(1)
  })
})
