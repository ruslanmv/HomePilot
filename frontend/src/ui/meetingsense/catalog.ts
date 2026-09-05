/**
 * Finding a meeting again (batch MS28, wave W10).
 *
 * Every decision this batch makes, as a pure function — the same split `meetingState.ts` uses,
 * for the same reason: a filter is the thing that has to be right, and a renderer is the wrong
 * place to test one.
 *
 * **D5 decided where the catalog lives: History.** A meeting *is* a conversation, so the
 * cheap and correct surface is a filter chip on the list the user already opens, and the
 * library grid is a second view of the same rows behind a flag that defaults off. That flag is
 * the mechanism for D5's condition — "a sidebar tab only if History gets crowded" — and it
 * stays off until somebody's History actually is.
 *
 * **A meeting is identified by the server, never by its title.** D5 notes that the meeting
 * message is the last message, so a conversation's History label leads with the meeting's own
 * first line. That makes title-sniffing look viable and it is not: the label is the *last*
 * message, so it stops being the meeting's the moment anybody replies in the thread — which is
 * the normal case, since MS16 exists to make people carry on talking there. So the rows come
 * from `GET /v1/meetingsense/meetings`, which knows, and a conversation is a meeting when its
 * id is in that set.
 */

/** One row of `GET /v1/meetingsense/meetings`. */
export interface Meeting {
    id: string;
    conversation_id?: string | null;
    title?: string | null;
    source?: string | null;
    started_at?: number | null;
    ended_at?: number | null;
    state?: string | null;
    attendees?: string | null;
    segments?: number | null;
    keyframes?: number | null;
}

/** The subset of a History row this module needs. */
export interface ConversationLike {
    conversation_id: string;
    last_content: string;
    updated_at: string | number;
}

/** The mic that marks a meeting in History. D5's format, and the chip's icon. */
export const MEETING_MARK = '🎙';

/** Sources we know how to name. Anything else is shown as it arrived. */
const SOURCE_LABELS: Record<string, string> = {
    zoom: 'Zoom',
    meet: 'Google Meet',
    teams: 'Microsoft Teams',
    webex: 'Webex',
    slack: 'Slack',
    discord: 'Discord',
    local: 'This machine',
};

export function sourceLabel(source?: string | null): string {
    const key = (source || '').trim().toLowerCase();
    if (!key) return 'Unknown source';
    return SOURCE_LABELS[key] || source!.trim();
}

/**
 * The conversations that have a recording behind them.
 *
 * A Set rather than a predicate over each row, because History renders every conversation on
 * every keystroke of the search box and a linear scan per row turns that quadratic on the one
 * account where it matters — the one with enough history to want the filter.
 */
export function meetingConversations(meetings: Meeting[]): Set<string> {
    const out = new Set<string>();
    for (const meeting of meetings || []) {
        const id = (meeting?.conversation_id || '').trim();
        if (id) out.add(id);
    }
    return out;
}

/** How a meeting is titled, per D5: `🎙 <title> · <source> · <date>`. */
export function meetingTitle(meeting: Meeting): string {
    const parts: string[] = [];
    const name = (meeting?.title || '').trim();
    // MS17 names a meeting from its window title or its calendar event. Until that lands — and
    // on an install with neither — a meeting has no name, and "Untitled meeting" is a truer
    // label than a timestamp pretending to be one.
    parts.push(name || 'Untitled meeting');
    const source = (meeting?.source || '').trim();
    if (source) parts.push(sourceLabel(source));
    const when = dayLabel(meeting?.started_at);
    if (when) parts.push(when);
    return `${MEETING_MARK} ${parts.join(' · ')}`;
}

/** Seconds since the epoch → a short day label, or `''` when there is no usable time. */
export function dayLabel(startedAt?: number | null): string {
    if (typeof startedAt !== 'number' || !Number.isFinite(startedAt) || startedAt <= 0) return '';
    return new Date(startedAt * 1000).toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
    });
}

/**
 * How long it ran, in words. `''` for a meeting still running or missing an end.
 *
 * Rounded to the minute and never to zero: a meeting that ran for forty seconds reads as
 * "under a minute" rather than "0 min", which looks like a bug in the recorder.
 */
