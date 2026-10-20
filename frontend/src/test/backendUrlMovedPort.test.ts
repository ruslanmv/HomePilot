/**
 * `make start` may move the backend off :8000 when another program holds it (for example a
 * kubectl port-forward) and passes the new address as VITE_API_URL. A saved localhost:8000
 * must follow; any other saved address must be kept.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { followMovedDevBackend, getDefaultBackendUrl, resolveBackendUrl } from '../ui/lib/backendUrl'

afterEach(() => {
  vi.unstubAllEnvs()
  localStorage.clear()
})

describe('backend that make start moved to another port', () => {
  it('uses the moved address by default', () => {
    vi.stubEnv('VITE_API_URL', 'http://localhost:8002')
    expect(getDefaultBackendUrl()).toBe('http://localhost:8002')
    expect(resolveBackendUrl()).toBe('http://localhost:8002')
  })

  it('moves a saved or passed localhost:8000 along with it', () => {
    vi.stubEnv('VITE_API_URL', 'http://localhost:8002')
    localStorage.setItem('homepilot_backend_url', 'http://localhost:8000/')
    expect(resolveBackendUrl()).toBe('http://localhost:8002')
    expect(resolveBackendUrl('http://127.0.0.1:8000')).toBe('http://localhost:8002')
  })

  it('keeps any other saved address', () => {
    vi.stubEnv('VITE_API_URL', 'http://localhost:8002')
    expect(resolveBackendUrl('http://localhost:9000')).toBe('http://localhost:9000')
    expect(resolveBackendUrl('https://pilot.example.com')).toBe('https://pilot.example.com')
    localStorage.setItem('homepilot_backend_url', 'http://192.168.1.20:8000')
    expect(resolveBackendUrl()).toBe('http://192.168.1.20:8000')
  })

  it('changes nothing when the backend was not moved', () => {
    vi.stubEnv('VITE_API_URL', '')
    expect(followMovedDevBackend('http://localhost:8000')).toBe('http://localhost:8000')
    expect(resolveBackendUrl('http://localhost:8000')).toBe('http://localhost:8000')
  })

  it('never redirects to a remote configured address', () => {
    vi.stubEnv('VITE_API_URL', 'https://pilot.example.com')
    expect(followMovedDevBackend('http://localhost:8000')).toBe('http://localhost:8000')
  })
})
