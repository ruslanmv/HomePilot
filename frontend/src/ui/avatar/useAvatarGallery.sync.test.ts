import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor, cleanup } from '@testing-library/react'
import { useAvatarGallery, resetAvatarGallerySync } from './useAvatarGallery'

function json(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response
}

const saved = [{ id: 'a1', url: '/comfy/view/avatar_00001_.png', mode: 'studio_random', createdAt: 5 }]

let calls: { method: string; url: string }[] = []

beforeEach(() => {
  localStorage.clear()
  resetAvatarGallerySync()
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ method: init?.method || 'GET', url: String(url) })
    if (String(url).endsWith('/v1/avatar-gallery')) return json({ ok: true, items: saved })
    return json({})
  }))
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const gets = () => calls.filter((c) => c.method === 'GET' && c.url.endsWith('/v1/avatar-gallery'))
const puts = () => calls.filter((c) => c.method === 'PUT')

describe('avatar gallery sync', () => {
  it('two users of the hook share one download and upload nothing unchanged', async () => {
    const a = renderHook(() => useAvatarGallery())
    const b = renderHook(() => useAvatarGallery())
    await waitFor(() => expect(a.result.current.serverLoaded && b.result.current.serverLoaded).toBe(true))
    await waitFor(() => expect(a.result.current.items.map((i) => i.id)).toEqual(['a1']))
    expect(gets().length).toBe(1)
    await new Promise((r) => setTimeout(r, 1000))
    expect(puts().length).toBe(0)
  })

  it('a revisit reuses the recent download with no loading state', async () => {
    const first = renderHook(() => useAvatarGallery())
    await waitFor(() => expect(first.result.current.serverLoaded).toBe(true))
    first.unmount()
    const again = renderHook(() => useAvatarGallery())
    expect(again.result.current.serverLoaded).toBe(true)
    expect(again.result.current.items.map((i) => i.id)).toEqual(['a1'])
    await new Promise((r) => setTimeout(r, 50))
    expect(gets().length).toBe(1)
  })

  it('a real change is saved once', async () => {
    const h = renderHook(() => useAvatarGallery())
    await waitFor(() => expect(h.result.current.serverLoaded).toBe(true))
    h.result.current.removeItem('a1')
    await waitFor(() => expect(puts().length).toBe(1), { timeout: 3000 })
  })
})
