/**
 * A /files/ URL carries the account token only across origins (lib/fileUrl.ts): the dev setup
 * needs it for <img> tags, the packaged container has the session cookie and must not leak the
 * token into URLs.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { fileAuthToken } from '../ui/lib/fileUrl'

afterEach(() => {
  localStorage.clear()
})

describe('the token in file URLs', () => {
  it('is absent without a session', () => {
    expect(fileAuthToken('http://localhost:8000')).toBe('')
  })

  it('is added only when the backend is on another origin than the page', () => {
    localStorage.setItem('homepilot_auth_token', 'tok-123')
    const page = window.location.origin
    expect(fileAuthToken(page)).toBe('')                       // same origin: the cookie does it
    expect(fileAuthToken(`${page}/`)).toBe('')
    expect(fileAuthToken('')).toBe('')                         // relative backend = this origin
    expect(fileAuthToken('http://localhost:8000')).toBe(page === 'http://localhost:8000' ? '' : 'tok-123')
    expect(fileAuthToken('http://127.0.0.1:8002')).toBe('tok-123')
  })
})
