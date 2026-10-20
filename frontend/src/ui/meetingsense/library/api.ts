/**
 * The Meetings Library's client — every call to `/v1/meetingsense/library…`, imports,
 * folder sync and processing, in one place (same base URL and credentials as MeetingSense).
 *
 * Errors come back as `LibraryError` with the server's `code`, message and hint, so a
 * component can say *what to do* ("set MEETINGS_SYNC_ALLOWED_ROOTS…") instead of "failed".
 */
import { backendBase, requestHeaders } from '../api';

export type TranscriptState =
    | 'none' | 'imported' | 'queued' | 'transcribing' | 'ready' | 'ready_warnings' | 'failed'
    | 'needs_setup' | 'no_speech' | 'transcript_only' | 'live';
export type RecordingState = 'none' | 'awaiting' | 'recording' | 'paused' | 'present' | 'unavailable';

export interface LibraryProject { id: string; name: string; kind?: string; missing?: boolean }

export interface LibraryItem {
    library_id: string;
    meeting_id: string | null;
    origin_type: 'meetingsense' | 'import' | 'sync' | 'scheduled' | 'teams_room';
    origin_id: string;
    title: string;
    description: string;
    category: string;
    started_at: number | null;
    ended_at: number | null;
    scheduled_for: number | null;
    duration_ms: number | null;
    projects: LibraryProject[];
    source: { kind: string; label: string };
    media_present: boolean;
    recording_state: RecordingState;
    transcript_state: TranscriptState;
    summary_state: string;
    segments: number;
    conversation_id: string | null;
    status: string;
    live: boolean;
    warnings: string[];
}

export interface LibraryPage {
    items: LibraryItem[];
    next_cursor: string | null;
    total: number;
    counts: Record<string, number>;
    facets: { sources: Array<{ kind: string; label: string }>; projects: Array<{ id: string; name: string }> };
}

export interface LibraryStatus {
    enabled: boolean;
    processing?: boolean;
    sync?: boolean;
    sync_suggestion?: string;
    max_upload_mb?: number;
    ffmpeg?: boolean;
    stt?: { available: boolean; provider?: string | null; hint?: string | null };
}

export interface Segment { id?: string; t0_ms: number; t1_ms: number | null; speaker: string | null; text: string; conf?: number | null }

export interface LibraryAsset {
    id: string; kind: 'audio' | 'transcript' | 'metadata'; role: string; original_name: string;
    relative_path: string; sha256: string; mime: string | null; size_bytes: number;
    media_duration_ms: number | null; source_id: string; origin_type: string; created_at: number;
    metadata: Record<string, any>; source_available: boolean;
}

export interface LibraryJob {
    id: string; meeting_id: string; meeting_title?: string; type: 'transcribe' | 'index' | 'summarize';
    state: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'needs_setup'; stage: string | null;
    progress: number; attempt: number; error: string | null; diagnostic: Record<string, any>;
    created_at: number; started_at: number | null; finished_at: number | null;
}

export interface TranscriptVersion {
    id: string; origin: string; timing: string; active: number; segment_count: number; provider: string | null;
    model: string | null; language: string | null; note: string | null; created_at: number;
}

export interface MeetingNotes { summary?: string; decisions?: any[]; actions?: any[]; questions?: any[]; [k: string]: any }

export interface LibraryDetail {
    item: LibraryItem;
    meeting?: Record<string, any> | null;
    entry?: { origin_type?: string; category?: string; description?: string; scheduled_for?: number | null;
              recording_plan?: string | null; outputs?: any; raw_metadata?: any; warnings?: string[] };
    segments?: Segment[];
    keyframes?: any[];
    notes?: { version: number; updated_at: number; notes: MeetingNotes } | null;
    summaries?: Array<{ id?: string; style?: string; text?: string; created_at?: number; [k: string]: any }>;
    assets?: LibraryAsset[];
    jobs?: LibraryJob[];
    versions?: TranscriptVersion[];
    teams_room?: { id: string; name: string; topic?: string; participants: string[]; message_count: number;
                   messages: Array<{ speaker: string; text: string; t: number }> };
}

