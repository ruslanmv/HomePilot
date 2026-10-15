/**
 * Meetings — the library landing page (MEETINGS_LIBRARY_UPGRADE).
 *
 * Laid out like Projects: a header with the page's actions, a tab strip, a search row and a
 * card grid (1 / 2 / 3 columns). Every meeting appears once — recorded live, imported,
 * synced, scheduled, or a Teams room — and opens in Meeting Detail (or in Teams for a room).
 * Nothing here records or uploads by itself: New Meeting opens the wizard, Import Files the
 * import preview, Folder Sync the folder panel.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    ArrowUpDown, Building2, CalendarDays, Check, ChevronDown, Clock3, CloudUpload, FileText, Filter, Folder,
    Loader2, MoreHorizontal, Plus, RefreshCw, Search, X,
} from 'lucide-react';
import { LibraryError, libraryApi, type LibraryItem, type LibraryPage, type LibraryStatus } from './api';
import {
    SORTS, STATE_FILTERS, TABS, TONE_CLASSES, categoryTone, footerPlace, formatDate, formatDuration, isWorking, statusChip,
} from './format';
import { ImportDialog } from './ImportDialog';
import { FolderSyncPanel } from './FolderSyncPanel';
import { ProcessingPanel } from './ProcessingPanel';
import { StartMeetingWizard } from './StartMeetingWizard';

export interface MeetingsHomeProps {
    status: LibraryStatus | null;
    onOpen: (item: LibraryItem) => void;
    /** Live start, provided by MeetingSense; absent when this install cannot record. */
    canRecordLive?: boolean;
}

const PAGE = 24;

function useDebounced<T>(value: T, ms: number): T {
    const [v, setV] = useState(value);
    useEffect(() => {
        const t = setTimeout(() => setV(value), ms);
        return () => clearTimeout(t);
    }, [value, ms]);
    return v;
}

