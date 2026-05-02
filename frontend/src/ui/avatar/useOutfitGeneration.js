/**
 * useOutfitGeneration — hook for generating outfit variations via the
 * /v1/avatars/outfits endpoint.
 *
 * Additive — no existing hooks or API clients are modified.
 */
import { useState, useCallback } from 'react';
// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------
export function useOutfitGeneration(backendUrl, apiKey) {
    const [loading, setLoading] = useState(false);
    const [results, setResults] = useState([]);
    const [warnings, setWarnings] = useState([]);
    const [error, setError] = useState(null);
    const generate = useCallback(async (params) => {
        setLoading(true);
        setError(null);
        setWarnings([]);
        const base = (backendUrl || '').replace(/\/+$/, '');
        const headers = {
            'Content-Type': 'application/json',
        };
        if (apiKey)
            headers['x-api-key'] = apiKey;
        try {
            const res = await fetch(`${base}/v1/avatars/outfits`, {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    reference_image_url: params.referenceImageUrl,
                    outfit_prompt: params.outfitPrompt,
                    character_prompt: params.characterPrompt,
                    negative_prompt: params.negativePrompt,
                    count: params.count ?? 4,
                    seed: params.seed,
                    generation_mode: params.generationMode ?? 'identity',
                    checkpoint_override: params.checkpointOverride,
                }),
            });
            if (!res.ok) {
                const text = await res.text().catch(() => '');
                throw new Error(`Outfit generation failed: ${res.status} ${text}`);
            }
            const data = await res.json();
            setResults(data.results);
            setWarnings(data.warnings || []);
            return data;
        }
        catch (e) {
            const msg = e instanceof Error ? e.message : 'Outfit generation failed';
            setError(msg);
            throw e;
        }
        finally {
            setLoading(false);
        }
    }, [backendUrl, apiKey]);
    const reset = useCallback(() => {
        setResults([]);
        setWarnings([]);
        setError(null);
    }, []);
    return { loading, results, warnings, error, generate, reset };
}
