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
    /**
     * What people call *you* in this meeting (MS26's `names`).
     *
     * This is what turns "somebody just asked you something" from a guess into a fact. The
     * detector will not infer it: with no names declared it has only second person to go on,
     * which is the narrow behaviour and the right default — the failure mode of guessing is
     * the assistant reacting to somebody else's name in front of them.
     */
    myNames: string;
    /** What the assistant answers to (MS26's `assistant_names`). Empty means it never does. */
    assistantName: string;
    /**
     * What the meeting's own document should be when it ends (MS34).
     *
     * Asked here rather than at the end because the moment a meeting stops is the moment the
     * user is least willing to answer a dialog — they want the recap, not a form — and
     * because the answer is usually the same every week. It is only a default: the recap
     * screen can rewrite the document in any other shape, and keeps both.
     */
    summaryStyle: string;
    summaryLength: string;
    /** LLM target used to write/rewrite the end-of-meeting document. */
    summaryProvider: string;
    summaryModel: string;
    summaryBaseUrl: string;
    /** LLM target used by the private meeting Q&A / conversation lane. */
    conversationProvider: string;
    conversationModel: string;
    conversationBaseUrl: string;
    /**
     * Material attached to this session, for the assistant to answer from (MS34).
     *
     * The agenda, the brief, last week's minutes — context the user has and the transcript
     * does not. Without it, "what were we supposed to cover?" is answered from the meeting
     * alone, which is the same shape of failure as answering from the general chat model:
     * the material exists, the user has it open, and the assistant never sees it.
     *
     * Stored on the meeting as MS27's prep artifact, which is the mechanism that already
     * exists for exactly this and is already scoped to one meeting.
     */
    context: string;
}

export const DEFAULT_CAPTURE: CaptureOptions = {
    audio: true, mic: true, slides: true, mode: null, myNames: '', assistantName: '',
    summaryStyle: 'minutes', summaryLength: 'standard',
    summaryProvider: '', summaryModel: '', summaryBaseUrl: '',
    conversationProvider: '', conversationModel: '', conversationBaseUrl: '',
    context: '',
};

/** Split a comma-separated name field into the list the wire expects. */
export function parseNames(value: string): string[] {
    return String(value || '')
        .split(',')
        .map((name) => name.trim())
        .filter(Boolean);
}

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
