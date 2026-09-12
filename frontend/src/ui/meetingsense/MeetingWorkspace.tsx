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
    Square,
    Volume2,
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
    dayLabel,
    durationLabel,
    notesBody,
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
    conversationId: string;
    screenStream: MediaStream | null;
    record: MeetingRecord | null;
    pendingNotes: boolean;
    starting?: boolean;
    error?: string | null;
    onEnd: () => void;
    onMute: (muted: boolean) => void;
    onResumeScreen?: () => void;
}

type ChatTurn = {
    id: string;
    role: 'user' | 'assistant';
    text: string;
    pending?: boolean;
    error?: boolean;
    createdAt: number;
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
    conversationId,
    screenStream,
    record,
    pendingNotes,
    starting = false,
    error = null,
    onEnd,
    onMute,
    onResumeScreen,
}: MeetingWorkspaceProps) {
    const host = useMainHost();
    const [tab, setTab] = useState<'timeline' | 'transcript'>('timeline');
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
        for (const turn of chatTurns) {
            events.push({
                id: `chat-${turn.id}`,
                t: Math.max(0, turn.createdAt),
                kind: turn.role === 'user' ? 'question' : 'meeting',
                title: turn.role === 'user' ? 'Your question' : 'HomePilot',
                text: turn.text || (turn.pending ? 'Thinking…' : ''),
            });
        }
        return events.sort((a, b) => a.t - b.t);
    }, [view.slideList, view.chips, sourceEvents, chatTurns]);

    const sendQuestion = async () => {
        const text = input.trim();
        if (!text) return;
        setInput('');
        const now = view.elapsedMs;
        const user: ChatTurn = { id: crypto.randomUUID(), role: 'user', text, createdAt: now };
        const pendingId = crypto.randomUUID();
        setChatTurns((turns) => [...turns, user, { id: pendingId, role: 'assistant', text: '', pending: true, createdAt: now }]);
        try {
            const provider = localStorage.getItem('homepilot_provider_chat') || 'ollama';
            const model = localStorage.getItem('homepilot_model_chat') || '';
            const providerBase = localStorage.getItem('homepilot_base_url_chat') || '';
            const response = await fetch(`${backendBase()}/chat`, {
                method: 'POST',
                credentials: 'include',
                headers: requestHeaders(),
                body: JSON.stringify({
                    message: text,
                    conversation_id: conversationId,
                    mode: 'chat',
                    provider,
                    provider_model: model || undefined,
                    provider_base_url: providerBase || undefined,
                    memoryEngine: localStorage.getItem('homepilot_memory_engine') || 'v2',
                }),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const body = await response.json();
            const answer = String(body.text ?? body.content ?? 'I could not produce an answer.');
            setChatTurns((turns) => turns.map((turn) => turn.id === pendingId ? { ...turn, text: answer, pending: false } : turn));
        } catch (sendError) {
            const message = sendError instanceof Error ? sendError.message : 'request failed';
            setChatTurns((turns) => turns.map((turn) => turn.id === pendingId ? { ...turn, text: `Could not answer from this meeting: ${message}`, pending: false, error: true } : turn));
        }
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
                            onClick={() => setConfirmEnd(true)}
                            className="inline-flex h-9 shrink-0 items-center gap-2 rounded-xl border border-red-400/25 bg-red-500/10 px-3.5 text-xs font-semibold text-red-200 hover:bg-red-500/15"
                        >
                            <Square size={13} /> End meeting
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
                                </button>
                            </div>
                            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
                                <div className="mx-auto max-w-3xl">
                                    {tab === 'timeline' ? (
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
                                                <div key={segment.id || index} className="grid grid-cols-[64px_70px_1fr] gap-2 rounded-lg px-2 py-1.5 text-xs leading-5 hover:bg-white/[0.025]">
                                                    <span className="font-mono text-white/30">{stampLabel(segment.t0)}</span>
                                                    <span className="font-medium text-white/55">{speakerLabel(segment.speaker)}</span>
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
                            <button type="button" onClick={() => void sendQuestion()} disabled={!input.trim()} className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white text-black disabled:opacity-35">
                                <Send size={15} />
                            </button>
                        </div>
                        <div className="mx-auto mt-1.5 max-w-3xl text-[10px] text-white/25">Using current meeting context · same conversation</div>
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
