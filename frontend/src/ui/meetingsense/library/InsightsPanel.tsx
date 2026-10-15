/**
 * Meeting insights on the Overview tab — a compact card: what the analysis found, in numbers,
 * the verification line, suggested questions, and the way into the Visual Summary tab, where
 * the full executive brief lives. Without `onOpenVisual` (no tab to go to) it shows the whole
 * dark visual page here instead.
 *
 * Hidden entirely when the feature is off on the server (the analysis route answers 404), so
 * an install without `MEETINGS_INTELLIGENCE` sees the page exactly as before.
 */
import React from 'react';
import { ArrowRight, Bot, Download, HelpCircle, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { formatDateTime } from './format';
import { analysisToMarkdown, type ExecutiveBrief, type MeetingAnalysis, type SuggestedQuestion, type ValidatorReport } from './intelligenceApi';
import { VisualSummary } from './meeting-summary/VisualSummary';
import { useAnalysis } from './useAnalysis';

export function InsightsPanel({ meetingId, hasTranscript, title, onSeek, onAsk, onChanged, onOpenVisual }: {
    meetingId: string;
    hasTranscript: boolean;
    title?: string;
    onSeek?: (ms: number) => void;
    onAsk?: (question: string) => void;
    onChanged?: () => void;
    /** Open the Visual Summary tab; when given, the Overview shows the compact card. */
    onOpenVisual?: () => void;
}) {
    const a = useAnalysis(meetingId, onChanged);
    const payload = a.payload;

    const download = () => {
        if (!payload?.analysis) return;
        const blob = new Blob([analysisToMarkdown(payload.analysis)], { type: 'text/markdown;charset=utf-8' });
        const href = URL.createObjectURL(blob);
        const el = document.createElement('a');
        el.href = href;
        el.download = `${(payload.analysis.title || title || 'meeting').replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '-').toLowerCase() || 'meeting'}-insights.md`;
        document.body.appendChild(el);
        el.click();
        el.remove();
        setTimeout(() => URL.revokeObjectURL(href), 1000);
    };

    if (a.hidden) return null;
    if (!payload && !a.error) {
        return <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.02] p-4 text-sm text-white/55" aria-busy="true"><Loader2 size={14} className="animate-spin" /> Loading insights…</div>;
    }

    const state = payload?.state;
    const ready = a.ready;
    const job = payload?.job;

    return (
        <section className="space-y-3" aria-label="Meeting insights" data-testid="insights-panel">
            {a.error ? <p className="rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert">{a.error}</p> : null}

            {!ready && state === 'no_transcript' ? (
                <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 text-sm text-white/55">Insights are written once there is a transcript.</div>
            ) : null}

            {!ready && (state === 'none' || state === 'failed') && hasTranscript ? (
                <div className="rounded-2xl border border-violet-400/25 bg-gradient-to-br from-violet-600/15 via-fuchsia-600/10 to-transparent p-5" data-testid="insights-cta">
                    <div className="flex items-start gap-3">
                        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-violet-500/20 text-violet-200"><Sparkles size={18} /></span>
                        <div className="min-w-0 flex-1">
                            <h3 className="font-semibold">Turn this meeting into a one-page summary</h3>
                            <p className="mt-1 text-sm leading-relaxed text-white/65">
                                Decisions, risks, action items and open questions, each linked to the exact line it came from, plus questions you can ask the assistant.
                                {state === 'failed' && job?.error ? <span className="block pt-1 text-rose-200">Last attempt failed: {job.error}</span> : null}
                            </p>
                            <button type="button" onClick={() => void a.regenerate()} disabled={a.busy}
                                className="mt-3 inline-flex h-10 items-center gap-2 rounded-xl bg-gradient-to-r from-fuchsia-600 to-violet-600 px-4 text-sm font-semibold shadow-lg shadow-fuchsia-900/30 hover:from-fuchsia-500 hover:to-violet-500 disabled:opacity-60">
                                {a.busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />} {state === 'failed' ? 'Try again' : 'Generate insights'}
                            </button>
                        </div>
                    </div>
                </div>
            ) : null}

            {a.pending && !ready ? <Progress stage={job?.stage || 'queued'} progress={job?.progress || 0} /> : null}

            {ready && payload?.analysis && payload.visual ? (
                <>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-white/55">
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-0.5">
                            {payload.degraded ? 'No model · extractive' : payload.model ? `Model · ${payload.model}` : 'Written by the configured model'}
                        </span>
                        {payload.created_at ? <span>Generated {formatDateTime(payload.created_at)}</span> : null}
                        {payload.versions && payload.versions > 1 ? <span>· version {payload.versions}</span> : null}
                        {a.pending ? <span className="inline-flex items-center gap-1 text-violet-200"><Loader2 size={12} className="animate-spin" /> Updating…</span> : null}
                        <div className="ml-auto flex items-center gap-2">
                            <button type="button" onClick={download} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 text-xs text-white/80 hover:bg-white/10"><Download size={13} /> Download .md</button>
                            <button type="button" onClick={() => void a.regenerate()} disabled={a.busy || a.pending} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 text-xs text-white/80 hover:bg-white/10 disabled:opacity-50"><RefreshCw size={13} /> Regenerate</button>
                        </div>
                    </div>
                    {onOpenVisual ? (
                        <CompactBrief analysis={payload.analysis} brief={payload.visual.brief} report={payload.report} onOpen={onOpenVisual} />
                    ) : (
                        <VisualSummary analysis={payload.analysis} spec={payload.visual} onSeek={onSeek} footer={<ValidatorLine report={payload.report} />} />
                    )}
                    {payload.questions?.length ? <SuggestedQuestions questions={payload.questions} onAsk={onAsk} /> : null}
                </>
            ) : null}
        </section>
    );
}

