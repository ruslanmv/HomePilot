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
import { resolveBackendUrl } from './lib/backendUrl'

export function resolveFileUrl(url: string, backendUrl?: string): string {
  if (!url) return url

  // Pass through blob: and data: URLs unchanged
  if (url.startsWith('blob:') || url.startsWith('data:')) return url

  // Step 1: Make the URL absolute if it's relative
  let fullUrl = url
  if (!url.startsWith('http')) {
    const base = resolveBackendUrl(backendUrl)
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

/**
 * Small cached thumbnail for gallery grids. ComfyUI images (/comfy/view/…, or
 * ComfyUI's own http://host:8188/view?filename=… links) are ~500 KB at full
 * size; the backend serves a ~10 KB WEBP when asked for ?thumb=<px>.
 * Any other link is returned as resolveFileUrl would return it.
 */
export function thumbUrl(url: string, backendUrl?: string, size = 384): string {
  if (!url) return url
  let path = url
  // ComfyUI's own /view link → the backend's /comfy/view proxy (served from disk).
  const m = /^https?:\/\/[^/]+\/view\?(.*)$/.exec(url)
  if (m) {
    const q = new URLSearchParams(m[1])
    const name = q.get('filename')
    if (name && (q.get('type') || 'output') === 'output') {
      const sub = q.get('subfolder')
      path = `/comfy/view/${encodeURIComponent(name)}${sub ? `?subfolder=${encodeURIComponent(sub)}` : ''}`
    }
  }
  const full = resolveFileUrl(path, backendUrl)
  if (!full.includes('/comfy/view/') || /[?&]thumb=/.test(full)) return full
  return `${full}${full.includes('?') ? '&' : '?'}thumb=${size}`
}
