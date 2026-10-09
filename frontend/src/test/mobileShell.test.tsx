/**
 * Mobile shell regressions: dialogs escape transformed ancestors, Account
 * Settings is one sheet with a single-line Save All and protects unsaved edits,
 * startup never sits on a silent blank screen, and render errors are recoverable.
 */
import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ModalSheet } from '../ui/components/ModalSheet'
import { AppErrorBoundary } from '../ui/components/AppErrorBoundary'
import AuthGate, { AUTH_CHECK_TIMEOUT_MS, SLOW_START_HINT_MS } from '../ui/components/AuthGate'
import ProfileSettingsModal from '../ui/ProfileSettingsModal'

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
  localStorage.clear()
  document.body.style.overflow = ''
})

describe('ModalSheet', () => {
  it('renders at <body>, outside a transformed drawer, as a labelled modal dialog', () => {
    render(
      <div data-testid="drawer" style={{ transform: 'translateX(0)' }}>
        <ModalSheet labelledBy="t" onRequestClose={() => {}} header={<h2 id="t">Title</h2>} footer={<button>Save</button>}>
          <input aria-label="field" />
        </ModalSheet>
      </div>,
    )
    const dialog = screen.getByRole('dialog', { name: 'Title' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByTestId('drawer')).not.toContainElement(dialog)
    expect(dialog.closest('.hp-sheet-backdrop')?.parentElement).toBe(document.body)
    expect(document.body.style.overflow).toBe('hidden')
  })

  it('closes on Escape and on a backdrop press, and keeps Tab inside', () => {
    const onClose = vi.fn()
    render(
      <ModalSheet labelledBy="t" onRequestClose={onClose} header={<button>First</button>} footer={<button>Last</button>}>
        <span id="t">x</span>
      </ModalSheet>,
    )
    expect(screen.getByText('First')).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(screen.getByText('Last')).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.mouseDown(document.querySelector('.hp-sheet-backdrop')!)
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})

describe('Account Settings', () => {
  beforeEach(() => {
    localStorage.setItem('homepilot_auth_token', 't0k')
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/v1/user-profile')) return json({ ok: true, profile: { display_name: 'Alex', timezone: 'UTC' } })
      if (url.endsWith('/v1/user-profile/secrets')) return json({ ok: true, secrets: [] })
      if (url.endsWith('/v1/user-memory')) return json({ ok: true, memory: { items: [] } })
      return json({ ok: true })
    })
  })

  it('is one sheet: scrollable tabs, a single-line Save All, and a labelled close button', async () => {
    render(<ProfileSettingsModal backendUrl="http://hp" apiKey="" nsfwMode={false} onClose={() => {}} />)
    expect(await screen.findByRole('dialog', { name: 'Account Settings' })).toBeInTheDocument()
    expect(screen.getByRole('tablist', { name: 'Settings sections' })).toHaveClass('hp-tabs')
    expect(screen.getByRole('tab', { name: 'Profile' })).toHaveAttribute('aria-selected', 'true')
    const save = screen.getByRole('button', { name: 'Save All' })
    expect(save.className).toContain('whitespace-nowrap')
    expect(save.closest('.hp-sheet__footer')).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Close settings' })).toBeInTheDocument()
  })

  it('asks before discarding unsaved edits, and closes freely when nothing changed', async () => {
    const onClose = vi.fn()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<ProfileSettingsModal backendUrl="http://hp" apiKey="" nsfwMode={false} onClose={onClose} />)
    await waitFor(() => expect(screen.queryByLabelText('Loading your settings')).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }))
    expect(confirm).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)

    fireEvent.change(screen.getByDisplayValue('Alex'), { target: { value: 'Alexandra' } })
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }))
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1) // kept open: the person chose not to discard
  })
})

describe('Startup', () => {
  it('shows a visible startup screen, explains a slow start, then offers Retry instead of a blank screen', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))
      }),
    )
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<AuthGate><div>app</div></AuthGate>)
    expect(screen.getByRole('status')).toHaveTextContent('Starting HomePilot…')
    await act(async () => { vi.advanceTimersByTime(SLOW_START_HINT_MS + 10) })
    expect(screen.getByRole('status')).toHaveTextContent('waking up')
    await act(async () => { vi.advanceTimersByTime(AUTH_CHECK_TIMEOUT_MS) })
    expect(screen.getByRole('alert')).toHaveTextContent('Can’t reach HomePilot')
    expect(screen.queryByText('app')).not.toBeInTheDocument()

    fetchMock.mockImplementation(() => json({ user: null }))
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Retry' })) })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.getByText('app')).toBeInTheDocument()
  })

  it('Continue anyway keeps the old pre-auth path available', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<AuthGate><div>app</div></AuthGate>)
    fireEvent.click(await screen.findByRole('button', { name: 'Continue anyway' }))
    expect(screen.getByText('app')).toBeInTheDocument()
  })
})

describe('AppErrorBoundary', () => {
  it('turns a render error into a recoverable screen instead of a blank page', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    let explode = true
    function Fragile() {
      if (explode) throw new Error('kaboom')
      return <div>recovered</div>
    }
    render(<AppErrorBoundary><Fragile /></AppErrorBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong')
    expect(screen.getByText('Error: kaboom')).toBeInTheDocument()
    explode = false
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByText('recovered')).toBeInTheDocument()
  })
})
