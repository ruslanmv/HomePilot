import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import ModelStorageSettings from '../ModelStorageSettings'

const builtin = { path: '/repo/models/comfy', display_path: 'C:\repo\models\comfy', label: 'Built-in (current models)', builtin: true, exists: true, writable: true, is_download_target: true, free_gb: 9.6, total_gb: 929, model_files: 32 }
const ext = { path: '/mnt/e/homepilot-models', display_path: 'E:\homepilot-models', label: 'E:\homepilot-models', builtin: false, exists: true, writable: true, is_download_target: false, free_gb: 114, total_gb: 466, model_files: 0 }

function json(body: unknown, ok = true): Response {
  return { ok, status: ok ? 200 : 400, json: async () => body } as unknown as Response
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('ModelStorageSettings', () => {
  it('shows locations and adds a folder as a new location', async () => {
    const calls: { method: string; body?: any }[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      const method = init?.method || 'GET'
      calls.push({ method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (method === 'PUT') return json({ locations: [builtin, ext], download_target: 'C:\repo\models\comfy', download_target_fallback: false, restart_note: 'Restart.' })
      return json({ locations: [builtin], download_target: 'C:\repo\models\comfy', download_target_fallback: false, restart_note: 'Restart.' })
    }))
    render(<ModelStorageSettings />)
    expect(await screen.findByText('Built-in (current models)')).toBeTruthy()
    expect(screen.getByText(/9.6 GB free/)).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Folder to add as a model storage location'), { target: { value: 'E:\homepilot-models' } })
    fireEvent.click(screen.getByText('Add'))
    expect(await screen.findByText(/114 GB free/)).toBeTruthy()
    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.body).toEqual({ locations: [{ path: 'E:\homepilot-models' }], download_target: 'builtin' })
  })

  it('chooses a location for new downloads', async () => {
    const calls: any[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') { calls.push(JSON.parse(String(init.body))); return json({ locations: [{ ...builtin, is_download_target: false }, { ...ext, is_download_target: true }], download_target: 'E:\homepilot-models', download_target_fallback: false, restart_note: '' }) }
      return json({ locations: [builtin, ext], download_target: 'C:\repo\models\comfy', download_target_fallback: false, restart_note: '' })
    }))
    render(<ModelStorageSettings />)
    fireEvent.click(await screen.findByLabelText('Use E:\homepilot-models for new downloads'))
    expect(await screen.findByText('New downloads will go to E:\homepilot-models.')).toBeTruthy()
    expect(calls[0]).toEqual({ locations: [{ path: '/mnt/e/homepilot-models', label: 'E:\homepilot-models' }], download_target: '/mnt/e/homepilot-models' })
  })
})
