/**
 * The live transcript card (batch MS6).
 *
 * Three §2a rules shape every decision in this file, and each of them is about trust rather
 * than about looks.
 *
 * **Nothing already shown changes.** Segments are append-only and keyed by id, so a resume
 * replay is invisible instead of doubling the last few lines.
 *
 * **No layout jump.** A provisional line occupies the same element, with the same class, as
 * the segment that replaces it — so solidifying swaps text in place instead of adding a row
 * and pushing everything up.
 *
 * **The reader is never yanked.** New lines scroll into view only when the reader is already
 * at the bottom. Somebody who scrolled up is reading something; a "↓ new lines" button lets
 * them come back when they choose to.
 *
 * The transcript is a `<section aria-label="Live transcript">` with `aria-live="polite"`, and
 * each line a `<p data-t0>` — the timestamp is data, not decoration, and MS10's slide join
 * reads it.
 *
 * MS10 hangs the slide strip below the transcript rather than beside it: a strip in the margin
 * competes with the transcript for the same attention and adds a horizontal scroll on every
 * phone, and the slides are the thing a reader goes looking for rather than watches.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import ChipRow from './ChipRow';
import MeetingSummary from './MeetingSummary';
import AskField from './AskField';
import MeetingMenu from './MeetingMenu';
import {
    dayLabel,
    durationLabel,
    notesBody,
    segmentAt,
    titleOf,
    type MeetingRecord,
} from './meetingRecord';
import SlideStrip from './SlideStrip';
import {
    latencyLabel,
    shouldStickToBottom,
    speakerLabel,
    stampLabel,
    type MeetingView,
    type Segment,
} from './meetingState';

export interface MeetingCardProps {
    view: MeetingView;
    /** Rendered small: a phone shows the summary and the last few lines, never the lot. */
    compact?: boolean;
    lastLines?: number;
    /**
     * Kept for embedders. The product's export surface is the `•••` menu (MS33) and the
     * provider does not pass this, so a HomePilot install has exactly one way to export.
     */
    onExport?: (fmt: 'md' | 'srt' | 'json') => void;
    /** MS33. The ended meeting's stored record — summary, decisions, actions. */
    record?: MeetingRecord | null;
    /** The final notes window has not been written yet. */
    pendingNotes?: boolean;
    fetcher?: typeof fetch;
    base?: string;
    onOpenConversation?: (conversationId: string) => void;
    onDeleted?: () => void;
    /** MS25. Both absent means the card shows no chips at all — which is what a surface that
     *  has not wired them, or an install with the flag off, should show. */
    onAcceptChip?: (id: string) => void;
    onDismissChip?: (id: string) => void;
}

function Line({ segment, provisional }: { segment: Segment; provisional?: boolean }) {
    // One element for both states. A provisional line rendered as a different element — a
    // <span>, an <em>, a wrapper — changes the box, and the transcript shifts under the
    // reader the moment the real text arrives.
    return (
        <p
            className={provisional ? 'ms-line ms-line--provisional' : 'ms-line'}
            data-t0={segment.t0 ?? 0}
            data-testid={provisional ? 'ms-partial' : 'ms-segment'}
        >
            <span className="ms-line__stamp">{stampLabel(segment.t0)}</span>{' '}
            <span className="ms-line__speaker">{speakerLabel(segment.speaker)}</span>{' '}
            <span className="ms-line__text">{segment.text}</span>
        </p>
    );
}

