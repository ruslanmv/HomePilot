/**
 * The Meeting control in the header (batch MS32, wave W12).
 *
 * ── Why it moved ─────────────────────────────────────────────────────────────────────────
 *
 * MS29 mounted the record button under the composer, reasoning that a control people have to
 * go looking for is pressed after the first two minutes are gone. That was right about
 * discoverability and wrong about where it costs. Under the composer, one optional feature sat
 * directly beneath the primary input on every chat screen — with its own setup sentence — and
 * competed with the thing the product is for. Chat first. Features on demand.
 *
 * The header already holds exactly this class of control: Call is there, and Call is the
 * closest sibling a meeting has. So Meeting joins it, and the composer goes back to being a
 * composer.
 *
 * ── The three states ─────────────────────────────────────────────────────────────────────
 *
 *   idle      a 36px icon button, identical in weight to Call / Settings / New Chat
 *   starting  the same button, spinner, disabled — a press that has been received
 *   live      a pill, `● 08:42`, red, counting; the only state that is visually louder
 *
 * Only one of those is louder than its neighbours, and it is the one that must be: §2a says
 * recording state is unmissable. The pill at the top of the viewport (`RecordingPill`) still
 * carries that promise on its own; this is the second, quieter place the same truth shows,
 * where somebody's eye already goes for actions.
 *
 * ── Nothing explains itself until it is pressed ──────────────────────────────────────────
 *
 * There is no permanently disabled control and no permanent sentence. When a meeting cannot
 * start the button is live and pressing it opens a small popover that says why — see
 * `MeetingPanel.meetingBlock`. That is the whole of the difference from MS29's button, and
 * the reason `blockedReason` is still exported there unchanged: the developer-facing copy is
 * still correct, it just no longer belongs in chat.
 *
 * ── Opening Settings without a prop ──────────────────────────────────────────────────────
 *
 * The popover's `Open Settings` fires `homepilot:open-settings`, the window event `App` has
 * listened for since the offline banner needed it. A prop would have to be threaded through
 * two `ChatState` mount sites to reach here; the event already exists and already works.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Mic } from 'lucide-react';
import { useMeetingControls } from './MeetingSenseProvider';
import { LivePanel, SetupPanel, meetingBlock } from './MeetingPanel';
import { CapturePopover } from './CapturePopover';
import { elapsedLabel } from './meetingState';

export interface MeetingActionProps {
    /** Injected in tests. Defaults to the window event `App` already listens for. */
    onOpenSettings?: () => void;
}

/** The shared geometry of the header cluster. Meeting is a peer of Call, not a CTA. */
const BASE = [
    'h-9 flex items-center justify-center rounded-full border',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30 focus-visible:ring-offset-0',
    'transition-colors duration-150',
].join(' ');

const QUIET = 'bg-white/5 border-white/10 text-white/60 hover:bg-white/10 hover:text-white';
const LOUD = 'bg-red-500/10 border-red-500/30 text-red-200 hover:bg-red-500/20';

