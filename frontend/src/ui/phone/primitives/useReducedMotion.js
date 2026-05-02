/**
 * useReducedMotion — subscribe to the OS-level
 * ``prefers-reduced-motion`` preference.
 *
 * Every animated component under ``phone/`` reads this hook so a
 * single user preference disables animation app-wide. The hook also
 * tracks runtime changes (macOS + iOS let users toggle the setting
 * without reloading), so an animation doesn't silently persist when
 * the user enables the preference mid-call.
 *
 * SSR-safe: returns ``false`` when ``window`` is undefined. Callers
 * don't need to null-guard the DOM.
 */
import { useEffect, useState } from 'react';
const QUERY = '(prefers-reduced-motion: reduce)';
export function useReducedMotion() {
    const [reduced, setReduced] = useState(() => {
        if (typeof window === 'undefined')
            return false;
        try {
            return window.matchMedia(QUERY).matches;
        }
        catch {
            return false;
        }
    });
    useEffect(() => {
        if (typeof window === 'undefined')
            return;
        let mq;
        try {
            mq = window.matchMedia(QUERY);
        }
        catch {
            return;
        }
        const onChange = (e) => setReduced(e.matches);
        // Both APIs exist in the wild; prefer addEventListener on modern
        // browsers, fall back to the deprecated addListener for older ones
        // (Safari < 14). Same pattern at teardown.
        if ('addEventListener' in mq) {
            mq.addEventListener('change', onChange);
            return () => mq.removeEventListener('change', onChange);
        }
        const legacy = mq;
        legacy.addListener?.(onChange);
        return () => legacy.removeListener?.(onChange);
    }, []);
    return reduced;
}
