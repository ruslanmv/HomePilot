/**
 * The document the meeting was for (batch MS34).
 *
 * `MeetingSummary` above this renders the **rolling notes** — written a window at a time
 * while the meeting ran, held to a card's worth of words however long it went on. That is
 * the right thing to glance at mid-call and the wrong thing to be left with: a three-hour
 * workshop and a nine-minute stand-up both come out as the same four sentences.
 *
 * This is the other one. Written once from the whole transcript, by a map-reduce that is
 * bounded whatever the length of the meeting, in the shape the reader actually needs.
 *
 * ── Why the style picker is on the panel and not in a settings page ──────────────────────
 *
 * "Summarise the meeting" is five different documents. Minutes for the record, a recap email
 * for the people who were not there, personal notes, an executive brief, a bare list of who
 * owes what — and a single summary that tries to be all five is a worse version of each. The
 * choice belongs beside the output because the reader only knows which one they wanted after
 * seeing one.
 *
 * ── Regenerating is safe, and the UI has to make that obvious ────────────────────────────
 *
 * Every generation **appends**. Asking for an email after taking minutes leaves the minutes
 * where they were, and the panel says how many documents there are and lets you move between
 * them. The alternative — one summary slot, overwritten — makes every press of the button a
 * gamble on liking the new one better, and people stop pressing it.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Check, Copy, FileText, Loader2, RefreshCw } from 'lucide-react';
import {
    backendBase,
    fetchMeetingModels,
    readMeetingModelTarget,
    requestHeaders,
    type MeetingModelTarget,
} from './api';
import type { MeetingSummaryDoc } from './meetingRecord';

/** Mirrors `minutes.STYLES` server-side. Held here too so the picker needs no round trip. */
export const SUMMARY_STYLES: Array<{ id: string; label: string; note: string }> = [
    { id: 'minutes', label: 'Minutes', note: 'For the record: discussion, decisions, actions.' },
    { id: 'email', label: 'Recap email', note: 'Sendable to people who were not there.' },
    { id: 'notes', label: 'Notes', note: 'Personal notes, in reading order.' },
    { id: 'brief', label: 'Executive brief', note: 'Outcome first, for a reader with two minutes.' },
    { id: 'actions', label: 'Action list', note: 'Only what is owed, and by whom.' },
];

/** Mirrors `minutes.LENGTHS`. */
export const SUMMARY_LENGTHS: Array<{ id: string; label: string }> = [
    { id: 'short', label: 'Short' },
    { id: 'standard', label: 'Standard' },
    { id: 'detailed', label: 'Detailed' },
];

export function styleLabel(id?: string | null): string {
    return SUMMARY_STYLES.find((style) => style.id === id)?.label || 'Summary';
}

/**
 * Render the document.
 *
 * A deliberately small reader rather than a Markdown library: the server writes headings,
 * bullets and paragraphs, and those three are the whole grammar. Pulling a parser in here to
 * gain tables and footnotes nothing emits would cost every meeting card the bundle.
 *
 * Unrecognised syntax falls through as text, which is the safe direction — a stray `*` shows
 * as a `*` rather than swallowing the line after it.
 */
export function DocumentBody({ text }: { text: string }) {
    const blocks = useMemo(() => {
        const out: Array<{ kind: 'h' | 'li' | 'p'; text: string; key: string }> = [];
        (text || '').split('\n').forEach((raw, index) => {
            const line = raw.trim();
            if (!line) return;
            const heading = /^#{1,6}\s+(.*)$/.exec(line);
            if (heading) {
                out.push({ kind: 'h', text: heading[1], key: `h${index}` });
                return;
            }
            const bullet = /^[-*•]\s+(.*)$/.exec(line);
            if (bullet) {
                out.push({ kind: 'li', text: bullet[1], key: `l${index}` });
                return;
            }
            out.push({ kind: 'p', text: line, key: `p${index}` });
        });
        return out;
    }, [text]);

    return (
        <div className="space-y-2" data-testid="ms-minutes-body">
            {blocks.map((block) => {
                // Bold runs are the one inline form the server emits — the time range that
                // opens every line of the chronological outline.
                const parts = block.text.split(/\*\*(.+?)\*\*/g).map((piece, index) => (
                    index % 2 ? <strong key={index} className="font-semibold text-white/90">{piece}</strong>
                        : <React.Fragment key={index}>{piece}</React.Fragment>
                ));
                if (block.kind === 'h') {
                    return (
                        <h4 key={block.key} className="pt-2 text-xs font-semibold uppercase tracking-wide text-white/55">
                            {parts}
                        </h4>
                    );
                }
                if (block.kind === 'li') {
                    return (
                        <div key={block.key} className="flex gap-2 text-sm leading-6 text-white/80">
                            <span aria-hidden="true" className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-white/30" />
                            <span>{parts}</span>
                        </div>
                    );
                }
                return <p key={block.key} className="text-sm leading-6 text-white/80">{parts}</p>;
            })}
        </div>
    );
}

