/**
 * fetch() that identifies the signed-in user to HomePilot's backend.
 *
 * Projects are private to their owner, so project requests must say who is
 * asking. Same-origin deployments already send the session cookie; this also
 * covers a frontend served from another origin (local development) by sending
 * the session token and including credentials.
 */
export function authToken(): string {
  try {
    return localStorage.getItem('homepilot_auth_token') || ''
  } catch {
    return ''
  }
}

export function authFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {})
  const token = authToken()
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
  return fetch(input, { ...init, headers, credentials: init.credentials ?? 'include' })
}