export function durationLabel(meeting: Meeting): string {
    const from = meeting?.started_at;
    const to = meeting?.ended_at;
    // Both have to be numbers, checked rather than left to the arithmetic: a server that sent
    // `"1800"` would otherwise subtract cleanly and report a duration for a meeting that has
    // not ended.
    if (typeof from !== 'number' || typeof to !== 'number') return '';
    const seconds = to - from;
    if (!Number.isFinite(seconds) || seconds < 0) return '';
    if (seconds < 60) return 'under a minute';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** Is this meeting still running? */
export function isLive(meeting: Meeting): boolean {
    return (meeting?.state || '').trim().toLowerCase() === 'live';
}

// ── History: the filter chip ────────────────────────────────────────────────

export interface HistoryFilter {
    query?: string;
    /** The chip. `false` is History exactly as it was. */
    meetingsOnly?: boolean;
    meetingIds?: Set<string>;
}

/**
 * History's list, filtered.
 *
 * **With the chip off this is History's own behaviour, unchanged** — same predicate, same
 * order, same rows. That is the acceptance criterion for the flag-off case restated as code:
 * a filter that subtly reorders the list when it is *not* filtering is a regression wearing a
 * feature's clothes.
 */
export function filterConversations<T extends ConversationLike>(
    conversations: T[],
    { query = '', meetingsOnly = false, meetingIds }: HistoryFilter = {},
): T[] {
    const needle = query.trim().toLowerCase();
    return (conversations || []).filter((conv) => {
        if (meetingsOnly && !(meetingIds && meetingIds.has(conv.conversation_id))) return false;
        // No empty-query fast path: `includes('')` is already true for every row, so a guard
        // here would be a second statement of the same rule and one more thing to keep in step.
        return (
            conv.conversation_id.toLowerCase().includes(needle)
            || (conv.last_content || '').toLowerCase().includes(needle)
        );
    });
}

/** How many of these conversations are meetings — the number on the chip. */
export function meetingCount(
    conversations: ConversationLike[],
    meetingIds: Set<string>,
): number {
    let n = 0;
    for (const conv of conversations || []) if (meetingIds.has(conv.conversation_id)) n += 1;
    return n;
}

// ── the library grid ────────────────────────────────────────────────────────

export interface LibraryFilter {
    query?: string;
    /** `''` is every source. */
    source?: string;
    /** Seconds since the epoch; meetings started before this are hidden. */
    since?: number | null;
}

/**
 * The grid's rows, filtered and newest first.
 *
 * Searches the title, the source and the attendees — the three things somebody actually
 * remembers about a meeting they are trying to find again. Not the transcript: that is
 * `GET /v1/meetingsense/search`, which is MS15's retrieval with citations, and a second
 * substring scan over the same words here would be a worse answer to the same question.
 */
export function filterMeetings(meetings: Meeting[], filter: LibraryFilter = {}): Meeting[] {
    const needle = (filter.query || '').trim().toLowerCase();
    const source = (filter.source || '').trim().toLowerCase();
    const since = typeof filter.since === 'number' ? filter.since : null;

    const kept = (meetings || []).filter((meeting) => {
        if (source && (meeting?.source || '').trim().toLowerCase() !== source) return false;
        if (since !== null) {
            const started = meeting?.started_at;
            // Inclusive at the boundary: "the last 7 days" contains the moment 7 days ago.
            if (typeof started !== 'number' || started < since) return false;
        }
        if (!needle) return true;
        const haystack = [
            meeting?.title || '',
            meeting?.source || '',
            sourceLabel(meeting?.source),
            meeting?.attendees || '',
        ].join(' ').toLowerCase();
        return haystack.includes(needle);
    });

    // Sorted in place: `filter` above already returned a new array, so the caller's list is
    // untouched and a `.slice()` here would be copying a copy.
    return kept.sort((a, b) => (b?.started_at || 0) - (a?.started_at || 0));
}

/** The sources present, for the facet row. Alphabetical, so the chips do not move about. */
export function sources(meetings: Meeting[]): string[] {
    const seen = new Set<string>();
    for (const meeting of meetings || []) {
        const source = (meeting?.source || '').trim();
        if (source) seen.add(source);
    }
    return [...seen].sort();
}

/** Seconds since the epoch for "the last N days", or `null` for all time. */
export function since(days: number | null, now: number = Date.now() / 1000): number | null {
    if (days === null || !Number.isFinite(days) || days <= 0) return null;
    return now - days * 86_400;
}

/** Meetings grouped by day, newest day first, newest meeting first inside each. */
export function groupByDay(meetings: Meeting[]): Array<{ day: string; meetings: Meeting[] }> {
    const buckets = new Map<string, Meeting[]>();
    for (const meeting of filterMeetings(meetings)) {
        const day = dayLabel(meeting?.started_at) || 'Undated';
        const bucket = buckets.get(day);
        if (bucket) bucket.push(meeting);
        else buckets.set(day, [meeting]);
    }
    return [...buckets.entries()].map(([day, rows]) => ({ day, meetings: rows }));
}


// ── the `_CATALOG` flag ─────────────────────────────────────────────────────

/** The shape `GET /v1/meetingsense/status` answers with, as far as this decision cares. */
export interface CatalogStatus {
    enabled?: boolean;
    flags?: { catalog?: boolean };
}

/**
 * Does the sidebar get a Meetings tab?
 *
 * **Both flags, and `enabled` is not implied.** MS0 made the sub-flags deliberately
 * independent of the master, so an install with `MEETINGSENSE_CATALOG` set and MeetingSense
 * itself off would otherwise grow a nav item leading to a view of a feature that cannot run.
 * A client combining the two by guessing would guess wrong in the direction that matters —
 * offering a control the server will refuse — which is the reasoning MS7's `remote_ok` already
 * settled for the other pair.
 *
 * Everything unknown is off. A status route that did not answer, an older server with no
 * `flags` key, a body that is not an object: none of those are a reason to change somebody's
 * sidebar, and D5's condition for this tab existing at all is a person deciding their History
 * is crowded.
 */
export function catalogEnabled(status: CatalogStatus | null | undefined): boolean {
    if (!status || typeof status !== 'object') return false;
    return Boolean(status.enabled) && Boolean(status.flags?.catalog);
}
