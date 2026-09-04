/**
 * The mount (batch MS29, wave W11).
 *
 * W0–W10 built a recorder, a card, a pill, a consent sheet, four helper modes and a catalog —
 * and mounted none of it. Every batch was specified "additive, new directories, guarded hooks",
 * and that was followed so exactly that the mount points were built and the mount never was.
 * `entryPoint.attach()` has existed since MS5 for this purpose and nothing ever called it.
 *
 * This is the one component the application renders. Everything else hangs off it, so there is
 * a single place to answer "is MeetingSense on screen right now, and why".
 *
 * **Off is nothing.** No flag, no recorder script, no meeting running — this returns `null` and
 * the application's DOM is what it was before the feature existed. That is asserted in tests
 * rather than assumed, because a provider that renders an empty wrapper on every install is a
 * change to every page in the product.
 *
 * **Consent comes before capture, once.** The sheet is shown before the first recording on this
 * machine and remembered. It is not shown again on every meeting: a consent dialog that appears
 * every time is one people learn to dismiss without reading, which is the opposite of consent.
 *
 * **The pill is not optional.** §2a: recording state is unmissable. Whenever a meeting is live
 * the pill is on screen at every scroll position, and no prop can turn it off — a recorder that
 * can be hidden is a recorder that records something it should not.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { ConsentSheet, consentAcknowledged, rememberConsent } from './ConsentSheet';
import { MeetingCard } from './MeetingCard';
import { RecordingPill } from './RecordingPill';
import { useMeetingSense } from './useMeetingSense';
import type { MeetingSenseStatus } from './entryPoint';

export interface MeetingSenseProviderProps {
    /** The conversation the meeting belongs to. Without one there is nowhere for it to land. */
    conversationId: string | null;
    status: MeetingSenseStatus | null;
    /** MS29, Settings → "Let agents see my shared screen". Undefined reads as on. */
    screenAwareness?: boolean;
    /** Rendered small on a phone. */
    compact?: boolean;
    /** Injected in tests. */
    storage?: Storage;
    onExport?: (fmt: 'md' | 'srt' | 'json') => void;
}

/**
 * Everything a control anywhere in the tree needs, so nothing has to be threaded to it.
 *
 * `status` and `conversationId` ride along with the callbacks deliberately. The record button
 * belongs beside the composer, which is several components deep; passing two props down that
 * path would put MeetingSense's wiring into every component between here and there, and this
 * programme has spent ten waves not growing `App.tsx`.
 */
export interface MeetingControls {
    live: boolean;
    starting: boolean;
    error: string | null;
    status: MeetingSenseStatus | null;
    conversationId: string | null;
    begin: () => void;
    end: () => void;
}

/**
 * The provider's own state, lifted so a button anywhere in the tree can drive it.
 *
 * A context rather than props threaded through the application: the button belongs beside the
 * composer and the pill belongs at the top of the viewport, and making `App` carry the wiring
 * between them would put MeetingSense's state in the one file this programme has been careful
 * not to grow.
 */
export const MeetingSenseContext = React.createContext<MeetingControls | null>(null);

export function useMeetingControls(): MeetingControls | null {
    return React.useContext(MeetingSenseContext);
}

export function MeetingSenseProvider({
    conversationId, status, compact = false, storage, onExport,
    screenAwareness = true,
    children,
}: React.PropsWithChildren<MeetingSenseProviderProps>) {
    const meeting = useMeetingSense({ provider: status?.stt?.provider ?? null });
    const [pendingStart, setPendingStart] = useState(false);
    const [starting, setStarting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const enabled = Boolean(status?.enabled);
    const live = meeting.view.phase !== 'idle';

    const actuallyStart = useCallback(async () => {
        if (!conversationId) {
            setError('Open or start a conversation first — a meeting has to land somewhere.');
            return;
        }
        setStarting(true);
        setError(null);
        try {
            // Sensible defaults, deliberately. Asking somebody to configure notes and slides
            // before they can press record is how a record button goes unpressed; the popover
            // on the 👁 button is where those are changed by the people who want to.
            const result = await meeting.start({
                conversationId,
                notes: true,
                watch: true,
            });
            if (!result.ok) setError(result.error || 'The meeting could not start.');
        } finally {
            setStarting(false);
        }
    }, [conversationId, meeting]);

    const begin = useCallback(() => {
        if (live || starting) return;
        // The server's switch, checked here and not only in the button. `begin` is reachable
        // through the context by anything in the tree, and "the control is hidden" is not the
        // same as "the capability is off".
        if (!enabled) {
            setError('MeetingSense is turned off on this server.');
            return;
        }
        // Consent first, and only the first time on this machine.
        if (!consentAcknowledged(storage)) {
            setPendingStart(true);
            return;
        }
        void actuallyStart();
    }, [live, starting, enabled, storage, actuallyStart]);

    const end = useCallback(() => {
        void meeting.stop();
    }, [meeting]);

    const onAccept = useCallback(
        (remember: boolean) => {
            if (remember) rememberConsent(storage);
            setPendingStart(false);
            void actuallyStart();
        },
        [storage, actuallyStart],
    );

    // MS29. ScreenSense's own 👁 button can start a share before the user has typed anything,
    // and at that moment it needs to know which conversation the share belongs to — otherwise
    // the persona is told a screen is being shared somewhere it cannot name. Guarded: an
    // install without the addon, or an older copy of it, simply has no `bindConversation`.
    useEffect(() => {
        const sense = (globalThis as unknown as {
            hpScreenSense?: {
                bindConversation?: (id: string | null) => void;
                setAwareness?: (on: boolean) => void;
            };
        }).hpScreenSense;
        try {
            // The setting first: it decides whether the binding may say anything at all.
            sense?.setAwareness?.(screenAwareness);
            sense?.bindConversation?.(conversationId);
        } catch {
            // A screen-presence ping is never worth a chat.
        }
    }, [conversationId, screenAwareness]);

    // A conversation change while recording is the user walking away from the meeting's home.
    // The recording is not stopped — that would lose audio somebody is still speaking — but the
    // card follows the meeting rather than the chat, which is what `hydrate` is for (MS16).
    useEffect(() => {
        if (!enabled) setError(null);
    }, [enabled]);

    const controls: MeetingControls = {
        live, starting, error, status, conversationId, begin, end,
    };

    // Two conditions and no wrapper around them. An outer "is anything happening" guard would
    // restate exactly what these two say, and a rule written twice is a rule that gets edited
    // once. `enabled` is not checked here either — `begin` enforces it, which is where a
    // capability check belongs, and duplicating it would let the two drift.
    //
    // With nothing happening this contributes no node at all, which is the promise the whole
    // programme was built under and the one thing these components could most easily break.
    return (
        <MeetingSenseContext.Provider value={controls}>
            {children}
            {pendingStart ? (
                <ConsentSheet
                    status={status}
                    onAccept={onAccept}
                    onCancel={() => setPendingStart(false)}
                />
            ) : null}
            {live ? (
                <>
                    <RecordingPill
                        view={meeting.view}
                        onMute={meeting.muteMic}
                        onStop={meeting.stop}
                        onUndo={meeting.undo}
                        undoSecondsLeft={meeting.undoSecondsLeft}
                    />
                    <MeetingCard
                        view={meeting.view}
                        compact={compact}
                        onExport={onExport}
                        onAcceptChip={meeting.acceptChip}
                        onDismissChip={meeting.dismissChip}
                    />
                </>
            ) : null}
        </MeetingSenseContext.Provider>
    );
}

export default MeetingSenseProvider;
