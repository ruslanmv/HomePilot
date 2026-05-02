/**
 * vibeTabPersistence — Persist the Standard / Spicy tab selection.
 *
 * Stores `homepilot_vibe_tab` in localStorage so the user's choice
 * survives page refreshes. Falls back to 'standard' if NSFW is off.
 */
const STORAGE_KEY = 'homepilot_vibe_tab';
/** Read persisted tab, falling back to 'standard'. */
export function loadVibeTab() {
    try {
        const v = localStorage.getItem(STORAGE_KEY);
        if (v === 'spicy')
            return 'spicy';
    }
    catch { /* ignore */ }
    return 'standard';
}
/** Persist the tab choice. */
export function saveVibeTab(tab) {
    try {
        localStorage.setItem(STORAGE_KEY, tab);
    }
    catch { /* ignore */ }
}