export function MeetingAction({ onOpenSettings }: MeetingActionProps) {
    const controls = useMeetingControls();
    const [open, setOpen] = useState(false);
    const [options, setOptions] = useState(false);
    const wrap = useRef<HTMLDivElement | null>(null);

    const close = useCallback(() => setOpen(false), []);

    // Escape and outside-click, both, because a popover that only one of them closes is a
    // popover somebody ends up clicking twice to dismiss.
    useEffect(() => {
        if (!open && !options) return undefined;
        const onKey = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            setOpen(false);
            setOptions(false);
        };
        const onDown = (event: MouseEvent) => {
            const node = wrap.current;
            if (node && node.contains(event.target as Node)) return;
            setOpen(false);
            setOptions(false);
        };
        document.addEventListener('keydown', onKey);
        document.addEventListener('mousedown', onDown);
        return () => {
            document.removeEventListener('keydown', onKey);
            document.removeEventListener('mousedown', onDown);
        };
    }, [open, options]);

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

    // Outside the provider, or off on this server: no control at all. A permanently dead
    // button in the header teaches people the product is broken; an absent one teaches them
    // nothing, which is correct when there is nothing to learn.
    if (!controls || !controls.status?.enabled) return null;

    const { live, starting, phase, phaseText, elapsedMs, micMuted, undoSecondsLeft } = controls;
    const block = live ? null : meetingBlock(controls.status, controls.conversationId);
    const stopping = phase === 'stopping';

    const label = live
        ? `Meeting · ${elapsedLabel(elapsedMs)}`
        : starting
            ? 'Starting meeting…'
            : 'Start meeting';

    const onClick = () => {
        if (live) {
            setOpen((v) => !v);
            return;
        }
        // No `starting` guard here. The button is `disabled` while starting and the
        // provider's `begin` refuses a second start of its own — a third copy of the same
        // rule is one that gets edited alone and then disagrees with the other two.
        if (block) {
            setOpen((v) => !v);
            return;
        }
        setOpen(false);
        setOptions(false);
        controls.begin();
    };

    // MS33. A split action: pressing Meeting starts one, pressing the chevron configures it.
    // One click still starts a meeting — the chevron is a second control, not a step in front
    // of the first — which is the whole reason MS29 refused to open a form on the main press.
    const splittable = !live && !starting && !block;

    return (
        <div className="relative" ref={wrap} data-testid="ms-action">
            <button
                type="button"
                onClick={onClick}
                disabled={starting}
                title={label}
                aria-label={label}
                aria-expanded={open}
                aria-haspopup={live || block ? 'dialog' : undefined}
                data-live={live ? 'true' : 'false'}
                data-state={live ? 'live' : starting ? 'starting' : 'idle'}
                data-testid="ms-action-button"
                className={[
                    BASE,
                    live ? LOUD : QUIET,
                    // The live state is the only one that earns extra width: it carries a
                    // number somebody reads. Everything else stays a 36px circle so the
                    // header keeps one rhythm.
                    live ? 'gap-2 px-3' : 'w-9',
                    starting ? 'opacity-60 cursor-default' : '',
                ].join(' ')}
            >
                {live ? (
                    <>
                        <span
                            aria-hidden="true"
                            className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0"
                        />
                        <span className="text-[12px] tabular-nums" data-testid="ms-action-elapsed">
                            {elapsedLabel(elapsedMs)}
                        </span>
                    </>
                ) : starting ? (
                    <span
                        aria-hidden="true"
                        data-testid="ms-action-spinner"
                        className="w-3.5 h-3.5 rounded-full border-2 border-white/20 border-t-white/70 animate-spin"
                    />
                ) : (
                    <Mic size={16} aria-hidden="true" />
                )}
            </button>

            {splittable ? (
                <button
                    type="button"
                    onClick={() => setOptions((v) => !v)}
                    aria-expanded={options}
                    aria-haspopup="dialog"
                    aria-label="Meeting options"
                    title="What gets captured"
                    data-testid="ms-action-options"
                    className={[
                        'absolute -right-1 -bottom-1 w-4 h-4 flex items-center justify-center',
                        'rounded-full bg-[#0d0d0d] border border-white/15 text-[9px] text-white/50',
                        'hover:text-white hover:border-white/30',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30',
                        'transition-colors duration-150',
                    ].join(' ')}
                >
                    <span aria-hidden="true">⌄</span>
                </button>
            ) : null}

            {options && splittable ? (
                <div
                    className={[
                        'absolute right-0 top-11 z-50 w-64 p-3.5',
                        'rounded-2xl bg-[#0d0d0d] border border-white/10',
                        'shadow-[0_12px_40px_-12px_rgba(0,0,0,0.9)]',
                    ].join(' ')}
                    data-testid="ms-action-capture"
                >
                    <CapturePopover
                        value={controls.capture}
                        onChange={controls.setCapture}
                        onClose={() => setOptions(false)}
                    />
                </div>
            ) : null}

            {open && (live || block) ? (
                <div
                    role="dialog"
                    aria-label={live ? 'Meeting' : (block as NonNullable<typeof block>).title}
                    data-testid="ms-action-popover"
                    className={[
                        'absolute right-0 top-11 z-50 w-64 p-3.5',
                        'rounded-2xl bg-[#0d0d0d] border border-white/10',
                        'shadow-[0_12px_40px_-12px_rgba(0,0,0,0.9)]',
                    ].join(' ')}
                >
                    {live ? (
                        <LivePanel
                            elapsedMs={elapsedMs}
                            phase={phaseText}
                            micMuted={micMuted}
                            stopping={stopping}
                            undoSecondsLeft={undoSecondsLeft}
                            onMute={controls.mute}
                            onEnd={() => controls.end()}
                            onUndo={() => controls.undo()}
                        />
                    ) : (
                        <SetupPanel
                            block={block as NonNullable<typeof block>}
                            onOpenSettings={openSettings}
                            onClose={close}
                        />
                    )}
                </div>
            ) : null}

            {controls.error ? (
                // A start that failed is news, and it is short-lived. It rides under the
                // control rather than in chat, and it is the only text this component ever
                // puts on screen without a press.
                <span
                    role="status"
                    data-testid="ms-action-error"
                    className="absolute right-0 top-11 z-40 w-64 px-3 py-2 rounded-xl bg-[#0d0d0d] border border-red-500/25 text-[11px] text-red-200"
                >
                    {controls.error}
                </span>
            ) : null}
        </div>
    );
}

export default MeetingAction;
