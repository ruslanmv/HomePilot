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
    slides: number;
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
