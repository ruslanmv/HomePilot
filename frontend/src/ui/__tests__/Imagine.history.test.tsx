import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import ImagineView from '../Imagine'

function json(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function page(from: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `srv_${from + i}`,
    url: `/comfy/view/img_${from + i}.png`,
    createdAt: 1_000_000 - (from + i),
    prompt: `prompt ${from + i}`,
    status: 'done',
  }))
}

beforeEach(() => {
  localStorage.clear()
  // jsdom has no scrollIntoView; the page scrolls its grid to the top on load.
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Imagine server history', () => {
  it('shows saved images from the server and loads more on demand', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(String(url))
      if (String(url).includes('/v1/imagine/history')) {
        const offset = Number(new URL(String(url)).searchParams.get('offset') || 0)
        return json({ ok: true, items: offset === 0 ? page(0, 60) : page(60, 10), total: 70 })
      }
      return json({})
    }))

    render(<ImagineView backendUrl="http://b" providerImages="comfyui" />)

    expect(await screen.findByAltText('prompt 0')).toBeTruthy()
    expect(screen.getByText('Showing 60 of 70 saved images')).toBeTruthy()
    expect(screen.queryByText('Your gallery is empty')).toBeNull()

    fireEvent.click(screen.getByText('Load more images'))
    expect(await screen.findByAltText('prompt 69')).toBeTruthy()
    await waitFor(() => expect(screen.queryByText('Load more images')).toBeNull())
    expect(calls.some((u) => u.includes('offset=60'))).toBe(true)
  })
})
