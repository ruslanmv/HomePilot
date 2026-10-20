/**
 * The meeting assistant: a sidebar that answers from this meeting only, with citations that
 * play the recording from the line they point at.
 *
 * The history is kept per meeting for the browser session, so switching tabs or closing the
 * panel never loses a conversation. Answers come from the same `ask` route the AI Chat tab
 * uses, with their `cited` stamps, and say when an answer is quoted from the transcript
 * because no model answered.
 *
 * **A sidebar, not a modal.** It used to sit on a full-page `bg-black/50` backdrop that closed
 * it on `click` — which also fired when a press began inside the panel and ended outside it
 * (selecting a line of an answer, dragging from the input, a scrollbar), so the chat vanished
 * mid-gesture, and the dimmed page read as disabled. Now nothing covers the meeting: on wide
 * screens the panel takes the details column's place in the page layout (`layout="inline"`),
 * on small ones it is a full-screen view (`layout="sheet"`). It closes on its X, on Escape,
 * and on a press that both starts *and* ends outside it — never on one that touched it, and
 * never on a control that opens it (`data-assistant-trigger`).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, Loader2, Play, Send, X } from 'lucide-react';
import { LibraryError, libraryApi } from './api';
import { stampToMs } from './intelligenceApi';

interface Turn {
    q: string;
    a: string;
    cited: string[];
    degraded?: string | null;
    error?: boolean;
    /** When the question was asked and when it was answered (epoch ms). */
    askedAt?: number;
    answeredAt?: number;
}

const KEY = (meetingId: string) => `hp_meeting_assistant:${meetingId}`;
/** Matches the panel's exit transition. */
const CLOSE_MS = 160;

function readHistory(meetingId: string): Turn[] {
    try {
        const raw = sessionStorage.getItem(KEY(meetingId));
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch { return []; }
}

function timeOf(ms?: number): string {
    if (!ms) return '';
    try {
        return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(ms));
    } catch { return ''; }
}

function reducedMotion(): boolean {
    try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches; } catch { return false; }
}

export function AssistantLauncher({ onOpen, hidden }: { onOpen: () => void; hidden?: boolean }) {
    if (hidden) return null;
    return (
        <button type="button" onClick={onOpen} data-testid="assistant-launcher" data-assistant-trigger=""
            className="fixed bottom-5 right-5 z-[55] inline-flex h-12 items-center gap-2 rounded-full border border-violet-300/30 bg-gradient-to-r from-fuchsia-600 to-violet-600 pl-4 pr-5 text-sm font-semibold text-white shadow-xl shadow-fuchsia-900/30 hover:from-fuchsia-500 hover:to-violet-500 focus-visible:outline-violet-300">
            <Bot size={18} /> Ask about this meeting
        </button>
    );
}

