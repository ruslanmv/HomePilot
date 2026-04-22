/**
 * useAvatarCapabilities — hook for detecting avatar engine availability.
 *
 * Additive: does not modify any existing hook or component.
 * Used by the UI to show/hide StyleGAN-specific controls and status.
 */
import { useState, useCallback, useEffect } from 'react';
import { fetchAvatarCapabilities } from './avatarApi';
export function useAvatarCapabilities(backendUrl, apiKey) {
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);
    const refresh = useCallback(async () => {
        if (!backendUrl)
            return;
        setLoading(true);
        setError(null);
        try {
            const result = await fetchAvatarCapabilities(backendUrl, apiKey);
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
    // Convenience helpers
    const styleganAvailable = data?.engines?.stylegan?.available ?? false;
    const comfyuiAvailable = data?.engines?.comfyui?.available ?? false;
    const quickfaceAvailable = data?.engines?.quickface?.available ?? false;
    return {
        data,
        error,
        loading,
        refresh,
        styleganAvailable,
        comfyuiAvailable,
        quickfaceAvailable,
    };
}
