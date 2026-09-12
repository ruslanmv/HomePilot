/**
 * Bridge the plain MeetingSense recorder into React state.
 *
 * The recorder owns capture and the socket; this hook owns the UI view. Ending a meeting is
 * deliberately immediate: the recorder is stopped as soon as the user confirms End, so mic
 * and display tracks are released before recap generation starts.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
    EMPTY_VIEW,
    dismissChip,
    mergeChip,
    mergeSegment,
    mergeSlide,
    resolveChip,
    type MeetingView,
    type Phase,
    type Segment,
    type Slide,
} from './meetingState';
import type { MeetingRecord } from './meetingRecord';

export interface Recorder {
    start: (options: Record<string, unknown>) => Promise<{ ok: boolean; meetingId?: string; error?: string }>;
    stop: () => Promise<unknown>;
    muteMic: (muted: boolean) => void;
    acceptChip?: (id: string) => boolean;
    levels?: number[];
    behindMs?: number;
    audioMode?: string;
}

function recorderOf(): Recorder | null {
    return (globalThis as unknown as { hpMeetingSense?: Recorder }).hpMeetingSense || null;
}

export interface UseMeetingSenseOptions {
    recorder?: Recorder | null;
    provider?: string | null;
    target?: EventTarget;
}

function numberOr(value: unknown, fallback = 0): number {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
}

function segmentFromRecord(row: Record<string, unknown>, index: number): Segment {
    return {
        id: typeof row.id === 'string' ? row.id : `stored-segment-${index}`,
        seq: typeof row.seq === 'number' ? row.seq : undefined,
        t0: numberOr(row.t0 ?? row.t0_ms),
        t1: row.t1 == null && row.t1_ms == null ? null : numberOr(row.t1 ?? row.t1_ms),
        speaker: typeof row.speaker === 'string' ? row.speaker : null,
        text: typeof row.text === 'string' ? row.text : '',
        conf: typeof row.conf === 'number' ? row.conf : null,
    };
}

function slideFromRecord(row: Record<string, unknown>, index: number): Slide | null {
    const url = typeof row.url === 'string' ? row.url : '';
    if (!url) return null;
    return {
        id: typeof row.id === 'string' ? row.id : `stored-slide-${index}`,
        t: numberOr(row.t ?? row.t_ms),
        url,
        caption: typeof row.caption === 'string' ? row.caption : null,
        hash: typeof row.hash === 'string' ? row.hash : null,
        reused: row.reused === true,
    };
}

export function useMeetingSense(options: UseMeetingSenseOptions = {}) {
    const [view, setView] = useState<MeetingView>(EMPTY_VIEW);
    // Kept in the public API for compatibility with older controls. The dedicated workspace no
    // longer offers capture-while-counting-down undo, so this remains null.
    const [undoSecondsLeft] = useState<number | null>(null);
    const tick = useRef<ReturnType<typeof setInterval> | null>(null);
    const stopping = useRef(false);

    const target = options.target || (globalThis as unknown as EventTarget);
    const recorder = options.recorder !== undefined ? options.recorder : recorderOf();

    const patch = useCallback((next: Partial<MeetingView>) => {
        setView((current) => ({ ...current, ...next }));
    }, []);

    useEffect(() => {
        const onSegment = (event: Event) => {
            const detail = (event as CustomEvent).detail;
            setView((current) => ({
                ...current,
                segments: mergeSegment(current.segments, detail),
                partial: null,
            }));
        };
        const onPartial = (event: Event) => patch({ partial: (event as CustomEvent).detail });
        const onSlide = (event: Event) => {
            const detail = (event as CustomEvent).detail;
            if (!detail || !detail.url) return;
            setView((current) => ({ ...current, slideList: mergeSlide(current.slideList, detail) }));
        };
        const onStatus = (event: Event) => {
            const detail = (event as CustomEvent).detail || {};
            setView((current) => ({
                ...current,
                behindMs: detail.behind_ms ?? current.behindMs,
                elapsedMs: detail.elapsed ?? current.elapsedMs,
                micMuted: detail.mic_muted ?? current.micMuted,
                slides: detail.slides ?? current.slides,
                error: detail.type === 'error' ? detail.msg || detail.code : current.error,
                phase: detail.type === 'final' ? 'ended' : current.phase,
            }));
            if (detail.type === 'final') stopping.current = false;
        };
        const onChip = (event: Event) => {
            setView((current) => ({
                ...current,
                chips: mergeChip(current.chips, (event as CustomEvent).detail),
            }));
        };
        const onChipResult = (event: Event) => {
            const detail = (event as CustomEvent).detail;
            if (!detail) return;
            setView((current) => ({ ...current, chips: resolveChip(current.chips, detail.id, detail) }));
        };
        const onMode = (event: Event) => {
            const detail = (event as CustomEvent).detail || {};
            if (detail.mode) patch({ mode: detail.mode });
        };
        const onQueued = (event: Event) => {
            const detail = (event as CustomEvent).detail || {};
            if (typeof detail.waiting === 'number') patch({ queued: detail.waiting });
        };
        const onReconnecting = () => patch({ phase: 'reconnecting' });
        const onResumed = () => patch({ phase: 'live', error: null });
        const onAudioLost = (event: Event) => {
            patch({ audioMode: (event as CustomEvent).detail?.audioMode ?? null });
        };

        const handlers: Array<[string, EventListener]> = [
            ['ms:segment', onSegment],
            ['ms:partial', onPartial],
            ['ms:slide', onSlide],
            ['ms:chip', onChip],
            ['ms:mode', onMode],
            ['ms:queued', onQueued],
            ['ms:chip_result', onChipResult],
            ['ms:status', onStatus],
            ['ms:reconnecting', onReconnecting],
            ['ms:resumed', onResumed],
            ['ms:audio_lost', onAudioLost],
        ];
        for (const [name, handler] of handlers) target.addEventListener(name, handler);
        return () => {
            for (const [name, handler] of handlers) target.removeEventListener(name, handler);
        };
    }, [target, patch]);

    useEffect(() => {
        if (view.phase === 'idle' || view.phase === 'ended' || !recorder) return undefined;
        tick.current = setInterval(() => {
            patch({ levels: recorder.levels || [0] });
        }, 100);
        return () => {
            if (tick.current) clearInterval(tick.current);
            tick.current = null;
        };
    }, [view.phase, recorder, patch]);

    const start = useCallback(
        async (opts: Record<string, unknown>) => {
            if (!recorder) return { ok: false, error: 'the recorder is not loaded' };
            stopping.current = false;
            const result = await recorder.start(opts);
            if (result.ok) {
                setView({
                    ...EMPTY_VIEW,
                    phase: 'live',
                    meetingId: result.meetingId ?? null,
                    provider: options.provider ?? null,
                    audioMode: recorder.audioMode ?? null,
                });
            }
            return result;
        },
        [recorder, options.provider],
    );

    /**
     * End means end. The recorder's stop path flushes the current utterance and tears down all
     * media tracks synchronously before its promise settles; recap work can continue after the
     * browser/OS capture indicators have already gone away.
     */
    const stop = useCallback(async () => {
        if (stopping.current || view.phase === 'idle' || view.phase === 'ended') return;
        stopping.current = true;
        patch({ phase: 'stopping' });
        try {
            await recorder?.stop();
        } finally {
            stopping.current = false;
            patch({ phase: 'ended' });
        }
    }, [recorder, patch, view.phase]);

    // Compatibility only. The previous 10-second undo kept recording after Stop; the Meeting
    // Workspace intentionally removes that behavior because a confirmed End must release
    // capture immediately.
    const undo = useCallback(() => undefined, []);

    const muteMic = useCallback(
        (muted: boolean) => {
            recorder?.muteMic(muted);
            patch({ micMuted: muted });
        },
        [recorder, patch],
    );

    const acceptChip = useCallback(
        (id: string) => {
            if (!recorder?.acceptChip) return;
            if (!recorder.acceptChip(id)) return;
            setView((current) => ({
                ...current,
                chips: current.chips.map((c) => (c.id === id ? { ...c, pending: true } : c)),
            }));
        },
        [recorder],
    );

    const dismissChipById = useCallback((id: string) => {
        setView((current) => ({ ...current, chips: dismissChip(current.chips, id) }));
    }, []);

    /** Rebuild an origin meeting conversation as a recap workspace when History opens it. */
    const hydrateRecord = useCallback((record: MeetingRecord) => {
        const meeting = record.meeting || null;
        const segments = (record.segments || [])
            .filter((row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'))
            .map(segmentFromRecord)
            .filter((segment) => Boolean(segment.text));
        const slideList = (record.keyframes || [])
            .filter((row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'))
            .map(slideFromRecord)
            .filter((slide): slide is Slide => Boolean(slide));
        const started = typeof meeting?.started_at === 'number' ? meeting.started_at : null;
        const ended = typeof meeting?.ended_at === 'number' ? meeting.ended_at : null;
        const elapsedMs = started != null && ended != null ? Math.max(0, Math.round((ended - started) * 1000)) : 0;
        setView({
            ...EMPTY_VIEW,
            phase: record.live ? 'live' : 'ended',
            meetingId: typeof meeting?.id === 'string' ? meeting.id : null,
            segments,
            elapsedMs,
            provider: options.provider ?? null,
            audioMode: meeting?.audio_mode ?? null,
            slides: slideList.length,
            slideList,
        });
    }, [options.provider]);

    const reset = useCallback(() => {
        stopping.current = false;
        setView({ ...EMPTY_VIEW });
    }, []);

    useEffect(
        () => () => {
            if (tick.current) clearInterval(tick.current);
        },
        [],
    );

    return {
        view,
        start,
        stop,
        undo,
        muteMic,
        acceptChip,
        dismissChip: dismissChipById,
        hydrateRecord,
        reset,
        undoSecondsLeft,
        setPhase: (p: Phase) => patch({ phase: p }),
    };
}

export default useMeetingSense;
