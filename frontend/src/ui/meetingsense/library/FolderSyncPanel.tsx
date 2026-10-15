/**
 * Folder Sync — connect a folder such as D:\AIRecord and import finished recordings from it.
 *
 * The server decides what it may read: a folder must be below one the operator allowed
 * (MEETINGS_SYNC_ALLOWED_ROOTS). When it is not, this panel says exactly that and what to
 * set — a typed path never grants access by itself. Originals are only read; meetings
 * already imported stay when a folder is disconnected.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { FolderSync, Loader2, Pause, Play, RefreshCw, Trash2, X } from 'lucide-react';
import { ModalSheet } from '../../components/ModalSheet';
import { LibraryError, libraryApi, type SyncSource } from './api';
import { formatDateTime } from './format';

export function FolderSyncPanel({ onClose, onImported, suggestion }: {
    onClose: () => void; onImported: () => void; suggestion?: string;
}) {
    const [sources, setSources] = useState<SyncSource[]>([]);
    const [enabled, setEnabled] = useState(true);
    const [allowed, setAllowed] = useState<string[]>([]);
    const [interval, setIntervalS] = useState(60);
    const [path, setPath] = useState(suggestion || 'D:\\AIRecord');
    const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
    const [projectId, setProjectId] = useState('');
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<{ message: string; hint?: string } | null>(null);
    const [result, setResult] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const body = await libraryApi.sources();
            setSources(body.sources);
            setEnabled(body.enabled);
            setAllowed(body.allowed_roots);
            setIntervalS(body.interval_s);
        } catch (e) {
            setError({ message: e instanceof LibraryError ? e.message : 'Folder sync could not be loaded.' });
        }
    }, []);

    useEffect(() => { void load(); void libraryApi.projects().then(setProjects); }, [load]);

    const run = async (key: string, fn: () => Promise<unknown>) => {
        setBusy(key);
        setError(null);
        try {
            await fn();
            await load();
        } catch (e) {
            setError(e instanceof LibraryError ? { message: e.message, hint: e.hint } : { message: 'That did not work.' });
        } finally {
            setBusy(null);
        }
    };

    const pickFolder = async () => {
        // The desktop app can open the system folder picker; in a browser the path is typed.
        const bridge = (window as any).homepilot?.meetings;
        if (bridge?.pickFolder) {
            const picked = await bridge.pickFolder();
            if (picked) setPath(picked);
        }
    };

    const scan = (s: SyncSource) => run(`scan:${s.id}`, async () => {
        const body = await libraryApi.scanSource(s.id);
        const c = body.counts;
        setResult(`${s.display_name}: ${c.imported || 0} imported, ${c.already || 0} already in the library, ${c.waiting || 0} still being written${c.failed ? `, ${c.failed} failed` : ''}.`);
        if (c.imported) onImported();
    });

    return (
        <ModalSheet
            labelledBy="hp-sync-title"
            onRequestClose={onClose}
            header={(
                <div className="flex items-start gap-3 px-5 py-4">
                    <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[0.04] text-violet-200"><FolderSync size={18} /></div>
                    <div className="min-w-0 flex-1">
                        <h2 id="hp-sync-title" className="text-lg font-semibold">Folder Sync</h2>
                        <p className="text-sm text-white/55">Import finished recordings from a folder, such as the Insta360 AIRecord folder. Checked every {Math.round(interval / 60) || 1} min and on demand.</p>
                    </div>
                    <button type="button" onClick={onClose} aria-label="Close" className="grid h-9 w-9 place-items-center rounded-full text-white/60 hover:bg-white/10"><X size={18} /></button>
                </div>
            )}
        >
            <div className="space-y-4 px-5 pb-6">
                {!enabled ? (
                    <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-3 text-sm text-amber-100">
                        <p className="font-semibold">Folder sync is turned off on this server.</p>
                        <p className="mt-1 text-amber-100/80">
                            HomePilot only reads folders its operator allows. To sync <code className="rounded bg-black/30 px-1">D:\AIRecord</code>,
                            set <code className="rounded bg-black/30 px-1">MEETINGS_SYNC_ALLOWED_ROOTS=/mnt/d/AIRecord</code> (HomePilot under WSL)
                            or <code className="rounded bg-black/30 px-1">D:\AIRecord</code> (HomePilot on Windows) and restart. Until then, use Import Files.
                        </p>
                    </div>
                ) : null}

                {sources.length ? (
                    <ul className="space-y-2" data-testid="sync-sources">
                        {sources.map((s) => (
                            <li key={s.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className={`h-2 w-2 rounded-full ${s.enabled ? (s.last_error ? 'bg-amber-400' : 'bg-emerald-400') : 'bg-white/30'}`} aria-hidden />
                                    <span className="font-semibold">{s.display_name}</span>
                                    <code className="truncate text-xs text-white/50">{s.path}</code>
                                    <div className="ml-auto flex gap-1.5">
                                        <IconButton label={`Sync ${s.display_name} now`} busy={busy === `scan:${s.id}`} onClick={() => void scan(s)}><RefreshCw size={14} /></IconButton>
                                        <IconButton label={s.enabled ? 'Pause' : 'Resume'} busy={busy === `toggle:${s.id}`}
                                            onClick={() => void run(`toggle:${s.id}`, () => libraryApi.updateSource(s.id, { enabled: !s.enabled }))}>
                                            {s.enabled ? <Pause size={14} /> : <Play size={14} />}
                                        </IconButton>
                                        <IconButton label={`Disconnect ${s.display_name}`} busy={busy === `del:${s.id}`}
                                            onClick={() => {
                                                if (window.confirm(`Disconnect ${s.path}? Meetings already imported from it stay in your library.`)) {
                                                    void run(`del:${s.id}`, () => libraryApi.deleteSource(s.id));
                                                }
                                            }}><Trash2 size={14} /></IconButton>
                                    </div>
                                </div>
                                <p className="mt-2 text-xs text-white/50">
                                    {s.enabled ? 'Watching' : 'Paused'} · Last sync {s.last_success_at ? formatDateTime(s.last_success_at) : 'never'}
                                    {s.counts && Object.keys(s.counts).length
                                        ? ` · ${s.counts.found || 0} found, ${s.counts.imported || 0} new, ${s.counts.waiting || 0} waiting` : ''}
                                </p>
                                {s.last_error ? <p className="mt-1 text-xs text-amber-200">{s.last_error}</p> : null}
                            </li>
                        ))}
                    </ul>
                ) : null}

                <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                    <h3 className="text-sm font-semibold">Connect a folder</h3>
                    <div className="mt-2 flex gap-2">
                        <input value={path} onChange={(e) => setPath(e.target.value)} aria-label="Folder path" placeholder="D:\AIRecord"
                            className="h-10 min-w-0 flex-1 rounded-xl border border-white/10 bg-black px-3 font-mono text-sm text-white focus:border-violet-400/60 focus:outline-none" />
                        {(window as any).homepilot?.meetings?.pickFolder ? (
                            <button type="button" onClick={() => void pickFolder()} className="h-10 rounded-xl border border-white/15 px-3 text-sm hover:bg-white/10">Browse…</button>
                        ) : null}
                    </div>
                    <label className="mt-3 block text-xs text-white/60">
                        Put new meetings in
                        <select value={projectId} onChange={(e) => setProjectId(e.target.value)}
                            className="mt-1 h-9 w-full rounded-lg border border-white/10 bg-black px-2 text-sm text-white">
                            <option value="">Unsorted</option>
                            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                    </label>
                    {allowed.length ? <p className="mt-2 text-xs text-white/40">Allowed on this server: {allowed.join(' · ')}</p> : null}
                    <button type="button" disabled={!path.trim() || busy === 'add'}
                        onClick={() => void run('add', async () => {
                            const { source } = await libraryApi.addSource(path.trim(), '', projectId);
                            await scan(source);
                        })}
                        className="mt-3 inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold hover:bg-violet-500 disabled:opacity-50">
                        {busy === 'add' ? <Loader2 size={15} className="animate-spin" /> : <FolderSync size={15} />} Connect and sync
                    </button>
                    <p className="mt-2 text-xs text-white/40">Recordings are imported once they have finished writing. Source files are never changed or deleted.</p>
                </div>

                {result ? <p className="rounded-xl border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100" role="status">{result}</p> : null}
                {error ? (
                    <div className="rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert">
                        {error.message}{error.hint ? <span className="mt-1 block text-xs text-rose-200/80">{error.hint}</span> : null}
                    </div>
                ) : null}
            </div>
        </ModalSheet>
    );
}

function IconButton({ label, busy, onClick, children }: { label: string; busy?: boolean; onClick: () => void; children: React.ReactNode }) {
    return (
        <button type="button" onClick={onClick} aria-label={label} title={label} disabled={busy}
            className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 text-white/70 hover:bg-white/10 hover:text-white disabled:opacity-50">
            {busy ? <Loader2 size={14} className="animate-spin" /> : children}
        </button>
    );
}

export default FolderSyncPanel;