export function MeetingsHome({ status, onOpen, canRecordLive = true }: MeetingsHomeProps) {
    const [tab, setTab] = useState(() => {
        try { return localStorage.getItem('hp_meetings_tab') || 'all'; } catch { return 'all'; }
    });
    const [query, setQuery] = useState('');
    const q = useDebounced(query.trim(), 250);
    const [sort, setSort] = useState('newest');
    const [source, setSource] = useState('');
    const [projectId, setProjectId] = useState('');
    const [state, setState] = useState('');
    const [page, setPage] = useState<LibraryPage | null>(null);
    const [items, setItems] = useState<LibraryItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [sortOpen, setSortOpen] = useState(false);
    const [filterOpen, setFilterOpen] = useState(false);
    const [dialog, setDialog] = useState<null | 'import' | 'sync' | 'new'>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const requestRef = useRef(0);

    useEffect(() => { try { localStorage.setItem('hp_meetings_tab', tab); } catch { /* ignore */ } }, [tab]);

    const params = useMemo(() => ({ tab, q, sort, source, project_id: projectId, state, limit: PAGE }),
        [tab, q, sort, source, projectId, state]);

    const load = useCallback(async (quiet = false) => {
        const id = ++requestRef.current;
        if (!quiet) setLoading(true);
        try {
            const body = await libraryApi.list(params);
            if (id !== requestRef.current) return;
            setPage(body);
            setItems(body.items);
            setError(null);
        } catch (e) {
            if (id !== requestRef.current) return;
            setError(e instanceof LibraryError ? e.message : 'The meetings could not be loaded.');
        } finally {
            if (id === requestRef.current) setLoading(false);
        }
    }, [params]);

    useEffect(() => { void load(); }, [load]);

    // Keep cards current while something is being transcribed or summarised.
    const working = items.some(isWorking) || tab === 'processing';
    useEffect(() => {
        if (!working) return undefined;
        const t = setInterval(() => { void load(true); }, 4000);
        return () => clearInterval(t);
    }, [working, load]);

    const loadMore = async () => {
        if (!page?.next_cursor) return;
        setLoadingMore(true);
        try {
            const body = await libraryApi.list({ ...params, cursor: page.next_cursor });
            setPage(body);
            setItems((cur) => [...cur, ...body.items]);
        } catch (e) {
            setError(e instanceof LibraryError ? e.message : 'More meetings could not be loaded.');
        } finally {
            setLoadingMore(false);
        }
    };

    const filtersActive = Boolean(source || projectId || state);
    const counts = page?.counts || {};

    return (
        <div className="hp-meetings h-full flex flex-col bg-black text-white" data-testid="meetings-home">
            <header className="hp-clear-nav flex flex-wrap items-center gap-3 border-b border-white/[0.06] px-4 py-3 sm:px-6 sm:py-4">
                <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[0.04]">
                    <CalendarDays size={20} className="text-violet-300" />
                </div>
                <div className="min-w-0">
                    <h1 className="text-lg font-semibold leading-tight sm:text-xl">Meetings</h1>
                    <p className="text-xs text-white/50 sm:text-sm">All meetings in one place</p>
                </div>
                <div className="ml-auto flex items-center gap-2">
                    <button
                        type="button"
                        onClick={() => setDialog('new')}
                        aria-label="New Meeting"
                        title="New Meeting"
                        className="inline-flex h-10 items-center gap-2 rounded-xl bg-gradient-to-r from-fuchsia-600 to-violet-600 px-3 text-sm font-semibold shadow-lg shadow-fuchsia-900/30 hover:from-fuchsia-500 hover:to-violet-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fuchsia-300 sm:px-4"
                    >
                        <Plus size={16} /> <span className="hidden sm:inline">New Meeting</span>
                    </button>
                    <button
                        type="button"
                        onClick={() => setDialog('import')}
                        aria-label="Import Files"
                        title="Import Files"
                        className="inline-flex h-10 items-center gap-2 rounded-xl border border-teal-400/40 bg-teal-500/10 px-3 text-sm font-semibold text-teal-200 hover:bg-teal-500/20 sm:px-4"
                    >
                        <CloudUpload size={16} /> <span className="hidden sm:inline">Import Files</span>
                    </button>
                    <button
                        type="button"
                        onClick={() => setDialog('sync')}
                        aria-label="Folder Sync"
                        title="Folder Sync"
                        className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm font-medium text-white/80 hover:bg-white/[0.08] sm:px-4"
                    >
                        <RefreshCw size={15} /> <span className="hidden sm:inline">Folder Sync</span>
                    </button>
                </div>
            </header>

            <nav className="flex gap-2 overflow-x-auto px-4 pt-4 scrollbar-hide sm:px-6" aria-label="Meeting groups" role="tablist">
                {TABS.map((t) => (
                    <button
                        key={t.id}
                        type="button"
                        role="tab"
                        aria-selected={tab === t.id}
                        onClick={() => setTab(t.id)}
                        data-testid={`meetings-tab-${t.id}`}
                        className={`shrink-0 rounded-full px-4 py-1.5 text-sm transition-colors ${
                            tab === t.id
                                ? 'bg-violet-600/80 font-semibold text-white'
                                : 'border border-white/10 bg-white/[0.03] text-white/70 hover:bg-white/[0.07] hover:text-white'
                        }`}
                    >
                        {t.label}
                        {t.id === 'processing' && counts.processing ? (
                            <span className="ml-1.5 rounded-full bg-sky-500/30 px-1.5 text-[11px] text-sky-100">{counts.processing}</span>
                        ) : null}
                    </button>
                ))}
            </nav>

            <div className="flex flex-wrap items-center gap-2 px-4 pt-3 sm:gap-3 sm:px-6">
                <label className="relative min-w-0 flex-1 basis-[16rem]">
                    <span className="sr-only">Search meetings</span>
                    <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-white/40" />
                    <input
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search meetings by title, transcript, or project..."
                        className="h-11 w-full rounded-xl border border-white/10 bg-white/[0.03] pl-10 pr-3 text-sm text-white placeholder-white/40 focus:border-violet-400/60 focus:outline-none"
                        data-testid="meetings-search"
                    />
                </label>
                <div className="relative">
                    <button type="button" onClick={() => { setSortOpen((o) => !o); setFilterOpen(false); }} aria-expanded={sortOpen}
                        className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 text-sm text-white/80 hover:bg-white/[0.07]">
                        <ArrowUpDown size={15} /> Sort <ChevronDown size={14} className="text-white/50" />
                    </button>
                    {sortOpen ? (
                        <div className="absolute right-0 z-30 mt-2 w-48 overflow-hidden rounded-xl border border-white/10 bg-[#121218] py-1 shadow-2xl" role="menu">
                            {SORTS.map((s) => (
                                <button key={s.id} type="button" role="menuitemradio" aria-checked={sort === s.id}
                                    onClick={() => { setSort(s.id); setSortOpen(false); }}
                                    className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-white/80 hover:bg-white/[0.06]">
                                    {s.label} {sort === s.id ? <Check size={14} className="text-violet-300" /> : null}
                                </button>
                            ))}
                        </div>
                    ) : null}
                </div>
                <div className="relative">
                    <button type="button" onClick={() => { setFilterOpen((o) => !o); setSortOpen(false); }} aria-expanded={filterOpen}
                        className={`inline-flex h-11 items-center gap-2 rounded-xl border px-3.5 text-sm hover:bg-white/[0.07] ${
                            filtersActive ? 'border-violet-400/50 bg-violet-500/10 text-violet-100' : 'border-white/10 bg-white/[0.03] text-white/80'}`}>
                        <Filter size={15} /> Filter{filtersActive ? ' •' : ''}
                    </button>
                    {filterOpen ? (
                        <div className="absolute right-0 z-30 mt-2 w-72 space-y-3 rounded-xl border border-white/10 bg-[#121218] p-3 shadow-2xl">
                            <FilterSelect label="Source" value={source} onChange={setSource}
                                options={[{ id: '', label: 'Every source' }, ...(page?.facets.sources || []).map((s) => ({ id: s.kind, label: s.label }))]} />
                            <FilterSelect label="Project" value={projectId} onChange={setProjectId}
                                options={[{ id: '', label: 'Every project' }, ...(page?.facets.projects || []).map((p) => ({ id: p.id, label: p.name }))]} />
                            <FilterSelect label="Transcript" value={state} onChange={setState} options={STATE_FILTERS} />
                            {filtersActive ? (
                                <button type="button" onClick={() => { setSource(''); setProjectId(''); setState(''); }}
                                    className="w-full rounded-lg border border-white/10 py-1.5 text-xs text-white/70 hover:bg-white/[0.06]">Clear filters</button>
                            ) : null}
                        </div>
                    ) : null}
                </div>
            </div>

            <div className="flex-1 overflow-y-auto px-4 pb-8 pt-4 sm:px-6" onClick={() => { setSortOpen(false); setFilterOpen(false); }}>
                {notice ? (
                    <div className="mb-3 flex items-center gap-3 rounded-xl border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100" role="status">
                        <Check size={16} /> <span className="flex-1">{notice}</span>
                        <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss" className="text-emerald-200/70 hover:text-white"><X size={14} /></button>
                    </div>
                ) : null}
                {tab === 'processing' ? <ProcessingPanel onChanged={() => void load(true)} /> : null}
                {error ? (
                    <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 p-6 text-center" role="alert">
                        <p className="text-sm text-rose-100">{error}</p>
                        <button type="button" onClick={() => void load()} className="mt-3 rounded-lg border border-white/15 px-3 py-1.5 text-sm hover:bg-white/10">Try again</button>
                    </div>
                ) : loading && !items.length ? (
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading meetings">
                        {Array.from({ length: 6 }).map((_, i) => (
                            <div key={i} className="h-[174px] animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.03]" />
                        ))}
                    </div>
                ) : items.length === 0 ? (
                    <EmptyState tab={tab} filtered={Boolean(q || filtersActive)} onImport={() => setDialog('import')} onNew={() => setDialog('new')} onSync={() => setDialog('sync')} />
                ) : (
                    <>
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="meetings-grid">
                            {items.map((item) => (
                                <LibraryCard key={item.library_id} item={item} onOpen={() => onOpen(item)}
                                    onChanged={(msg) => { if (msg) setNotice(msg); void load(true); }} />
                            ))}
                        </div>
                        {page?.next_cursor ? (
                            <div className="mt-6 text-center">
                                <button type="button" onClick={() => void loadMore()} disabled={loadingMore}
                                    className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-white/80 hover:bg-white/[0.08] disabled:opacity-50">
                                    {loadingMore ? <Loader2 size={14} className="animate-spin" /> : null}
                                    Show more ({(page.total || 0) - items.length} left)
                                </button>
                            </div>
                        ) : null}
                    </>
                )}
            </div>

            {dialog === 'import' ? (
                <ImportDialog
                    onClose={() => setDialog(null)}
                    maxUploadMb={status?.max_upload_mb}
                    onImported={(n) => { setDialog(null); setNotice(n === 1 ? 'Imported 1 meeting.' : `Imported ${n} meetings.`); void load(true); }}
                />
            ) : null}
            {dialog === 'sync' ? (
                <FolderSyncPanel onClose={() => setDialog(null)} onImported={() => void load(true)} suggestion={status?.sync_suggestion} />
            ) : null}
            {dialog === 'new' ? (
                <StartMeetingWizard
                    canRecordLive={canRecordLive}
                    onClose={() => setDialog(null)}
                    onCreated={(msg) => { setDialog(null); setNotice(msg); void load(true); }}
                />
            ) : null}
        </div>
    );
}