export function MeetingCard({
    view, compact = false, lastLines = 3, onExport, onAcceptChip, onDismissChip,
    record = null, pendingNotes = false, fetcher, base = '', onOpenConversation, onDeleted,
}: MeetingCardProps) {
    const scroller = useRef<HTMLDivElement | null>(null);
    const [stuck, setStuck] = useState(true);
    const [unseen, setUnseen] = useState(0);

    const onScroll = useCallback(() => {
        const el = scroller.current;
        if (!el) return;
        const atBottom = shouldStickToBottom(el);
        setStuck(atBottom);
        if (atBottom) setUnseen(0);
    }, []);

    useEffect(() => {
        const el = scroller.current;
        if (!el) return;
        if (stuck) {
            el.scrollTop = el.scrollHeight;
        } else {
            // Counted rather than jumped to: the button says how much is waiting, and going
            // there stays the reader's decision.
            setUnseen((n) => n + 1);
        }
        // Only when the transcript grows: a re-render for any other reason must not scroll.
    }, [view.segments.length]); // eslint-disable-line react-hooks/exhaustive-deps

    const jumpToBottom = () => {
        const el = scroller.current;
        if (el) el.scrollTop = el.scrollHeight;
        setStuck(true);
        setUnseen(0);
    };

    const lines = compact ? view.segments.slice(-lastLines) : view.segments;
    const behind = latencyLabel(view.behindMs);

    // ── MS33: the ended meeting ─────────────────────────────────────────────
    //
    // `ended` is where the product pays off, so the card changes shape rather than adding a
    // footer to the live one: summary, decisions, actions and an ask field come first, and
    // the transcript — the recording rather than the value — collapses behind a disclosure.
    const ended = view.phase === 'ended';
    const body = notesBody(record?.notes);
    const meeting = record?.meeting || null;
    const [renamed, setRenamed] = useState<string | null>(null);
    const heading = renamed || titleOf(meeting, 'Meeting');
    const meta = [dayLabel(meeting), durationLabel(meeting)].filter(Boolean).join(' · ');
    // Collapsed on the *transition* to ended, and never again — the dependency array is the
    // whole of that rule. Notes land a second or two after the meeting stops, so the render
    // that brings the summary is exactly the render that would otherwise shut the transcript
    // under somebody already reading it.
    //
    // An earlier draft latched this with a ref as well. The latch was unreachable: an effect
    // keyed on `ended` cannot run twice for one transition, so the second guard could only
    // ever agree with the first. Two copies of one rule is how they come to disagree.
    const [transcriptOpen, setTranscriptOpen] = useState(true);
    useEffect(() => {
        if (ended) setTranscriptOpen(false);
    }, [ended]);

    const [highlight, setHighlight] = useState<string | null>(null);
    /** A citation is only a citation if it can be followed. */
    const seek = useCallback((ms: number) => {
        const id = segmentAt(view.segments as never, ms);
        setTranscriptOpen(true);
        setHighlight(id);
        if (!id) return;
        // After the disclosure has rendered, or there is nothing to scroll to yet.
        requestAnimationFrame(() => {
            const node = scroller.current?.querySelector(`[data-segment-id="${CSS.escape(id)}"]`);
            node?.scrollIntoView({ block: 'center', behavior: 'smooth' });
        });
    }, [view.segments]);

    return (
        <div className="ms-card" data-phase={view.phase} data-compact={compact ? 'true' : 'false'} data-testid="ms-card">
            <header className="ms-card__head">
                <h3 className="ms-card__title" data-testid="ms-card-title">{ended ? heading : 'Meeting'}</h3>
                {ended && meta ? (
                    <span className="ms-card__meta" data-testid="ms-card-meta">{meta}</span>
                ) : null}
                {behind ? (
                    // §2a: a slow transcript says it is slow. Silence where words should be
                    // reads as broken, and the user's next move is to stop the recording.
                    <span className="ms-card__behind" data-testid="ms-behind">
                        {behind}
                    </span>
                ) : null}
                {view.phase === 'reconnecting' ? (
                    <span className="ms-card__reconnecting" data-testid="ms-reconnecting">
                        reconnecting…
                    </span>
                ) : null}
                {view.error ? (
                    <span className="ms-card__error" data-testid="ms-error">
                        {view.error}
                    </span>
                ) : null}
                {ended && view.meetingId ? (
                    <MeetingMenu
                        meetingId={view.meetingId}
                        title={heading}
                        fetcher={fetcher}
                        base={base}
                        onOpenConversation={onOpenConversation}
                        onDeleted={onDeleted}
                        onRenamed={setRenamed}
                    />
                ) : null}
            </header>

            {/* The payoff, above everything. A reader who never scrolls further has what
                they recorded the meeting for. */}
            {ended ? (
                <>
                    <MeetingSummary body={body} pending={pendingNotes} onSeek={seek} />
                    <AskField
                        meetingId={view.meetingId}
                        fetcher={fetcher}
                        base={base}
                        onSeek={seek}
                    />
                </>
            ) : null}

            {ended ? (
                // Evidence, reached for. Named with its line count so the disclosure says
                // what is behind it rather than asking the reader to open it to find out.
                <button
                    type="button"
                    className="ms-card__disclosure"
                    onClick={() => setTranscriptOpen((v) => !v)}
                    aria-expanded={transcriptOpen}
                    aria-controls="ms-transcript-region"
                    data-testid="ms-transcript-toggle"
                >
                    <span aria-hidden="true">{transcriptOpen ? '▾' : '▸'}</span>
                    {' '}Transcript
                    <span className="ms-card__count">· {view.segments.length}</span>
                </button>
            ) : null}

            <section
                id="ms-transcript-region"
                aria-label={ended ? 'Transcript' : 'Live transcript'}
                aria-live={ended ? 'off' : 'polite'}
                className="ms-card__transcript"
                ref={scroller}
                onScroll={onScroll}
                // `transcriptOpen` starts true and only the ended disclosure can change it,
                // so an `ended &&` here would restate what the button already guarantees.
                hidden={!transcriptOpen}
                data-testid="ms-transcript"
            >
                {lines.length === 0 && !view.partial ? (
                    <p className="ms-card__empty" data-testid="ms-empty">
                        {view.phase === 'live'
                            ? 'Listening — nothing has been said yet.'
                            : 'Nothing was transcribed.'}
                    </p>
                ) : null}
                {lines.map((segment, index) => (
                    <div
                        key={segment.id ?? `${segment.seq ?? index}`}
                        data-segment-id={segment.id != null ? String(segment.id) : undefined}
                        data-cited={highlight != null && String(segment.id) === highlight ? 'true' : undefined}
                        className="ms-card__row"
                    >
                        <Line segment={segment} />
                    </div>
                ))}
                {view.partial ? <Line segment={{ ...view.partial }} provisional /> : null}
            </section>

            {/* Under the transcript, not beside it: the transcript is what the reader is
                following, and a strip in the margin competes with it for the same attention
                while adding a horizontal scroll on every phone. */}
            {/* Between the transcript and the slides: a chip is about what was *just* said,
                so it sits where the reader's eye already is when a new line lands. Above the
                transcript it would push the words the reader is following down the card. */}
            {onAcceptChip && onDismissChip ? (
                <ChipRow
                    chips={view.chips}
                    onAccept={onAcceptChip}
                    onDismiss={onDismissChip}
                    compact={compact}
                />
            ) : null}

            <SlideStrip slides={view.slideList} segments={view.segments} compact={compact} />

            {unseen > 0 && !stuck ? (
                <button type="button" className="ms-card__jump" onClick={jumpToBottom} data-testid="ms-jump">
                    ↓ {unseen} new line{unseen === 1 ? '' : 's'}
                </button>
            ) : null}

            {view.phase === 'ended' && onExport ? (
                <footer className="ms-card__actions">
                    {(['md', 'srt', 'json'] as const).map((fmt) => (
                        <button
                            key={fmt}
                            type="button"
                            onClick={() => onExport(fmt)}
                            data-testid={`ms-export-${fmt}`}
                        >
                            Export {fmt.toUpperCase()}
                        </button>
                    ))}
                </footer>
            ) : null}
        </div>
    );
}

export default MeetingCard;
