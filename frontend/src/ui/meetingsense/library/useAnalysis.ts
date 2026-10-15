/**
 * The meeting's analysis, shared by the Overview card and the Visual Summary tab: one load,
 * polling while a job runs, hidden when the server has the feature off (404), and the two
 * actions that start work (regenerate the analysis, rewrite the brief).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { LibraryError } from './api';
import { intelligenceApi, isNotEnabled, type AnalysisPayload } from './intelligenceApi';

export interface AnalysisHandle {
    payload: AnalysisPayload | null;
    hidden: boolean;
    error: string | null;
    busy: boolean;
    pending: boolean;
    ready: boolean;
    reload: () => Promise<void>;
    regenerate: () => Promise<void>;
    rewrite: () => Promise<void>;
}

export function useAnalysis(meetingId: string, onSettled?: () => void): AnalysisHandle {
    const [payload, setPayload] = useState<AnalysisPayload | null>(null);
    const [hidden, setHidden] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const alive = useRef(true);

    const reload = useCallback(async () => {
        try {
            const body = await intelligenceApi.analysis(meetingId);
            if (!alive.current) return;
            setPayload(body);
            setError(null);
        } catch (e) {
            if (!alive.current) return;
            if (isNotEnabled(e)) { setHidden(true); return; }
            setError(e instanceof LibraryError ? e.message : 'Insights could not be loaded.');
        }
    }, [meetingId]);

    useEffect(() => { alive.current = true; void reload(); return () => { alive.current = false; }; }, [reload]);

    const pending = payload?.state === 'pending';
    useEffect(() => {
        if (!pending) return undefined;
        const t = setInterval(() => void reload(), 3000);
        return () => clearInterval(t);
    }, [pending, reload]);

    const wasPending = useRef(false);
    useEffect(() => {
        if (wasPending.current && !pending) onSettled?.();
        wasPending.current = pending;
    }, [pending, onSettled]);

    const run = async (fn: () => Promise<unknown>, fallback: string) => {
        setBusy(true);
        setError(null);
        try {
            await fn();
            await reload();
        } catch (e) {
            setError(e instanceof LibraryError ? `${e.message}${e.hint ? ` ${e.hint}` : ''}` : fallback);
        } finally {
            setBusy(false);
        }
    };

    return {
        payload, hidden, error, busy, pending,
        ready: !!(payload?.analysis && payload?.visual),
        reload,
        regenerate: () => run(() => intelligenceApi.run(meetingId), 'The analysis could not be started.'),
        rewrite: () => run(() => intelligenceApi.relayout(meetingId), 'The brief could not be rewritten.'),
    };
}
