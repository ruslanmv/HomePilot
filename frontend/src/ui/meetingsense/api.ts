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


export interface MeetingModelTarget {
    provider: string;
    model: string;
    baseUrl: string;
}

/** The app's current chat target — the same settings ordinary conversation uses. */
export function readMeetingModelTarget(): MeetingModelTarget {
    const get = (key: string): string => {
        try { return (window.localStorage.getItem(key) || '').trim(); } catch { return ''; }
    };
    return {
        provider: get('homepilot_provider_chat') || 'ollama',
        model: get('homepilot_model_chat') || get('homepilot_ollama_model'),
        baseUrl: get('homepilot_base_url_chat') || get('homepilot_ollama_url'),
    };
}

function modelId(value: unknown): string {
    if (typeof value === 'string') return value.trim();
    if (value && typeof value === 'object') {
        const row = value as Record<string, unknown>;
        for (const key of ['id', 'name', 'model']) {
            if (typeof row[key] === 'string' && row[key]) return String(row[key]).trim();
        }
    }
    return '';
}

/**
 * Models already reachable through HomePilot's selected chat provider.
 * Failure returns the currently selected model rather than turning meeting setup into an error.
 */
export async function fetchMeetingModels(
    target: MeetingModelTarget,
    fetcher: typeof fetch = fetch,
): Promise<string[]> {
    const params = new URLSearchParams({ provider: target.provider || 'ollama' });
    if (target.baseUrl) params.set('base_url', target.baseUrl);
    try {
        const response = await fetcher(`${backendBase()}/models?${params.toString()}`, {
            credentials: 'include',
            headers: requestHeaders(),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        const rows: string[] = Array.isArray(body?.models)
            ? (body.models as unknown[]).map(modelId).filter((id): id is string => Boolean(id))
            : [];
        if (target.model && !rows.includes(target.model)) rows.unshift(target.model);
        return [...new Set(rows)];
    } catch {
        return target.model ? [target.model] : [];
    }
}
