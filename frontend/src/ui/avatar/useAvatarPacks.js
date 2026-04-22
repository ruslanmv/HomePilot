/**
 * Hook: loads avatar pack availability from the backend.
 */
import { useEffect, useState, useCallback } from 'react';
import { fetchAvatarPacks } from './avatarApi';
export function useAvatarPacks(backendUrl, apiKey) {
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);
    const refresh = useCallback(async () => {
        if (!backendUrl)
            return;
        setLoading(true);
        setError(null);
        try {
            const result = await fetchAvatarPacks(backendUrl, apiKey);
            setData(result);
        }
        catch (e) {
            setError(e?.message || String(e));
        }
        finally {
            setLoading(false);
        }
    }, [backendUrl, apiKey]);
    useEffect(() => {
        refresh();
    }, [refresh]);
    return { data, error, loading, refresh };
}
