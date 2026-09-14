import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
    AlertTriangle,
    CheckCircle2,
    ChevronDown,
    FileText,
    MessageSquare,
    Mic2,
    MonitorUp,
    RefreshCw,
    Send,
    Sparkles,
    Square,
    Volume2,
    X,
} from 'lucide-react';
import MeetingSummary from './MeetingSummary';
import {
    elapsedLabel,
    modeLabel,
    speakerLabel,
    stampLabel,
    type MeetingView,
} from './meetingState';
import {
    answerParts,
    dayLabel,
    durationLabel,
    notesBody,
    segmentAt,
    titleOf,
    type MeetingRecord,
} from './meetingRecord';
import type { CaptureOptions } from './CapturePopover';

export type CaptureHealth =
    | 'off'
    | 'connecting'
    | 'receiving'
    | 'no_signal'
    | 'lost'
    | 'blocked'
    | 'error';

export interface CaptureSourceStatus {
    requested: boolean;
    health: CaptureHealth;
    label: string | null;
    level: number;
    error: string | null;
    lastSignalAt: number | null;
}

export interface MeetingCaptureStatus {
    meetingAudio: CaptureSourceStatus;
    microphone: CaptureSourceStatus;
    screen: CaptureSourceStatus;
}

export interface MeetingWorkspaceProps {
    view: MeetingView;
    capture: CaptureOptions;
    captureStatus: MeetingCaptureStatus;
    /**
     * The conversation the meeting was recorded in.
     *
     * Kept for the header and for callers, and deliberately **not** used by the ask lane any
     * more: posting questions here is what wrote a private side-channel into the meeting's
     * permanent thread.
     */
    conversationId: string;
    screenStream: MediaStream | null;
    record: MeetingRecord | null;
    pendingNotes: boolean;
    starting?: boolean;
    error?: string | null;
    onEnd: () => void;
    onMute: (muted: boolean) => void;
    onResumeScreen?: () => void;
    /** Dismiss the recap and go back to the application. Absent while a meeting is live. */
    onClose?: () => void;
}

/**
 * One question you asked about the meeting, and what came back.
 *
 * ── Why these are not transcript, and not chat either ────────────────────────────────────
 *
 * A meeting transcript is a record of **what was said in the room**. Anything else written
 * into it is a forgery: a reader — or the recap model, or a search six months later — cannot
 * tell your private question to an assistant from a sentence somebody actually spoke. So these
 * live in their own lane, are labelled as yours and private, and reach the meeting's permanent
 * record only when you explicitly put them there.
 *
 * They are equally not ordinary chat. This used to POST to `/chat` with the meeting's
 * `conversation_id`, which was wrong twice over: the model was handed no transcript at all, so
 * "what did they say about the tax cuts" was answered by a model that had never seen the
 * meeting; and every exchange was persisted into the meeting conversation, quietly rewriting
 * the thread the meeting was recorded in.
 *
 * `POST /v1/meetingsense/{id}/ask` is the endpoint built for exactly this. It assembles the
 * last ninety seconds verbatim, the rolling recap, and the passages that match the question,
 * and it works on a **live** meeting — the verbatim tier is the reason it exists.
 */
type ChatTurn = {
    id: string;
    role: 'user' | 'assistant';
    text: string;
    pending?: boolean;
    error?: boolean;
    createdAt: number;
    /** Stamps the server vouched for, so only a real source is rendered as a link. */
    cited?: string[];
    /** Whether this answer has been deliberately added to the meeting's notes. */
    kept?: boolean;
};

type TimelineEvent = {
    id: string;
    t: number;
    kind: 'meeting' | 'slide' | 'decision' | 'action' | 'question' | 'source';
    title: string;
    text?: string;
};

function backendBase(): string {
    try {
        const saved = window.localStorage.getItem('homepilot_backend_url') || '';
        if (saved.trim()) return saved.replace(/\/+$/, '');
    } catch {
        // Storage can be unavailable in locked-down contexts.
    }
    const fromWindow = (window as typeof window & { HOMEPILOT_API_BASE?: string }).HOMEPILOT_API_BASE || '';
    return fromWindow.replace(/\/+$/, '');
}

function requestHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    try {
        const apiKey = window.localStorage.getItem('homepilot_api_key') || '';
        const token = window.localStorage.getItem('homepilot_auth_token') || '';
        if (apiKey) headers['x-api-key'] = apiKey;
        if (token) headers.Authorization = `Bearer ${token}`;
    } catch {
        // A meeting can still run on an unauthenticated local backend.
    }
    return headers;
}

function healthCopy(status: CaptureSourceStatus): string {
    switch (status.health) {
        case 'receiving': return 'Receiving';
        case 'connecting': return 'Connecting…';
        case 'no_signal': return 'No audio detected';
        case 'lost': return 'Source disconnected';
        case 'blocked': return 'Permission blocked';
        case 'error': return 'Needs attention';
        default: return 'Off';
    }
}

function healthTone(status: CaptureSourceStatus): string {
    switch (status.health) {
        case 'receiving': return 'text-emerald-300';
        case 'connecting': return 'text-violet-300';
        case 'no_signal': return 'text-amber-200';
        case 'lost':
        case 'blocked':
        case 'error': return 'text-red-300';
        default: return 'text-white/35';
    }
}

function SourceRow({
    icon,
    label,
    status,
}: {
    icon: React.ReactNode;
    label: string;
    status: CaptureSourceStatus;
}) {
    return (
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] px-3 py-2.5">
            <div className="flex items-center gap-2">
                <span className="text-white/45">{icon}</span>
                <span className="min-w-0 flex-1 text-xs font-medium text-white/80">{label}</span>
                <span className={`text-[11px] font-medium ${healthTone(status)}`}>{healthCopy(status)}</span>
            </div>
            {status.label ? <div className="mt-1 truncate pl-6 text-[10px] text-white/30">{status.label}</div> : null}
            {status.error ? <div className="mt-1 pl-6 text-[10px] leading-4 text-red-200/70">{status.error}</div> : null}
        </div>
    );
}

function useMainHost() {
    const [host, setHost] = useState<HTMLElement | null>(null);
    useEffect(() => {
        let cancelled = false;
        let frame = 0;
        const find = () => {
            if (cancelled) return;
            const node = document.querySelector<HTMLElement>('.hp-app-shell main');
            if (node) {
                setHost(node);
                return;
            }
            frame = requestAnimationFrame(find);
        };
        find();
        return () => {
            cancelled = true;
            if (frame) cancelAnimationFrame(frame);
        };
    }, []);
    return host;
}

function ScreenPreview({
    stream,
    status,
    onResume,
}: {
    stream: MediaStream | null;
    status: CaptureSourceStatus;
    onResume?: () => void;
}) {
    const videoRef = useRef<HTMLVideoElement | null>(null);
    const [lastFrame, setLastFrame] = useState<string | null>(null);

    const snapshot = () => {
        const video = videoRef.current;
        if (!video || !video.videoWidth || !video.videoHeight) return;
        try {
            const canvas = document.createElement('canvas');
            const scale = Math.min(1, 640 / video.videoWidth);
            canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
            canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
            canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
            setLastFrame(canvas.toDataURL('image/jpeg', 0.72));
        } catch {
            // A frozen preview is a convenience, never a reason to fail the meeting.
        }
    };

    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;
        video.srcObject = stream;
        if (stream) void video.play().catch(() => undefined);
        return () => {
            if (video.srcObject === stream) video.srcObject = null;
        };
    }, [stream]);

    useEffect(() => {
        if (status.health === 'lost' || status.health === 'error') snapshot();
    }, [status.health]);

    const active = status.health === 'receiving' || status.health === 'connecting';

    return (
        <div className="overflow-hidden rounded-2xl border border-white/[0.09] bg-[#0b0c0e]">
            <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3">
                <div>
                    <div className="text-xs font-semibold text-white/90">HomePilot sees</div>
                    <div className="mt-0.5 max-w-[220px] truncate text-[10px] text-white/35">
                        {status.label || (status.requested ? 'Shared screen' : 'Not shared')}
                    </div>
                </div>
                <span className={`text-[10px] font-medium ${healthTone(status)}`}>● {healthCopy(status)}</span>
            </div>
            <div className="relative aspect-video bg-black">
                <video
                    ref={videoRef}
                    muted
                    autoPlay
                    playsInline
                    className={`h-full w-full object-contain ${active && stream ? 'opacity-100' : 'opacity-0'}`}
                />
                {!active || !stream ? (
                    <div className="absolute inset-0 flex items-center justify-center p-5 text-center">
                        {lastFrame ? (
                            <img src={lastFrame} alt="Last shared screen frame" className="absolute inset-0 h-full w-full object-contain opacity-45" />
                        ) : null}
                        <div className="relative rounded-xl bg-black/65 px-4 py-3 backdrop-blur-sm">
                            <MonitorUp size={20} className="mx-auto mb-2 text-white/35" />
                            <div className="text-xs font-medium text-white/75">
                                {status.requested ? healthCopy(status) : 'Screen sharing is off'}
                            </div>
                            {status.health === 'lost' && onResume ? (
                                <button
                                    type="button"
                                    onClick={onResume}
                                    className="mt-3 inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.06] px-3 text-[11px] font-medium text-white/75 hover:bg-white/10"
                                >
                                    <RefreshCw size={12} /> Resume screen
                                </button>
                            ) : null}
                        </div>
                    </div>
                ) : null}
            </div>
        </div>
    );
}

