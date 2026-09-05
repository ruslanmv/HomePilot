/**
 * The ended meeting's record (batch MS33, wave W13).
 *
 * One fetch of `GET /v1/meetingsense/{id}`, which is the route MS16 wrote so a card could
 * "rebuild itself … reopened days later". The ended state is exactly that case arriving one
 * second after the meeting rather than three days later, so it uses the same door.
 *
 * **Notes arrive late on purpose.** The final window is flushed when the meeting stops, so a
 * fetch fired the instant `phase` becomes `ended` can beat the summary into existence. Rather
 * than show an empty payoff and leave it empty, this retries a few times while the record has
 * no notes yet — bounded, then stops. A spinner that never ends is worse than a card that
 * says the summary is still being written.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { hasPayoff, notesBody, type MeetingRecord } from './meetingRecord';

/** How many times to look again when the record arrives without notes, and how far apart. */
export const NOTES_RETRIES = 4;
export const NOTES_RETRY_MS = 1500;

export interface UseMeetingRecordOptions {
    meetingId: string | null;
    /** Only fetch once there is something to fetch. */
    enabled?: boolean;
    /** Injected in tests; defaults to `fetch`. */
    fetcher?: typeof fetch;
    base?: string;
    /** Injected in tests, so a retry schedule does not cost the suite six seconds. */
    delayMs?: number;
}

export interface MeetingRecordState {
    record: MeetingRecord | null;
    loading: boolean;
    error: string | null;
    /** True while the record exists but its summary has not been written yet. */
    pendingNotes: boolean;
    reload: () => void;
}

export function useMeetingRecord({
    meetingId, enabled = true, fetcher, base = '', delayMs = NOTES_RETRY_MS,
}: UseMeetingRecordOptions): MeetingRecordState {
    const [record, setRecord] = useState<MeetingRecord | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [pendingNotes, setPendingNotes] = useState(false);
    const [nonce, setNonce] = useState(0);
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

    const reload = useCallback(() => setNonce((n) => n + 1), []);

    useEffect(() => {
        if (!enabled || !meetingId) {
            setRecord(null);
            setError(null);
            setPendingNotes(false);
            return undefined;
        }
        let cancelled = false;
        let attempt = 0;
        const get = fetcher || (typeof fetch === 'function' ? fetch : null);
        if (!get) return undefined;

        const load = async () => {
            if (cancelled) return;
            setLoading(true);
            try {
                const res = await get(`${base}/v1/meetingsense/${encodeURIComponent(meetingId)}`);
                if (cancelled) return;
                if (!res.ok) {
                    setError('This meeting could not be loaded.');
                    setPendingNotes(false);
                    return;
                }
                const body = (await res.json()) as MeetingRecord;
                if (cancelled) return;
                setRecord(body);
                setError(null);
                // The record is here; the summary may not be. Look again a few times, then
                // accept that this meeting has no notes — some genuinely do not, and a
                // meeting of pure silence should not spin forever.
                const ready = hasPayoff(notesBody(body?.notes));
                if (!ready && attempt < NOTES_RETRIES) {
                    attempt += 1;
                    setPendingNotes(true);
                    timer.current = setTimeout(() => void load(), delayMs);
                } else {
                    setPendingNotes(false);
                }
            } catch {
                if (!cancelled) {
                    setError('This meeting could not be loaded.');
                    setPendingNotes(false);
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };

        void load();
        return () => {
            cancelled = true;
            if (timer.current) clearTimeout(timer.current);
        };
    }, [meetingId, enabled, fetcher, base, delayMs, nonce]);

    return { record, loading, error, pendingNotes, reload };
}

export default useMeetingRecord;
