/**
 * resolveFileUrl — centralized helper for resolving image URLs with auth tokens.
 *
 * Any URL that goes through the /files/ endpoint requires authentication.
 * Since <img> tags cannot send Authorization headers, we append the auth
 * token as a query parameter (?token=...).
 *
 * Usage:
 *   import { resolveFileUrl } from '../resolveFileUrl'
 *   <img src={resolveFileUrl(url, backendUrl)} />
 *
 * ADDITIVE ONLY — new utility, does not modify existing code.
 */

/**
 * Resolve an image URL so it works with authenticated /files/ endpoints.
 *
 * - Relative URLs are resolved against backendUrl
 * - URLs containing /files/ get a ?token= query parameter appended
 * - External URLs (not /files/) are returned as-is
 */
export function resolveFileUrl(url: string, backendUrl?: string): string {
  if (!url) return url

  // Pass through blob: and data: URLs unchanged
  if (url.startsWith('blob:') || url.startsWith('data:')) return url

  // Step 1: Make the URL absolute if it's relative
  let fullUrl = url
  if (!url.startsWith('http')) {
    const base = (backendUrl || localStorage.getItem('homepilot_backend_url') || 'http://localhost:8000').replace(/\/+$/, '')
    fullUrl = `${base}${url.startsWith('/') ? '' : '/'}${url}`
  }

  // Step 2: Append auth token for /files/ paths
  if (fullUrl.includes('/files/')) {
    const tok = localStorage.getItem('homepilot_auth_token') || ''
    if (tok) {
      const sep = fullUrl.includes('?') ? '&' : '?'
      fullUrl = `${fullUrl}${sep}token=${encodeURIComponent(tok)}`
    }
  }

  return fullUrl
}
