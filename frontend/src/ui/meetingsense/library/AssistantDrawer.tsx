/**
 * The meeting assistant: a drawer that answers from this meeting only, with citations that
 * play the recording from the line they point at.
 *
 * The history is kept per meeting for the browser session, so switching tabs or closing the
 * drawer never loses a conversation. Answers come from the same `ask` route the AI Chat tab
 * uses; this drawer finally shows its `cited` stamps and says when an answer is quoted from
 * the transcript because no model answered.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Bot, Loader2, Play, Send, X } from 'lucide-react';
import { LibraryError, libraryApi } from './api';
import { stampToMs } from './intelligenceApi';

interface Turn { q: string; a: string; cited: string[]; degraded?: string | null; error?: boolean }

const KEY = (meetingId: string) => `hp_meeting_assistant:${meetingId}`;

function readHistory(meetingId: string): Turn[] {
    try {
        const raw = sessionStorage.getItem(KEY(meetingId));
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch { return []; }
}

export function AssistantLauncher({ onOpen, hidden }: { onOpen: () => void; hidden?: boolean }) {
    if (hidden) return null;
    return (
        <button type="button" onClick={onOpen} data-testid="assistant-launcher"
            className="fixed bottom-5 right-5 z-[55] inline-flex h-12 items-center gap-2 rounded-full border border-violet-300/30 bg-gradient-to-r from-fuchsia-600 to-violet-600 pl-4 pr-5 text-sm font-semibold text-white shadow-xl shadow-fuchsia-900/30 hover:from-fuchsia-500 hover:to-violet-500 focus-visible:outline-violet-300">
            <Bot size={18} /> Ask about this meeting
        </button>
    );
}

export function AssistantDrawer({ meetingId, open, onClose, seed, onSeeded, onSeek, hasTranscript, title }: {
    meetingId: string;
    open: boolean;
    onClose: () => void;
    /** A question handed in from a suggestion card; asked as soon as the drawer opens. */
    seed?: string | null;
    onSeeded?: () => void;
    onSeek?: (ms: number) => void;
    hasTranscript: boolean;
    title?: string;
}) {
    const [log, setLog] = useState<Turn[]>(() => readHistory(meetingId));
    const [q, setQ] = useState('');
    const [busy, setBusy] = useState(false);
    const input = useRef<HTMLInputElement>(null);
    const end = useRef<HTMLDivElement>(null);

    useEffect(() => { setLog(readHistory(meetingId)); }, [meetingId]);
    useEffect(() => { try { sessionStorage.setItem(KEY(meetingId), JSON.stringify(log.slice(-40))); } catch { /* ignore */ } }, [meetingId, log]);
    useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }); }, [log, busy, open]);

    const ask = async (question: string) => {
        const text = question.trim();
        if (!text || !meetingId) return;
        setQ('');
        setBusy(true);
        try {
            const res = await libraryApi.ask(meetingId, text);
            const answer = String(res.text || res.answer || '').trim();
            const cited: string[] = Array.isArray(res.cited) ? res.cited.map((c: unknown) => String(c)) : [];
            setLog((l) => [...l, {
                q: text,
                a: answer || (res.error ? 'No language model answered, so this could not be answered. The transcript is still searchable.' : 'The meeting does not say.'),
                cited, degraded: res.degraded || null, error: !answer && !!res.error,
            }]);
        } catch (e) {
            setLog((l) => [...l, { q: text, a: e instanceof LibraryError ? e.message : 'The question could not be answered.', cited: [], error: true }]);
        } finally {
            setBusy(false);
        }
    };

    useEffect(() => {
        if (open && seed) {
            onSeeded?.();
            void ask(seed);
        }
        if (open) setTimeout(() => input.current?.focus(), 50);
    }, [open, seed]); // eslint-disable-line react-hooks/exhaustive-deps

    // Escape closes the drawer wherever focus is — the page behind it, the input, a chip.
    useEffect(() => {
        if (!open) return undefined;
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [open, onClose]);

    if (!open) return null;
    return (
        <div className="fixed inset-0 z-[60] flex justify-end bg-black/50" onClick={onClose} data-testid="assistant-drawer">
            <aside role="dialog" aria-modal="true" aria-label="Meeting assistant"
                className="flex h-full w-full flex-col border-l border-white/10 bg-[#0b0b10] sm:w-[min(94vw,440px)]"
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
                <header className="flex items-center gap-3 border-b border-white/[0.06] px-4 py-3">
                    <span className="grid h-9 w-9 place-items-center rounded-xl bg-violet-500/20 text-violet-200"><Bot size={18} /></span>
                    <div className="min-w-0 flex-1">
                        <h2 className="font-semibold leading-tight">Ask about this meeting</h2>
                        <p className="truncate text-xs text-white/50">{title || 'Answers come only from this meeting’s transcript.'}</p>
                    </div>
                    <button type="button" onClick={onClose} aria-label="Close assistant" className="grid h-9 w-9 place-items-center rounded-full hover:bg-white/10"><X size={16} /></button>
                </header>

                <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
                    {!hasTranscript ? <p className="text-sm text-white/55">Questions are answered from the transcript, and this meeting does not have one yet.</p> : null}
                    {hasTranscript && !log.length ? (
                        <p className="text-sm text-white/55">Ask what was decided, who owns what, why an approach was chosen, or what is still open. Each answer points at the lines it rests on.</p>
                    ) : null}
                    {log.map((m, i) => (
                        <div key={i} className="space-y-1.5">
                            <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-violet-600/40 px-3 py-2 text-sm">{m.q}</p>
                            <div className="w-fit max-w-[92%] rounded-2xl rounded-bl-md border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white/85">
                                <p className="whitespace-pre-line">{m.a}</p>
                                {m.cited.length ? (
                                    <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Sources in the transcript">
                                        {m.cited.map((c) => {
                                            const ms = stampToMs(c);
                                            return ms === null ? null : (
                                                <button key={c} type="button" onClick={() => onSeek?.(ms)} disabled={!onSeek} aria-label={`Play from ${c}`}
                                                    className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-xs tabular-nums text-violet-200 hover:bg-violet-500/20 hover:text-white disabled:text-white/50">
                                                    <Play size={10} /> {c}
                                                </button>
                                            );
                                        })}
                                    </div>
                                ) : null}
                                {m.degraded === 'extractive' ? <p className="mt-1.5 text-xs text-amber-200/90">No language model answered — these are the transcript lines that match your question.</p> : null}
                            </div>
                        </div>
                    ))}
                    {busy ? <p className="flex items-center gap-2 text-sm text-white/50"><Loader2 size={14} className="animate-spin" /> Reading the transcript…</p> : null}
                    <div ref={end} />
                </div>

                <form className="flex gap-2 border-t border-white/[0.06] p-3" onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
                    <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} disabled={!hasTranscript || busy}
                        placeholder="Ask a question about this meeting…" aria-label="Ask a question about this meeting"
                        className="h-11 min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm focus:border-violet-400/60 focus:outline-none disabled:opacity-50" />
                    <button type="submit" disabled={busy || !q.trim() || !hasTranscript} aria-label="Ask"
                        className="grid h-11 w-11 place-items-center rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50"><Send size={16} /></button>
                </form>
            </aside>
        </div>
    );
}

export default AssistantDrawer;