/** The analysis at a glance, and the door to the full brief. Counts only; no text is written here. */
function CompactBrief({ analysis, brief, report, onOpen }: { analysis: MeetingAnalysis; brief?: ExecutiveBrief | null; report?: ValidatorReport | null; onOpen: () => void }) {
    const counts = [
        { label: 'decisions', n: analysis.decisions.length },
        { label: 'risks', n: analysis.risks.length },
        { label: 'actions', n: analysis.action_items.length },
        { label: 'open questions', n: analysis.open_questions.length },
    ].filter((c) => c.n > 0);
    const headline = brief?.title || analysis.title;
    const line = brief?.intro || analysis.one_line;
    return (
        <div className="rounded-2xl border border-violet-400/25 bg-gradient-to-br from-violet-600/15 via-fuchsia-600/10 to-transparent p-4 sm:p-5" data-testid="insights-compact">
            <div className="flex flex-wrap items-start gap-4">
                <div className="min-w-0 flex-1">
                    <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-violet-200/80">{brief?.eyebrow || 'Executive brief'}</div>
                    <h3 className="mt-1 text-base font-semibold leading-snug">{headline}</h3>
                    {line ? <p className="mt-1 text-sm leading-relaxed text-white/70">{line}</p> : null}
                    {counts.length ? (
                        <ul className="mt-3 flex flex-wrap gap-2 text-xs">
                            {counts.map((c) => (
                                <li key={c.label} className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-0.5 text-white/80"><strong className="font-semibold text-white">{c.n}</strong> {c.label}</li>
                            ))}
                        </ul>
                    ) : null}
                </div>
                <button type="button" onClick={onOpen}
                    className="inline-flex h-10 items-center gap-2 self-center rounded-xl bg-gradient-to-r from-fuchsia-600 to-violet-600 px-4 text-sm font-semibold shadow-lg shadow-fuchsia-900/30 hover:from-fuchsia-500 hover:to-violet-500">
                    Open visual summary <ArrowRight size={15} aria-hidden />
                </button>
            </div>
            {brief?.takeaway ? <p className="mt-3 border-t border-white/10 pt-3 text-sm text-white/75"><span className="text-fuchsia-300" aria-hidden>✦ </span>{brief.takeaway}</p> : null}
            <p className="mt-3 text-xs text-white/45"><ValidatorLine report={report} /></p>
        </div>
    );
}

function Progress({ stage, progress }: { stage: string; progress: number }) {
    const pct = Math.max(4, Math.min(100, Math.round(progress * 100)));
    return (
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4" role="status" aria-live="polite" data-testid="insights-progress">
            <div className="flex items-center gap-2 text-sm"><Loader2 size={15} className="animate-spin text-violet-300" /> Writing the insights — <span className="text-white/70">{stage}</span></div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-gradient-to-r from-fuchsia-500 to-violet-500 transition-all" style={{ width: `${pct}%` }} /></div>
            <p className="mt-2 text-xs text-white/45">Runs on this computer. You can keep reading the transcript meanwhile.</p>
        </div>
    );
}

function ValidatorLine({ report }: { report?: ValidatorReport | null }) {
    if (!report) return <span>Every item links to the transcript line it came from.</span>;
    return (
        <span title={report.notes?.join('\n') || undefined}>
            {report.kept} item{report.kept === 1 ? '' : 's'} verified against the transcript
            {report.dropped ? ` · ${report.dropped} dropped because the quoted words were not found` : ''}
            {report.repaired ? ` · ${report.repaired} re-anchored to the right line` : ''}.
        </span>
    );
}

export function SuggestedQuestions({ questions, onAsk }: { questions: SuggestedQuestion[]; onAsk?: (q: string) => void }) {
    return (
        <div data-testid="suggested-questions">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-white/70"><HelpCircle size={15} className="text-violet-300" /> Ask about this meeting</h3>
            <div className="grid gap-2 sm:grid-cols-3">
                {questions.slice(0, 3).map((q, i) => (
                    <button key={q.id} type="button" onClick={() => onAsk?.(q.text)} disabled={!onAsk}
                        className="group flex items-start gap-2 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-left text-sm text-white/80 transition-colors hover:border-violet-400/40 hover:bg-violet-500/10 disabled:cursor-default">
                        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-white/10 text-[11px] font-semibold text-white/70 group-hover:bg-violet-500/30">{i + 1}</span>
                        <span className="min-w-0 flex-1 leading-snug">{q.text}</span>
                        <Bot size={14} className="mt-0.5 shrink-0 text-white/30 group-hover:text-violet-200" aria-hidden />
                    </button>
                ))}
            </div>
        </div>
    );
}

export default InsightsPanel;
