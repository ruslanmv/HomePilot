/**
 * The Visual Summary tab: the Executive Brief as a light, print-ready report inside the dark
 * frame, with Regenerate, Rewrite brief, PDF, PNG and Present, plus the honest states around
 * it (nothing yet, generating, failed, no transcript, feature off).
 */
import React, { useRef, useState } from 'react';
import { Download, FileImage, Loader2, Play, RefreshCw, Sparkles, ChevronDown, ChevronUp } from 'lucide-react';
import type { LibraryItem } from './api';
import { formatDate, formatDateTime, formatDuration } from './format';
import { findItem, type SuggestedQuestion } from './intelligenceApi';
import { ExecutiveBriefView } from './meeting-summary/ExecutiveBrief';
import { PresentMode } from './PresentMode';
import { downloadBriefPng, printBrief, safeFilename } from './briefExport';
import { useAnalysis } from './useAnalysis';
import { SuggestedQuestions } from './InsightsPanel';

export function VisualSummaryTab({ meetingId, item, hasTranscript, onEvidence, onAsk, onChanged }: {
    meetingId: string;
    item: LibraryItem;
    hasTranscript: boolean;
    onEvidence?: (ms: number, itemId: string) => void;
    onAsk?: (question: string) => void;
    onChanged?: () => void;
}) {
    const a = useAnalysis(meetingId, onChanged);
    const report = useRef<HTMLDivElement>(null);
    const [presenting, setPresenting] = useState(false);
    const [notesOpen, setNotesOpen] = useState(false);
    const [exporting, setExporting] = useState<'png' | null>(null);

    if (a.hidden) {
        return <Shell><p className="text-sm text-white/55">Meeting intelligence is turned off on this server (<code className="text-white/70">MEETINGS_INTELLIGENCE</code>).</p></Shell>;
    }
    if (!a.payload && !a.error) {
        return <Shell><p className="flex items-center gap-2 text-sm text-white/55" aria-busy="true"><Loader2 size={14} className="animate-spin" /> Loading the visual summary…</p></Shell>;
    }

    const payload = a.payload;
    const brief = payload?.visual?.brief;
    const analysis = payload?.analysis;
    const state = payload?.state;
    const job = payload?.job;
    const questions: SuggestedQuestion[] = payload?.questions || [];
    const meta = { date: formatDate(item.started_at || item.scheduled_for), duration: formatDuration(item.duration_ms),
                   project: item.projects[0]?.name, source: item.source.label };

    const exportPng = async () => {
        if (!report.current) return;
        setExporting('png');
        try { await downloadBriefPng(report.current, safeFilename(brief?.title || item.title, 'visual-summary')); } finally { setExporting(null); }
    };
    const firstEvidence = () => {
        if (!analysis || !brief) return;
        const ids = [...brief.risks, ...brief.blockers].map((c) => c.item).concat(brief.decisions.map((r) => r.item), brief.actions.map((s) => s.item));
        for (const id of ids) {
            const it = findItem(analysis, id) as { evidence?: Array<{ t0_ms: number }> } | undefined;
            if (it?.evidence?.[0]) { onEvidence?.(it.evidence[0].t0_ms, id); return; }
        }
    };

    return (
        <Shell>
            <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                    <h2 className="flex items-center gap-2 text-lg font-semibold"><Sparkles size={18} className="text-violet-300" /> Visual meeting summary</h2>
                    <p className="mt-0.5 text-[12.5px] text-white/55">Executive brief generated from the transcript. Every card carries the moment it rests on; wording is verified before it is shown.</p>
                </div>
                {brief && analysis ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <Tool onClick={() => void a.rewrite()} disabled={a.busy || a.pending} title="Write the wording again from the same analysis"><RefreshCw size={13} /> Rewrite brief</Tool>
                        <Tool onClick={() => void a.regenerate()} disabled={a.busy || a.pending} title="Analyse the transcript again"><Sparkles size={13} /> Regenerate</Tool>
                        <Tool onClick={() => report.current && printBrief(report.current)}><Download size={13} /> PDF</Tool>
                        <Tool onClick={() => void exportPng()} disabled={exporting === 'png'}>{exporting === 'png' ? <Loader2 size={13} className="animate-spin" /> : <FileImage size={13} />} PNG</Tool>
                        <button type="button" onClick={() => setPresenting(true)}
                            className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-gradient-to-r from-fuchsia-600 to-violet-600 px-3.5 text-sm font-semibold shadow-lg shadow-fuchsia-900/30 hover:from-fuchsia-500 hover:to-violet-500">
                            <Play size={13} /> Present
                        </button>
                    </div>
                ) : null}
            </div>

            {a.error ? <p className="mt-3 rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert">{a.error}</p> : null}

            {!brief && state === 'no_transcript' ? <Empty>The visual summary is written once there is a transcript.</Empty> : null}
            {!brief && (state === 'none' || state === 'failed') && hasTranscript ? (
                <div className="mt-4 rounded-2xl border border-violet-400/25 bg-gradient-to-br from-violet-600/15 via-fuchsia-600/10 to-transparent p-5" data-testid="visual-cta">
                    <h3 className="font-semibold">Turn this meeting into a one-page executive brief</h3>
                    <p className="mt-1 max-w-2xl text-sm leading-relaxed text-white/65">
                        Risks and blockers, a decision comparison, a next-actions timeline and a core takeaway, laid out for print and presenting. Every claim links to the transcript line it came from.
                        {state === 'failed' && job?.error ? <span className="block pt-1 text-rose-200">Last attempt failed: {job.error}</span> : null}
                    </p>
                    <button type="button" onClick={() => void a.regenerate()} disabled={a.busy}
                        className="mt-3 inline-flex h-10 items-center gap-2 rounded-xl bg-gradient-to-r from-fuchsia-600 to-violet-600 px-4 text-sm font-semibold shadow-lg shadow-fuchsia-900/30 hover:from-fuchsia-500 hover:to-violet-500 disabled:opacity-60">
                        {a.busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />} {state === 'failed' ? 'Try again' : 'Generate visual summary'}
                    </button>
                </div>
            ) : null}
            {a.pending && !brief ? (
                <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.02] p-4" role="status" aria-live="polite" data-testid="visual-progress">
                    <p className="flex items-center gap-2 text-sm"><Loader2 size={15} className="animate-spin text-violet-300" /> Writing the brief — <span className="text-white/70">{job?.stage || 'queued'}</span></p>
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-gradient-to-r from-fuchsia-500 to-violet-500 transition-all" style={{ width: `${Math.max(4, Math.round((job?.progress || 0) * 100))}%` }} /></div>
                </div>
            ) : null}

            {brief && analysis ? (
                <>
                    <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-white/55">
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-0.5">
                            {payload?.degraded ? 'No model · the meeting’s own words' : brief.polished ? `AI-written wording · verified${payload?.model ? ` · ${payload.model}` : ''}` : 'Wording from the transcript'}
                        </span>
                        {payload?.created_at ? <span>Generated {formatDateTime(payload.created_at)}</span> : null}
                        {a.pending ? <span className="inline-flex items-center gap-1 text-violet-200"><Loader2 size={12} className="animate-spin" /> Updating…</span> : null}
                    </div>
                    <div className="mt-3 rounded-2xl border border-white/10 bg-[#131019] p-3 sm:p-4 shadow-[0_14px_55px_rgba(0,0,0,0.35)]">
                        <div ref={report}>
                            <ExecutiveBriefView analysis={analysis} brief={brief} meta={meta} onEvidence={onEvidence} />
                        </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px] text-white/60" data-testid="visual-footer">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden />
                        Grounded in {brief.source_count} referenced transcript moment{brief.source_count === 1 ? '' : 's'}
                        <span className="text-white/25">·</span>
                        <button type="button" onClick={firstEvidence} className="text-violet-300 underline-offset-2 hover:underline">View source evidence →</button>
                        {brief.notes.length || payload?.report?.dropped ? (
                            <button type="button" onClick={() => setNotesOpen((o) => !o)} className="ml-auto inline-flex items-center gap-1 text-white/50 hover:text-white/80">
                                {notesOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />} What was checked
                            </button>
                        ) : null}
                    </div>
                    {notesOpen ? (
                        <ul className="mt-2 space-y-1 rounded-xl border border-white/10 bg-white/[0.02] p-3 text-xs text-white/60">
                            {payload?.report ? <li>{payload.report.kept} items verified against the transcript{payload.report.dropped ? `, ${payload.report.dropped} dropped because the quoted words were not found` : ''}.</li> : null}
                            {brief.notes.map((n, i) => <li key={i}>{n}</li>)}
                        </ul>
                    ) : null}
                    {questions.length ? <div className="mt-5"><SuggestedQuestions questions={questions} onAsk={onAsk} /></div> : null}
                </>
            ) : null}

            {presenting && brief && analysis ? (
                <PresentMode analysis={analysis} brief={brief} title={brief.title || item.title} onClose={() => setPresenting(false)}
                    onEvidence={onEvidence ? (ms, id) => { setPresenting(false); onEvidence(ms, id); } : undefined} />
            ) : null}
        </Shell>
    );
}

function Shell({ children }: { children: React.ReactNode }) {
    return <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 sm:p-5" aria-label="Visual summary" data-testid="visual-summary-tab">{children}</section>;
}

function Empty({ children }: { children: React.ReactNode }) {
    return <p className="mt-4 rounded-xl border border-white/10 bg-white/[0.02] p-4 text-sm text-white/55">{children}</p>;
}

function Tool({ children, onClick, disabled, title }: { children: React.ReactNode; onClick: () => void; disabled?: boolean; title?: string }) {
    return (
        <button type="button" onClick={onClick} disabled={disabled} title={title}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-white/85 hover:bg-white/[0.08] disabled:opacity-50">
            {children}
        </button>
    );
}

export default VisualSummaryTab;
