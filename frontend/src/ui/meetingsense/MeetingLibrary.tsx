/**
 * The meetings grid (batch MS28, wave W10) — behind `_CATALOG`, which defaults off.
 *
 * The card grid is `teams/TeamsLandingPage`'s, which the batch row asked for by name: the same
 * `sm:2 / lg:3 / xl:4` columns, the same `rounded-2xl` card on a near-black ground, the same
 * hover. Copied rather than imported for the reason `MeetingDetail` gives — that page is typed
 * against persona rooms, and the two things share a word and nothing else.
 *
 * **This view exists behind a flag that is off, and that is the point of it.** D5 decided the
 * catalog lives in History and said a sidebar tab is for "only if History gets crowded". A flag
 * defaulting off is that condition, made operable: the code is here, ready, and nobody's
 * sidebar changes until somebody decides their History is crowded. Shipping it on would be
 * overturning a recorded decision on a guess about how people will use a feature that has not
 * finished its pilot.
 */
import React, { useMemo, useState } from 'react';
import {
    durationLabel,
    filterMeetings,
    isLive,
    since as sinceSeconds,
    sourceLabel,
    sources as sourcesOf,
    type Meeting,
} from './catalog';

export interface MeetingLibraryProps {
    meetings: Meeting[];
    onOpen?: (meeting: Meeting) => void;
    /** Injected so the "last 7 days" chips are testable without freezing the clock globally. */
    now?: number;
}

const RANGES: Array<{ label: string; days: number | null }> = [
    { label: 'All time', days: null },
    { label: 'Last 7 days', days: 7 },
    { label: 'Last 30 days', days: 30 },
];

export function MeetingLibrary({ meetings, onOpen, now }: MeetingLibraryProps) {
    const [query, setQuery] = useState('');
    const [source, setSource] = useState('');
    const [days, setDays] = useState<number | null>(null);

    const available = useMemo(() => sourcesOf(meetings), [meetings]);
    const shown = useMemo(
        () => filterMeetings(meetings, {
            query, source, since: sinceSeconds(days, now ?? Date.now() / 1000),
        }),
        [meetings, query, source, days, now],
    );

    return (
        <div className="h-full flex flex-col bg-[#0a0a0a]" data-testid="ms-library">
            <header className="flex-shrink-0 px-6 py-5 border-b border-white/[0.04]">
                <h2 className="text-base font-semibold text-white/90">Meetings</h2>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                    <input
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search meetings…"
                        aria-label="Search meetings"
                        data-testid="ms-library-search"
                        className="flex-1 min-w-[200px] bg-black border border-white/10 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-white/30"
                    />
                    {RANGES.map((range) => (
                        <button
                            key={range.label}
                            type="button"
                            onClick={() => setDays(range.days)}
                            aria-pressed={days === range.days}
                            data-testid={`ms-library-range-${range.days ?? 'all'}`}
                            className={
                                days === range.days
                                    ? 'px-3 py-1 rounded-full text-xs border border-cyan-500/40 bg-cyan-500/10 text-cyan-200'
                                    : 'px-3 py-1 rounded-full text-xs border border-white/10 bg-white/[0.03] text-white/60 hover:text-white/90'
                            }
                        >
                            {range.label}
                        </button>
                    ))}
                </div>
                {available.length > 1 ? (
                    // One source is not a facet, it is a label — and a filter with a single
                    // option is a control that cannot change anything.
                    <div className="mt-2 flex flex-wrap gap-2" data-testid="ms-library-sources">
                        <button
                            type="button"
                            onClick={() => setSource('')}
                            aria-pressed={source === ''}
                            data-testid="ms-library-source-all"
                            className={
                                source === ''
                                    ? 'px-3 py-1 rounded-full text-xs border border-cyan-500/40 bg-cyan-500/10 text-cyan-200'
                                    : 'px-3 py-1 rounded-full text-xs border border-white/10 bg-white/[0.03] text-white/60 hover:text-white/90'
                            }
                        >
                            Every source
                        </button>
                        {available.map((name) => (
                            <button
                                key={name}
                                type="button"
                                onClick={() => setSource(name)}
                                aria-pressed={source === name}
                                data-testid={`ms-library-source-${name}`}
                                className={
                                    source === name
                                        ? 'px-3 py-1 rounded-full text-xs border border-cyan-500/40 bg-cyan-500/10 text-cyan-200'
                                        : 'px-3 py-1 rounded-full text-xs border border-white/10 bg-white/[0.03] text-white/60 hover:text-white/90'
                                }
                            >
                                {sourceLabel(name)}
                            </button>
                        ))}
                    </div>
                ) : null}
            </header>

            <div className="flex-1 overflow-y-auto px-6 py-5">
                {shown.length === 0 ? (
                    <div className="max-w-[1400px] mx-auto rounded-2xl border border-white/[0.08] bg-white/[0.02] p-16 text-center">
                        <p className="text-sm text-white/50" data-testid="ms-library-empty">
                            {meetings.length === 0
                                ? 'No meetings recorded yet.'
                                : 'No meetings match those filters.'}
                        </p>
                    </div>
                ) : (
                    <div
                        className="max-w-[1400px] mx-auto grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5 content-start"
                        data-testid="ms-library-grid"
                    >
                        {shown.map((meeting) => (
                            <button
                                key={meeting.id}
                                type="button"
                                onClick={() => onOpen?.(meeting)}
                                data-testid={`ms-library-card-${meeting.id}`}
                                className="group text-left rounded-2xl overflow-hidden bg-white/[0.02] border border-white/[0.06] hover:border-cyan-500/30 hover:bg-white/[0.04] transition-all duration-200 p-4"
                            >
                                <div className="flex items-start justify-between gap-2">
                                    <span className="text-sm text-white/90 line-clamp-2">
                                        {meeting.title?.trim() || 'Untitled meeting'}
                                    </span>
                                    {isLive(meeting) ? (
                                        <span
                                            className="flex-shrink-0 px-2 py-0.5 rounded-full text-[10px] border border-red-500/40 bg-red-500/10 text-red-300"
                                            data-testid={`ms-library-live-${meeting.id}`}
                                        >
                                            Recording
                                        </span>
                                    ) : null}
                                </div>
                                <p className="mt-2 text-xs text-white/40">
                                    {[sourceLabel(meeting.source), durationLabel(meeting)]
                                        .filter(Boolean).join(' · ')}
                                </p>
                                <p className="mt-3 text-xs text-white/30">
                                    {[
                                        meeting.segments ? `${meeting.segments} lines` : '',
                                        meeting.keyframes ? `${meeting.keyframes} slides` : '',
                                    ].filter(Boolean).join(' · ')}
                                </p>
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

export default MeetingLibrary;
