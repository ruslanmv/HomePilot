// MB0 — link the app to a compute backend (OllaBridge Cloud by default) without
// pasting raw config. The credential is the user's Cloud access token (a JWT or
// an `ob_` API key, mintable in the Cloud's API-Keys tab); the shared client
// sends it as `Authorization: Bearer`. Structured so a QR scan can drop in later
// (a QR simply yields { baseUrl, token } and calls linkWithToken).
import { DEFAULT_CLOUD_URL, getBaseUrl, setBaseUrl } from './client';
import { secureTokenStorage, setStoredBaseUrl } from './storage';

export interface ConnectResult {
  reachable: boolean;
  /** true = token accepted · false = rejected · null = couldn't verify */
  authed: boolean | null;
  detail: string;
}

function normalize(url: string): string {
  return url.trim().replace(/\/+$/, '');
}

/** Persist + activate a credential. Takes effect immediately (client is built
 *  per call). Pass an empty token to clear it. */
export async function linkWithToken(token: string, baseUrl: string = DEFAULT_CLOUD_URL): Promise<void> {
  const base = normalize(baseUrl);
  await secureTokenStorage.set(token.trim() || null);
  await setStoredBaseUrl(base);
  setBaseUrl(base);
}

/** Best-effort connection test: reachability (unauthenticated `/health`) plus,
 *  when the jobs API is enabled, whether the token authenticates. Never throws. */
export async function testConnection(
  baseUrl: string = getBaseUrl(),
  token?: string,
): Promise<ConnectResult> {
  const base = normalize(baseUrl);

  try {
    const h = await fetch(`${base}/health`, { method: 'GET' });
    if (!h.ok) return { reachable: false, authed: null, detail: `Server returned ${h.status}` };
  } catch {
    return { reachable: false, authed: null, detail: 'Cannot reach the server' };
  }

  const t = (token ?? (await secureTokenStorage.get()) ?? '').trim();
  if (!t) return { reachable: true, authed: null, detail: 'Reachable — add an access token' };

  try {
    const r = await fetch(`${base}/v1/jobs`, {
      headers: { Authorization: `Bearer ${t}`, 'X-API-Key': t },
    });
    if (r.status === 401 || r.status === 403) {
      return { reachable: true, authed: false, detail: 'Token rejected — check your access token' };
    }
    if (r.status === 404) {
      return { reachable: true, authed: null, detail: 'Connected (token not verified — jobs API off)' };
    }
    return { reachable: true, authed: true, detail: 'Connected' };
  } catch {
    return { reachable: true, authed: null, detail: 'Connected (token not verified)' };
  }
}
