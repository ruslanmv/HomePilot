/**
 * The one-page visual summary: a `VisualSpec` drawn from a `MeetingAnalysis`.
 *
 * Every word on this page is copied from the analysis — titles, statements, quotes — and
 * every card carries the timestamp of the transcript line it rests on, which plays the
 * recording from there. Nothing is generated here; this file only arranges.
 *
 * Designed to lift into a shared package later (DayPilot will render the same spec): no
 * HomePilot imports beyond the shared tone classes, no data fetching, no app state.
 */
import React from 'react';
import { AlertTriangle, CheckCircle2, Circle, HelpCircle, Lightbulb, ListChecks, Play, Quote, ShieldAlert, Sparkles, XCircle } from 'lucide-react';
import {
    findItem, msToClock,
    type ActionItem, type Conclusion, type Decision, type Evidence, type MeetingAnalysis, type OpenQuestion, type Risk, type Topic,
    type VisualBlock, type VisualSpec,
} from '../intelligenceApi';

export interface VisualSummaryProps {
    analysis: MeetingAnalysis;
    spec: VisualSpec;
    /** Play the recording from a transcript line. Without it, timestamps are plain text. */
    onSeek?: (ms: number) => void;
    /** Branded footer line, e.g. the model that wrote it. */
    footer?: React.ReactNode;
}

