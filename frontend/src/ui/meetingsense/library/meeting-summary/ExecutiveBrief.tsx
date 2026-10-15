/**
 * The Executive Brief as a printable, light "paper" report inside HomePilot's dark shell:
 * numbered sections, coloured risk and blocker cards, a decision table with status pills, a
 * next-actions timeline and a highlighted takeaway — the structure of the reference design.
 *
 * Everything shown comes from the `ExecutiveBrief` the server composed and validated. The
 * renderer never writes text: it arranges, numbers the sections that have content, hides the
 * ones that do not, and puts a transcript stamp on every card so a claim can be checked.
 *
 * Kept free of app state so the same component can print, export to PNG, play as slides, and
 * later ship as a package for DayPilot.
 */
import React from 'react';
import { findItem, msToClock, type BriefCard, type BriefRow, type BriefStep, type ExecutiveBrief, type MeetingAnalysis, type OpenQuestion } from '../intelligenceApi';

export interface BriefMeta { date?: string; duration?: string; project?: string; source?: string }

export interface ExecutiveBriefProps {
    analysis: MeetingAnalysis;
    brief: ExecutiveBrief;
    meta?: BriefMeta;
    /** Jump to the transcript line behind an item (and play from it when there is audio). */
    onEvidence?: (ms: number, itemId: string) => void;
    /** Which sections to draw; defaults to all. Present mode renders one at a time. */
    only?: BriefSection[];
    compact?: boolean;
    className?: string;
}

export type BriefSection = 'header' | 'risks' | 'decisions' | 'actions' | 'questions' | 'takeaway' | 'footer';

const SEVERITY = {
    high: { card: 'border-pink-200 bg-pink-50', head: 'text-pink-700', badge: 'bg-white text-pink-600 ring-1 ring-pink-200', note: 'bg-pink-100/70 text-pink-900', label: 'HIGH PRIORITY', dot: '●' },
    medium: { card: 'border-amber-200 bg-amber-50', head: 'text-amber-700', badge: 'bg-white text-amber-700 ring-1 ring-amber-200', note: 'bg-amber-100/70 text-amber-900', label: 'NEEDS ATTENTION', dot: '▲' },
    low: { card: 'border-sky-200 bg-sky-50', head: 'text-sky-700', badge: 'bg-white text-sky-700 ring-1 ring-sky-200', note: 'bg-sky-100/70 text-sky-900', label: 'LOW', dot: '○' },
} as const;

const STATUS_PILL: Record<BriefRow['status'], string> = {
    confirmed: 'bg-emerald-100 text-emerald-700',
    proposed: 'bg-amber-100 text-amber-700',
    rejected: 'bg-rose-100 text-rose-700',
};

function Stamp({ analysis, itemId, onEvidence, className = '' }: { analysis: MeetingAnalysis; itemId: string; onEvidence?: (ms: number, itemId: string) => void; className?: string }) {
    const item = findItem(analysis, itemId) as { evidence?: Array<{ t0_ms: number; quote?: string }> } | undefined;
    const first = item?.evidence?.[0];
    if (!first) return null;
    const label = msToClock(first.t0_ms);
    const title = first.quote ? `“${first.quote}”` : `Said at ${label}`;
    const cls = `inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium tabular-nums ${className}`;
    if (!onEvidence) return <span className={`${cls} text-slate-400`} title={title}>{label}</span>;
    return (
        <button type="button" onClick={() => onEvidence(first.t0_ms, itemId)} title={title} aria-label={`View source at ${label}`}
            className={`${cls} border border-slate-200 bg-white text-violet-700 hover:bg-violet-50 print:border-0`}>
            {label} <span aria-hidden>↗</span>
        </button>
    );
}

