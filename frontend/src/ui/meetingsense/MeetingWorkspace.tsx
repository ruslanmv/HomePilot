import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
    AlertTriangle,
    ArrowDown,
    CheckCircle2,
    ChevronDown,
    CircleHelp,
    FileText,
    Info,
    ListChecks,
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
import MeetingMinutes from './MeetingMinutes';
import { backendBase, requestHeaders } from './api';
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
    summaryDocs,
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
    /**
     * `extractive` when the server quoted the transcript because no model answered.
     *
     * Surfaced rather than swallowed: an answer that is the meeting's own words and an
     * answer that was written are different things, and a reader who cannot tell will either
     * distrust the written ones or over-trust the quoted ones.
     */
    degraded?: string | null;
};

/**
 * Server wording turned into something a person can act on. "session is idle, not live" is
 * true and useless; what the user needs to know is whether the recording is still going.
 */
export function friendlyMeetingError(raw: string | null | undefined): string | null {
    if (!raw) return null;
    const text = String(raw);
    const lower = text.toLowerCase();
    if (lower.includes('not live') || lower.includes('not resumable') || lower.includes('not_resumable')) {
        return 'The connection to HomePilot dropped and this recording could not continue. End the meeting and start a new one.';
    }
    if (lower.includes('socket closed') || lower.includes('session socket')) {
        return 'Reconnecting to HomePilot… what is said meanwhile is kept and sent when the connection is back.';
    }
    return text;
}

type TranscriptSegment = MeetingView['segments'][number];
type Turn = { key: string; speaker: string | null; t0: number; lines: TranscriptSegment[] };

/** Consecutive lines from the same speaker read as one turn, the way a chat does. */
export function groupTurns(segments: TranscriptSegment[]): Turn[] {
    const turns: Turn[] = [];
    for (const segment of segments) {
        const speaker = segment.speaker ?? null;
        const t0 = Number(segment.t0 ?? 0);
        const last = turns[turns.length - 1];
        const lastLine = last ? last.lines[last.lines.length - 1] : undefined;
        const gap = lastLine ? t0 - Number(lastLine.t1 ?? lastLine.t0 ?? 0) : 0;
        if (last && last.speaker === speaker && gap < 30000) {
            last.lines.push(segment);
        } else {
            turns.push({ key: String(segment.id || `${speaker}-${t0}-${turns.length}`), speaker, t0, lines: [segment] });
        }
    }
    return turns;
}

