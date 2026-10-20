/**
 * Quick record — the one-click way to record a call (Slack, Zoom, Teams, a browser call).
 *
 * The full Start-a-meeting wizard (Setup, Recording, Assistant, Summary) stays as it is behind
 * "More options". This module holds the three choices the quick view asks for, remembered on
 * this computer so the second call is a single click, and the one sentence that tells people
 * what the browser's share picker is about to ask them.
 */

export interface QuickRecordPrefs {
    /** The other people on the call: tab or system audio from the browser's share picker. */
    audio: boolean;
    /** What you say. */
    mic: boolean;
    /** Key frames of a shared screen. Optional, off by default. */
    screen: boolean;
}

export const QUICK_RECORD_KEY = 'homepilot_meeting_quick_v1';
export const QUICK_RECORD_DEFAULTS: QuickRecordPrefs = { audio: true, mic: true, screen: false };

export function readQuickPrefs(storage?: Storage): QuickRecordPrefs {
    try {
        const raw = (storage ?? window.localStorage).getItem(QUICK_RECORD_KEY);
        if (!raw) return { ...QUICK_RECORD_DEFAULTS };
        const parsed = JSON.parse(raw) || {};
        return {
            audio: parsed.audio !== false,
            mic: parsed.mic !== false,
            screen: parsed.screen === true,
        };
    } catch {
        return { ...QUICK_RECORD_DEFAULTS };
    }
}

export function writeQuickPrefs(prefs: QuickRecordPrefs, storage?: Storage): void {
    try {
        (storage ?? window.localStorage).setItem(QUICK_RECORD_KEY, JSON.stringify(prefs));
    } catch {
        /* private mode or blocked storage: the defaults come back next time */
    }
}

export function nothingSelected(prefs: QuickRecordPrefs): boolean {
    return !prefs.audio && !prefs.mic && !prefs.screen;
}

/** What happens right after pressing Start, in the words of the picker the browser shows. */
export function shareHint(prefs: QuickRecordPrefs): string {
    if (prefs.audio) {
        return 'Your browser asks what to share next. For the Slack, Zoom or Teams app, choose '
            + '“Entire screen” and switch on “Share system audio”. For a call in a browser tab, '
            + 'choose that tab and keep “Share tab audio” on.';
    }
    if (prefs.screen) return 'Your browser asks which screen or window to share next.';
    if (prefs.mic) return 'Only your microphone is recorded. Turn on Call audio to hear the other people.';
    return 'Choose at least one thing to record.';
}
