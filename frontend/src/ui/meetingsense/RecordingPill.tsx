/**
 * The recording pill (batch MS6, §2a "recording state is unmissable").
 *
 * A recorder that can be forgotten about is a recorder that records something it should not.
 * So the pill is visible at every scroll position, states the elapsed time, the speech
 * provider and what is being captured, and carries a live level meter — the meter is the part
 * that answers "is it actually hearing me", which a static red dot never does.
 *
 * It is a `role="status"` with `aria-live="polite"`: a screen-reader user has no red dot, and
 * "recording" is the one thing they must not have to go looking for.
 *
 * ── MS33: what rests and what is one press away ──────────────────────────────────────────
 *
 * The pill used to carry `whisper · system+mic` permanently. That is the answer to a question
 * people ask once, sitting beside the answer to the question they ask every thirty seconds.
 * At rest it now reads `🔴 Recording · 12:43 ▂▅▃▆` — state, time, and the meter, which is the
 * part that actually answers "is it hearing me".
 *
 * The technical detail is behind a **click, not a hover**. Hover does not exist on a phone or
 * a tablet, and it is not reachable from a keyboard, so a hover-only disclosure would hide
 * the audio configuration from exactly the people most likely to have it wrong.
 *
 * Mute and Stop move inside the same disclosure. They are one press further away than before,
 * which is right for Mute and does not matter for Stop, because Stop is a ten-second
 * countdown rather than an ending — and while it counts, the pill says so in words.
 */
import React, { useState } from 'react';
import {
    elapsedLabel,
    meterLevel,
    modeLabel,
    phaseLabel,
    type MeetingView,
} from './meetingState';

export interface RecordingPillProps {
    view: MeetingView;
    onMute?: (muted: boolean) => void;
    onStop?: () => void;
    onUndo?: () => void;
    undoSecondsLeft?: number | null;
}

export function RecordingPill({ view, onMute, onStop, onUndo, undoSecondsLeft }: RecordingPillProps) {
    const [open, setOpen] = useState(false);
    if (view.phase === 'idle') return null;

    const stopping = view.phase === 'stopping';
    const level = meterLevel(view.levels);
    // MS27. A mode changes what the recording is *for*, so it belongs on the unmissable thing
    // rather than in a panel. Note-taker is unlabelled — a badge that is always there is one
    // nobody reads, and that would cost it its meaning in the modes where it matters.
    const mode = modeLabel(view.mode);

    return (
        <div
            className="ms-pill"
            data-phase={view.phase}
            role="status"
            aria-live="polite"
            data-testid="ms-pill"
        >
            <span className="ms-pill__dot" aria-hidden="true" />
            <span className="ms-pill__phase">
                {stopping && undoSecondsLeft != null
                    // The exact ambiguity Undo exists to remove: for these ten seconds the
                    // meeting is still being captured, so nothing said now is lost. A bare
                    // "stopping…" invites people to stop talking, which is the one outcome
                    // the countdown was built to prevent.
                    ? `Stopping in ${undoSecondsLeft}s · still recording`
                    : phaseLabel(view)}
            </span>
            {mode ? (
                // Inside the `role="status"` region on purpose: a screen-reader user has no
                // badge to glance at, and "the assistant is going to speak into this call" is
                // not something they should have to go looking for.
                <span className="ms-pill__mode" data-mode={view.mode} data-testid="ms-mode">
                    {mode}
                </span>
            ) : null}
            {view.queued > 0 ? (
                <span className="ms-pill__queued" data-testid="ms-queued">
                    {view.queued} question{view.queued === 1 ? '' : 's'} waiting
                </span>
            ) : null}
            <span className="ms-pill__time" data-testid="ms-elapsed">
                {elapsedLabel(view.elapsedMs)}
            </span>

            {/* The meter answers "is it hearing me", which a static indicator cannot. Hidden
                from assistive tech: it carries no information the phase line does not. */}
            <span className="ms-pill__meter" aria-hidden="true" data-testid="ms-meter">
                <span className="ms-pill__meter-fill" style={{ width: `${Math.round(level * 100)}%` }} />
            </span>

            {stopping ? (
                // Undo stays on the pill's face. Ten seconds is not long enough to go looking
                // for it behind a disclosure.
                <button type="button" className="ms-pill__undo" onClick={onUndo} data-testid="ms-undo">
                    Undo{undoSecondsLeft != null ? ` · ${undoSecondsLeft}s` : ''}
                </button>
            ) : (
                <button
                    type="button"
                    className="ms-pill__more"
                    onClick={() => setOpen((v) => !v)}
                    aria-expanded={open}
                    aria-controls="ms-pill-details"
                    aria-label={open ? 'Hide recording details' : 'Show recording details'}
                    data-testid="ms-pill-toggle"
                >
                    <span aria-hidden="true">{open ? '⌃' : '⌄'}</span>
                </button>
            )}

            {open && !stopping ? (
                <div className="ms-pill__details" id="ms-pill-details" data-testid="ms-pill-details">
                    {view.audioMode ? (
                        <span className="ms-pill__fact" data-testid="ms-capture">Audio: {view.audioMode}</span>
                    ) : null}
                    {view.provider ? (
                        <span className="ms-pill__fact" data-testid="ms-pill-provider">
                            Transcription: {view.provider}
                        </span>
                    ) : null}
                    <span className="ms-pill__fact" data-testid="ms-pill-slides">
                        Slides: {view.slides > 0 ? `on · ${view.slides}` : 'on'}
                    </span>
                    <button
                        type="button"
                        className="ms-pill__mute"
                        aria-pressed={view.micMuted}
                        onClick={() => onMute?.(!view.micMuted)}
                        data-testid="ms-mute"
                    >
                        {view.micMuted ? 'Unmute my mic' : 'Mute my mic'}
                    </button>
                    <button type="button" className="ms-pill__stop" onClick={onStop} data-testid="ms-stop">
                        Stop
                    </button>
                </div>
            ) : null}
        </div>
    );
}

export default RecordingPill;
