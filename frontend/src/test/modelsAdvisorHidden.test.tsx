/**
 * Model suggestions switched off ("Hide suggestions", or Settings → Models) leave one quiet
 * line on the Models page with the way back — the toast that said where to turn them on is
 * long gone by the time someone wonders where the suggested image models went.
 */
import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ModelsView from '../ui/Models'
import { advisorEnabled, setAdvisorEnabled } from '../ui/modelAdvisor'

const BACKEND = 'http://hp.test'

beforeEach(() => {
  localStorage.clear()
  // Nothing on the page needs a real backend for this: every request is a 404 JSON answer.
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
    new Response(JSON.stringify({ detail: 'not found' }), { status: 404, headers: { 'content-type': 'application/json' } }))
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('hidden model suggestions', () => {
  it('say so on the Models page, and come back from there', async () => {
    setAdvisorEnabled(false)
    render(<ModelsView backendUrl={BACKEND} providerChat="ollama" />)

    const line = await screen.findByTestId('advisor-hidden')
    expect(line.textContent).toContain('Model suggestions for this computer are hidden.')
    expect(screen.queryByText('Suggested for your GPU')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Show them' }))
    expect(advisorEnabled()).toBe(true)
    await waitFor(() => expect(screen.getByText('Suggested for your GPU')).toBeTruthy())
    expect(screen.queryByTestId('advisor-hidden')).toBeNull()
  })

  it('are not mentioned while they are on', async () => {
    render(<ModelsView backendUrl={BACKEND} providerChat="ollama" />)
    await screen.findByText('Suggested for your GPU')
    expect(screen.queryByTestId('advisor-hidden')).toBeNull()
  })
})
