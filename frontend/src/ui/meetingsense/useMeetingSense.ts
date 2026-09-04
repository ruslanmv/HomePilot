/**
 * The hook that joins the recorder to the card (batch MS6).
 *
 * MS4's addon is a plain browser script that publishes DOM events on `window`; this turns
 * those into React state. Events rather than a direct dependency on purpose: the pill and the
 * card are different components on different surfaces, and neither owns the recorder.
 *
 * The one piece of real logic here is the **undo window**, and it is not what it looks like.
 * Pressing Stop does *not* stop the recorder. It starts a ten-second countdown during which
 * capture keeps running, and only then sends `stop`. Undoing therefore leaves no hole — which
 * it would if Stop had actually stopped, since the ten seconds a user spends deciding are
 * usually the ten seconds somebody was still talking.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
    EMPTY_VIEW,
    UNDO_WINDOW_MS,
    dismissChip,
    mergeChip,
    mergeSegment,
    mergeSlide,
    resolveChip,
    type MeetingView,
    type Phase,
} from './meetingState';

export interface Recorder {
    start: (options: Record<string, unknown>) => Promise<{ ok: boolean; meetingId?: string; error?: string }>;
    stop: () => Promise<unknown>;
    muteMic: (muted: boolean) => void;
    /** MS25. Takes an id — the card never sends a chip body back. Optional because an older
     *  addon on a newer card is the ordinary case, and the button is hidden rather than
     *  throwing when it is missing. */
    acceptChip?: (id: string) => boolean;
    levels?: number[];
    behindMs?: number;
    audioMode?: string;
}

function recorderOf(): Recorder | null {
    return (globalThis as unknown as { hpMeetingSense?: Recorder }).hpMeetingSense || null;
}

export interface UseMeetingSenseOptions {
    /** Injected in tests; defaults to `window.hpMeetingSense`. */
    recorder?: Recorder | null;
    provider?: string | null;
    /** Injected in tests; defaults to `window`. */
    target?: EventTarget;
}

export function useMeetingSense(options: UseMeetingSenseOptions = {}) {
    const [view, setView] = useState<MeetingView>(EMPTY_VIEW);
    const [undoSecondsLeft, setUndoSecondsLeft] = useState<number | null>(null);
    const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const tick = useRef<ReturnType<typeof setInterval> | null>(null);

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
                // The provisional line has been superseded by the real one. Cleared here
                // rather than left to time out, so the same words are never on screen twice.
                partial: null,
            }));
        };
        const onPartial = (event: Event) => {
            patch({ partial: (event as CustomEvent).detail });
        };
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
        };
        const onChip = (event: Event) => {
            // No guard here: `mergeChip` already refuses a chip with no id, and a second copy
            // of that rule is a second thing to keep in step. MS2 settled this — one
            // implementation, tested where it lives.
            setView((current) => ({
                ...current,
                chips: mergeChip(current.chips, (event as CustomEvent).detail),
            }));
        };
        const onChipResult = (event: Event) => {
            const detail = (event as CustomEvent).detail;
            // This one *is* needed: it reads `detail.id` before handing it on.
            if (!detail) return;
            setView((current) => ({ ...current, chips: resolveChip(current.chips, detail.id, detail) }));
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

    /** Poll the recorder for the level meter rather than having it push fifty events a second. */
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

    const finishStop = useCallback(async () => {
        undoTimer.current = null;
        setUndoSecondsLeft(null);
        patch({ phase: 'ended' });
        await recorder?.stop();
    }, [recorder, patch]);

    /**
     * Begin stopping — and keep recording.
     *
     * The recorder is untouched until the window closes. A Stop that stopped immediately would
     * make Undo a lie: the ten seconds somebody spends deciding are usually ten seconds
     * somebody else was still talking.
     */
    const stop = useCallback(() => {
        if (undoTimer.current) return;
        patch({ phase: 'stopping' });
        setUndoSecondsLeft(Math.round(UNDO_WINDOW_MS / 1000));
        undoTimer.current = setTimeout(finishStop, UNDO_WINDOW_MS);
    }, [finishStop, patch]);

    const undo = useCallback(() => {
        if (!undoTimer.current) return;
        clearTimeout(undoTimer.current);
        undoTimer.current = null;
        setUndoSecondsLeft(null);
        // Straight back to live, with no gap in the transcript: nothing ever stopped.
        patch({ phase: 'live' });
    }, [patch]);

    useEffect(() => {
        if (undoSecondsLeft === null) return undefined;
        const timer = setInterval(() => {
            setUndoSecondsLeft((n) => (n === null ? null : Math.max(0, n - 1)));
        }, 1000);
        return () => clearInterval(timer);
    }, [undoSecondsLeft === null]); // eslint-disable-line react-hooks/exhaustive-deps

    const muteMic = useCallback(
        (muted: boolean) => {
            recorder?.muteMic(muted);
            patch({ micMuted: muted });
        },
        [recorder, patch],
    );

    /**
     * MS25. Accept a chip's offer.
     *
     * An id goes to the recorder, never the chip: the server offered it and still has it, so
     * what runs is what was shown rather than whatever this page currently holds. The chip is
     * marked pending immediately, because the round trip goes to a tool and a button that
     * looks unpressed for two seconds gets pressed twice.
     */
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

    /** Local, and not a deletion: one reader is not interested, which is not a fact about the
     *  meeting. Nothing is sent and the record is untouched. */
    const dismissChipById = useCallback((id: string) => {
        setView((current) => ({ ...current, chips: dismissChip(current.chips, id) }));
    }, []);

    useEffect(
        () => () => {
            if (undoTimer.current) clearTimeout(undoTimer.current);
            if (tick.current) clearInterval(tick.current);
        },
        [],
    );

    return {
        view, start, stop, undo, muteMic, acceptChip, dismissChip: dismissChipById,
        undoSecondsLeft, setPhase: (p: Phase) => patch({ phase: p }),
    };
}

export default useMeetingSense;
