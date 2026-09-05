/**
 * The offers a meeting makes, and the button that acts on one (batch MS25).
 *
 * A chip appears while somebody is still talking, because of what they just said. That is what
 * makes it useful and it is also what makes it expensive: a chip that is wrong is not a bad
 * summary the reader scrolls past, it is the assistant visibly misunderstanding the room in
 * front of the room. The triggers are deterministic and live server-side in `chips.py`, with
 * their negatives written down; this file only renders what arrived.
 *
 * **Rendering runs nothing.** A chip carries a `proposal` — "add to calendar" — and the
 * proposal is a description until somebody presses the button. That is ask-before-acting in
 * the only form that means anything: the ask happens *before* the act, not alongside it.
 *
 * **Dismissal is local and is not a deletion.** One reader saying "not interested" is not a
 * fact about the meeting, so nothing is sent and nothing is removed; the chip stops being
 * shown on this card and the meeting's record is untouched.
 */
import React, { useCallback } from 'react';
import { chipLabel, visibleChips, type Chip } from './meetingState';

export interface ChipRowProps {
    chips: Chip[];
    /** Accept a chip's proposal. Takes an **id**: the card never sends a chip body back, so
     *  nothing on this page can rewrite what the user thought they were agreeing to. */
    onAccept: (id: string) => void;
    onDismiss: (id: string) => void;
    /** Rendered small — a phone shows one line per chip. */
    compact?: boolean;
}

function ChipResult({ chip }: { chip: Chip }) {
    if (chip.pending) {
        return (
            <span className="ms-chip__result" data-state="pending" role="status">
                Working…
            </span>
        );
    }
    if (!chip.result) return null;
    if (chip.result.ok) {
        return (
            <span className="ms-chip__result" data-state="done" role="status">
                Done{chip.result.tool ? ` · ${chip.result.tool}` : ''}
            </span>
        );
    }
    // The server's own words, not a paraphrase: it knows whether this install has no tools, no
    // matching tool, or a tool this meeting has not approved, and those need different fixes.
    return (
        <span className="ms-chip__result" data-state="failed" role="status">
            {chip.result.reason || 'That did not run'}
        </span>
    );
}

export function ChipRow({ chips, onAccept, onDismiss, compact = false }: ChipRowProps) {
    const shown = visibleChips(chips);

    const accept = useCallback(
        (id: string) => () => onAccept(id),
        [onAccept],
    );
    const dismiss = useCallback(
        (id: string) => () => onDismiss(id),
        [onDismiss],
    );

    if (!shown.length) return null;

    return (
        <div
            className={`ms-chips${compact ? ' ms-chips--compact' : ''}`}
            data-testid="ms-chips"
            // Polite, never assertive: a chip is an offer, and an offer that interrupts a
            // screen reader mid-sentence is the audible version of the mistake this whole
            // batch is arranged around avoiding.
            aria-live="polite"
            aria-label="Suggestions from this meeting"
        >
            {shown.map((chip) => (
                <div className="ms-chip" key={chip.id} data-kind={chip.kind} data-testid="ms-chip">
                    <span className="ms-chip__badge">{chipLabel(chip)}</span>
                    <span className="ms-chip__text" title={chip.text}>
                        {chip.text}
                    </span>
                    <ChipResult chip={chip} />
                    {chip.proposal && !chip.result && !chip.pending ? (
                        <button
                            type="button"
                            className="ms-chip__accept"
                            onClick={accept(chip.id)}
                            data-testid={`ms-chip-accept-${chip.id}`}
                        >
                            {chip.proposal.label}
                        </button>
                    ) : null}
                    <button
                        type="button"
                        className="ms-chip__dismiss"
                        onClick={dismiss(chip.id)}
                        aria-label={`Dismiss: ${chip.text}`}
                        data-testid={`ms-chip-dismiss-${chip.id}`}
                    >
                        ×
                    </button>
                </div>
            ))}
        </div>
    );
}

export default ChipRow;