export function AssistantDrawer({ meetingId, open, onClose, seed, onSeeded, onSeek, hasTranscript, title, layout = 'sheet' }: {
    meetingId: string;
    open: boolean;
    onClose: () => void;
    /** A question handed in from a suggestion card or the Ask card; asked as soon as it opens. */
    seed?: string | null;
    onSeeded?: () => void;
    onSeek?: (ms: number) => void;
    hasTranscript: boolean;
    title?: string;
    /** `inline`: a column of the page layout (wide screens). `sheet`: a full-screen view. */
    layout?: 'inline' | 'sheet';
}) {
    const [log, setLog] = useState<Turn[]>(() => readHistory(meetingId));
    const [q, setQ] = useState('');
    const [busy, setBusy] = useState(false);
    const [leaving, setLeaving] = useState(false);
    const panel = useRef<HTMLElement>(null);
    const input = useRef<HTMLTextAreaElement>(null);
    const end = useRef<HTMLDivElement>(null);
    const onCloseRef = useRef(onClose);
    onCloseRef.current = onClose;

    useEffect(() => { setLog(readHistory(meetingId)); }, [meetingId]);
    useEffect(() => { try { sessionStorage.setItem(KEY(meetingId), JSON.stringify(log.slice(-40))); } catch { /* ignore */ } }, [meetingId, log]);
    useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }); }, [log, busy, open]);

    // It slides in with a CSS animation on mount; a closing panel slides out before it unmounts.
    useEffect(() => { if (!open) setLeaving(false); }, [open]);

    const requestClose = useCallback(() => {
        if (reducedMotion()) { onCloseRef.current(); return; }
        setLeaving(true);
        window.setTimeout(() => onCloseRef.current(), CLOSE_MS);
    }, []);

    const ask = async (question: string) => {
        const text = question.trim();
        if (!text || !meetingId || busy) return;
        setQ('');
        setBusy(true);
        const askedAt = Date.now();
        try {
            const res = await libraryApi.ask(meetingId, text);
            const answer = String(res.text || res.answer || '').trim();
            const cited: string[] = Array.isArray(res.cited) ? res.cited.map((c: unknown) => String(c)) : [];
            setLog((l) => [...l, {
                q: text,
                a: answer || (res.error ? 'No language model answered, so this could not be answered. The transcript is still searchable.' : 'The meeting does not say.'),
                cited, degraded: res.degraded || null, error: !answer && !!res.error,
                askedAt, answeredAt: Date.now(),
            }]);
        } catch (e) {
            setLog((l) => [...l, {
                q: text, a: e instanceof LibraryError ? e.message : 'The question could not be answered.', cited: [], error: true,
                askedAt, answeredAt: Date.now(),
            }]);
        } finally {
            setBusy(false);
            // Ready for the next question without reaching for the mouse.
            window.setTimeout(() => input.current?.focus(), 0);
        }
    };

    useEffect(() => {
        if (open && seed) {
            onSeeded?.();
            void ask(seed);
        }
        if (open) window.setTimeout(() => input.current?.focus(), 50);
    }, [open, seed]); // eslint-disable-line react-hooks/exhaustive-deps

    // Escape closes the panel wherever focus is — the page, the input, a citation.
    useEffect(() => {
        if (!open) return undefined;
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') requestClose(); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [open, requestClose]);

    // Outside press: one that starts and ends outside the panel, on the page, and not on a
    // control that opens the assistant. Listening in the capture phase means nothing inside
    // the page can swallow it, and nothing inside the panel can ever be mistaken for outside.
    useEffect(() => {
        if (!open || layout !== 'inline') return undefined;
        let downOutside = false;
        const outside = (target: EventTarget | null): boolean => {
            const el = target as Element | null;
            if (!el || !(el instanceof Element) || !panel.current) return false;
            if (panel.current.contains(el)) return false;
            if (el.closest('[data-assistant-trigger]')) return false;
            // A node already removed from the page (a menu that closed itself) is no evidence.
            return document.documentElement.contains(el);
        };
        const primary = (e: Event) => ((e as PointerEvent).button ?? 0) === 0;
        const onDown = (e: Event) => { downOutside = primary(e) && outside(e.target); };
        const onUp = (e: Event) => {
            if (downOutside && primary(e) && outside(e.target)) requestClose();
            downOutside = false;
        };
        document.addEventListener('pointerdown', onDown, true);
        document.addEventListener('pointerup', onUp, true);
        return () => {
            document.removeEventListener('pointerdown', onDown, true);
            document.removeEventListener('pointerup', onUp, true);
        };
    }, [open, layout, requestClose]);

    if (!open) return null;

    const frame = layout === 'inline'
        ? 'h-full w-full border-l border-white/[0.08]'
        : 'fixed inset-0 z-[70]';
    return (
        <aside
            ref={panel}
            role="complementary"
            aria-label="Ask about this meeting"
            data-testid="assistant-drawer"
            data-layout={layout}
            className={[
                frame,
                'flex flex-col bg-[#0b0b10] text-white',
                'motion-safe:animate-[hpPanelIn_150ms_ease-out]',
                'motion-safe:transition-[opacity,transform] motion-safe:duration-150 motion-safe:ease-out',
                leaving ? 'translate-x-4 opacity-0' : 'translate-x-0 opacity-100',
            ].join(' ')}
        >
            <header className="flex shrink-0 items-center gap-3 border-b border-white/[0.06] px-4 py-3.5">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-violet-500/20 text-violet-200"><Bot size={19} /></span>
                <div className="min-w-0 flex-1">
                    <h2 className="font-semibold leading-tight">Ask about this meeting</h2>
                    <p className="truncate text-xs text-white/50">{title || 'Answers come only from this meeting’s transcript.'}</p>
                </div>
                <button type="button" onClick={requestClose} aria-label="Close assistant"
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-white/70 hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400">
                    <X size={17} />
                </button>
            </header>

            <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-5" aria-live="polite">
                {!hasTranscript ? <p className="text-sm text-white/55">Questions are answered from the transcript, and this meeting does not have one yet.</p> : null}
                {hasTranscript && !log.length && !busy ? (
                    <p className="rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-3 text-sm leading-relaxed text-white/60">
                        Ask what was decided, who owns what, why an approach was chosen, or what is still open. Each answer
                        points at the lines it rests on. <span className="text-white/40">Private to you — nothing here is added to the meeting.</span>
                    </p>
                ) : null}
                {log.map((m, i) => (
                    <div key={i} className="space-y-3">
                        <div className="flex flex-col items-end">
                            <p className="max-w-[85%] whitespace-pre-line rounded-2xl rounded-br-md bg-violet-600 px-4 py-2.5 text-sm leading-relaxed text-white">{m.q}</p>
                            {m.askedAt ? <span className="mt-1 text-[11px] text-white/35">{timeOf(m.askedAt)}</span> : null}
                        </div>
                        <div className="flex items-start gap-2.5">
                            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-violet-500/15 text-violet-200" aria-hidden><Bot size={15} /></span>
                            <div className="min-w-0 max-w-[88%]">
                                <div className={`rounded-2xl rounded-tl-md border px-4 py-2.5 text-sm leading-relaxed ${m.error ? 'border-rose-400/20 bg-rose-500/[0.06] text-rose-100/90' : 'border-white/[0.07] bg-[#16161d] text-white/85'}`}>
                                    <p className="whitespace-pre-line">{m.a}</p>
                                    {m.degraded === 'extractive' ? <p className="mt-2 text-xs text-amber-200/90">No language model answered — these are the transcript lines that match your question.</p> : null}
                                </div>
                                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                                    {m.answeredAt ? <span className="mr-1 text-[11px] text-white/35">{timeOf(m.answeredAt)}</span> : null}
                                    {m.cited.map((c) => {
                                        const ms = stampToMs(c);
                                        return ms === null ? null : (
                                            <button key={c} type="button" onClick={() => onSeek?.(ms)} disabled={!onSeek} aria-label={`Play from ${c}`}
                                                className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-xs tabular-nums text-violet-200 hover:bg-violet-500/20 hover:text-white disabled:cursor-default disabled:text-white/50">
                                                <Play size={10} /> {c}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        </div>
                    </div>
                ))}
                {busy ? (
                    <div className="flex items-center gap-2.5" role="status">
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-violet-500/15 text-violet-200" aria-hidden><Bot size={15} /></span>
                        <span className="inline-flex items-center gap-2 rounded-2xl rounded-tl-md border border-white/[0.07] bg-[#16161d] px-4 py-2.5 text-sm text-white/60">
                            <Loader2 size={14} className="animate-spin" /> Reading the transcript…
                        </span>
                    </div>
                ) : null}
                <div ref={end} />
            </div>

            <form className="shrink-0 border-t border-white/[0.06] p-3" onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
                <div className="flex items-end gap-2">
                    <textarea
                        ref={input}
                        value={q}
                        rows={1}
                        onChange={(e) => setQ(e.target.value)}
                        // Enter sends; Shift+Enter is a new line. A composing IME keeps its Enter.
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                                e.preventDefault();
                                void ask(q);
                            }
                        }}
                        disabled={!hasTranscript}
                        placeholder="Ask a question about this meeting…"
                        aria-label="Ask a question about this meeting"
                        className="max-h-32 min-h-[44px] min-w-0 flex-1 resize-none rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm leading-relaxed placeholder:text-white/35 focus:border-violet-400/60 focus:outline-none disabled:opacity-50"
                    />
                    <button type="submit" disabled={busy || !q.trim() || !hasTranscript} aria-label="Ask"
                        className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-45">
                        {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                    </button>
                </div>
                <p className="mt-1.5 px-1 text-[11px] text-white/30">Enter to send · Shift+Enter for a new line</p>
            </form>
        </aside>
    );
}

export default AssistantDrawer;
