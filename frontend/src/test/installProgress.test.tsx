/**
 * Installing a model shows real progress — from the catalog rows and from the suggestions card
 * alike (lib/installProgress.ts, components/InstallProgress.tsx).
 *
 * The suggestions card used to show a bare spinner while a 6 GB checkpoint downloaded. It now
 * has the catalog rows' downloading look, with the percentage, and a bar with size and speed —
 * read once a second from GET /models/install/progress while the install request runs.
 *
 * And a download outlives the page: leaving Models for the chat and coming back used to show
 * a plain Install button while the backend was still at 14%. The card now asks the backend
 * what is running when it mounts and picks the download up where it is.
 */
import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ModelAdvisorCard } from '../ui/components/ModelAdvisorCard'
import { parseInstallProgress, progressLabel } from '../ui/lib/installProgress'

const SDXL = 'sd_xl_base_1.0.safetensors'
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
const ADVISOR = {
  ok: true, enabled: true, app_version: '2', hardware: { kind: 'nvidia', name: 'RTX', vram_gb: 6, detected: true },
  feeds: { llm: { source: 'bundled' }, media: { source: 'bundled' } }, fetch: null, attribution: 'FitLab',
  suggestions: {
    chat: [], vision: [], video: [],
    image: [{ id: 'sdxl', name: 'SDXL Base 1.0', kind: 'image', verdict: 'fits', score: 1, reasons: ['Fits'],
      install: { provider: 'comfyui', model_type: 'image', model_id: SDXL }, installed: false, download_gb: 6.94 }],
  },
}
const RUNNING_14 = { state: 'running', percent: 14, done: '549M', total: '4.0G', rate: '10.0MB/s' }

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('the progress line', () => {
  it('says the stage, then the percent, size and speed', () => {
    expect(progressLabel(null)).toBe('Starting the download…')
    expect(progressLabel(parseInstallProgress({ state: 'running', percent: null, stage: 'Validating download source' })))
      .toBe('Validating download source…')
    expect(progressLabel(parseInstallProgress({ state: 'running', percent: 42, done: '2.71G', total: '6.46G', rate: '5.63MB/s' })))
      .toBe('Downloading 42% · 2.7 GB of 6.5 GB · 5.63 MB/s')
    expect(progressLabel(parseInstallProgress({ state: 'running', percent: 42, done: '845 MB', total: '2.0 GB', rate: '25 MB/s' })))
      .toBe('Downloading 42% · 845 MB of 2.0 GB · 25 MB/s')
    expect(progressLabel(parseInstallProgress({ state: 'done' }))).toBe('Installed — finishing up…')
  })
})

describe('installing a suggestion', () => {
  it('shows the downloading button with the percent and a progress bar, then reports done', async () => {
    let finish: (v: Response) => void = () => undefined
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/models/install/progress')) return Promise.resolve(json({ installs: {} }))   // nothing to pick up
      if (url.includes('/models/install/progress')) {
        return Promise.resolve(json({ model_id: SDXL, state: 'running', percent: 42, done: '2.71G', total: '6.46G', rate: '5.63MB/s' }))
      }
      if (url.includes('/models/install')) return new Promise<Response>((resolve) => { finish = resolve })
      return Promise.resolve(json(ADVISOR))
    })
    const onBusyChange = vi.fn()
    render(<ModelAdvisorCard backendUrl="http://hp" initialKind="image" onBusyChange={onBusyChange} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Install' }))  // asks first
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))         // confirms
    expect(onBusyChange).toHaveBeenCalledWith(SDXL)

    expect(await screen.findByText('Downloading 42%')).toBeTruthy()
    const bar = await screen.findByTestId('install-progress')
    await waitFor(() => expect(bar.textContent).toBe('Downloading 42% · 2.7 GB of 6.5 GB · 5.63 MB/s'))
    expect(screen.getByRole('progressbar', { name: 'Download progress' }).getAttribute('aria-valuenow')).toBe('42')

    finish(json({ ok: true, message: `Successfully installed ${SDXL}` }))
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(null))
    await waitFor(() => expect(screen.queryByTestId('install-progress')).toBeNull())
  })
})

describe('a download still running when the card mounts', () => {
  /** The backend: one install running at 14%; its own progress answers `perModel` in turn. */
  function backend(perModel: unknown[]) {
    const seen = { install: 0 }
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/models/install/progress')) return Promise.resolve(json({ installs: { [SDXL]: RUNNING_14 } }))
      if (url.includes('/models/install/progress')) return Promise.resolve(json(perModel.length > 1 ? perModel.shift() : perModel[0]))
      if (url.includes('/models/install')) { seen.install += 1; return Promise.resolve(json({ ok: true })) }
      return Promise.resolve(json(ADVISOR))
    })
    return seen
  }

  it('is picked up where it is, without a new install request, and ends the usual way', async () => {
    const seen = backend([{ model_id: SDXL, ...RUNNING_14 }, { model_id: SDXL, state: 'done', percent: 100 }])
    const onBusyChange = vi.fn()
    const onToast = vi.fn()
    const onInstalled = vi.fn()
    render(<ModelAdvisorCard backendUrl="http://hp" initialKind="image" onBusyChange={onBusyChange} onToast={onToast} onInstalled={onInstalled} />)

    expect(await screen.findByText('Downloading 14%')).toBeTruthy()      // nobody clicked Install
    expect(onBusyChange).toHaveBeenCalledWith(SDXL)
    await waitFor(() => expect(screen.getByRole('progressbar', { name: 'Download progress' }).getAttribute('aria-valuenow')).toBe('14'))

    await waitFor(() => expect(onInstalled).toHaveBeenCalled(), { timeout: 4000 })   // the next poll says done
    expect(onToast).toHaveBeenLastCalledWith('SDXL Base 1.0 installed.')
    expect(onBusyChange).toHaveBeenLastCalledWith(null)
    await waitFor(() => expect(screen.queryByTestId('install-progress')).toBeNull())
    expect(seen.install).toBe(0)
  })

  it('is let go when the backend no longer knows it', async () => {
    backend([{ model_id: SDXL, state: 'idle' }])
    const onBusyChange = vi.fn()
    const onToast = vi.fn()
    render(<ModelAdvisorCard backendUrl="http://hp" initialKind="image" onBusyChange={onBusyChange} onToast={onToast} />)

    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(SDXL))
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(null))
    expect(onToast.mock.calls.at(-1)?.[0]).toContain('Lost track of the SDXL Base 1.0 download')
    expect(screen.getByRole('button', { name: 'Install' })).toBeTruthy()
  })
})
