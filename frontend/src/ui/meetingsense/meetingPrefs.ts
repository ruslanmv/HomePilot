/**
 * Meeting preferences — Settings → Meetings.
 *
 * Saved on this computer and applied immediately, the same way the Audio & Video and Motion
 * settings are: there is nothing to "Save", and the next meeting uses them. The microphone
 * and its clean-up switches are deliberately *not* here — they are the one media preference
 * shared with calls and voice (`media/mediaPreferences.ts`), and the Meetings tab edits that
 * same record rather than keeping a second microphone that could disagree with the first.
 *
 * `homepilot_meeting_prefs_v1` and the `language` field are also read by the classic recorder
 * script (`public/js/homepilot-meetingsense.js`, `meetingLanguage()`), which cannot import
 * this module.
 */

export type SummaryStyle = 'minutes' | 'email' | 'notes' | 'brief' | 'actions';
export type SummaryLength = 'short' | 'standard' | 'detailed';

export interface MeetingPrefs {
    /** Spoken language: 'auto' (lock to the first confident detection), 'multi', or a code. */
    language: string;
    /** Rolling notes and highlights while the meeting runs. Uses the chat model. */
    liveNotes: boolean;
    /** Default shape of the end-of-meeting document. */
    summaryStyle: SummaryStyle;
    summaryLength: SummaryLength;
    /** The language the summary is written in; '' = the meeting's own. */
    summaryLanguage: string;
}

export const MEETING_PREFS_KEY = 'homepilot_meeting_prefs_v1';
export const MEETING_PREFS_EVENT = 'homepilot:meeting-prefs-changed';

export const MEETING_PREFS_DEFAULTS: MeetingPrefs = {
    language: 'auto',
    liveNotes: true,
    summaryStyle: 'minutes',
    summaryLength: 'standard',
    summaryLanguage: '',
};

/** Languages offered for speech. Whisper knows ~100; these are the ones people pick. */
export const SPOKEN_LANGUAGES: Array<{ id: string; label: string }> = [
    { id: 'auto', label: 'Detect automatically' },
    { id: 'en', label: 'English' },
    { id: 'es', label: 'Spanish' },
    { id: 'it', label: 'Italian' },
    { id: 'fr', label: 'French' },
    { id: 'de', label: 'German' },
    { id: 'pt', label: 'Portuguese' },
    { id: 'nl', label: 'Dutch' },
    { id: 'da', label: 'Danish' },
    { id: 'sv', label: 'Swedish' },
    { id: 'no', label: 'Norwegian' },
    { id: 'pl', label: 'Polish' },
    { id: 'ru', label: 'Russian' },
    { id: 'uk', label: 'Ukrainian' },
    { id: 'tr', label: 'Turkish' },
    { id: 'ar', label: 'Arabic' },
    { id: 'hi', label: 'Hindi' },
    { id: 'zh', label: 'Chinese' },
    { id: 'ja', label: 'Japanese' },
    { id: 'ko', label: 'Korean' },
    { id: 'multi', label: 'Several languages (detect every sentence)' },
];

const STYLES: SummaryStyle[] = ['minutes', 'email', 'notes', 'brief', 'actions'];
const LENGTHS: SummaryLength[] = ['short', 'standard', 'detailed'];

function storage(given?: Storage): Storage | null {
    if (given) return given;
    try {
        return typeof window !== 'undefined' ? window.localStorage : null;
    } catch {
        return null;
    }
}

function sanitize(raw: unknown): MeetingPrefs {
    const value = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
    const language = typeof value.language === 'string' && /^(auto|multi|[a-z]{2,3})$/.test(value.language)
        ? value.language : MEETING_PREFS_DEFAULTS.language;
    return {
        language,
        liveNotes: value.liveNotes !== false,
        summaryStyle: STYLES.includes(value.summaryStyle as SummaryStyle)
            ? (value.summaryStyle as SummaryStyle) : MEETING_PREFS_DEFAULTS.summaryStyle,
        summaryLength: LENGTHS.includes(value.summaryLength as SummaryLength)
            ? (value.summaryLength as SummaryLength) : MEETING_PREFS_DEFAULTS.summaryLength,
        summaryLanguage: typeof value.summaryLanguage === 'string' ? value.summaryLanguage.slice(0, 40) : '',
    };
}

export function readMeetingPrefs(given?: Storage): MeetingPrefs {
    try {
        const raw = storage(given)?.getItem(MEETING_PREFS_KEY);
        return sanitize(raw ? JSON.parse(raw) : null);
    } catch {
        return { ...MEETING_PREFS_DEFAULTS };
    }
}

export function writeMeetingPrefs(next: Partial<MeetingPrefs>, given?: Storage): MeetingPrefs {
    const merged = sanitize({ ...readMeetingPrefs(given), ...next });
    try {
        storage(given)?.setItem(MEETING_PREFS_KEY, JSON.stringify(merged));
    } catch {
        /* private mode or blocked storage: the defaults come back next time */
    }
    try {
        window.dispatchEvent(new CustomEvent(MEETING_PREFS_EVENT, { detail: merged }));
    } catch {
        /* no window (tests without jsdom) */
    }
    return merged;
}

export function subscribeMeetingPrefs(listener: (prefs: MeetingPrefs) => void): () => void {
    const onChange = () => listener(readMeetingPrefs());
    const onStorage = (event: StorageEvent) => {
        if (event.key === MEETING_PREFS_KEY) onChange();
    };
    window.addEventListener(MEETING_PREFS_EVENT, onChange);
    window.addEventListener('storage', onStorage);
    return () => {
        window.removeEventListener(MEETING_PREFS_EVENT, onChange);
        window.removeEventListener('storage', onStorage);
    };
}
