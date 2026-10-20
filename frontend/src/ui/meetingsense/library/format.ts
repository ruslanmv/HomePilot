/**
 * How library meetings are labelled — chips, dates, durations. Pure functions, so the rules
 * are tested without rendering anything.
 *
 * The chips follow the Meetings mockup: a type chip (Project Meeting, Client Call, Imported…)
 * and a status chip (Transcribed, Recording, Needs Transcript…). Status is honest by design:
 * a recording whose transcript is empty is "Needs Transcript", never "Transcribed", and a
 * silent one says "No speech".
 */
import type { LibraryItem } from './api';
import { TONE_CLASSES, type Tone } from '../../ds';

// The badge colours are HomePilot's, shared by every page (ui/ds); re-exported here because
// the Meetings code reads them from this module.
export { TONE_CLASSES, type Tone };

const CATEGORY_TONES: Array<[RegExp, Tone]> = [
    [/project/i, 'violet'],
    [/client|customer|sales/i, 'blue'],
    [/import|synced|insta360/i, 'indigo'],
    [/research|interview/i, 'teal'],
    [/executive|board|leadership/i, 'pink'],
    [/team/i, 'sky'],
];

export function categoryTone(category: string): Tone {
    for (const [pattern, tone] of CATEGORY_TONES) if (pattern.test(category || '')) return tone;
    return 'slate';
}

export interface Chip { label: string; tone: Tone; busy?: boolean; title?: string }

/** The status chip for a card: recording first (it is happening now), then the transcript. */
export function statusChip(item: Pick<LibraryItem, 'transcript_state' | 'recording_state' | 'media_present' | 'live' | 'origin_type' | 'warnings'>): Chip {
    if (item.live || item.recording_state === 'recording') return { label: 'Recording', tone: 'red', busy: true };
    if (item.recording_state === 'paused') {
        return { label: 'Reconnecting', tone: 'amber', busy: true, title: 'The connection dropped. Recording continues when the browser reconnects.' };
    }
    switch (item.transcript_state) {
        case 'ready':
        case 'imported':
            return { label: 'Transcribed', tone: 'green' };
        case 'ready_warnings':
            return { label: 'Transcribed', tone: 'green', title: 'Timestamps are approximate' };
        case 'transcript_only':
            return { label: item.origin_type === 'teams_room' ? 'Transcript' : 'Transcript only', tone: 'green' };
        case 'queued':
            return { label: 'Queued', tone: 'sky' };
        case 'transcribing':
            return { label: 'Transcribing', tone: 'sky', busy: true };
        case 'needs_setup':
            return { label: 'Needs setup', tone: 'amber', title: 'Install local speech-to-text to transcribe on this computer' };
        case 'failed':
            return { label: 'Failed', tone: 'red' };
        case 'no_speech':
            return { label: 'No speech', tone: 'slate', title: 'The recording is silent' };
        case 'live':
            return { label: 'Recording', tone: 'red', busy: true };
        default:
            if (item.recording_state === 'awaiting') return { label: 'Awaiting recording', tone: 'slate' };
            if (item.media_present) return { label: 'Needs Transcript', tone: 'amber' };
            return { label: 'No transcript', tone: 'slate' };
    }
}

export function formatDate(ts: number | null | undefined, locale?: string): string {
    if (!ts) return '—';
    return new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(ts * 1000));
}

/** The time of day a meeting started, in the viewer's locale: "10:27 AM", or "10:27". */
export function formatTime(ts: number | null | undefined, locale?: string): string {
    if (!ts) return '';
    return new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(new Date(ts * 1000));
}

/** Date and start time for a card: "10/20/2026 · 10:27 AM". The hour is what tells one day's
 *  meetings apart, so a card never shows the date alone. */
export function formatWhen(ts: number | null | undefined, locale?: string): string {
    if (!ts) return '—';
    return `${formatDate(ts, locale)} · ${formatTime(ts, locale)}`;
}

export function formatDateTime(ts: number | null | undefined, locale?: string): string {
    if (!ts) return '—';
    return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
        .format(new Date(ts * 1000));
}

export function formatDuration(ms: number | null | undefined): string {
    if (ms === null || ms === undefined || ms <= 0) return '—';
    const totalS = Math.round(ms / 1000);
    if (totalS < 60) return `${totalS} s`;
    const min = Math.round(totalS / 60);
    if (min < 60) return `${min} min`;
    const h = Math.floor(min / 60);
    return `${h} h ${String(min % 60).padStart(2, '0')} min`;
}

