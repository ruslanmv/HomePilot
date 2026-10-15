/**
 * Import Files — upload, preview, confirm.
 *
 * Nothing is created until "Import": the preview shows what HomePilot found in the files (an
 * Insta360 / AIRecord folder, a recording, a transcript), how long the audio really is,
 * whether a transcript is usable or the recording is silent, duplicates already in the
 * library, and scheduled meetings a recording seems to belong to. Each meeting can be
 * renamed, skipped, attached or imported on its own.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, CloudUpload, FileAudio, FileText, Loader2, X } from 'lucide-react';
import { ModalSheet } from '../../components/ModalSheet';
import { LibraryError, libraryApi, previewImport, type ImportItem, type ImportPreview } from './api';
import { bytes, formatDateTime, formatDuration } from './format';

const ACCEPT = '.mp3,.m4a,.wav,.ogg,.oga,.opus,.flac,.webm,.aac,.mp4,.txt,.md,.srt,.vtt,.json,.zip';

interface Choice { action: 'import' | 'skip' | 'attach'; title: string; attach_to?: string; transcribe: boolean }

export function ImportDialog({ onClose, onImported, maxUploadMb }: {
    onClose: () => void; onImported: (count: number) => void; maxUploadMb?: number;
}) {
    const [files, setFiles] = useState<File[]>([]);
    const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
    const [projectId, setProjectId] = useState('');
    const [progress, setProgress] = useState<number | null>(null);
    const [preview, setPreview] = useState<ImportPreview | null>(null);
    const [choices, setChoices] = useState<Record<string, Choice>>({});
    const [error, setError] = useState<{ message: string; hint?: string } | null>(null);
    const [committing, setCommitting] = useState(false);
    const [drag, setDrag] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);
    const abortRef = useRef<AbortController | null>(null);
    const keyRef = useRef(`imp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`);

    useEffect(() => { void libraryApi.projects().then(setProjects); }, []);
    useEffect(() => () => abortRef.current?.abort(), []);

    const addFiles = (list: FileList | File[] | null) => {
        if (!list) return;
        const next = Array.from(list);
        const tooBig = maxUploadMb ? next.find((f) => f.size > maxUploadMb * 1024 * 1024) : undefined;
        if (tooBig) {
            setError({ message: `${tooBig.name} is larger than ${maxUploadMb} MB.` });
            return;
        }
        setError(null);
        setFiles((cur) => [...cur, ...next.filter((f) => !cur.some((c) => c.name === f.name && c.size === f.size))]);
    };

    const analyse = async () => {
        setError(null);
        setProgress(0);
        abortRef.current = new AbortController();
        try {
            const body = await previewImport(files, projectId, setProgress, abortRef.current.signal);
            setPreview(body);
            const initial: Record<string, Choice> = {};
            body.items.forEach((item) => {
                initial[item.key] = { action: item.outcome, title: item.title, attach_to: item.attach_to, transcribe: true };
            });
            setChoices(initial);
        } catch (e) {
            if (e instanceof LibraryError && e.code === 'aborted') return;
            setError(e instanceof LibraryError ? { message: e.message, hint: e.hint } : { message: 'The files could not be analysed.' });
        } finally {
            setProgress(null);
        }
    };

    const selected = useMemo(() => Object.values(choices).filter((c) => c.action !== 'skip').length, [choices]);

    const commit = async () => {
        if (!preview) return;
        setCommitting(true);
        setError(null);
        try {
            const res = await libraryApi.commitImport({
                import_id: preview.import_id,
                idempotency_key: keyRef.current,
                project_id: projectId,
                choices: Object.entries(choices).map(([key, c]) => ({
                    key, action: c.action, title: c.title, attach_to: c.action === 'attach' ? c.attach_to : undefined,
                    transcribe: c.transcribe,
                })),
            });
            onImported(res.results.filter((r) => r.status === 'created' || r.status === 'attached').length);
        } catch (e) {
            setError(e instanceof LibraryError ? { message: e.message, hint: e.hint } : { message: 'The import failed.' });
        } finally {
            setCommitting(false);
        }
    };

    const footer = (
        <div className="flex flex-wrap items-center gap-3 px-5 py-3">
            <span className="text-xs text-white/50">
                {preview ? `${selected} of ${preview.items.length} will be imported` : files.length ? `${files.length} file${files.length === 1 ? '' : 's'} chosen` : 'Nothing chosen yet'}
            </span>
            <div className="ml-auto flex gap-2">
                <button type="button" onClick={onClose} className="h-10 rounded-xl border border-white/15 px-4 text-sm hover:bg-white/10">Cancel</button>
                {preview ? (
                    <button type="button" onClick={() => void commit()} disabled={committing || selected === 0}
                        className="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold hover:bg-violet-500 disabled:opacity-50">
                        {committing ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />} Import {selected || ''}
                    </button>
                ) : (
                    <button type="button" onClick={() => void analyse()} disabled={!files.length || progress !== null}
                        className="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-semibold hover:bg-violet-500 disabled:opacity-50">
                        {progress !== null ? <Loader2 size={15} className="animate-spin" /> : null}
                        {progress !== null ? (progress < 1 ? `Uploading ${Math.round(progress * 100)}%` : 'Analysing…') : 'Preview import'}
                    </button>
                )}
            </div>
        </div>
    );

    return (
        <ModalSheet
            labelledBy="hp-import-title"
            onRequestClose={() => { if (!committing) onClose(); }}
            className="hp-sheet--wide"
            header={(
                <div className="flex items-start gap-3 px-5 py-4">
                    <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-teal-400/30 bg-teal-500/10 text-teal-200"><CloudUpload size={18} /></div>
                    <div className="min-w-0 flex-1">
                        <h2 id="hp-import-title" className="text-lg font-semibold">Import Files</h2>
                        <p className="text-sm text-white/55">Recordings, transcripts, ZIP archives and Insta360 / AIRecord folders. Files are copied into HomePilot; originals are not changed.</p>
                    </div>
                    <button type="button" onClick={onClose} aria-label="Close" className="grid h-9 w-9 place-items-center rounded-full text-white/60 hover:bg-white/10"><X size={18} /></button>
                </div>
            )}
            footer={footer}
        >
            <div className="space-y-4 px-5 pb-5">
                {!preview ? (
                    <>
                        <div
                            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
                            onDragLeave={() => setDrag(false)}
                            onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
                            className={`rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${drag ? 'border-teal-400/60 bg-teal-500/10' : 'border-white/15 bg-white/[0.02]'}`}
                        >
                            <CloudUpload size={28} className="mx-auto text-white/40" />
                            <p className="mt-2 text-sm text-white/70">Drop files here, or</p>
                            <button type="button" onClick={() => inputRef.current?.click()} className="mt-2 rounded-xl border border-white/15 px-4 py-2 text-sm font-semibold hover:bg-white/10">Choose files</button>
                            <input ref={inputRef} type="file" multiple accept={ACCEPT} className="hidden" data-testid="import-input"
                                onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }} />
                            <p className="mt-3 text-xs text-white/40">MP3, M4A, WAV, OGG, FLAC, WebM · TXT, MD, SRT, VTT, JSON · ZIP{maxUploadMb ? ` · up to ${maxUploadMb} MB each` : ''}</p>
                        </div>
                        {files.length ? (
                            <ul className="divide-y divide-white/[0.06] rounded-xl border border-white/10">
                                {files.map((f) => (
                                    <li key={f.name + f.size} className="flex items-center gap-3 px-3 py-2 text-sm">
                                        {/\.(txt|md|srt|vtt|json)$/i.test(f.name) ? <FileText size={16} className="text-white/50" /> : <FileAudio size={16} className="text-white/50" />}
                                        <span className="min-w-0 flex-1 truncate">{f.name}</span>
                                        <span className="text-xs text-white/40">{bytes(f.size)}</span>
                                        <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles((cur) => cur.filter((c) => c !== f))}
                                            className="text-white/40 hover:text-white"><X size={14} /></button>
                                    </li>
                                ))}
                            </ul>
                        ) : null}
                        {progress !== null ? (
                            <div className="h-1.5 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
                                <div className="h-full bg-teal-400 transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
                            </div>
                        ) : null}
                    </>
                ) : (
                    <>
                        <div className="flex flex-wrap gap-2 text-xs">
                            <Stat label="Meetings found" value={preview.totals.meetings} />
                            <Stat label="Already in library" value={preview.totals.duplicates} />
                            <Stat label="Need transcription" value={preview.totals.needs_transcription} />
                            <Stat label="Audio to transcribe" value={`${preview.totals.audio_minutes_to_transcribe} min`} />
                        </div>
                        <ul className="space-y-3" data-testid="import-preview">
                            {preview.items.map((item) => (
                                <PreviewRow key={item.key} item={item} choice={choices[item.key]}
                                    onChange={(c) => setChoices((cur) => ({ ...cur, [item.key]: { ...cur[item.key], ...c } }))} />
                            ))}
                        </ul>
                    </>
                )}
                <label className="block text-sm text-white/70">
                    Add to project <span className="text-white/40">(optional)</span>
                    <select value={projectId} onChange={(e) => setProjectId(e.target.value)}
                        className="mt-1 h-10 w-full rounded-xl border border-white/10 bg-black px-3 text-sm text-white focus:border-violet-400/60 focus:outline-none">
                        <option value="">No project — Unsorted</option>
                        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                </label>
                {error ? (
                    <div className="rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert">
                        {error.message}{error.hint ? <span className="mt-1 block text-xs text-rose-200/80">{error.hint}</span> : null}
                    </div>
                ) : null}
            </div>
        </ModalSheet>
    );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
    return (
        <span className="rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1 text-white/70">
            {label}: <strong className="text-white">{value}</strong>
        </span>
    );
}

const OUTCOME_TEXT: Record<string, string> = {
    imported: 'Transcript included',
    needs_transcription: 'Will be transcribed on this computer',
    no_speech: 'No speech detected — kept, not transcribed',
    transcript_only: 'Transcript only',
    failed: 'The recording could not be read',
    none: 'Nothing to transcribe',
};

function PreviewRow({ item, choice, onChange }: { item: ImportItem; choice?: Choice; onChange: (c: Partial<Choice>) => void }) {
    if (!choice) return null;
    const skipped = choice.action === 'skip';
    return (
        <li className={`rounded-2xl border p-4 ${skipped ? 'border-white/[0.06] bg-white/[0.01] opacity-70' : 'border-white/10 bg-white/[0.03]'}`}>
            <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="rounded-md border border-indigo-400/25 bg-indigo-500/15 px-2 py-0.5 text-indigo-200">{item.source_label}</span>
                        <span className="text-white/50">{formatDateTime(item.started_at)}{item.time_source === 'file_date' ? ' (from file date)' : ''}</span>
                        {item.audio?.duration_ms ? <span className="text-white/50">· {formatDuration(item.audio.duration_ms)}</span> : null}
                    </div>
                    <input
                        value={choice.title}
                        onChange={(e) => onChange({ title: e.target.value })}
                        aria-label="Meeting title"
                        disabled={skipped}
                        className="mt-2 w-full rounded-lg border border-transparent bg-transparent px-1 text-base font-semibold text-white hover:border-white/10 focus:border-violet-400/60 focus:outline-none"
                    />
                    <p className="mt-1 text-sm text-white/60">{OUTCOME_TEXT[item.transcript_state] || item.transcript_state}</p>
                    <p className="mt-1 truncate text-xs text-white/40" title={item.files.map((f) => f.rel).join('\n')}>
                        {item.files.map((f) => f.name).join(' · ')}
                        {item.ignored_files.length ? ` · ${item.ignored_files.length} device working file${item.ignored_files.length === 1 ? '' : 's'} not imported` : ''}
                    </p>
                </div>
                <select value={choice.action} onChange={(e) => onChange({ action: e.target.value as Choice['action'] })}
                    aria-label={`What to do with ${item.title}`}
                    className="h-9 rounded-lg border border-white/10 bg-black px-2 text-sm text-white focus:border-violet-400/60 focus:outline-none">
                    <option value="import">Import as new meeting</option>
                    {item.scheduled_matches.length ? <option value="attach">Attach to scheduled meeting</option> : null}
                    <option value="skip">Skip</option>
                </select>
            </div>
            {item.duplicate_of ? (
                <p className="mt-2 text-xs text-sky-200">Already in your library — skipped unless you choose to import it again.</p>
            ) : null}
            {choice.action === 'attach' && item.scheduled_matches.length ? (
                <label className="mt-2 block text-xs text-white/60">
                    Scheduled meeting
                    <select value={choice.attach_to || ''} onChange={(e) => onChange({ attach_to: e.target.value })}
                        className="mt-1 h-9 w-full rounded-lg border border-white/10 bg-black px-2 text-sm text-white">
                        {item.scheduled_matches.map((m) => (
                            <option key={m.meeting_id} value={m.meeting_id}>{m.title} — {m.minutes_apart} min apart</option>
                        ))}
                    </select>
                </label>
            ) : null}
            {item.warnings.length ? (
                <ul className="mt-2 space-y-1">
                    {item.warnings.map((w) => (
                        <li key={w} className="flex gap-2 text-xs text-amber-200/90"><AlertTriangle size={13} className="mt-0.5 shrink-0" /> {w}</li>
                    ))}
                </ul>
            ) : null}
        </li>
    );
}

export default ImportDialog;
