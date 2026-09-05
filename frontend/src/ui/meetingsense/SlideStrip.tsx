/**
 * The slides a meeting captured, and what was said while each was up (batch MS10).
 *
 * A strip of thumbnails under the transcript, and a lightbox that opens one. The lightbox is
 * the whole point of the batch: a slide on its own is a picture of a screen, and a picture of
 * a screen is not why anybody records a meeting. Joined to the words spoken while it was up,
 * it becomes the answer to "what were they saying when this chart was on?" — which is the
 * question a slide in a transcript is actually for.
 *
 * The join is :func:`segmentsDuring`, and it lives in ``meetingState`` rather than in here
 * because it is the claim this batch has to get right; a renderer is the wrong place to test
 * an interval boundary.
 *
 * **The strip is never the only route to a slide.** A caption is text in the meeting's export
 * and in the summary message, so a reader who never opens this — on a phone, in a screen
 * reader, in the Markdown export — still gets what the slide said.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
    segmentsDuring,
    slideLabel,
    speakerLabel,
    stampLabel,
    type Segment,
    type Slide,
} from './meetingState';

export interface SlideStripProps {
    slides: Slide[];
    segments: Segment[];
    /** Rendered small: a phone shows the strip and opens the lightbox full-width. */
    compact?: boolean;
}

function Lightbox({
    slides,
    segments,
    index,
    onClose,
    onMove,
}: {
    slides: Slide[];
    segments: Segment[];
    index: number;
    onClose: () => void;
    onMove: (next: number) => void;
}) {
    const slide = slides[index];

    // Escape closes and the arrows move. A lightbox that can only be dismissed by finding a
    // small × is a lightbox people close by reloading the page.
    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onClose();
            else if (event.key === 'ArrowRight' && index < slides.length - 1) onMove(index + 1);
            else if (event.key === 'ArrowLeft' && index > 0) onMove(index - 1);
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [index, slides.length, onClose, onMove]);

    if (!slide) return null;
    const spoken = segmentsDuring(slides, segments, index);

    return (
        <div
            className="ms-lightbox"
            role="dialog"
            aria-modal="true"
            aria-label={`Slide at ${stampLabel(slide.t)}`}
            data-testid="ms-lightbox"
        >
            <div className="ms-lightbox__backdrop" onClick={onClose} data-testid="ms-lightbox-backdrop" />
            <div className="ms-lightbox__body">
                <header className="ms-lightbox__head">
                    <span className="ms-lightbox__stamp">{stampLabel(slide.t)}</span>
                    <span className="ms-lightbox__index">
                        {index + 1} of {slides.length}
                    </span>
                    <button type="button" onClick={onClose} data-testid="ms-lightbox-close" aria-label="Close">
                        ×
                    </button>
                </header>

                <img className="ms-lightbox__image" src={slide.url} alt={slideLabel(slide)} />

                <p className="ms-lightbox__caption" data-testid="ms-lightbox-caption">
                    {slideLabel(slide)}
                </p>

                <section
                    className="ms-lightbox__spoken"
                    aria-label="Said while this slide was up"
                    data-testid="ms-lightbox-spoken"
                >
                    <h4>Said while this slide was up</h4>
                    {spoken.length === 0 ? (
                        // An honest empty state rather than a blank panel: nobody spoke, which
                        // is different from the join having failed.
                        <p className="ms-lightbox__silent" data-testid="ms-lightbox-silent">
                            Nothing was said while this slide was up.
                        </p>
                    ) : (
                        spoken.map((segment, at) => (
                            <p
                                className="ms-line"
                                key={segment.id ?? `${segment.seq ?? at}`}
                                data-t0={segment.t0 ?? 0}
                                data-testid="ms-lightbox-line"
                            >
                                <span className="ms-line__stamp">{stampLabel(segment.t0)}</span>{' '}
                                <span className="ms-line__speaker">{speakerLabel(segment.speaker)}</span>{' '}
                                <span className="ms-line__text">{segment.text}</span>
                            </p>
                        ))
                    )}
                </section>
            </div>
        </div>
    );
}

export function SlideStrip({ slides, segments, compact = false }: SlideStripProps) {
    const [open, setOpen] = useState<number | null>(null);
    const close = useCallback(() => setOpen(null), []);

    // Rendered as nothing rather than as an empty strip: a meeting with no slides should not
    // grow a heading announcing that it has none.
    if (!slides.length) return null;

    return (
        <section
            className="ms-slides"
            aria-label="Slides"
            data-compact={compact ? 'true' : 'false'}
            data-testid="ms-slides"
        >
            <h4 className="ms-slides__title">
                {slides.length} slide{slides.length === 1 ? '' : 's'}
            </h4>
            <ul className="ms-slides__strip">
                {slides.map((slide, index) => (
                    <li className="ms-slides__item" key={slide.id ?? `${slide.t ?? index}`}>
                        <button
                            type="button"
                            className="ms-slides__button"
                            onClick={() => setOpen(index)}
                            data-testid="ms-slide"
                            data-t={slide.t ?? 0}
                            // The accessible name carries the caption, so a screen reader gets
                            // what the slide said rather than "button, image".
                            aria-label={`${stampLabel(slide.t)} — ${slideLabel(slide)}`}
                        >
                            <img className="ms-slides__thumb" src={slide.url} alt="" />
                            <span className="ms-slides__stamp">{stampLabel(slide.t)}</span>
                            <span className="ms-slides__caption">{slideLabel(slide)}</span>
                        </button>
                    </li>
                ))}
            </ul>
            {open !== null ? (
                <Lightbox
                    slides={slides}
                    segments={segments}
                    index={open}
                    onClose={close}
                    onMove={setOpen}
                />
            ) : null}
        </section>
    );
}

export default SlideStrip;
