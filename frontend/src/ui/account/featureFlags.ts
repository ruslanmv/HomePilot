/**
 * Feature flags for the Account & Computers spine (Batch 2).
 *
 * Everything here is OFF by default so mounting the providers is a no-op until
 * explicitly enabled — the spine must never change today's behavior.
 */

function lsGet(key: string): string | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null
  } catch {
    return null
  }
}

/**
 * Master switch for the Account & Computers experience. Enable via a build-time
 * env (`VITE_ACCOUNTS_UX=1`) or at runtime (`localStorage.homepilot_accounts_ux = '1'`).
 * When false the providers render children but do no network and hold empty state.
 */
export function isAccountsUxEnabled(): boolean {
  try {
    const env = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_ACCOUNTS_UX
    if (env === '1' || env === 'true') return true
  } catch {
    /* import.meta not available (e.g. tests) */
  }
  return lsGet('homepilot_accounts_ux') === '1'
}

/**
 * Dev-only visibility for the mirror debug panel. Enable with `?mirrorDebug=1`
 * in the URL or `localStorage.homepilot_mirror_debug = '1'`.
 */
export function isMirrorDebug(): boolean {
  try {
    if (typeof location !== 'undefined') {
      const q = new URLSearchParams(location.search).get('mirrorDebug')
      if (q === '1' || q === 'true') return true
    }
  } catch {
    /* no location */
  }
  return lsGet('homepilot_mirror_debug') === '1'
}
