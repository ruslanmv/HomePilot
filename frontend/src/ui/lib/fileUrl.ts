/**
 * The account token to put in a /files/ (or /media/resolve) URL — only when the backend is on
 * another origin than this page, the Vite dev setup, where an <img> cannot carry the session
 * cookie. Same-origin — the packaged container, the Space — sends the HttpOnly cookie by itself,
 * and a URL with no credential in it can be copied, logged and cached without leaking the
 * account (docs/design/MEDIA_STORAGE.md, audit item A3). Sharing a file with someone else is
 * what signed links are for: GET /v1/files/{id}/link.
 */
export function fileAuthToken(backendUrl: string): string {
  let token = ''
  try {
    token = localStorage.getItem('homepilot_auth_token') || ''
  } catch {
    return ''
  }
  if (!token) return ''
  try {
    const page = window.location.origin
    const backend = new URL(backendUrl || '/', page).origin
    return backend === page ? '' : token
  } catch {
    return token
  }
}
