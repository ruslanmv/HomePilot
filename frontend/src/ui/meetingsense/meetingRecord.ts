/**
 * The ended meeting, as data (batch MS33, wave W13).
 *
 * Ten waves built capture and one built the mount. What none of them built is the moment the
 * product actually pays off: the meeting is over, and the question is *did this save me work*.
 * Until now the answer on screen was a transcript — which is the recording, not the value.
 *
 * ── Why this is a fetch and not a socket frame ───────────────────────────────────────────
 *
 * The recorder publishes `ms:segment`, `ms:partial`, `ms:slide`, `ms:chip` … and no notes
 * frame; notes live in the store and `GET /v1/meetingsense/{id}` returns them. That turns out
 * to be the right shape rather than a gap to work around: the same fetch rebuilds a meeting
 * opened three days later, so the ended card and the reopened card are one component with one
 * data path instead of a live view and a separate history view that drift.
 *
 * ── Everything here is pure ──────────────────────────────────────────────────────────────
 *
 * The parsing is the part that can be wrong in ways nobody notices — a notes wrapper unwrapped
 * one level too few, a citation regex that matches the wrong half of `1:23:45`, a decision
 * list that silently drops items with no `text`. So it is all functions from a body to a
 * value, unit-tested without a DOM, and the components below only arrange what these return.
 */

/** One decision, action or open question. The server's shape (`notes_engine._item`). */
export interface NoteItem {
    text: string;
    /** Where in the meeting it was said, in ms. Absent when the model did not cite one. */
    t0?: number;
    /** Who owns an action. Absent on decisions, and on actions nobody was named for. */
    owner?: string;
    /** Questions only: answered later in the meeting. Struck through, never removed. */
    resolved?: boolean;
}

export interface MeetingRow {
    id?: string;
    title?: string | null;
    conversation_id?: string | null;
    project_id?: string | null;
    started_at?: number | null;
    ended_at?: number | null;
    audio_mode?: string | null;
    status?: string | null;
}

/** What `GET /v1/meetingsense/{id}` answers with. */
export interface MeetingRecord {
    meeting?: MeetingRow | null;
    segments?: Array<Record<string, unknown>> | null;
    keyframes?: Array<Record<string, unknown>> | null;
    notes?: unknown;
    live?: boolean;
}

/**
 * The notes object, from whichever of three shapes the caller has.
 *
 * Deliberately a port of the server's `export.notes_body` rather than a guess at one of them.
 * That function carries a scar in its docstring: a test built `{"json": …}` by hand, a shape
 * the store never produces, so the test passed and the Markdown export shipped without its
 * notes for a whole batch. Reading only the shape you happened to test is the bug, so all
 * three are read here too.
 */
export function notesBody(notes: unknown): Record<string, unknown> | null {
    if (!notes || typeof notes !== 'object' || Array.isArray(notes)) return null;
    const outer = notes as Record<string, unknown>;
    for (const candidate of [outer.notes, outer.json, outer]) {
        if (candidate && typeof candidate === 'object' && !Array.isArray(candidate) && candidate !== outer) {
            return candidate as Record<string, unknown>;
        }
        if (typeof candidate === 'string') {
            try {
                const parsed = JSON.parse(candidate);
                if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                    return parsed as Record<string, unknown>;
                }
            } catch {
                // Not JSON. The next candidate may still be the notes.
            }
        }
    }
    for (const key of ['summary', 'decisions', 'actions', 'questions', 'recap']) {
        if (key in outer) return outer;
    }
    return null;
}

/** One list of note items, normalised. Items with no text are dropped, not rendered blank. */
export function items(body: Record<string, unknown> | null, key: string): NoteItem[] {
    const raw = body ? body[key] : null;
    if (!Array.isArray(raw)) return [];
    const out: NoteItem[] = [];
    for (const entry of raw) {
        if (!entry || typeof entry !== 'object') continue;
        const row = entry as Record<string, unknown>;
        const text = typeof row.text === 'string' ? row.text.trim() : '';
        if (!text) continue;
        const item: NoteItem = { text };
        if (typeof row.t0 === 'number' && Number.isFinite(row.t0) && row.t0 >= 0) item.t0 = row.t0;
        if (typeof row.owner === 'string' && row.owner.trim()) item.owner = row.owner.trim();
        if (row.resolved === true) item.resolved = true;
        out.push(item);
    }
    return out;
}

/**
 * The summary paragraph.
 *
 * `recap` is preferred over `summary` for the same reason `ask.answer` prefers it: the recap
 * is the rolling one the engine keeps current, and `summary` can be the earlier, shorter
 * field on an older record. Falling back rather than choosing means a record written by
 * either version reads correctly.
 */
export function summaryOf(body: Record<string, unknown> | null): string {
    if (!body) return '';
    for (const key of ['recap', 'summary']) {
        const value = body[key];
        if (typeof value === 'string' && value.trim()) return value.trim();
    }
    return '';
}

/** Whether there is anything worth showing above the transcript. */
export function hasPayoff(body: Record<string, unknown> | null): boolean {
    return Boolean(
        summaryOf(body) ||
        items(body, 'decisions').length ||
        items(body, 'actions').length,
    );
}

