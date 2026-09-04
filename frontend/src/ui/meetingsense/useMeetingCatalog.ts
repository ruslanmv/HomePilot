/**
 * The meetings this install has, for History and the library (batch MS28, wave W10).
 *
 * One fetch, shared. Both surfaces need the same rows — History needs the conversation ids to
 * light its chip, the library needs everything — and two components each deciding to load them
 * is two round trips for one answer, on a panel the user opens and closes all day.
 *
 * **Silent when MeetingSense is off.** The status route is always mounted and always answers,
 * so this asks it rather than guessing from a failed request: an install with the feature off
 * gets an empty list and History renders exactly as it always has, with no chip and no error.
 * A network failure lands in the same place, because a History panel that shows a red banner
 * because an optional feature's endpoint was slow has made the user's problem worse.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { meetingConversations, type Meeting } from './catalog';

export interface UseMeetingCatalogOptions {
    /** Injected in tests; defaults to `fetch`. */
    fetcher?: typeof fetch;
    /** Only load when the panel is actually open. */
    enabled?: boolean;
    base?: string;
}

export function useMeetingCatalog({
    fetcher, enabled = true, base = '',
}: UseMeetingCatalogOptions = {}) {
    const [meetings, setMeetings] = useState<Meeting[]>([]);
    const [loaded, setLoaded] = useState(false);

    const load = useCallback(async () => {
        const get = fetcher || (typeof fetch === 'function' ? fetch : null);
        if (!get) return;
        try {
            const status = await get(`${base}/v1/meetingsense/status`);
            const flags = status && status.ok ? await status.json() : null;
            if (!flags?.enabled) {
                // Not an error and not worth reporting: the feature is off, so there are no
                // meetings, so History is History.
                setMeetings([]);
                setLoaded(true);
                return;
            }
            const res = await get(`${base}/v1/meetingsense/meetings?limit=100`);
            const body = res && res.ok ? await res.json() : null;
            setMeetings(Array.isArray(body?.meetings) ? body.meetings : []);
        } catch {
            // An optional feature's endpoint being slow is not the user's problem to see.
            setMeetings([]);
        } finally {
            setLoaded(true);
        }
    }, [fetcher, base]);

    useEffect(() => {
        if (!enabled) return;
        void load();
    }, [enabled, load]);

    const meetingIds = useMemo(() => meetingConversations(meetings), [meetings]);
    return { meetings, meetingIds, loaded, reload: load };
}

export default useMeetingCatalog;
