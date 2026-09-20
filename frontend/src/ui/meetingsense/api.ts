/**
 * How the meeting surfaces reach the backend.
 *
 * Both of these were written out a second time in each component that needed them, and the
 * copies had already drifted — one read `window.localStorage`, the other `localStorage`, and
 * only one of them sent the API key. A third copy for the summary panel would have been the
 * one that forgot the key on an authenticated install, so they live here instead.
 *
 * Every accessor is wrapped: storage throws rather than returning null in a locked-down
 * context, and a meeting must still run against an unauthenticated local backend.
 */

/** The backend origin, with no trailing slash. Empty means same-origin. */
export function backendBase(): string {
    try {
        const saved = window.localStorage.getItem('homepilot_backend_url') || '';
        if (saved.trim()) return saved.replace(/\/+$/, '');
    } catch {
        // Storage can be unavailable in locked-down contexts.
    }
    const fromWindow = (window as typeof window & { HOMEPILOT_API_BASE?: string }).HOMEPILOT_API_BASE || '';
    return fromWindow.replace(/\/+$/, '');
}

/** JSON headers, plus whichever credentials this install has. */
export function requestHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    try {
        const apiKey = window.localStorage.getItem('homepilot_api_key') || '';
        const token = window.localStorage.getItem('homepilot_auth_token') || '';
        if (apiKey) headers['x-api-key'] = apiKey;
        if (token) headers.Authorization = `Bearer ${token}`;
    } catch {
        // A meeting can still run on an unauthenticated local backend.
    }
    return headers;
}