function Card({ card, analysis, onEvidence, blocker }: { card: BriefCard; analysis: MeetingAnalysis; onEvidence?: ExecutiveBriefProps['onEvidence']; blocker?: boolean }) {
    const sev = SEVERITY[card.severity] || SEVERITY.medium;
    return (
        <article className={`flex min-h-[9rem] flex-col rounded-xl border p-4 ${sev.card}`} data-testid={`brief-card-${card.item}`}>
            <div className={`flex items-start gap-2 text-[13px] font-bold ${sev.head}`}>
                <span aria-hidden className="mt-px">{sev.dot}</span>
                <h4 className="flex-1 leading-snug">{card.title}</h4>
                <span className={`ml-auto shrink-0 rounded-full px-2 py-0.5 text-[9px] font-bold tracking-wide ${sev.badge}`}>{blocker ? 'BLOCKER' : sev.label}</span>
            </div>
            {card.summary ? <p className="mt-2 text-[11.5px] leading-relaxed text-slate-600">{card.summary}</p> : null}
            {card.note ? <p className={`mt-2 rounded-lg px-2.5 py-1.5 text-[10.5px] ${sev.note}`}>{blocker ? '⊗' : '⚠'} {card.note}</p> : null}
            <div className="mt-auto pt-2"><Stamp analysis={analysis} itemId={card.item} onEvidence={onEvidence} /></div>
        </article>
    );
}

