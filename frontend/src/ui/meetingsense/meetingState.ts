/**
 * What the meeting card knows, as functions (batch MS6).
 *
 * The components below this are renderers. Every decision a reader would notice — whether a
 * line is new, what the pill says, whether the view should follow the transcript down — is a
 * pure function here, so it can be tested for the thing that actually matters rather than for
 * the markup that happens to express it.
 *
 * The §2a bar this file exists to keep: **nothing already shown ever changes.** Segments are
 * append-only, a re-render contains every line it contained before, and a provisional line is
 * replaced in place rather than added beside the real one. A transcript that rewrites itself
 * is one the reader stops trusting, and they stop quietly.
 */

export interface Segment {
    id?: string;
    seq?: number;
    t0?: number;
    t1?: number | null;
    speaker?: string | null;
    text: string;
    conf?: number | null;
    replayed?: boolean;
}

export interface Partial {
    t0?: number;
    speaker?: string | null;
    text: string;
}

/** One captured keyframe (MS9/MS10). ``caption`` is null until the model answers, and stays
 *  null forever on an install with no vision model — which is a complete meeting. */
export interface Slide {
    id?: string;
    /** Milliseconds into the meeting, on the *same* clock as a segment's ``t0``. */
    t?: number;
    url: string;
    caption?: string | null;
    hash?: string | null;
    /** The same picture as an earlier slide, captioned once. */
    reused?: boolean;
}

/** MS25. An offer on the card, produced by a deterministic trigger server-side. */
export interface Chip {
    id: string;
    kind: 'question' | 'decision' | 'action' | 'date' | 'link';
    text: string;
    t0?: number | null;
    owner?: string;
    when?: string;
    url?: string;
    /** What the chip offers to do. Absent means there is nothing to run — a `question` chip
     *  has nothing to do about it except answer it. **Never executed by rendering.** */
    proposal?: { capability: string; label: string; args?: Record<string, unknown> };
    /** Local, per client: the user dismissed this offer. Dismissal is not sent anywhere —
     *  it is one reader deciding they are not interested, not a fact about the meeting. */
    dismissed?: boolean;
    /** What came back after the user accepted. */
    result?: { ok: boolean; tool?: string; reason?: string } | null;
    /** Accepted, and the answer has not arrived yet. */
    pending?: boolean;
}

export type Phase = 'idle' | 'live' | 'reconnecting' | 'stopping' | 'ended';

export interface MeetingView {
    phase: Phase;
    meetingId: string | null;
    segments: Segment[];
    partial: Partial | null;
    elapsedMs: number;
    behindMs: number;
    micMuted: boolean;
    levels: number[];
    provider: string | null;
    audioMode: string | null;
    /** How many keyframes the *server* has. Can lead ``slideList`` by a frame while one is
     *  still in flight, which is why the pill reads this and the strip reads the list. */
    slides: number;
    slideList: Slide[];
    chips: Chip[];
    error: string | null;
}

export const EMPTY_VIEW: MeetingView = {
    phase: 'idle',
    meetingId: null,
    segments: [],
    partial: null,
    elapsedMs: 0,
    behindMs: 0,
    micMuted: false,
    levels: [0],
    provider: null,
    audioMode: null,
    slides: 0,
    slideList: [],
    chips: [],
    error: null,
};

/**
 * Add a segment without ever duplicating one.
 *
 * Resume replays: after a reconnect the server re-sends everything above the sequence the
 * client acknowledged, and some of that may already be on screen. Keying on `id` makes the
 * merge idempotent, so a replay is invisible instead of doubling the last few lines — which
 * is precisely the moment a reader is already unsettled by a "reconnecting" pill.
 *
 * Ordering is by `seq` where both have one. A replayed segment can arrive after a newer live
 * one, and appending it would put an older line at the bottom of the transcript.
 */
export function mergeSegment(segments: Segment[], incoming: Segment): Segment[] {
    const existing = incoming.id ? segments.findIndex((s) => s.id === incoming.id) : -1;
    if (existing !== -1) {
        // Already shown. Keep what is on screen rather than swapping in a copy: identical
        // content re-rendered is still a re-render, and this is the append-only promise.
        return segments;
    }
    const next = segments.concat(incoming);
    if (incoming.seq === undefined) return next;
    return next.sort((a, b) => (a.seq ?? Number.MAX_SAFE_INTEGER) - (b.seq ?? Number.MAX_SAFE_INTEGER));
}

/**
 * Add or update a slide, keeping the strip in time order.
 *
 * An upsert rather than an append, because one slide arrives twice: once when the recorder
 * takes it, and again when the caption lands seconds later. Appending both would put the same
 * picture in the strip twice with one of them blank.
 *
 * This does not break §2a's "nothing already shown changes". A caption arriving fills a blank
 * that was visibly a blank — the thumbnail, its position and its timestamp are all unchanged.
 * What that rule forbids is *rewriting* something the reader has already read.
 *
 * Ordered by ``t``: a caption for slide 2 can land after slide 3 has been taken, and appending
 * on arrival would leave the strip in the order the model happened to answer in.
 */