const STATUS: Record<Decision['status'], { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
    confirmed: { label: 'Confirmed', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/30', Icon: CheckCircle2 },
    proposed: { label: 'Proposed', cls: 'bg-amber-500/15 text-amber-200 border-amber-400/30', Icon: Circle },
    rejected: { label: 'Rejected', cls: 'bg-rose-500/15 text-rose-300 border-rose-400/30', Icon: XCircle },
};

const SEVERITY: Record<Risk['severity'], { label: string; card: string; badge: string }> = {
    high: { label: 'High priority', card: 'border-rose-400/30 bg-rose-500/[0.08]', badge: 'bg-rose-500/20 text-rose-200' },
    medium: { label: 'Needs attention', card: 'border-amber-400/30 bg-amber-500/[0.07]', badge: 'bg-amber-500/20 text-amber-100' },
    low: { label: 'Low', card: 'border-sky-400/25 bg-sky-500/[0.06]', badge: 'bg-sky-500/20 text-sky-100' },
};

export function EvidenceChip({ evidence, onSeek, className = '' }: { evidence: Evidence[] | undefined; onSeek?: (ms: number) => void; className?: string }) {
    const first = evidence?.[0];
    if (!first) return null;
    const label = msToClock(first.t0_ms);
    const title = first.quote ? `“${first.quote}”` : `Said at ${label}`;
    if (!onSeek) return <span className={`inline-flex items-center gap-1 text-xs tabular-nums text-white/45 ${className}`} title={title}>{label}</span>;
    return (
        <button type="button" onClick={() => onSeek(first.t0_ms)} title={title} aria-label={`Play from ${label}`}
            className={`inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-xs tabular-nums text-violet-200 hover:bg-violet-500/20 hover:text-white ${className}`}>
            <Play size={10} className="translate-x-px" /> {label}
        </button>
    );
}

function Header({ block, analysis }: { block: VisualBlock; analysis: MeetingAnalysis }) {
    const degraded = !!(block.meta?.degraded || analysis.degraded);
    return (
        <header>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-violet-300/80"><Sparkles size={13} /> Meeting insights</div>
            <h2 className="mt-1.5 text-xl font-semibold leading-snug text-white sm:text-2xl">{block.title || analysis.title}</h2>
            {block.text ? <p className="mt-2 max-w-3xl text-[15px] leading-relaxed text-white/75">{block.text}</p> : null}
            {degraded ? (
                <p className="mt-3 flex items-start gap-2 rounded-xl border border-amber-400/30 bg-amber-500/[0.08] px-3 py-2 text-sm text-amber-100">
                    <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                    No language model answered, so this page is assembled from the meeting&apos;s own words: each item is a transcript line chosen by cue words, not a written summary.
                </p>
            ) : null}
        </header>
    );
}

function KpiRow({ block }: { block: VisualBlock }) {
    const kpis: Array<{ label: string; value: string | number; sub?: string }> = block.meta?.kpis || [];
    if (!kpis.length) return null;
    return (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-5" data-testid="vs-kpis">
            {kpis.map((k) => (
                <div key={k.label} className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5">
                    <div className="text-xl font-semibold tabular-nums text-white">{k.value}</div>
                    <div className="text-xs text-white/55">{k.label}{k.sub ? <span className="block truncate text-white/40">{k.sub}</span> : null}</div>
                </div>
            ))}
        </div>
    );
}

function RiskCards({ block, analysis, onSeek }: { block: VisualBlock; analysis: MeetingAnalysis; onSeek?: (ms: number) => void }) {
    const risks = block.items.map((id) => findItem(analysis, id) as Risk | undefined).filter(Boolean) as Risk[];
    if (!risks.length) return null;
    return (
        <section aria-label={block.title || 'Risks'}>
            <SectionTitle icon={<ShieldAlert size={16} />}>{block.title || 'Risks and problems'}</SectionTitle>
            <div className="grid gap-3 md:grid-cols-2">
                {risks.map((r) => {
                    const sev = SEVERITY[r.severity] || SEVERITY.medium;
                    return (
                        <article key={r.id} className={`rounded-xl border p-4 ${sev.card}`} data-testid={`vs-risk-${r.id}`}>
                            <div className="flex items-start gap-2">
                                <h4 className="flex-1 font-semibold leading-snug text-white">{r.title}</h4>
                                <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-medium ${sev.badge}`}>{sev.label}</span>
                            </div>
                            {r.detail && r.detail !== r.title ? <p className="mt-2 text-sm leading-relaxed text-white/75">{r.detail}</p> : null}
                            {r.root_cause ? <p className="mt-2 text-sm text-white/65"><span className="font-medium text-white/80">Root cause:</span> {r.root_cause}</p> : null}
                            {r.solutions.length ? (
                                <ul className="mt-2 space-y-1">
                                    {r.solutions.map((s, i) => <li key={i} className="flex gap-2 text-sm text-white/75"><CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-300" /> {s}</li>)}
                                </ul>
                            ) : null}
                            <div className="mt-3"><EvidenceChip evidence={r.evidence} onSeek={onSeek} /></div>
                        </article>
                    );
                })}
            </div>
        </section>
    );
}

function DecisionList({ block, analysis, onSeek }: { block: VisualBlock; analysis: MeetingAnalysis; onSeek?: (ms: number) => void }) {
    const decisions = block.items.map((id) => findItem(analysis, id) as Decision | undefined).filter(Boolean) as Decision[];
    if (!decisions.length) return null;
    return (
        <section aria-label={block.title || 'Decisions'}>
            <SectionTitle icon={<Lightbulb size={16} />}>{block.title || 'Decisions'}</SectionTitle>
            <ol className="space-y-2">
                {decisions.map((d, i) => {
                    const st = STATUS[d.status] || STATUS.proposed;
                    return (
                        <li key={d.id} className="flex items-start gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-3" data-testid={`vs-decision-${d.id}`}>
                            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-violet-600/80 text-xs font-semibold">{i + 1}</span>
                            <div className="min-w-0 flex-1">
                                <p className="text-[15px] leading-relaxed text-white/90">{d.statement}</p>
                                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                                    <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${st.cls}`}><st.Icon size={11} /> {st.label}</span>
                                    <EvidenceChip evidence={d.evidence} onSeek={onSeek} />
                                </div>
                            </div>
                        </li>
                    );
                })}
            </ol>
        </section>
    );
}

