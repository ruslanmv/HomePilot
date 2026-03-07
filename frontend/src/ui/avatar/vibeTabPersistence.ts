/**
 * vibeTabPersistence — Persist the Standard / Spicy tab selection.
 *
 * Stores `homepilot_vibe_tab` in localStorage so the user's choice
 * survives page refreshes. Falls back to 'standard' if NSFW is off.
 */

const STORAGE_KEY = 'homepilot_vibe_tab'

export type VibeTab = 'standard' | 'spicy'

/** Read persisted tab, falling back to 'standard'. */
export function loadVibeTab(): VibeTab {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'spicy') return 'spicy'
  } catch { /* ignore */ }
  return 'standard'
}

/** Persist the tab choice. */
export function saveVibeTab(tab: VibeTab): void {
  try {
    localStorage.setItem(STORAGE_KEY, tab)
  } catch { /* ignore */ }
}
