/**
 * MeetingSense mount and meeting-workspace owner.
 *
 * One meeting gets one dedicated ordinary HomePilot conversation. The recorder still owns
 * capture and persistence; this provider owns the transition from normal chat → connecting →
 * live workspace → recap, and restores an origin meeting conversation as that recap when it is
 * reopened from History.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { consentAcknowledged, rememberConsent } from './ConsentSheet';
import { MeetingStartDialog } from './MeetingStartDialog';
import MeetingWorkspace, {
    type CaptureHealth,
    type CaptureSourceStatus,
    type MeetingCaptureStatus,
} from './MeetingWorkspace';
import { useMeetingSense } from './useMeetingSense';
import { modeLabel, phaseLabel, type Phase } from './meetingState';
import { DEFAULT_CAPTURE, parseNames, type CaptureOptions } from './CapturePopover';
import { useMeetingRecord } from './useMeetingRecord';
import type { MeetingRecord } from './meetingRecord';
import type { MeetingSenseStatus } from './entryPoint';
import { readMeetingModelTarget } from './api';

export interface MeetingSenseProviderProps {
    conversationId: string | null;
    status: MeetingSenseStatus | null;
    screenAwareness?: boolean;
    compact?: boolean;
    storage?: Storage;
    onExport?: (fmt: 'md' | 'srt' | 'json') => void;
    onOpenConversation?: (conversationId: string) => void;
}

export interface MeetingControls {
    live: boolean;
    starting: boolean;
    error: string | null;
    status: MeetingSenseStatus | null;
    conversationId: string | null;
    begin: () => void;
    end: () => void;
    phase: Phase;
    phaseText: string;
    elapsedMs: number;
    micMuted: boolean;
    mute: (muted: boolean) => void;
    /** Compatibility with older header/pill consumers. End is now immediate, so Undo is inert. */
    undo: () => void;
    undoSecondsLeft: number | null;
    capture: CaptureOptions;
    setCapture: (next: CaptureOptions) => void;
}

interface WorkspaceRecorder {
    getScreenPreviewStream?: () => MediaStream | null;
    resumeScreenCapture?: () => Promise<{ ok: boolean; error?: string; stream?: MediaStream }>;
}

interface ScreenSenseUi {
    stop?: () => void;
    bindConversation?: (id: string | null) => void;
    setAwareness?: (on: boolean) => void;
    setVision?: (next: { provider?: string; baseUrl?: string; model?: string }) => void;
    _button?: HTMLElement | null;
    _panel?: HTMLElement | null;
}

function browserRecorder(): WorkspaceRecorder | null {
    return (globalThis as unknown as { hpMeetingSense?: WorkspaceRecorder }).hpMeetingSense || null;
}

function browserScreenSense(): ScreenSenseUi | null {
    return (globalThis as unknown as { hpScreenSense?: ScreenSenseUi }).hpScreenSense || null;
}

function apiBase(): string {
    try {
        const saved = localStorage.getItem('homepilot_backend_url') || '';
        if (saved.trim()) return saved.replace(/\/+$/, '');
    } catch {
        // Relative routes still work when localStorage is unavailable.
    }
    return '';
}

function headers(): Record<string, string> {
    const out: Record<string, string> = { 'Content-Type': 'application/json' };
    try {
        const apiKey = localStorage.getItem('homepilot_api_key') || '';
        const token = localStorage.getItem('homepilot_auth_token') || '';
        if (apiKey) out['x-api-key'] = apiKey;
        if (token) out.Authorization = `Bearer ${token}`;
    } catch {
        // Local deployments may have neither key nor token.
    }
    return out;
}