export interface MeetingMinutesProps {
    meetingId: string | null;
    /** The documents already written for this meeting, oldest first. */
    documents: MeetingSummaryDoc[];
    /** The transcript is what a document is written from; with none there is nothing to do. */
    hasTranscript: boolean;
    /** Initial model target, normally the one chosen in meeting setup. */
    modelTarget?: MeetingModelTarget;
    /** Injected in tests. */
    fetcher?: typeof fetch;
    modelFetcher?: typeof fetch;
}

export function MeetingMinutes({
    meetingId, documents, hasTranscript, modelTarget, fetcher, modelFetcher,
}: MeetingMinutesProps) {
    const [written, setWritten] = useState<MeetingSummaryDoc[]>([]);
    const [selected, setSelected] = useState<number | null>(null);
    const [style, setStyle] = useState<string>(documents[documents.length - 1]?.style || 'minutes');
    const [length, setLength] = useState<string>('standard');
    const [instructions, setInstructions] = useState('');
    const [tuning, setTuning] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [copied, setCopied] = useState(false);
    const globalTarget = useMemo(() => readMeetingModelTarget(), []);
    const latestStoredTarget = documents[documents.length - 1]?.options;
    const initialTarget = modelTarget || {
        provider: String(latestStoredTarget?.provider || globalTarget.provider),
        model: String(latestStoredTarget?.model || globalTarget.model),
        baseUrl: String(latestStoredTarget?.base_url || globalTarget.baseUrl),
    };
    const [provider, setProvider] = useState(initialTarget.provider || 'ollama');
    const [model, setModel] = useState(initialTarget.model || '');
    const [baseUrl, setBaseUrl] = useState(initialTarget.baseUrl || '');
    const [models, setModels] = useState<string[]>(initialTarget.model ? [initialTarget.model] : []);

    useEffect(() => {
        if (!tuning) return;
        let cancelled = false;
        void fetchMeetingModels(
            { provider, model, baseUrl },
            modelFetcher || fetch,
        ).then((rows) => {
            if (!cancelled) setModels(rows);
        });
        return () => { cancelled = true; };
    }, [tuning, provider, model, baseUrl, modelFetcher]);

    // The server's documents plus this session's, in the order they were written. Kept as
    // two lists rather than one mutable one so that a record reload — which happens while a
    // recap is still settling — cannot drop a document generated a moment ago.
    const all = useMemo(() => {
        const byId = new Map<string, MeetingSummaryDoc>();
        for (const doc of [...documents, ...written]) {
            byId.set(String(doc.id ?? `${doc.style}-${doc.created_at}`), doc);
        }
        return [...byId.values()];
    }, [documents, written]);

    const index = selected == null ? all.length - 1 : Math.min(selected, all.length - 1);
    const current = index >= 0 ? all[index] : null;

    const generate = async () => {
        if (!meetingId || busy) return;
        setBusy(true);
        setError(null);
        const get = fetcher || fetch;
        try {
            const response = await get(
                `${backendBase()}/v1/meetingsense/${encodeURIComponent(meetingId)}/summary`,
                {
                    method: 'POST',
                    credentials: 'include',
                    headers: requestHeaders(),
                    body: JSON.stringify({
                        style,
                        length,
                        instructions,
                        remember: true,
                        provider,
                        model,
                        base_url: baseUrl,
                    }),
                },
            );
            if (response.status === 409) {
                setError('There is no transcript to summarise in this meeting.');
                return;
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const document = await response.json() as MeetingSummaryDoc;
            if (!(document?.text || '').trim()) {
                setError('The summary came back empty. Try again in a moment.');
                return;
            }
            setWritten((rows) => [...rows, document]);
            setSelected(null);
        } catch (failure) {
            const message = failure instanceof Error ? failure.message : 'request failed';
            setError(`Could not write the summary: ${message}`);
        } finally {
            setBusy(false);
        }
    };

    const copy = async () => {
        const text = current?.text || '';
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1800);
        } catch {
            // A clipboard a browser will not open is not worth an error message; the text is
            // on screen and selectable.
        }
    };

    return (
        <section
            className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4"
            data-testid="ms-minutes"
            aria-label="Meeting summary"
        >
            <div className="mb-3 flex flex-wrap items-center gap-2">
                <FileText size={14} className="text-violet-200/70" />
                <h3 className="text-sm font-semibold text-white/90">Full summary</h3>
                {all.length > 1 ? (
                    <span className="text-[10px] text-white/35" data-testid="ms-minutes-count">
                        {all.length} versions kept
                    </span>
                ) : null}
                <button
                    type="button"
                    onClick={() => setTuning((open) => !open)}
                    data-testid="ms-minutes-tune"
                    className="ml-auto rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[11px] text-white/55 hover:bg-white/[0.07] hover:text-white/80"
                >
                    {tuning ? 'Hide options' : 'Options'}
                </button>
            </div>

            {tuning ? (
                <div className="mb-3 space-y-3 rounded-xl border border-white/[0.07] bg-black/20 p-3" data-testid="ms-minutes-options">
                    <div>
                        <span className="mb-1.5 block text-[11px] font-medium text-white/55">Write it as</span>
                        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Summary style">
                            {SUMMARY_STYLES.map((option) => (
                                <button
                                    key={option.id}
                                    type="button"
                                    role="radio"
                                    aria-checked={style === option.id}
                                    title={option.note}
                                    onClick={() => setStyle(option.id)}
                                    data-testid={`ms-minutes-style-${option.id}`}
                                    className={`rounded-lg border px-2.5 py-1.5 text-[11px] transition ${style === option.id ? 'border-violet-300/30 bg-violet-400/10 text-violet-100' : 'border-white/[0.08] bg-white/[0.02] text-white/45 hover:text-white/75'}`}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                        <p className="mt-1.5 text-[10px] leading-4 text-white/30">
                            {SUMMARY_STYLES.find((option) => option.id === style)?.note}
                        </p>
                    </div>
                    <div>
                        <span className="mb-1.5 block text-[11px] font-medium text-white/55">Length</span>
                        <div className="flex gap-1.5" role="radiogroup" aria-label="Summary length">
                            {SUMMARY_LENGTHS.map((option) => (
                                <button
                                    key={option.id}
                                    type="button"
                                    role="radio"
                                    aria-checked={length === option.id}
                                    onClick={() => setLength(option.id)}
                                    data-testid={`ms-minutes-length-${option.id}`}
                                    className={`rounded-lg border px-2.5 py-1.5 text-[11px] transition ${length === option.id ? 'border-violet-300/30 bg-violet-400/10 text-violet-100' : 'border-white/[0.08] bg-white/[0.02] text-white/45 hover:text-white/75'}`}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                    </div>
                    <label className="block">
                        <span className="mb-1.5 block text-[11px] font-medium text-white/55">Language model</span>
                        <select
                            value={model}
                            onChange={(event) => setModel(event.target.value)}
                            data-testid="ms-minutes-model"
                            className="w-full rounded-xl border border-white/[0.08] bg-black/30 px-3 py-2 text-xs text-white/85 focus:border-violet-300/30 focus:outline-none"
                        >
                            <option value="">Automatic / provider default</option>
                            {models.map((row) => <option key={row} value={row}>{row}</option>)}
                        </select>
                        <span className="mt-1 block text-[10px] text-white/30">
                            {provider || 'ollama'} · the same provider family configured for HomePilot chat
                        </span>
                    </label>
                    <label className="block">
                        <span className="mb-1.5 block text-[11px] font-medium text-white/55">Anything else</span>
                        <input
                            type="text"
                            value={instructions}
                            onChange={(event) => setInstructions(event.target.value)}
                            placeholder="Write it in Spanish · address it to the board · keep the numbers"
                            data-testid="ms-minutes-instructions"
                            className="w-full rounded-xl border border-white/[0.08] bg-black/30 px-3 py-2 text-xs text-white/85 placeholder:text-white/25 focus:border-violet-300/30 focus:outline-none"
                        />
                    </label>
                </div>
            ) : null}

            {all.length > 1 ? (
                <div className="mb-3 flex flex-wrap gap-1.5" role="tablist" aria-label="Summary versions">
                    {all.map((doc, position) => (
                        <button
                            key={doc.id || `${doc.style}-${position}`}
                            type="button"
                            role="tab"
                            aria-selected={position === index}
                            onClick={() => setSelected(position)}
                            data-testid="ms-minutes-version"
                            className={`rounded-lg border px-2.5 py-1 text-[10px] ${position === index ? 'border-white/20 bg-white/10 text-white/85' : 'border-white/[0.07] bg-white/[0.02] text-white/40 hover:text-white/70'}`}
                        >
                            {styleLabel(doc.style)}
                        </button>
                    ))}
                </div>
            ) : null}

            {current ? (
                <>
                    {current.degraded === 'extractive' ? (
                        <p className="mb-3 rounded-xl border border-amber-300/15 bg-amber-300/[0.06] px-3 py-2 text-[11px] leading-4 text-amber-100/70" data-testid="ms-minutes-degraded">
                            No language model was reachable, so this is assembled from the meeting's
                            own words rather than written. Start your model and press Rewrite.
                        </p>
                    ) : null}
                    <DocumentBody text={current.text || ''} />
                    <div className="mt-3 flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => void copy()}
                            data-testid="ms-minutes-copy"
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 text-[11px] text-white/65 hover:bg-white/[0.08]"
                        >
                            {copied ? <Check size={12} /> : <Copy size={12} />}
                            {copied ? 'Copied' : 'Copy'}
                        </button>
                        {current.chunks ? (
                            <span className="text-[10px] text-white/25" data-testid="ms-minutes-meta">
                                From {current.chunks} part{current.chunks === 1 ? '' : 's'} of the transcript
                            </span>
                        ) : null}
                    </div>
                </>
            ) : (
                <p className="py-4 text-sm text-white/35" data-testid="ms-minutes-empty">
                    {hasTranscript
                        ? 'No full summary yet. Write one in whichever shape you need — minutes, a recap email, or just the actions.'
                        : 'There is no transcript in this meeting to summarise.'}
                </p>
            )}

            {error ? (
                <p className="mt-3 rounded-xl border border-red-400/20 bg-red-500/[0.07] px-3 py-2 text-[11px] text-red-200/85" role="status" data-testid="ms-minutes-error">
                    {error}
                </p>
            ) : null}

            <button
                type="button"
                onClick={() => void generate()}
                disabled={busy || !meetingId || !hasTranscript}
                data-testid="ms-minutes-generate"
                className="mt-3 inline-flex h-9 items-center gap-2 rounded-xl bg-white px-3.5 text-xs font-semibold text-black hover:bg-white/90 disabled:opacity-35"
            >
                {busy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                {busy ? 'Writing…' : current ? `Rewrite as ${styleLabel(style).toLowerCase()}` : 'Write the summary'}
            </button>
            {/* Said plainly, because the button is the one people hesitate over: a
                regeneration they dislike costs nothing, so there is no reason not to try one. */}
            <p className="mt-1.5 text-[10px] text-white/25" data-testid="ms-minutes-additive">
                Every version is kept. Writing a new one never replaces the meeting's notes or an
                earlier summary.
            </p>
        </section>
    );
}

export default MeetingMinutes;