function FilterSelect({ label, value, onChange, options }: {
    label: string; value: string; onChange: (v: string) => void; options: Array<{ id: string; label: string }>;
}) {
    return (
        <label className="block text-xs text-white/60">
            {label}
            <select value={value} onChange={(e) => onChange(e.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-white/10 bg-black px-2 text-sm text-white focus:border-violet-400/60 focus:outline-none">
                {options.map((o) => <option key={o.id || 'any'} value={o.id}>{o.label}</option>)}
            </select>
        </label>
    );
}

function EmptyState({ tab, filtered, onImport, onNew, onSync }: {
    tab: string; filtered: boolean; onImport: () => void; onNew: () => void; onSync: () => void;
}) {
    const text = filtered
        ? 'No meetings match your search or filters.'
        : tab === 'processing'
            ? 'Nothing is being processed right now.'
            : tab === 'all'
                ? 'No meetings yet. Start one, import recordings, or connect a folder such as D:\\AIRecord.'
                : 'No meetings in this group yet.';
    return (
        <div className="mx-auto max-w-xl rounded-2xl border border-white/[0.08] bg-white/[0.02] p-10 text-center" data-testid="meetings-empty">
            <CalendarDays size={28} className="mx-auto text-white/30" />
            <p className="mt-3 text-sm text-white/60">{text}</p>
            {!filtered && tab === 'all' ? (
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                    <button type="button" onClick={onNew} className="rounded-xl bg-violet-600 px-3 py-2 text-sm font-semibold hover:bg-violet-500">New Meeting</button>
                    <button type="button" onClick={onImport} className="rounded-xl border border-teal-400/40 bg-teal-500/10 px-3 py-2 text-sm text-teal-200 hover:bg-teal-500/20">Import Files</button>
                    <button type="button" onClick={onSync} className="rounded-xl border border-white/10 px-3 py-2 text-sm text-white/80 hover:bg-white/[0.06]">Folder Sync</button>
                </div>
            ) : null}
        </div>
    );
}

export function LibraryCard({ item, onOpen, onChanged }: {
    item: LibraryItem; onOpen: () => void; onChanged?: (message?: string) => void;
}) {
    const chip = statusChip(item);
    const place = footerPlace(item);
    const PlaceIcon = place.kind === 'project' ? Folder
        : item.source.kind === 'teams_room' ? Building2
            : (item.source.kind === 'insta360' || item.source.kind === 'upload' || item.source.kind === 'transcript') ? FileText : Folder;
    const [menu, setMenu] = useState(false);
    const [busy, setBusy] = useState(false);
    const meetingId = item.meeting_id;

    const act = async (fn: () => Promise<unknown>, message?: string) => {
        setBusy(true);
        try {
            await fn();
            onChanged?.(message);
        } catch (e) {
            onChanged?.(e instanceof LibraryError ? e.message : 'That did not work.');
        } finally {
            setBusy(false);
            setMenu(false);
        }
    };

    return (
        <div
            role="button"
            tabIndex={0}
            onClick={onOpen}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(); } }}
            aria-label={`${item.title}, ${chip.label}`}
            data-testid={`meeting-card-${item.library_id}`}
            className="group relative cursor-pointer rounded-2xl border border-white/10 bg-white/[0.03] p-5 transition-colors hover:border-white/20 hover:bg-white/[0.05] focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400"
        >
            <div className="flex flex-wrap items-center gap-2 pr-8">
                <span className={`rounded-lg border px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[categoryTone(item.category)]}`}>{item.category}</span>
                <span className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[chip.tone]}`} title={chip.title}>
                    {chip.busy ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden /> : null}
                    {chip.label}
                </span>
            </div>
            <h3 className="mt-3 line-clamp-1 text-lg font-semibold text-white">{item.title}</h3>
            <p className="mt-1 line-clamp-2 min-h-[2.5rem] text-sm text-white/55">
                {item.description || (item.recording_state === 'awaiting' ? 'Waiting for its recording.' : item.warnings[0] || '\u00a0')}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-white/55">
                <span className="inline-flex items-center gap-1.5"><CalendarDays size={14} /> {formatDate(item.started_at || item.scheduled_for)}</span>
                <span className="inline-flex items-center gap-1.5"><Clock3 size={14} /> {formatDuration(item.duration_ms)}</span>
                <span className="inline-flex min-w-0 items-center gap-1.5"><PlaceIcon size={14} /> <span className="truncate">{place.label}</span></span>
            </div>
            {meetingId ? (
                <div className="absolute right-3 top-3" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                    <button
                        type="button"
                        aria-label={`More actions for ${item.title}`}
                        aria-expanded={menu}
                        onClick={() => setMenu((m) => !m)}
                        className="grid h-8 w-8 place-items-center rounded-lg text-white/50 opacity-100 hover:bg-white/10 hover:text-white focus-visible:opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
                    >
                        {busy ? <Loader2 size={15} className="animate-spin" /> : <MoreHorizontal size={16} />}
                    </button>
                    {menu ? (
                        <div className="absolute right-0 z-20 mt-1 w-52 overflow-hidden rounded-xl border border-white/10 bg-[#121218] py-1 text-sm shadow-2xl" role="menu">
                            <MenuButton onClick={() => {
                                const title = window.prompt('Rename meeting', item.title);
                                if (title && title.trim() && title.trim() !== item.title) void act(() => libraryApi.update(meetingId, { title: title.trim() }), 'Renamed.');
                                else setMenu(false);
                            }}>Rename</MenuButton>
                            {item.media_present && item.transcript_state !== 'transcribing' && item.transcript_state !== 'queued' ? (
                                <MenuButton onClick={() => void act(() => libraryApi.transcribe(meetingId), 'Queued for transcription on this computer.')}>
                                    {item.segments ? 'Transcribe again' : 'Transcribe'}
                                </MenuButton>
                            ) : null}
                            <MenuButton onClick={() => void act(() => libraryApi.remove(meetingId, 'remove'), 'Removed from the library. Its data is kept.')}>Remove from library</MenuButton>
                            <MenuButton danger onClick={() => {
                                if (window.confirm(`Delete "${item.title}" and the copies HomePilot keeps of its recording and transcript? Original files in a synced folder are not touched.`)) {
                                    void act(() => libraryApi.remove(meetingId, 'delete'), 'Deleted.');
                                } else setMenu(false);
                            }}>Delete meeting data…</MenuButton>
                        </div>
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}

function MenuButton({ children, onClick, danger }: { children: React.ReactNode; onClick: () => void; danger?: boolean }) {
    return (
        <button type="button" role="menuitem" onClick={onClick}
            className={`block w-full px-3 py-2 text-left hover:bg-white/[0.06] ${danger ? 'text-rose-300' : 'text-white/85'}`}>
            {children}
        </button>
    );
}

export default MeetingsHome;