export function mergeSlide(slides: Slide[], incoming: Slide): Slide[] {
    const at = incoming.id ? slides.findIndex((s) => s.id === incoming.id) : -1;
    const next = slides.slice();
    if (at !== -1) {
        // Merged field by field, and **only by a value that says something**. A plain spread
        // looks equivalent and is not: the two frames for one slide can arrive in either
        // order across a reconnect, so the "taken" frame's `caption: null` can land after the
        // captioned one and would erase a caption the reader has already read. Same for a
        // frame that omits the url — it would blank the thumbnail on screen.
        const merged: Record<string, unknown> = { ...next[at] };
        for (const [key, value] of Object.entries(incoming)) {
            if (value === undefined || value === null || value === '') continue;
            merged[key] = value;
        }
        next[at] = merged as unknown as Slide;
    } else {
        next.push(incoming);
    }
    return next.sort((a, b) => (a.t ?? 0) - (b.t ?? 0));
}

/**
 * The transcript spoken while one slide was up — MS10's join, and the reason keyframes carry
 * the transcript's clock rather than a wall clock.
 *
 * **Half-open on the start of the next slide.** A segment whose ``t0`` equals the next slide's
 * timestamp belongs to that next slide: the words began as the new slide went up, and a
 * closed interval would put the opening sentence of every slide under the one before it.
 *
 * **Attribution is by where a segment *starts*.** A sentence that ran across a slide change
 * belongs to the slide it began under. The alternative — splitting on overlap — would show the
 * same words under two slides, and a reader who has just read them under slide 3 does not need
 * to read them again under slide 4.
 */
export function segmentsDuring(slides: Slide[], segments: Segment[], index: number): Segment[] {
    const slide = slides[index];
    if (!slide) return [];
    const from = slide.t ?? 0;
    const nextSlide = slides[index + 1];
    const to = nextSlide ? (nextSlide.t ?? Number.MAX_SAFE_INTEGER) : Number.MAX_SAFE_INTEGER;
    return segments.filter((segment) => {
        const t0 = segment.t0 ?? 0;
        return t0 >= from && t0 < to;
    });
}

/** What a strip entry says under its thumbnail. */
export function slideLabel(slide: Slide): string {
    const caption = (slide.caption || '').trim();
    // Not "no caption": the difference between "the model has not answered yet" and "there is
    // no model here" is not something the strip can tell, and either way what the reader can
    // act on is the timestamp and the picture.
    return caption || 'Not captioned';
}