export function MeetingWorkspace({
    view,
    capture,
    captureStatus,
    screenStream,
    record,
    pendingNotes,
    starting = false,
    error = null,
    onEnd,
    onMute,
    onResumeScreen,
    onClose,
}: MeetingWorkspaceProps) {
    const host = useMainHost();
    /*
     * Transcript first, deliberately.
     *
     * This opened on Timeline, which renders decisions, slides and capture-source changes —
     * and no transcript at all. So a live meeting showed "Meeting started" and nothing else
     * while the words were arriving one tab away, and the only way to find out it had been
     * working the whole time was to end the meeting and read the recap. "It does not update
     * while transcribing, but after the session ends it recognised it" is that, exactly.
     *
     * During a meeting the question is *is it hearing me*, and only the transcript answers it.
     */
    const [tab, setTab] = useState<'timeline' | 'transcript' | 'ask'>('transcript');
    const [confirmEnd, setConfirmEnd] = useState(false);
    const [input, setInput] = useState('');
    const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);
    const [sourceEvents, setSourceEvents] = useState<TimelineEvent[]>([]);
    const previousHealth = useRef<Record<string, CaptureHealth>>({});

    useEffect(() => {
        const entries: Array<[string, string, CaptureSourceStatus]> = [
            ['meeting-audio', 'Meeting audio', captureStatus.meetingAudio],
            ['microphone', 'My microphone', captureStatus.microphone],
            ['screen', 'Screen sharing', captureStatus.screen],
        ];
        setSourceEvents((current) => {
            const next = [...current];
            for (const [id, label, status] of entries) {
                const before = previousHealth.current[id];
                previousHealth.current[id] = status.health;
                if (!before || before === status.health) continue;
                if (status.health === 'connecting' || status.health === 'off') continue;
                next.push({
                    id: `source-${id}-${Date.now()}-${status.health}`,
                    t: view.elapsedMs,
                    kind: 'source',
                    title: label,
                    text: healthCopy(status),
                });
            }
            return next.slice(-20);
        });
    }, [captureStatus, view.elapsedMs]);

    const semanticEvents = useMemo<TimelineEvent[]>(() => {
        const events: TimelineEvent[] = [
            { id: 'meeting-started', t: 0, kind: 'meeting', title: 'Meeting started', text: 'HomePilot is taking notes in this dedicated meeting conversation.' },
        ];
        for (const slide of view.slideList) {
            events.push({
                id: `slide-${slide.id || slide.t || slide.url}`,
                t: slide.t ?? 0,
                kind: 'slide',
                title: 'Slide changed',
                text: slide.caption || 'New shared-screen context captured',
            });
        }
        for (const chip of view.chips) {
            if (chip.dismissed) continue;
            const kind = chip.kind === 'decision' ? 'decision' : chip.kind === 'action' ? 'action' : 'question';
            events.push({
                id: `chip-${chip.id}`,
                t: chip.t0 ?? 0,
                kind,
                title: chip.kind === 'decision' ? 'Decision' : chip.kind === 'action' ? 'Action item' : 'Key point',
                text: chip.text,
            });
        }
        events.push(...sourceEvents);
        /*
         * Your questions are deliberately absent here.
         *
         * The Timeline is the meeting's own record — decisions, slides, capture changes — and
         * interleaving a private side-channel into it by timestamp made an exchange nobody else
         * was party to look like a moment of the meeting. They have their own tab now.
         */
        return events.sort((a, b) => a.t - b.t);
    }, [view.slideList, view.chips, sourceEvents]);

    /** Exchanges, not turns: a question and its answer are one thing to count. */
    const askCount = chatTurns.filter((turn) => turn.role === 'user').length;

    const sendQuestion = async () => {
        const text = input.trim();
        if (!text) return;
        const meetingId = view.meetingId;
        const now = view.elapsedMs;
        const pendingId = crypto.randomUUID();
        setInput('');
        setChatTurns((turns) => [
            ...turns,
            { id: crypto.randomUUID(), role: 'user', text, createdAt: now },
            { id: pendingId, role: 'assistant', text: '', pending: true, createdAt: now },
        ]);
        /*
         * Switch to the lane the answer is arriving in.
         *
         * The exchange used to be rendered only inside the Timeline, while the workspace opens
         * on Transcript — so pressing Enter produced no visible change anywhere, and the
         * question looked like it had been swallowed. Sending is a request to see the answer.
         */
        setTab('ask');

        const settle = (patch: Partial<ChatTurn>) => {
            setChatTurns((turns) => turns.map((turn) => (
                turn.id === pendingId ? { ...turn, ...patch, pending: false } : turn
            )));
        };

        if (!meetingId) {
            // Before the session id lands there is nothing to ask *about*, and asking the
            // general model instead would answer from no transcript while looking authoritative.
            settle({ text: 'This meeting is still connecting — ask again in a moment.', error: true });
            return;
        }

        try {
            const response = await fetch(
                `${backendBase()}/v1/meetingsense/${encodeURIComponent(meetingId)}/ask`,
                {
                    method: 'POST',
                    credentials: 'include',
                    headers: requestHeaders(),
                    body: JSON.stringify({ text }),
                },
            );
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const body = await response.json();
            const answer = String(body?.text ?? '').trim();
            if (!answer) {
                settle({ text: 'That question could not be answered from this meeting.', error: true });
                return;
            }
            settle({ text: answer, cited: Array.isArray(body?.cited) ? body.cited : [] });
        } catch (sendError) {
            const message = sendError instanceof Error ? sendError.message : 'request failed';
            settle({ text: `Could not answer from this meeting: ${message}`, error: true });
        }
    };

    /**
     * Put one answer into the meeting's permanent record, because you asked for it.
     *
     * Recorded as a `suggestion` artifact — beside the notes rather than merged into them.
     * Merged in, an assistant's paragraph becomes indistinguishable from something a person
     * said, which is the exact confusion this whole lane exists to prevent.
     */
    const keepInNotes = async (turn: ChatTurn) => {
        const meetingId = view.meetingId;
        if (!meetingId || turn.kept || !turn.text.trim()) return;
        setChatTurns((turns) => turns.map((row) => (row.id === turn.id ? { ...row, kept: true } : row)));
        try {
            await fetch(`${backendBase()}/v1/meetingsense/${encodeURIComponent(meetingId)}/notes`, {
                method: 'POST',
                credentials: 'include',
                headers: requestHeaders(),
                body: JSON.stringify({ op: 'suggestion', kind: 'note', text: turn.text }),
            });
        } catch {
            // Reverted, so the button does not claim something was kept that was not.
            setChatTurns((turns) => turns.map((row) => (row.id === turn.id ? { ...row, kept: false } : row)));
        }
    };

    /** Jump from a citation to the moment it names. */
    const seekTo = (ms: number) => {
        setTab('transcript');
        const id = segmentAt(view.segments, ms);
        if (!id) return;
        window.requestAnimationFrame(() => {
            // Every step here is optional on some runtime — `CSS.escape` is absent in older
            // embedded webviews, `scrollIntoView` in others. Following a citation is a
            // convenience; the tab switch above is the part that matters, and it has already
            // happened. Throwing from inside an animation frame would take the workspace down
            // mid-meeting for a scroll.
            try {
                const selector = typeof CSS?.escape === 'function'
                    ? `[data-segment-id="${CSS.escape(id)}"]`
                    : null;
                if (!selector) return;
                const node = document.querySelector(selector);
                if (node && typeof (node as HTMLElement).scrollIntoView === 'function') {
                    (node as HTMLElement).scrollIntoView({ block: 'center', behavior: 'smooth' });
                }
            } catch {
                // A citation that does not scroll is not worth an exception.
            }
        });
    };

    if (!host) return null;

    const ending = view.phase === 'stopping';
    const ended = view.phase === 'ended';
    const active = !ended && !ending;
    const role = modeLabel(view.mode) || (capture.mode === 'note-taker' || !capture.mode ? 'Note taker' : capture.mode);
    const sourceCount = [captureStatus.meetingAudio, captureStatus.microphone]
        .filter((source) => source.requested && source.health !== 'off').length;
    const body = notesBody(record?.notes);
    const meeting = record?.meeting || null;
    const recapTitle = titleOf(meeting, 'Meeting recap');
    const recapMeta = [dayLabel(meeting), durationLabel(meeting)].filter(Boolean).join(' · ');

    return createPortal(
        <div className="absolute inset-0 z-[35] flex min-h-0 flex-col overflow-hidden bg-[#111214] text-white" data-testid="meeting-workspace">
            <header className="shrink-0 border-b border-white/[0.08] bg-[#141519] px-4 py-3 sm:px-5">
                <div className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                            <span className={ended || ending ? 'text-white/65' : 'font-semibold text-emerald-300'}>
                                {starting ? '● Connecting' : ending ? 'Meeting ended · Preparing recap…' : ended ? 'Meeting recap' : '● Live'}
                            </span>
                            {!ended ? <span className="font-mono text-white/55">{elapsedLabel(view.elapsedMs)}</span> : null}
                            <span className="text-white/55">{role}</span>
                            <span className="text-white/35">🎙 {sourceCount} audio source{sourceCount === 1 ? '' : 's'}</span>
                            <span className="text-white/35">🖥 {captureStatus.screen.requested ? healthCopy(captureStatus.screen) : 'Off'}</span>
                        </div>
                        {error || view.error ? <div className="mt-1 text-[11px] text-red-300/80">{error || view.error}</div> : null}
                    </div>
                    {active ? (
                        <button
                            type="button"
                            data-testid="ms-workspace-end"
                            onClick={() => setConfirmEnd(true)}
                            className="inline-flex h-9 shrink-0 items-center gap-2 rounded-xl border border-red-400/25 bg-red-500/10 px-3.5 text-xs font-semibold text-red-200 hover:bg-red-500/15"
                        >
                            <Square size={13} /> End meeting
                        </button>
                    ) : onClose ? (
                        /*
                         * The way out.
                         *
                         * The workspace is a full-screen portal over the application, and once
                         * a meeting ended it offered no control at all: the only exit was to
                         * navigate to a different conversation somewhere underneath it, which
                         * is not reachable from on top of it. That is a dead end, and it is
                         * the missing "close" button.
                         */
                        <button
                            type="button"
                            data-testid="ms-workspace-close"
                            onClick={onClose}
                            className="inline-flex h-9 shrink-0 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 text-xs font-semibold text-white/75 hover:bg-white/10"
                        >
                            <X size={13} /> Close
                        </button>
                    ) : null}
                </div>
            </header>

            <div className="flex min-h-0 flex-1 flex-col md:flex-row">
                <section className="flex min-h-0 min-w-0 flex-1 flex-col">
                    {ended ? (
                        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
                            <div className="mx-auto max-w-4xl space-y-5">
                                <div>
                                    <h2 className="text-xl font-semibold tracking-[-0.02em] text-white">{recapTitle}</h2>
                                    {recapMeta ? <p className="mt-1 text-xs text-white/40">{recapMeta}</p> : null}
                                </div>
                                <MeetingSummary body={body} pending={pendingNotes} />
                                {view.slideList.length ? (
                                    <section className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4">
                                        <h3 className="text-sm font-semibold text-white/90">Key screens</h3>
                                        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
                                            {view.slideList.slice(-9).map((slide, index) => (
                                                <figure key={slide.id || `${slide.url}-${index}`} className="overflow-hidden rounded-xl border border-white/[0.08] bg-black">
                                                    <img src={slide.url} alt={slide.caption || `Meeting screen ${index + 1}`} className="aspect-video w-full object-cover" />
                                                    <figcaption className="px-2.5 py-2 text-[10px] leading-4 text-white/45">{slide.caption || stampLabel(slide.t)}</figcaption>
                                                </figure>
                                            ))}
                                        </div>
                                    </section>
                                ) : null}
                                <details className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4">
                                    <summary className="cursor-pointer text-sm font-semibold text-white/85">Transcript · {view.segments.length}</summary>
                                    <div className="mt-4 space-y-2">
                                        {view.segments.map((segment, index) => (
                                            <div key={segment.id || index} className="grid grid-cols-[64px_70px_1fr] gap-2 text-xs leading-5">
                                                <span className="font-mono text-white/30">{stampLabel(segment.t0)}</span>
                                                <span className="font-medium text-white/55">{speakerLabel(segment.speaker)}</span>
                                                <span className="text-white/75">{segment.text}</span>
                                            </div>
                                        ))}
                                    </div>
                                </details>
                            </div>
                        </div>
                    ) : (
                        <>
                            <div className="flex shrink-0 items-center gap-1 border-b border-white/[0.07] px-4 py-2.5">
                                <button type="button" onClick={() => setTab('timeline')} className={`rounded-lg px-3 py-1.5 text-xs ${tab === 'timeline' ? 'bg-white/10 text-white' : 'text-white/45 hover:text-white/75'}`}>
                                    <MessageSquare size={13} className="mr-1.5 inline" /> Timeline
                                </button>
                                <button type="button" onClick={() => setTab('transcript')} className={`rounded-lg px-3 py-1.5 text-xs ${tab === 'transcript' ? 'bg-white/10 text-white' : 'text-white/45 hover:text-white/75'}`}>
                                    <FileText size={13} className="mr-1.5 inline" /> Transcript
                                    {/* The count is the live proof that transcription is
                                        working, visible from either tab — so the Timeline no
                                        longer reads as "nothing is happening". */}
                                    {view.segments.length ? (
                                        <span className="ml-1.5 text-white/40" data-testid="ms-transcript-count">
                                            {view.segments.length}
                                        </span>
                                    ) : null}
                                </button>
                                {/* The private lane. Separate from both other tabs on purpose:
                                    the Transcript is what was said in the room and the Timeline
                                    is the meeting's own record, and your questions are neither. */}
                                <button type="button" data-testid="ms-tab-ask" onClick={() => setTab('ask')} className={`rounded-lg px-3 py-1.5 text-xs ${tab === 'ask' ? 'bg-white/10 text-white' : 'text-white/45 hover:text-white/75'}`}>
                                    <Sparkles size={13} className="mr-1.5 inline" /> Ask
                                    {askCount ? (
                                        <span className="ml-1.5 text-white/40" data-testid="ms-ask-count">{askCount}</span>
                                    ) : null}
                                </button>
                            </div>
                            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
                                <div className="mx-auto max-w-3xl">
                                    {tab === 'ask' ? (
                                        <div className="space-y-3" aria-label="Your questions about this meeting" data-testid="ms-ask-lane">
                                            {/*
                                              Said once, at the top, and not repeated per turn.
                                              The single most important property of this lane is
                                              that it is *not* the meeting — a user who thinks
                                              their question was spoken into the room, or will
                                              appear in the recap somebody else reads, is being
                                              misled by the interface.
                                            */}
                                            <p className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-[11px] leading-5 text-white/40" data-testid="ms-ask-privacy">
                                                Private to you. These questions are answered from the live transcript,
                                                and are not part of the meeting — they are not spoken into the call, not
                                                recorded in the transcript, and not in the recap unless you keep one.
                                            </p>
                                            {chatTurns.length === 0 ? (
                                                <div className="py-8 text-center text-sm text-white/35" data-testid="ms-ask-empty">
                                                    Ask anything about what has been said so far — “what did they say about tax cuts?”
                                                </div>
                                            ) : null}
                                            {chatTurns.map((turn) => (turn.role === 'user' ? (
                                                <div key={turn.id} className="flex justify-end" data-testid="ms-ask-question">
                                                    <div className="max-w-[85%] rounded-2xl rounded-br-md border border-sky-400/20 bg-sky-400/[0.08] px-3.5 py-2.5">
                                                        <div className="text-[10px] font-semibold uppercase tracking-wide text-sky-200/70">You · private</div>
                                                        <p className="mt-1 text-sm leading-5 text-white/90">{turn.text}</p>
                                                    </div>
                                                </div>
                                            ) : (
                                                <div key={turn.id} className="flex justify-start" data-testid="ms-ask-answer">
                                                    <div className={`max-w-[85%] rounded-2xl rounded-bl-md border px-3.5 py-2.5 ${turn.error ? 'border-red-400/20 bg-red-500/[0.07]' : 'border-white/[0.08] bg-white/[0.03]'}`}>
                                                        <div className="text-[10px] font-semibold uppercase tracking-wide text-white/40">HomePilot</div>
                                                        {turn.pending ? (
                                                            <p className="mt-1 text-sm leading-5 text-white/45" data-testid="ms-ask-pending">Looking through the meeting…</p>
                                                        ) : (
                                                            <>
                                                                <p className={`mt-1 text-sm leading-5 ${turn.error ? 'text-red-200/85' : 'text-white/85'}`}>
                                                                    {answerParts(turn.text, turn.cited).map((part, index) => (
                                                                        part.kind === 'cite' ? (
                                                                            <button
                                                                                key={`c${index}`}
                                                                                type="button"
                                                                                onClick={() => seekTo(part.ms)}
                                                                                title="Show this in the transcript"
                                                                                data-testid="ms-ask-cite"
                                                                                className="rounded bg-white/10 px-1 font-mono text-[11px] text-sky-200 hover:bg-white/15"
                                                                            >
                                                                                {part.text}
                                                                            </button>
                                                                        ) : (
                                                                            <React.Fragment key={`t${index}`}>{part.text}</React.Fragment>
                                                                        )
                                                                    ))}
                                                                </p>
                                                                {!turn.error ? (
                                                                    /* The "optional" half of the ask: nothing reaches the
                                                                       meeting's record unless it is put there on purpose. */
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => void keepInNotes(turn)}
                                                                        disabled={turn.kept}
                                                                        data-testid="ms-ask-keep"
                                                                        className="mt-2 text-[10px] text-white/35 hover:text-white/65 disabled:text-emerald-300/70"
                                                                    >
                                                                        {turn.kept ? '✓ Kept in meeting notes' : '+ Keep in meeting notes'}
                                                                    </button>
                                                                ) : null}
                                                            </>
                                                        )}
                                                    </div>
                                                </div>
                                            )))}
                                        </div>
                                    ) : tab === 'timeline' ? (
                                        <div className="space-y-3">
                                            {semanticEvents.map((event) => (
                                                <div key={event.id} className="grid grid-cols-[54px_1fr] gap-3">
                                                    <div className="pt-1 font-mono text-[10px] text-white/25">{stampLabel(event.t)}</div>
                                                    <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-3.5 py-3">
                                                        <div className="text-xs font-semibold text-white/75">{event.title}</div>
                                                        {event.text ? <div className="mt-1 text-sm leading-5 text-white/85">{event.text}</div> : null}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    ) : (
                                        <div className="space-y-2" aria-label="Live transcript">
                                            {view.segments.length === 0 && !view.partial ? <div className="py-10 text-center text-sm text-white/35">Transcript will appear here as people speak.</div> : null}
                                            {view.segments.map((segment, index) => (
                                                <div
                                                    key={segment.id || index}
                                                    data-segment-id={segment.id || undefined}
                                                    className="grid grid-cols-[64px_70px_1fr] gap-2 rounded-lg px-2 py-1.5 text-xs leading-5 hover:bg-white/[0.025]"
                                                >
                                                    <span className="font-mono text-white/30">{stampLabel(segment.t0)}</span>
                                                    {/* "You" and "Them" are different colours, not just different
                                                        words: at a glance down a column the distinction that matters
                                                        is who was talking, and two greys do not carry it. */}
                                                    <span className={`font-medium ${segment.speaker === 'me' ? 'text-emerald-300/75' : 'text-white/55'}`}>
                                                        {speakerLabel(segment.speaker)}
                                                    </span>
                                                    <span className="text-white/80">{segment.text}</span>
                                                </div>
                                            ))}
                                            {view.partial ? (
                                                <div className="grid grid-cols-[64px_70px_1fr] gap-2 rounded-lg px-2 py-1.5 text-xs leading-5 opacity-55">
                                                    <span className="font-mono text-white/30">{stampLabel(view.partial.t0)}</span>
                                                    <span className="font-medium text-white/55">{speakerLabel(view.partial.speaker)}</span>
                                                    <span className="text-white/70">{view.partial.text}</span>
                                                </div>
                                            ) : null}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </>
                    )}

                    <div className="shrink-0 border-t border-white/[0.08] bg-[#141519] p-3 sm:p-4">
                        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-white/10 bg-[#090a0b] p-2">
                            <textarea
                                value={input}
                                onChange={(event) => setInput(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter' && !event.shiftKey) {
                                        event.preventDefault();
                                        void sendQuestion();
                                    }
                                }}
                                rows={1}
                                placeholder={ended ? 'Ask about this meeting…' : 'Ask about this meeting…'}
                                className="max-h-32 min-h-[38px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-white outline-none placeholder:text-white/30"
                            />
                            {/* Icon-only, so the name has to be said out loud: a screen
                                reader announced this as "button" with nothing after it. */}
                            <button type="button" aria-label="Ask about this meeting" title="Ask about this meeting" onClick={() => void sendQuestion()} disabled={!input.trim()} className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white text-black disabled:opacity-35">
                                <Send size={15} aria-hidden="true" />
                            </button>
                        </div>
                        {/*
                          This read "Using current meeting context · same conversation", and
                          both halves were false: the question went to the general chat model
                          with no transcript, and it was written into the meeting's own
                          conversation. Now both halves are true and worth saying — the answer
                          comes from the transcript, and the exchange stays out of the record.
                        */}
                        <div className="mx-auto mt-1.5 max-w-3xl text-[10px] text-white/25" data-testid="ms-ask-footnote">
                            Answered from this meeting’s transcript · private to you, not added to the transcript
                        </div>
                    </div>
                </section>

                {!ended ? (
                    <aside className="shrink-0 border-t border-white/[0.08] bg-[#121316] p-4 md:w-[320px] md:border-l md:border-t-0 lg:w-[360px]">
                        <div className="space-y-3">
                            <ScreenPreview stream={screenStream} status={captureStatus.screen} onResume={onResumeScreen} />
                            <SourceRow icon={<Volume2 size={14} />} label="Meeting audio" status={captureStatus.meetingAudio} />
                            <SourceRow icon={<Mic2 size={14} />} label="My microphone" status={captureStatus.microphone} />
                            <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-3 text-[10px] leading-4 text-white/35">
                                These indicators report the actual capture path. Permission alone is not shown as “Receiving.”
                            </div>
                        </div>
                    </aside>
                ) : null}
            </div>

            {confirmEnd ? (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/65 p-5 backdrop-blur-sm">
                    <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#18191d] p-5 shadow-2xl">
                        <div className="flex items-start gap-3">
                            <span className="mt-0.5 rounded-xl bg-red-500/10 p-2 text-red-300"><AlertTriangle size={17} /></span>
                            <div>
                                <h3 className="text-sm font-semibold text-white">End this meeting?</h3>
                                <p className="mt-1.5 text-xs leading-5 text-white/45">HomePilot will stop microphone and screen capture immediately, then prepare the recap from already captured material.</p>
                            </div>
                        </div>
                        <div className="mt-5 flex justify-end gap-2">
                            <button type="button" onClick={() => setConfirmEnd(false)} className="h-9 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 text-xs text-white/65">Cancel</button>
                            <button type="button" onClick={() => { setConfirmEnd(false); onEnd(); }} className="h-9 rounded-xl bg-red-500 px-3.5 text-xs font-semibold text-white hover:bg-red-400">End & create recap</button>
                        </div>
                    </div>
                </div>
            ) : null}
        </div>,
        host,
    );
}

export default MeetingWorkspace;
