/**
 * The composer's `+` menu — where input sources and session tools live.
 *
 * ── Why one menu, and why here ───────────────────────────────────────────────────────────
 *
 * The composer row now says three different things in three places, and keeping them apart is
 * the point:
 *
 *     [+]  What do you want to know?          [ Fast ▾ ]  [🎤]
 *      │                                          │        │
 *      │                                          │        └── how the message is submitted
 *      │                                          └─────────── how HomePilot should answer
 *      └────────────────────────────────────────────────────── what it should look at
 *
 * `+` collects everything in that last category: a file, a screenshot, a live screen, a
 * meeting. Before this they were scattered — the paperclip sat in the composer, Meeting sat in
 * the header beside Call, and screen sharing was a floating blue button the page mounted for
 * itself. Three entry points for one idea ("give HomePilot something to look at"), each in a
 * different place, none of them findable from the others.
 *
 * **It replaces the paperclip rather than joining it.** A `+` next to a 📎 is two buttons for
 * the same intent, and the reader has to work out which one is the superset. The first item in
 * the menu fires the same `fileInputRef.current?.click()` the paperclip always did, so the
 * upload path itself is untouched.
 *
 * ── It opens upward ──────────────────────────────────────────────────────────────────────
 *
 * The composer sits at the bottom of the viewport, so a menu anchored below it would open off
 * screen. `bottom-full` and a small gap, not a computed position: the anchor is a fixed-size
 * button in a fixed-height row, so there is nothing to measure.
 *
 * ── Items decide for themselves whether they exist ───────────────────────────────────────
 *
 * The meeting entry renders nothing when MeetingSense is off, and screen sharing renders
 * nothing where the browser cannot share — rather than appearing disabled. A permanently dead
 * row teaches people the product is broken; an absent one teaches them nothing, which is the
 * correct lesson when there is nothing to learn. That means the menu's own length is not known
 * here, which is why it has no fixed height.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, MonitorUp, Paperclip, Plus, Square } from 'lucide-react';
import { MeetingMenuItem } from '../meetingsense/MeetingMenuItem';

export interface ComposerPlusMenuProps {
    /** Opens the composer's existing file picker. The same call the paperclip made. */
    onAddFile: () => void;
    /** One-shot capture, attached to the message. Absent when the platform cannot. */
    onScreenshot?: () => void;
}

interface ScreenSenseApi {
    enable?: () => Promise<unknown>;
    stop?: () => void;
    mode?: string;
    enabled?: boolean;
}

function screenSense(): ScreenSenseApi | null {
    return (globalThis as unknown as { hpScreenSense?: ScreenSenseApi }).hpScreenSense || null;
}

/**
 * One row. Extracted because there are four of them and the only thing that varies is the
 * icon, the words and the handler — inlining that four times is where rows drift apart.
 */
export function MenuItem({
    icon,
    label,
    hint,
    onClick,
    tone = 'normal',
    testId,
}: {
    icon: React.ReactNode;
    label: string;
    hint?: string;
    onClick: () => void;
    tone?: 'normal' | 'live';
    testId?: string;
}) {
    return (
        <button
            type="button"
            role="menuitem"
            data-testid={testId}
            onClick={onClick}
            className={[
                'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left',
                'transition-colors duration-100',
                tone === 'live'
                    ? 'text-red-200 hover:bg-red-500/10'
                    : 'text-white/80 hover:bg-white/[0.07]',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/25',
            ].join(' ')}
        >
            <span className="shrink-0 text-white/45" aria-hidden="true">{icon}</span>
            <span className="min-w-0 flex-1">
                <span className="block text-[13px] leading-5">{label}</span>
                {hint ? <span className="block text-[11px] leading-4 text-white/35">{hint}</span> : null}
            </span>
        </button>
    );
}

/**
 * "● Screen sharing — Stop", above the composer, while a share is live.
 *
 * The floating blue button this replaces was doing two jobs: it was the way in, and it was the
 * only sign that a share was running. Removing it without replacing the second job would take
 * away a privacy indicator, which is not a tidy-up — so the state stays visible, just at the
 * weight it deserves: one small line where the user is already looking, rather than a circle
 * parked over the conversation.
 *
 * **It polls, because ScreenSense emits nothing.** A share ends in ways no React tree
 * observes — the browser's own "Stop sharing" bar, a shared window closing, a stream going
 * inactive — and the one state that must never be wrong is claiming a share is live after it
 * has stopped. Reading a boolean off an object every second and a half costs nothing and
 * cannot go stale; subscribing to an event that does not exist would have meant adding one to
 * the engine, which this change deliberately does not touch.
 */
export function ScreenShareStatus() {
    const [sharing, setSharing] = useState(false);

    useEffect(() => {
        const read = () => {
            const api = screenSense();
            setSharing(Boolean(api && api.mode === 'browser' && api.enabled));
        };
        read();
        const timer = window.setInterval(read, 1500);
        return () => window.clearInterval(timer);
    }, []);

    if (!sharing) return null;

    return (
        <div className="flex justify-center pb-1.5" data-testid="screen-share-status">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] text-white/55">
                <span aria-hidden="true" className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                <span>Screen sharing</span>
                <button
                    type="button"
                    data-testid="screen-share-stop"
                    onClick={() => {
                        screenSense()?.stop?.();
                        setSharing(false);
                    }}
                    className="text-white/45 hover:text-white underline underline-offset-2 transition-colors"
                >
                    Stop
                </button>
            </div>
        </div>
    );
}

