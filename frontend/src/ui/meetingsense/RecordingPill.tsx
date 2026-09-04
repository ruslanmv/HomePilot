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
 */
import React from 'react';
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
    if (view.phase === 'idle') return null;

    const stopping = view.phase === 'stopping';
    const level = meterLevel(view.levels);
    const capture = [view.provider, view.audioMode].filter(Boolean).join(' · ');
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
            <span className="ms-pill__phase">{phaseLabel(view)}</span>
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

            {capture ? (
                <span className="ms-pill__capture" data-testid="ms-capture">
                    {capture}
                </span>
            ) : null}

            {stopping ? (
                <button type="button" className="ms-pill__undo" onClick={onUndo} data-testid="ms-undo">
                    {/* Still recording while this is on screen — see MeetingCard. Undoing must
                        not leave a ten-second hole in the middle of the meeting. */}
                    Undo{undoSecondsLeft != null ? ` · ${undoSecondsLeft}s` : ''}
                </button>
            ) : (
                <>
                    <button
                        type="button"
                        className="ms-pill__mute"
                        aria-pressed={view.micMuted}
                        onClick={() => onMute?.(!view.micMuted)}
                        data-testid="ms-mute"
                    >
                        {view.micMuted ? 'Unmute' : 'Mute'}
                    </button>
                    <button type="button" className="ms-pill__stop" onClick={onStop} data-testid="ms-stop">
                        Stop
                    </button>
                </>
            )}
        </div>
    );
}

export default RecordingPill;
