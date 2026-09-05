/**
 * The record button (batch MS29, wave W11).
 *
 * **One click starts a meeting.** No dialog, no configuration, no "which of these four things
 * would you like captured" — notes and slides are on, because they are what the feature is for,
 * and the people who want to change that can. A record button that opens a form is a record
 * button pressed after the first two minutes of the meeting are gone.
 *
 * The options live behind a chevron, and the chevron re-uses `entryPoint`'s popover — the one
 * MS5 already built and tested, attached to the 👁 button. Two ways in, one popover, because
 * two popovers that drift is how a product ends up with two answers to "is slide capture on".
 *
 * **The button says what it will do before it does it.** Disabled states name their cause and
 * their fix: no conversation, no speech provider, feature off. A greyed control with no
 * explanation is the failure mode MS5 was written to prevent and this keeps that promise at
 * the one place most people will meet the feature.
 */
import React from 'react';
import { useMeetingControls } from './MeetingSenseProvider';
import type { MeetingSenseStatus } from './entryPoint';

export interface MeetingButtonProps {
    /** Opens MS5's popover on the 👁 button. Absent hides the chevron rather than breaking it. */
    onOptions?: () => void;
    compact?: boolean;
}

/** Why the button cannot be pressed, in the user's terms, or `null` when it can. */
export function blockedReason(
    status: MeetingSenseStatus | null,
    conversationId: string | null,
): string | null {
    if (!status?.enabled) return 'MeetingSense is turned off on this server.';
    if (!conversationId) return 'Start or open a conversation first — the meeting lands in it.';
    if (status.stt && status.stt.available === false) {
        // The hint comes from the server, which knows which provider is missing and what to
        // set. Paraphrasing it here would be a second, staler copy of that answer.
        return status.stt.hint || 'No speech provider is configured, so nothing can be transcribed.';
    }
    return null;
}

export function MeetingButton({ onOptions, compact = false }: MeetingButtonProps) {
    const controls = useMeetingControls();

    // Outside the provider, or the feature is off on this server: no button at all, rather
    // than a disabled one. A permanently dead control teaches people the product is broken;
    // an absent one teaches them nothing, which is correct when there is nothing to learn.
    if (!controls || !controls.status?.enabled) return null;

    const blocked = blockedReason(controls.status, controls.conversationId);
    const { live, starting } = controls;
    const label = live ? 'Stop meeting' : starting ? 'Starting…' : 'Start meeting';

    return (
        <div className="ms-record" data-testid="ms-record">
            <button
                type="button"
                onClick={live ? controls.end : controls.begin}
                disabled={Boolean(blocked) || starting}
                title={blocked || label}
                aria-label={label}
                data-live={live ? 'true' : 'false'}
                data-testid="ms-record-button"
                className={
                    live
                        ? 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs border border-red-500/40 bg-red-500/10 text-red-200 hover:bg-red-500/20 transition-colors'
                        : 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs border border-white/10 bg-white/[0.03] text-white/70 hover:text-white hover:border-white/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed'
                }
            >
                <span aria-hidden="true">{live ? '■' : '🎙'}</span>
                {compact ? null : <span>{label}</span>}
            </button>

            {onOptions && !live ? (
                <button
                    type="button"
                    onClick={onOptions}
                    aria-label="Meeting options"
                    title="What gets captured"
                    data-testid="ms-record-options"
                    className="ml-1 px-1.5 py-1.5 rounded-lg text-xs text-white/40 hover:text-white/80 transition-colors"
                >
                    <span aria-hidden="true">⌄</span>
                </button>
            ) : null}

            {blocked ? (
                // Named, not greyed. The one thing a disabled control must never do is stay
                // silent about why.
                <span className="ml-2 text-[11px] text-white/40" data-testid="ms-record-blocked">
                    {blocked}
                </span>
            ) : null}

            {controls.error ? (
                <span className="ml-2 text-[11px] text-red-300" role="status" data-testid="ms-record-error">
                    {controls.error}
                </span>
            ) : null}
        </div>
    );
}

export default MeetingButton;