/** `Q3 Planning`, or a date when nobody named it and no calendar did. */
export function titleOf(meeting: MeetingRow | null | undefined, fallback = 'Meeting'): string {
    const title = meeting?.title;
    if (typeof title === 'string' && title.trim()) return title.trim();
    return fallback;
}

/** `42 min`, or `1 h 04 min`. Empty when the meeting has no end yet. */
export function durationLabel(meeting: MeetingRow | null | undefined): string {
    const start = meeting?.started_at;
    const end = meeting?.ended_at;
    if (typeof start !== 'number' || typeof end !== 'number') return '';
    const seconds = Math.round(end - start);
    if (!Number.isFinite(seconds) || seconds < 0) return '';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    return `${hours} h ${String(minutes % 60).padStart(2, '0')} min`;
}

/**
 * `Today`, `Yesterday`, or a date.
 *
 * Relative for the two days somebody actually says out loud, absolute after that. `now` is a
 * parameter because a function that reads the clock cannot be tested across a midnight
 * boundary, and every date bug this programme has hit lived in exactly that gap.
 */
export function dayLabel(meeting: MeetingRow | null | undefined, now = Date.now()): string {
    const start = meeting?.started_at;
    if (typeof start !== 'number' || !Number.isFinite(start)) return '';
    const then = new Date(start * 1000);
    const today = new Date(now);
    const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const days = Math.round((midnight(today) - midnight(then)) / 86_400_000);
    if (days === 0) return 'Today';
    if (days === 1) return 'Yesterday';
    return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// ── citations ───────────────────────────────────────────────────────────────

/**
 * The `mm:ss` and `h:mm:ss` stamps in an answer.
 *
 * `ask.answer` returns `cited` — the stamps it *offered* that survived into the text — so a
 * client does not have to find them. This finds them anyway, because `cited` says which
 * stamps are real and this says *where in the sentence they are*, which is what turns a
 * citation into a link. The two are used together: a match is only made a link when the
 * server also listed it.
 *
 * The pattern is anchored on both sides so `31:42` inside `1:31:42` is not matched as its own
 * stamp — the longer form wins, which is the one the server emits for a meeting over an hour.
 */
const STAMP = /(?<![\d:])(\d{1,2}:)?([0-5]?\d):([0-5]\d)(?![\d:])/g;

export interface Cite {
    /** The stamp exactly as it appears, so a link's text is what the model wrote. */
    stamp: string;
    ms: number;
    start: number;
    end: number;
}

/** `01:05` → 65_000. `NaN` for anything this cannot read. */
export function stampToMs(stamp: string): number {
    const parts = stamp.split(':').map((p) => Number(p));
    if (parts.some((n) => !Number.isFinite(n))) return NaN;
    if (parts.length === 2) return (parts[0] * 60 + parts[1]) * 1000;
    if (parts.length === 3) return (parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000;
    return NaN;
}

/**
 * Split an answer into text and citations.
 *
 * `cited` restricts it: a model that writes "we shipped 12:30 units" has not made a citation,
 * and turning that into a jump link would be the UI inventing a source. When `cited` is
 * absent — an older server — nothing is linked, which is the safe direction.
 */
export function citations(text: string, cited?: readonly string[] | null): Cite[] {
    if (!text) return [];
    const allowed = new Set(cited || []);
    if (!allowed.size) return [];
    const out: Cite[] = [];
    STAMP.lastIndex = 0;
    let match: RegExpExecArray | null = STAMP.exec(text);
    while (match) {
        const stamp = match[0];
        const ms = stampToMs(stamp);
        if (allowed.has(stamp) && Number.isFinite(ms)) {
            out.push({ stamp, ms, start: match.index, end: match.index + stamp.length });
        }
        match = STAMP.exec(text);
    }
    return out;
}

/** An answer, split into the runs a renderer walks: plain text and clickable stamps. */
export type AnswerPart = { kind: 'text'; text: string } | { kind: 'cite'; text: string; ms: number };

export function answerParts(text: string, cited?: readonly string[] | null): AnswerPart[] {
    const marks = citations(text, cited);
    if (!marks.length) return text ? [{ kind: 'text', text }] : [];
    const parts: AnswerPart[] = [];
    let cursor = 0;
    for (const mark of marks) {
        if (mark.start > cursor) parts.push({ kind: 'text', text: text.slice(cursor, mark.start) });
        parts.push({ kind: 'cite', text: mark.stamp, ms: mark.ms });
        cursor = mark.end;
    }
    if (cursor < text.length) parts.push({ kind: 'text', text: text.slice(cursor) });
    return parts;
}

/**
 * The segment a citation lands on: the last one that had started by then.
 *
 * Not the nearest. A stamp names the moment something was said, and the line containing that
 * moment is the one already in progress — jumping forward to the next line would land after
 * the sentence the citation is evidence for.
 */
export function segmentAt(
    segments: ReadonlyArray<{ id?: string; t0?: number; t0_ms?: number }>,
    ms: number,
): string | null {
    let best: string | null = null;
    let bestT0 = -1;
    for (const segment of segments || []) {
        const t0 = typeof segment.t0 === 'number' ? segment.t0
            : typeof segment.t0_ms === 'number' ? segment.t0_ms : null;
        if (t0 === null || t0 > ms) continue;
        if (t0 >= bestT0) {
            bestT0 = t0;
            best = segment.id != null ? String(segment.id) : null;
        }
    }
    return best;
}
