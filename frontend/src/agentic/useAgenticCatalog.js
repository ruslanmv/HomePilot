/**
 * React hook for fetching and refreshing the agentic catalog.
 *
 * Returns { catalog, loading, error, refresh } so the wizard
 * can render tools, servers, agents and trigger manual refreshes.
 */
import { useCallback, useEffect, useState } from 'react';
export function useAgenticCatalog({ backendUrl, apiKey, enabled = true }) {
    const [catalog, setCatalog] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const fetchCatalog = useCallback(async () => {
        if (!enabled)
            return;
        setLoading(true);
        setError(null);
        try {
            const headers = {};
            if (apiKey)
                headers['x-api-key'] = apiKey;
            // Additive: logged-in user session fallback. The backend's
            // require_api_key now accepts a valid bearer JWT / session
            // cookie as an alternative to the shared API key — see
            // backend/app/auth.py. Send both so either path succeeds.
            try {
                if (typeof window !== 'undefined') {
                    const tok = window.localStorage.getItem('homepilot_auth_token') || '';
                    if (tok)
                        headers['authorization'] = `Bearer ${tok}`;
                }
            }
            catch { /* ignore storage errors */ }
            const res = await fetch(`${backendUrl}/v1/agentic/catalog`, {
                headers,
                credentials: 'include',
            });
            if (!res.ok)
                throw new Error(`HTTP ${res.status}`);
            const data = (await res.json());
            setCatalog(data);
        }
        catch (e) {
            setCatalog(null);
            setError(e?.message || 'Failed to load catalog');
        }
        finally {
            setLoading(false);
        }
    }, [backendUrl, apiKey, enabled]);
    useEffect(() => {
        void fetchCatalog();
    }, [fetchCatalog]);
    return { catalog, loading, error, refresh: fetchCatalog };
}