function ComparisonTable({ block, onSeek }: { block: VisualBlock; onSeek?: (ms: number) => void }) {
    if (!block.rows.length) return null;
    const statusCol = typeof block.meta?.status_column === 'number' ? block.meta.status_column : -1;
    const timeCol = typeof block.meta?.time_column === 'number' ? block.meta.time_column : -1;
    const stampMs = (v: string) => {
        const m = /(\d{1,2}):(\d{2}):(\d{2})/.exec(v);
        return m ? (Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3])) * 1000 : null;
    };
    return (
        <section aria-label={block.title || 'Table'}>
            {block.title ? <SectionTitle icon={<ListChecks size={16} />}>{block.title}</SectionTitle> : null}
            <div className="overflow-x-auto rounded-xl border border-white/10">
                <table className="w-full text-left text-sm">
                    <thead className="bg-white/[0.04] text-xs uppercase tracking-wide text-white/55">
                        <tr>{block.columns.map((c) => <th key={c} className="px-3 py-2 font-medium">{c}</th>)}</tr>
                    </thead>
                    <tbody>
                        {block.rows.map((row, ri) => (
                            <tr key={ri} className="border-t border-white/[0.06]">
                                {row.map((cell, ci) => {
                                    if (ci === statusCol) {
                                        const key = cell.toLowerCase() as Decision['status'];
                                        const st = STATUS[key];
                                        return <td key={ci} className="px-3 py-2 align-top">{st ? <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${st.cls}`}><st.Icon size={11} /> {st.label}</span> : cell}</td>;
                                    }
                                    if (ci === timeCol) {
                                        const ms = stampMs(cell);
                                        return <td key={ci} className="px-3 py-2 align-top">{ms !== null ? <EvidenceChip evidence={[{ t0_ms: ms, quote: '' }]} onSeek={onSeek} /> : cell}</td>;
                                    }
                                    return <td key={ci} className="px-3 py-2 align-top text-white/85">{cell}</td>;
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </section>
    );
}

function Timeline({ block, analysis, onSeek }: { block: VisualBlock; analysis: MeetingAnalysis; onSeek?: (ms: number) => void }) {
    const steps = block.items.map((id) => findItem(analysis, id) as ActionItem | undefined).filter(Boolean) as ActionItem[];
    if (!steps.length) return null;
    return (
        <section aria-label={block.title || 'Action items'}>
            <SectionTitle icon={<ListChecks size={16} />}>{block.title || 'Action items'}</SectionTitle>
            <ol className="relative grid gap-3 sm:grid-flow-col sm:auto-cols-fr" data-testid="vs-timeline">
                {steps.map((a, i) => (
                    <li key={a.id} className="relative rounded-xl border border-white/10 bg-white/[0.02] p-3 sm:pt-5">
                        <span className="absolute -top-2 left-3 hidden h-4 w-4 rounded-full border-2 border-black bg-violet-400 sm:block" aria-hidden />
                        <div className="text-xs font-semibold uppercase tracking-wide text-violet-200/90">{a.due_text || a.due || `Step ${i + 1}`}</div>
                        <p className={`mt-1 text-sm leading-relaxed ${a.status === 'done' ? 'text-white/45 line-through' : 'text-white/90'}`}>{a.text}</p>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-white/55">
                            {a.owner ? <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5">{a.owner}</span> : <span className="text-white/35">Owner not stated</span>}
                            <EvidenceChip evidence={a.evidence} onSeek={onSeek} />
                        </div>
                    </li>
                ))}
            </ol>
        </section>
    );
}

function ListSection({ block, analysis, onSeek }: { block: VisualBlock; analysis: MeetingAnalysis; onSeek?: (ms: number) => void }) {
    const items = block.items.map((id) => findItem(analysis, id)).filter(Boolean) as Array<OpenQuestion | Topic | Conclusion>;
    if (!items.length) return null;
    const tone = block.tone === 'amber' ? 'border-amber-400/20' : 'border-white/10';
    return (
        <section aria-label={block.title || 'Section'}>
            <SectionTitle icon={block.tone === 'amber' ? <HelpCircle size={16} /> : <ListChecks size={16} />}>{block.title}</SectionTitle>
            <ul className={`space-y-1.5 rounded-xl border ${tone} bg-white/[0.02] p-3`}>
                {items.map((it) => {
                    const topic = it as Topic;
                    const isTopic = typeof topic.label === 'string';
                    return (
                        <li key={it.id} className="flex items-start gap-2 text-sm text-white/85">
                            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-300" aria-hidden />
                            <span className="min-w-0 flex-1">
                                {isTopic ? (
                                    <>
                                        <span className="font-medium text-white">{topic.label}</span>
                                        {topic.summary ? <span className="text-white/65"> — {topic.summary}</span> : null}
                                        <span className="ml-2 text-xs tabular-nums text-white/40">{msToClock(topic.t0_ms)}–{msToClock(topic.t1_ms)}</span>
                                    </>
                                ) : (
                                    <>
                                        {(it as OpenQuestion).text}
                                        {(it as OpenQuestion).owner ? <span className="ml-2 text-xs text-white/45">{(it as OpenQuestion).owner}</span> : null}
                                        <EvidenceChip evidence={(it as OpenQuestion).evidence} onSeek={onSeek} className="ml-2" />
                                    </>
                                )}
                            </span>
                        </li>
                    );
                })}
            </ul>
        </section>
    );
}

function Callout({ block, analysis, onSeek }: { block: VisualBlock; analysis: MeetingAnalysis; onSeek?: (ms: number) => void }) {
    if (!block.text) return null;
    const item = block.items[0] ? (findItem(analysis, block.items[0]) as Conclusion | undefined) : undefined;
    return (
        <aside className="rounded-xl border border-violet-400/30 bg-violet-500/[0.1] p-4" data-testid="vs-callout">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-violet-200"><Sparkles size={13} /> {block.title || 'Key conclusion'}</div>
            <p className="mt-1.5 text-[15px] leading-relaxed text-white">{block.text}</p>
            {item?.evidence?.length ? <div className="mt-2"><EvidenceChip evidence={item.evidence} onSeek={onSeek} /></div> : null}
        </aside>
    );
}

function QuoteBlock({ block }: { block: VisualBlock }) {
    if (!block.text) return null;
    return <blockquote className="flex gap-3 rounded-xl border border-white/10 p-4 text-[15px] italic text-white/80"><Quote size={16} className="shrink-0 text-violet-300" /> {block.text}</blockquote>;
}

function SectionTitle({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
    return <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-white/70"><span className="text-violet-300">{icon}</span>{children}</h3>;
}

export function VisualSummary({ analysis, spec, onSeek, footer }: VisualSummaryProps) {
    return (
        <div className="space-y-5 rounded-2xl border border-white/10 bg-gradient-to-b from-white/[0.04] to-transparent p-4 sm:p-6" data-testid="visual-summary">
            {spec.blocks.map((block, i) => {
                switch (block.type) {
                    case 'header': return <Header key={i} block={block} analysis={analysis} />;
                    case 'kpi_row': return <KpiRow key={i} block={block} />;
                    case 'risk_cards': return <RiskCards key={i} block={block} analysis={analysis} onSeek={onSeek} />;
                    case 'decision_list': return <DecisionList key={i} block={block} analysis={analysis} onSeek={onSeek} />;
                    case 'comparison_table': return <ComparisonTable key={i} block={block} onSeek={onSeek} />;
                    case 'timeline': return <Timeline key={i} block={block} analysis={analysis} onSeek={onSeek} />;
                    case 'section': return <ListSection key={i} block={block} analysis={analysis} onSeek={onSeek} />;
                    case 'callout': return <Callout key={i} block={block} analysis={analysis} onSeek={onSeek} />;
                    case 'quote': return <QuoteBlock key={i} block={block} />;
                    default: return null;
                }
            })}
            {footer ? <footer className="border-t border-white/[0.06] pt-3 text-xs text-white/45">{footer}</footer> : null}
        </div>
    );
}

export default VisualSummary;
