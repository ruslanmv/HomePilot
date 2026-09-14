/**
 * Starting a meeting from the composer's `+` menu.
 *
 * ── A second presentation, not a second implementation ───────────────────────────────────
 *
 * Everything that decides what a meeting does still lives in `MeetingSenseProvider`:
 * `begin()`, `end()`, the phase machine, the capture options, whether the feature exists on
 * this server at all. `MeetingAction` is one presentation of that state and this is another,
 * and they read the same `useMeetingControls()`. A meeting started from either is the same
 * meeting, visible to both, because neither of them owns anything.
 *
 * The temptation is to call `controls.begin()` from a menu row and be done. That would be
 * wrong in exactly the cases the header button already handles:
 *
 *   - **blocked** — MeetingSense off, no speech-to-text, no permission. Pressing must explain
 *     why (`meetingBlock`), not fail silently or start something that cannot work.
 *   - **starting** — a press already received. A second `begin()` is refused by the provider,
 *     but offering it invites the click.
 *   - **live** — there is nothing to start. The row becomes the meeting's status and its way
 *     back to the controls.
 *
 * So this reuses `meetingBlock`, `SetupPanel` and `LivePanel` unchanged rather than
 * reimplementing the states around them.
 *
 * ── Why the live row exists here at all ──────────────────────────────────────────────────
 *
 * §2a's promise is that recording state is unmissable, and `RecordingPill` keeps that promise
 * on its own at the top of the viewport — removing Meeting from the header does not hide an
 * active meeting. This row is the quieter second place the same truth shows, in the menu
 * somebody opens when they are thinking about meetings. A menu that said "Start a meeting"
 * while one was running would be the only part of the interface disagreeing with the rest.
 */
import React, { useCallback, useState } from 'react';
import { Users } from 'lucide-react';
import { useMeetingControls } from './MeetingSenseProvider';
import { LivePanel, SetupPanel, meetingBlock } from './MeetingPanel';
import { elapsedLabel } from './meetingState';
import { MenuItem } from '../components/ComposerPlusMenu';

export interface MeetingMenuItemProps {
    /** Close the surrounding menu — called when the press has been fully handled. */
    onDone: () => void;
    /** Injected in tests. Defaults to the window event `App` already listens for. */
    onOpenSettings?: () => void;
}

export function MeetingMenuItem({ onDone, onOpenSettings }: MeetingMenuItemProps) {
    const controls = useMeetingControls();
    // A panel shown *instead of* the row, inside the same menu: the press was received and
    // has something to say, and closing the menu to say it elsewhere loses the connection
    // between the two.
    const [panel, setPanel] = useState<'none' | 'live' | 'blocked'>('none');

    const openSettings = useCallback(() => {
        if (onOpenSettings) {
            onOpenSettings();
            return;
        }
        try {
            window.dispatchEvent(new CustomEvent('homepilot:open-settings'));
        } catch {
            // A settings shortcut failing is never worth an error in chat.
        }
    }, [onOpenSettings]);

    // Outside the provider, or off on this server: no row at all. Same rule the header button
    // kept — an absent control teaches nothing, which is correct when there is nothing to
    // learn, and a permanently dead one teaches that the product is broken.
    if (!controls || !controls.status?.enabled) return null;

    const { live, starting, phase, phaseText, elapsedMs, micMuted, undoSecondsLeft } = controls;
    const block = live ? null : meetingBlock(controls.status, controls.conversationId);
    const stopping = phase === 'stopping';

    if (panel === 'live' && live) {
        return (
            <div className="px-1.5 py-1" data-testid="ms-menu-live-panel">
                <LivePanel
                    elapsedMs={elapsedMs}
                    phase={phaseText}
                    micMuted={micMuted}
                    stopping={stopping}
                    undoSecondsLeft={undoSecondsLeft}
                    onMute={controls.mute}
                    onEnd={() => { controls.end(); onDone(); }}
                    onUndo={() => controls.undo()}
                />
            </div>
        );
    }

    if (panel === 'blocked' && block) {
        return (
            <div className="px-1.5 py-1" data-testid="ms-menu-blocked-panel">
                <SetupPanel
                    block={block}
                    onOpenSettings={() => { openSettings(); onDone(); }}
                    onClose={() => setPanel('none')}
                />
                {/*
                  `SetupPanel` has no dismiss control of its own — in the header it lived in a
                  popover that an outside click closed, and its only button is the optional
                  "Open Settings". Inside a menu that leaves the reader holding an explanation
                  with no way back to the rest of it, and on the blocks where `settings` is
                  false ("open a conversation first") no button at all. Escape still closes the
                  whole menu, but the thing they wanted was the menu.
                */}
                <button
                    type="button"
                    onClick={() => setPanel('none')}
                    data-testid="ms-menu-back"
                    className="mt-2 text-[11px] text-white/40 hover:text-white/75 transition-colors"
                >
                    ← Back
                </button>
            </div>
        );
    }

    if (live) {
        return (
            <MenuItem
                icon={<span aria-hidden="true" className="block w-2 h-2 rounded-full bg-red-400" />}
                label={`Meeting in progress · ${elapsedLabel(elapsedMs)}`}
                hint="Mute, or end and write the recap"
                tone="live"
                testId="ms-menu-live"
                onClick={() => setPanel('live')}
            />
        );
    }

    if (starting) {
        // Shown, not hidden: the press was received and the wait is the feedback. Hiding the
        // row here would read as the click having done nothing.
        return (
            <MenuItem
                icon={(
                    <span
                        aria-hidden="true"
                        className="block w-3.5 h-3.5 rounded-full border-2 border-white/20 border-t-white/70 animate-spin"
                    />
                )}
                label="Starting meeting…"
                testId="ms-menu-starting"
                onClick={() => undefined}
            />
        );
    }

    return (
        <MenuItem
            icon={<Users size={16} />}
            label="Start a meeting"
            hint="Transcribe and take notes from this call"
            testId="ms-menu-start"
            onClick={() => {
                // Blocked is explained, never started. `meetingBlock` is the same copy the
                // header button used, so the two surfaces cannot drift into giving different
                // reasons for the same refusal.
                if (block) {
                    setPanel('blocked');
                    return;
                }
                controls.begin();
                onDone();
            }}
        />
    );
}

export default MeetingMenuItem;