/** mm:ss or h:mm:ss for a player / transcript timestamp. */
export function clock(ms: number | null | undefined): string {
    const s = Math.max(0, Math.floor((ms || 0) / 1000));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`;
}

/** What the card's last footer slot says: the project it lives in, else where it came from. */
export function footerPlace(item: Pick<LibraryItem, 'projects' | 'source' | 'origin_type'>): { kind: 'project' | 'source'; label: string } {
    const project = item.projects?.find((p) => !p.missing) || item.projects?.[0];
    if (project) return { kind: 'project', label: `Project: ${project.name}` };
    return { kind: 'source', label: item.source?.label || 'Meeting' };
}

export function bytes(n: number | null | undefined): string {
    if (!n) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let v = n;
    let u = 0;
    while (v >= 1024 && u < units.length - 1) { v /= 1024; u += 1; }
    return `${v < 10 && u ? v.toFixed(1) : Math.round(v)} ${units[u]}`;
}

export const TABS: Array<{ id: string; label: string }> = [
    { id: 'all', label: 'All' },
    { id: 'project', label: 'Project Meetings' },
    { id: 'recorded', label: 'Recorded' },
    { id: 'imported', label: 'Imported' },
    { id: 'unsorted', label: 'Unsorted' },
    { id: 'processing', label: 'Processing' },
];

export const SORTS: Array<{ id: string; label: string }> = [
    { id: 'newest', label: 'Newest first' },
    { id: 'oldest', label: 'Oldest first' },
    { id: 'title', label: 'Title A–Z' },
    { id: 'duration', label: 'Longest first' },
];

export const STATE_FILTERS: Array<{ id: string; label: string }> = [
    { id: '', label: 'Any status' },
    { id: 'ready', label: 'Transcribed' },
    { id: 'imported', label: 'Imported transcript' },
    { id: 'transcript_only', label: 'Transcript only' },
    { id: 'none', label: 'No transcript' },
    { id: 'queued', label: 'Queued' },
    { id: 'transcribing', label: 'Transcribing' },
    { id: 'needs_setup', label: 'Needs setup' },
    { id: 'no_speech', label: 'No speech' },
    { id: 'failed', label: 'Failed' },
];

/** Which list items mean "keep polling" — something is still changing. */
export function isWorking(item: Pick<LibraryItem, 'transcript_state' | 'summary_state' | 'live'> & Partial<Pick<LibraryItem, 'recording_state'>>): boolean {
    return item.live || item.transcript_state === 'queued' || item.transcript_state === 'transcribing'
        || item.summary_state === 'pending' || item.recording_state === 'saving';
}

export type SummaryDoc = { text?: string; degraded?: string | null; [k: string]: unknown };

const FALLBACK_MARK = /^\s*\*No language model was reachable/;
const OUTLINE_HEADING = /\n#{1,3}\s*The meeting in order\b[\s\S]*$/;

/**
 * A document assembled from the meeting's own words because no language model answered —
 * flagged `degraded: "extractive"` by the server, or (older documents) marked in its text.
 */
export function isFallbackSummary(doc: SummaryDoc | null | undefined): boolean {
    return !!doc && (doc.degraded === 'extractive' || FALLBACK_MARK.test(doc.text || ''));
}

/**
 * What the Overview shows: the newest written summary without its long chronological outline
 * (the Summary tab has the whole document). A fallback outline is not a summary, so it is
 * skipped; the notes' one-paragraph summary or the meeting description stand in.
 */
export function overviewSummary(docs: SummaryDoc[] | undefined, notesSummary?: string | null, description?: string | null):
    { text: string; markdown: boolean } {
    const written = (docs || []).filter((d) => (d.text || '').trim() && !isFallbackSummary(d));
    const latest = written[written.length - 1];
    if (latest) return { text: (latest.text || '').replace(OUTLINE_HEADING, '').trim(), markdown: true };
    const plain = (notesSummary || description || '').trim();
    return { text: plain, markdown: false };
}

/**
 * The paragraph a "Quick summary" shows: a written document's opening prose — not its headings,
 * lists or later sections, which the Overview shows in full — or the plain fallback text as is.
 */
export function quickSummary(overview: { text: string; markdown: boolean }): string {
    if (!overview.markdown) return overview.text;
    const prose = overview.text
        .split(/\n\s*\n/)
        .map((block) => block.replace(/^(\s*#{1,6}\s.*(\n|$))+/, '').trim())
        .find((block) => block && !/^[-*+]\s|^\d+[.)]\s/.test(block));
    return plainText(prose || overview.text);
}

/** Markdown reduced to readable plain text, for short previews. */
export function plainText(markdown: string): string {
    return markdown
        .replace(/```[\s\S]*?```/g, ' ')
        .replace(/^\s{0,3}#{1,6}\s+/gm, '')
        .replace(/^\s*[-*+]\s+/gm, '• ')
        .replace(/(\*\*|__)(.*?)\1/g, '$2')
        .replace(/(\*|_)(.*?)\1/g, '$2')
        .replace(/`([^`]*)`/g, '$1')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}
