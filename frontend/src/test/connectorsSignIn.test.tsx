/**
 * Settings → Connectors → "Continue with Hugging Face" opens the provider's sign-in page in the
 * click itself. It used to open an empty window and point it at Hugging Face after the server
 * answered, which left that window blank in the Space (HomePilot runs there inside an iframe).
 */
import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import ConnectorsPanel from '../ui/connectors/ConnectorsPanel'

const SIGN_IN = 'https://huggingface.co/oauth/authorize?client_id=abc&state=s1'

const hf = {
  id: 'huggingface', name: 'Hugging Face', description: 'Models on your account.', auth: 'token',
  oauth: true, grants: ['Run models'], billing: 'Billed to you.', connected: false,
}

describe('Continue with Hugging Face', () => {
  let starts = 0
  beforeEach(() => {
    starts = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/oauth/start') && init?.method === 'POST') {
        starts += 1
        return new Response(JSON.stringify({ ok: true, url: SIGN_IN }), { status: 200 })
      }
      return new Response(JSON.stringify({ ok: true, connectors: [hf] }), { status: 200 })
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('opens the sign-in page itself on the first click, never a blank window', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({ closed: false, close() {} } as unknown as Window)
    render(<ConnectorsPanel backendUrl="http://hp.test" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Connect' }))
    // The sheet makes the one-use sign-in URL while it is read.
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    expect(starts).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: /Continue with Hugging Face/ }))
    expect(open).toHaveBeenCalledTimes(1)
    expect(open.mock.calls[0][0]).toBe(SIGN_IN)
    expect(await screen.findByText(/Finish in the Hugging Face window/)).toBeTruthy()
  })

  it('says so when the browser blocks the window, and offers the link', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    render(<ConnectorsPanel backendUrl="http://hp.test" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Connect' }))
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    fireEvent.click(screen.getByRole('button', { name: /Continue with Hugging Face/ }))
    expect(await screen.findByText('Your browser blocked the window')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Open Hugging Face sign-in/ }).getAttribute('href')).toBe(SIGN_IN)
  })
})
