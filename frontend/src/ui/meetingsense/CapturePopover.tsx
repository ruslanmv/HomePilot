/**
 * The chevron (batch MS33, wave W13).
 *
 * MS29 gave the record button a `⌄` into MS5's capture popover; MS32 moved the control to the
 * header and dropped it, which quietly made advanced capture settings unreachable. This
 * restores it as a split action — **Meeting** starts, `⌄` configures — so one click still
 * starts a meeting with notes and slides on, and the people who want to change that can.
 *
 * ── What is in here, and what is deliberately not ────────────────────────────────────────
 *
 * Capture is two checkboxes. Assistant behaviour is one line that reads `Note taker ·
 * Default` and a way through to the rest.
 *
 * Note-taker is not "mode 1 of 5" — it is what MeetingSense *is*, and Participant, Presenter,
 * Coach and Practice are advanced surfaces that materially change what the assistant may do.
 * Putting five modes beside the record button would make the exception look like the rule and
 * make every user answer a question that has one right answer for almost all of them.
 *
 * The mode list only opens when somebody deliberately asks for it, and a chosen non-default
 * mode is then loud: it shows on the pill for the whole meeting, because it changes what the
 * assistant is permitted to do and that is never something to discover afterwards.
 */
import React, { useState } from 'react';
import { modeLabel, type HelperMode } from './meetingState';

export interface CaptureOptions {
    /** Meeting audio and the user's microphone. Both on is what a meeting means. */
    audio: boolean;
    mic: boolean;
    /** Keyframe capture of a shared screen. */
    slides: boolean;
    mode: HelperMode | null;
}

export const DEFAULT_CAPTURE: CaptureOptions = {
    audio: true, mic: true, slides: true, mode: null,
};

/** The advanced modes, in the order MS24 gives them, with Note-taker as the floor. */
export const MODES: Array<{ id: HelperMode | null; label: string; note: string }> = [
    { id: null, label: 'Note taker', note: 'Listens and writes notes. Says nothing.' },
    { id: 'participant', label: 'Participant', note: 'Answers when addressed by name; drafts replies for you.' },
    { id: 'presenter', label: 'Presenter', note: 'Tracks your deck and holds audience questions.' },
    { id: 'coach', label: 'Coach', note: 'Talking points from prep material you uploaded.' },
    { id: 'practice', label: 'Practice', note: 'Runs a mock interview or exam.' },
];

export interface CapturePopoverProps {
    value: CaptureOptions;
    onChange: (next: CaptureOptions) => void;
    onClose: () => void;
}

export function CapturePopover({ value, onChange, onClose }: CapturePopoverProps) {
    const [modesOpen, setModesOpen] = useState(false);

    const row = (
        key: 'audio' | 'mic' | 'slides',
        label: string,
    ) => (
        <label className="ms-cap__row" key={key}>
            <input
                type="checkbox"
                checked={value[key]}
                onChange={(event) => onChange({ ...value, [key]: event.target.checked })}
                data-testid={`ms-cap-${key}`}
            />
            <span>{label}</span>
        </label>
    );

    return (
        <div
            className="ms-cap"
            role="dialog"
            aria-label="Meeting options"
            data-testid="ms-capture-popover"
        >
            {!modesOpen ? (
                <>
                    <h4 className="ms-cap__head">Capture</h4>
                    {row('audio', 'Meeting audio')}
                    {row('mic', 'My microphone')}
                    {row('slides', 'Screen / slides')}

                    <h4 className="ms-cap__head">Assistant behaviour</h4>
                    <button
                        type="button"
                        className="ms-cap__mode"
                        onClick={() => setModesOpen(true)}
                        data-testid="ms-cap-more-modes"
                    >
                        <span>{modeLabel(value.mode) || 'Note taker'}</span>
                        {value.mode ? null : <span className="ms-cap__default">Default</span>}
                        <span aria-hidden="true">›</span>
                    </button>
                </>
            ) : (
                <>
                    <button
                        type="button"
                        className="ms-cap__back"
                        onClick={() => setModesOpen(false)}
                        data-testid="ms-cap-back"
                    >
                        <span aria-hidden="true">‹</span> Assistant behaviour
                    </button>
                    <ul className="ms-cap__modes" role="radiogroup" aria-label="Assistant behaviour">
                        {MODES.map((mode) => (
                            <li key={mode.label}>
                                <button
                                    type="button"
                                    role="radio"
                                    aria-checked={value.mode === mode.id}
                                    className="ms-cap__mode-item"
                                    onClick={() => {
                                        onChange({ ...value, mode: mode.id });
                                        setModesOpen(false);
                                    }}
                                    data-testid={`ms-cap-mode-${mode.id ?? 'note-taker'}`}
                                >
                                    <span className="ms-cap__mode-name">{mode.label}</span>
                                    <span className="ms-cap__mode-note">{mode.note}</span>
                                </button>
                            </li>
                        ))}
                    </ul>
                </>
            )}

            <button type="button" className="ms-cap__done" onClick={onClose} data-testid="ms-cap-done">
                Done
            </button>
        </div>
    );
}

export default CapturePopover;
