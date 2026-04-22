/**
 * useAvatarCapabilities — Additive, non-destructive capability hook.
 *
 * Fetches /v1/avatar-models and derives boolean flags for each optional feature.
 * Components use these flags to show/hide *new* optional buttons without
 * affecting any existing behaviour.
 *
 * Usage:
 *   const { capabilities, loading } = useAvatarCapabilities(backendUrl, apiKey)
 *   // capabilities.canIdentityPortrait → true/false
 *   // capabilities.canOutfits          → true/false
 *   // etc.
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
const EMPTY_CAPABILITIES = {
    canIdentityPortrait: false,
    canOutfits: false,
    canFaceSwap: false,
    canRandomFaces: false,
    hasNonCommercialInstalled: false,
    missingIds: [],
    features: {},
};
// ── Hook ───────────────────────────────────────────────────────────────────
export function useAvatarCapabilities(backendUrl, apiKey) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const base = (backendUrl || '').replace(/\/+$/, '');
    const authKey = (apiKey || '').trim();
    const refresh = useCallback(async () => {
        if (!base)
            return;
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`${base}/v1/avatar-models`, {
                method: 'GET',
                headers: authKey ? { 'x-api-key': authKey } : {},
            });
            if (!res.ok)
                throw new Error(`HTTP ${res.status}`);
            const json = await res.json();
            setData(json);
        }
        catch (e) {
            setError(e?.message || String(e));
            setData(null);
        }
        finally {
            setLoading(false);
        }
    }, [base, authKey]);
    // Fetch once on mount
    useEffect(() => {
        refresh();
    }, [refresh]);
    const capabilities = useMemo(() => {
        if (!data)
            return EMPTY_CAPABILITIES;
        const feats = data.features || {};
        const hasNonCommercialInstalled = (data.available || []).some((m) => m.installed && m.commercial_use_ok === false);
        const missingIds = (data.available || [])
            .filter((m) => !m.installed)
            .map((m) => m.id);
        return {
            canIdentityPortrait: feats.photo_variations?.ready ?? false,
            canOutfits: feats.outfit_generation?.ready ?? false,
            canFaceSwap: feats.face_swap?.ready ?? false,
            canRandomFaces: feats.random_faces?.ready ?? false,
            hasNonCommercialInstalled,
            missingIds,
            features: feats,
        };
    }, [data]);
    return { capabilities, loading, error, refresh };
}
