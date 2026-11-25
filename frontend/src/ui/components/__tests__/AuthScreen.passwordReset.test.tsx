import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import AuthScreen from '../AuthScreen'

type Call = { url: string; body?: any }

function mockFetch(handlers: Record<string, (body: any) => { status?: number; json: any }>) {
  const calls: Call[] = []
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ url, body })
    const key = Object.keys(handlers).find((k) => url.endsWith(k))
    const out = key ? handlers[key](body) : { status: 404, json: {} }
    return { ok: (out.status ?? 200) < 400, status: out.status ?? 200, json: async () => out.json } as Response
  })
  vi.stubGlobal('fetch', fn)
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('AuthScreen local password reset', () => {
  it('requests a code, then sets a new password and signs in', async () => {
    const calls = mockFetch({
      '/v1/auth/password-reset/status': () => ({ json: { enabled: true } }),
      '/v1/auth/password-reset/request': () => ({ json: { ok: true } }),
      '/v1/auth/password-reset/confirm': () => ({
        json: { ok: true, token: 't1', user: { id: 'u1', username: 'alice' } },
      }),
    })
    const onAuthenticated = vi.fn()
    render(<AuthScreen backendUrl="http://b" onAuthenticated={onAuthenticated} />)

    fireEvent.click(screen.getByText('Forgot password?'))
    await screen.findByText('Get a reset code')
    fireEvent.change(screen.getByLabelText('Username or email', { selector: '#fpIdentifier' }), {
      target: { value: 'alice' },
    })
    fireEvent.click(screen.getByText('Get a reset code'))

    await screen.findByLabelText('Reset code')
    fireEvent.change(screen.getByLabelText('Reset code'), { target: { value: 'ABCDE-FGHJK' } })
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'newpassword1' } })
    fireEvent.change(screen.getByLabelText('Confirm new password'), { target: { value: 'newpassword1' } })
    fireEvent.click(screen.getByText('Set new password'))

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith({ id: 'u1', username: 'alice' }, 't1'))
    const confirm = calls.find((c) => c.url.endsWith('/confirm'))
    expect(confirm?.body).toEqual({ identifier: 'alice', code: 'ABCDE-FGHJK', new_password: 'newpassword1' })
  })

  it('shows only the terminal route when the backend does not answer the status call', async () => {
    mockFetch({})
    render(<AuthScreen backendUrl="http://b" onAuthenticated={() => {}} />)
    fireEvent.click(screen.getByText('Forgot password?'))
    expect((await screen.findAllByText(/python -m app.password_reset YOUR_USERNAME --set-password/)).length).toBeGreaterThan(0)
    expect(screen.queryByText('Get a reset code')).toBeNull()
  })

  it('shows the command line route when web reset is off', async () => {
    mockFetch({ '/v1/auth/password-reset/status': () => ({ json: { enabled: false } }) })
    render(<AuthScreen backendUrl="http://b" onAuthenticated={() => {}} />)
    fireEvent.click(screen.getByText('Forgot password?'))
    expect((await screen.findAllByText(/python -m app.password_reset/)).length).toBeGreaterThan(0)
  })
})
