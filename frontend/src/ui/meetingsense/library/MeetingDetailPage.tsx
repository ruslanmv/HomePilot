/**
 * Meeting Detail — one page for every library meeting, recorded or imported, with or without
 * a conversation behind it.
 *
 * The main column holds the task at hand (recording, overview, transcript, actions, AI chat);
 * the right column holds supporting details and can be hidden ("Hide details") for a focus
 * view, resized by dragging its edge, and opens as a drawer on small screens. The choice is
 * remembered on this device and never changes the meeting.
 *
 * Nothing here invents content: no summary until one has been written, "Speaker unknown"
 * when the transcript has no speakers, and the AI chat answers only from this meeting.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertTriangle, ArrowLeft, Bot, CalendarDays, CheckSquare, ChevronDown, Clock3, Download, ExternalLink, FileText,
    Folder, Info, Lightbulb, ListChecks, Loader2, MoreHorizontal, PanelRightClose, PanelRightOpen, Pencil, RefreshCw,
    Send, Sparkles, Users, X,
} from 'lucide-react';
import {
    LibraryError, libraryApi, mediaUrl, transcriptUrl, type LibraryDetail, type LibraryItem, type Segment,
} from './api';
import {
    TONE_CLASSES, bytes, clock, formatDate, formatDateTime, formatDuration, isFallbackSummary, overviewSummary, plainText, statusChip,
} from './format';
import { SummaryMarkdown } from './SummaryMarkdown';
import { WaveformPlayer, type PlayerHandle } from './WaveformPlayer';
import { ProcessingPanel } from './ProcessingPanel';

const PANEL_OPEN_KEY = 'hp_meeting_details_open';
const PANEL_WIDTH_KEY = 'hp_meeting_details_width';
const PANEL_MIN = 280;
const PANEL_MAX = 520;

type Tab = 'overview' | 'transcript' | 'actions' | 'audio' | 'summary' | 'chat' | 'properties';

function readPanelOpen(): boolean {
    try {
        const v = localStorage.getItem(PANEL_OPEN_KEY);
        if (v === '1') return true;
        if (v === '0') return false;
    } catch { /* ignore */ }
    return typeof window === 'undefined' || window.innerWidth >= 1280;
}

function readPanelWidth(): number {
    try {
        const v = Number(localStorage.getItem(PANEL_WIDTH_KEY));
        if (v >= PANEL_MIN && v <= PANEL_MAX) return v;
    } catch { /* ignore */ }
    return 360;
}

function useNarrow(query = '(max-width: 1023.98px)'): boolean {
    const get = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(query).matches;
    const [narrow, setNarrow] = useState(get);
    useEffect(() => {
        if (!window.matchMedia) return undefined;
        const mq = window.matchMedia(query);
        const on = () => setNarrow(mq.matches);
        mq.addEventListener?.('change', on);
        return () => mq.removeEventListener?.('change', on);
    }, [query]);
    return narrow;
}