export interface ImportItem {
    key: string; kind: 'airecord' | 'audio' | 'transcript'; source_label: string; title: string;
    started_at: number | null; time_source: string; warnings: string[];
    files: Array<{ rel: string; name: string; size: number; role: string }>;
    ignored_files: Array<{ rel: string; name: string; size: number; role: string }>;
    audio: null | { name: string; size: number; duration_ms?: number; readable: boolean; silent?: boolean; max_db?: number; error?: string };
    transcript: null | { name: string; format: string; segments: number; usable: boolean; timing: string; speakers: string[]; preview: string };
    duplicate_of: string | null;
    scheduled_matches: Array<{ meeting_id: string; title: string; scheduled_for: number; minutes_apart: number }>;
    outcome: 'import' | 'skip' | 'attach';
    attach_to?: string;
    transcript_state: string;
}

export interface ImportPreview {
    import_id: string;
    items: ImportItem[];
    totals: { meetings: number; duplicates: number; needs_transcription: number; audio_minutes_to_transcribe: number };
    project_id: string | null;
}

export interface SyncSource {
    id: string; kind: string; display_name: string; path: string; enabled: boolean; project_id: string | null;
    last_scan_at: number | null; last_success_at: number | null; last_error: string | null;
    counts: Record<string, number>; created_at: number;
}

export class LibraryError extends Error {
    constructor(message: string, public status: number, public code = '', public hint = '') {
        super(message);
    }
}

function url(path: string): string {
    return `${backendBase()}${path}`;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = { ...requestHeaders(), ...(init.headers as Record<string, string> || {}) };
    if (init.body instanceof FormData) delete headers['Content-Type'];
    let res: Response;
    try {
        res = await fetch(url(path), { credentials: 'include', ...init, headers });
    } catch {
        throw new LibraryError('HomePilot could not be reached.', 0, 'offline');
    }
    let body: any = null;
    try { body = await res.json(); } catch { /* empty body */ }
    if (!res.ok) {
        const detail = body?.detail;
        if (detail && typeof detail === 'object') {
            throw new LibraryError(detail.message || `HTTP ${res.status}`, res.status, detail.code || '', detail.hint || '');
        }
        throw new LibraryError(typeof detail === 'string' ? detail : `HTTP ${res.status}`, res.status);
    }
    return body as T;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const libraryApi = {
    status: () => call<LibraryStatus>('/v1/meetingsense/library/status'),
    list: (params: Record<string, string | number | undefined>) => {
        const q = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') q.set(k, String(v)); });
        return call<LibraryPage>(`/v1/meetingsense/library?${q.toString()}`);
    },
    item: (libraryId: string) => call<LibraryDetail>(`/v1/meetingsense/library/item/${encodeURIComponent(libraryId)}`),
    update: (meetingId: string, body: Record<string, unknown>) =>
        call<{ ok: boolean; item: LibraryItem }>(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}`, { method: 'PATCH', ...json(body) }),
    createScheduled: (body: Record<string, unknown>) =>
        call<{ ok: boolean; meeting_id: string; item: LibraryItem }>('/v1/meetingsense/library/meetings', { method: 'POST', ...json(body) }),
    remove: (meetingId: string, mode: 'remove' | 'delete') =>
        call<{ ok: boolean; removed?: Record<string, number> }>(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}?mode=${mode}`, { method: 'DELETE' }),
    setProjects: (meetingId: string, projectIds: string[]) =>
        call<{ ok: boolean; project_ids: string[] }>(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}/projects`, { method: 'PUT', ...json({ project_ids: projectIds }) }),
    peaks: (meetingId: string, assetId: string) =>
        call<{ peaks: number[] }>(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}/media/${assetId}/peaks`),
    transcribe: (meetingId: string) =>
        call<{ job: LibraryJob }>(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}/transcriptions`, { method: 'POST', ...json({}) }),
    summarize: (meetingId: string, body: Record<string, unknown> = {}) =>
        call<{ job: LibraryJob }>(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}/summarize`, { method: 'POST', ...json(body) }),
    saveVersion: (meetingId: string, segments: Segment[], note = 'Edited by hand') =>
        call<{ version_id: string; versions: TranscriptVersion[] }>(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}/versions`, { method: 'POST', ...json({ segments, note }) }),
    publishVersion: (meetingId: string, versionId: string) =>
        call<{ ok: boolean; versions: TranscriptVersion[] }>(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}/versions/${versionId}/publish`, { method: 'POST' }),
    ask: (meetingId: string, text: string) =>
        call<{ answer?: string; text?: string; [k: string]: any }>(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}/ask`, { method: 'POST', ...json({ text }) }),
    commitImport: (body: Record<string, unknown>) =>
        call<{ import_id: string; status: string; results: Array<{ key: string; status: string; meeting_id?: string; transcript_state?: string }> }>(
            '/v1/meetingsense/imports', { method: 'POST', ...json(body) }),
    sources: () => call<{ sources: SyncSource[]; enabled: boolean; allowed_roots: string[]; suggestion: string; interval_s: number }>('/v1/meetingsense/sync-sources'),
    addSource: (path: string, displayName = '', projectId = '') =>
        call<{ source: SyncSource }>('/v1/meetingsense/sync-sources', { method: 'POST', ...json({ path, display_name: displayName, project_id: projectId }) }),
    scanSource: (id: string) => call<{ counts: Record<string, number>; source: SyncSource }>(`/v1/meetingsense/sync-sources/${id}/scan`, { method: 'POST' }),
    updateSource: (id: string, body: Record<string, unknown>) =>
        call<{ source: SyncSource }>(`/v1/meetingsense/sync-sources/${id}`, { method: 'PATCH', ...json(body) }),
    deleteSource: (id: string) => call<{ ok: boolean }>(`/v1/meetingsense/sync-sources/${id}`, { method: 'DELETE' }),
    jobs: (params: { meeting_id?: string; active?: boolean } = {}) =>
        call<{ jobs: LibraryJob[]; stt: { available: boolean; hint?: string | null } }>(
            `/v1/meetingsense/jobs?${new URLSearchParams({ ...(params.meeting_id ? { meeting_id: params.meeting_id } : {}), ...(params.active ? { active: '1' } : {}) })}`),
    cancelJob: (id: string) => call<{ job: LibraryJob }>(`/v1/meetingsense/jobs/${id}/cancel`, { method: 'POST' }),
    retryJob: (id: string) => call<{ job: LibraryJob }>(`/v1/meetingsense/jobs/${id}/retry`, { method: 'POST' }),
    projects: async (): Promise<Array<{ id: string; name: string }>> => {
        try {
            const body = await call<any>('/projects');
            const list = Array.isArray(body?.projects) ? body.projects : Array.isArray(body) ? body : [];
            return list.filter((p: any) => p?.id && !p?.is_example).map((p: any) => ({ id: String(p.id), name: String(p.name || 'Untitled') }));
        } catch {
            return [];
        }
    },
};

/** A media URL an <audio> element can load (it cannot send headers, so the token rides along). */
export function mediaUrl(meetingId: string, assetId: string, download = false): string {
    let token = '';
    try { token = window.localStorage.getItem('homepilot_auth_token') || ''; } catch { /* ignore */ }
    const q = new URLSearchParams();
    if (token) q.set('token', token);
    if (download) q.set('download', '1');
    const qs = q.toString();
    return url(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}/media/${assetId}${qs ? `?${qs}` : ''}`);
}

