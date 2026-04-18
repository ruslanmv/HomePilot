import { afterEach, describe, expect, it, vi } from 'vitest'
import { resolveBackendUrl } from './backendUrl'

afterEach(() => {
  window.localStorage.clear()
  vi.unstubAllGlobals()
})

describe('resolveBackendUrl', () => {
  it('falls back to localhost:8000 when stored backend points to local vite dev port', () => {
    vi.stubGlobal('location', {
      hostname: 'localhost',
      origin: 'http://localhost:3000',
      port: '3000',
      protocol: 'http:',
    })

    window.localStorage.setItem('homepilot_backend_url', 'http://localhost:3000')

    expect(resolveBackendUrl()).toBe('http://localhost:8000')
  })

  it('keeps stored localhost backend when it targets a non-vite port', () => {
    vi.stubGlobal('location', {
      hostname: 'localhost',
      origin: 'http://localhost:3000',
      port: '3000',
      protocol: 'http:',
    })

    window.localStorage.setItem('homepilot_backend_url', 'http://localhost:8010')

    expect(resolveBackendUrl()).toBe('http://localhost:8010')
  })
})