/** ``mm:ss``, or ``h:mm:ss`` once a meeting runs past the hour. */
export function elapsedLabel(ms: number): string {
    const total = Math.max(0, Math.floor((ms || 0) / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    const pad = (n: number) => String(n).padStart(2, '0');
    return hours ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

/** ``00:01:05`` for a transcript line — always three parts, so the column stays aligned. */
export function stampLabel(ms?: number): string {
    const total = Math.max(0, Math.floor((ms || 0) / 1000));
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(Math.floor(total / 3600))}:${pad(Math.floor((total % 3600) / 60))}:${pad(total % 60)}`;
}

export function speakerLabel(speaker?: string | null): string {
    if (speaker === 'me') return 'You';
    if (speaker === 'them') return 'Them';
    return 'Speaker';
}

/** Below this the transcript is keeping up and saying so would be noise. */
export const BEHIND_THRESHOLD_MS = 2000;

/**
 * *"catching up · 12 s behind"*, or nothing.
 *
 * §2a's rule is that a slow transcript must say it is slow rather than look broken — silence
 * where words should be reads as a bug, and the user's next move is to stop the recording. The
 * threshold is deliberately above one chunk: a transcript momentarily one utterance behind is
 * working normally, and a label that flickers on every sentence is worse than none.
 */
export function latencyLabel(behindMs: number): string | null {
    if (!behindMs || behindMs < BEHIND_THRESHOLD_MS) return null;
    return `catching up · ${Math.round(behindMs / 1000)} s behind`;
}

/** What the pill says it is doing. One phrase, never two at once. */
export function phaseLabel(view: MeetingView): string {
    if (view.phase === 'reconnecting') return 'reconnecting…';
    if (view.phase === 'stopping') return 'stopping…';
    if (view.phase === 'ended') return 'ended';
    if (view.phase === 'idle') return 'not recording';
    return latencyLabel(view.behindMs) || 'recording';
}

/** How close to the bottom still counts as "at the bottom", in pixels. */
export const STICK_SLACK_PX = 48;

/**
 * Whether new lines should scroll into view.
 *
 * Only when the reader is already at the bottom. Somebody who has scrolled up is reading
 * something, and yanking them back down mid-sentence every time a new line lands is the
 * single most irritating thing a live transcript can do.
 */
export function shouldStickToBottom(el: {
    scrollTop: number;
    scrollHeight: number;
    clientHeight: number;
}): boolean {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_SLACK_PX;
}

/** Peak level across channels, clamped — what the pill's meter draws. */
export function meterLevel(levels: number[]): number {
    if (!levels || !levels.length) return 0;
    return Math.max(0, Math.min(1, Math.max(...levels) * 6));
}

/**
 * The consent sentence, built from the same `/status` the popover reads.
 *
 * Naming the provider is the point: someone who set `STT_BASE_URL` months ago for voice calls
 * would otherwise send an hour of meeting audio to it having been told only that recording had
 * started. The endpoint itself is never shown — it can carry a key.
 */
export function consentSentences(status: {
    stt?: { provider?: string | null; remote?: boolean; segments?: boolean };
    retention?: string;
} | null): string[] {
    const stt = (status && status.stt) || {};
    const lines: string[] = [];
    lines.push(
        stt.remote
            ? `Audio is sent to your configured speech endpoint (${stt.provider || 'remote'}) to be transcribed.`
            : `Audio is transcribed on this machine by ${stt.provider || 'the local speech model'}, and does not leave it.`,
    );
    lines.push(
        status?.retention === 'all'
            ? 'The transcript, the slide images and the audio are kept until you delete the meeting.'
            : status?.retention === 'text+frames'
              ? 'The transcript and slide images are kept until you delete the meeting; the audio is not.'
              : 'Only the transcript is kept. No audio and no images are stored.',
    );
    lines.push('Tell the other people in the meeting that you are recording.');
    return lines;
}

/** Seconds a stop can be taken back. Capture keeps running throughout — see MeetingCard. */
export const UNDO_WINDOW_MS = 10000;


/**
 * How many chips the card shows at once (MS25).
 *
 * Three. A chip interrupts, and a column of them is not three interruptions — it is a panel
 * nobody reads, which is how a feature that fires correctly still fails.
 */
export const MAX_VISIBLE_CHIPS = 3;

/**
 * Add or update a chip, keyed on `id`.
 *
 * Idempotent for the same reason `mergeSegment` is: a reconnect or a second client on one
 * meeting re-offers what it already offered, and the server derives a chip's id from the offer
 * rather than from a counter — so the same offer is the same row rather than a second one.
 *
 * **Local state is never overwritten by a re-offer.** A chip the reader dismissed stays
 * dismissed, and one they accepted keeps its result: the second copy is the same offer
 * arriving again, not news about it.
 */
export function mergeChip(chips: Chip[], incoming: Chip): Chip[] {
    if (!incoming || !incoming.id) return chips;
    const at = chips.findIndex((c) => c.id === incoming.id);
    if (at === -1) return [...chips, incoming];
    const next = chips.slice();
    next[at] = {
        ...incoming,
        dismissed: chips[at].dismissed,
        pending: chips[at].pending,
        result: chips[at].result,
    };
    return next;
}

/** Mark a chip dismissed. Local only — nothing is sent, and nothing is deleted. */
export function dismissChip(chips: Chip[], id: string): Chip[] {
    return chips.map((c) => (c.id === id ? { ...c, dismissed: true } : c));
}

/** Record what came back from an accepted chip, and clear its pending state. */
export function resolveChip(
    chips: Chip[],
    id: string,
    result: { ok: boolean; tool?: string; reason?: string },
): Chip[] {
    return chips.map((c) => (c.id === id ? { ...c, pending: false, result } : c));
}

/**
 * The chips actually on screen: newest first, dismissed ones gone, capped.
 *
 * Newest first because a chip is about what was *just* said; oldest-first would put the offer
 * the reader has already ignored at the top of the list and the one they might want off the
 * bottom of it.
 *
 * A chip whose action has run stays visible, so somebody who pressed a button can see what it
 * did rather than watching the row vanish and having to trust it.
 */
export function visibleChips(chips: Chip[], limit = MAX_VISIBLE_CHIPS): Chip[] {
    return chips.filter((c) => !c.dismissed).slice(-limit).reverse();
}

/** The words on a chip's badge. One place, so the card and a test agree. */
export function chipLabel(chip: Chip): string {
    switch (chip.kind) {
        case 'question':
            return 'Asked you';
        case 'decision':
            return 'Decision';
        case 'action':
            return chip.owner && chip.owner !== 'me' ? `Action · ${chip.owner}` : 'Action';
        case 'date':
            return chip.when ? `Date · ${chip.when}` : 'Date';
        case 'link':
            return 'Link on slide';
        default:
            return 'Note';
    }
}