export function transcriptUrl(meetingId: string, fmt: 'txt' | 'md' | 'srt' | 'vtt' | 'json'): string {
    return url(`/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}/transcript?fmt=${fmt}`);
}

/**
 * Upload files for an import preview, reporting progress. XHR rather than fetch: fetch
 * cannot report upload progress, and a 600 MB WAV needs a progress bar.
 */
export function previewImport(files: File[], projectId: string, onProgress?: (fraction: number) => void,
                              signal?: AbortSignal): Promise<ImportPreview> {
    return new Promise((resolve, reject) => {
        const form = new FormData();
        files.forEach((f) => form.append('files', f, f.name));
        form.append('project_id', projectId || '');
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url('/v1/meetingsense/imports/preview'));
        xhr.withCredentials = true;
        const headers = requestHeaders();
        Object.entries(headers).forEach(([k, v]) => { if (k.toLowerCase() !== 'content-type') xhr.setRequestHeader(k, v); });
        xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); };
        xhr.onload = () => {
            let body: any = null;
            try { body = JSON.parse(xhr.responseText); } catch { /* ignore */ }
            if (xhr.status >= 200 && xhr.status < 300) resolve(body as ImportPreview);
            else {
                const d = body?.detail;
                reject(typeof d === 'object' && d
                    ? new LibraryError(d.message || `HTTP ${xhr.status}`, xhr.status, d.code || '', d.hint || '')
                    : new LibraryError(typeof d === 'string' ? d : `HTTP ${xhr.status}`, xhr.status));
            }
        };
        xhr.onerror = () => reject(new LibraryError('HomePilot could not be reached.', 0, 'offline'));
        xhr.onabort = () => reject(new LibraryError('Upload cancelled.', 0, 'aborted'));
        signal?.addEventListener('abort', () => xhr.abort());
        xhr.send(form);
    });
}