function SpeakerBadge({ speaker }: { speaker: string | null }) {
    const label = speakerLabel(speaker) || 'Speaker';
    const me = speaker === 'me';
    return (
        <span
            aria-hidden="true"
            className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full text-[11px] font-semibold ${
                me
                    ? 'bg-gradient-to-br from-cyan-400 via-blue-500 to-purple-500 text-white shadow-[0_0_0_3px_rgba(99,102,241,0.15)]'
                    : 'border border-white/10 bg-white/[0.06] text-white/70'}`}
        >
            {label.slice(0, 1).toUpperCase()}
        </span>
    );
}

/** Five bars that follow the captured level, so "is it hearing me" is answered at a glance. */
function LevelMeter({ level, on }: { level: number; on: boolean }) {
    // RMS of speech sits around 0.02–0.2; a square root spreads that across the bars.
    const value = on ? Math.min(1, Math.sqrt(Math.max(0, level || 0)) * 2.4) : 0;
    return (
        <span className="flex h-3.5 items-end gap-[2px]" aria-hidden="true">
            {[0.15, 0.35, 0.55, 0.75, 0.92].map((threshold) => (
                <span
                    key={threshold}
                    className={`w-[3px] rounded-full transition-all duration-150 ${value >= threshold ? 'bg-gradient-to-t from-blue-500 to-cyan-300' : 'bg-white/15'}`}
                    style={{ height: `${30 + threshold * 70}%` }}
                />
            ))}
        </span>
    );
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
    const metered = status.health === 'receiving' || status.health === 'no_signal';
    return (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.025] px-3 py-2.5">
            <div className="flex items-center gap-2.5">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-white/[0.05] text-white/55">{icon}</span>
                <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-medium text-white/85">{label}</span>
                        {metered ? <LevelMeter level={status.level} on={status.health === 'receiving'} /> : null}
                    </span>
                    <span className="flex min-w-0 items-center gap-1.5 text-[10px]">
                        <span className={`shrink-0 font-medium ${healthTone(status)}`}>{healthCopy(status)}</span>
                        {status.label ? <span className="truncate text-white/35">· {status.label}</span> : null}
                    </span>
                </span>
            </div>
            {status.error ? <div className="mt-1.5 pl-[38px] text-[10px] leading-4 text-red-200/75">{status.error}</div> : null}
        </div>
    );
}


function AskLane({
    turns,
    live,
    onSeek,
    onKeep,
}: {
    turns: ChatTurn[];
    live: boolean;
    onSeek: (ms: number) => void;
    onKeep: (turn: ChatTurn) => void | Promise<void>;
}) {
    return (
        <div className="space-y-3" aria-label="Your questions about this meeting" data-testid={live ? 'ms-ask-lane' : 'ms-ended-ask'}>
            <p className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-[11px] leading-5 text-white/40" data-testid="ms-ask-privacy">
                Private to you. These questions are answered from the {live ? 'live transcript available so far' : 'meeting transcript'},
                and are not part of the meeting — they are not spoken into the call, not recorded
                in the transcript, and not in the recap unless you keep one.
            </p>
            {turns.length === 0 ? (
                <div className="py-8 text-center text-sm text-white/35" data-testid="ms-ask-empty">
                    {live
                        ? 'Ask anything about what has been said so far — “what are they talking about?”'
                        : 'Ask anything about what was said in this meeting — “what did they decide?”'}
                </div>
            ) : null}
            {turns.map((turn) => (turn.role === 'user' ? (
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
                                                onClick={() => onSeek(part.ms)}
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
                                {turn.degraded === 'extractive' ? (
                                    <p className="mt-1.5 text-[10px] leading-4 text-amber-100/55" data-testid="ms-ask-degraded">
                                        Quoted from the transcript — no language model was reachable to write an answer.
                                    </p>
                                ) : null}
                                {!turn.error ? (
                                    <button
                                        type="button"
                                        onClick={() => void onKeep(turn)}
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
        <div className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#141416]">
            <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
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
    // Two lanes only: what was said, and your private questions about it. The Timeline tab
    // (capture changes, slide changes) is gone — decisions and actions now sit in the side
    // panel as Highlights, which is the part of it people actually used.
    const [tab, setTab] = useState<'transcript' | 'ask'>('transcript');
    const [confirmEnd, setConfirmEnd] = useState(false);
    const [input, setInput] = useState('');
    const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);

    // The chat page's own header buttons (Call, Chat settings, New chat) are fixed above
    // everything and sat on top of "End meeting". They act on the chat underneath, which is
    // not what anyone wants mid-meeting, so they step aside while this is open.
    useEffect(() => {
        document.body.classList.add('hp-meeting-open');
        return () => document.body.classList.remove('hp-meeting-open');
    }, []);

    // A clock that ticks on its own. The server's elapsed time arrives with status frames, and
    // a timer that sits on 00:00 between them reads as "nothing is happening".
    const isRecording = view.phase === 'live' || view.phase === 'reconnecting';
    const clockStart = useRef<number | null>(null);
    const [clockNow, setClockNow] = useState(() => Date.now());
    useEffect(() => {
        if (!isRecording) return undefined;
        if (clockStart.current === null) clockStart.current = Date.now() - (view.elapsedMs || 0);
        const id = window.setInterval(() => setClockNow(Date.now()), 1000);
        return () => window.clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isRecording]);
    const shownElapsed = Math.max(
        view.elapsedMs || 0,
        isRecording && clockStart.current !== null ? clockNow - clockStart.current : 0,
    );

    // Follow the transcript while the reader is at the bottom; stop following the moment
    // they scroll up to read, and offer the way back.
    const scrollRef = useRef<HTMLDivElement | null>(null);
    const [following, setFollowing] = useState(true);
    const onTranscriptScroll = () => {
        const el = scrollRef.current;
        if (!el) return;
        setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight < 96);
    };
    const jumpToLive = () => {
        const el = scrollRef.current;
        if (!el) return;
        el.scrollTop = el.scrollHeight;
        setFollowing(true);
    };
    useEffect(() => {
        if (tab !== 'transcript' || !following) return;
        const el = scrollRef.current;
        if (el) el.scrollTop = el.scrollHeight;
    }, [view.segments.length, view.partial?.text, tab, following]);

    const turns = useMemo(() => groupTurns(view.segments), [view.segments]);
    const highlights = useMemo(
        () => view.chips.filter((chip) => !chip.dismissed && (chip.kind === 'decision' || chip.kind === 'action' || chip.kind === 'question')),
        [view.chips],
    );

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
        if (view.phase !== 'ended') setTab('ask');

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
                    /*
                     * The compute target rides along **only while the meeting is live**.
                     *
                     * The server already holds the target chosen at setup, and for a live
                     * meeting `capture` is that same choice — so sending it is a harmless
                     * restatement. Once the meeting has ended and been reopened from
                     * History, `capture` is no longer this meeting's anything: it is
                     * whatever the app's chat settings happen to say now, read at mount.
                     * Sending that as an override would silently beat the model the meeting
                     * was actually set up with, which is the behaviour storing the
                     * preference per meeting exists to prevent.
                     *
                     * Omitted, the server falls back to the meeting's stored preference and
                     * then to the install's configured provider — both better informed than
                     * this component is.
                     */
                    body: JSON.stringify(
                        view.phase === 'ended'
                            ? { text }
                            : {
                                text,
                                ...(capture.conversationProvider ? { provider: capture.conversationProvider } : {}),
                                ...(capture.conversationModel ? { model: capture.conversationModel } : {}),
                                ...(capture.conversationBaseUrl ? { base_url: capture.conversationBaseUrl } : {}),
                            },
                    ),
                },
            );
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const body = await response.json();
            const answer = String(body?.text ?? '').trim();
            if (!answer) {
                /*
                 * The server does not send an empty answer any more — it says which kind of
                 * nothing it found, in a sentence. This is the older-server path, and the
                 * wording matters: "that question could not be answered from this meeting"
                 * was printed beside a transcript the user could read on screen, which reads
                 * as the feature being broken rather than as the meeting being quiet.
                 */
                settle({
                    text: 'Nothing in what has been captured of this meeting answers that yet.',
                    error: true,
                });
                return;
            }
            settle({
                text: answer,
                cited: Array.isArray(body?.cited) ? body.cited : [],
                degraded: typeof body?.degraded === 'string' ? body.degraded : null,
            });
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
        if (view.phase === 'ended') {
            const details = document.querySelector<HTMLDetailsElement>('[data-testid="ms-ended-transcript"]');
            if (details) details.open = true;
        } else {
            setTab('transcript');
        }
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
    const body = notesBody(record?.notes);
    const meeting = record?.meeting || null;
    const recapTitle = titleOf(meeting, 'Meeting recap');
    const recapMeta = [dayLabel(meeting), durationLabel(meeting)].filter(Boolean).join(' · ');

    return createPortal(
        <div className="absolute inset-0 z-[35] flex min-h-0 flex-col overflow-hidden bg-[#090909] text-white" data-testid="meeting-workspace">
            <header className="shrink-0 border-b border-white/[0.06] bg-[#0d0d10]/95 px-4 py-3 backdrop-blur sm:px-6">
                <div className="flex items-center gap-3">
                    {ended && onClose ? (
                        <button
                            type="button"
                            data-testid="ms-workspace-close"
                            onClick={onClose}
                            title="Close meeting recap"
                            className="inline-flex h-9 shrink-0 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 text-xs font-semibold text-white/75 hover:bg-white/10"
                        >
                            <X size={13} /> Close
                        </button>
                    ) : null}
                    <div className="flex min-w-0 items-center gap-2.5">
                        {!ended && !ending ? (
                            <span className="relative flex h-2.5 w-2.5 shrink-0" aria-hidden="true">
                                {isRecording && !starting ? <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400/70" /> : null}
                                <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${starting || view.phase === 'reconnecting' ? 'bg-amber-300' : 'bg-red-500'}`} />
                            </span>
                        ) : null}
                        <span className="truncate text-sm font-semibold text-white/90" data-testid="ms-workspace-state">
                            {starting
                                ? 'Connecting…'
                                : ending
                                    ? 'Meeting ended · Preparing recap…'
                                    : ended
                                        ? 'Meeting recap'
                                        : view.phase === 'reconnecting'
                                            ? 'Reconnecting…'
                                            : 'Recording'}
                        </span>
                        {!ended ? (
                            <span className="rounded-md bg-white/[0.06] px-2 py-0.5 font-mono text-xs tabular-nums text-white/75" data-testid="ms-workspace-elapsed">
                                {elapsedLabel(shownElapsed)}
                            </span>
                        ) : null}
                        {!ended && role && role !== 'Note taker' ? (
                            <span className="hidden rounded-full border border-purple-400/25 bg-purple-500/10 px-2 py-0.5 text-[11px] text-purple-200 sm:inline">{role}</span>
                        ) : null}
                    </div>
                    {!ended ? (
                        <div className="ml-2 hidden min-w-0 items-center gap-1.5 lg:flex" aria-label="Capture status">
                            {[
                                { key: 'audio', icon: <Volume2 size={12} />, label: 'Call audio', status: captureStatus.meetingAudio },
                                { key: 'mic', icon: <Mic2 size={12} />, label: 'Mic', status: captureStatus.microphone },
                                { key: 'screen', icon: <MonitorUp size={12} />, label: 'Screen', status: captureStatus.screen },
                            ].map((chip) => (
                                <span key={chip.key} className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.07] bg-white/[0.03] px-2.5 py-1 text-[11px] text-white/60" title={healthCopy(chip.status)}>
                                    <span className="text-white/45">{chip.icon}</span>
                                    {chip.label}
                                    <span className={`text-[11px] ${chip.status.requested ? healthTone(chip.status) : 'text-white/30'}`}>
                                        {chip.status.requested ? healthCopy(chip.status) : 'Off'}
                                    </span>
                                </span>
                            ))}
                        </div>
                    ) : null}
                    <div className="flex-1" />
                    {active ? (
                        <button
                            type="button"
                            data-testid="ms-workspace-end"
                            onClick={() => setConfirmEnd(true)}
                            className="inline-flex h-9 shrink-0 items-center gap-2 rounded-xl bg-red-500/90 px-4 text-xs font-semibold text-white shadow-[0_8px_24px_-12px_rgba(239,68,68,0.8)] transition hover:bg-red-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-300/70"
                        >
                            <Square size={12} fill="currentColor" /> End meeting
                        </button>
                    ) : null}
                </div>
                {view.notice && !ended ? (
                    <div className="mt-2.5 flex items-start gap-2 rounded-xl border border-blue-400/20 bg-blue-500/[0.08] px-3 py-2 text-xs leading-5 text-blue-100/85" role="status" data-testid="ms-workspace-notice">
                        <Info size={14} className="mt-0.5 shrink-0 text-blue-300" /> {view.notice}
                    </div>
                ) : null}
                {friendlyMeetingError(error || view.error) ? (
                    <div className="mt-2.5 flex items-start gap-2 rounded-xl border border-amber-300/20 bg-amber-400/[0.08] px-3 py-2 text-xs leading-5 text-amber-100/90" role="alert" data-testid="ms-workspace-error">
                        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-300" /> {friendlyMeetingError(error || view.error)}
                    </div>
                ) : null}
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
                                {/* The rolling notes are what the reader watched being written;
                                    this is the document written from the whole transcript once
                                    the meeting ended. Both, in that order: the glance first and
                                    the thing they are going to send second. */}
                                <MeetingMinutes
                                    meetingId={view.meetingId}
                                    documents={summaryDocs(record)}
                                    hasTranscript={view.segments.length > 0}
                                    modelTarget={{
                                        provider: capture.summaryProvider,
                                        model: capture.summaryModel,
                                        baseUrl: capture.summaryBaseUrl,
                                    }}
                                />
                                <section className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4">
                                    <div className="mb-3 flex items-center gap-2">
                                        <Sparkles size={14} className="text-sky-200/70" />
                                        <h3 className="text-sm font-semibold text-white/90">Ask this meeting</h3>
                                    </div>
                                    <AskLane
                                        turns={chatTurns}
                                        live={false}
                                        onSeek={seekTo}
                                        onKeep={keepInNotes}
                                    />
                                </section>
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
                                <details data-testid="ms-ended-transcript" className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4">
                                    <summary className="cursor-pointer text-sm font-semibold text-white/85">Transcript · {view.segments.length}</summary>
                                    <div className="mt-4 space-y-2">
                                        {view.segments.map((segment, index) => (
                                            <div
                                                key={segment.id || index}
                                                data-segment-id={segment.id || undefined}
                                                className="grid grid-cols-[64px_70px_1fr] gap-2 text-xs leading-5"
                                            >
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
                            <div className="flex shrink-0 items-center gap-3 border-b border-white/[0.06] px-4 py-2.5 sm:px-6">
                                <div className="inline-flex rounded-xl border border-white/[0.07] bg-white/[0.03] p-1" role="tablist" aria-label="Meeting views">
                                    <button
                                        type="button"
                                        role="tab"
                                        aria-selected={tab === 'transcript'}
                                        onClick={() => setTab('transcript')}
                                        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${tab === 'transcript' ? 'bg-gradient-to-r from-blue-500/25 to-purple-500/25 text-white shadow-[inset_0_0_0_1px_rgba(147,197,253,0.18)]' : 'text-white/50 hover:text-white/80'}`}
                                    >
                                        <FileText size={13} /> Transcript
                                        {/* The count is the live proof that transcription is
                                            working, visible from either tab. */}
                                        {view.segments.length ? (
                                            <span className="rounded-md bg-white/10 px-1.5 text-[10px] tabular-nums text-white/70" data-testid="ms-transcript-count">
                                                {view.segments.length}
                                            </span>
                                        ) : null}
                                    </button>
                                    {/* The private lane: your questions are not part of what was said. */}
                                    <button
                                        type="button"
                                        role="tab"
                                        aria-selected={tab === 'ask'}
                                        data-testid="ms-tab-ask"
                                        onClick={() => setTab('ask')}
                                        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${tab === 'ask' ? 'bg-gradient-to-r from-blue-500/25 to-purple-500/25 text-white shadow-[inset_0_0_0_1px_rgba(147,197,253,0.18)]' : 'text-white/50 hover:text-white/80'}`}
                                    >
                                        <Sparkles size={13} /> Ask
                                        {askCount ? (
                                            <span className="rounded-md bg-white/10 px-1.5 text-[10px] tabular-nums text-white/70" data-testid="ms-ask-count">{askCount}</span>
                                        ) : null}
                                    </button>
                                </div>
                                {tab === 'transcript' && isRecording ? (
                                    <span className="hidden items-center gap-2 whitespace-nowrap text-[11px] text-white/40 sm:inline-flex" title="Speech is turned into text on this computer as people speak">
                                        <LevelMeter level={Math.max(captureStatus.microphone.level || 0, captureStatus.meetingAudio.level || 0)} on />
                                        Live · on this computer
                                    </span>
                                ) : null}
                            </div>
                            <div className="relative min-h-0 flex-1">
                                <div ref={scrollRef} onScroll={onTranscriptScroll} className="h-full overflow-y-auto px-4 py-5 sm:px-6">
                                    <div className="mx-auto max-w-3xl">
                                        {tab === 'ask' ? (
                                            <AskLane
                                                turns={chatTurns}
                                                live
                                                onSeek={seekTo}
                                                onKeep={keepInNotes}
                                            />
                                        ) : (
                                            <div className="space-y-5" aria-label="Live transcript">
                                                {view.segments.length === 0 && !view.partial ? (
                                                    <div className="flex flex-col items-center py-16 text-center" data-testid="ms-workspace-listening">
                                                        <div className="flex h-10 items-end gap-1.5" aria-hidden="true">
                                                            {[0, 1, 2, 3, 4].map((bar) => (
                                                                <span
                                                                    key={bar}
                                                                    className="w-1.5 animate-pulse rounded-full bg-gradient-to-t from-blue-500 to-cyan-300"
                                                                    style={{ height: `${[40, 70, 100, 70, 40][bar]}%`, animationDelay: `${bar * 150}ms` }}
                                                                />
                                                            ))}
                                                        </div>
                                                        <p className="mt-4 text-sm font-medium text-white/85">{starting ? 'Connecting…' : 'Listening…'}</p>
                                                        <p className="mt-1 max-w-sm text-xs leading-5 text-white/45">
                                                            {captureStatus.meetingAudio.health === 'receiving' || captureStatus.microphone.health === 'receiving'
                                                                ? 'Words appear here a few seconds after they are spoken.'
                                                                : 'No sound reaches HomePilot yet. Check that the call is playing and your microphone is on.'}
                                                        </p>
                                                    </div>
                                                ) : null}
                                                {turns.map((turn) => (
                                                    <div key={turn.key} className="flex gap-3">
                                                        <SpeakerBadge speaker={turn.speaker} />
                                                        <div className="min-w-0 flex-1">
                                                            <div className="flex items-baseline gap-2">
                                                                <span className={`text-xs font-semibold ${turn.speaker === 'me' ? 'text-blue-200' : 'text-white/80'}`}>{speakerLabel(turn.speaker)}</span>
                                                                <span className="font-mono text-[10px] text-white/30">{stampLabel(turn.t0)}</span>
                                                            </div>
                                                            <div className="mt-1 space-y-1">
                                                                {turn.lines.map((segment, index) => (
                                                                    <p
                                                                        key={segment.id || `${turn.key}-${index}`}
                                                                        data-segment-id={segment.id || undefined}
                                                                        className="rounded-lg text-[14px] leading-6 text-white/85"
                                                                    >
                                                                        {segment.text}
                                                                    </p>
                                                                ))}
                                                            </div>
                                                        </div>
                                                    </div>
                                                ))}
                                                {view.partial ? (
                                                    <div className="flex gap-3" data-testid="ms-workspace-partial">
                                                        <SpeakerBadge speaker={view.partial.speaker ?? null} />
                                                        <div className="min-w-0 flex-1">
                                                            <div className="flex items-baseline gap-2">
                                                                <span className="text-xs font-semibold text-white/60">{speakerLabel(view.partial.speaker)}</span>
                                                                <span className="text-[10px] text-white/30">speaking…</span>
                                                            </div>
                                                            <p className="mt-1 text-[14px] italic leading-6 text-white/55">
                                                                {view.partial.text}
                                                                <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-pulse bg-blue-300/80" aria-hidden="true" />
                                                            </p>
                                                        </div>
                                                    </div>
                                                ) : null}
                                            </div>
                                        )}
                                    </div>
                                </div>
                                {tab === 'transcript' && !following && view.segments.length ? (
                                    <button
                                        type="button"
                                        onClick={jumpToLive}
                                        data-testid="ms-workspace-jump"
                                        className="absolute bottom-4 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-white/10 bg-[#17171b]/95 px-3.5 py-1.5 text-xs font-medium text-white/85 shadow-lg backdrop-blur hover:bg-[#1d1d22]"
                                    >
                                        <ArrowDown size={13} /> Jump to live
                                    </button>
                                ) : null}
                            </div>
                        </>
                    )}

                    <div className="shrink-0 border-t border-white/[0.06] bg-[#0d0d10] p-3 sm:p-4">
                        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-white/10 bg-[#141416] p-2 transition focus-within:border-purple-400/40 focus-within:shadow-[0_0_0_3px_rgba(168,85,247,0.12)]">
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
                                placeholder="Ask about this meeting…"
                                className="max-h-32 min-h-[38px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-white outline-none placeholder:text-white/30"
                            />
                            {/* Icon-only, so the name has to be said out loud: a screen
                                reader announced this as "button" with nothing after it. */}
                            <button type="button" aria-label="Ask about this meeting" title="Ask about this meeting" onClick={() => void sendQuestion()} disabled={!input.trim()} className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 text-white shadow-[0_6px_18px_-8px_rgba(99,102,241,0.9)] transition hover:brightness-110 disabled:opacity-35 disabled:shadow-none">
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
                    <aside className="shrink-0 overflow-y-auto border-t border-white/[0.06] bg-[#0d0d10] p-4 md:w-[320px] md:border-l md:border-t-0 lg:w-[340px]">
                        <div className="space-y-4">
                            <section aria-labelledby="ms-capture-title" className="rounded-2xl border border-white/[0.07] bg-[#141416] p-3">
                                <h3 id="ms-capture-title" className="px-1 pb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-white/40">Capture</h3>
                                <div className="space-y-2">
                                    <SourceRow icon={<Volume2 size={14} />} label="Call audio" status={captureStatus.meetingAudio} />
                                    <SourceRow icon={<Mic2 size={14} />} label="My microphone" status={captureStatus.microphone} />
                                    {!captureStatus.screen.requested ? (
                                        <SourceRow icon={<MonitorUp size={14} />} label="Screen" status={captureStatus.screen} />
                                    ) : null}
                                </div>
                                <p className="px-1 pt-2.5 text-[10px] leading-4 text-white/30">
                                    These indicators report the actual capture path. Permission alone is not shown as “Receiving.”
                                </p>
                            </section>
                            {captureStatus.screen.requested ? (
                                <ScreenPreview stream={screenStream} status={captureStatus.screen} onResume={onResumeScreen} />
                            ) : null}
                            {highlights.length ? (
                                <section aria-labelledby="ms-highlights-title" className="rounded-2xl border border-white/[0.07] bg-[#141416] p-3" data-testid="ms-workspace-highlights">
                                    <h3 id="ms-highlights-title" className="px-1 pb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-white/40">Highlights</h3>
                                    <ul className="space-y-1.5">
                                        {highlights.slice(-8).map((chip) => (
                                            <li key={chip.id}>
                                                <button
                                                    type="button"
                                                    onClick={() => (chip.t0 != null ? seekTo(chip.t0) : undefined)}
                                                    className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-white/[0.04]"
                                                >
                                                    <span className="mt-0.5 shrink-0">
                                                        {chip.kind === 'decision'
                                                            ? <CheckCircle2 size={13} className="text-emerald-300" />
                                                            : chip.kind === 'action'
                                                                ? <ListChecks size={13} className="text-blue-300" />
                                                                : <CircleHelp size={13} className="text-purple-300" />}
                                                    </span>
                                                    <span className="min-w-0 text-xs leading-5 text-white/80">{chip.text}</span>
                                                </button>
                                            </li>
                                        ))}
                                    </ul>
                                </section>
                            ) : null}
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
