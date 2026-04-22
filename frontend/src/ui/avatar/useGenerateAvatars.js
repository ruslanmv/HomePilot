/**
 * Hook: manage avatar generation state (loading, results, errors).
 *
 * Includes a 5-minute AbortController timeout so the frontend never
 * hangs indefinitely waiting for the backend.
 */
import { useState, useCallback, useRef } from 'react';
import { generateAvatars } from './avatarApi';
/** Frontend-side timeout for a single generation request (5 min). */
const GENERATE_TIMEOUT_MS = 5 * 60 * 1000;
export function useGenerateAvatars(backendUrl, apiKey) {
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const abortRef = useRef(null);
    const run = useCallback(async (req) => {
        // Abort any in-flight request
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        const timer = setTimeout(() => controller.abort(), GENERATE_TIMEOUT_MS);
        setLoading(true);
        setError(null);
        try {
            const r = await generateAvatars(backendUrl, req, apiKey, controller.signal);
            setResult(r);
            return r;
        }
        catch (e) {
            if (e?.name === 'AbortError') {
                const msg = 'Generation timed out. Try reducing the count or switching models.';
                setError(msg);
                throw new Error(msg);
            }
            setError(e?.message || String(e));
            throw e;
        }
        finally {
            clearTimeout(timer);
            setLoading(false);
            if (abortRef.current === controller) {
                abortRef.current = null;
            }
        }
    }, [backendUrl, apiKey]);
    const cancel = useCallback(() => {
        abortRef.current?.abort();
        abortRef.current = null;
        setLoading(false);
    }, []);
    const reset = useCallback(() => {
        setResult(null);
        setError(null);
    }, []);
    /** Remove a single result by index (e.g. delete a face the user doesn't like). */
    const removeResult = useCallback((index) => {
        setResult((prev) => {
            if (!prev?.results)
                return prev;
            const next = prev.results.filter((_, i) => i !== index);
            if (next.length === 0)
                return null;
            return { ...prev, results: next };
        });
    }, []);
    return { loading, result, error, run, reset, cancel, removeResult };
}