export function ExecutiveBriefView({ analysis, brief, meta, onEvidence, only, compact = false, className = '' }: ExecutiveBriefProps) {
    const show = (s: BriefSection) => !only || only.includes(s);
    const cards = [...brief.risks, ...brief.blockers];
    const hasImpact = brief.decisions.some((r) => r.impact);
    const questions = brief.open_questions.map((id) => findItem(analysis, id) as OpenQuestion | undefined).filter(Boolean) as OpenQuestion[];
    const sections: Array<{ key: BriefSection; title: string; present: boolean }> = [
        { key: 'risks', title: brief.blockers.length && brief.risks.length ? 'Core risks & blockers' : brief.blockers.length ? 'Blockers' : 'Core risks', present: cards.length > 0 },
        { key: 'decisions', title: brief.decisions.length > 1 ? 'Decision comparison' : 'Decision', present: brief.decisions.length > 0 },
        { key: 'actions', title: 'Next actions', present: brief.actions.length > 0 },
        { key: 'questions', title: 'Still open', present: questions.length > 0 },
    ];
    const numbered = sections.filter((s) => s.present);
    const number = (key: BriefSection) => `${String(numbered.findIndex((s) => s.key === key) + 1).padStart(2, '0')} /`;
    const label = (key: BriefSection) => {
        const s = sections.find((x) => x.key === key)!;
        return <h3 className="mb-2.5 mt-5 text-[11px] font-bold uppercase tracking-wide text-slate-500 first:mt-0">{number(key)} {s.title}</h3>;
    };

    return (
        <article className={`hp-brief rounded-xl bg-white text-slate-800 shadow-[0_6px_25px_rgba(0,0,0,0.12)] ${compact ? 'p-5' : 'p-6 sm:p-7'} ${className}`}
            data-testid="executive-brief" lang={analysis.language || undefined}>
            {show('header') ? (
                <header className="flex items-start justify-between gap-4 border-b border-slate-200 pb-4">
                    <div className="min-w-0">
                        <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-violet-500">{brief.eyebrow}</div>
                        <h2 className="mt-1 text-xl font-extrabold leading-snug tracking-tight text-slate-900 sm:text-[22px]">{brief.title || analysis.title}</h2>
                        {brief.intro ? <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-slate-600">{brief.intro}</p> : null}
                        {meta && (meta.date || meta.duration || meta.project) ? (
                            <p className="mt-2 text-[10.5px] text-slate-400">{[meta.date, meta.duration, meta.project, meta.source].filter(Boolean).join(' · ')}</p>
                        ) : null}
                    </div>
                    <div className="shrink-0 text-[12px] font-extrabold tracking-tight text-violet-700">✦ HomePilot <span className="text-slate-400">AI</span></div>
                </header>
            ) : null}

            {show('risks') && cards.length ? (
                <section aria-label="Risks and blockers">
                    {label('risks')}
                    <div className={`grid gap-2.5 ${cards.length > 1 ? 'sm:grid-cols-2' : ''}`}>
                        {brief.risks.map((c) => <Card key={c.item} card={c} analysis={analysis} onEvidence={onEvidence} />)}
                        {brief.blockers.map((c) => <Card key={c.item} card={c} analysis={analysis} onEvidence={onEvidence} blocker />)}
                    </div>
                </section>
            ) : null}

            {show('decisions') && brief.decisions.length ? (
                <section aria-label="Decisions">
                    {label('decisions')}
                    <div className="overflow-x-auto rounded-lg border border-slate-200">
                        <table className="w-full border-collapse text-left text-[11px]">
                            <thead className="bg-slate-50 text-[10px] font-bold text-slate-500">
                                <tr>
                                    <th className="px-3 py-2">Option</th>
                                    <th className="px-3 py-2">Status</th>
                                    {hasImpact ? <th className="px-3 py-2">Operational impact</th> : null}
                                    <th className="px-3 py-2 text-right">Source</th>
                                </tr>
                            </thead>
                            <tbody>
                                {brief.decisions.map((row) => (
                                    <tr key={row.item} className="border-t border-slate-100 align-top" data-testid={`brief-row-${row.item}`}>
                                        <td className="px-3 py-2 text-slate-700">{row.option}</td>
                                        <td className="px-3 py-2"><span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[9.5px] font-bold uppercase ${STATUS_PILL[row.status]}`}>{row.status_label}</span></td>
                                        {hasImpact ? <td className="px-3 py-2 text-slate-600">{row.impact}</td> : null}
                                        <td className="px-3 py-2 text-right"><Stamp analysis={analysis} itemId={row.item} onEvidence={onEvidence} /></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </section>
            ) : null}

            {show('actions') && brief.actions.length ? (
                <section aria-label="Next actions">
                    {label('actions')}
                    <ol className={`grid gap-3 pt-3 ${brief.actions.length === 2 ? 'sm:grid-cols-2' : brief.actions.length >= 3 ? 'sm:grid-cols-3' : ''}`}
                        data-testid="brief-timeline">
                        {brief.actions.map((step: BriefStep, i) => (
                            <li key={step.item} className="relative rounded-lg border border-violet-100 bg-violet-50/60 px-3 pb-3 pt-4 text-center">
                                <span className="absolute -top-3 left-1/2 grid h-6 w-6 -translate-x-1/2 place-items-center rounded-full border-[3px] border-white bg-violet-500 text-[10px] font-bold text-white">{i + 1}</span>
                                <h4 className="text-[11px] font-bold text-slate-700">{step.bucket}</h4>
                                {step.label && step.label.toLowerCase() !== step.bucket.toLowerCase() ? (
                                    <div className="mt-0.5 text-[9.5px] font-semibold uppercase tracking-wide text-violet-600">{step.label}</div>
                                ) : null}
                                <p className="mt-1.5 text-[10.5px] leading-relaxed text-slate-600">{step.text}</p>
                                <div className="mt-2 flex items-center justify-center gap-2 text-[10px] text-slate-500">
                                    {step.owner ? <span className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">{step.owner}</span> : null}
                                    <Stamp analysis={analysis} itemId={step.item} onEvidence={onEvidence} />
                                </div>
                            </li>
                        ))}
                    </ol>
                </section>
            ) : null}

            {show('questions') && questions.length ? (
                <section aria-label="Open questions">
                    {label('questions')}
                    <ul className="space-y-1.5 rounded-lg border border-slate-200 p-3">
                        {questions.map((q) => (
                            <li key={q.id} className="flex items-start gap-2 text-[11.5px] text-slate-700">
                                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" aria-hidden />
                                <span className="flex-1">{q.text}{q.owner ? <span className="ml-1.5 text-slate-400">{q.owner}</span> : null}</span>
                                <Stamp analysis={analysis} itemId={q.id} onEvidence={onEvidence} />
                            </li>
                        ))}
                    </ul>
                </section>
            ) : null}

            {show('takeaway') && brief.takeaway ? (
                <aside className="mt-5 flex items-start gap-2.5 rounded-lg bg-fuchsia-50 px-3.5 py-3 text-[11px] leading-relaxed text-fuchsia-900" data-testid="brief-takeaway">
                    <span className="text-[14px] text-fuchsia-500" aria-hidden>✦</span>
                    <span>
                        <strong className="font-bold">Core takeaway</strong> · {brief.takeaway}
                        {brief.takeaway_items.map((id) => <Stamp key={id} analysis={analysis} itemId={id} onEvidence={onEvidence} className="ml-1.5" />)}
                    </span>
                </aside>
            ) : null}

            {show('footer') ? (
                <footer className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-3 text-[9px] text-slate-400">
                    <span>{brief.polished ? 'AI-written wording, verified against the transcript' : 'Wording taken from the transcript'} · Review important decisions against the source</span>
                    <span>Grounded in {brief.source_count} transcript moment{brief.source_count === 1 ? '' : 's'} · HomePilot Meetings Intelligence</span>
                </footer>
            ) : null}
        </article>
    );
}

export default ExecutiveBriefView;
