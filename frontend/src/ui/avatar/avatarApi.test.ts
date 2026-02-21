/**
 * Avatar API client tests — validates request building and response parsing.
 *
 * Uses a minimal fetch mock; no real network calls.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchAvatarPacks, generateAvatars } from './avatarApi'
import type { AvatarPacksResponse, AvatarGenerateResponse } from './types'

// ---------------------------------------------------------------------------
// Mock fetch
// ---------------------------------------------------------------------------

const mockFetch = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch)
  mockFetch.mockReset()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('fetchAvatarPacks', () => {
  const PACKS_RESPONSE: AvatarPacksResponse = {
    packs: [
      {
        id: 'basic',
        title: 'Basic',
        installed: true,
        license: 'Apache-2.0',
        commercial_ok: true,
        modes_enabled: ['studio_random', 'studio_reference'],
      },
    ],
    enabled_modes: ['studio_random', 'studio_reference'],
  }

  it('calls the correct endpoint', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(PACKS_RESPONSE),
    })

    await fetchAvatarPacks('http://localhost:8000')
    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8000/v1/avatars/packs',
      { headers: {} },
    )
  })

  it('strips trailing slash from backendUrl', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(PACKS_RESPONSE),
    })

    await fetchAvatarPacks('http://localhost:8000/')
    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8000/v1/avatars/packs',
      expect.anything(),
    )
  })

  it('sends API key header when provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(PACKS_RESPONSE),
    })

    await fetchAvatarPacks('http://localhost:8000', 'secret-key')
    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      { headers: { 'x-api-key': 'secret-key' } },
    )
  })

  it('returns parsed response on success', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(PACKS_RESPONSE),
    })

    const result = await fetchAvatarPacks('http://localhost:8000')
    expect(result.packs).toHaveLength(1)
    expect(result.enabled_modes).toContain('studio_random')
  })

  it('throws on HTTP error', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      text: () => Promise.resolve('Internal Server Error'),
    })

    await expect(fetchAvatarPacks('http://localhost:8000')).rejects.toThrow(
      'Internal Server Error',
    )
  })
})

describe('generateAvatars', () => {
  const GEN_RESPONSE: AvatarGenerateResponse = {
    mode: 'studio_random',
    results: [
      { url: '/files/avatar_001.png', seed: 42 },
      { url: '/files/avatar_002.png', seed: 43 },
    ],
  }

  it('sends POST with correct body', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(GEN_RESPONSE),
    })

    await generateAvatars('http://localhost:8000', {
      mode: 'studio_random',
      count: 2,
      truncation: 0.7,
    })

    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8000/v1/avatars/generate',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
      }),
    )

    // Verify body contents
    const callArgs = mockFetch.mock.calls[0]
    const body = JSON.parse(callArgs[1].body)
    expect(body.mode).toBe('studio_random')
    expect(body.count).toBe(2)
    expect(body.truncation).toBe(0.7)
  })

  it('sends API key when provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(GEN_RESPONSE),
    })

    await generateAvatars(
      'http://localhost:8000',
      { mode: 'studio_random' },
      'my-api-key',
    )

    const headers = mockFetch.mock.calls[0][1].headers
    expect(headers['x-api-key']).toBe('my-api-key')
  })

  it('returns results on success', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(GEN_RESPONSE),
    })

    const result = await generateAvatars('http://localhost:8000', {
      mode: 'studio_random',
    })
    expect(result.results).toHaveLength(2)
    expect(result.results[0].seed).toBe(42)
  })

  it('throws on HTTP error', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      text: () => Promise.resolve('Service Unavailable'),
    })

    await expect(
      generateAvatars('http://localhost:8000', { mode: 'studio_random' }),
    ).rejects.toThrow('Service Unavailable')
  })

  it('includes reference_image_url for reference mode', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(GEN_RESPONSE),
    })

    await generateAvatars('http://localhost:8000', {
      mode: 'studio_reference',
      reference_image_url: 'http://localhost:8000/uploads/face.png',
    })

    const body = JSON.parse(mockFetch.mock.calls[0][1].body)
    expect(body.reference_image_url).toBe(
      'http://localhost:8000/uploads/face.png',
    )
  })
})