function freshMeetingConversationId(): string {
    try {
        if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    } catch {
        // Fall through to an RFC-4122-shaped local id.
    }
    return `meeting-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function offSource(requested = false): CaptureSourceStatus {
    return {
        requested,
        health: requested ? 'connecting' : 'off',
        label: null,
        level: 0,
        error: null,
        lastSignalAt: null,
    };
}

function statusForCapture(capture: CaptureOptions): MeetingCaptureStatus {
    return {
        meetingAudio: offSource(capture.audio),
        microphone: offSource(capture.mic),
        screen: offSource(capture.slides),
    };
}

function allSourcesOff(): MeetingCaptureStatus {
    return {
        meetingAudio: offSource(false),
        microphone: offSource(false),
        screen: offSource(false),
    };
}

const HEALTH = new Set<CaptureHealth>([
    'off', 'connecting', 'receiving', 'no_signal', 'lost', 'blocked', 'error',
]);

function readVisionSettings(): { provider: string; baseUrl: string; model: string } {
    const get = (key: string): string => {
        try { return (localStorage.getItem(key) || '').trim(); } catch { return ''; }
    };
    return {
        provider: get('homepilot_provider_multimodal'),
        baseUrl: get('homepilot_base_url_multimodal'),
        model: get('homepilot_model_multimodal'),
    };
}

function meetingStartMarker(capture: CaptureOptions, remote: boolean): string {
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const sources = [
        capture.audio ? 'Meeting audio' : null,
        capture.mic ? 'microphone' : null,
        capture.slides ? 'screen' : null,
    ].filter(Boolean).join(' + ') || 'notes only';
    return [
        '[Meeting event]',
        `Meeting started · ${time}`,
        '',
        `${modeLabel(capture.mode) || 'Note taker'} · ${sources}`,
        remote ? 'Remote speech transcription' : 'Processed locally',
    ].join('\n');
}

export const MeetingSenseContext = React.createContext<MeetingControls | null>(null);

export function useMeetingControls(): MeetingControls | null {
    return React.useContext(MeetingSenseContext);
}

export function MeetingSenseProvider(props: React.PropsWithChildren<MeetingSenseProviderProps>) {
    const {
        conversationId,
        status,
        storage,
        onOpenConversation,
        screenAwareness = true,
        children,
    } = props;
    const meeting = useMeetingSense({ provider: status?.stt?.provider ?? null });
    const [capture, setCapture] = useState<CaptureOptions>(() => {
        const target = readMeetingModelTarget();
        return {
            ...DEFAULT_CAPTURE,
            summaryProvider: target.provider,
            summaryModel: target.model,
            summaryBaseUrl: target.baseUrl,
            conversationProvider: target.provider,
            conversationModel: target.model,
            conversationBaseUrl: target.baseUrl,
        };
    });
    const [pendingStart, setPendingStart] = useState(false);
    const [starting, setStarting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [workspaceMounted, setWorkspaceMounted] = useState(false);
    const [meetingConversationId, setMeetingConversationId] = useState<string | null>(null);
    const [captureStatus, setCaptureStatus] = useState<MeetingCaptureStatus>(allSourcesOff);
    const [screenStream, setScreenStream] = useState<MediaStream | null>(null);
    /** Chat that was open before this provider moved the app into the meeting conversation. */
    const returnConversationIdRef = useRef<string | null>(null);
    /**
     * Explicitly closed recaps must not immediately hydrate themselves again while the app is
     * still finishing navigation away from their conversation.
     */
    const dismissedMeetingConversationIdRef = useRef<string | null>(null);

    const enabled = Boolean(status?.enabled);
    const phase = meeting.view.phase;
    const live = phase === 'live' || phase === 'reconnecting' || phase === 'stopping';
    const ended = phase === 'ended';

    const persistStartMarker = useCallback(async (id: string) => {
        const response = await fetch(`${apiBase()}/conversations/${encodeURIComponent(id)}/messages`, {
            method: 'POST',
            credentials: 'include',
            headers: headers(),
            body: JSON.stringify({
                role: 'system',
                content: meetingStartMarker(capture, Boolean(status?.stt?.remote)),
            }),
        });
        if (!response.ok) throw new Error(`conversation marker HTTP ${response.status}`);
    }, [capture, status?.stt?.remote]);

    /**
     * Attach the context the user pasted in the setup dialog (MS34).
     *
     * After `start`, not before it: the meeting id does not exist until the socket answers
     * `ready`, and there is nothing to attach it to. Failure is logged and swallowed — a
     * meeting that records perfectly well must not be taken down because an optional
     * paragraph did not reach the store, and the user can attach it again.
     */
    const attachContext = useCallback(async (meetingId: string, text: string) => {
        const body = text.trim();
        if (!meetingId || !body) return;
        try {
            await fetch(`${apiBase()}/v1/meetingsense/${encodeURIComponent(meetingId)}/prep`, {
                method: 'POST',
                credentials: 'include',
                headers: headers(),
                body: JSON.stringify({ title: 'Meeting context', text: body }),
            });
        } catch (attachError) {
            console.warn('[MeetingSense] meeting context could not be attached', attachError);
        }
    }, []);

    const actuallyStart = useCallback(async () => {
        const nextConversation = freshMeetingConversationId();
        // Remember where the user was before the dedicated meeting thread takes over. Close
        // returns there instead of leaving the app parked on a meeting conversation that
        // immediately re-opens its recap.
        returnConversationIdRef.current = conversationId;
        dismissedMeetingConversationIdRef.current = null;
        meeting.reset();
        setMeetingConversationId(nextConversation);
        setWorkspaceMounted(true);
        setCaptureStatus(statusForCapture(capture));
        setScreenStream(null);
        setStarting(true);
        setError(null);

        try {
            const result = await meeting.start({
                conversationId: nextConversation,
                notes: true,
                watch: capture.slides,
                audio: capture.audio,
                mic: capture.mic,
                ...(capture.mode ? { mode: capture.mode } : {}),
                // MS26's name lists. Sent as arrays because that is what the `start` frame
                // takes; the wizard collects them as one comma-separated field each, since
                // "Ruslan, Rus" is how a person writes the two things they are called.
                names: parseNames(capture.myNames),
                assistantNames: parseNames(capture.assistantName),
                // MS34. The shape of the document this meeting should leave behind. Sent at
                // `start` and stored on the meeting, so a stop that happens after a
                // reconnect — or after this tab was closed — still writes the one the user
                // chose rather than the default.
                summary: {
                    style: capture.summaryStyle,
                    length: capture.summaryLength,
                    provider: capture.summaryProvider,
                    model: capture.summaryModel,
                    base_url: capture.summaryBaseUrl,
                },
                conversation: {
                    provider: capture.conversationProvider,
                    model: capture.conversationModel,
                    base_url: capture.conversationBaseUrl,
                },
            });
            if (!result.ok) {
                setError(result.error || 'The meeting could not start.');
                setWorkspaceMounted(false);
                setMeetingConversationId(null);
                setCaptureStatus(allSourcesOff());
                setScreenStream(null);
                returnConversationIdRef.current = null;
                meeting.reset();
                return;
            }

            const stream = browserRecorder()?.getScreenPreviewStream?.() || null;
            if (stream) setScreenStream(stream);

            if (result.meetingId) void attachContext(result.meetingId, capture.context);

            try {
                await persistStartMarker(nextConversation);
            } catch (markerError) {
                console.warn('[MeetingSense] meeting started but start marker could not be persisted', markerError);
            }

            // Only after capture succeeds: the normal chat underneath switches to the new
            // conversation. If permissions fail, the user is still exactly where they started.
            onOpenConversation?.(nextConversation);
        } finally {
            setStarting(false);
        }
    }, [attachContext, capture, conversationId, meeting, onOpenConversation, persistStartMarker]);

    const begin = useCallback(() => {
        if (live || starting) return;
        if (!enabled) {
            setError('MeetingSense is turned off on this server.');
            return;
        }
        if (!consentAcknowledged(storage)) {
            setPendingStart(true);
            return;
        }
        void actuallyStart();
    }, [live, starting, enabled, storage, actuallyStart]);

    const end = useCallback(() => {
        // useMeetingSense.stop() calls recorder.stop() immediately; `stopping` now means
        // finalizing already-captured material, not continuing to listen during an undo timer.
        void meeting.stop();
    }, [meeting]);

    const onAccept = useCallback((remember: boolean) => {
        if (remember) rememberConsent(storage);
        setPendingStart(false);
        void actuallyStart();
    }, [storage, actuallyStart]);

    // Source state comes from the actual tracks/RMS in homepilot-meetingsense-media.js. Never
    // infer Receiving from a permission grant or from the preflight switch being on.
    useEffect(() => {
        const onSource = (event: Event) => {
            const detail = (event as CustomEvent).detail || {};
            const state = HEALTH.has(detail.state as CaptureHealth) ? detail.state as CaptureHealth : 'error';
            const next: CaptureSourceStatus = {
                requested: Boolean(detail.requested),
                health: state,
                label: typeof detail.label === 'string' && detail.label ? detail.label : null,
                level: typeof detail.level === 'number' ? detail.level : 0,
                error: typeof detail.error === 'string' && detail.error ? detail.error : null,
                lastSignalAt: typeof detail.lastSignalAt === 'number' ? detail.lastSignalAt : null,
            };
            const key = detail.source === 'meeting_audio'
                ? 'meetingAudio'
                : detail.source === 'microphone'
                    ? 'microphone'
                    : detail.source === 'screen'
                        ? 'screen'
                        : null;
            if (!key) return;
            setCaptureStatus((current) => ({ ...current, [key]: next }));
        };
        const onScreen = (event: Event) => {
            const detail = (event as CustomEvent).detail || {};
            if (detail.state === 'off') {
                setScreenStream(null);
                return;
            }
            // Keep the last stream object on `lost`; MeetingScreenPreview takes one frozen
            // frame from it before offering Resume.
            if (detail.stream && typeof detail.stream.getTracks === 'function') {
                setScreenStream(detail.stream as MediaStream);
            }
        };
        window.addEventListener('ms:source_changed', onSource);
        window.addEventListener('ms:screen_source', onScreen);
        return () => {
            window.removeEventListener('ms:source_changed', onSource);
            window.removeEventListener('ms:screen_source', onScreen);
        };
    }, []);

    const resumeScreen = useCallback(async () => {
        const recorder = browserRecorder();
        if (!recorder?.resumeScreenCapture) {
            setCaptureStatus((current) => ({
                ...current,
                screen: { ...current.screen, health: 'error', error: 'This browser cannot resume the current screen capture.' },
            }));
            return;
        }
        const result = await recorder.resumeScreenCapture();
        if (!result.ok) {
            setCaptureStatus((current) => ({
                ...current,
                screen: { ...current.screen, health: 'error', error: result.error || 'Screen sharing could not resume.' },
            }));
        } else if (result.stream) {
            setScreenStream(result.stream);
        }
    }, []);

    // Bind the generic one-off ScreenSense feature as before. During a live Meeting Workspace
    // its presentation is hidden separately below, so there is one visible capture owner.
    useEffect(() => {
        const sense = browserScreenSense();
        try {
            sense?.setAwareness?.(screenAwareness);
            sense?.bindConversation?.(conversationId);
            sense?.setVision?.(readVisionSettings());
        } catch {
            // Screen presence is best-effort.
        }
    }, [conversationId, screenAwareness]);

    // Hide the legacy “What I can see” button/panel while the meeting owns capture. If it had
    // a separate browser stream, stop it only after MeetingSense is actually live so a failed
    // preflight never destroys the user's previous context.
    useEffect(() => {
        if (!workspaceMounted || ended) return undefined;
        const sense = browserScreenSense();
        if (!sense) return undefined;
        const button = sense._button || null;
        const panel = sense._panel || null;
        const buttonDisplay = button?.style.display ?? '';
        const panelDisplay = panel?.style.display ?? '';
        if (button) button.style.display = 'none';
        if (panel) panel.style.display = 'none';
        if (phase === 'live' && capture.slides) {
            try { sense.stop?.(); } catch { /* MeetingSense remains authoritative */ }
        }
        return () => {
            if (button) button.style.display = buttonDisplay;
            if (panel) panel.style.display = panelDisplay;
        };
    }, [workspaceMounted, ended, phase, capture.slides]);

    /** Reset only MeetingSense state. Used when normal navigation has already left the recap. */
    const resetWorkspace = useCallback(() => {
        setWorkspaceMounted(false);
        setMeetingConversationId(null);
        setScreenStream(null);
        setCaptureStatus(allSourcesOff());
        setError(null);
        meeting.reset();
    }, [meeting]);

    /**
     * Close from the recap means "back to chat", not merely "hide this portal".
     *
     * Hiding the workspace while `conversationId` still points at the meeting thread caused
     * the restore effect below to hydrate the same recap again on the next render. Remember
     * that id as explicitly dismissed, reset the meeting session, then navigate back to the
     * chat that was open before the meeting started.
     */
    const closeWorkspace = useCallback(() => {
        const closingMeetingId = meetingConversationId;
        if (closingMeetingId) dismissedMeetingConversationIdRef.current = closingMeetingId;
        const returnConversationId = returnConversationIdRef.current;
        returnConversationIdRef.current = null;
        resetWorkspace();
        if (returnConversationId && returnConversationId !== closingMeetingId) {
            onOpenConversation?.(returnConversationId);
        }
    }, [meetingConversationId, onOpenConversation, resetWorkspace]);

    // The dedicated meeting conversation is sticky while capture is live. Navigation becomes
    // ordinary again after ending, at which point leaving the recap closes this workspace.
    useEffect(() => {
        if (!meetingConversationId || !conversationId || conversationId === meetingConversationId) return;
        if (live || starting) {
            onOpenConversation?.(meetingConversationId);
            return;
        }
        if (ended) {
            returnConversationIdRef.current = null;
            resetWorkspace();
        }
    }, [conversationId, meetingConversationId, live, starting, ended, onOpenConversation, resetWorkspace]);

    // Opening an origin meeting conversation from History restores the dedicated recap. A
    // branch deliberately remains a normal chat even though it can search the same meeting.
    useEffect(() => {
        if (!conversationId || starting || live) return undefined;
        const dismissedId = dismissedMeetingConversationIdRef.current;
        if (dismissedId && conversationId !== dismissedId) {
            // Once normal navigation has visibly left the dismissed meeting, reopening it from
            // History is an intentional action again and should restore its recap as before.
            dismissedMeetingConversationIdRef.current = null;
        } else if (dismissedId === conversationId) {
            return undefined;
        }
        if (workspaceMounted && meetingConversationId === conversationId) return undefined;
        let cancelled = false;
        const hydrate = async () => {
            try {
                const listResponse = await fetch(
                    `${apiBase()}/v1/meetingsense/conversations/${encodeURIComponent(conversationId)}`,
                    { credentials: 'include', headers: headers() },
                );
                if (!listResponse.ok || cancelled) return;
                const listBody = await listResponse.json();
                const rows = Array.isArray(listBody?.meetings) ? listBody.meetings : [];
                const origin = [...rows].reverse().find((row: Record<string, unknown>) => row?.thread_kind === 'origin');
                const meetingId = origin && typeof origin.meeting_id === 'string' ? origin.meeting_id : null;
                if (!meetingId) return;
                const recordResponse = await fetch(
                    `${apiBase()}/v1/meetingsense/${encodeURIComponent(meetingId)}`,
                    { credentials: 'include', headers: headers() },
                );
                if (!recordResponse.ok || cancelled) return;
                const record = await recordResponse.json() as MeetingRecord;
                if (cancelled) return;
                meeting.hydrateRecord(record);
                setMeetingConversationId(conversationId);
                setWorkspaceMounted(true);
                setCaptureStatus(allSourcesOff());
                setScreenStream(null);
                setError(null);
            } catch {
                // A normal conversation has no MeetingSense record; that is not an error.
            }
        };
        void hydrate();
        return () => { cancelled = true; };
    }, [conversationId, starting, live, workspaceMounted, meetingConversationId, meeting]);

    useEffect(() => {
        if (!enabled) setError(null);
    }, [enabled]);

    const stored = useMeetingRecord({
        meetingId: meeting.view.meetingId,
        enabled: ended,
    });

    const controls: MeetingControls = {
        live,
        starting,
        error,
        status,
        conversationId: meetingConversationId || conversationId,
        begin,
        end,
        phase,
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
            {workspaceMounted && meetingConversationId ? (
                <MeetingWorkspace
                    view={meeting.view}
                    capture={capture}
                    captureStatus={captureStatus}
                    conversationId={meetingConversationId}
                    screenStream={screenStream}
                    record={stored.record}
                    pendingNotes={stored.pendingNotes}
                    starting={starting}
                    error={error}
                    onEnd={end}
                    onMute={meeting.muteMic}
                    onResumeScreen={() => void resumeScreen()}
                    // Only once it has ended: closing a live meeting would be a Stop that
                    // does not say it is stopping, and capture would outlive the window that
                    // said it was recording.
                    onClose={ended ? closeWorkspace : undefined}
                />
            ) : null}
        </MeetingSenseContext.Provider>
    );
}

export default MeetingSenseProvider;
