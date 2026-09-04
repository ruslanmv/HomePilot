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
    onExport?: (fmt: 'md' | 'srt' | 'json') => void;
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

    return (
        <div className="ms-card" data-phase={view.phase} data-compact={compact ? 'true' : 'false'} data-testid="ms-card">
            <header className="ms-card__head">
                <h3 className="ms-card__title">Meeting</h3>
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
            </header>

            <section
                aria-label="Live transcript"
                aria-live="polite"
                className="ms-card__transcript"
                ref={scroller}
                onScroll={onScroll}
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
                    <Line key={segment.id ?? `${segment.seq ?? index}`} segment={segment} />
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
