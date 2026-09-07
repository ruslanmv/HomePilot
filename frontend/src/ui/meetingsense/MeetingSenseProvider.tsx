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
 * **Preflight comes before capture, once unless the user explicitly skips it.** The first-run
 * surface combines truthful consent with the capture choices that already existed behind the
 * meeting-options chevron. A remembered choice preserves the existing one-click start path.
 *
 * **The pill is not optional.** §2a: recording state is unmissable. Whenever a meeting is live
 * the pill is on screen at every scroll position, and no prop can turn it off — a recorder that
 * can be hidden is a recorder that records something it should not.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { consentAcknowledged, rememberConsent } from './ConsentSheet';
import { MeetingStartDialog } from './MeetingStartDialog';
import { MeetingCard } from './MeetingCard';
import { RecordingPill } from './RecordingPill';
import { useMeetingSense } from './useMeetingSense';
import { phaseLabel, type Phase } from './meetingState';
import { DEFAULT_CAPTURE, type CaptureOptions } from './CapturePopover';
import { useMeetingRecord } from './useMeetingRecord';
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
    /** MS33. Navigate to the conversation "Discuss in new chat" creates. */
    onOpenConversation?: (conversationId: string) => void;
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
    /**
     * MS32. The header control is a *state* as well as an action — `● 08:42` while a
     * meeting runs — and its popover carries the same two buttons the pill does. These
     * fields are added rather than handing out the whole `MeetingView`: a context that
     * exposes the view is one every future control reads straight through, and then the
     * shape of the recorder's state becomes the application's API.
     *
     * `phaseText` is resolved here rather than re-derived at each consumer, so the pill and
     * the header can never disagree about what phase the meeting is in.
     */
    phase: Phase;
    phaseText: string;
    elapsedMs: number;
    micMuted: boolean;
    mute: (muted: boolean) => void;
    undo: () => void;
    undoSecondsLeft: number | null;
    /**
     * MS33. What the next meeting will capture, and in which mode. Held here rather than in
     * the chevron's popover so the choice survives the popover closing — and so `begin`
     * reads exactly what the user last saw, instead of the popover posting its state
     * somewhere and hoping the two agree.
     */
    capture: CaptureOptions;
    setCapture: (next: CaptureOptions) => void;
}

/**
 * The vision provider the user chose in Settings (V1).
 *
 * The same three `localStorage` keys `App.tsx` writes when Settings is saved. Read here
 * rather than threaded down as props because ScreenSense is a plain script on `globalThis`,
 * not part of the React tree — and a missing or unreadable value is an empty string, which
 * ScreenSense treats as "no choice" and leaves to the backend.
 */
function readVisionSettings(): { provider: string; baseUrl: string; model: string } {
    const get = (key: string): string => {
        try {
            return (localStorage.getItem(key) || '').trim();
        } catch {
            return '';
        }
    };
    return {
        provider: get('homepilot_provider_multimodal'),
        baseUrl: get('homepilot_base_url_multimodal'),
        model: get('homepilot_model_multimodal'),
    };
}

export const MeetingSenseContext = React.createContext<MeetingControls | null>(null);

export function useMeetingControls(): MeetingControls | null {
    return React.useContext(MeetingSenseContext);
}

export function MeetingSenseProvider({
    conversationId, status, compact = false, storage, onExport, onOpenConversation,
    screenAwareness = true,
    children,
}: React.PropsWithChildren<MeetingSenseProviderProps>) {
    const meeting = useMeetingSense({ provider: status?.stt?.provider ?? null });
    const [capture, setCapture] = useState<CaptureOptions>(DEFAULT_CAPTURE);
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
            const result = await meeting.start({
                conversationId,
                notes: true,
                watch: capture.slides,
                audio: capture.audio,
                mic: capture.mic,
                ...(capture.mode ? { mode: capture.mode } : {}),
            });
            if (!result.ok) setError(result.error || 'The meeting could not start.');
        } finally {
            setStarting(false);
        }
    }, [conversationId, meeting, capture]);

    const begin = useCallback(() => {
        if (live || starting) return;
        if (!enabled) {
            setError('MeetingSense is turned off on this server.');
            return;
        }
        // Preserve the established fast path when this machine explicitly opted out of
        // preflight. Otherwise the start click opens the premium, non-capturing setup dialog.
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

    useEffect(() => {
        const sense = (globalThis as unknown as {
            hpScreenSense?: {
                bindConversation?: (id: string | null) => void;
                setAwareness?: (on: boolean) => void;
                setVision?: (next: { provider?: string; baseUrl?: string; model?: string }) => void;
            };
        }).hpScreenSense;
        try {
            sense?.setAwareness?.(screenAwareness);
            sense?.bindConversation?.(conversationId);
            sense?.setVision?.(readVisionSettings());
        } catch {
            // A screen-presence ping is never worth a chat.
        }
    }, [conversationId, screenAwareness]);

    useEffect(() => {
        if (!enabled) setError(null);
    }, [enabled]);

    const ended = meeting.view.phase === 'ended';
    const stored = useMeetingRecord({
        meetingId: meeting.view.meetingId,
        enabled: ended,
    });

    const controls: MeetingControls = {
        live, starting, error, status, conversationId, begin, end,
        phase: meeting.view.phase,
        phaseText: phaseLabel(meeting.view),
        elapsedMs: meeting.view.elapsedMs,
        micMuted: meeting.view.micMuted,
        mute: meeting.muteMic,
        undo: meeting.undo,
        undoSecondsLeft: meeting.undoSecondsLeft,
        capture,
        setCapture,
    };

    return (
        <MeetingSenseContext.Provider value={controls}>
            {children}
            {pendingStart ? (
                <MeetingStartDialog
                    status={status}
                    capture={capture}
                    onCaptureChange={setCapture}
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
                        record={stored.record}
                        pendingNotes={stored.pendingNotes}
                        onOpenConversation={onOpenConversation}
                        onDeleted={() => meeting.setPhase('idle')}
                    />
                </>
            ) : null}
        </MeetingSenseContext.Provider>
    );
}

export default MeetingSenseProvider;
