/**
 * HomePilot edition helper.
 *
 * web   — the hosted Hugging Face Space: a pure *consumer*. It signs into
 *         OllaBridge Cloud and uses the user's linked machines; it does NOT
 *         run a provider sidecar or pretend the Space is the user's GPU.
 * local — installed on the user's PC: a *consumer + provider* that can expose
 *         its own GPU through the OllaBridge Local sidecar.
 *
 * Resolved from the backend `GET /v1/edition` and cached for the session.
 * Defaults to "web" while loading so the UI never shows provider controls it
 * shouldn't (fail safe toward the more restricted role).
 */
import { resolveBackendUrl } from './backendUrl'

export interface EditionInfo {
  edition: 'web' | 'local'
  is_web: boolean
  is_local: boolean
  can_provide_gpu: boolean
  cloud_url: string
}

const FALLBACK: EditionInfo = {
  edition: 'web', is_web: true, is_local: false, can_provide_gpu: false, cloud_url: '',
}

let cache: EditionInfo | null = null
let inflight: Promise<EditionInfo> | null = null

export async function getEdition(): Promise<EditionInfo> {
  if (cache) return cache
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const res = await fetch(`${resolveBackendUrl()}/v1/edition`, { credentials: 'include' })
      if (res.ok) {
        const d = await res.json()
        cache = {
          edition: d.edition === 'local' ? 'local' : 'web',
          is_web: !!d.is_web,
          is_local: !!d.is_local,
          can_provide_gpu: !!d.can_provide_gpu,
          cloud_url: d.cloud_url || '',
        }
        return cache
      }
    } catch {
      /* fall through */
    }
    cache = FALLBACK
    return cache
  })()
  return inflight
}
