/**
 * Processing — what is being transcribed, indexed and summarised, with progress, and the
 * reason when something is waiting (no local speech model) or failed.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Loader2, RotateCcw, X } from 'lucide-react';
import { LibraryError, libraryApi, type LibraryJob } from './api';

const TYPE_LABEL: Record<string, string> = { transcribe: 'Transcription', index: 'Search index', summarize: 'Summary' };

export function ProcessingPanel({ onChanged, meetingId }: { onChanged?: () => void; meetingId?: string }) {
    const [jobs, setJobs] = useState<LibraryJob[]>([]);
    const [stt, setStt] = useState<{ available: boolean; hint?: string | null } | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const body = await libraryApi.jobs({ active: !meetingId, meeting_id: meetingId });
            setJobs(body.jobs);
            setStt(body.stt);
            setError(null);
        } catch (e) {
            setError(e instanceof LibraryError ? e.message : 'Processing status is unavailable.');
        }
    }, [meetingId]);

    useEffect(() => {
        void load();
        const t = setInterval(() => void load(), 3000);
        return () => clearInterval(t);
    }, [load]);

    const act = async (fn: () => Promise<unknown>) => {
        try { await fn(); } catch (e) { setError(e instanceof LibraryError ? e.message : 'That did not work.'); }
        await load();
        onChanged?.();
    };

    const waitingForSetup = jobs.some((j) => j.state === 'needs_setup');

    return (
        <section className="mb-5 rounded-2xl border border-white/10 bg-white/[0.02] p-4" aria-label="Processing" data-testid="processing-panel">
            <h2 className="text-sm font-semibold">Processing</h2>
            {waitingForSetup && stt && !stt.available ? (
                <p className="mt-2 flex gap-2 rounded-xl border border-amber-400/30 bg-amber-500/10 p-3 text-sm text-amber-100">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                    <span>Recordings are stored and waiting: no local speech-to-text model is installed. {stt.hint || ''} Then press Retry.</span>
                </p>
            ) : null}
            {error ? <p className="mt-2 text-sm text-rose-200">{error}</p> : null}
            {jobs.length === 0 ? (
                <p className="mt-2 text-sm text-white/50">Nothing is being processed.</p>
            ) : (
                <ul className="mt-3 space-y-2">
                    {jobs.map((job) => (
                        <li key={job.id} className="rounded-xl border border-white/[0.08] bg-black/40 p-3">
                            <div className="flex flex-wrap items-center gap-2 text-sm">
                                <span className="font-medium">{TYPE_LABEL[job.type] || job.type}</span>
                                <span className="truncate text-white/50">· {job.meeting_title || 'Meeting'}</span>
                                <span className="ml-auto text-xs text-white/50">{stateLabel(job)}</span>
                                {job.state === 'queued' || job.state === 'running' ? (
                                    <button type="button" onClick={() => void act(() => libraryApi.cancelJob(job.id))} aria-label="Cancel"
                                        className="grid h-7 w-7 place-items-center rounded-lg text-white/50 hover:bg-white/10 hover:text-white"><X size={14} /></button>
                                ) : (
                                    <button type="button" onClick={() => void act(() => libraryApi.retryJob(job.id))}
                                        className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs hover:bg-white/10"><RotateCcw size={12} /> Retry</button>
                                )}
                            </div>
                            {job.state === 'running' || job.state === 'queued' ? (
                                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10" role="progressbar"
                                    aria-valuenow={Math.round((job.progress || 0) * 100)} aria-valuemin={0} aria-valuemax={100}>
                                    <div className="h-full bg-sky-400 transition-[width] duration-500" style={{ width: `${Math.max(3, Math.round((job.progress || 0) * 100))}%` }} />
                                </div>
                            ) : null}
                            {job.error && job.state !== 'running' ? <p className="mt-1 text-xs text-amber-200/90">{job.error}</p> : null}
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}

function stateLabel(job: LibraryJob): React.ReactNode {
    switch (job.state) {
        case 'running':
            return <span className="inline-flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> {job.stage || 'Working'} · {Math.round((job.progress || 0) * 100)}%</span>;
        case 'queued':
            return 'Queued';
        case 'needs_setup':
            return 'Needs speech-to-text setup';
        case 'failed':
            return 'Failed';
        case 'cancelled':
            return 'Cancelled';
        default:
            return 'Done';
    }
}

export default ProcessingPanel;