function initials(name?: string | null): string {
    const parts = (name || '').trim().split(/\s+/).filter(Boolean);
    return parts.length ? (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase() : '?';
}

function noteItems(list: any[] | undefined): Array<{ text: string; owner?: string; due?: string; t0?: number }> {
    return (list || []).map((it: any) => typeof it === 'string'
        ? { text: it }
        : { text: String(it?.text || it?.title || it?.item || ''), owner: it?.owner || it?.who || undefined,
            due: it?.due || it?.when || undefined, t0: typeof it?.t0_ms === 'number' ? it.t0_ms : undefined })
        .filter((it) => it.text.trim());
}

export function MeetingDetailPage({ libraryId, onBack, onOpenConversation, onOpenTeamsRoom, onOpenProject }: {
    libraryId: string;
    onBack: () => void;
    onOpenConversation?: (conversationId: string) => void;
    onOpenTeamsRoom?: (roomId: string) => void;
    onOpenProject?: (projectId: string) => void;
}) {
    const [detail, setDetail] = useState<LibraryDetail | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [tab, setTab] = useState<Tab>('overview');
    const [moreOpen, setMoreOpen] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [panelOpen, setPanelOpen] = useState(readPanelOpen);
    const [panelWidth, setPanelWidth] = useState(readPanelWidth);
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [peaks, setPeaks] = useState<number[]>([]);
    const [notice, setNotice] = useState<string | null>(null);
    const narrow = useNarrow();
    const player = useRef<PlayerHandle>(null);
    const toggleRef = useRef<HTMLButtonElement>(null);

    const load = useCallback(async () => {
        try {
            const body = await libraryApi.item(libraryId);
            setDetail(body);
            setError(null);
        } catch (e) {
            setError(e instanceof LibraryError ? (e.status === 404 ? 'This meeting no longer exists.' : e.message) : 'The meeting could not be loaded.');
        }
    }, [libraryId]);

    useEffect(() => { void load(); }, [load]);

    const item = detail?.item;
    const meetingId = item?.meeting_id || null;
    const audio = detail?.assets?.find((a) => a.kind === 'audio') || null;

    useEffect(() => {
        if (!meetingId || !audio) return;
        let cancelled = false;
        void libraryApi.peaks(meetingId, audio.id).then((b) => { if (!cancelled) setPeaks(b.peaks || []); }).catch(() => undefined);
        return () => { cancelled = true; };
    }, [meetingId, audio?.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const working = !!item && (['queued', 'transcribing'].includes(item.transcript_state) || item.summary_state === 'pending' || item.live);
    useEffect(() => {
        if (!working) return undefined;
        const t = setInterval(() => void load(), 4000);
        return () => clearInterval(t);
    }, [working, load]);

    useEffect(() => { try { localStorage.setItem(PANEL_OPEN_KEY, panelOpen ? '1' : '0'); } catch { /* ignore */ } }, [panelOpen]);
    useEffect(() => { try { localStorage.setItem(PANEL_WIDTH_KEY, String(panelWidth)); } catch { /* ignore */ } }, [panelWidth]);

    const startResize = (e: React.PointerEvent) => {
        e.preventDefault();
        const startX = e.clientX;
        const startW = panelWidth;
        const move = (ev: PointerEvent) => setPanelWidth(Math.min(PANEL_MAX, Math.max(PANEL_MIN, startW + (startX - ev.clientX))));
        const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
    };

    const notes = detail?.notes?.notes;
    const decisions = noteItems(notes?.decisions);
    const actions = noteItems(notes?.actions);
    const overview = overviewSummary(detail?.summaries, notes?.summary, item?.description);
    const overviewText = overview.markdown ? plainText(overview.text) : overview.text;
    const segments = detail?.segments || [];
    const speakers = useMemo(() => Array.from(new Set(segments.map((s) => s.speaker).filter(Boolean) as string[])), [segments]);
    const timed = (detail?.versions || []).find((v) => v.active)?.timing !== 'none';

    const act = async (fn: () => Promise<unknown>, message: string) => {
        try {
            await fn();
            setNotice(message);
            await load();
        } catch (e) {
            setNotice(e instanceof LibraryError ? e.message : 'That did not work.');
        }
    };

    if (error) {
        return (
            <div className="grid h-full place-items-center bg-black p-6 text-center text-white">
                <div>
                    <p className="text-sm text-white/70">{error}</p>
                    <button type="button" onClick={onBack} className="mt-4 rounded-xl border border-white/15 px-4 py-2 text-sm hover:bg-white/10">Back to Meetings</button>
                </div>
            </div>
        );
    }
    if (!detail || !item) {
        return <div className="grid h-full place-items-center bg-black text-white/60" aria-busy="true"><Loader2 className="animate-spin" /></div>;
    }

    const chip = statusChip(item);
    const statusPill = item.live ? { label: 'Recording', tone: 'red' as const }
        : item.recording_state === 'awaiting' ? { label: item.scheduled_for && item.scheduled_for * 1000 > Date.now() ? 'Scheduled' : 'Awaiting recording', tone: 'slate' as const }
            : ['queued', 'transcribing'].includes(item.transcript_state) ? { label: 'Processing', tone: 'sky' as const }
                : { label: 'Completed', tone: 'green' as const };
    const project = item.projects[0];
    const teamsRoom = detail.teams_room;
    const details = (
        <DetailsPanel
            item={item} detail={detail} overviewText={overviewText} actions={actions} speakers={speakers}
            onViewActions={() => { setTab('actions'); setDrawerOpen(false); }}
            onOpenProject={onOpenProject}
            onTranscribe={meetingId && audio ? () => act(() => libraryApi.transcribe(meetingId), 'Queued for transcription on this computer.') : undefined}
            onEditProjects={meetingId ? async (ids) => act(() => libraryApi.setProjects(meetingId, ids), 'Projects updated.') : undefined}
        />
    );

    const showPanelInline = panelOpen && !narrow;

    return (
        <div className="flex h-full flex-col bg-black text-white" data-testid="meeting-detail">
            <div className="hp-clear-nav flex items-center gap-3 border-b border-white/[0.06] px-4 py-3 sm:px-6">
                <button type="button" onClick={onBack} className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm hover:bg-white/[0.08]">
                    <ArrowLeft size={16} /> Back
                </button>
                <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-2 text-sm text-white/55 sm:flex">
                    <button type="button" onClick={onBack} className="hover:text-white">Meetings</button>
                    <span aria-hidden>›</span>
                    <span className="truncate text-white/90">{item.title}</span>
                </nav>
                <div className="relative ml-auto flex items-center gap-2">
                    {meetingId && segments.length ? (
                        <a href={transcriptUrl(meetingId, 'md')} className="hidden h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold hover:bg-violet-500 sm:inline-flex">
                            <Download size={15} /> Export
                        </a>
                    ) : null}
                    {meetingId ? (
                        <button type="button" onClick={() => setMenuOpen((m) => !m)} aria-label="More actions" aria-expanded={menuOpen}
                            className="grid h-10 w-10 place-items-center rounded-full border border-white/10 hover:bg-white/10"><MoreHorizontal size={18} /></button>
                    ) : null}
                    {menuOpen && meetingId ? (
                        <div className="absolute right-0 top-12 z-30 w-56 overflow-hidden rounded-xl border border-white/10 bg-[#121218] py-1 text-sm shadow-2xl" role="menu">
                            <MenuItem onClick={() => { setMenuOpen(false); const t = window.prompt('Rename meeting', item.title); if (t && t.trim()) void act(() => libraryApi.update(meetingId, { title: t.trim() }), 'Renamed.'); }}>Rename</MenuItem>
                            {audio ? <MenuItem onClick={() => { setMenuOpen(false); void act(() => libraryApi.transcribe(meetingId), 'Queued for transcription on this computer.'); }}>{segments.length ? 'Transcribe again' : 'Transcribe'}</MenuItem> : null}
                            {segments.length ? <MenuItem onClick={() => { setMenuOpen(false); void act(() => libraryApi.summarize(meetingId), 'Writing a summary…'); }}>Write summary again</MenuItem> : null}
                            {(['txt', 'srt', 'vtt', 'json', 'md'] as const).map((fmt) => segments.length ? (
                                <a key={fmt} href={transcriptUrl(meetingId, fmt)} role="menuitem" className="block px-3 py-2 text-white/85 hover:bg-white/[0.06]">Export transcript (.{fmt})</a>
                            ) : null)}
                            {audio ? <a href={mediaUrl(meetingId, audio.id, true)} role="menuitem" className="block px-3 py-2 text-white/85 hover:bg-white/[0.06]">Download recording</a> : null}
                            <MenuItem onClick={() => { setMenuOpen(false); void act(() => libraryApi.remove(meetingId, 'remove'), 'Removed from the library.').then(onBack); }}>Remove from library</MenuItem>
                            <MenuItem danger onClick={() => {
                                setMenuOpen(false);
                                if (window.confirm(`Delete "${item.title}" and the copies HomePilot keeps? Originals in a synced folder are not touched.`)) {
                                    void act(() => libraryApi.remove(meetingId, 'delete'), 'Deleted.').then(onBack);
                                }
                            }}>Delete meeting data…</MenuItem>
                        </div>
                    ) : null}
                </div>
            </div>

            <div className="flex min-h-0 flex-1">
                <main className="min-w-0 flex-1 overflow-y-auto px-4 pb-10 pt-5 sm:px-6">
                    <div className="flex flex-wrap items-start gap-3">
                        <h1 className="min-w-0 text-2xl font-semibold sm:text-3xl">{item.title}</h1>
                        <span className={`mt-1 inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm ${TONE_CLASSES[statusPill.tone]}`}>
                            <span className="h-2 w-2 rounded-full bg-current" aria-hidden /> {statusPill.label}
                        </span>
                        <button
                            ref={toggleRef}
                            type="button"
                            onClick={() => (narrow ? setDrawerOpen(true) : setPanelOpen((o) => !o))}
                            aria-expanded={narrow ? drawerOpen : panelOpen}
                            aria-controls="meeting-details-panel"
                            className="ml-auto inline-flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-white/80 hover:bg-white/[0.08]"
                            data-testid="details-toggle"
                        >
                            {(narrow ? drawerOpen : panelOpen) ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
                            {(narrow ? drawerOpen : panelOpen) ? 'Hide details' : 'Show details'}
                        </button>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-white/60">
                        <span className="inline-flex items-center gap-1.5"><CalendarDays size={15} /> {formatDate(item.started_at || item.scheduled_for)}</span>
                        <span className="inline-flex items-center gap-1.5"><Clock3 size={15} /> {formatDuration(item.duration_ms)}</span>
                        {project ? (
                            <button type="button" onClick={() => onOpenProject?.(project.id)} className="inline-flex items-center gap-1.5 hover:text-white"><Folder size={15} /> {project.name}</button>
                        ) : null}
                        <span className="inline-flex items-center gap-1.5"><Info size={15} /> {item.source.label}</span>
                        {chip.label.toLowerCase() !== item.source.label.toLowerCase() ? (
                            <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs ${TONE_CLASSES[chip.tone]}`}>{chip.label}</span>
                        ) : null}
                    </div>

                    {notice ? (
                        <div className="mt-4 flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm" role="status">
                            <span className="flex-1">{notice}</span>
                            <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)} className="text-white/50 hover:text-white"><X size={14} /></button>
                        </div>
                    ) : null}
                    {item.live && item.conversation_id ? (
                        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">
                            <span className="h-2 w-2 animate-pulse rounded-full bg-rose-400" aria-hidden /> This meeting is recording now.
                            <button type="button" onClick={() => onOpenConversation?.(item.conversation_id!)} className="ml-auto rounded-lg border border-rose-300/30 px-3 py-1 hover:bg-rose-500/20">Open live meeting</button>
                        </div>
                    ) : null}
                    {item.warnings.length ? (
                        <ul className="mt-4 space-y-1 rounded-xl border border-amber-400/25 bg-amber-500/[0.07] px-3 py-2">
                            {item.warnings.map((w) => <li key={w} className="flex gap-2 text-xs text-amber-100/90"><AlertTriangle size={13} className="mt-0.5 shrink-0" /> {w}</li>)}
                        </ul>
                    ) : null}

                    {teamsRoom ? (
                        <TeamsRoomView room={teamsRoom} onOpen={() => onOpenTeamsRoom?.(teamsRoom.id)} />
                    ) : (
                        <>
                            <div className="mt-5 flex items-center gap-1 rounded-2xl border border-white/10 bg-white/[0.02] p-1" role="tablist" aria-label="Meeting sections">
                                <TabButton id="overview" tab={tab} setTab={setTab} icon={<Sparkles size={16} />}>Overview</TabButton>
                                <TabButton id="transcript" tab={tab} setTab={setTab} icon={<FileText size={16} />}>Transcript</TabButton>
                                <TabButton id="actions" tab={tab} setTab={setTab} icon={<CheckSquare size={16} />}>
                                    Actions {actions.length ? <span className="ml-1 rounded-full bg-white/10 px-1.5 text-xs">{actions.length}</span> : null}
                                </TabButton>
                                <div className="relative ml-auto">
                                    <button type="button" onClick={() => setMoreOpen((o) => !o)} aria-expanded={moreOpen}
                                        className={`inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl px-2.5 text-sm sm:px-3 ${['audio', 'summary', 'chat', 'properties'].includes(tab) ? 'bg-violet-600/30 text-white' : 'text-white/70 hover:bg-white/[0.06]'}`}>
                                        <MoreHorizontal size={16} className="hidden sm:block" aria-hidden /> More <ChevronDown size={14} aria-hidden />
                                    </button>
                                    {moreOpen ? (
                                        <div className="absolute right-0 z-20 mt-1 w-44 overflow-hidden rounded-xl border border-white/10 bg-[#121218] py-1 text-sm shadow-2xl" role="menu">
                                            {([['audio', 'Audio'], ['summary', 'Summary'], ['chat', 'AI Chat'], ['properties', 'Properties']] as const).map(([id, label]) => (
                                                <button key={id} type="button" role="menuitem" onClick={() => { setTab(id); setMoreOpen(false); }}
                                                    className="block w-full px-3 py-2 text-left text-white/85 hover:bg-white/[0.06]">{label}</button>
                                            ))}
                                        </div>
                                    ) : null}
                                </div>
                            </div>

                            <div className="mt-4 space-y-4" role="tabpanel">
                                {tab === 'overview' ? (
                                    <>
                                        {audio && meetingId ? (
                                            <WaveformPlayer ref={player} src={mediaUrl(meetingId, audio.id)} peaks={peaks}
                                                durationMs={audio.media_duration_ms} downloadUrl={mediaUrl(meetingId, audio.id, true)} />
                                        ) : null}
                                        <Card icon={<ListChecks size={18} />} title="Meeting overview">
                                            {overview.text ? (
                                                overview.markdown ? <SummaryMarkdown text={overview.text} />
                                                    : <p className="whitespace-pre-line text-[15px] leading-relaxed text-white/80">{overview.text}</p>
                                            ) : <EmptyLine item={item} hasTranscript={!!segments.length}
                                                    onSummarize={meetingId ? () => act(() => libraryApi.summarize(meetingId), 'Writing a summary…') : undefined} />}
                                        </Card>
                                        {decisions.length ? (
                                            <Card icon={<Lightbulb size={18} />} title="Key decisions">
                                                <ol className="space-y-2">
                                                    {decisions.map((d, i) => (
                                                        <li key={i} className="flex gap-3 text-[15px] text-white/85">
                                                            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-violet-600/80 text-xs font-semibold">{i + 1}</span>{d.text}
                                                        </li>
                                                    ))}
                                                </ol>
                                            </Card>
                                        ) : null}
                                        <Card icon={<FileText size={18} />} title="Transcript preview"
                                            action={segments.length ? <button type="button" onClick={() => setTab('transcript')} className="text-sm text-violet-300 hover:text-violet-200">View full transcript →</button> : null}>
                                            {segments.length ? (
                                                <ul className="space-y-3">
                                                    {segments.slice(0, 3).map((s, i) => <TranscriptLine key={s.id || i} seg={s} timed={timed} speakers={speakers.length > 0} onSeek={audio ? (ms) => player.current?.seek(ms) : undefined} />)}
                                                </ul>
                                            ) : <TranscriptEmpty item={item} />}
                                        </Card>
                                    </>
                                ) : null}
                                {tab === 'transcript' ? (
                                    <TranscriptTab meetingId={meetingId} detail={detail} timed={timed}
                                        onSeek={audio ? (ms) => { setTab('overview'); setTimeout(() => player.current?.seek(ms), 50); } : undefined}
                                        onSaved={() => { setNotice('Saved as a new transcript version.'); void load(); }} />
                                ) : null}
                                {tab === 'actions' ? <ActionsTab meetingId={meetingId || libraryId} actions={actions} item={item} /> : null}
                                {tab === 'audio' ? (
                                    audio && meetingId ? (
                                        <>
                                            <WaveformPlayer ref={player} src={mediaUrl(meetingId, audio.id)} peaks={peaks} durationMs={audio.media_duration_ms}
                                                downloadUrl={mediaUrl(meetingId, audio.id, true)} />
                                            <FilesList detail={detail} meetingId={meetingId} />
                                        </>
                                    ) : <Card title="Audio" icon={<FileText size={18} />}><p className="text-sm text-white/60">This meeting has no recording.</p></Card>
                                ) : null}
                                {tab === 'summary' ? (
                                    <SummaryTab detail={detail} onWrite={meetingId && segments.length ? (style, length) => act(() => libraryApi.summarize(meetingId, { outputs: { style, length } }), 'Writing a summary…') : undefined} />
                                ) : null}
                                {tab === 'chat' ? <ChatTab meetingId={meetingId} hasTranscript={!!segments.length} /> : null}
                                {tab === 'properties' ? <PropertiesTab detail={detail} meetingId={meetingId} /> : null}
                                {meetingId && (detail.jobs || []).some((j) => ['queued', 'running', 'needs_setup', 'failed'].includes(j.state)) ? (
                                    <ProcessingPanel meetingId={meetingId} onChanged={() => void load()} />
                                ) : null}
                            </div>
                        </>
                    )}
                </main>

                {showPanelInline ? (
                    <div className="relative hidden shrink-0 border-l border-white/[0.06] lg:block" style={{ width: panelWidth }}>
                        <div
                            role="separator"
                            aria-orientation="vertical"
                            aria-label="Resize details"
                            aria-valuemin={PANEL_MIN}
                            aria-valuemax={PANEL_MAX}
                            aria-valuenow={panelWidth}
                            tabIndex={0}
                            onPointerDown={startResize}
                            onKeyDown={(e) => {
                                if (e.key === 'ArrowLeft') setPanelWidth((w) => Math.min(PANEL_MAX, w + 20));
                                if (e.key === 'ArrowRight') setPanelWidth((w) => Math.max(PANEL_MIN, w - 20));
                            }}
                            className="absolute -left-1 top-0 z-10 h-full w-2 cursor-col-resize hover:bg-violet-500/30 focus-visible:bg-violet-500/40 focus-visible:outline-none"
                        />
                        <aside id="meeting-details-panel" aria-label="Meeting details" className="h-full overflow-y-auto px-4 py-5">{details}</aside>
                    </div>
                ) : null}
            </div>

            {narrow && drawerOpen ? (
                <div className="fixed inset-0 z-[70] flex justify-end bg-black/60" onClick={() => setDrawerOpen(false)}>
                    <aside id="meeting-details-panel" aria-label="Meeting details" role="dialog" aria-modal="true"
                        className="h-full w-[min(92vw,380px)] overflow-y-auto border-l border-white/10 bg-[#0b0b10] px-4 py-4"
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => { if (e.key === 'Escape') { setDrawerOpen(false); toggleRef.current?.focus(); } }}>
                        <div className="mb-3 flex items-center">
                            <h2 className="font-semibold">Details</h2>
                            <button type="button" autoFocus onClick={() => { setDrawerOpen(false); toggleRef.current?.focus(); }} aria-label="Close details"
                                className="ml-auto grid h-9 w-9 place-items-center rounded-full hover:bg-white/10"><X size={16} /></button>
                        </div>
                        {details}
                    </aside>
                </div>
            ) : null}
        </div>
    );
}

function MenuItem({ children, onClick, danger }: { children: React.ReactNode; onClick: () => void; danger?: boolean }) {
    return <button type="button" role="menuitem" onClick={onClick} className={`block w-full px-3 py-2 text-left hover:bg-white/[0.06] ${danger ? 'text-rose-300' : 'text-white/85'}`}>{children}</button>;
}

function TabButton({ id, tab, setTab, icon, children }: { id: Tab; tab: Tab; setTab: (t: Tab) => void; icon: React.ReactNode; children: React.ReactNode }) {
    const active = tab === id;
    return (
        <button type="button" role="tab" aria-selected={active} onClick={() => setTab(id)}
            className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-xl px-2.5 text-sm sm:px-4 ${active ? 'bg-violet-600/30 font-semibold text-white shadow-[inset_0_-2px_0_rgba(167,139,250,0.9)]' : 'text-white/70 hover:bg-white/[0.06]'}`}>
            {/* Icons step aside on phones so all four tabs, More included, fit on one line. */}
            <span className="hidden sm:inline-flex" aria-hidden>{icon}</span>{children}
        </button>
    );
}

function Card({ icon, title, action, children }: { icon: React.ReactNode; title: string; action?: React.ReactNode; children: React.ReactNode }) {
    return (
        <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 sm:p-5">
            <div className="mb-3 flex items-center gap-2">
                <span className="text-violet-300">{icon}</span>
                <h3 className="flex-1 font-semibold">{title}</h3>
                {action}
            </div>
            {children}
        </section>
    );
}

function EmptyLine({ item, hasTranscript, onSummarize }: { item: LibraryItem; hasTranscript: boolean; onSummarize?: () => void }) {
    if (item.summary_state === 'pending') return <p className="flex items-center gap-2 text-sm text-white/60"><Loader2 size={14} className="animate-spin" /> Writing the summary…</p>;
    if (!hasTranscript) return <p className="text-sm text-white/55">A summary is written once there is a transcript.</p>;
    return (
        <div className="text-sm text-white/60">
            {item.summary_state === 'unavailable' ? 'No language model answered, so no summary was written. ' : 'No summary yet. '}
            {onSummarize ? <button type="button" onClick={onSummarize} className="text-violet-300 hover:text-violet-200">Write one now</button> : null}
        </div>
    );
}

function TranscriptEmpty({ item }: { item: LibraryItem }) {
    const text: Record<string, string> = {
        queued: 'Waiting to be transcribed on this computer.',
        transcribing: 'Transcribing on this computer…',
        needs_setup: 'No local speech-to-text model is installed. The recording is kept; install one and choose Transcribe.',
        no_speech: 'No speech was detected in the recording.',
        failed: 'Transcription failed. Try again from the menu.',
        live: 'The transcript appears here while the meeting is recorded.',
    };
    return <p className="text-sm text-white/55">{text[item.transcript_state] || (item.recording_state === 'awaiting' ? 'The recording has not arrived yet.' : 'There is no transcript.')}</p>;
}

function TranscriptLine({ seg, timed, onSeek, speakers = true }: { seg: Segment; timed: boolean; onSeek?: (ms: number) => void; speakers?: boolean }) {
    // A transcript with no speakers at all (most recordings transcribed here) drops the speaker
    // columns rather than repeating "Speaker unknown" on every line.
    const who = seg.speaker || 'Speaker unknown';
    const stamp = timed && onSeek ? (
        <button type="button" onClick={() => onSeek(seg.t0_ms)} className="hidden self-start pt-2 text-left text-sm tabular-nums text-violet-300 hover:text-violet-200 sm:block" aria-label={`Play from ${clock(seg.t0_ms)}`}>{clock(seg.t0_ms)}</button>
    ) : <span className="hidden pt-2 text-sm tabular-nums text-white/40 sm:block">{timed ? clock(seg.t0_ms) : ''}</span>;
    const phoneLabel = [speakers ? who : '', timed ? clock(seg.t0_ms) : ''].filter(Boolean).join(' · ');
    return (
        <li className={`grid gap-3 ${speakers ? 'grid-cols-[2.25rem_minmax(0,1fr)] sm:grid-cols-[2.25rem_7.5rem_4.5rem_minmax(0,1fr)]' : 'grid-cols-1 sm:grid-cols-[4.5rem_minmax(0,1fr)]'}`}>
            {speakers ? (
                <>
                    <span className="grid h-9 w-9 place-items-center rounded-full bg-violet-500/20 text-xs font-semibold text-violet-100" aria-hidden>{initials(seg.speaker)}</span>
                    <span className="hidden truncate pt-2 text-sm font-medium sm:block" title={who}>{who}</span>
                </>
            ) : null}
            {stamp}
            <p className="pt-1.5 text-[15px] leading-relaxed text-white/85">
                {phoneLabel ? <span className="mr-2 text-xs text-white/40 sm:hidden">{phoneLabel}</span> : null}
                {seg.text}
            </p>
        </li>
    );
}

function TranscriptTab({ meetingId, detail, timed, onSeek, onSaved }: {
    meetingId: string | null; detail: LibraryDetail; timed: boolean; onSeek?: (ms: number) => void; onSaved: () => void;
}) {
    const segments = detail.segments || [];
    const [q, setQ] = useState('');
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState<Segment[]>([]);
    const [saving, setSaving] = useState(false);
    const shown = q ? segments.filter((s) => `${s.speaker || ''} ${s.text}`.toLowerCase().includes(q.toLowerCase())) : segments;
    const versions = detail.versions || [];
    const hasSpeakers = segments.some((s) => s.speaker);

    if (!segments.length) return <Card icon={<FileText size={18} />} title="Transcript"><TranscriptEmpty item={detail.item} /></Card>;
    return (
        <Card icon={<FileText size={18} />} title="Transcript" action={meetingId ? (
            editing ? (
                <div className="flex gap-2">
                    <button type="button" onClick={() => setEditing(false)} className="rounded-lg border border-white/15 px-3 py-1 text-sm hover:bg-white/10">Cancel</button>
                    <button type="button" disabled={saving} onClick={async () => {
                        setSaving(true);
                        try { await libraryApi.saveVersion(meetingId, draft); setEditing(false); onSaved(); } finally { setSaving(false); }
                    }} className="rounded-lg bg-violet-600 px-3 py-1 text-sm font-semibold hover:bg-violet-500 disabled:opacity-50">{saving ? 'Saving…' : 'Save version'}</button>
                </div>
            ) : (
                <button type="button" onClick={() => { setDraft(segments.map((s) => ({ ...s }))); setEditing(true); }}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1 text-sm text-white/80 hover:bg-white/10"><Pencil size={13} /> Correct</button>
            )
        ) : null}>
            {!editing ? (
                <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the transcript…" aria-label="Search the transcript"
                    className="mb-4 h-10 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm focus:border-violet-400/60 focus:outline-none" />
            ) : null}
            {editing ? (
                <ul className="space-y-2">
                    {draft.map((s, i) => (
                        <li key={i} className="grid grid-cols-[6rem_minmax(0,1fr)] gap-2">
                            <input value={s.speaker || ''} placeholder="Speaker" aria-label={`Speaker of line ${i + 1}`}
                                onChange={(e) => setDraft((d) => d.map((x, j) => j === i ? { ...x, speaker: e.target.value || null } : x))}
                                className="h-9 rounded-lg border border-white/10 bg-black px-2 text-sm" />
                            <textarea value={s.text} rows={2} aria-label={`Line ${i + 1}`}
                                onChange={(e) => setDraft((d) => d.map((x, j) => j === i ? { ...x, text: e.target.value } : x))}
                                className="rounded-lg border border-white/10 bg-black px-2 py-1.5 text-sm" />
                        </li>
                    ))}
                </ul>
            ) : (
                <ul className="space-y-3">{shown.map((s, i) => <TranscriptLine key={s.id || i} seg={s} timed={timed} speakers={hasSpeakers} onSeek={onSeek} />)}</ul>
            )}
            {versions.length > 1 && meetingId ? (
                <details className="mt-5 rounded-xl border border-white/10 p-3 text-sm">
                    <summary className="cursor-pointer text-white/70">Versions ({versions.length})</summary>
                    <ul className="mt-2 space-y-1.5">
                        {versions.slice().reverse().map((v) => (
                            <li key={v.id} className="flex flex-wrap items-center gap-2 text-xs text-white/60">
                                <span className="font-medium text-white/85">{v.origin === 'stt' ? 'Transcribed here' : v.origin === 'edit' ? 'Corrected' : v.origin === 'live' ? 'Recorded live' : 'Imported'}</span>
                                <span>· {formatDateTime(v.created_at)} · {v.segment_count} lines{v.provider ? ` · ${v.provider}` : ''}</span>
                                {v.active ? <span className="rounded bg-emerald-500/20 px-1.5 text-emerald-200">shown</span>
                                    : <button type="button" onClick={() => void libraryApi.publishVersion(meetingId, v.id).then(onSaved)} className="text-violet-300 hover:text-violet-200">Show this version</button>}
                            </li>
                        ))}
                    </ul>
                </details>
            ) : null}
        </Card>
    );
}

function ActionsTab({ meetingId, actions, item }: { meetingId: string; actions: Array<{ text: string; owner?: string; due?: string }>; item: LibraryItem }) {
    const key = `hp_meeting_actions_done:${meetingId}`;
    const [done, setDone] = useState<Record<number, boolean>>(() => {
        try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch { return {}; }
    });
    useEffect(() => { try { localStorage.setItem(key, JSON.stringify(done)); } catch { /* ignore */ } }, [key, done]);
    return (
        <Card icon={<CheckSquare size={18} />} title={`Action items${actions.length ? ` (${actions.length})` : ''}`}>
            {actions.length ? (
                <ul className="space-y-2">
                    {actions.map((a, i) => (
                        <li key={i} className="flex items-start gap-3 rounded-xl border border-white/[0.06] p-3">
                            <input type="checkbox" checked={!!done[i]} onChange={(e) => setDone((d) => ({ ...d, [i]: e.target.checked }))}
                                aria-label={`Done: ${a.text}`} className="mt-1 h-4 w-4 accent-violet-500" />
                            <div className="min-w-0 flex-1">
                                <p className={`text-[15px] ${done[i] ? 'text-white/40 line-through' : 'text-white/85'}`}>{a.text}</p>
                                {a.owner ? <p className="text-xs text-white/50">{a.owner}</p> : null}
                            </div>
                            {a.due ? <span className="rounded-md border border-white/10 px-2 py-0.5 text-xs text-white/60">{a.due}</span> : null}
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="text-sm text-white/55">{item.summary_state === 'pending' ? 'Action items are being written…' : 'No action items were found in this meeting.'}</p>
            )}
            {actions.length ? <p className="mt-3 text-xs text-white/40">Ticks are kept on this device.</p> : null}
        </Card>
    );
}

function SummaryTab({ detail, onWrite }: { detail: LibraryDetail; onWrite?: (style: string, length: string) => void }) {
    const [style, setStyle] = useState('minutes');
    const [length, setLength] = useState('standard');
    const docs = detail.summaries || [];
    return (
        <Card icon={<Sparkles size={18} />} title="Summary" action={onWrite ? (
            <div className="flex flex-wrap gap-2">
                <select value={style} onChange={(e) => setStyle(e.target.value)} aria-label="Summary style" className="h-8 rounded-lg border border-white/10 bg-black px-2 text-sm">
                    {[['minutes', 'Minutes'], ['email', 'Recap email'], ['notes', 'Notes'], ['brief', 'Executive brief'], ['actions', 'Action list']].map(([id, l]) => <option key={id} value={id}>{l}</option>)}
                </select>
                <select value={length} onChange={(e) => setLength(e.target.value)} aria-label="Summary length" className="h-8 rounded-lg border border-white/10 bg-black px-2 text-sm">
                    {['short', 'standard', 'detailed'].map((l) => <option key={l} value={l}>{l[0].toUpperCase() + l.slice(1)}</option>)}
                </select>
                <button type="button" onClick={() => onWrite(style, length)} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-violet-600 px-3 text-sm font-semibold hover:bg-violet-500"><RefreshCw size={13} /> Write</button>
            </div>
        ) : null}>
            {docs.length ? (
                <div className="space-y-4">
                    {docs.slice().reverse().map((d, i) => (
                        <article key={d.id || i} className="rounded-xl border border-white/[0.06] p-4">
                            <p className="mb-2 text-xs uppercase tracking-wide text-white/40">
                                {isFallbackSummary(d) ? 'Outline · no language model' : (d.label || d.style || 'summary')} · {formatDateTime(d.created_at)}
                            </p>
                            <SummaryMarkdown text={d.text || ''} />
                        </article>
                    ))}
                </div>
            ) : <EmptyLine item={detail.item} hasTranscript={!!(detail.segments || []).length} />}
        </Card>
    );
}

function ChatTab({ meetingId, hasTranscript }: { meetingId: string | null; hasTranscript: boolean }) {
    const [q, setQ] = useState('');
    const [log, setLog] = useState<Array<{ q: string; a: string }>>([]);
    const [busy, setBusy] = useState(false);
    const ask = async () => {
        if (!meetingId || !q.trim()) return;
        const question = q.trim();
        setQ('');
        setBusy(true);
        try {
            const res = await libraryApi.ask(meetingId, question);
            const text = String(res.text || res.answer || '').trim();
            setLog((l) => [...l, { q: question, a: text || (res.error
                ? 'No language model answered, so this could not be answered. The transcript is still searchable.'
                : 'The meeting does not say.') }]);
        } catch (e) {
            setLog((l) => [...l, { q: question, a: e instanceof LibraryError ? e.message : 'The question could not be answered.' }]);
        } finally {
            setBusy(false);
        }
    };
    return (
        <Card icon={<Bot size={18} />} title="Ask about this meeting">
            {!hasTranscript ? <p className="text-sm text-white/55">Questions are answered from the transcript, and this meeting does not have one yet.</p> : (
                <>
                    <ul className="space-y-3">
                        {log.map((m, i) => (
                            <li key={i} className="space-y-1.5">
                                <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-violet-600/40 px-3 py-2 text-sm">{m.q}</p>
                                <p className="w-fit max-w-[90%] whitespace-pre-line rounded-2xl rounded-bl-md border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white/85">{m.a}</p>
                            </li>
                        ))}
                        {busy ? <li className="flex items-center gap-2 text-sm text-white/50"><Loader2 size={14} className="animate-spin" /> Thinking…</li> : null}
                    </ul>
                    <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); void ask(); }}>
                        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a question about this meeting..." aria-label="Ask a question about this meeting"
                            className="h-11 min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm focus:border-violet-400/60 focus:outline-none" />
                        <button type="submit" disabled={busy || !q.trim()} aria-label="Ask" className="grid h-11 w-11 place-items-center rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50"><Send size={16} /></button>
                    </form>
                    <p className="mt-2 text-xs text-white/40">Answers come only from this meeting&apos;s transcript and notes.</p>
                </>
            )}
        </Card>
    );
}

function FilesList({ detail, meetingId }: { detail: LibraryDetail; meetingId: string }) {
    const assets = detail.assets || [];
    if (!assets.length) return null;
    return (
        <Card icon={<Folder size={18} />} title="Recording files">
            <ul className="divide-y divide-white/[0.06] text-sm">
                {assets.map((a) => (
                    <li key={a.id} className="flex flex-wrap items-center gap-2 py-2">
                        <span className="min-w-0 flex-1 truncate">{a.original_name}</span>
                        <span className="text-xs text-white/45">{a.kind} · {bytes(a.size_bytes)}{a.media_duration_ms ? ` · ${clock(a.media_duration_ms)}` : ''}</span>
                        {!a.source_available ? <span className="text-xs text-amber-200">original no longer in the folder</span> : null}
                        <a href={mediaUrl(meetingId, a.id, true)} className="text-xs text-violet-300 hover:text-violet-200">Download</a>
                    </li>
                ))}
            </ul>
        </Card>
    );
}

function PropertiesTab({ detail, meetingId }: { detail: LibraryDetail; meetingId: string | null }) {
    const active = (detail.versions || []).find((v) => v.active);
    const raw = detail.entry?.raw_metadata;
    return (
        <>
            <Card icon={<Info size={18} />} title="Properties">
                <dl className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
                    <dt className="text-white/50">Origin</dt><dd>{detail.item.source.label} ({detail.item.origin_type})</dd>
                    <dt className="text-white/50">Started</dt><dd>{formatDateTime(detail.item.started_at)}</dd>
                    <dt className="text-white/50">Duration</dt><dd>{formatDuration(detail.item.duration_ms)}</dd>
                    <dt className="text-white/50">Transcript</dt>
                    <dd>{active ? `${active.origin === 'stt' ? 'Transcribed on this computer' : active.origin} · timing ${active.timing}${active.provider ? ` · ${active.provider}` : ''}${active.model ? ` (${active.model})` : ''}` : statusChip(detail.item).label}</dd>
                    <dt className="text-white/50">Meeting id</dt><dd className="truncate font-mono text-xs">{meetingId || detail.item.library_id}</dd>
                </dl>
            </Card>
            {meetingId ? <FilesList detail={detail} meetingId={meetingId} /> : null}
            {(detail.assets || []).length ? (
                <Card icon={<FileText size={18} />} title="File integrity">
                    <ul className="space-y-1 font-mono text-xs text-white/55">
                        {(detail.assets || []).map((a) => <li key={a.id} className="truncate">{a.sha256.slice(0, 16)}… {a.relative_path}</li>)}
                    </ul>
                </Card>
            ) : null}
            {raw ? (
                <details className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 text-sm">
                    <summary className="cursor-pointer font-semibold">Original recorder metadata</summary>
                    <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-white/60">{JSON.stringify(raw, null, 2)}</pre>
                </details>
            ) : null}
        </>
    );
}

function TeamsRoomView({ room, onOpen }: { room: NonNullable<LibraryDetail['teams_room']>; onOpen: () => void }) {
    return (
        <div className="mt-5 space-y-4">
            <Card icon={<Users size={18} />} title="Teams room" action={
                <button type="button" onClick={onOpen} className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-semibold hover:bg-violet-500"><ExternalLink size={14} /> Open in Teams</button>}>
                <p className="text-sm text-white/60">A conversation between personas — there is no recording. {room.message_count} messages{room.topic ? ` about “${room.topic}”` : ''}.</p>
            </Card>
            <Card icon={<FileText size={18} />} title="Conversation">
                <ul className="space-y-3">
                    {room.messages.slice(0, 40).map((m, i) => (
                        <li key={i} className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-3">
                            <span className="grid h-9 w-9 place-items-center rounded-full bg-sky-500/20 text-xs font-semibold" aria-hidden>{initials(m.speaker)}</span>
                            <p className="text-[15px] text-white/85"><span className="mr-2 text-xs text-white/45">{m.speaker}</span>{m.text}</p>
                        </li>
                    ))}
                </ul>
            </Card>
        </div>
    );
}

function DetailsPanel({ item, detail, overviewText, actions, speakers, onViewActions, onOpenProject, onTranscribe, onEditProjects }: {
    item: LibraryItem; detail: LibraryDetail; overviewText: string; actions: Array<{ text: string; owner?: string; due?: string }>;
    speakers: string[]; onViewActions: () => void; onOpenProject?: (id: string) => void; onTranscribe?: () => void;
    onEditProjects?: (ids: string[]) => Promise<void>;
}) {
    const [expanded, setExpanded] = useState(false);
    const [editing, setEditing] = useState(false);
    const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
    const [chosen, setChosen] = useState<string[]>(item.projects.map((p) => p.id));
    const chip = statusChip(item);
    const short = overviewText.length > 260 && !expanded ? `${overviewText.slice(0, 260)}…` : overviewText;
    const assets = detail.assets || [];
    return (
        <div className="space-y-4 text-sm">
            <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                <h3 className="mb-2 flex items-center gap-2 font-semibold"><FileText size={16} className="text-violet-300" /> Quick summary</h3>
                {short ? <p className="whitespace-pre-line leading-relaxed text-white/75">{short}</p> : <p className="text-white/50">No summary yet.</p>}
                {overviewText.length > 260 ? (
                    <button type="button" onClick={() => setExpanded((e) => !e)} className="mt-1 text-xs text-violet-300 hover:text-violet-200">{expanded ? 'Show less' : 'Show more'}</button>
                ) : null}
            </section>
            <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                <h3 className="mb-2 flex items-center gap-2 font-semibold"><CheckSquare size={16} className="text-violet-300" /> Action items
                    {actions.length ? <span className="rounded-full bg-white/10 px-1.5 text-xs">{actions.length}</span> : null}
                    {actions.length ? <button type="button" onClick={onViewActions} className="ml-auto text-xs font-normal text-violet-300 hover:text-violet-200">View all →</button> : null}
                </h3>
                {actions.length ? (
                    <ul className="space-y-2">{actions.slice(0, 3).map((a, i) => (
                        <li key={i} className="flex items-start gap-2 text-white/80"><span className="mt-1 h-3.5 w-3.5 shrink-0 rounded border border-white/30" aria-hidden />
                            <span className="min-w-0">{a.text}{a.owner ? <span className="block text-xs text-white/45">{a.owner}</span> : null}</span>
                            {a.due ? <span className="ml-auto shrink-0 rounded border border-white/10 px-1.5 text-xs text-white/55">{a.due}</span> : null}
                        </li>))}
                    </ul>
                ) : <p className="text-white/50">None found.</p>}
            </section>
            <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                <h3 className="mb-3 flex items-center gap-2 font-semibold"><Info size={16} className="text-violet-300" /> Details</h3>
                <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-2.5">
                    <dt className="text-white/50">Date</dt><dd>{formatDateTime(item.started_at || item.scheduled_for)}</dd>
                    <dt className="text-white/50">Duration</dt><dd>{formatDuration(item.duration_ms)}</dd>
                    <dt className="text-white/50">Project</dt>
                    <dd>
                        {editing ? (
                            <div className="space-y-1">
                                {projects.map((p) => (
                                    <label key={p.id} className="flex items-center gap-2"><input type="checkbox" checked={chosen.includes(p.id)} className="accent-violet-500"
                                        onChange={(e) => setChosen((c) => e.target.checked ? [...c, p.id] : c.filter((x) => x !== p.id))} /> {p.name}</label>
                                ))}
                                <div className="flex gap-2 pt-1">
                                    <button type="button" onClick={() => setEditing(false)} className="text-xs text-white/60 hover:text-white">Cancel</button>
                                    <button type="button" onClick={async () => { await onEditProjects?.(chosen); setEditing(false); }} className="text-xs text-violet-300 hover:text-violet-200">Save</button>
                                </div>
                            </div>
                        ) : (
                            <div className="flex flex-wrap items-center gap-1.5">
                                {item.projects.length ? item.projects.map((p) => (
                                    <button key={p.id} type="button" onClick={() => onOpenProject?.(p.id)} className="inline-flex items-center gap-1 text-violet-300 hover:text-violet-200">
                                        {p.name} <ExternalLink size={12} />
                                    </button>
                                )) : <span className="text-white/50">Unsorted</span>}
                                {onEditProjects ? (
                                    <button type="button" aria-label="Change projects" onClick={async () => { setProjects(await libraryApi.projects()); setEditing(true); }}
                                        className="text-white/40 hover:text-white"><Pencil size={12} /></button>
                                ) : null}
                            </div>
                        )}
                    </dd>
                    <dt className="text-white/50">Source</dt><dd>{item.source.label}</dd>
                    <dt className="text-white/50">Transcription</dt>
                    <dd className="flex flex-wrap items-center gap-2">
                        <span className={`inline-flex items-center gap-1.5 ${chip.tone === 'green' ? 'text-emerald-300' : chip.tone === 'red' ? 'text-rose-300' : chip.tone === 'amber' ? 'text-amber-200' : 'text-white/75'}`}>
                            <span className="h-2 w-2 rounded-full bg-current" aria-hidden /> {chip.label}
                        </span>
                        {onTranscribe && ['none', 'needs_setup', 'failed'].includes(item.transcript_state) ? (
                            <button type="button" onClick={onTranscribe} className="text-xs text-violet-300 hover:text-violet-200">Transcribe</button>
                        ) : null}
                    </dd>
                </dl>
            </section>
            {speakers.length ? (
                <details className="rounded-2xl border border-white/10 bg-white/[0.02] p-4" open>
                    <summary className="flex cursor-pointer items-center gap-2 font-semibold"><Users size={16} className="text-violet-300" /> Participants ({speakers.length})</summary>
                    <ul className="mt-2 space-y-1.5">{speakers.map((s) => <li key={s} className="flex items-center gap-2"><span className="grid h-6 w-6 place-items-center rounded-full bg-violet-500/20 text-[10px]">{initials(s)}</span>{s}</li>)}</ul>
                </details>
            ) : null}
            {assets.length ? (
                <details className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                    <summary className="flex cursor-pointer items-center gap-2 font-semibold"><Folder size={16} className="text-violet-300" /> Recording files ({assets.length})</summary>
                    <ul className="mt-2 space-y-1.5 text-white/70">{assets.map((a) => (
                        <li key={a.id} className="flex gap-2"><span className="min-w-0 flex-1 truncate">{a.original_name}</span><span className="shrink-0 text-xs text-white/45">{bytes(a.size_bytes)}</span></li>
                    ))}</ul>
                </details>
            ) : null}
        </div>
    );
}

export default MeetingDetailPage;
