/**
 * A model download outlives the Models page. Going to the chat and back used to show plain
 * Install buttons while the backend was still downloading; the page now asks the backend what
 * is running when it opens and shows that download again — its row, the toast's progress line,
 * and the usual message when it ends (lib/installProgress.ts).
 */
import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ModelsView from '../ui/Models'

const BACKEND = 'http://hp.test'
const SD15 = 'sd15.safetensors'
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('a download still running when the Models page opens', () => {
  it('shows again in the toast and on its row, and ends with the usual message', async () => {
    const perModel = [
      { model_id: SD15, state: 'running', percent: 14, done: '549M', total: '4.0G', rate: '10.0MB/s' },
      { model_id: SD15, state: 'done', percent: 100 },
    ]
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/models/install/progress')) {
        return json({ installs: { [SD15]: { state: 'running', percent: 14, done: '549M', total: '4.0G', rate: '10.0MB/s' } } })
      }
      if (url.includes('/models/install/progress')) return json(perModel.length > 1 ? perModel.shift() : perModel[0])
      return json({ detail: 'not found' }, 404)          // no advisor, no catalog service, nothing installed
    })

    render(<ModelsView backendUrl={BACKEND} providerChat="ollama" />)

    expect(await screen.findByText(`Still downloading ${SD15}…`)).toBeTruthy()
    await waitFor(() => expect(screen.getByTestId('install-toast-progress').textContent).toBe('Downloading 14% · 549 MB of 4.0 GB · 10.0 MB/s'))

    fireEvent.click(screen.getByRole('radio', { name: /Image/ }))
    expect(await screen.findByText('Downloading 14%')).toBeTruthy()

    await waitFor(() => expect(screen.getByText(`Successfully installed ${SD15}`)).toBeTruthy(), { timeout: 4000 })
    expect(screen.queryByText('Downloading 14%')).toBeNull()
  })
})