export function ComposerPlusMenu({ onAddFile, onScreenshot }: ComposerPlusMenuProps) {
    const [open, setOpen] = useState(false);
    const [sharing, setSharing] = useState(false);
    const wrap = useRef<HTMLDivElement | null>(null);

    const close = useCallback(() => setOpen(false), []);

    // Escape and outside-click, both. A menu only one of them closes is a menu somebody ends
    // up clicking twice to dismiss.
    useEffect(() => {
        if (!open) return undefined;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') setOpen(false);
        };
        const onDown = (event: MouseEvent) => {
            const node = wrap.current;
            if (node && node.contains(event.target as Node)) return;
            setOpen(false);
        };
        document.addEventListener('keydown', onKey);
        document.addEventListener('mousedown', onDown);
        return () => {
            document.removeEventListener('keydown', onKey);
            document.removeEventListener('mousedown', onDown);
        };
    }, [open]);

    /*
     * Believe the engine, not this component's memory of it.
     *
     * A share ends in ways nothing here observes: the browser's own "Stop sharing" bar, a
     * window closing, a stream going inactive. ScreenSense already handles all of those and
     * already exposes the truth through `enabled`, so the menu reads it each time it opens
     * instead of keeping a flag that can be wrong in the one direction that matters — claiming
     * a share is live when it has stopped.
     */
    useEffect(() => {
        if (!open) return;
        const api = screenSense();
        setSharing(Boolean(api && api.mode === 'browser' && api.enabled));
    }, [open]);

    const api = screenSense();
    // Desktop mode captures without a persistent share, and upload mode has no share to start.
    // Only the browser has an ongoing session to begin and end, so only there is this a row.
    const canShare = Boolean(api && api.mode === 'browser' && typeof api.enable === 'function');

    const toggleShare = useCallback(async () => {
        const current = screenSense();
        setOpen(false);
        if (!current) return;
        if (current.mode === 'browser' && current.enabled) {
            current.stop?.();
            setSharing(false);
            return;
        }
        try {
            await current.enable?.();
        } catch {
            // A declined picker is an answer, not a failure — ScreenSense falls back on its own.
        }
        setSharing(Boolean(screenSense()?.enabled));
    }, []);

    return (
        <div className="relative" ref={wrap} data-testid="composer-plus">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-label="Add"
                aria-expanded={open}
                aria-haspopup="menu"
                title="Add files, screen or a meeting"
                data-testid="composer-plus-button"
                className={[
                    'h-10 w-10 rounded-full grid place-items-center transition-colors',
                    open ? 'bg-white/10 text-white' : 'text-white/50 hover:text-white hover:bg-white/5',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/25',
                ].join(' ')}
            >
                <Plus size={18} />
            </button>

            {open ? (
                <div
                    role="menu"
                    aria-label="Add to this message"
                    data-testid="composer-plus-menu"
                    className={[
                        // Upward: the composer is at the bottom of the viewport.
                        'absolute bottom-full left-0 mb-2 z-50 w-64 p-1.5',
                        'rounded-2xl bg-[#0d0d0d] border border-white/10',
                        'shadow-[0_12px_40px_-12px_rgba(0,0,0,0.9)]',
                    ].join(' ')}
                >
                    <MenuItem
                        icon={<Paperclip size={16} />}
                        label="Add files or photos"
                        testId="composer-plus-file"
                        onClick={() => { setOpen(false); onAddFile(); }}
                    />
                    {onScreenshot ? (
                        <MenuItem
                            icon={<Camera size={16} />}
                            label="Take a screenshot"
                            hint="One capture, attached to this message"
                            testId="composer-plus-screenshot"
                            onClick={() => { setOpen(false); onScreenshot(); }}
                        />
                    ) : null}
                    {canShare ? (
                        /*
                         * Deliberately a different row from the screenshot above, though the
                         * two are close technically. A screenshot is one image attached to one
                         * message; a share is an ongoing permission that lets HomePilot keep
                         * looking. Collapsing them would hide the privacy difference, which is
                         * the half that matters.
                         */
                        sharing ? (
                            <MenuItem
                                icon={<Square size={16} />}
                                label="Stop sharing screen"
                                tone="live"
                                testId="composer-plus-share-stop"
                                onClick={() => void toggleShare()}
                            />
                        ) : (
                            <MenuItem
                                icon={<MonitorUp size={16} />}
                                label="Share screen"
                                hint="HomePilot can see it until you stop"
                                testId="composer-plus-share"
                                onClick={() => void toggleShare()}
                            />
                        )
                    ) : null}

                    <div className="my-1 h-px bg-white/[0.07]" aria-hidden="true" />

                    {/* Renders nothing when MeetingSense is off on this server. */}
                    <MeetingMenuItem onDone={close} />
                </div>
            ) : null}
        </div>
    );
}

export default ComposerPlusMenu;
