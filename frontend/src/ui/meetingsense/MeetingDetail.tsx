/**
 * One meeting, read back (batch MS28, wave W10).
 *
 * A tabbed side panel — Notes, Slides, Transcript — which is the shape `teams/MeetingRightRail`
 * uses for Agenda / Actions / Stats, and the batch row asked for that shape by name.
 *
 * **The shape is reused; the component is not, and that is deliberate.** Teams'
 * `MeetingRightRail` is typed against `MeetingRoom` from `teams/types` — a *persona room*,
 * with agenda items and per-persona speaking distribution. A MeetingSense meeting is a
 * recording of real people. The two share the word "meeting" and nothing else, and importing
 * that component would mean either widening its type to cover both or handing it a lie. The
 * layout is the part worth copying, so the layout is what was copied.
 *
 * **Nothing here fetches.** The panel renders what it is given, so History can pass rows it
 * already has and the library can pass rows it already has, and neither loads a meeting twice
 * because two components each decided to.
 */
import React, { useState } from 'react';
import { durationLabel, isLive, meetingTitle, sourceLabel, type Meeting } from './catalog';

export type DetailTab = 'notes' | 'slides' | 'transcript';

export interface MeetingDetailProps {
    meeting: Meeting | null;
    notes?: { recap?: string; decisions?: Array<{ text: string }>; actions?: Array<{ text: string; owner?: string }> } | null;
    slides?: Array<{ id?: string; caption?: string | null; t?: number }>;
    segments?: Array<{ id?: string; speaker?: string | null; text: string; t0?: number }>;
    onOpenConversation?: (conversationId: string) => void;
    onClose?: () => void;
}

const TABS: Array<{ id: DetailTab; label: string }> = [
    { id: 'notes', label: 'Notes' },
    { id: 'slides', label: 'Slides' },
    { id: 'transcript', label: 'Transcript' },
];

function Empty({ children }: { children: React.ReactNode }) {
    return <p className="text-xs text-white/40 py-6 text-center">{children}</p>;
}

export function MeetingDetail({
    meeting, notes, slides = [], segments = [], onOpenConversation, onClose,
}: MeetingDetailProps) {
    const [tab, setTab] = useState<DetailTab>('notes');
    if (!meeting) return null;

    const duration = durationLabel(meeting);
    const live = isLive(meeting);

    return (
        <aside
            className="w-96 h-full border-l border-white/[0.06] bg-[#0d0d0d] flex flex-col"
            data-testid="ms-detail"
            aria-label={`Meeting: ${meeting.title || 'Untitled meeting'}`}
        >
            <header className="p-4 border-b border-white/[0.06]">
                <div className="flex items-start justify-between gap-2">
                    <h3 className="text-sm font-semibold text-white/90" data-testid="ms-detail-title">
                        {meetingTitle(meeting)}
                    </h3>
                    {onClose ? (
                        <button
                            type="button"
                            onClick={onClose}
                            aria-label="Close meeting details"
                            className="text-white/40 hover:text-white/80 transition-colors"
                            data-testid="ms-detail-close"
                        >
                            ×
                        </button>
                    ) : null}
                </div>
                <p className="mt-1 text-xs text-white/40" data-testid="ms-detail-meta">
                    {[sourceLabel(meeting.source), live ? 'Recording now' : duration]
                        .filter(Boolean).join(' · ')}
                </p>
                {meeting.conversation_id && onOpenConversation ? (
                    // The route back to where the meeting already lives. D5's whole point is
                    // that a meeting is a conversation, so the catalog is a way in rather than
                    // a second home — and every path from it leads back to the thread.
                    <button
                        type="button"
                        onClick={() => onOpenConversation(meeting.conversation_id!)}
                        className="mt-3 text-xs text-cyan-300 hover:text-cyan-200 transition-colors"
                        data-testid="ms-detail-open"
                    >
                        Open the conversation →
                    </button>
                ) : null}
            </header>

            <nav className="flex border-b border-white/[0.06]" role="tablist" aria-label="Meeting detail">
                {TABS.map((entry) => (
                    <button
                        key={entry.id}
                        type="button"
                        role="tab"
                        aria-selected={tab === entry.id}
                        onClick={() => setTab(entry.id)}
                        data-testid={`ms-detail-tab-${entry.id}`}
                        className={
                            tab === entry.id
                                ? 'flex-1 px-3 py-2 text-xs text-white border-b-2 border-cyan-500/60'
                                : 'flex-1 px-3 py-2 text-xs text-white/40 hover:text-white/70 border-b-2 border-transparent transition-colors'
                        }
                    >
                        {entry.label}
                    </button>
                ))}
            </nav>

            <div className="flex-1 overflow-y-auto p-4" role="tabpanel" data-testid="ms-detail-panel">
                {tab === 'notes' ? (
                    notes && (notes.recap || notes.decisions?.length || notes.actions?.length) ? (
                        <div className="space-y-4">
                            {notes.recap ? (
                                <p className="text-sm text-white/80" data-testid="ms-detail-recap">{notes.recap}</p>
                            ) : null}
                            {notes.decisions?.length ? (
                                <section>
                                    <h4 className="text-xs uppercase tracking-wide text-white/40 mb-1">Decisions</h4>
                                    <ul className="space-y-1">
                                        {notes.decisions.map((d, i) => (
                                            <li key={i} className="text-sm text-white/75">{d.text}</li>
                                        ))}
                                    </ul>
                                </section>
                            ) : null}
                            {notes.actions?.length ? (
                                <section>
                                    <h4 className="text-xs uppercase tracking-wide text-white/40 mb-1">Actions</h4>
                                    <ul className="space-y-1">
                                        {notes.actions.map((a, i) => (
                                            <li key={i} className="text-sm text-white/75">
                                                {a.text}{a.owner ? <span className="text-white/40"> · {a.owner}</span> : null}
                                            </li>
                                        ))}
                                    </ul>
                                </section>
                            ) : null}
                        </div>
                    ) : (
                        <Empty>No notes were taken for this meeting.</Empty>
                    )
                ) : null}

                {tab === 'slides' ? (
                    slides.length ? (
                        <ul className="space-y-2" data-testid="ms-detail-slides">
                            {slides.map((slide, i) => (
                                <li key={slide.id ?? i} className="text-sm text-white/75">
                                    {slide.caption || <span className="text-white/40">Uncaptioned slide</span>}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <Empty>No slides were captured.</Empty>
                    )
                ) : null}

                {tab === 'transcript' ? (
                    segments.length ? (
                        <ul className="space-y-1.5" data-testid="ms-detail-transcript">
                            {segments.map((segment, i) => (
                                <li key={segment.id ?? i} className="text-sm text-white/75">
                                    <span className="text-white/35">{segment.speaker === 'me' ? 'You' : 'Them'}</span>{' '}
                                    {segment.text}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <Empty>Nothing was transcribed.</Empty>
                    )
                ) : null}
            </div>
        </aside>
    );
}

export default MeetingDetail;
